#!/usr/bin/env python3
"""Анализ собранных прогонов: условия helper/raw, метрики, провалы, артефакты."""
from __future__ import annotations

import glob
import json
import os
import re
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUNS = os.path.join(ROOT, "runs")
OUT = os.path.join(ROOT, "analysis")
os.makedirs(OUT, exist_ok=True)


def load():
    best = {}
    for d in glob.glob(os.path.join(RUNS, "m-*")):
        mp = os.path.join(d, "meta.json")
        try:
            m = json.load(open(mp))
        except Exception:
            continue
        if not m.get("ended"):
            continue
        rid = m["run_id"]
        if rid not in best or m["ended"] > best[rid][1]["ended"]:
            best[rid] = (d, m)
    rows = []
    for rid, (d, m) in best.items():
        task = m["task"]
        cond = "raw" if task.endswith("raw") else "helpers"
        if task == "T1":
            cond = "shared"
        base_task = task.replace("raw", "")
        cf = sorted(glob.glob(os.path.join(d, "checks", "t*.json")), key=lambda p: int(os.path.basename(p)[1:-5]))
        ch = json.load(open(cf[-1])) if cf else {}
        ops = os.path.join(d, "operator.jsonl")
        optexts = [json.loads(x).get("text", "") for x in open(ops)] if os.path.exists(ops) else []
        final = any(t.lstrip().lower().startswith("[final]") for t in optexts)
        fails = [x["id"] for x in ch.get("checks", []) if x["status"] == "fail"]
        passed = bool(ch.get("passed")) and not fails
        try:
            secs = int((datetime.fromisoformat(m["ended"]) - datetime.fromisoformat(m["started"])).total_seconds())
        except Exception:
            secs = None
        art = {
            "frames": len(glob.glob(os.path.join(d, "frames", "*.png"))),
            "gif": os.path.exists(os.path.join(d, "session.gif")),
            "plots": sum(1 for b, _x, ns in os.walk(os.path.join(d, "workspace")) for n in ns if n.lower().endswith(".png")),
            "result": os.path.exists(os.path.join(d, "workspace", "out", "result.json")),
            "variants": os.path.exists(os.path.join(d, "workspace", "out", "variants.json")),
            "geometry": os.path.exists(os.path.join(d, "workspace", "out", "geometry.json")),
        }
        rows.append({
            "run": rid, "dir": os.path.relpath(d, ROOT), "started": m["started"], "stack": m["stack"].split("/")[-1].replace(".json", ""),
            "profile": m["profile"], "task": base_task, "condition": cond, "turns": m.get("turns"),
            "seconds": secs, "final": final, "passed": passed, "false_accept": final and not passed,
            "fails": fails, "operator_chars": sum(len(t) for t in optexts), "artifacts": art,
        })
    shared = {}
    for r in rows:
        if r["condition"] != "shared":
            continue
        key = (r["stack"], r["profile"])
        if key not in shared or r["started"] > shared[key]["started"]:
            shared[key] = r
    rows = [r for r in rows if r["condition"] != "shared"] + list(shared.values())
    overrides = {
        "m-opencode-A-T4raw-2": "missing_dep",
        "m-opencode-A-T5raw-2": "path",
        "m-opencode-C-T2raw-2": "timeout_utility",
        "m-opencode-C-T3raw-2": "missing_dep",
        "m-opencode-C-T4raw-2": "missing_dep",
        "m-opencode-C-T5raw-2": "resource_limit",
    }
    for r in rows:
        r["category"] = overrides.get(r["run"], categorize(r))
    return sorted(rows, key=lambda r: (r["condition"], r["stack"], r["profile"], r["task"]))


def categorize(r):
    if r["passed"]:
        return "pass"
    p = os.path.join(ROOT, r["dir"], "executor", "raw.ansi")
    text = open(p, encoding="utf8", errors="ignore").read() if os.path.exists(p) else ""
    text += "\n".join(open(os.path.join(ROOT, r["dir"], "operator.jsonl")).read() if os.path.exists(os.path.join(ROOT, r["dir"], "operator.jsonl")) else "")
    if "Malformed_HTTP" in text or "target host connection failed" in text:
        return "endpoint"
    if "No module named" in text or "timeout: command not found" in text:
        return "missing_dep"
    if "No such file" in text:
        return "path"
    if "rate limit" in text.lower() or "too many requests" in text.lower():
        return "rate_limit"
    limits = {"T1": 25, "T2": 35, "T3": 30, "T4": 20, "T5": 60}
    if r["seconds"] and r["seconds"] >= limits.get(r["task"], 999) * 60 * 0.95:
        return "limit"
    if "Timed out" in text or "timed out" in text:
        return "timeout"
    return "incomplete"


