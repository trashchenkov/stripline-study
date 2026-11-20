#!/usr/bin/env python3
"""Заморозить датасет: tasks/, hidden/, verifier/, operator/, lib/, schema/.

    python3 tools/freeze.py v1
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DIRS = ["tasks", "hidden", "verifier", "operator", "lib", "schema"]
IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc", "_frozen", "runs")


def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(65536), b""):
            h.update(c)
    return h.hexdigest()


def main():
    name = sys.argv[1] if len(sys.argv) > 1 else dt.datetime.now().strftime("v%Y%m%d-%H%M")
    out = os.path.join(ROOT, "tasks", "_frozen", name)
    if os.path.exists(out):
        print(f"уже есть {out}", file=sys.stderr)
        return 1
    files = {}
    for d in DIRS:
        src = os.path.join(ROOT, d)
        if not os.path.isdir(src):
            continue
        dst = os.path.join(out, d)
        shutil.copytree(src, dst, ignore=IGNORE)
        for base, _dirs, names in os.walk(dst):
            for n in sorted(names):
                p = os.path.join(base, n)
                files[os.path.relpath(p, out)] = sha(p)
    version = hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()
    with open(os.path.join(out, "DATASET_VERSION"), "w") as f:
        f.write(f"{name}\nsha256={version}\n{dt.datetime.now().isoformat(timespec='seconds')}\n")
    json.dump({"version": version, "files": files}, open(os.path.join(out, "manifest.json"), "w"), ensure_ascii=False, indent=1)
    open(os.path.join(out, "README.md"), "w").write(
        f"# Замороженный датасет {name}\n\nsha256={version}\n\nПосле заморозки задачи не меняются. Изменения — новая версия и `deviations.md`.\n")
    print(out)
    print(version)
    return 0


if __name__ == "__main__":
    sys.exit(main())
