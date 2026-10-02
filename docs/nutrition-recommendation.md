# Nutrition → Daily/Recommendation Integration (v1)

`muscle50 recommend` and `muscle50 daily` show the recommended date's nutrition status next to
the training plan, and add a short action only where configured targets and logged intake
support one. Nutrition is an extra signal: it never changes, shortens or cancels the training
plan. No migration, no new stored data, nothing medical or diagnostic.

## Integration boundary

```text
BuildTrainingRecommendation (unchanged) ──► TrainingRecommendation ─┐
                                                                    ├─► BuildNutritionContext ─► NutritionContext
ShowDailyNutritionStatus (unchanged, = `nutrition status`) ─────────┘        (status + guidance)
```

| Layer | Code | Role |
| --- | --- | --- |
| Domain | `domain/nutrition_guidance.py` | `build_nutrition_guidance`: availability, training fuel context, actions. Reads `NutrientTargetStatus` as-is; no arithmetic on nutrient values, no thresholds, no target values |
| Application | `application/nutrition_recommendation.py` | `BuildNutritionContext`: runs `ShowDailyNutritionStatus` for D, then the guidance; expected read errors become `unavailable` |
| Application | `application/daily_sync.py` | optional `nutrition` collaborator, called only when the recommendation was built; not a stage, never changes `ok` |
| Storage | `infrastructure/sqlite/nutrition_reader.py` | `SqliteNutritionReader`: read-only `list_eaten_between` (`mode=ro`, `query_only`, no mkdir/migrate/WAL switch), decoding with the repository's own `_load_meal` |
| Output | `presentation/nutrition_terminal.py` | `nutrition_context_lines`/`nutrition_context_payload`; reuse `nutrient_status_line`/`nutrient_status_payload`, the exact `nutrition status` wording and JSON |
| CLI | `cli.py` `_nutrition_context` | same `_local_timezone`/`offset_name` day boundary as `nutrition status` |

The training recommendation is built first and never receives nutrition, so the nutrition code
structurally cannot alter training history, progression, recovery, swim fatigue or a
user-selected focus. Totals, known subtotals, missing items and target comparison all come from
Nutrition Core / Nutrition Targets unchanged; the only change on that side is that
`ShowDailyIntake` and `ShowDailyNutritionStatus` accept a narrow `MealReader` protocol
(`list_eaten_between` only) instead of the full `MealRepository`, so the read-only reader fits.
`SqliteMealRepository` still satisfies it; `nutrition` commands are unchanged.

## Which nutrition states do what

`availability` (one per date):

| availability | when | text | actions |
| --- | --- | --- | --- |
| `no_targets_configured` | every target unset (the default; production today) | no section: text identical to before | none |
| `no_intake_logged` | a target is set, no meal logged for D | one line: status not used, not counted as 0 kcal/0 g | none |
| `evaluated` | a target is set and at least one item is logged | one line per *targeted* nutrient + actions | see below |
| `unavailable` | targets file invalid, DB unreadable/too old | one line with the reason; training plan unaffected, exit 0 | none |

Per nutrient (only with `evaluated`, only for a configured target):

| status | action |
| --- | --- |
| protein `below_target`/`below_range` | `protein_below_target` (any day) |
| kcal `below_target`/`below_range` | `energy_below_target`; with training work ahead it mentions fueling and states the plan is unchanged |
| carbohydrate `below_target`/`below_range` | `carbohydrate_below_target_for_training` **only** when `fuel_relevant`; otherwise status line only |
| fat any status | status line only (v1 has no fat action) |
| `target_reached` / `within_range` | status line only, no action |
| `above_target` / `above_range` | status line only, factual ("above target by X", or "known items alone exceed it; exact excess unknown"); no compensating advice |
| `indeterminate` | status line + "N logged item(s) have no <nutrient> value: the known amount is a lower bound, not a total"; no remaining amount, no action |
| `no_target` | not listed in text, no action |

