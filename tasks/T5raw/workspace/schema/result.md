# Формат результата `out/result.json`

Обязательный файл для T1–T4. T5 сдаёт `out/variants.json` по `schema/variants.md`.

```json
{
  "task": "T2",
  "status": "ok",
  "potentials_V": {"strip_conductor": 10000.0, "ground_plane_top": 0.0, "ground_plane_bottom": 0.0},
  "convergence": {"levels": [1, 2, 3], "max_E_kV_per_mm": [3.1, 2.4, 2.19], "rel_change": 0.017},
  "C_pF_per_m": 142.0,
  "max_E_kV_per_mm": 2.19,
  "max_E_at": [12.4, -8.1],
  "elements": [10000, 20000, 40000],
  "radius_mm": 4.2,
  "margin_kV_per_mm": 0.01,
  "defects": ["..."],
  "conflict_declared": false,
  "reason": "...",
  "reason_sum_radii": "7+7=14 > 10",
  "alternative": {"radius_mm": 5.0},
  "optimum_rationale": "..."
}
```

Поля, не относящиеся к задаче, можно опускать. Числа — в мм, кВ/мм, пФ/м. `rel_change` — относительное изменение max|E| между двумя последними уровнями.
