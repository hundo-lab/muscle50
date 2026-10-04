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

Logging fits `003_nutrition.sql`. The only later migration is `008_nutrition_meal_item_removals.sql`,
which records items removed by Meal Edit. Reused Nutrition Core pieces:

| Concept | Reused as |
| --- | --- |
| Catalog food | `FoodNutritionProfile` (`profile_id` = food ID, `name` = display name, `aliases`) |
| Food nutrition | `NutritionFact` versions per food (`fact_id` `food:<id>:<n>`, `n` = 1, 2, ...), basis quantity/unit + `NutritionProvenance`; a new version supersedes the previous one |
| Meal / item | `Meal`, `MealItem` (`food_profile_id`, quantity, `QuantityUnit`) |
| Scaling | `NutritionFact.calculate` (28-digit half-even `Decimal`, same unit only) |
| Totals | `aggregate_meal`, `aggregate_day` (`totals`, `known_subtotals`, `incomplete_fields`, `estimated_fields`) |
| Storage | `SqliteFoodNutritionRepository` (+ new `list_all`), `SqliteMealRepository` |

New code: `application/nutrition_logging.py` (use cases `AddFood`, `AddFoodFact`, `ListFoods`,
`ShowFood`, `LogMeal`, `ShowDailyIntake`, for Meal Edit `ShowMeal`, `AddMealItems`, `RemoveMealItem`,
`ReplaceMealItem`, and for Meal Repeat `RepeatMeal`), `presentation/nutrition_terminal.py` (text + JSON), and the
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

