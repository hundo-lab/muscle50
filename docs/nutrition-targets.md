# Nutrition Targets + Daily Nutrition Status (v1)

Daily targets for kcal, protein, carbohydrate and fat that you set explicitly, and a daily
status that compares a date's logged intake (Nutrition Logging) with those targets.

**Not nutrition-aware yet:** `muscle50 recommend` and `muscle50 daily` do not read targets or
intake. Not implemented: automatic target calculation (per kg, TDEE, ...), training/rest-day
target cycling, Garmin-based adjustment, food or meal suggestions, free-text meal parsing,
meal/food edit or delete, unit conversion.

## Architecture

No migration. Targets are one small user setting, not nutrition fact history, so they are a
versioned JSON file under the muscle50 home instead of a SQLite table:

```text
%LOCALAPPDATA%\muscle50\config\nutrition_targets.json   (or MUSCLE50_HOME\config\...)
```

| Layer | Code |
| --- | --- |
| Domain | `domain/nutrition_targets.py`: `ExactTarget`, `RangeTarget`, `NutritionTargets`, `TargetStatus`, `evaluate_nutrient`/`evaluate_targets` |
| Application | `application/nutrition_targets.py`: `NutritionTargetRepository` port, `SetNutritionTarget`, `ShowNutritionTargets`, `ShowDailyNutritionStatus` |
| Storage | `infrastructure/nutrition_target_store.py`: `JsonNutritionTargetRepository` |
| Output | `presentation/nutrition_terminal.py`: `render_targets[_json]`, `render_nutrition_status[_json]` |

The status reuses `ShowDailyIntake` unchanged (same day selection, same `aggregate_day`
totals, known subtotals, incomplete/estimated fields and per-item missing nutrients). Nothing
is re-aggregated and no fact is re-selected.

Targets live apart from meals, so changing a target never rewrites logged data. There is one
current target set and **no target history**: the status for any date, including past dates,
compares that date's intake with the targets configured *now*. Every status line and JSON
entry shows the target it used.

### File format

```json
{
  "schema_version": 1,
  "targets": {
    "calories_kcal": {"kind": "exact", "value": "2400"},
    "protein_g": {"kind": "range", "minimum": "170", "maximum": "180"},
    "carbohydrate_g": {"kind": "unset"},
    "fat_g": {"kind": "exact", "value": "80"}
  }
}
```

(Synthetic numbers.) Written atomically (temporary file + replace), LF, deterministic key
order. Read strictly: every nutrient must be listed with an explicit kind, values must be
canonical decimal strings (JSON numbers are refused, so no value passes through a binary
float), unknown keys are refused. A malformed file is an error (`오류: nutrition target file
... is not valid: ...`, exit 1), never "no targets"; `target set` refuses to overwrite it. A
missing file means no targets are set; `target show` and `status` never create it, and
`ensure_directories` does not create `config\`.

## Target model

| Kind | Meaning | Validation |
| --- | --- | --- |
| exact | one value, e.g. fat 80 g | finite, > 0 |
| range | inclusive `minimum..maximum`, e.g. protein 170-180 g | both finite, > 0, minimum <= maximum (equal allowed) |
| unset | no target | — |

Unset is not zero, and 0 is not a valid target (use `--unset`). Values are `Decimal`; there is
no float arithmetic anywhere in targets or status. Nothing is calculated or inferred.

## Status semantics

Per nutrient:

| Field | Meaning |
| --- | --- |
| `target` | `{"kind": "exact", "value"}`, `{"kind": "range", "minimum", "maximum"}` or `{"kind": "unset"}` |
| `consumed` | the day total; `null` unless every logged item has a value for the nutrient |
| `known_subtotal` | sum over the items that do have a value (Nutrition Core's known subtotal); `null` if none do |
| `complete` | every logged item has a value (false on a day without meals) |
| `estimated` | the total includes a fact marked estimated |
| `status` | see below |
| `remaining` | amount still needed to reach the exact value or the range minimum (`"0"` once reached) |
| `remaining_to_maximum` | range only: headroom up to the maximum (`"0"` at or above it); `null` for exact/unset |
| `excess` | amount above the exact value or the range maximum (`"0"` if not above) |
| `missing_items` | `meal_id`, `sequence`, `food_id`, `food_name` of each logged item without a value |

`remaining`, `remaining_to_maximum` and `excess` are never negative, and are `null` whenever
they cannot be known exactly (unset target, incomplete data, no meals).

Statuses (`status`):

| Status | When |
| --- | --- |
| `no_target` | target unset (consumed is still reported) |
| `no_intake_logged` | target set, no meal logged that day. Nutrition Core treats an empty day as incomplete, not as zero, so no remaining amount is claimed. |
| `below_target` / `target_reached` / `above_target` | exact target, complete data. Reached means exactly equal (Decimal equality, no tolerance). |
| `below_range` / `within_range` / `above_range` | range target, complete data. Both bounds are inside the range. |
| `indeterminate` | data incomplete and the known items prove nothing |

### Missing data: unknown is not zero

If any logged item has no value for a nutrient, that nutrient has no `consumed` total and no
`remaining`/`excess`; its `known_subtotal` and `missing_items` are shown instead. The only
conclusion drawn is one that is certain: nutrient values are validated non-negative, so the
missing items can only add to the known subtotal, which is therefore a lower bound of the real
total. When the known subtotal alone is **greater than** the exact value or the range maximum,
the status is `above_target` / `above_range` (with `complete: false` and `excess: null`).
Everything else is `indeterminate`, including a known subtotal exactly equal to the target
(reached or above, unknown which) and a known subtotal inside a range. Other nutrients that are
complete are evaluated normally.

The status uses point values. A total that includes estimated facts is flagged
`estimated: true` (text: `(estimated)`); its status is computed from the same point value.

## Commands

All commands use `%LOCALAPPDATA%\muscle50` (or `MUSCLE50_HOME`) and never call Garmin. Nutrient
names match `food add`: `kcal`, `protein`, `carbs`, `fat` (g).

```powershell
muscle50 nutrition target set protein --range 170 180   # inclusive range
muscle50 nutrition target set fat --exact 80
muscle50 nutrition target set kcal --unset               # remove a target
muscle50 nutrition target show [--json]
muscle50 nutrition status [--date YYYY-MM-DD] [--json]   # default: today on this computer
```

(Example numbers only; enter your own.) Exactly one of `--exact N`, `--range MIN MAX`,
`--unset` is required. Values are plain decimals (`80`, `172.5`); `0`, `-5`, `1e3`, `NaN`,
`1,000` and `MIN > MAX` are refused with nothing written. `target set` changes only the named
nutrient.

Text output (synthetic values; amounts rounded to 0.1 for display, a non-zero gap below 0.05
shows as `<0.1`, targets shown exactly):

```text
Nutrition status 2026-10-02 (UTC+09:00)
Logged intake compared with the currently configured daily targets.

