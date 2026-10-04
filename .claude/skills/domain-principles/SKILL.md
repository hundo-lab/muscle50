---
name: domain-principles
description: muscle50 data and output rules every feature must keep - missing is not 0, no guessing/auto-merge/auto-correction, RAW first, source vs derived separation, read-only paths never mkdir/migrate, nutrition never changes the training plan, no LLM/ML, byte-stable ASCII text and JSON. Use when designing, implementing or reviewing any muscle50 change.
user-invocable: false
---

# muscle50 domain principles

These are rules already followed by the code and recorded in the docs. They are not new policy:
each one lists where it comes from. When a spec seems to need an exception, stop and raise it as a
design question (human gate 1). Do not quietly break it.

## 1. Missing is not zero

- Unknown or absent values stay `None`/`NULL`/`unknown`/`unavailable`. Never fill them with 0.
  Sources: README.md "Training snapshot" ("없는 값은 0이 아니라 `unavailable`"), README.md
  "Nutrition logging" (`unknown`, "0으로 채우지 않음"), docs/nutrition-logging.md.
- Garmin does not give a weight/reps/time, so store `NULL` and do not estimate it. Source: README.md
  "최신 Garmin activity 동기화" (strength sets).
- If any item lacks a value, the total is incomplete. Report the known subtotal (a lower bound) and the
  missing items, never a total. Sources: docs/nutrition-targets.md, docs/CURRENT_STATE.md
  "Nutrition Targets + Daily Status v1".
- "No meals logged" is its own state (`no_intake_logged`), not "0 kcal". Source:
  docs/nutrition-recommendation.md (`availability`).
- Missing recovery data is not poor recovery ("missing != poor"). Source: docs/training-recommendation.md.
- A target that is `unset` is not a target of 0. Source: docs/nutrition-targets.md.

## 2. No guessing, no automatic merge, no automatic correction

- Do not guess exercise classification. `UNKNOWN` stays `UNKNOWN` and is reported for review.
  Sources: README.md "기존 Garmin activity 명시적 refresh", docs/exercise-taxonomy.md,
  docs/analytics-engine.md.
- Taxonomy rules are explicit per Garmin label. There is no category fallback, fuzzy match or
  inference, and the original label stays the identity. Source: docs/exercise-taxonomy.md,
  docs/CURRENT_STATE.md "Important decisions".
- Never merge split sessions or duplicate-looking records automatically. Equal InBody fingerprints
  are comparison candidates, not merges. Sources: docs/CURRENT_STATE.md "Known issues" (2026-07-20
  swims), migration `007_inbody.sql` comments.
- Never correct Garmin summary values. Exclude implausible details from derived numbers and report
  them as data-quality issues. Source: docs/CURRENT_STATE.md "Important decisions" (Analytics).