`below_*` exists only for complete totals (Nutrition Targets never derives it from a known
subtotal), so an action never rests on unknown values. A known subtotal equal to the maximum
stays `indeterminate`; only a known subtotal above the maximum proves `above_*` (with
`excess: null`). Estimated totals stay marked: the status line shows `(estimated)` and actions
add "(the logged total includes estimated values)". Actions carry no numbers; every amount
shown comes from the status (text 0.1 rounding, exact in JSON). Action order: protein, energy,
carbohydrate.

**Training fuel context** (`training_context` in JSON), from the already-built plan:

- `strength_session_planned`: the plan has exercises.
- `fuel_relevant` = (strength planned **and** adjustment level is not `reduce`) **or** next swim goal is
  `distance_progression`/`pace_intervals`.
- Rest/light = no strength session or a `reduce` session, and an easy next swim
  (`easy_continuous`/`return_easy`/`recovery_technique`): no training-fuel wording, no carbohydrate action.
- The swim goal is the *next* swim, not necessarily today's; messages say "the next swim".

No shortfall threshold, gram prescription or meal timing is invented; target values come only
from `nutrition target set`.

## Day and target semantics

- D's intake is whatever is logged for D so far ("Logged so far"); for today that is usually a
  partial day. Wording is "logged ... is below the configured target", never "you ate" or
  "deficit".
- Day boundary: this computer's UTC offset for D (same as `nutrition status`).
- No target history: past dates are compared with the **currently** configured targets
  (`scope: intake_vs_current_targets`).

## JSON contract

`recommend --json` (and `daily --json`'s `recommendation`) keep every existing field unchanged
and add one trailing key `nutrition`, always present when run from the CLI:

```json
"nutrition": {
  "guidance_version": 1,
  "date": "2026-10-02",
  "timezone": "+09:00",
  "scope": "intake_vs_current_targets",
  "availability": "evaluated",
  "unavailable_reason": null,
  "meal_count": 1,
  "item_count": 1,
  "training_context": {
    "strength_session_planned": true,
    "strength_adjustment_level": "hold",
    "next_swim_session_type": "return_easy",
    "fuel_relevant": true,
    "description": "today's planned strength session"
  },
  "nutrients": {"calories_kcal": {"...": "exactly the `nutrition status --json` entry"}, "...": "..."},
  "actions": [{"code": "protein_below_target", "nutrient": "protein_g", "message": "..."}]
}
```

- `nutrients` is byte-for-byte the `nutrition status --json` `nutrients` object (same
  serializer; a contract test compares them), `null` only when `unavailable`.
- `meal_count`/`item_count` are `null` only when `unavailable`.
- `recommendation_version` stays 1 (training fields unchanged); the block has its own
  `guidance_version`.
- Deterministic: fixed key order, exact Decimal strings, ASCII-escaped. Program against
  `availability`, `status`, `complete` and action `code`, not the text.

## Read-only and production safety

`recommend` stays read-only: the reader never creates the database, its directory or
`config\`, never migrates and never changes the journal mode. As with the existing analytics
reader, SQLite may create/refresh the empty `-wal`/`-shm` side files of a WAL database when a
`mode=ro` connection opens it; database content, the `-wal` content and every other file are
unchanged (tests check this; see CURRENT_STATE Verification).

## Limitations

- One date only: D's intake. Yesterday's completed intake is not considered.
- No target history (above), same targets every day (no training/rest-day targets).
- A day with no logged meals cannot be marked "ate nothing"; it is always `no_intake_logged`.
- Below-target is reported whatever the time of day: in the morning most targets are naturally
  below. The text says "logged so far" but does not know the time.
- Fat has no action; above-target never produces advice.
- Estimated totals are compared by their point value (Nutrition Targets behaviour).
- `fuel_relevant` uses only the plan's strength session/adjustment and next swim type; it does
  not know when (or whether) the user actually trains today.