Logged: 2 meals, 4 items
  kcal          1255.6 (estimated); target 2400 (exact): below target, 1144.4 to go
  Protein       172.1 g (estimated); target 170-180 g (range): within range, 7.9 g left to maximum
  Carbohydrate  80.5 g (estimated); no target
  Fat           incomplete (known items only: 22.5 g (estimated)); target 20 g (exact): above target (the known items alone exceed it; exact excess unknown)
Incomplete: no exact total or remaining amount, because an item has no value for:
  fat: 2026-10-02-breakfast-1 item 2 SynRice (syn-rice)
Estimated: kcal, protein, carbohydrate, fat include values from facts marked estimated.
```

With a fat target of 80 instead, the same day's fat line reads
`cannot tell yet (incomplete); remaining unknown`.

## JSON contract (`nutrition status --json`)

Deterministic for identical stored data and targets (fixed key order, ASCII-escaped, exact
canonical Decimal strings, no floats). `null` only where a value is genuinely unknown or does
not apply; unset targets are `{"kind": "unset"}`, never `null`. Program against `status`,
`complete` and the `target.kind`, not the text.

```json
{
  "date": "2026-10-02",
  "timezone": "+09:00",
  "scope": "intake_vs_current_targets",
  "meal_count": 2,
  "item_count": 4,
  "nutrients": {
    "calories_kcal": {"target": {"kind": "exact", "value": "2400"}, "status": "below_target", "complete": true, "...": "..."},
    "protein_g": {
      "target": {"kind": "range", "minimum": "170", "maximum": "180"},
      "status": "within_range",
      "complete": true,
      "estimated": true,
      "consumed": "172.09",
      "known_subtotal": "172.09",
      "remaining": "0",
      "remaining_to_maximum": "7.91",
      "excess": "0",
      "missing_items": []
    },
    "carbohydrate_g": {"target": {"kind": "unset"}, "status": "no_target", "remaining": null, "...": "..."},
    "fat_g": {
      "target": {"kind": "exact", "value": "20"},
      "status": "above_target",
      "complete": false,
      "estimated": true,
      "consumed": null,
      "known_subtotal": "22.515",
      "remaining": null,
      "remaining_to_maximum": null,
      "excess": null,
      "missing_items": [{"meal_id": "2026-10-02-breakfast-1", "sequence": 2, "food_id": "syn-rice", "food_name": "SynRice"}]
    }
  }
}
```

(`"...": "..."` abbreviates; real output always has every field.) `nutrients` keys are always
the four nutrients in this order. `target show --json` prints `{"targets": {...}}` with the same
per-nutrient target objects.

## Limitations

- One current target set, no history: a past date's status uses today's targets.
- Same targets every day (no training/rest/swim day variants), no automatic calculation.
- Recommendations (`muscle50 recommend`) and `muscle50 daily` are not nutrition-aware.
- A day without logged meals is `no_intake_logged`, not "0 consumed"; there is no way to mark
  a day as "logged, ate nothing".
- Estimated totals are compared by their point value; estimate ranges are not used (catalog
  foods never carry one).
- Text rounds amounts to 0.1; use `--json` for exact values.
