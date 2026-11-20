#!/usr/bin/env python3
"""Собрать чистый workspace задачи из tasks/<id>/workspace.

Не запускает агента. Копирует только разрешённое, добавляет spec и schema,
считает хэши. Скрытые проверки и runs не попадают в workspace.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def sha(path: str) -> str:
    h = hashlib.sha256()
    if os.path.isdir(path):
        for base, _dirs, names in os.walk(path):
            for n in sorted(names):
                p = os.path.join(base, n)
                h.update(os.path.relpath(p, path).encode())
                with open(p, "rb") as f:
                    for chunk in iter(lambda: f.read(65536), b""):
                        h.update(chunk)
        return h.hexdigest()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("task")
    ap.add_argument("--out")
    a = ap.parse_args()
    task_dir = os.path.join(ROOT, "tasks", a.task)
    if not os.path.isdir(task_dir):
        print(f"нет задачи {a.task}", file=sys.stderr)
        return 2
    cfg = json.load(open(os.path.join(task_dir, "task.json")))
    src = os.path.join(task_dir, "workspace")
    out = a.out or os.path.join(ROOT, "runs", "_build", f"{a.task}-{dt.datetime.now():%Y%m%d-%H%M%S}")
    ws = os.path.join(out, "workspace")
    os.makedirs(out, exist_ok=True)
    if os.path.exists(ws):
        shutil.rmtree(ws)
    shutil.copytree(src, ws)
    shutil.copy2(os.path.join(task_dir, "spec.md"), os.path.join(ws, "spec.md"))
    shutil.copy2(os.path.join(ROOT, "AGENTS.template.md"), os.path.join(ws, "AGENTS.md"))
    if cfg.get("lib"):
        shutil.copytree(os.path.join(ROOT, "lib"), os.path.join(ws, "lib"))
    # пустой git-корень: агент видит workspace как корень, а не родительский репозиторий
    subprocess.run(["git", "init", "-q"], cwd=ws, check=True)

    docs_src = os.path.join(ROOT, "docs", "femm")
    docs = os.path.isdir(docs_src) and any(os.scandir(docs_src))
    if docs:
        dst = os.path.join(ws, "docs")
        if os.path.exists(dst):
            shutil.rmtree(dst)
        shutil.copytree(docs_src, dst)

    files = {}
    for base, dirs, names in os.walk(ws):
        if ".git" in dirs:
            dirs.remove(".git")
        for n in sorted(names):
            p = os.path.join(base, n)
            files[os.path.relpath(p, ws)] = sha(p)
    manifest = {
        "task": cfg["id"], "version": cfg.get("version"), "built_at": dt.datetime.now().isoformat(timespec="seconds"),
        "task_json_sha256": sha(os.path.join(task_dir, "task.json")), "spec_sha256": sha(os.path.join(task_dir, "spec.md")),
        "workspace_sha256": sha(os.path.join(out, "workspace")), "docs": docs, "files": files,
    }
    with open(os.path.join(out, "build.json"), "w") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=1)
    print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
