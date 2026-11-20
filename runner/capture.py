#!/usr/bin/env python3
"""Рендер экрана pyte в PNG для иллюстраций."""
from __future__ import annotations

import os
from PIL import Image, ImageDraw, ImageFont

FONT = "/System/Library/Fonts/Menlo.ttc"
FS = 13
CW, CH = 8, 17
FG = (208, 210, 214)
BG = (28, 32, 33)
DIM = (120, 124, 128)
ACCENT = (120, 200, 255)


def render(screen, path: str, caption: str = "") -> str:
    w = max(1, screen.columns) * CW
    h = max(1, screen.lines) * CH + (22 if caption else 0)
    img = Image.new("RGB", (w, h), BG)
    d = ImageDraw.Draw(img)
    font = ImageFont.truetype(FONT, FS)
    for y, line in enumerate(screen.display):
        for x, ch in enumerate(line):
            if ch == " ":
                continue
            cell = screen.buffer[y][x]
            fg = DIM if cell.fg == "brightblack" else ACCENT if cell.fg in ("brightblue", "blue") else FG
            if cell.reverse:
                d.rectangle([x * CW, y * CH, (x + 1) * CW, (y + 1) * CH], fill=FG)
                d.text((x * CW, y * CH - 2), ch, font=font, fill=BG)
            else:
                d.text((x * CW, y * CH - 2), ch, font=font, fill=fg)
    if caption:
        d.text((8, h - 19), caption, font=font, fill=DIM)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    img.save(path)
    return path
