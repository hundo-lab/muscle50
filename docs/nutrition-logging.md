# Nutrition Logging MVP

Nutrition Logging turns Nutrition Core into a usable intake log: a small personal food
catalog, structured meal entry, and per-meal / daily consumed totals for kcal, protein,
carbohydrate and fat.

**Intake only.** Explicit daily targets and the comparison with intake (`muscle50 nutrition
target`, `muscle50 nutrition status`) are a separate layer on top: see `nutrition-targets.md`.
Not implemented yet:

- calculated targets (protein per kg, calorie targets, training/swim/rest day targets);
- menu or pre/post-workout meal recommendations;
- free-text meal parsing (`"아침: 닭가슴살 200g, 계란 2개..."`). The `MealParser` port stays
  unimplemented; input is structured CLI flags only.
- public food databases, barcode or photo lookup. Nothing is looked up or estimated from a name.

## Architecture

No migration: everything fits `003_nutrition.sql`. Reused Nutrition Core pieces:

| Concept | Reused as |
| --- | --- |
| Catalog food | `FoodNutritionProfile` (`profile_id` = food ID, `name` = display name, `aliases`) |
| Food nutrition | one `NutritionFact` per food (`fact_id` `food:<id>:1`), basis quantity/unit + `NutritionProvenance` |
| Meal / item | `Meal`, `MealItem` (`food_profile_id`, quantity, `QuantityUnit`) |
| Scaling | `NutritionFact.calculate` (28-digit half-even `Decimal`, same unit only) |
| Totals | `aggregate_meal`, `aggregate_day` (`totals`, `known_subtotals`, `incomplete_fields`, `estimated_fields`) |
| Storage | `SqliteFoodNutritionRepository` (+ new `list_all`), `SqliteMealRepository` |

New code: `application/nutrition_logging.py` (use cases `AddFood`, `ListFoods`, `ShowFood`,
`LogMeal`, `ShowDailyIntake`), `presentation/nutrition_terminal.py` (text + JSON), and the
`muscle50 nutrition` command group in `cli.py`.

### Snapshot at log time

When a meal is logged, for each item the food's fact history for the logged unit is copied
onto the meal item as item-owned facts, as `nutrition-core.md` intends ("snapshotting the
facts used for the historical meal"):

- numbers, basis, estimate range and provenance (source type, accuracy, reference,
  created_at) are copied verbatim;
- the copy's `fact_id` is `<meal_id>:<sequence>:<catalog fact_id>`, so each item names the
  exact catalog fact it came from, and `food_profile_id` names the food;
- `supersedes_fact_id` is remapped to the copy of the superseded fact. Supersession is
  decided per nutrient (a protein-only correction supersedes the old fact for protein only),
  so copying only the current winners would let the item pick differently from the catalog.
  With the links kept, the item's per-nutrient selection is the catalog's selection.

A later catalog correction (a superseding fact appended to the food) therefore does not
change meals already logged; new meals use the corrected fact.

## Commands

All commands use `%LOCALAPPDATA%\muscle50` (or `MUSCLE50_HOME`) and never call Garmin.
Errors print `오류: ...` to stderr and exit 1 (argparse usage errors exit 2). Nothing is
written when a command fails.

### Add a personal food

```powershell
muscle50 nutrition food add --id chicken-breast --name 닭가슴살 --per 100 g `
  --kcal 110 --protein 23 --carbs 0 --fat 1.5 `
  --source nutrition_label --accuracy exact --source-ref "package label 2026-10"
muscle50 nutrition food add --id egg --name 계란 --per 1 count `
  --kcal 75 --protein 6.5 --carbs 0.5 --fat 5 --source user_provided --accuracy estimated
muscle50 nutrition food add --id hetbahn --name 햇반 --per 1 pack `
  --kcal 300 --protein 5 --carbs 66 --fat unknown --source nutrition_label --accuracy exact
muscle50 nutrition food add --id banana --name 바나나 --per 1 piece `
  --kcal 90 --protein 1 --carbs 23 --fat 0.3 --source user_provided --accuracy estimated
```

(The numbers above illustrate syntax only; enter the values from your own label or source.)

- `--id`: stable ID used when logging. One token of letters (Hangul allowed), digits, `_`,
  `.`, `-`.
- `--name`: display name (Korean is fine). `--alias NAME` adds another name (repeatable).
- `--per QTY UNIT`: the reference quantity the values describe.
- `--kcal --protein --carbs --fat`: all four are **required**. A number (`0` is a real zero),
  or `unknown` to record the nutrient as missing. At least one must be a number. Numbers must
  be plain decimals (`200`, `1.5`); `1e3`, `-5`, `.5`, `NaN`, `1,000` are rejected.
- `--source`: `nutrition_label`, `user_provided`, `known_product`, `food_database`
  (meaning you copied the numbers from one yourself). Estimate sources
  (`visual_estimate`, `language_estimate`) are reserved for a future parser and refused.
- `--accuracy`: `exact` or `estimated`. No default.
- `--source-ref`: free text; default `entered with muscle50 nutrition food add`.

Duplicates: an existing food ID is refused, as is a name or alias that already matches any
food's name or alias (case-insensitive). The existing food is never changed. There is no
edit command; see Limitations.

```powershell
muscle50 nutrition food list            # ID, name, active facts per food
muscle50 nutrition food show egg        # full fact history, reference, recorded time
muscle50 nutrition food list --json
```

### Log a structured meal

```powershell
muscle50 nutrition log --date 2026-10-02 --meal breakfast `
  --item chicken-breast 200 g --item egg 2 count --item hetbahn 1 pack --item banana 1 piece
muscle50 nutrition log --meal lunch --time 12:30 --item chicken-breast 150.5 g
muscle50 nutrition log --meal snack --additional --item banana 1 piece
```

- `--meal`: `breakfast`, `lunch`, `dinner`, `snack`, `other`.
- `--date`: default today on this computer (same convention as `muscle50 daily`).
- `--time HH:MM`: optional. Without it the meal is stored at local 00:00 of the date and
  shown as "time not recorded".
- `--item FOOD_ID QTY UNIT`: repeatable; the unit must be one the food has nutrition for.
  Fractional quantities are allowed for every unit (`0.5 pack`, `1.5 piece`).
- A second meal of the same type on the same date is refused unless `--additional` is given
  (prevents an accidental re-run from doubling intake). Meal IDs are
  `<date>-<meal>-<n>`, e.g. `2026-10-02-breakfast-1`, `2026-10-02-snack-2`.
- The command prints the stored meal (re-read from the database) with per-item nutrients and
  the meal total; `--json` prints the same as JSON.

### View a day's intake

```powershell
muscle50 nutrition day                  # today
muscle50 nutrition day --date 2026-10-02
muscle50 nutrition day --date 2026-10-02 --json
```

Text output (synthetic example values):

```text
Nutrition intake 2026-10-02 (UTC+09:00)
Consumed intake only. Compare with targets: muscle50 nutrition status

[breakfast] 2026-10-02-breakfast-1 (2026-10-02, time not recorded)
  1. 닭가슴살 (chicken-breast) 200 g: kcal 220 | P 36 g | C 2 g | F 6 g
     source: nutrition_label/exact
  2. 계란 (egg) 2 count: kcal 140 | P 12 g | C 1 g | F 10 g
     source: user_provided/estimated
  3. 햇반 (hetbahn) 1 pack: kcal 300 | P 5 g | C 68 g | F missing
     source: nutrition_label/exact
     missing: fat
  4. 바나나 (banana) 1 piece: kcal 90 | P 1 g | C 23 g | F 0.3 g
     source: user_provided/exact
  Meal total: kcal 750 (estimated) | P 54 g (estimated) | C 94 g (estimated) | F incomplete (known items only: 16.3 g (estimated))

Consumed (1 meal, 4 items):
  kcal          750 (estimated)
  Protein       54 g (estimated)
  Carbohydrate  94 g (estimated)
  Fat           incomplete (known items only: 16.3 g (estimated))
Incomplete: these totals are not precise because an item has no value for them:
  fat: 2026-10-02-breakfast-1 item 3 햇반 (hetbahn)
Estimated: kcal, protein, carbohydrate, fat include values from facts marked estimated.
```

The day is this computer's local calendar date, using its UTC offset as a fixed offset (no
IANA zone lookup, so no `tzdata` dependency). Meals are ordered by time, then meal type.

