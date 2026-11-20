#!/usr/bin/env python3
"""Проверки результата задачи. Не блокируют прогон, пишут JSON.

    python3 verifier/verify.py T2 runs/<run>/workspace [--out checks.json]

Код проверяет механические критерии; T4/T5-смысл помечается manual_required.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import geomodel as gm  # noqa: E402

GEO_SOURCE = None  # откуда прочитана проверяемая геометрия


def src_label() -> str:
    if GEO_SOURCE and GEO_SOURCE.replace(os.sep, "/").endswith("/out/geometry.json"):
        return "out/geometry.json"
    return "geometry.json (базовая версия)"


def load_geo(path):
    d = json.load(open(path))
    return d, {o["id"]: gm.contour(o) for o in d.get("objects", [])}


def check_units(geo, c, res):
    return geo.get("units") == "mm", f"units={geo.get('units')}"


def check_bbox(geo, c, res, ch):
    if ch["object"] not in c:
        return False, "нет объекта"
    x0, y0, x1, y1 = gm.bbox(c[ch["object"]])
    ok = abs((x1 - x0) - ch["width"]) <= ch.get("tol", 0.05) and abs((y1 - y0) - ch["height"]) <= ch.get("tol", 0.05)
    return ok, f"{x1-x0:.3f} x {y1-y0:.3f}"


def check_bbox_each(geo, c, res, ch):
    t = ch.get("tol", 0.05)
    bad = []
    for oid in ch["objects"]:
        if oid not in c:
            bad.append(f"{oid}: нет")
            continue
        x0, y0, x1, y1 = gm.bbox(c[oid])
        if abs((x1 - x0) - ch["width"]) > t or abs((y1 - y0) - ch["height"]) > t:
            bad.append(f"{oid}: {x1-x0:.3f} x {y1-y0:.3f}")
    return not bad, "; ".join(bad) or "ok"


def check_gap(geo, c, res, ch):
    a, b = ch["between"]
    if a not in c or b not in c:
        return False, "нет объекта"
    d = gm.contour_distance(c[a], c[b])[0]
    lo, hi = ch.get("min"), ch.get("max")
    ok = (lo is None or d >= lo) and (hi is None or d <= hi)
    return ok, f"gap={d:.4f}"


def check_potentials(geo, c, res, ch):
    got = res.get("potentials_V") or {}
    bad = []
    for oid, v in ch["expected"].items():
        if abs(float(got.get(oid, 1e99)) - v) > ch.get("tol", 1.0):
            bad.append(f"{oid}={got.get(oid)}")
    return not bad, "; ".join(bad) or "ok"


def check_closed(geo, c, res):
    bad = []
    for oid, cc in c.items():
        for i, s in enumerate(cc):
            if gm.dist(s.b, cc[(i + 1) % len(cc)].a) > 1e-6:
                bad.append(oid)
                break
    return not bad, ", ".join(bad) or "ok"


def check_self(geo, c, res):
    bad = []
    for oid, cc in c.items():
        n = len(cc)
        for i in range(n):
            for j in range(i + 2, n):
                if i == 0 and j == n - 1:
                    continue
                if gm.intersections(cc[i], cc[j]):
                    bad.append(f"{oid}:{i}/{j}")
    return not bad, ", ".join(bad) or "ok"


def check_gap_balance(geo, c, res, ch):
    a, b = ch["between"]
    if a not in c or b[0] not in c or b[1] not in c:
        return False, "нет объекта"
    d1 = gm.contour_distance(c[a], c[b[0]])[0]
    d2 = gm.contour_distance(c[a], c[b[1]])[0]
    return abs(d1 - d2) <= ch.get("tol", 0.1), f"{d1:.3f}/{d2:.3f}"


def check_convergence(geo, c, res, ch):
    rel = (res.get("convergence") or {}).get("rel_change")
    if rel is None:
        return False, "нет rel_change"
    return rel <= ch["rel_tol"], f"rel={rel}"


def check_range(geo, c, res, ch):
    v = res.get(ch["quantity"])
    if v is None:
        return False, "нет величины"
    ok = (ch.get("min") is None or v >= ch["min"]) and (ch.get("max") is None or v <= ch["max"])
    return ok, str(v)


def check_max_value(geo, c, res, ch):
    """Верхний предел величины с относительным допуском на разброс сетки/выборки (tol_rel, доля)."""
    v = res.get(ch["quantity"])
    if v is None:
        return False, "нет величины"
    tol = ch.get("tol_rel", 0.0)
    lim = ch["max"] * (1 + tol)
    return v <= lim, f"{v} (предел {ch['max']:g}, допуск {tol * 100:g} % -> {lim:.4g})"


def corner_radius(cc, corner):
    best = None
    for s in cc:
        if isinstance(s, gm.Arc) and abs(abs(s.sweep) - math.pi / 2) < 0.05:
            if abs(gm.dist(s.c, corner) - s.r * math.sqrt(2)) < 0.05 * s.r + 1e-3:
                best = s.r if best is None else min(best, s.r)
    if best is not None:
        return best
    if any(gm.dist(s.a, corner) < 1e-6 for s in cc):
        return 0.0
    return None


def check_radius(geo, c, res, ch, base):
    oid = ch["object"]
    if oid not in c:
        return False, "нет объекта"
    if base and oid in [o["id"] for o in base.get("objects", [])]:
        b = gm.contour(base["objects"][[o["id"] for o in base["objects"]].index(oid)])
    else:
        b = c[oid]
    x0, y0, x1, y1 = gm.bbox(b)
    corners = {"bottom_left": (x0, y0), "bottom_right": (x1, y0), "top_right": (x1, y1), "top_left": (x0, y1)}
    names = list(corners) if ch.get("corners") == "all" else ch.get("corners", [])
    vals = {k: corner_radius(c[oid], corners[k]) for k in names}
    ok = all(v is not None and ch.get("min", 0) - 1e-6 <= v <= ch.get("max", 1e9) + 1e-6 for v in vals.values())
    return ok, f"{src_label()}: " + json.dumps(vals)


def check_radius_max(geo, c, res, ch, base):
    return check_radius(geo, c, res, {**ch, "min": 0.0, "corners": "all"}, base)


def check_geometry_saved(geo, c, res, ch, base):
    """Проверяемая геометрия должна отличаться от базовой: иначе правка не сдана файлом."""
    if GEO_SOURCE is None:
        return False, "нет проверяемой геометрии"
    if base is None:
        return True, src_label()
    oid = ch["object"]
    if oid not in c:
        return False, "нет объекта"
    old = gm.contour(base["objects"][[o["id"] for o in base["objects"]].index(oid)])
    if gm.same_contour(c[oid], old):
        return False, f"{oid} совпадает с базовой геометрией ({src_label()})"
    return True, f"{src_label()}: {oid} отличается от базовой"


def check_radius_matches_result(geo, c, res, ch, base):
    """Радиус из result.json должен совпадать с радиусом в сданной геометрии."""
    oid = ch["object"]
    if oid not in c:
        return False, "нет объекта"
    rep = res.get("radius_mm")
    if rep is None:
        return False, "нет radius_mm"
    old = gm.contour(base["objects"][[o["id"] for o in base["objects"]].index(oid)])
    x0, y0, x1, y1 = gm.bbox(old)
    corners = {"bottom_left": (x0, y0), "bottom_right": (x1, y0), "top_right": (x1, y1), "top_left": (x0, y1)}
    vals = {k: corner_radius(c[oid], corners[k]) for k in corners}
    tol = ch.get("tol", 0.05)
    bad = [f"{k}={v}" for k, v in vals.items() if v is None or abs(v - float(rep)) > tol]
    return not bad, f"radius_mm={rep}; " + (", ".join(bad) if bad else "геометрия совпадает")


def check_unchanged(geo, c, res, ch, base):
    bad = []
    for oid in ch["objects"]:
        if oid not in c:
            bad.append(f"{oid}: нет")
            continue
        old = gm.contour(base["objects"][[o["id"] for o in base["objects"]].index(oid)])
        if not gm.same_contour(c[oid], old):
            bad.append(oid)
    return not bad, ", ".join(bad) or "ok"


def check_alternative(geo, c, res, ch):
    alt = res.get("alternative") or {}
    r = alt.get("radius_mm")
    return (res.get("conflict_declared") is True and r is not None and ch.get("min", 0) <= float(r) <= ch.get("max", 1e9)), f"alternative={alt}, conflict={res.get('conflict_declared')}"


def check_geometry_present(geo, c, res):
    return bool(c), f"objects={len(c)}"


def check_points(geo, c, res, ch):
    if not c:
        return False, "нет объектов геометрии"
    p = os.path.join(ch.get("workspace") or "", "out", "points.txt")
    if not p or not os.path.exists(p):
        return None, "нет out/points.txt"
    try:
        pts = [tuple(map(float, x.split())) for x in open(p) if x.strip()][:200000]
    except Exception as e:  # noqa: BLE001
        return False, f"points: {e}"
    ids = list((res.get("potentials_V") or {}).keys()) or [x for x in c if x != "air_region"]
    off = ch.get("offset", 0.05)
    bad = []
    for x, y in pts:
        for oid in ids:
            if oid not in c:
                continue
            if gm.point_in_contour((x, y), c[oid]) or min(gm.point_seg_dist((x, y), s)[0] for s in c[oid]) < off:
                bad.append((round(x, 3), round(y, 3), oid))
                break
    return not bad, f"bad={len(bad)} {bad[:5]}"


def check_manual(geo, c, res, ch):
    v = res.get(ch["field"])
    return v is not None, f"{ch['field']}={v!r}"


def check_variants(ws, ch):
    p = os.path.join(ws, "out", "variants.json")
    if not os.path.exists(p):
        return False, "нет variants.json"
    try:
        rows = json.load(open(p))
    except Exception as e:  # noqa: BLE001
        return False, f"json: {e}"
    t = ch["type"]
    if t == "json_count":
        return len(rows) == ch["count"], f"n={len(rows)}"
    if t == "json_grid":
        got = {(float(r["r_mm"]), float(r["R_mm"])) for r in rows}
        exp = {(float(r), float(R)) for r in ch["rs"] for R in ch["Rs"]}
        return got == exp, f"missing={exp-got} extra={got-exp}"
    if t == "all_valid":
        bad = []
        for i, r in enumerate(rows):
            try:
                cc = gm.contour({"id": "x", **r["geometry"]})
                if gm.area(cc) <= 0 or any(gm.intersections(cc[a], cc[b]) for a in range(len(cc)) for b in range(a + 2, len(cc)) if not (a == 0 and b == len(cc) - 1)):
                    bad.append(i)
            except Exception:  # noqa: BLE001
                bad.append(i)
        return not bad, f"bad={bad}"
    if t == "all_gaps":
        bottom = gm.contour({"id": "pb", "type": "rounded_rect", "x0": -50, "y0": -30, "x1": 50, "y1": -20, "radii": {}})
        bad = []
        for i, r in enumerate(rows):
            try:
                cc = gm.contour({"id": "x", **r["geometry"]})
                top = gm.contour({"id": "pt", "type": "rounded_rect", "x0": -50, "y0": r["top_plane_y0_mm"], "x1": 50, "y1": r["top_plane_y1_mm"], "radii": {}})
            except Exception:  # noqa: BLE001
                bad.append(i)
                continue
            ds = [gm.contour_distance(cc, p)[0] for p in (top, bottom)]
            if not all(ch.get("min", 0) <= d <= ch.get("max", 1e9) for d in ds):
                bad.append(i)
        return not bad, f"bad={bad}"
    if t == "convergence_points":
        pts = [r for r in rows if r.get("converged") is True and r.get("rel_change") is not None and r["rel_change"] <= ch["rel_tol"]]
        return len(pts) >= ch["min_points"], f"converged={len(pts)}"
    if t == "recompute":
        bad = []
        for i, r in enumerate(rows):
            try:
                w = 0.5 * r["C_pF_per_m"] * 1e-12 * (r["U_kV"] * 1e3) ** 2 * 1e3
                if abs(w - r["W_mJ_per_m"]) / r["W_mJ_per_m"] > ch["rel_tol"]:
                    bad.append(i)
            except Exception:  # noqa: BLE001
                bad.append(i)
        return not bad, f"bad={bad}"
    if t == "ranking_consistent":
        try:
            order = sorted(range(len(rows)), key=lambda i: -rows[i][ch["sort_by"]])
            bad = [i for pos, i in enumerate(order, 1) if rows[i].get("rank") != pos]
            return not bad, f"bad={bad}"
        except Exception as e:  # noqa: BLE001
            return False, f"rank: {e}"
    return None, "неизвестная проверка"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("task")
    ap.add_argument("workspace")
    ap.add_argument("--out")
    a = ap.parse_args()
    task_dir = os.path.join(ROOT, "tasks", a.task)
    cfg = json.load(open(os.path.join(task_dir, "task.json")))
    hid = json.load(open(os.path.join(ROOT, cfg["verification"]["hidden"])))
    base = None
    bpath = os.path.join(task_dir, "workspace", "geometry.json")
    if os.path.exists(bpath):
        base, _ = load_geo(bpath)
    gp = os.path.join(a.workspace, "out", "geometry.json")
    if not os.path.exists(gp):
        gp = os.path.join(a.workspace, "geometry.json")
    global GEO_SOURCE
    GEO_SOURCE = gp if os.path.exists(gp) else None
    geo, c = load_geo(gp) if os.path.exists(gp) else ({"units": None, "objects": []}, {})
    rp = os.path.join(a.workspace, "out", "result.json")
    res = json.load(open(rp)) if os.path.exists(rp) else {}

    out = []
    for ch in hid["checks"]:
        t = ch["type"]
        fn = {
            "units": lambda: check_units(geo, c, res),
            "bbox": lambda: check_bbox(geo, c, res, ch),
            "bbox_each": lambda: check_bbox_each(geo, c, res, ch),
            "min_gap": lambda: check_gap(geo, c, res, ch),
            "gap_balance": lambda: check_gap_balance(geo, c, res, ch),
            "potentials": lambda: check_potentials(geo, c, res, ch),
            "closed_contours": lambda: check_closed(geo, c, res),
            "no_self_intersections": lambda: check_self(geo, c, res),
            "convergence": lambda: check_convergence(geo, c, res, ch),
            "range": lambda: check_range(geo, c, res, ch),
            "max": lambda: check_max_value(geo, c, res, ch),
            "corner_radius": lambda: check_radius(geo, c, res, ch, base),
            "corner_radius_max": lambda: check_radius_max(geo, c, res, ch, base),
            "geometry_saved": lambda: check_geometry_saved(geo, c, res, ch, base),
            "radius_matches_result": lambda: check_radius_matches_result(geo, c, res, ch, base),
            "unchanged": lambda: check_unchanged(geo, c, res, ch, base),
            "alternative_valid": lambda: check_alternative(geo, c, res, ch),
            "manual_required": lambda: check_manual(geo, c, res, ch),
            "reported": lambda: check_manual(geo, c, res, ch),
            "geometry_present": lambda: check_geometry_present(geo, c, res),
            "sampling_points": lambda: check_points(geo, c, res, {**ch, "workspace": a.workspace}),
            "json_count": lambda: check_variants(a.workspace, ch),
            "json_grid": lambda: check_variants(a.workspace, ch),
            "all_valid": lambda: check_variants(a.workspace, ch),
            "all_gaps": lambda: check_variants(a.workspace, ch),
            "convergence_points": lambda: check_variants(a.workspace, ch),
            "recompute": lambda: check_variants(a.workspace, ch),
            "ranking_consistent": lambda: check_variants(a.workspace, ch),
        }.get(t)
        try:
            ok, detail = fn() if fn else (None, "неизвестная проверка")
        except Exception as e:  # noqa: BLE001
            ok, detail = False, f"error: {e}"
        out.append({"id": ch["id"], "type": t, "status": "manual" if t in ("manual_required", "reported") and ok else
                    "pass" if ok else "fail" if ok is not None else "skip", "detail": detail})
    report = {"task": a.task, "workspace": a.workspace, "checks": out,
              "passed": all(x["status"] in ("pass", "manual", "skip") for x in out),
              "manual_required": [x["id"] for x in out if x["status"] == "manual"]}
    text = json.dumps(report, ensure_ascii=False, indent=1)
    if a.out:
        open(a.out, "w").write(text)
    print(text)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
