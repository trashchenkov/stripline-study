#!/usr/bin/env python3
"""Последовательный прогон матрицы. Один прогон на ячейку.

    python3 tools/run_matrix.py --stacks claude,codex,opencode --profiles A,C --tasks T1,T2,T3,T4,T5 --seed 1
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import random
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
STACKS = {"claude": "claude.json", "codex": "codex.json", "opencode": "opencode.json"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stacks", default="claude,codex,opencode")
    ap.add_argument("--profiles", default="A,C")
    ap.add_argument("--tasks", default="T1,T2,T3,T4,T5")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--capture", action="store_true")
    a = ap.parse_args()
    jobs = [(s, p, t) for s in a.stacks.split(",") for p in a.profiles.split(",") for t in a.tasks.split(",")]
    random.Random(a.seed).shuffle(jobs)
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    out = os.path.join(ROOT, "runs", f"matrix-{stamp}")
    os.makedirs(out, exist_ok=True)
    log = open(os.path.join(out, "matrix.jsonl"), "a", encoding="utf-8")
    for i, (stack, profile, task) in enumerate(jobs, 1):
        run_id = f"m-{stack}-{profile}-{task}-{a.seed}"
        mp = os.path.join(ROOT, "runs", run_id, "meta.json")
        if a.resume and os.path.exists(mp):
            try:
                if json.load(open(mp)).get("ended"):
                    continue
            except Exception:  # noqa: BLE001
                pass
        print(f"[{i}/{len(jobs)}] {run_id}", flush=True)
        cmd = [sys.executable, os.path.join(ROOT, "runner", "session_loop.py"), task,
               "--stack", os.path.join(ROOT, "runner", "adapters", "profiles", STACKS[stack]),
               "--profile", profile, "--run-id", run_id] + (["--capture", "--gif"] if a.capture else [])
        r = subprocess.run(cmd, capture_output=True, text=True)
        rec = {"run_id": run_id, "stack": stack, "profile": profile, "task": task,
               "rc": r.returncode, "stdout": r.stdout[-1000:], "stderr": r.stderr[-1000:]}
        log.write(json.dumps(rec, ensure_ascii=False) + "\n")
        log.flush()
    log.close()
    print(out)


if __name__ == "__main__":
    main()
