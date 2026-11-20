#!/usr/bin/env python3
"""Сводка по матрице прогонов. Не запускает агентов.

    python3 tools/summarize_runs.py runs/matrix-YYYYmmdd-HHMMSS
"""
from __future__ import annotations

import glob
import json
import os
import sys
from collections import Counter, defaultdict


def final_check(run_dir):
    files = sorted(glob.glob(os.path.join(run_dir, "checks", "t*.json")),
                   key=lambda p: int(os.path.basename(p)[1:-5]))
    if not files:
        return {}
    try:
        return json.load(open(files[-1]))
    except Exception:  # noqa: BLE001
        return {}


def main():
    root = sys.argv[1]
    rows = [json.loads(x) for x in open(os.path.join(root, "matrix.jsonl"))]
    out = []
    agg = defaultdict(list)
    for r in rows:
        d = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "runs", r["run_id"])
        meta = json.load(open(os.path.join(d, "meta.json"))) if os.path.exists(os.path.join(d, "meta.json")) else {}
        ops = [json.loads(x) for x in open(os.path.join(d, "operator.jsonl"))] if os.path.exists(os.path.join(d, "operator.jsonl")) else []
        final = any((o.get("text") or "").lstrip().lower().startswith("[final]") for o in ops)
        ch = final_check(d)
        st = Counter(x["status"] for x in ch.get("checks", []))
        passed = bool(ch.get("passed")) and not st.get("fail")
        failed = [x["id"] for x in ch.get("checks", []) if x["status"] == "fail"]
        rec = {"stack": r["stack"], "profile": r["profile"], "task": r["task"], "run": r["run_id"],
               "seconds": meta.get("ended") and meta.get("turns") is not None and None,
               "turns": meta.get("turns"), "final": final, "passed": passed,
               "false_accept": final and not passed, "failed": failed, "checks": dict(st)}
        # длительность из meta
        try:
            from datetime import datetime
            rec["seconds"] = int((datetime.fromisoformat(meta["ended"]) - datetime.fromisoformat(meta["started"])).total_seconds())
        except Exception:  # noqa: BLE001
            rec["seconds"] = None
        rows_out = rec
        out.append(rows_out)
        agg[(r["stack"], r["profile"])].append(rows_out)

    L = ["# Сводка матрицы", ""]
    L.append("| Стек | Профиль | Прогонов | Финалов | Проверки pass | Ложная приёмка | Среднее время, с |")
    L.append("|---|---|---:|---:|---:|---:|---:|")
    for (stack, profile), rs in sorted(agg.items()):
        secs = [x["seconds"] for x in rs if x["seconds"] is not None]
        L.append(f"| {stack} | {profile} | {len(rs)} | {sum(x['final'] for x in rs)} | "
                 f"{sum(x['passed'] for x in rs)} | {sum(x['false_accept'] for x in rs)} | "
                 f"{(sum(secs)/len(secs)):.0f}" if secs else f"| {stack} | {profile} | {len(rs)} | {sum(x['final'] for x in rs)} | {sum(x['passed'] for x in rs)} | {sum(x['false_accept'] for x in rs)} | — |")
    L += ["", "## По задачам", "", "| Стек | Профиль | Задача | Ходы | Финал | Pass | Fail |", "|---|---|---|---:|---|---:|---|"]
    for x in out:
        L.append(f"| {x['stack']} | {x['profile']} | {x['task']} | {x['turns']} | {'да' if x['final'] else 'нет'} | "
                 f"{x['checks'].get('pass',0)} | {x['checks'].get('fail',0)} |")
    L += ["", "## Провалы", ""]
    for x in out:
        if x["failed"] or x["false_accept"]:
            L.append(f"- {x['run']}: fail={','.join(x['failed']) or '—'}, final={x['final']}, "
                     f"ложная приёмка={x['false_accept']}")
    open(os.path.join(root, "summary.md"), "w", encoding="utf-8").write("\n".join(L) + "\n")
    json.dump(out, open(os.path.join(root, "summary.json"), "w"), ensure_ascii=False, indent=1)
    print(os.path.join(root, "summary.md"))


if __name__ == "__main__":
    main()