## Units and scaling

Supported units are Nutrition Core's `QuantityUnit`: `g`, `ml`, `count`, `pack`, `piece`,
`animal`, `serving`. Scaling is `value * logged quantity / reference quantity` in the same
unit only (100 g facts, 200 g logged: protein 18 g becomes 36 g). Units are never converted:
`count`, `piece` and `pack` are distinct from each other and from `g`; there is no hidden
"1 egg = N g". Logging a food in a unit it has no facts for is refused, naming the units it
does have (e.g. 햇반 declared per pack cannot be logged as `210 g`; declare the food per 210 g
or log `1 pack`).

## Source, accuracy and missing data

- Each item shows the `source_type/accuracy` of the facts it used; JSON carries the full
  provenance and the snapshot fact ID per nutrient.
- A total that includes any estimated fact is marked `(estimated)`; JSON lists
  `estimated_fields`.
- A nutrient recorded as `unknown` is missing, never 0. Any item without a value for a
  nutrient makes that nutrient's meal and day total **incomplete**: text shows "incomplete"
  with the known-items-only subtotal explicitly labeled, and lists which meal item is missing
  what; JSON sets the total to `null`, gives `known_subtotals`, `incomplete_fields`,
  per-item `missing_fields` and `complete: false`.
- A day without meals says "No meals recorded for this day."

## JSON

`--json` output is deterministic for identical stored data: fixed key order, Decimal values
as exact canonical strings (no rounding, no floats), nutrient lists in
kcal/protein/carbohydrate/fat order, ASCII-escaped. Text output rounds to 0.1 for display
only.

## Limitations

- **No edit or delete.** Nutrition facts are append-only (`nutrition_facts` update/delete
  triggers) and meal items reference their snapshot facts with `ON DELETE RESTRICT`, so a
  logged meal cannot be deleted without changing the schema's append-only guarantee. A
  correction design (e.g. void/replacement records or appended superseding item facts) is
  deferred. The duplicate-meal guard exists because of this. Catalog corrections are possible
  in code via `append_nutrition_fact` (superseding fact), but there is no CLI for it yet.
- One fact per food from the CLI; no per-food unit conversions (e.g. `1 pack = 210 g`).
- Without `--time` a meal is stored at local 00:00; `--time 00:00` is displayed the same way.
- The day boundary uses this computer's current UTC offset rules; meals logged under a
  different offset are still found by their absolute time.
- No recommendations, weekly analytics, parser, Telegram, external databases. Targets and
  remaining amounts are in `muscle50 nutrition status` (`nutrition-targets.md`), not in `day`.
