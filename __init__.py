# -*- coding: utf-8 -*-
bl_info = {
    "name": "3DCG Tutorial Simulator",
    "blender": (4, 2, 0),
    "version": (0, 8, 5),
    "author": "Daichi",
    "description": "Interactive 3D learning simulation for Blender (Ch1-6 tutorials + participant JSONL logging + CSV export + DIR_PATH safe buttons; Ch6 Stage1 only w/ auto camera+sun on setup)",
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
    @staticmethod
    def _now():
        return time.time()

    @staticmethod
    def vec_dist(a, b):
        return math.sqrt(sum((a[i] - b[i]) ** 2 for i in range(3)))

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
        try:
            props = context.scene.tutorial_props
            if props.stage_start_time <= 0.0:
                return 0.0
            return max(0.0, StageManager._now() - props.stage_start_time)
        except Exception:
            return 0.0

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
                f.write(json.dumps({
                    "t": StageManager._now(),
                    "participant_id": pid,
                    "event": "session_start",
                    "blender_version": ".".join(map(str, bpy.app.version)),
                    "addon_version": ".".join(map(str, bl_info.get("version", (0, 0, 0)))),
                }, ensure_ascii=False) + "\n")
            props.participant_log_path = log_path
            props.participant_log_error = ""
            return True
        except Exception as e:
            props.participant_log_error = f"ログファイル作成に失敗: {e}"
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
            props.participant_log_error = f"ログ書き込みに失敗: {e}"

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

    @staticmethod
    def finalize_current_run(context, completed: bool):
        try:
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
        except Exception:
            return

    # -----------------------------
    # Chapter 6: camera + sun + cleanup
    # -----------------------------
    @staticmethod
    def file_exists_nonempty(path: str) -> bool:
        try:
            return os.path.isfile(path) and os.path.getsize(path) > 0
        except Exception:
            return False

    @staticmethod
    def ensure_camera_for_ch6_stage1(location=(10.0, -4.0, 4.5), rotation_deg=(63.0, 0.0, 66.0)):
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

        # other chapters omitted from get_stage_info for brevity; keep existing mapping if you want
        return {"title": f"第{chapter_num}章", "name": f"ステージ{stage_num}", "description": ""}

    @staticmethod
    def apply_hint_escalation(hints, failed_validate_count: int):
        if not hints:
            return []
        if failed_validate_count <= 1:
            return hints[:1]
        if failed_validate_count == 2:
            return hints[:2]
        return hints[:3]

    @staticmethod
    def validate_stage(context):
        props = context.scene.tutorial_props
        ch = props.current_chapter

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

        # Fallback: treat other chapters as not implemented in this reduced snippet
        return False, "❌ このビルドは第6章を中心にしています", "NOT_IMPLEMENTED", []

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

    initial_position: FloatVectorProperty(default=(0.0, 0.0, 0.0), size=3)
    initial_rotation: FloatVectorProperty(default=(0.0, 0.0, 0.0), size=3)
    initial_scale: FloatVectorProperty(default=(1.0, 1.0, 1.0), size=3)

    initial_view_distance: FloatProperty(default=0.0)
    initial_view_location: FloatVectorProperty(default=(0.0, 0.0, 0.0), size=3)

    initial_vertex_count: IntProperty(default=0)
    initial_edge_count: IntProperty(default=0)
    initial_face_count: IntProperty(default=0)

    initial_vertex_positions: CollectionProperty(type=VertexPos)

    failed_validate_count: IntProperty(default=0, min=0)
    stage_start_time: FloatProperty(default=0.0)
    last_result_ok: BoolProperty(default=True)
    last_reason: StringProperty(default="")
    last_message: StringProperty(default="")
    last_hints: StringProperty(default="")

    stage_runs: CollectionProperty(type=StageRun)

    # IMPORTANT:
    # This property must NOT be written in Panel.draw(). Only read there.
    current_stall_seconds: FloatProperty(default=0.0, min=0.0)

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

    final_render_saved_path: StringProperty(default="")

# =====================================================
# OPERATORS
# =====================================================

class TUTORIAL_OT_set_default_log_dir(Operator):
    bl_idname = "tutorial.set_default_log_dir"
    bl_label = "既定フォルダに設定"

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

    def execute(self, context):
        props = context.scene.tutorial_props
        try:
            StageManager.open_folder_in_os(props.log_dir or StageManager.default_log_dir())
        except Exception as e:
            self.report({'ERROR'}, f"フォルダを開けません: {e}")
            return {'CANCELLED'}
        return {'FINISHED'}

class TUTORIAL_OT_export_stage_summary_csv(Operator):
    bl_idname = "tutorial.export_stage_summary_csv"
    bl_label = "ステージ集計CSV出力"

    def execute(self, context):
        props = context.scene.tutorial_props

        # auto-create log file so CSV can be exported even before first "確認"
        if not props.participant_log_path:
            ok = StageManager.ensure_participant_log_file(context)
            if not ok or not props.participant_log_path:
                self.report({'ERROR'}, props.participant_log_error or "ログファイルを作成できません")
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

        out_csv = os.path.splitext(jsonl_path)[0] + ".stage_summary.csv"
        try:
            with open(out_csv, "w", encoding="utf-8-sig", newline="") as f:
                w = csv.writer(f)
                w.writerow(["participant_log_file", os.path.basename(jsonl_path)])
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

class TUTORIAL_OT_setup_stage(Operator):
    bl_idname = "tutorial.setup_stage"
    bl_label = "セットアップ"

    def execute(self, context):
        props = context.scene.tutorial_props
        StageManager.finalize_current_run(context, completed=False)

        # start timer
        props.stage_start_time = time.time()
        props.monitoring_active = True
        props.stage_complete = False
        props.failed_validate_count = 0
        props.last_result_ok = True
        props.last_reason = ""
        props.last_message = ""
        props.last_hints = ""

        # ensure log dir exists
        if not (props.log_dir or "").strip():
            props.log_dir = StageManager.default_log_dir()
        try:
            StageManager.ensure_dir_exists(props.log_dir)
        except Exception as e:
            props.participant_log_error = f"ログ保存フォルダ作成に失敗: {e}"

        # Chapter 6 setup: create camera+sun
        if props.current_chapter == 6:
            props.current_stage = 1
            props.final_render_saved_path = ""
            StageManager.ensure_camera_for_ch6_stage1()
            StageManager.ensure_sun_for_ch6_stage1()

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
            props.last_hints = "\n".join(hints) if hints else ""

        StageManager.log_validate_event(context, ok=ok, reason=reason, message=message)
        self.report({'INFO'} if ok else {'WARNING'}, message)
        return {'FINISHED'}

class TUTORIAL_OT_monitoring(Operator):
    bl_idname = "wm.tutorial_monitoring"
    bl_label = "Monitoring"
    _timer = None
    _last_check = 0.0

    def modal(self, context, event):
        if event.type == 'TIMER':
            props = context.scene.tutorial_props
            if not props.monitoring_active:
                wm = context.window_manager
                if self._timer:
                    wm.event_timer_remove(self._timer)
                return {'FINISHED'}

            # OK to write props here (NOT in draw)
            props.current_stall_seconds = StageManager.get_stall_seconds(context)

            current_time = time.time()
            if current_time - self._last_check > 0.2:
                StageManager.check_stage(context)
                self._last_check = current_time

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

        # Controls
        layout.separator()
        col = layout.column()
        col.scale_y = 1.2
        col.operator("tutorial.setup_stage", text="セットアップ")
        col.operator("wm.tutorial_monitoring", text="監視開始")
        col.operator("tutorial.validate_stage", text="確認")

        # IMPORTANT: do NOT write to props in draw()
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
    TUTORIAL_OT_export_stage_summary_csv,
    TUTORIAL_OT_setup_stage,
    TUTORIAL_OT_validate_stage,
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