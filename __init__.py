# -*- coding: utf-8 -*-
bl_info = {
    "name": "3DCG Tutorial Simulator",
    "blender": (4, 2, 0),
    "version": (0, 8, 3),
    "author": "Daichi",
    "description": "Interactive 3D learning simulation for Blender (Ch1-6 tutorials + per-participant JSONL logging + CSV export + DIR_PATH w/ safe buttons; Ch6 Stage1 only w/ auto camera+sun on setup)",
    "category": "Education",
    "support": "COMMUNITY",
}

import bpy
import bmesh
import math
import time
import json
import os
import csv
import subprocess
import sys
from mathutils import Vector
from bpy.types import Operator, Panel, PropertyGroup
from bpy.props import (
    IntProperty,
    BoolProperty,
    FloatVectorProperty,
    FloatProperty,
    CollectionProperty,
    StringProperty,
)

# =====================================================
# VERTEX POSITION STORAGE
# =====================================================

class VertexPos(PropertyGroup):
    """Store vertex position for comparison"""
    co: FloatVectorProperty(size=3)

# =====================================================
# RESEARCH DATA STORAGE (SESSION-IN-MEMORY)
# =====================================================

class StageRun(PropertyGroup):
    chapter: IntProperty(default=1, min=1, max=6)
    stage: IntProperty(default=1, min=1, max=10)

    completed: BoolProperty(default=False)
    last_reason: StringProperty(default="")
    last_message: StringProperty(default="")

    failed_count: IntProperty(default=0, min=0)
    stalled_seconds: FloatProperty(default=0.0, min=0.0)

    started_at: FloatProperty(default=0.0)
    ended_at: FloatProperty(default=0.0)

# =====================================================
# STAGE MANAGER
# =====================================================

