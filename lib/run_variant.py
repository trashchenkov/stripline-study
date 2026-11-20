#!/usr/bin/env python3
"""Один вариант T5: перевёрнутый купол по r, R.

    python3 lib/run_variant.py --r 4 --R 120 --tag r4_R120

Пишет out/cases/<tag>.json и модели в out/cases/<tag>/. Сетку, variants.json,
ранжирование и оптимум собирает агент.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import femm_lua  # noqa: E402
import femm_runner  # noqa: E402
import geomodel as gm  # noqa: E402

A = 20.0
Y_APEX = -14.0
GAP = 6.0


def dome_down(r: float, R: float) -> dict:
    if R <= A or not 0 < r < A:
        raise ValueError("нужно R > 20 и 0 < r < 20")
    c = (0.0, Y_APEX + R)
    yt = Y_APEX + R + r - math.sqrt((R - r) ** 2 - (A - r) ** 2)
    fr, fl = (A - r, yt - r), (-(A - r), yt - r)

    def tangent(f):
        d = gm.dist(c, f)
        return (c[0] + R * (f[0] - c[0]) / d, c[1] + R * (f[1] - c[1]) / d)

    tr, tl = tangent(fr), tangent(fl)
    th_l, th_r = math.atan2(tl[1] - c[1], tl[0] - c[0]), math.atan2(tr[1] - c[1], tr[0] - c[0])
    phi_r, phi_l = math.atan2(tr[1] - fr[1], tr[0] - fr[0]), math.atan2(tl[1] - fl[1], tl[0] - fl[0]) % (2 * math.pi)
    segs = [
        gm.Arc(c, R, th_l, (th_r - th_l) % (2 * math.pi)),
        gm.Arc(fr, r, phi_r, math.pi / 2 - phi_r),
        gm.Line((fr[0], yt), (fl[0], yt)),
        gm.Arc(fl, r, math.pi / 2, phi_l - math.pi / 2),
    ]
    return {"contour": segs, "d": gm.to_svg_path(segs), "y_top": yt, "height": yt - Y_APEX}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--r", type=float, required=True)
    ap.add_argument("--R", type=float, required=True)
    ap.add_argument("--tag")
    ap.add_argument("--levels", default="1,2,3")
    a = ap.parse_args()
    tag = a.tag or f"r{a.r:g}_R{a.R:g}"
    out = os.path.join(os.getcwd(), "out")
    cdir = os.path.join(out, "cases", tag)
    os.makedirs(cdir, exist_ok=True)
    dm = dome_down(a.r, a.R)
    base = json.load(open(os.path.join(os.getcwd(), "geometry.json")))
    geo = {"units": "mm", "objects": []}
    for o in base["objects"]:
        if o["id"] == "strip_conductor":
            geo["objects"].append({"id": "strip_conductor", "type": "path", "d": dm["d"]})
        elif o["id"] == "ground_plane_top":
            oo = dict(o); oo["y0"], oo["y1"] = dm["y_top"] + GAP, dm["y_top"] + GAP + 10
            geo["objects"].append(oo)
        elif o["id"] == "air_region":
            oo = dict(o); oo["y1"] = max(oo["y1"], dm["y_top"] + GAP + 12)
            geo["objects"].append(oo)
        else:
            geo["objects"].append(o)
    ph = json.load(open(os.path.join(os.getcwd(), "physics.json")))
    ph["control_points"] = [{"id": "b", "x": 0, "y": -17.0}, {"id": "t", "x": 0, "y": dm["y_top"] + 3.0}]
    pts = femm_lua.sampling_points(geo, ph)
    with open(os.path.join(cdir, "points.txt"), "w") as f:
        f.write("\n".join(f"{x} {y}" for x, y in pts) + "\n")
    levels = [next(l for l in ph["mesh_levels"] if l["level"] == int(x)) for x in a.levels.split(",")]
    res = [femm_runner.solve(geo, ph, lv, cdir, f"L{lv['level']}") for lv in levels]
    last = res[-1]
    rel = abs(res[-1]["max_E_V_per_m"] - res[-2]["max_E_V_per_m"]) / res[-1]["max_E_V_per_m"] if len(res) > 1 else 0.0
    C = abs(last["conductors"]["strip_conductor"]["Q_C"]) / 1e4 * 1e12
    U = 1e4 * 4.0 / last["max_E_kV_per_mm"]
    row = {
        "r_mm": a.r, "R_mm": a.R, "geometry": {"type": "path", "d": dm["d"]},
        "top_plane_y0_mm": dm["y_top"] + GAP, "top_plane_y1_mm": dm["y_top"] + GAP + 10,
        "C_pF_per_m": C, "max_E_at_10kV_kV_per_mm": last["max_E_kV_per_mm"],
        "U_kV": U / 1000, "W_mJ_per_m": 0.5 * C * 1e-12 * U ** 2 * 1e3,
        "elements": last["elements"], "converged": rel <= 0.02, "rel_change": rel,
    }
    json.dump(row, open(os.path.join(out, "cases", tag + ".json"), "w"), ensure_ascii=False, indent=1)
    print(json.dumps(row, ensure_ascii=False))


if __name__ == "__main__":
    main()