- Nutrition never guesses unit conversion (pack vs g). Sources that are themselves estimates are refused
  in the catalog. Sources: docs/nutrition-core.md ("never guesses that a pack ... equals a particular
  gram amount"), docs/CURRENT_STATE.md "Nutrition Logging MVP" ("추정 source 거부").
- Do not invent value systems that are not defined yet. Example: `sync_runs` stays unused because
  `command`/`error_code` values were never defined. Source: docs/CURRENT_STATE.md "Important decisions".

## 3. RAW first, immutable history

- Save the provider response as RAW before you normalize. A failed normalize/persist keeps the new
  RAW and leaves the previous canonical rows unchanged. Source: README.md "기존 Garmin activity
  명시적 refresh".
- RAW snapshots are content-addressed (`snapshots/<sha256>/`) and never rewritten. Canonical rows
  point at the accepted capture. Sources: docs/CURRENT_STATE.md "Current architecture",
  migrations 005/006.
- History tables are append-only and enforced by triggers: `nutrition_facts`,
  `nutrition_meal_item_removals`. Change data by appending (supersession, tombstone), never with
  UPDATE/DELETE. Sources: migrations `003_nutrition.sql`, `008_nutrition_meal_item_removals.sql`,
  docs/nutrition-logging.md.
- Canonical rows can be rebuilt from RAW without calling the provider (`garmin recovery-renormalize`).
  Source: docs/CURRENT_STATE.md.

## 4. Source vs corrected/derived values

- Garmin source values and corrected/derived values never overwrite each other. Corrections are
  overlays (`activity_corrections`, append-only design). Sources: docs/CURRENT_STATE.md
  "Current architecture", `001_initial.sql` comment.
- Derived metrics get their own path. Example: load metrics come from a RAW-only backfill, not the
  shared normalizer, so the verified refresh output does not change. Source: docs/CURRENT_STATE.md
  "Important decisions".
- If a source value is missing, do not delete the existing canonical value. That rule lives in the
  use case (`_preserve_missing_canonical_values()`), not in the repository's replace contract.
  Sources: docs/garmin-analytics-prerequisites.md, docs/CURRENT_STATE.md "Important decisions".

## 5. Read-only paths stay read-only

- Analytics, recommendation and nutrition readers open SQLite with `mode=ro` +
  `PRAGMA query_only`. They never call `ensure_directories()` or `migrate()`, and they never change the
  journal mode. Sources: docs/analytics-engine.md, docs/nutrition-recommendation.md,
  `src/muscle50/cli.py` `_analytics_snapshot` ("Deliberately read-only").
- Files are created only by the command that owns them. Example: `config\nutrition_targets.json` is
  created only by the first `target set`, never by `ensure_directories`. Source: docs/CURRENT_STATE.md
  "Important decisions".
- A read-only reader must still read a DB from before the newest migration (check that the table exists).
  Source: docs/CURRENT_STATE.md "Nutrition Meal Edit v1".
- Production data (`%LOCALAPPDATA%\muscle50`) is not touched by development work. Every test and smoke
  run uses a temporary `MUSCLE50_HOME`. Even read commands can create WAL files or directories there.
  Source: docs/CURRENT_STATE.md "Verification" (Nutrition Logging). Enforced by
  `.claude/hooks/pre_bash_guard.py`.

## 6. Feature boundaries

- Nutrition is an extra signal. It never changes, shortens or cancels the training plan, and it never
  adds compensation advice. Source: docs/nutrition-recommendation.md.
- Recommendations are deterministic rules. There is no LLM, ML or synthetic readiness score. Sources:
  docs/training-recommendation.md, README.md "Training recommendation".
- Nothing computes targets automatically. Targets are set by the user. Source: docs/nutrition-targets.md.
- Health values are not printed unless the user asks (`inbody sync --show-values`). Tests use only
  synthetic fixtures. Source: README.md "Samsung Health InBody sync", "개발 검증".

## 7. Output is a contract (byte-stable)

- Text output is ASCII only, apart from user-entered food names. cp949 consoles crash on dashes and
  arrows. Sources: `presentation/nutrition_terminal.py` module docstring, docs/CURRENT_STATE.md
  "Garmin refresh hotfix" (em-dash crash).
- JSON uses `json.dumps(..., indent=2, ensure_ascii=True)`, fixed key order, and Decimal values as exact
  strings. The same stored data gives byte-identical JSON. Sources: docs/nutrition-targets.md,
  docs/nutrition-recommendation.md, docs/analytics-engine.md.
- Existing output does not change unless the spec says so (`output_change`). New JSON data is added as a
  new key at the end. Example: `nutrition` was appended to `recommend --json` and
  `recommendation_version` stayed 1. Source: docs/CURRENT_STATE.md "Nutrition -> Daily/Recommendation
  Integration v1".
- Progress messages and prompts go to stderr, results go to stdout, so `--json` stdout is JSON only.
  Source: docs/CURRENT_STATE.md "Daily orchestration".
- Exit codes: 0 ok, 1 known error, 2 argparse error / InBody RAW conflict, 130 Ctrl+C. Source:
  `src/muscle50/cli.py`.

## 8. Time and dates

- The default date is this computer's today (`date.today()`). The day boundary is the computer's UTC
  offset as a fixed offset, so no tzdata is needed. Do not add named IANA zones: Windows has no tz
  database and `tzdata` is not a dependency. Sources: docs/CURRENT_STATE.md "Nutrition Logging MVP",
  user memory note "Windows zoneinfo needs tzdata".