class StageManager:
    # -----------------------------
    # Time/helpers
    # -----------------------------
    @staticmethod
    def _now():
        return time.time()

    @staticmethod
    def degrees_to_radians_xyz(deg_xyz):
        return tuple(math.radians(v) for v in deg_xyz)

    @staticmethod
    def vec_dist(a, b):
        return math.sqrt(sum((a[i] - b[i]) ** 2 for i in range(3)))

    @staticmethod
    def rot_dist_deg(a_rad, b_rad):
        """Rough per-axis rotation distance in degrees (Euler)."""
        try:
            a_deg = tuple(math.degrees(v) for v in a_rad)
            b_deg = tuple(math.degrees(v) for v in b_rad)
            return sum(abs(a_deg[i] - b_deg[i]) for i in range(3))
        except Exception:
            return 9999.0

    # -----------------------------
    # Windows-safe log dir helpers
    # -----------------------------
    @staticmethod
    def default_log_dir() -> str:
        if os.name == "nt":
            return r"C:\temp\tutorial_logs\\"
        return os.path.join("~", "tutorial_logs") + os.sep

    @staticmethod
    def ensure_dir_exists(path: str) -> str:
        abs_path = bpy.path.abspath(path)
        os.makedirs(abs_path, exist_ok=True)
        return abs_path

    @staticmethod
    def open_folder_in_os(path: str):
        abs_path = StageManager.ensure_dir_exists(path)
        if os.name == "nt":
            os.startfile(abs_path)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", abs_path])
        else:
            subprocess.Popen(["xdg-open", abs_path])

    # -----------------------------
    # Participant log (JSONL)
    # -----------------------------
    @staticmethod
    def _safe_participant_id(pid: str) -> str:
        pid = (pid or "").strip()
        if not pid:
            return ""
        allowed = []
        for ch in pid:
            if ch.isalnum() or ch in ("-", "_"):
                allowed.append(ch)
            else:
                allowed.append("_")
        return "".join(allowed)

    @staticmethod
    def get_stall_seconds(context) -> float:
        props = context.scene.tutorial_props
        if props.stage_start_time <= 0.0:
            return 0.0
        return max(0.0, StageManager._now() - props.stage_start_time)

    @staticmethod
    def ensure_participant_log_file(context) -> bool:
        props = context.scene.tutorial_props
        pid = StageManager._safe_participant_id(props.participant_id)

        if not pid:
            props.participant_log_error = "参加者IDが未入力です"
            return False

        if not (props.log_dir or "").strip():
            props.log_dir = StageManager.default_log_dir()

        try:
            dir_abs = StageManager.ensure_dir_exists(props.log_dir)
        except Exception as e:
            props.participant_log_error = f"ログ保存フォルダ作成に失敗: {e}"
            return False

        if props.participant_log_path:
            try:
                existing = bpy.path.abspath(props.participant_log_path)
                if os.path.isfile(existing):
                    props.participant_log_error = ""
                    return True
            except Exception:
                pass

        ts = time.strftime("%Y%m%d_%H%M%S", time.localtime(StageManager._now()))
        log_path = os.path.join(dir_abs, f"{pid}_{ts}.jsonl")

        try:
            with open(log_path, "a", encoding="utf-8") as f:
                # SAFE: bl_info may not exist depending on load/reload context
                _addon_info = globals().get("bl_info", {}) or {}
                f.write(json.dumps({
                    "t": StageManager._now(),
                    "participant_id": pid,
                    "event": "session_start",
                    "blender_version": ".".join(map(str, bpy.app.version)),
                    "addon_version": ".".join(map(str, _addon_info.get("version", (0, 0, 0)))),
                }, ensure_ascii=False) + "\n")

            props.participant_log_path = log_path
            props.participant_log_error = ""
            return True
        except Exception as e:
            props.participant_log_error = f"ログファイル作成に失敗: {type(e).__name__}: {e}"
            return False

    @staticmethod
    def append_participant_event(context, event: dict):
        props = context.scene.tutorial_props
        if not props.enable_participant_logging:
            return
        if not StageManager.ensure_participant_log_file(context):
            return
        try:
            with open(bpy.path.abspath(props.participant_log_path), "a", encoding="utf-8") as f:
                f.write(json.dumps(event, ensure_ascii=False) + "\n")
        except Exception as e:
            props.participant_log_error = f"ログ書き込みに失敗: {type(e).__name__}: {e}"

    @staticmethod
    def log_setup_event(context):
        props = context.scene.tutorial_props
        pid = StageManager._safe_participant_id(props.participant_id)
        StageManager.append_participant_event(context, {
            "t": StageManager._now(),
            "participant_id": pid,
            "event": "setup",
            "chapter": props.current_chapter,
            "stage": props.current_stage,
        })

    @staticmethod
    def log_validate_event(context, ok: bool, reason: str, message: str):
        props = context.scene.tutorial_props
        pid = StageManager._safe_participant_id(props.participant_id)
        StageManager.append_participant_event(context, {
            "t": StageManager._now(),
            "participant_id": pid,
            "event": "validate",
            "chapter": props.current_chapter,
            "stage": props.current_stage,
            "ok": bool(ok),
            "reason": reason or "",
            "message": message or "",
            "fail_count": int(props.failed_validate_count),
            "stall_s": float(StageManager.get_stall_seconds(context)),
        })

    @staticmethod
    def log_finalize_event(context, completed: bool, stalled_seconds: float):
        props = context.scene.tutorial_props
        pid = StageManager._safe_participant_id(props.participant_id)
        StageManager.append_participant_event(context, {
            "t": StageManager._now(),
            "participant_id": pid,
            "event": "finalize",
            "chapter": props.current_chapter,
            "stage": props.current_stage,
            "completed": bool(completed),
            "failed_count": int(props.failed_validate_count),
            "stalled_seconds": float(stalled_seconds),
            "last_reason": props.last_reason or "",
            "last_message": props.last_message or "",
            "stage_started_at": float(props.stage_start_time),
        })

    # -----------------------------
    # Research metrics (in-memory) + finalize
    # -----------------------------
    @staticmethod
    def finalize_current_run(context, completed: bool):
        props = context.scene.tutorial_props
        if props.stage_start_time <= 0.0:
            return

        now = StageManager._now()
        stalled = max(0.0, now - props.stage_start_time)

        r = props.stage_runs.add()
        r.chapter = props.current_chapter
        r.stage = props.current_stage
        r.completed = bool(completed)
        r.failed_count = int(props.failed_validate_count)
        r.stalled_seconds = float(stalled)
        r.last_reason = props.last_reason or ""
        r.last_message = props.last_message or ""
        r.started_at = float(props.stage_start_time)
        r.ended_at = float(now)

        MAX_RUNS = 500
        if len(props.stage_runs) > MAX_RUNS:
            for _ in range(len(props.stage_runs) - MAX_RUNS):
                props.stage_runs.remove(0)

        StageManager.log_finalize_event(context, completed=completed, stalled_seconds=stalled)

    # -----------------------------
    # Chapter 6: camera + sun + render helper + cleanup
    # -----------------------------
    @staticmethod
    def file_exists_nonempty(path: str) -> bool:
        try:
            return os.path.isfile(path) and os.path.getsize(path) > 0
        except Exception:
            return False

    @staticmethod
    def ensure_camera_for_ch6_stage1(location=(10.0, -4.0, 4.5), rotation_deg=(63.0, 0.0, 66.0)):
        """Create or replace the scene camera for Chapter 6 Stage 1."""
        for obj in list(bpy.data.objects):
            if obj.type == 'CAMERA':
                bpy.data.objects.remove(obj, do_unlink=True)

        cam_data = bpy.data.cameras.new(name="Ch6_Camera")
        cam_obj = bpy.data.objects.new(name="Ch6_Camera", object_data=cam_data)
        bpy.context.collection.objects.link(cam_obj)
        cam_obj.location = location
        cam_obj.rotation_euler = tuple(math.radians(v) for v in rotation_deg)
        bpy.context.scene.camera = cam_obj
        return cam_obj

    @staticmethod
    def delete_all_lights():
        for obj in list(bpy.data.objects):
            if obj.type == 'LIGHT':
                bpy.data.objects.remove(obj, do_unlink=True)

    @staticmethod
    def create_sun_light(
        name="Ch6_Sun",
        location=(10.0, -4.0, 4.5),
        rotation_deg=(63.0, 0.0, 66.0),
        energy=1000.0,
    ):
        light_data = bpy.data.lights.new(name=name, type='SUN')
        light_data.energy = float(energy)

        light_obj = bpy.data.objects.new(name=name, object_data=light_data)
        bpy.context.collection.objects.link(light_obj)

        light_obj.location = location
        light_obj.rotation_euler = tuple(math.radians(v) for v in rotation_deg)
        light_obj.hide_viewport = False
        light_obj.hide_render = False
        return light_obj

    @staticmethod
    def ensure_sun_for_ch6_stage1(
        location=(10.0, -4.0, 4.5),
        rotation_deg=(63.0, 0.0, 66.0),
        energy=1000.0,
    ):
        StageManager.delete_all_lights()
        return StageManager.create_sun_light(
            name="Ch6_Sun",
            location=location,
            rotation_deg=rotation_deg,
            energy=energy,
        )

    @staticmethod
    def turn_off_scene_camera_and_lights():
        """End-of-session cleanup (do not delete)."""
        scene = bpy.context.scene
        scene.camera = None
        for obj in bpy.data.objects:
            if obj.type == 'LIGHT':
                obj.hide_viewport = True
                obj.hide_render = True

    # -----------------------------
    # Existing helpers for chapters 1-5
    # -----------------------------
    @staticmethod
    def open_shader_editor_at_bottom():
        try:
            context = bpy.context
            for area in context.screen.areas:
                if area.type == 'NODE_EDITOR':
                    return True

            view_area = None
            for area in context.screen.areas:
                if area.type == 'VIEW_3D':
                    view_area = area
                    break
            if not view_area:
                return False

            old_areas = set(context.screen.areas)
            override = {"window": context.window, "screen": context.screen, "area": view_area, "region": view_area.regions[-1]}
            bpy.ops.screen.area_split(override, direction='HORIZONTAL', factor=0.7)

            new_area = None
            for area in context.screen.areas:
                if area not in old_areas:
                    new_area = area
                    break
            if not new_area:
                return False

            new_area.type = 'NODE_EDITOR'
            new_area.spaces.active.tree_type = 'ShaderNodeTree'
            return True
        except Exception:
            return False

    @staticmethod
    def find_cube():
        for obj in bpy.data.objects:
            if obj.type == 'MESH' and obj.name == "Cube":
                return obj
        return None

    @staticmethod
    def find_sphere():
        for obj in bpy.data.objects:
            if obj.type == 'MESH' and obj.name == "Sphere":
                return obj
        return None

    @staticmethod
    def get_view3d_space(context):
        for area in context.screen.areas:
            if area.type == 'VIEW_3D':
                for space in area.spaces:
                    if space.type == 'VIEW_3D':
                        return space
        return None

    @staticmethod
    def get_bm(obj):
        if not obj or obj.type != 'MESH':
            return None
        if bpy.context.mode != 'EDIT_MESH':
            return None
        return bmesh.from_edit_mesh(obj.data)

    @staticmethod
    def get_mesh_select_mode(context):
        try:
            ts = context.tool_settings
            mode = getattr(ts, "mesh_select_mode", None) if ts else None
            return tuple(mode) if mode else (False, False, False)
        except Exception:
            return (False, False, False)

    @staticmethod
    def is_in_sculpt_mode():
        return bpy.context.mode == 'SCULPT'

    @staticmethod
    def get_current_brush_name():
        try:
            s = bpy.context.tool_settings.sculpt
            return s.brush.name if s and s.brush else None
        except Exception:
            return None

    @staticmethod
    def is_brush_type_selected(brush_type_name):
        bn = StageManager.get_current_brush_name()
        return bool(bn and brush_type_name in bn)

    @staticmethod
    def get_vertex_deformation_amount(sphere, initial_positions):
        """Crash-safe deformation detection."""
        try:
            if not sphere or not sphere.data or not sphere.data.vertices:
                return 0, 0.0
            if initial_positions is None:
                return 0, 0.0

            moved = 0
            total = 0.0
            compare_count = min(len(sphere.data.vertices), len(initial_positions))

            for i in range(compare_count):
                try:
                    v = sphere.data.vertices[i]
                    init = Vector(initial_positions[i].co)
                    dist = (v.co - init).length
                    if dist > 0.001:
                        moved += 1
                        total += dist
                except Exception:
                    continue

            return moved, total
        except Exception:
            return 0, 0.0

    @staticmethod
    def get_active_material(obj):
        if not obj or not obj.material_slots:
            return None
        return obj.active_material

    @staticmethod
    def get_principled_bsdf(material):
        if not material or not material.use_nodes:
            return None
        for node in material.node_tree.nodes:
            if node.type == 'BSDF_PRINCIPLED':
                return node
        return None

    @staticmethod
    def check_image_texture_node_exists(obj):
        mat = StageManager.get_active_material(obj)
        if not mat or not mat.use_nodes:
            return False
        return any(n.type == 'TEX_IMAGE' and n.image for n in mat.node_tree.nodes)

    @staticmethod
    def check_correct_node_link(obj):
        mat = StageManager.get_active_material(obj)
        if not mat or not mat.use_nodes:
            return False

        tex = None
        bsdf = None
        for n in mat.node_tree.nodes:
            if n.type == 'TEX_IMAGE':
                tex = n
            if n.type == 'BSDF_PRINCIPLED':
                bsdf = n
        if not tex or not bsdf:
            return False

        for link in mat.node_tree.links:
            if link.from_node == tex and link.to_node == bsdf:
                if link.from_socket.name == 'Color' and link.to_socket.name == 'Base Color':
                    return True
        return False

    # -----------------------------
    # UI stage descriptions
    # -----------------------------
    @staticmethod
    def get_stage_info(chapter_num, stage_num):
        if chapter_num == 6:
            return {
                "title": "第6章: 最終制作",
                "name": "ステージ1: 自由制作→レンダー保存（のみ）",
                "description": "自由に作品を作って、Render Result から画像を保存してください",
                "details": "セットアップ時にカメラとSunライトを自動生成します。\n"
                           "カメラ位置: X=10m, Y=-4m, Z=4.5m\n"
                           "カメラ回転: X=63°, Y=0°, Z=66°\n"
                           "Sun: Energy=1000\n\n"
                           "F12でレンダー → Render Result で Image > Save As...\n"
                           "（補助ボタンで自動保存も可能）",
            }

        if chapter_num == 1:
            stages = {
                1: {"title": "第1章: 基本操作", "name": "ステージ1: キューブを選択",
                    "description": "キューブを選択してください", "details": "1. オブジェクトを右クリックしよう"},
                2: {"title": "第1章: 基本操作", "name": "ステージ2: キューブを移動",
                    "description": "X軸方向に+2移動", "details": "2. Gキー → Xキー → 2 → Enter"},
                3: {"title": "第1章: 基本操作", "name": "ステージ3: キューブを回転",
                    "description": "X軸周りに45度回転", "details": "3. Rキー → Xキー → 45 → Enter"},
                4: {"title": "第1章: 基本操作", "name": "ステージ4: スケール変更",
                    "description": "サイズを変更", "details": "4. Sキーでスケール → Enterで確定"},
            }
            return stages.get(stage_num, {})
        if chapter_num == 2:
            stages = {
                1: {"title": "第2章: ビュー操作", "name": "ステージ1: ビューを移動",
                    "description": "Shift + 中ボタンでパン"},
                2: {"title": "第2章: ビュー操作", "name": "ステージ2: ズーム",
                    "description": "中ボタンスクロール"},
                3: {"title": "第2章: ビュー操作", "name": "ステージ3: ビュー回転",
                    "description": "中ボタンドラッグ"},
                4: {"title": "第2章: ビュー操作", "name": "ステージ4: すべてマスター",
                    "description": "すべての操作を実行"},
            }
            return stages.get(stage_num, {})
        if chapter_num == 3:
            stages = {
                1: {"title": "第3章: モデリング基礎", "name": "ステージ1: エディットモード",
                    "description": "Tab キーで切り替え"},
                2: {"title": "第3章: モデリング基礎", "name": "ステージ2: 頂点選択",
                    "description": "3個以上の頂点を選択"},
                3: {"title": "第3章: モデリング基礎", "name": "ステージ3: エッジ選択",
                    "description": "エッジを選択"},
                4: {"title": "第3章: モデリング基礎", "name": "ステージ4: フェース選択",
                    "description": "フェースを選択"},
                5: {"title": "第3章: モデリング基礎", "name": "ステージ5: エクストルード",
                    "description": "E キーで押し出し"},
                6: {"title": "第3章: モデリング基礎", "name": "ステージ6: ループカット",
                    "description": "Ctrl+R でループカット"},
            }
            return stages.get(stage_num, {})
        if chapter_num == 4:
            stages = {
                1: {"title": "第4章: スカルプティング体験", "name": "ステージ1: スカルプトモード",
                    "description": "Sculpt Mode に入ってください"},
                2: {"title": "第4章: スカルプティング体験", "name": "ステージ2: Draw ブラシを使う",
                    "description": "Draw ブラシで球の表面を変形"},
                3: {"title": "第4章: スカルプティング体験", "name": "ステージ3: Smooth ブラシに切り替え",
                    "description": "Smooth ブラシを選択してください"},
                4: {"title": "第4章: スカルプティング体験", "name": "ステージ4: Grab ブラシに切り替え",
                    "description": "Grab ブラシを選択してください"},
            }
            return stages.get(stage_num, {})
        if chapter_num == 5:
            stages = {
                1: {"title": "第5章: マテリアルノード", "name": "ステージ1: マテリアル作成",
                    "description": "「新規」ボタンを押す"},
                2: {"title": "第5章: マテリアルノード", "name": "ステージ2: 色変更",
                    "description": "Base Color を変更"},
                3: {"title": "第5章: マテリアルノード", "name": "ステージ3: 画像テクスチャ追加",
                    "description": "追加 → 画像テクスチャで画像読み込み"},
                4: {"title": "第5章: マテリアルノード", "name": "ステージ4: ノード接続",
                    "description": "ImageTexture → BaseColor に接続"},
                5: {"title": "第5章: マテリアルノード", "name": "ステージ5: 質感調整",
                    "description": "Roughness または Metallic を変更"},
            }
            return stages.get(stage_num, {})
        return {}

    @staticmethod
    def apply_hint_escalation(hints, failed_validate_count: int):
        if not hints:
            return []
        if failed_validate_count <= 1:
            return hints[:1]
        if failed_validate_count == 2:
            return hints[:2]
        return hints[:3]

    # -----------------------------
    # Validation: Chapters 1-6 (Ch6 Stage1 only)
    # -----------------------------
    @staticmethod
    def validate_stage(context):
        props = context.scene.tutorial_props
        ch = props.current_chapter
        st = props.current_stage
        obj = context.active_object

        # ---- Chapter 1 ----
        if ch == 1:
            if st == 1:
                if obj and obj.name == "Cube":
                    return True, "✓ キューブが選択されました", "OK", []
                return False, "❌ キューブを選択してください", "NO_ACTIVE_CUBE", ["3Dビューで Cube をクリックして選択します"]
            if st == 2:
                if not obj or obj.name != "Cube":
                    return False, "❌ キューブなし", "NO_ACTIVE_CUBE", ["まず Cube を選択してください"]
                movement = obj.location.x - props.initial_position[0]
                if abs(movement - 2.0) < 0.1:
                    return True, "✓ +2移動しました", "OK", []
                return False, f"❌ 移動: {movement:.2f}", "TRANSFORM_NOT_MATCHED", ["G → X → 2 → Enter の順に入力します"]
            if st == 3:
                if not obj or obj.name != "Cube":
                    return False, "❌ キューブなし", "NO_ACTIVE_CUBE", ["まず Cube を選択してください"]
                rot = math.degrees(obj.rotation_euler.x) - math.degrees(props.initial_rotation[0])
                if abs(rot - 45.0) < 1.0:
                    return True, "✓ 45度回転しました", "OK", []
                return False, f"❌ 回転: {rot:.1f}°", "TRANSFORM_NOT_MATCHED", ["R → X → 45 → Enter の順に入力します"]
            if st == 4:
                if not obj or obj.name != "Cube":
                    return False, "❌ キューブなし", "NO_ACTIVE_CUBE", ["まず Cube を選択してください"]
                if abs(obj.scale.x - props.initial_scale[0]) > 0.01:
                    return True, "✓ スケール変更完了", "OK", []
                return False, "❌ スケール値を変更してください", "SCALE_NOT_CHANGED", ["S キーでスケール変更できます（Enterで確定）"]

        # ---- Chapter 2 ----
        if ch == 2:
            space = StageManager.get_view3d_space(context)
            if not space or not space.region_3d:
                return False, "❌ 3Dビューなし", "NO_VIEW3D", ["3Dビューがあるレイアウトに戻してください"]
            r3d = space.region_3d
            if st == 1:
                loc_diff = StageManager.vec_dist(tuple(r3d.view_location), tuple(props.initial_view_location))
                if loc_diff > 0.1:
                    return True, "✓ ビュー移動完了", "OK", []
                return False, "❌ ビューをパンしてください", "VIEW_NOT_MOVED", ["Shift + 中ボタンドラッグでパンします"]
            if st == 2:
                if abs(r3d.view_distance - props.initial_view_distance) > 0.5:
                    return True, "✓ ズーム完了", "OK", []
                return False, "❌ ズームしてください", "VIEW_NOT_ZOOMED", ["中ボタンスクロールでズームします"]
            if st == 3:
                loc_diff = StageManager.vec_dist(tuple(r3d.view_location), tuple(props.initial_view_location))
                dist_diff = abs(r3d.view_distance - props.initial_view_distance)
                if loc_diff > 0.01 or dist_diff > 0.01:
                    return True, "✓ ビュー回転完了", "OK", []
                return False, "❌ ビューを回転させてください", "VIEW_NOT_ROTATED", ["中ボタンドラッグで回転します（Shiftは押さない）"]
            if st == 4:
                loc_diff = StageManager.vec_dist(tuple(r3d.view_location), tuple(props.initial_view_location))
                dist_diff = abs(r3d.view_distance - props.initial_view_distance)
                if loc_diff > 0.1 and dist_diff > 0.5:
                    return True, "✓ すべてのビュー操作をマスターしました", "OK", []
                return False, "❌ パン + ズームを実行してください", "VIEW_NOT_COMPLETED", ["Shift+中ボタンでパン", "ホイールでズーム"]

        # ---- Chapter 3 ----
        if ch == 3:
            if st == 1:
                if obj and bpy.context.mode == 'EDIT_MESH':
                    return True, "✓ エディットモード突入", "OK", []
                return False, "❌ エディットモードに入ってください", "NOT_IN_EDIT_MODE", ["Cubeを選択→TabでEdit Mode"]

            bm = StageManager.get_bm(obj)
            if not bm:
                return False, "❌ エディットモード必須", "NOT_IN_EDIT_MODE", ["Cubeを選択→TabでEdit Mode"]

            if st == 2:
                if not StageManager.get_mesh_select_mode(context)[0]:
                    return False, "❌ 頂点選択モードに切り替えてください", "WRONG_SELECT_MODE", ["1キーで頂点選択モード"]
                sel_count = sum(1 for v in bm.verts if v.select)
                if sel_count >= 3:
                    return True, f"✓ 頂点選択: {sel_count}個", "OK", []
                return False, f"❌ 頂点を選択してください ({sel_count}個)", "NOT_ENOUGH_SELECTED", ["Shiftで複数選択", "3つ以上選択"]
            if st == 3:
                if not StageManager.get_mesh_select_mode(context)[1]:
                    return False, "❌ エッジ選択モードに切り替えてください", "WRONG_SELECT_MODE", ["2キーでエッジ選択モード"]
                if any(e.select for e in bm.edges):
                    return True, "✓ エッジ選択完了", "OK", []
                return False, "❌ エッジを選択してください", "NOTHING_SELECTED", ["エッジをクリックして選択"]
            if st == 4:
                if not StageManager.get_mesh_select_mode(context)[2]:
                    return False, "❌ フェース選択モードに切り替えてください", "WRONG_SELECT_MODE", ["3キーでフェース選択モード"]
                if any(f.select for f in bm.faces):
                    return True, "✓ フェース選択完了", "OK", []
                return False, "❌ フェースを選択してください", "NOTHING_SELECTED", ["面をクリックして選択"]
            if st == 5:
                if len(bm.faces) > props.initial_face_count:
                    return True, "✓ 押し出し完了", "OK", []
                return False, "❌ 面を押し出してください", "EXTRUDE_NOT_DETECTED", ["面を選択→E→Enter"]
            if st == 6:
                if len(bm.verts) > props.initial_vertex_count:
                    return True, "✓ ループカット完了", "OK", []
                return False, "❌ ループカットを追加してください", "LOOPCUT_NOT_DETECTED", ["Ctrl+R→クリック→クリック"]

        # ---- Chapter 4 ----
        if ch == 4:
            sphere = StageManager.find_sphere()
            if st == 1:
                if StageManager.is_in_sculpt_mode() and sphere:
                    return True, "✓ スカルプトモード入場", "OK", []
                return False, "❌ スカルプトモードに入ってください", "NOT_IN_SCULPT_MODE", ["セットアップ→Sculpt Mode"]
            if st == 2:
                if StageManager.is_in_sculpt_mode() and sphere:
                    moved, _ = StageManager.get_vertex_deformation_amount(sphere, props.initial_vertex_positions)
                    if moved > 5:
                        return True, "✓ Draw ブラシで変形しました", "OK", []
                    return False, "❌ Draw ブラシで変形してください", "SCULPT_NOT_DETECTED", ["Drawでドラッグ", "Fでサイズ調整"]
                return False, "❌ スカルプトモード必須", "NOT_IN_SCULPT_MODE", ["Sculpt Modeに切り替え"]
            if st == 3:
                if StageManager.is_in_sculpt_mode() and StageManager.is_brush_type_selected("Smooth"):
                    return True, "✓ Smooth ブラシを選択しました", "OK", []
                return False, "❌ Smooth ブラシを選択してください", "WRONG_BRUSH", ["Smoothを選択"]
            if st == 4:
                if StageManager.is_in_sculpt_mode() and StageManager.is_brush_type_selected("Grab"):
                    return True, "✓ Grab ブラシを選択しました", "OK", []
                return False, "❌ Grab ブラシを選択してください", "WRONG_BRUSH", ["Grabを選択"]

        # ---- Chapter 5 ----
        if ch == 5:
            if st == 1:
                if not obj:
                    return False, "❌ オブジェクトを選択してください", "NO_ACTIVE_OBJECT", ["オブジェクトを選択"]
                mat = StageManager.get_active_material(obj)
                if mat and mat.use_nodes:
                    return True, "✓ マテリアル作成完了", "OK", []
                return False, "❌ マテリアルを作成してください", "NO_MATERIAL", ["Materialで「新規」→Use Nodes"]
            if st == 2:
                if not obj:
                    return False, "❌ オブジェクトを選択してください", "NO_ACTIVE_OBJECT", ["オブジェクトを選択"]
                mat = StageManager.get_active_material(obj)
                bsdf = StageManager.get_principled_bsdf(mat) if mat else None
                if not bsdf:
                    return False, "❌ Principled BSDF が見つかりません", "NO_BSDF", ["Use NodesをON"]
                base_color = bsdf.inputs['Base Color'].default_value
                default = (1.0, 1.0, 1.0, 1.0)
                changed = any(abs(base_color[i] - default[i]) > 0.01 for i in range(4))
                if changed:
                    return True, "✓ Base Color を変更しました", "OK", []
                return False, "❌ Base Color を変更してください", "BASE_COLOR_NOT_CHANGED", ["Base Colorを変更"]
            if st == 3:
                if obj and StageManager.check_image_texture_node_exists(obj):
                    return True, "✓ 画像テクスチャをロードしました", "OK", []
                return False, "❌ 画像テクスチャをロードしてください", "NO_IMAGE_TEXTURE", ["画像テクスチャノード→Open"]
            if st == 4:
                if obj and StageManager.check_correct_node_link(obj):
                    return True, "✓ ノード接続完了", "OK", []
                return False, "❌ ノード接続してください", "NODE_LINK_INCORRECT", ["Image Color→Base Colorへ接続"]
            if st == 5:
                if not obj:
                    return False, "❌ オブジェクトを選択してください", "NO_ACTIVE_OBJECT", ["オブジェクトを選択"]
                mat = StageManager.get_active_material(obj)
                bsdf = StageManager.get_principled_bsdf(mat) if mat else None
                if not bsdf:
                    return False, "❌ Principled BSDF が見つかりません", "NO_BSDF", ["Use NodesをON"]
                roughness = bsdf.inputs['Roughness'].default_value
                metallic = bsdf.inputs['Metallic'].default_value
                if abs(roughness - 0.5) > 0.01 or abs(metallic - 0.0) > 0.01:
                    return True, "✓ 質感を変更しました", "OK", []
                return False, "❌ Roughness または Metallic を変更してください", "PBR_NOT_CHANGED", ["Roughness/Metallicを変更"]

        # ---- Chapter 6 (Stage 1 only) ----
        if ch == 6:
            if props.current_stage != 1:
                props.current_stage = 1

            saved = (props.final_render_saved_path or "").strip()
            if saved and StageManager.file_exists_nonempty(bpy.path.abspath(saved)):
                return True, f"✓ 保存OK: {os.path.basename(saved)}", "OK", []
            return False, "❌ まだ保存が検出できません", "RENDER_NOT_SAVED", [
                "F12 でレンダー → Render Result で Image > Save As...",
                "（補助:「補助: レンダーして保存（自動）」でもOK）",
            ]

        return False, "❌ 判定エラー", "UNKNOWN", ["セットアップして再試行"]

    @staticmethod
    def check_stage(context):
        try:
            ok, _message, _reason, _hints = StageManager.validate_stage(context)
            props = context.scene.tutorial_props
            if ok and not props.stage_complete:
                props.stage_complete = True
        except Exception:
            return

