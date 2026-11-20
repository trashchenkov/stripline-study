# Формат `out/variants.json` (T5)

Массив 16 объектов, по одному на пару r, R.

```json
[
  {
    "r_mm": 1.0,
    "R_mm": 30.0,
    "geometry": {"type": "path", "d": "M..."},
    "top_plane_y0_mm": -2.0,
    "top_plane_y1_mm": 8.0,
    "C_pF_per_m": 150.0,
    "max_E_at_10kV_kV_per_mm": 2.5,
    "U_kV": 16.0,
    "W_mJ_per_m": 19.2,
    "rank": 1,
    "elements": 20000,
    "converged": true,
    "rel_change": 0.01
  }
]
```

`W_mJ_per_m = 0.5 · C_pF_per_m · 1e-12 · (U_kV · 1e3)² · 1e3`.
