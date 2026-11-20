#!/usr/bin/env python3
"""Готовый прогон FEMM по geometry.json.

    python3 run_case.py --radius 4.5 --levels 1,2,3

Пишет out/geometry.json, out/points.txt, out/result.json и модели в out/femm.
Задачу выбора радиуса не решает.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import femm_lua  # noqa: E402
import femm_runner  # noqa: E402
import geomodel as gm  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--radius", type=float)
    ap.add_argument("--levels", default="1,2,3")
    ap.add_argument("--tag", default="case")
    a = ap.parse_args()
    out = os.path.join(os.getcwd(), "out")
    os.makedirs(out, exist_ok=True)
    src = os.path.join(out, "geometry.json")
    if not os.path.exists(src):
        src = os.path.join(os.getcwd(), "geometry.json")
    geo = json.load(open(src))
    if a.radius is not None:
        for o in geo["objects"]:
            if o["id"] == "strip_conductor" and o.get("type") == "rounded_rect":
                o["radii"] = {k: a.radius for k in gm.CORNERS}
    ph = json.load(open(os.path.join(os.getcwd(), "physics.json")))
    pts = femm_lua.sampling_points(geo, ph)
    with open(os.path.join(out, "points.txt"), "w") as f:
        f.write("\n".join(f"{x} {y}" for x, y in pts) + "\n")
    levels = [next(l for l in ph["mesh_levels"] if l["level"] == int(x)) for x in a.levels.split(",")]
    res = []
    for lv in levels:
        r = femm_runner.solve(geo, ph, lv, os.path.join(out, "femm"), f"{a.tag}_L{lv['level']}")
        res.append(r)
    last = res[-1]
    rel = abs(res[-1]["max_E_V_per_m"] - res[-2]["max_E_V_per_m"]) / res[-1]["max_E_V_per_m"] if len(res) > 1 else 0.0
    C = abs(last["conductors"]["strip_conductor"]["Q_C"]) / 1e4 * 1e12
    result = {
        "task": "case", "status": "ok",
        "potentials_V": {"strip_conductor": 10000.0, "ground_plane_top": 0.0, "ground_plane_bottom": 0.0},
        "convergence": {"levels": [lv["level"] for lv in levels],
                        "max_E_kV_per_mm": [x["max_E_kV_per_mm"] for x in res], "rel_change": rel},
        "C_pF_per_m": C, "max_E_kV_per_mm": last["max_E_kV_per_mm"], "max_E_at": last["max_E_at"],
        "elements": [x["elements"] for x in res], "radius_mm": a.radius,
        "margin_kV_per_mm": 2.2 - last["max_E_kV_per_mm"],
    }
    json.dump(geo, open(os.path.join(out, "geometry.json"), "w"), ensure_ascii=False, indent=1)
    json.dump(result, open(os.path.join(out, "result.json"), "w"), ensure_ascii=False, indent=1)
    print(json.dumps({k: result[k] for k in ("C_pF_per_m", "max_E_kV_per_mm", "margin_kV_per_mm")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
