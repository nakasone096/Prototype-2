import json
import csv
import sys
from pathlib import Path

def main(jsonl_path: str):
    p = Path(jsonl_path)
    if not p.exists():
        raise FileNotFoundError(p)

    rows = []
    with p.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                # 末尾が壊れている（クラッシュ等）場合でも復旧できるように無視
                continue

    # stage単位に集計
    by_stage = {}
    for ev in rows:
        if ev.get("event") not in ("validate", "finalize", "setup"):
            continue
        ch = ev.get("chapter")
        st = ev.get("stage")
        if ch is None or st is None:
            continue
        key = (int(ch), int(st))
        by_stage.setdefault(key, {
            "chapter": int(ch),
            "stage": int(st),
            "failures": 0,
            "stalled_seconds": 0.0,
            "completed": "",  # 最後のfinalizeのcompletedを入れる
        })

        if ev.get("event") == "validate":
            if ev.get("ok") is False:
                by_stage[key]["failures"] += 1

        if ev.get("event") == "finalize":
            # finalize はそのステージのsetup→離脱/完了までの時間
            stalled = ev.get("stalled_seconds")
            if stalled is not None:
                by_stage[key]["stalled_seconds"] = float(stalled)
            comp = ev.get("completed")
            if comp is not None:
                by_stage[key]["completed"] = str(bool(comp))

    # 出力（ステージ順）
    out_csv = p.with_suffix(".stage_summary.csv")
    stage_keys = sorted(by_stage.keys())

    total_time = sum(by_stage[k]["stalled_seconds"] for k in stage_keys)

    with out_csv.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["participant_file", str(p.name)])
        w.writerow(["total_stalled_seconds", f"{total_time:.3f}"])
        w.writerow([])
        w.writerow(["chapter", "stage", "failures", "stalled_seconds", "completed"])
        for k in stage_keys:
            r = by_stage[k]
            w.writerow([r["chapter"], r["stage"], r["failures"], f"{r['stalled_seconds']:.3f}", r["completed"]])

    print(f"written: {out_csv}")

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage: python jsonl_to_stage_summary_csv.py <participant_log.jsonl>")
        raise SystemExit(2)
    main(sys.argv[1])