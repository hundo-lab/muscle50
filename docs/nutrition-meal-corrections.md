# Nutrition Meal Void, Edit and Merge v1

Corrections for a whole logged meal, next to the item edits of `nutrition-logging.md`
("Edit a logged meal's items"):

- **void** a meal that was logged by mistake (`nutrition meal void`);
- **edit** a meal's date, type or time (`nutrition meal edit`);
- **merge** two meals of the same date, for example a meal split in two with `--additional`
  (`nutrition meal merge`).

Non-goals (v1): no unvoid, no editing of food names or aliases, no recalculation of nutrition
values (no new fact is selected, no item is re-snapshotted), no merging of three or more meals in
one step, no automatic merging, and no `--reason` on edit or merge.

## Commands

```text
muscle50 nutrition meal void MEAL_ID [--reason TEXT] [--json]
muscle50 nutrition meal edit MEAL_ID [--date YYYY-MM-DD] [--meal {breakfast,lunch,dinner,snack,other}]
                                     [--time HH:MM | --no-time] [--additional] [--json]
muscle50 nutrition meal merge TARGET_MEAL_ID SOURCE_MEAL_ID [--json]
```

The text output is a one-line headline, then the meal exactly as `nutrition meal show` prints it
(including its history lines, see below), then the `Whole day:` hint. `--json` prints exactly what
`nutrition meal show <meal> --json` prints afterwards; for a merge that is the target meal.

Exit codes: 0 ok; 1 a refused correction (`오류: ...` on stderr, nothing written), including a bad
`--date` or `--time`; 2 an argparse error (missing meal ID, `--time` together with `--no-time`,
unknown `--meal`); 130 Ctrl+C.

### Void

```text
> muscle50 nutrition meal void 2026-10-02-snack-1 --reason "double entry"
Voided meal 2026-10-02-snack-1. It no longer counts in nutrition day, status, recommend or daily.

[snack] 2026-10-02-snack-1 (2026-10-02, time not recorded)
  1. 바나나 (banana-medium) 1 count: kcal 90 | P 1 g | C 23 g | F 0 g
     source: food_database/exact
     facts: food:banana-medium:1
  Meal total: kcal 90 | P 1 g | C 23 g | F 0 g
  Voided 2026-10-02 21:00 (UTC+09:00); reason: double entry. Not counted in nutrition day, status, recommend or daily.

Whole day: muscle50 nutrition day --date 2026-10-02
```

- The meal drops out of `nutrition day`, `nutrition status`, `recommend` and `daily` at once. It
  stays stored, and `nutrition meal show` still shows it with the void line.
- `--reason` is optional free text, stored without surrounding spaces. A blank reason is refused.
  Without a reason the line reads `...; no reason given. Not counted ...`.
- A void cannot be undone. Voiding a meal twice is refused.
- The voided meal's ID stays taken: logging the same meal type on that date again needs no
  `--additional` (the voided meal no longer counts as a double entry), and gets the next number
  (for example `2026-10-02-snack-2`).

### Edit

```text
> muscle50 nutrition meal edit 2026-10-02-dinner-1 --date 2026-10-01 --time 21:30
Edited meal 2026-10-02-dinner-1: date 2026-10-02 -> 2026-10-01; time not recorded -> 21:30. The meal ID does not change.

[dinner] 2026-10-02-dinner-1 (2026-10-01 21:30)
  1. 닭가슴살 (chicken-breast) 200 g: kcal 200 | P 40 g | C 0 g | F 4 g
     source: user_provided/exact
     facts: food:chicken-breast:1
  Meal total: kcal 200 | P 40 g | C 0 g | F 4 g
  Edited 2026-10-02 22:00 (UTC+09:00): date 2026-10-02 -> 2026-10-01; time not recorded -> 21:30
  The meal ID keeps the date and type it was logged with; the date and type above are current.

Whole day: muscle50 nutrition day --date 2026-10-01
```

- Give at least one of `--date`, `--meal`, `--time` or `--no-time`. Unset options keep the current
  value. `--no-time` records that the time is not known (the meal is then stored at local 00:00,
  like a meal logged without `--time`).
