# Nutrition General Meal v1

Record "I ate a meal whose menu and numbers I do not know" (a canteen lunch, a delivery, side dishes
at home) without naming a menu or guessing a number. A **general meal** is an item with no quantity,
no unit and no nutrition facts. Every nutrient of it is unknown, never 0, so every total it is part of
is incomplete and no below-target judgement or action is produced from it.

Spec: `docs/specs/general-meal.md`. Migration: none. Output change: additive.

## Non-goals

- No estimation. A memo such as "제육" is never turned into kcal or protein.
- No general meal menu catalog (estimated values per typical dish), no portion sizes ("1인분",
  "half a bowl"). A general meal is "one meal eaten".
- No change to catalog foods: `food add` still needs at least one number.

## Commands

```powershell
muscle50 nutrition log --meal lunch --general
muscle50 nutrition log --meal lunch --general --general-note 구내식당
muscle50 nutrition log --meal dinner --general --item chicken-breast 100 g
muscle50 nutrition meal add-item 2026-10-08-dinner-1 --general
muscle50 nutrition meal replace-item 2026-10-08-dinner-1 --item-number 2 --general --general-note 배달
```

- `--general` takes no value and can be repeated. `--item` and `--general` share one ordered list,
  so the items keep the command-line order:
  `--item chicken-breast 100 g --general --general-note 구내식당 --general` gives item 1 chicken,
  item 2 a general meal with the memo "구내식당", item 3 a general meal without a memo.
- `--general-note TEXT` is optional and must come directly after the `--general` it belongs to
  (one memo per `--general`). Otherwise argparse exits 2 with
  `argument --general-note: must directly follow the --general it describes`.
- `nutrition log` and `meal add-item` need at least one `--item` or `--general` (exit 2,
  `one of the arguments --item --general is required`).
- `meal replace-item` takes exactly one of `--item FOOD QTY UNIT` or `--general`
  (`--general-note` only with `--general`, otherwise exit 2 `argument --general-note: requires --general`).
- The duplicate-meal guard, `--additional`, `--date` and `--time` work as for catalog items: a general
  meal is a meal of that type.
- Telegram: `/log lunch 일반식 [메모]`; see `docs/telegram-bot.md` "Nutrition General Meal v1".

### Text output (synthetic values)

`nutrition log --date 2026-10-08 --meal dinner --general --general-note 구내식당 --item chicken-breast 100 g`
with a food at 110 kcal / P 23 / C 0 / F 1.5 per 100 g:

```text
Recorded meal 2026-10-08-dinner-1.

[dinner] 2026-10-08-dinner-1 (2026-10-08, time not recorded)
  1. 일반식 (general meal; note: 구내식당): nutrition unknown
     source: no nutrition facts
     missing: kcal, protein, carbohydrate, fat
  2. 닭가슴살 (chicken-breast) 100 g: kcal 110 | P 23 g | C 0 g | F 1.5 g
     source: nutrition_label/exact
  Meal total: kcal incomplete (known items only: 110) | P incomplete (known items only: 23 g) | C incomplete (known items only: 0 g) | F incomplete (known items only: 1.5 g)

Whole day: muscle50 nutrition day --date 2026-10-08
```

- A meal with only general items shows `incomplete (no item has a value)` for each total.
- `meal show` adds the usual `facts: none selected` line.
- `nutrition day` and `nutrition status` list the item like any other incomplete item:
  `kcal: 2026-10-08-dinner-1 item 1 일반식 (general-meal)`. `status` says
  `cannot tell yet (incomplete); remaining unknown` for every nutrient that has a target.

### JSON

The meal document is unchanged except that a general item gets two keys appended at its end:

```json
{
  "sequence": 1,
  "food_id": "general-meal",
  "food_name": "일반식",
  "quantity": null,
  "unit": null,
  "nutrients": {"calories_kcal": null, "protein_g": null, "carbohydrate_g": null, "fat_g": null},
  "missing_fields": ["calories_kcal", "protein_g", "carbohydrate_g", "fat_g"],
  "facts": [],
  "general_meal": true,
  "note": "구내식당"
}
```

`note` is `null` without a memo. Totals are `null`, `known_subtotals` hold only the catalog items, and
`missing_items` in `status --json` name `"food_id": "general-meal"`. Items that are not general
meals keep their exact documents (no new keys).

## Rules

- **Storage (no migration).** A general item points to the reserved system profile `general-meal`
  (name `일반식`), which has no nutrition facts and no aliases. The item has no quantity, no unit and
  no facts; the memo is stored in the item's `serving_description`. The profile row is inserted with
  `INSERT OR IGNORE` inside the same transaction as the first general item, so a failed write leaves
  neither. Nothing is updated or deleted.
- **What a general item is.** `MealItem.is_general` is true only for the reserved profile ID with no
  quantity, unit or facts. An item without a quantity that points to any other food (for example one
  written below the CLI) is not a general meal and renders as before.
