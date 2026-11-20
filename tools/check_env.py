#!/usr/bin/env python3
"""Проверить среду: FEMM, Wine, версии. Не запускает расчёт."""
from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys

WINE = os.environ.get("WINE", "/Applications/Wine Stable.app/Contents/Resources/wine/bin/wine")
FEMM = os.environ.get("FEMM_EXE", os.path.expanduser("~/.wine/drive_c/femm42/bin/femm.exe"))


def ver(cmd):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=15).stdout.strip() or "?"
    except Exception as e:  # noqa: BLE001
        return f"error: {e}"


res = {
    "os": platform.platform(),
    "python": sys.version.split()[0],
    "wine": {"path": WINE, "exists": os.path.exists(WINE), "version": ver([WINE, "--version"]) if os.path.exists(WINE) else None},
    "femm": {"path": FEMM, "exists": os.path.exists(FEMM)},
    "commands": {c: shutil.which(c) for c in ("git", "node", "npm", "claude", "codex", "opencode")},
    "ok": os.path.exists(FEMM) and os.path.exists(WINE),
}
print(json.dumps(res, ensure_ascii=False, indent=1))
sys.exit(0 if res["ok"] else 1)