# =====================================================
# PROPERTIES
# =====================================================

class TUTORIAL_PG_Properties(PropertyGroup):
    current_chapter: IntProperty(default=1, min=1, max=6)
    current_stage: IntProperty(default=1, min=1, max=10)
    stage_complete: BoolProperty(default=False)
    monitoring_active: BoolProperty(default=False)

    # Chapter 1 initial transforms
    initial_position: FloatVectorProperty(default=(0.0, 0.0, 0.0), size=3)
    initial_rotation: FloatVectorProperty(default=(0.0, 0.0, 0.0), size=3)
    initial_scale: FloatVectorProperty(default=(1.0, 1.0, 1.0), size=3)

    # Chapter 2 view state
    initial_view_distance: FloatProperty(default=0.0)
    initial_view_location: FloatVectorProperty(default=(0.0, 0.0, 0.0), size=3)

    # Chapter 3 mesh counts
    initial_vertex_count: IntProperty(default=0)
    initial_edge_count: IntProperty(default=0)
    initial_face_count: IntProperty(default=0)

    # Chapter 4
    initial_vertex_positions: CollectionProperty(type=VertexPos)

    # Feedback
    failed_validate_count: IntProperty(default=0, min=0)
    stage_start_time: FloatProperty(default=0.0)
    last_result_ok: BoolProperty(default=True)
    last_reason: StringProperty(default="")
    last_message: StringProperty(default="")
    last_hints: StringProperty(default="")

    # Research summary
    stage_runs: CollectionProperty(type=StageRun)
    current_stall_seconds: FloatProperty(default=0.0, min=0.0)

    # Logging
    enable_participant_logging: BoolProperty(default=True)
    participant_id: StringProperty(name="参加者ID", default="")
    log_dir: StringProperty(
        name="ログ保存フォルダ",
        description="クリックでフォルダ選択（環境によってFile Browserが落ちる場合あり：下の安全ボタンを使用）",
        subtype='DIR_PATH',
        default=StageManager.default_log_dir(),
    )
    participant_log_path: StringProperty(default="")
    participant_log_error: StringProperty(default="")

    # Chapter 6
    final_render_saved_path: StringProperty(default="")