- **The meal ID never changes**, even though it contains the date and type it was logged with.
  `day`, `status`, `recommend` and `daily` place the meal by its current date, time and type;
  `meal show` says so in the ID note line. Re-deriving the ID would break every reference to it.
- Only the changed fields are listed, in date, type, time order.
- A type-only edit keeps the stored time exactly (offset included). A date change keeps the wall
  time unless `--time`/`--no-time` is given.
- Refused, with nothing written: no option given; every value equal to the current one (for
  example `--no-time` on a meal without a time); a voided meal.
- **Double-entry guard:** when the date or type changes and the destination date already has a
  (not voided) meal of that type, the edit is refused unless `--additional` is given, exactly like
  `nutrition log`. A time-only change never trips the guard.

### Merge

```text
> muscle50 nutrition meal merge 2026-10-02-breakfast-1 2026-10-02-breakfast-2
Merged meal 2026-10-02-breakfast-2 into 2026-10-02-breakfast-1 as items 3, 4; meal 2026-10-02-breakfast-2 is voided.

[breakfast] 2026-10-02-breakfast-1 (2026-10-02 07:30)
  1. 닭가슴살 (chicken-breast) 200 g: kcal 200 | P 40 g | C 0 g | F 4 g
  ...
  3. 바나나 (banana-medium) 1 count: kcal 90 | P 1 g | C 23 g | F 0 g
     source: food_database/exact
     facts: food:banana-medium:1
  4. 에너지바 (energy-bar) 1 count: kcal 200 | P 5 g | C 30 g | F 7 g
     source: food_database/estimated
     facts: food:energy-bar:1
  Meal total: ...
  Merged 2026-10-02 22:05 (UTC+09:00) from meal 2026-10-02-breakfast-2: items 3, 4 (its items 1, 2)

Whole day: muscle50 nutrition day --date 2026-10-02
```

- The source meal's active items (removed items are skipped) are added to the target with the
  target's next item numbers (numbers are never reused), and the source is voided, in one
  transaction: both happen or neither does.
- **Nutrition values do not change.** Each copy carries the source item's snapshot facts verbatim
  (values, basis, provenance, `created_at`); only the snapshot fact IDs follow the new meal and
  item number (`<target>:<item>:<catalog fact ID>`), so the `facts:` line names the same catalog
  versions. A catalog fact added after the source was logged is not picked up.
- Both meals must be on the same date (as `meal show` displays them). Meals of different types
  can be merged: the target keeps its own type and time (change it with `meal edit` if needed).
- The source's `meal show` gets `Voided ...; merged into meal <target>. Not counted ...`.
- Refused, with nothing written: target equal to source, a missing or voided meal, different dates,
  and a merge that would change the day's exact totals (see "Known issues").
- After a merge, the day's four nutrient total lines and its `Estimated:` line (text) and the
  `total` object (`day --json`) are byte-identical to before. The meal count, and the meal ID/item
  number references in `Incomplete:` lines, `missing_items` and `uncalculated_items`, change.

### Voided meals are read-only

`meal edit`, `meal merge` (as target or source), `meal add-item`, `remove-item`, `replace-item`,
`meal void` and `nutrition repeat` refuse a voided meal (exit 1, nothing written):

```text
오류: meal 2026-10-02-snack-1 was voided at 2026-10-02 21:00 (UTC+09:00); a voided meal cannot be changed. Nothing was changed.
오류: meal 2026-10-02-breakfast-2 was merged into 2026-10-02-breakfast-1 at 2026-10-02 22:05 (UTC+09:00); a voided meal cannot be changed (use 2026-10-02-breakfast-1). Nothing was changed.
```

`nutrition repeat` says "cannot be repeated" (and "repeat <target> instead" for a merged source):
a merged source only holds part of the meal.

## History in `meal show`

`meal show` (and the output of void/edit/merge) appends history lines after `Meal total`, only
for a meal that has a correction, in this order: edits (oldest first), the ID note (when edited),
merges into this meal (oldest first), the void. Timestamps are printed in the offset they were
recorded with, `YYYY-MM-DD HH:MM (UTC+hh:mm)`. Text is ASCII apart from food names and the void
reason.

### JSON