A later catalog correction (a superseding fact appended to the food, see "Add a new
nutrition fact version") therefore does not change meals already logged; new meals use the
corrected fact.

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
food's name or alias (case-insensitive). The existing food is never changed by `food add`;
to give it new nutrition numbers, add a new fact version (below).

```powershell
muscle50 nutrition food list            # ID, name, active facts per food
muscle50 nutrition food show egg        # full fact history, reference, recorded time
muscle50 nutrition food list --json
```

### Add a new nutrition fact version

```powershell
muscle50 nutrition food fact add chicken-breast --per 100 g `
  --kcal 120 --protein 18 --carbs 2 --fat 4 `
  --source food_database --accuracy estimated `
  --source-ref "generic lightly seasoned chicken breast estimate"
```

Appends fact `food:<id>:<n+1>` to an existing food. Nothing stored is updated or deleted: the
food ID, name, aliases and every earlier fact stay as they are, and `food show` lists the whole
history in recorded order (`(superseded)`, `(active, replaces food:<id>:<n>)`). The flags are
the same as `food add` (`--per`, all four nutrients, `--source`, `--accuracy`, `--source-ref`,
default reference `entered with muscle50 nutrition food fact add`), with the same validation.
`--json` prints the stored food like `food show --json`.

Activation: the new fact supersedes the food's current fact in the same unit and becomes the
fact used for every nutrient it gives, regardless of source priority (a `food_database`
estimate replaces an earlier `user_provided` exact fact, because you said so). `food list`
shows only active facts. The basis quantity may change (`per 200 g` -> `per 100 g`); the unit
may not (a version replaces a fact in the same unit; units are never converted).

Refused, with nothing written:

- unknown food ID, or a unit the food has no fact for;
- a nutrient the current fact knows given as `unknown` (supersession is per nutrient, so the
  old fact would silently stay in use for it; unknown cannot replace a known value). Filling
  in a nutrient that was `unknown` is fine;
- a version identical to the current fact (same numbers, basis, source, accuracy and
  reference), e.g. an accidental re-run;
- a history the CLI did not create where the result would be ambiguous (two current facts in
  the unit) or where an older fact would still win a nutrient over the new one.

Meals: already logged meals keep the facts they were snapshotted with (see "Snapshot at log
time"), so their values, `unknown`s, `nutrition day`, `nutrition status` and recommendation
output do not change. Meals logged afterwards use the new fact. An item's `source:` line shows
the provenance of the facts its values came from.

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
  (prevents an accidental re-run from doubling intake). To complete or correct a meal that is
  already logged, edit it with `nutrition meal add-item` (see below) instead. Meal IDs are
  `<date>-<meal>-<n>`, e.g. `2026-10-02-breakfast-1`, `2026-10-02-snack-2`.
- The command prints the stored meal (re-read from the database) with per-item nutrients and
  the meal total; `--json` prints the same as JSON.

### Edit a logged meal's items

When a meal is incomplete or has a wrong item, fix the existing meal rather than adding an
`--additional` one. The meal ID, date, type and time stay the same.

```powershell
muscle50 nutrition meal show 2026-10-02-breakfast-1            # items, quantities, fact versions (--json)
muscle50 nutrition meal add-item 2026-10-02-breakfast-1 --item hetbahn-white-210 210 g
muscle50 nutrition meal add-item 2026-10-02-breakfast-1 --item banana-medium 1 count
muscle50 nutrition meal remove-item 2026-10-02-breakfast-1 --item-number 3
muscle50 nutrition meal replace-item 2026-10-02-breakfast-1 --item-number 2 --item hetbahn-white-210 105 g
```

- **Item numbers** are the numbers `nutrition day` and `meal show` print. A number is never
  reused: new items get the next number after every item the meal ever had, including removed
  ones. After removing item 2 of 1, 2, 3, the meal has items 1 and 3, and the next added item
  is 4.
- **`add-item`** accepts `--item FOOD_ID QTY UNIT` as in `nutrition log`, and it can be repeated.
  Several items are added together or not at all. Each new item is snapshotted exactly like a
  logged item (see "Snapshot at log time") from the catalog **as it is now**. If the food got a
  new fact version after the meal was logged, the new item uses the new version. Items already in
  the meal keep their own snapshot, and nothing is recalculated or upgraded. `meal show` prints a
  `facts:` line per item with the catalog fact version(s) its values came from (for example
  `food:chicken-breast:1` for the old item and `food:chicken-breast:2` for one added later).
- **`remove-item`** removes one item. It disappears from `meal show`, `nutrition day`,
  `nutrition status`, `recommend` and `daily` at once, because totals are always computed from
  the stored items and nothing is cached. **The last item cannot be removed.** A meal always has
  at least one item, just as `nutrition log` refuses an empty meal. To change a one-item meal,
  use `replace-item`. Deleting a whole meal is not supported.
- **`replace-item`** adds the new item, with a fresh snapshot and the next number, and removes
  the old one in a single transaction, so either both happen or neither does. It also works on
  a one-item meal.
- Errors change nothing. A missing meal, unknown or removed item number, unknown food, a unit
  the food has no nutrition for, a bad quantity, or a storage failure leaves the meal exactly as
  it was. Errors print `오류: ...` and exit 1. A storage error (`sqlite3.Error`) is rolled back but,
  as with `food add`, appears as a traceback.
- **Retrying is not idempotent.** Running the same `add-item` twice adds the food twice: two
  items, both counted. The command prints the whole meal after every edit, so a duplicate is
  visible right away. Undo it with `remove-item`.
- Output is the edited meal, as in `meal show`, plus a headline such as `Added item 2 to meal ...`.
  `--json` prints the same document as `nutrition log --json`.
- `original_text` (in JSON) keeps the structured text the meal was first logged with. It is a
  record of the original entry, not a description of the current items.

Storage (migration `008_nutrition_meal_item_removals.sql`): a logged item owns append-only
snapshot facts that reference it with `ON DELETE RESTRICT`, so an item can never be deleted or
renumbered. Removing one appends a row to `nutrition_meal_item_removals`, keyed by
`(meal_id, item_sequence)` with `removed_at` and, for a replace, `replaced_by_item_sequence`.
That table is append-only too (update/delete triggers). Every meal read skips removed items. The
item row and its facts stay stored for audit, and a removal cannot be undone. The read-only
reader used by `recommend` also works on a database that has not yet run migration 8.

### Repeat a logged meal

For a meal you eat again, log a new meal with the same foods and amounts instead of typing every
`--item`:

```powershell
muscle50 nutrition repeat 2026-10-02-breakfast-1                  # today, same meal type, time not recorded
muscle50 nutrition repeat 2026-10-02-breakfast-1 --time 07:30
muscle50 nutrition repeat 2026-10-02-dinner-1 --date 2026-10-03 --meal lunch
muscle50 nutrition repeat 2026-10-02-snack-1 --additional       # today's snack is already logged
muscle50 nutrition repeat 2026-10-02-breakfast-1 --json
```

- **What is repeated:** the source meal's current items, in order: removed items are skipped and
  replacement items are included (what `meal show` lists). Only each item's food ID, quantity and
  unit are reused. The new meal's items are numbered 1, 2, ...
- **Nutrition comes from the catalog as it is now.** The new meal is recorded by the same code as
  `nutrition log`, so each item snapshots the food's current fact history (see "Snapshot at log
  time"); the source's snapshots are never copied. If a food got a new fact version after the source
  meal was logged, the repeat uses the new version, and the text output lists such items under
  "Nutrition facts changed since the source meal", naming the catalog fact versions on both sides.
  A nutrient that is `unknown` stays missing in the new meal, never 0.
- **Defaults:** `--date` is today on this computer, `--meal` is the source meal's type, and the
  time is not recorded unless `--time HH:MM` is given (the source's time is not copied).
- **Duplicate guard:** unchanged from `nutrition log`. If the date already has a meal of that type,
  the repeat is refused unless `--additional` is given, so running the same repeat twice records
  one meal.
- **The source meal is only read.** Its ID, items, facts and output stay exactly as they were.
- **Provenance:** the new meal's `original_text` starts with `repeated from <source meal ID>;`
  followed by the usual structured entry text. `--json` prints the same document as
  `nutrition log --json`.
- Errors change nothing: a missing source meal, a source item without a catalog food or quantity
  (possible only for meals written outside the CLI), a bad `--date`/`--time`, the duplicate guard,
  or a storage failure (rolled back, shown as a traceback as with `nutrition log`).

Not supported: scaling amounts (half a portion), saved templates, choosing the source by date or
type, adding or dropping items in the same command (edit the new meal with `nutrition meal`
afterwards), name/alias lookup and unit conversion. No migration: a repeat stores an ordinary meal.

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

- **Limited editing.** Food names/aliases cannot be changed; nutrition numbers change only by
  appending a fact version (`food fact add`). A meal's items can be added, removed or replaced
  (`nutrition meal`, see "Edit a logged meal's items"), but a meal's date, type and time cannot
  be changed, a whole meal cannot be deleted, a removal cannot be undone, and separate meals
  (e.g. ones created earlier with `--additional`) cannot be merged. The duplicate-meal guard
  still applies to `nutrition log`.
- An item edit reads the meal and the catalog, then writes in one transaction. The write
  re-checks the meal, item and next item number under its lock, so two simultaneous edits of the
  same meal cannot interleave. The loser is refused and changes nothing.
- One unit per food from the CLI (`food fact add` versions the existing unit); no per-food unit
  conversions (e.g. `1 pack = 210 g`).
- `food fact add` checks the current fact and appends in two steps; two simultaneous runs for
  the same food could both supersede the same fact (single-user CLI, not guarded).
- Without `--time` a meal is stored at local 00:00; `--time 00:00` is displayed the same way.
- The day boundary uses this computer's current UTC offset rules; meals logged under a
  different offset are still found by their absolute time.
- No meal or menu recommendations, weekly analytics, parser, Telegram, external databases. Targets
  and remaining amounts are in `muscle50 nutrition status` (`nutrition-targets.md`), not in `day`;
  `recommend`/`daily` show that status with short below-target actions (`nutrition-recommendation.md`).