# =====================================================
# OPERATORS
# =====================================================

class TUTORIAL_OT_set_default_log_dir(Operator):
    bl_idname = "tutorial.set_default_log_dir"
    bl_label = "既定フォルダに設定"
    bl_description = "ログ保存フォルダを既定値に戻し、フォルダも作成します"

    def execute(self, context):
        props = context.scene.tutorial_props
        props.log_dir = StageManager.default_log_dir()
        try:
            StageManager.ensure_dir_exists(props.log_dir)
        except Exception as e:
            self.report({'ERROR'}, f"フォルダ作成に失敗: {e}")
            return {'CANCELLED'}
        self.report({'INFO'}, f"設定: {bpy.path.abspath(props.log_dir)}")
        return {'FINISHED'}

class TUTORIAL_OT_open_log_folder(Operator):
    bl_idname = "tutorial.open_log_folder"
    bl_label = "ログフォルダを開く"
    bl_description = "OSのファイルエクスプローラでログ保存フォルダを開きます（BlenderのFile Browserは使いません）"

    def execute(self, context):
        props = context.scene.tutorial_props
        try:
            StageManager.open_folder_in_os(props.log_dir or StageManager.default_log_dir())
        except Exception as e:
            self.report({'ERROR'}, f"フォルダを開けません: {e}")
            return {'CANCELLED'}
        return {'FINISHED'}