For a meal with history, `meal show --json` appends these keys after `total`, always all of them
and in this order:

```json
  "voided": false,
  "voided_at": null,
  "void_reason": null,
  "merged_into": null,
  "merged_from": [
    {"meal_id": "2026-10-02-breakfast-2", "merged_at": "2026-10-02T22:05:00.123456+09:00",
     "items": [{"sequence": 3, "source_sequence": 1}, {"sequence": 4, "source_sequence": 2}]}
  ],
  "revisions": [
    {"revision": 1, "revised_at": "2026-10-02T22:00:00.654321+09:00",
     "before": {"meal_type": "dinner", "eaten_at": "2026-10-02T00:00:00+09:00", "time_recorded": false},
     "after": {"meal_type": "dinner", "eaten_at": "2026-10-01T21:30:00+09:00", "time_recorded": true}}
  ]
```

- `voided_at`/`merged_at`/`revised_at` are full ISO timestamps; `void_reason` is a string or null;
  `merged_into` is set on a merged source. `before` of revision 1 is the meal as logged; `before`
  of revision n is `after` of revision n-1. The top-level `meal_type` and `eaten_at` are the
  current values.
- **The keys are conditional.** A meal without any correction prints exactly the document
  `nutrition log --json` prints, so every existing output stays byte-identical. The keys never
  appear in `nutrition day --json`, `log`, `repeat` or `add-item`/`remove-item`/`replace-item`
  output. For a corrected meal, `meal show --json` is therefore no longer equal to its
  `day --json` `meals[]` entry.

## Storage (migration 9)

`009_nutrition_meal_corrections.sql` adds three append-only tables (update/delete triggers); no
existing table is altered and no existing row is ever updated:

| Table | Row |
| --- | --- |
| `nutrition_meal_revisions` | `(meal_id, revision)`: the meal's full effective `eaten_at` (+ UTC sort key) and `meal_type` after one edit; the latest revision wins. A trigger refuses a revision of a voided meal. |
| `nutrition_meal_voids` | One per meal (primary key): `voided_at`, optional `reason`, `merged_into_meal_id` for a merge. |
| `nutrition_meal_merged_items` | `(meal_id, item_sequence)` copy -> `(source_meal_id, source_item_sequence)`; the source must have a void row (foreign key). |

- Every meal read (`get`, `day`, `status`, the read-only reader of `recommend`/`daily`) uses the
  latest revision's date, time and type, and every listing leaves voided meals out.
- Writes are one `BEGIN IMMEDIATE` transaction each and re-check the guards inside it (meal
  exists, not voided, next revision number, the source's active items, the target's next item
  number). Item writes (`add-item`/`remove-item`/`replace-item`) and fact appends also refuse a
  voided meal inside their transaction.
- Read-only readers never migrate. They check whether each new table exists; a database without
  migration 9 is read exactly as before. `daily` migrates before it reads nutrition anyway.

## Known issues / limitations

- No unvoid, no undo of an edit, no correction of a void reason. Voiding a merge target also hides
  the items copied into it; the merged source stays voided.
- A merge is refused when copying the items would change the day's exact totals. Totals are summed
  in item order with 28-digit Decimals, so moving an item between meals can change how a
  non-terminating value (for example 1/3 of a basis) rounds in the last digit. The meals are then
  left separate. Ordinary values (whole numbers, finite decimals) never trigger this.
- The merge date check and totals check use the meals' dates as displayed (their stored UTC offset)
  and this computer's offset for the day; meals logged under a different offset than the current
  one may be refused rather than merged.
- `--time 00:00` and `--no-time` are the same: a meal at local 00:00 is shown as "time not
  recorded" (existing limitation of `nutrition log`).
- Like `nutrition log`, the edit double-entry guard is checked before the write transaction, not
  inside it (single-user CLI).
- Listing meals by their effective time no longer uses the `eaten_at_utc_sort_key` index, and each
  meal read does two or three more small queries. This is negligible at personal scale.
- `add-item`/`remove-item`/`replace-item` output of an edited meal does not include the history
  lines or keys; `meal show` does.
- Production databases get migration 9 the first time a writing command runs; until then,
  `recommend`/`daily` read them unchanged.
