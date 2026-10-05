# Nutrition Food Name Lookup (v1)

`--item <food> QTY UNIT` in `nutrition log`, `nutrition meal add-item` and
`nutrition meal replace-item` accepts a catalog food's **ID**, or its exact **name** or
**alias**. Typing `--item 닭가슴살 150 g` records exactly what `--item chicken-breast 150 g`
records: the same stored rows (including `original_text`), the same text and the same JSON.

Non-goals: no fuzzy, partial, typo-tolerant or suggested matches; no lookup in
`food show`/`food fact add`; no free-text meal parser; `nutrition repeat` is unchanged (it reuses
the source meal's food IDs and never looks anything up). No migration, no output change.

## Commands

```powershell
muscle50 nutrition log --meal breakfast --item 닭가슴살 200 g --item egg 2 count
muscle50 nutrition log --meal lunch --item "chicken breast" 150 g --json
muscle50 nutrition meal add-item 2026-10-02-breakfast-1 --item "현미 햇반" 1 pack
muscle50 nutrition meal replace-item 2026-10-02-breakfast-1 --item-number 1 --item 닭가슴살 180 g
```

A name or alias that contains spaces must be quoted so the shell passes it as one argument:
`--item "현미 햇반" 1 pack` in PowerShell, `--item "현미 햇반" 1 pack` or `--item '현미 햇반' 1 pack` in bash.

Output (synthetic catalog `chicken-breast`, name `닭가슴살`, alias `Chicken Breast`,
110 kcal / P 18 / C 1 / F 3 per 100 g) is byte-identical to the ID run:

```text
> muscle50 nutrition log --date 2026-10-02 --meal lunch --item 닭가슴살 150 g
Recorded meal 2026-10-02-lunch-1.

[lunch] 2026-10-02-lunch-1 (2026-10-02, time not recorded)
  1. 닭가슴살 (chicken-breast) 150 g: kcal 165 | P 27 g | C 1.5 g | F 4.5 g
     source: user_provided/exact
  Meal total: kcal 165 | P 27 g | C 1.5 g | F 4.5 g

Whole day: muscle50 nutrition day --date 2026-10-02
```

With `--json` the document is the one the ID run prints (`"food_id": "chicken-breast"`,
`"original_text": "structured entry lunch 2026-10-02: chicken-breast 150 g"`).

## Rules

Each `--item` token is resolved on its own, after every `--item` quantity/unit and `--time` has
been parsed (format errors are still reported first, exactly as before):

1. **ID**: the token equals a food ID exactly (case-sensitive).
2. **Name or alias**: after trimming surrounding whitespace, the token equals a food's name or
   one of its aliases, ignoring ASCII case. This reuses `FoodNutritionRepository.search`
   (SQLite `LOWER()`), the same check `food add` uses to refuse duplicate names and aliases.
3. **Ambiguous, refused**: the token is the ID of food A *and* a name/alias of a different food
   B; or (with data written outside the CLI) it is a name/alias of two or more foods. A food whose
   own name or alias equals its own ID is not ambiguous.
4. **No match, refused** with the existing unknown-food error, at the same point and with the same
   text as an unknown ID (for example after the duplicate-meal check of `nutrition log`).

The resolved food ID is then handed to the unchanged `LogMeal` / `AddMealItems` /
`ReplaceMealItem`, so everything stored and printed is what the ID input gives.

Refusals (stderr, exit 1, stdout empty, nothing written; all-or-nothing across several `--item`):

```text
오류: --item 1 'egg' is ambiguous: it is the ID of food egg and a name/alias of food quail-egg. No food is chosen automatically. Nothing was changed.
오류: --item 1 'tofu' is ambiguous: it is a name/alias of foods tofu-a, tofu-b. No food is chosen automatically; use one of these food IDs. Nothing was changed.
오류: item 1: no food with id '닭가슴' (see `muscle50 nutrition food list`)
```

Labels: `--item N` for `log` and `add-item`, `--item` for `replace-item`. The unknown-food line
keeps the existing labels (`item N` for `log`; `--item N`/`--item` plus "Nothing was changed."
for the edit commands).

Code: `application/food_lookup.py` (`ResolveFoodReference`), wired by `cli.py`
`_resolve_entries`. Tests: `tests/test_nutrition_food_lookup.py`.

## Known issues / limitations

- **An ID that is another food's name or alias cannot be used as an ID.** `food add` compares a
  new name/alias only with existing names/aliases, never with IDs (and a new ID never with
  names). So `food add --id egg --name 계란` followed by `food add --id quail-egg --name egg` is
  accepted, and from then on `--item egg` is refused as ambiguous. Food names and aliases cannot
  be edited, so `egg` stays unusable as an ID in `log`/`add-item`/`replace-item` (its name
  `계란` still works; `nutrition repeat` of an older meal with `egg` still works). The ambiguity
  message therefore states only the facts and gives no advice that could not work. Follow-up
  candidate: `food add` refuses a new ID that is an existing name/alias, and a new name/alias
  that is an existing ID.
- **A case-shifted or padded ID is not an ID.** `Egg` or ` egg` does not match the ID `egg`. If
  another food has the name or alias `egg`, such a token resolves to that food, as the rules
  above say (the printed `name (id)` line shows which food was recorded).
- **Case folding is ASCII only** (SQLite `LOWER()`). Full-width letters and other Unicode case
  variants do not match.
- **`original_text` stores the resolved food ID**, not what was typed (spec follow-up candidate).
- **No lookup in other commands**: `food show <name>` and `food fact add <name>` still take IDs
  only (spec follow-up candidate). `nutrition repeat` takes meal IDs and is unchanged.
- An ambiguous token is refused before the duplicate-meal, missing-meal and missing-item checks;
  an unknown token is refused after them, as before.
- Each `--item` costs two extra catalog reads (by ID and by name). A catalog change between the
  lookup and the write would need a concurrent `food add`, which a single-user CLI does not do.