class TUTORIAL_OT_confirm_all_chapters(Operator):
    bl_idname = "tutorial.confirm_all_chapters"
    bl_label = "全チャプター確認"
    bl_description = "第1章〜第6章のステージ1を順番に判定し、OK/NGを一覧表示します（状態は元に戻します）"

    def execute(self, context):
        props = context.scene.tutorial_props
        original_ch = props.current_chapter
        original_st = props.current_stage

        results = []
        try:
            for ch in range(1, 7):
                props.current_chapter = ch
                props.current_stage = 1
                ok, message, reason, _hints = StageManager.validate_stage(context)
                results.append((ch, ok, reason, message))
        finally:
            props.current_chapter = original_ch
            props.current_stage = original_st

        print("[Confirm All Chapters]")
        for ch, ok, reason, message in results:
            status = "OK" if ok else "NG"
            print(f"  Ch{ch}: {status} ({reason}) {message}")

        summary = " / ".join([f"Ch{ch}:{'OK' if ok else 'NG'}" for ch, ok, _, _ in results])
        self.report({'INFO'}, summary)
        return {'FINISHED'}

class TUTORIAL_OT_export_stage_summary_csv(Operator):
    bl_idname = "tutorial.export_stage_summary_csv"
    bl_label = "ステージ集計CSV出力"
    bl_description = "参加者ログ(JSONL)から、失敗回数/停滞時間(finalizeのみ)をステージ別に集計してCSV出力します"

    def execute(self, context):
        props = context.scene.tutorial_props

        # Create log automatically so CSV can be exported even before first "確認"
        if not props.participant_log_path:
            ok = StageManager.ensure_participant_log_file(context)
            if not ok or not props.participant_log_path:
                self.report({'ERROR'}, props.participant_log_error or "ログファイルを作成できません。参加者IDとログ保存フォルダを確認してください。")
                return {'CANCELLED'}

        jsonl_path = bpy.path.abspath(props.participant_log_path)
        if not os.path.isfile(jsonl_path):
            self.report({'ERROR'}, f"ログファイルが見つかりません: {jsonl_path}")
            return {'CANCELLED'}

        events = []
        try:
            with open(jsonl_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        events.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        except Exception as e:
            self.report({'ERROR'}, f"ログ読み込みに失敗: {e}")
            return {'CANCELLED'}

        by_stage = {}
        for ev in events:
            ev_type = ev.get("event")
            if ev_type not in ("validate", "finalize"):
                continue
            ch = ev.get("chapter")
            st = ev.get("stage")
            if ch is None or st is None:
                continue
            key = (int(ch), int(st))
            if key not in by_stage:
                by_stage[key] = {"chapter": int(ch), "stage": int(st), "failures": 0, "stalled_seconds": None, "completed": None}
            if ev_type == "validate" and ev.get("ok") is False:
                by_stage[key]["failures"] += 1
            if ev_type == "finalize":
                if ev.get("stalled_seconds") is not None:
                    by_stage[key]["stalled_seconds"] = float(ev["stalled_seconds"])
                if ev.get("completed") is not None:
                    by_stage[key]["completed"] = bool(ev["completed"])

        total_stalled = 0.0
        for r in by_stage.values():
            if isinstance(r["stalled_seconds"], (int, float)):
                total_stalled += float(r["stalled_seconds"])

        out_csv = os.path.splitext(jsonl_path)[0] + ".stage_summary.csv"
        try:
            # Excel-friendly UTF-8 with BOM
            with open(out_csv, "w", encoding="utf-8-sig", newline="") as f:
                w = csv.writer(f)
                w.writerow(["participant_log_file", os.path.basename(jsonl_path)])
                w.writerow(["total_stalled_seconds_finalize_only", f"{total_stalled:.3f}"])
                w.writerow([])
                w.writerow(["chapter", "stage", "failures", "stalled_seconds_finalize_only", "completed"])
                for key in sorted(by_stage.keys()):
                    r = by_stage[key]
                    stalled = r["stalled_seconds"]
                    stalled_str = f"{stalled:.3f}" if isinstance(stalled, (int, float)) else ""
                    completed_str = "" if r["completed"] is None else str(r["completed"])
                    w.writerow([r["chapter"], r["stage"], r["failures"], stalled_str, completed_str])
        except Exception as e:
            self.report({'ERROR'}, f"CSV出力に失敗: {e}")
            return {'CANCELLED'}

        self.report({'INFO'}, f"CSV出力完了: {out_csv}")
        return {'FINISHED'}

class TUTORIAL_OT_render_and_mark_saved(Operator):
    bl_idname = "tutorial.render_and_mark_saved"
    bl_label = "補助: レンダーして保存（自動）"
    bl_description = "最終制作: レンダー画像を自動で保存し、クリア判定できるようにします"

    def execute(self, context):
        props = context.scene.tutorial_props
        try:
            base_dir = StageManager.ensure_dir_exists(props.log_dir or StageManager.default_log_dir())
        except Exception as e:
            self.report({'ERROR'}, f"ログ保存フォルダ作成に失敗: {e}")
            return {'CANCELLED'}

        pid = StageManager._safe_participant_id(props.participant_id) or "participant"
        out_dir = os.path.join(base_dir, f"{pid}_renders")
        os.makedirs(out_dir, exist_ok=True)

        try:
            bpy.ops.render.render('INVOKE_DEFAULT', write_still=False)
        except Exception as e:
            self.report({'ERROR'}, f"レンダー開始に失敗: {e}")
            return {'CANCELLED'}

        try:
            img = bpy.data.images.get("Render Result")
            if not img:
                self.report({'ERROR'}, "Render Result が見つかりません")
                return {'CANCELLED'}

            ts = time.strftime("%Y%m%d_%H%M%S", time.localtime(StageManager._now()))
            filename = f"{pid}_final_{ts}.png"
            out_path = os.path.join(out_dir, filename)

            img.save_render(filepath=out_path, scene=context.scene)
            props.final_render_saved_path = out_path
            self.report({'INFO'}, f"保存しました: {out_path}")
            return {'FINISHED'}
        except Exception as e:
            self.report({'ERROR'}, f"保存に失敗: {e}")
            return {'CANCELLED'}

class TUTORIAL_OT_finish_and_turn_off(Operator):
    bl_idname = "tutorial.finish_and_turn_off"
    bl_label = "完了（カメラ・ライトOFF）"
    bl_description = "セッション終了: シーンのカメラを解除し、ライトを表示/レンダーから非表示にします"

    def execute(self, context):
        StageManager.turn_off_scene_camera_and_lights()
        self.report({'INFO'}, "カメラとライトをOFFにしました（削除はしていません）")
        return {'FINISHED'}

class TUTORIAL_OT_setup_stage(Operator):
    bl_idname = "tutorial.setup_stage"
    bl_label = "ステージセットアップ"

    def execute(self, context):
        props = context.scene.tutorial_props
        ch = props.current_chapter

        StageManager.finalize_current_run(context, completed=False)

        try:
            if ch == 1:
                bpy.ops.object.mode_set(mode='OBJECT')
                bpy.ops.object.select_all(action='SELECT')
                bpy.ops.object.delete(use_global=False)

                bpy.ops.mesh.primitive_cube_add(size=2, location=(0, 0, 0))
                cube = bpy.context.active_object
                cube.name = "Cube"
                props.initial_position = tuple(cube.location)
                props.initial_rotation = tuple(cube.rotation_euler)
                props.initial_scale = tuple(cube.scale)

            elif ch == 2:
                space = StageManager.get_view3d_space(context)
                if space and space.region_3d:
                    props.initial_view_distance = space.region_3d.view_distance
                    props.initial_view_location = tuple(space.region_3d.view_location)

            elif ch == 3:
                cube = StageManager.find_cube()
                if not cube:
                    bpy.ops.object.mode_set(mode='OBJECT')
                    bpy.ops.object.select_all(action='SELECT')
                    bpy.ops.object.delete(use_global=False)
                    bpy.ops.mesh.primitive_cube_add(size=2, location=(0, 0, 0))
                    cube = bpy.context.active_object
                    cube.name = "Cube"

                bpy.context.view_layer.objects.active = cube
                cube.select_set(True)
                bpy.ops.object.mode_set(mode='EDIT')
                bpy.context.view_layer.update()

                props.initial_vertex_count = len(cube.data.vertices)
                props.initial_edge_count = len(cube.data.edges)
                props.initial_face_count = len(cube.data.polygons)

            elif ch == 4:
                bpy.ops.object.mode_set(mode='OBJECT')
                bpy.ops.object.select_all(action='SELECT')
                bpy.ops.object.delete(use_global=False)

                bpy.ops.mesh.primitive_uv_sphere_add(radius=1, location=(0, 0, 0))
                sphere = bpy.context.active_object
                sphere.name = "Sphere"
                bpy.context.view_layer.objects.active = sphere
                sphere.select_set(True)
                bpy.ops.object.mode_set(mode='SCULPT')

                props.initial_vertex_positions.clear()
                for v in sphere.data.vertices:
                    item = props.initial_vertex_positions.add()
                    item.co = v.co.copy()

            elif ch == 5:
                bpy.ops.object.mode_set(mode='OBJECT')
                if not context.active_object or context.active_object.type != 'MESH':
                    bpy.ops.mesh.primitive_cube_add(size=2, location=(0, 0, 0))
                    cube = bpy.context.active_object
                    cube.name = "Cube"
                StageManager.open_shader_editor_at_bottom()

            elif ch == 6:
                props.current_stage = 1
                props.final_render_saved_path = ""
                StageManager.ensure_camera_for_ch6_stage1(
                    location=(10.0, -4.0, 4.5),
                    rotation_deg=(63.0, 0.0, 66.0),
                )
                StageManager.ensure_sun_for_ch6_stage1(
                    location=(10.0, -4.0, 4.5),
                    rotation_deg=(63.0, 0.0, 66.0),
                    energy=1000.0,
                )

        except Exception as e:
            self.report({'ERROR'}, f"セットアップ中にエラー: {e}")
            return {'CANCELLED'}

        props.stage_complete = False
        props.monitoring_active = True

        props.failed_validate_count = 0
        props.stage_start_time = time.time()
        props.last_result_ok = True
        props.last_reason = ""
        props.last_message = ""
        props.last_hints = ""

        if not (props.log_dir or "").strip():
            props.log_dir = StageManager.default_log_dir()
        try:
            StageManager.ensure_dir_exists(props.log_dir)
        except Exception as e:
            props.participant_log_error = f"ログ保存フォルダ作成に失敗: {e}"

        StageManager.log_setup_event(context)
        self.report({'INFO'}, "セットアップ完了")
        return {'FINISHED'}

class TUTORIAL_OT_validate_stage(Operator):
    bl_idname = "tutorial.validate_stage"
    bl_label = "確認"

    def execute(self, context):
        props = context.scene.tutorial_props
        ok, message, reason, hints = StageManager.validate_stage(context)

        props.last_result_ok = ok
        props.last_reason = reason
        props.last_message = message

        if ok:
            props.stage_complete = True
            props.failed_validate_count = 0
            props.last_hints = ""
        else:
            props.failed_validate_count += 1
            escalated = StageManager.apply_hint_escalation(hints, props.failed_validate_count)
            props.last_hints = "\n".join(escalated) if escalated else ""

        StageManager.log_validate_event(context, ok=ok, reason=reason, message=message)
        self.report({'INFO'} if ok else {'WARNING'}, message)
        return {'FINISHED'}

class TUTORIAL_OT_next_stage(Operator):
    bl_idname = "tutorial.next_stage"
    bl_label = "次へ"

    def execute(self, context):
        props = context.scene.tutorial_props
        StageManager.finalize_current_run(context, completed=True)

        max_stages_per_chapter = {1: 4, 2: 4, 3: 6, 4: 4, 5: 5, 6: 1}
        max_stages = max_stages_per_chapter.get(props.current_chapter, 1)

        if props.current_stage < max_stages:
            props.current_stage += 1
        else:
            if props.current_chapter < 6:
                props.current_chapter += 1
                props.current_stage = 1
            else:
                StageManager.turn_off_scene_camera_and_lights()
                self.report({'INFO'}, "完了!（カメラ・ライトをOFFにしました）")
                props.stage_start_time = 0.0
                return {'FINISHED'}

        props.stage_complete = False
        props.monitoring_active = False

        props.failed_validate_count = 0
        props.stage_start_time = 0.0
        props.last_result_ok = True
        props.last_reason = ""
        props.last_message = ""
        props.last_hints = ""
        return {'FINISHED'}

class TUTORIAL_OT_reset(Operator):
    bl_idname = "tutorial.reset"
    bl_label = "リセット"

    def execute(self, context):
        props = context.scene.tutorial_props
        StageManager.finalize_current_run(context, completed=False)

        props.current_chapter = 1
        props.current_stage = 1
        props.stage_complete = False
        props.monitoring_active = False

        props.failed_validate_count = 0
        props.stage_start_time = 0.0
        props.last_result_ok = True
        props.last_reason = ""
        props.last_message = ""
        props.last_hints = ""
        return {'FINISHED'}

class TUTORIAL_OT_goto_chapter(Operator):
    bl_idname = "tutorial.goto_chapter"
    bl_label = "チャプターへ"
    chapter: IntProperty(default=1, min=1, max=6)

    def execute(self, context):
        props = context.scene.tutorial_props
        StageManager.finalize_current_run(context, completed=False)

        props.current_chapter = self.chapter
        props.current_stage = 1
        props.stage_complete = False
        props.monitoring_active = False

        props.failed_validate_count = 0
        props.stage_start_time = 0.0
        props.last_result_ok = True
        props.last_reason = ""
        props.last_message = ""
        props.last_hints = ""
        return {'FINISHED'}

class TUTORIAL_OT_monitoring(Operator):
    bl_idname = "wm.tutorial_monitoring"
    bl_label = "Tutorial Monitoring"
    _timer = None
    _last_check = 0.0

    def modal(self, context, event):
        if event.type == 'TIMER':
            try:
                props = context.scene.tutorial_props
                if not props.monitoring_active:
                    wm = context.window_manager
                    if self._timer:
                        wm.event_timer_remove(self._timer)
                    return {'FINISHED'}

                # OK to write here (not in draw)
                props.current_stall_seconds = StageManager.get_stall_seconds(context)

                current_time = time.time()
                if current_time - self._last_check > 0.2:
                    StageManager.check_stage(context)
                    self._last_check = current_time
            except Exception:
                pass
        return {'PASS_THROUGH'}

    def execute(self, context):
        wm = context.window_manager
        self._timer = wm.event_timer_add(0.1, window=context.window)
        self._last_check = time.time()
        wm.modal_handler_add(self)
        return {'RUNNING_MODAL'}

# =====================================================
# PANEL
# =====================================================

class TUTORIAL_PT_main(Panel):
    bl_label = "3DCG チュートリアル"
    bl_idname = "TUTORIAL_PT_main"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Tutorial"

    def draw(self, context):
        layout = self.layout
        props = context.scene.tutorial_props

        pbox = layout.box()
        pbox.label(text="参加者ログ（DIR_PATH + 安全ボタン）")
        pbox.prop(props, "participant_id")
        pbox.prop(props, "log_dir")

        row = pbox.row(align=True)
        row.operator("tutorial.set_default_log_dir", text="既定フォルダに設定")
        row.operator("tutorial.open_log_folder", text="ログフォルダを開く")

        pbox.prop(props, "enable_participant_logging", text="ログ記録を有効化")
        pbox.operator("tutorial.export_stage_summary_csv", text="ステージ集計CSV出力")

        if props.participant_log_path:
            pbox.label(text=f"ログファイル: {props.participant_log_path}")
        if props.participant_log_error:
            pbox.label(text=f"注意: {props.participant_log_error}")

        cbox = layout.box()
        cbox.label(text="チャプター選択")
        row = cbox.row(align=True)
        for i in range(1, 7):
            op = row.operator("tutorial.goto_chapter", text=f"第{i}章", depress=(props.current_chapter == i))
            op.chapter = i
        cbox.operator("tutorial.confirm_all_chapters", text="全チャプター確認")

        info = StageManager.get_stage_info(props.current_chapter, props.current_stage)
        sbox = layout.box()
        sbox.label(text=info.get("title", ""))
        max_stages_per_chapter = {1: 4, 2: 4, 3: 6, 4: 4, 5: 5, 6: 1}
        sbox.label(text=f"ステージ {props.current_stage}/{max_stages_per_chapter.get(props.current_chapter, 1)}")
        sbox.label(text=info.get("name", ""))
        sbox.separator()
        sbox.label(text=info.get("description", ""))

        if info.get("details"):
            sbox.separator()
            for line in info["details"].split("\n"):
                sbox.label(text=line)

        if props.current_chapter == 6:
            sbox.separator()
            sbox.operator("tutorial.render_and_mark_saved", text="補助: レンダーして保存（自動）")
            if props.final_render_saved_path:
                sbox.label(text=f"保存検出: {props.final_render_saved_path}")

        if not props.last_result_ok and props.last_message:
            fb = layout.box()
            fb.label(text="フィードバック")
            fb.label(text=props.last_message)
            if props.last_hints:
                fb.separator()
                for line in props.last_hints.split("\n"):
                    fb.label(text=f"- {line}")

        layout.separator()
        col = layout.column()
        col.scale_y = 1.2
        col.operator("tutorial.setup_stage", text="セットアップ")
        col.operator("wm.tutorial_monitoring", text="監視開始")
        col.operator("tutorial.validate_stage", text="確認")
        if props.stage_complete:
            col.operator("tutorial.next_stage", text="次へ")
        layout.operator("tutorial.reset", text="リセット")
        layout.operator("tutorial.finish_and_turn_off", text="完了（カメラ・ライトOFF）")

        # draw() must be read-only: compute locally
        stall_s = StageManager.get_stall_seconds(context)
        layout.separator()
        layout.label(text=f"停滞時間: {stall_s:.1f}s / 失敗回数: {props.failed_validate_count}")

# =====================================================
# REGISTER
# =====================================================

classes = (
    VertexPos,
    StageRun,
    TUTORIAL_PG_Properties,
    TUTORIAL_OT_set_default_log_dir,
    TUTORIAL_OT_open_log_folder,
    TUTORIAL_OT_confirm_all_chapters,
    TUTORIAL_OT_export_stage_summary_csv,
    TUTORIAL_OT_render_and_mark_saved,
    TUTORIAL_OT_finish_and_turn_off,
    TUTORIAL_OT_setup_stage,
    TUTORIAL_OT_validate_stage,
    TUTORIAL_OT_next_stage,
    TUTORIAL_OT_reset,
    TUTORIAL_OT_goto_chapter,
    TUTORIAL_OT_monitoring,
    TUTORIAL_PT_main,
)

def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.tutorial_props = bpy.props.PointerProperty(type=TUTORIAL_PG_Properties)

def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    del bpy.types.Scene.tutorial_props

if __name__ == "__main__":
    register()