def main():
    rows = load()
    json.dump(rows, open(os.path.join(OUT, "runs.json"), "w"), ensure_ascii=False, indent=1)
    L = ["# Анализ прогонов", "", f"Всего уникальных ячеек: {len(rows)}", ""]
    # Условия без T1
    comp = [r for r in rows if r["condition"] != "shared"]
    L += ["## Условия", "", "| Условие | Стек | Ячеек | Pass | Финал | Ложная приёмка | Среднее время, с |", "|---|---|---:|---:|---:|---:|---:|"]
    for cond in ("helpers", "raw"):
        for stack in ("claude", "codex", "opencode"):
            rs = [r for r in comp if r["condition"] == cond and r["stack"] == stack]
            if not rs:
                continue
            secs = [r["seconds"] for r in rs if r["seconds"] is not None]
            avg = f"{sum(secs)/len(secs):.0f}" if secs else "—"
            L.append(f"| {cond} | {stack} | {len(rs)} | {sum(r['passed'] for r in rs)} | {sum(r['final'] for r in rs)} | {sum(r['false_accept'] for r in rs)} | {avg} |")
    # T1
    t1 = [r for r in rows if r["condition"] == "shared"]
    L += ["", "## T1 (без helper, общая)", "", "| Стек | Профиль | Pass | Финал | Время, с |", "|---|---|---:|---:|---:|"]
    for r in sorted(t1, key=lambda x: (x["stack"], x["profile"])):
        L.append(f"| {r['stack']} | {r['profile']} | {r['passed']} | {r['final']} | {r['seconds']} |")
    # По задачам
    L += ["", "## По задачам и условиям", "", "| Условие | Стек | Задача | Pass | Финал | Ходы | Время, с |", "|---|---|---|---:|---:|---:|---:|"]
    for r in comp:
        L.append(f"| {r['condition']} | {r['stack']} | {r['profile']}{r['task']} | {r['passed']} | {r['final']} | {r['turns']} | {r['seconds']} |")
    # Провалы
    L += ["", "## Провалы", "", "| Прогон | Условие | Стек | Задача | Категория | Проверки | Финал |", "|---|---|---|---|---|---|---|"]
    for r in rows:
        if not r["passed"]:
            L.append(f"| {r['run']} | {r['condition']} | {r['stack']} | {r['profile']}{r['task']} | {r['category']} | {','.join(r['fails']) or 'нет проверок'} | {r['final']} |")
    L += ["", "## Категории провалов", ""]
    cats = {}
    for r in rows:
        if not r["passed"]:
            cats[r["category"]] = cats.get(r["category"], 0) + 1
    for k, v in sorted(cats.items()):
        L.append(f"- {k}: {v}")
    # Артефакты
    L += ["", "## Артефакты", "", "| Условие | Кадры | GIF | Графики | result | variants |", "|---|---:|---:|---:|---:|---:|"]
    for cond in ("helpers", "raw"):
        rs = [r for r in comp if r["condition"] == cond]
        L.append(f"| {cond} | {sum(r['artifacts']['frames'] for r in rs)} | {sum(r['artifacts']['gif'] for r in rs)} | {sum(r['artifacts']['plots'] for r in rs)} | {sum(r['artifacts']['result'] for r in rs)} | {sum(r['artifacts']['variants'] for r in rs)} |")
    # Оператор
    L += ["", "## Оператор", ""]
    for cond in ("helpers", "raw"):
        for stack in ("claude", "codex", "opencode"):
            rs = [r for r in comp if r["condition"] == cond and r["stack"] == stack]
            if not rs:
                continue
            chars = sorted(r["operator_chars"] for r in rs)
            turns = [r["turns"] for r in rs if isinstance(r["turns"], int)]
            L.append(f"- {cond}/{stack}: медиана символов оператора {chars[len(chars)//2]}, средние ходы {sum(turns)/len(turns):.1f}, финалов {sum(r['final'] for r in rs)}/{len(rs)}")
    open(os.path.join(OUT, "summary.md"), "w").write("\n".join(L) + "\n")
    print(os.path.join(OUT, "summary.md"))


if __name__ == "__main__":
    main()