- **Memo.** Optional; surrounding whitespace is stripped; empty means no memo. At most 100
  characters and a single line (no control characters such as line breaks or tabs), checked before
  anything is read or written (exit 1):
  `item 1: --general-note must be at most 100 characters (got 123). Nothing was changed.` /
  `item 1: --general-note must be a single line of text. Nothing was changed.` (on `replace-item`
  without the `item N:` prefix). The memo is never used for nutrition.
- **Item numbers in error labels** count `--item` and `--general` entries together (`item 2` is the
  second entry of either kind), the same as the stored item numbers.
- **Reserved ID, name and alias.**
  - `food add` refuses the ID, name or alias `general-meal` / `일반식` (whitespace and case ignored),
    whether or not the profile exists yet:
    `food id 'general-meal' is reserved for the general meal (record one with nutrition log --general); nothing was changed`,
    `name or alias '일반식' is reserved for the general meal (...); nothing was changed`. These checks
    run after the existing format and fact checks, so the "at least one number" refusal is unchanged.
  - `food show general-meal` and `food fact add general-meal` refuse:
    `'general-meal' is the general meal (일반식), not a catalog food: it has no nutrition facts and none can be added. Nothing was changed.`
  - `--item 일반식 ...` / `--item general-meal ...` (any case) are refused before name lookup:
    `--item 1 '일반식' is the general meal, not a catalog food; record it with --general (no quantity or unit). Nothing was changed.`
  - `food list` (text and JSON) never shows the system profile, so it is byte-identical before and
    after general meals.
  - If a catalog food already holds the ID `general-meal` with facts, aliases or another name, a
    general meal is refused: `food 'general-meal' in the catalog is not the general meal (it has nutrition facts, aliases or another name); general meals cannot be recorded. Nothing was changed.`
- **Corrections.** `meal void/edit/merge`, `repeat`, `add-item`, `remove-item` and `replace-item`
  work on general items. Merge copies the general item and its memo (no facts to copy); the merge
  totals guard is unaffected because a general item adds nothing to any sum. `repeat` repeats a
  general item as a general item with the same memo; its `original_text` reads
  `repeated from <id>; structured entry dinner 2026-10-09: general meal (note: 구내식당); chicken-breast 100 g`.
  A meal's last item cannot be removed, general or not.
- **Readers.** `nutrition day/status`, `recommend` and `daily` read general items through the
  existing code. `recommend`/`daily` stay read-only and never create the profile row. A day with a
  general meal is `indeterminate` for every nutrient with a target (or `above_*` with an unknown
  excess when the known items alone exceed it), so no below-target action is produced.

## Known issues / limitations

- A day with general meals has no nutrition judgement: totals stay incomplete and `status`,
  `recommend` and `daily` show lower bounds only. This is intended; logging mostly general meals
  gives little nutrition feedback.
- The catalog table holds one row that is not a food (`general-meal`, no facts). It is hidden from
  `food list`, but raw database readers see it.
- A food whose ID, name or alias is `general-meal` / `일반식` that existed before this feature
  cannot be used with `--item` and blocks general meals. (Production was checked on 2026-10-08:
  no such food.)
- `일반식` is a Korean system label printed in otherwise ASCII text output. cp949 consoles print
  Hangul; the ASCII rule targets dashes and arrows.
- The "Meal total" line of a meal with only general items is long (four times
  `incomplete (no item has a value)`); the existing wording was kept instead of a new "unknown".
- No count of general meals in summaries yet ("일반식 N끼"); `food_id == "general-meal"` in the
  existing JSON is enough to build it later.
- Follow-up candidates (spec): a general meal menu catalog with estimated values, Telegram v2 free
  text with an LLM estimate, and a general-meal ratio in the between-measurement review.

## Code

- Domain: `domain/nutrition.py` (`GENERAL_MEAL_FOOD_ID`, `MealItem.is_general`,
  `normalize_general_meal_note`, `is_reserved_food_reference`).
- Use cases: `application/nutrition_logging.py` (`GeneralMealEntry`, `entry_item`,
  `general_meal_item`, reserved checks), `application/food_lookup.py` (E3 before lookup).
- Storage: `infrastructure/sqlite/nutrition_repository.py` (`_ensure_general_meal_profile`).
- Output: `presentation/nutrition_terminal.py` (`_meal_lines`, `_item_payload`).
- CLI: `cli.py` (`_add_meal_entry_arguments`, `_MealEntryAction`, `_GeneralNoteAction`,
  `_check_meal_entry_arguments`, `_meal_entries`, `_general_entry`).
- Telegram: `domain/telegram_commands.py` (`_log_command`).
- Tests: `tests/test_nutrition_general_meal.py`, `tests/test_telegram_general_meal.py`.
