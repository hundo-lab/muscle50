# Nutrition Core Handoff

## Current task

Finish the `feature/nutrition-core` worktree in an integration-ready state while
preserving the previous uncommitted documentation work.

The branch appears to implement Nutrition Core for `muscle50`: deterministic
nutrition domain/data modeling, provenance-aware nutrient facts, parser and
repository ports, serialization/schema, SQLite persistence, fixtures, and unit
tests. No merge to `main` has been performed.

## Completed work

- Added pure Nutrition domain model in `src/muscle50/domain/nutrition.py`.
- Added parser and repository Protocols in `src/muscle50/application/nutrition.py`.
- Added JSON-compatible meal serialization in
  `src/muscle50/infrastructure/nutrition_serialization.py`.
- Added shared canonical Decimal text helpers in
  `src/muscle50/infrastructure/decimal_text.py`.
- Added versioned JSON Schema at
  `src/muscle50/schemas/nutrition_meal_v1.schema.json`.
- Added SQLite nutrition repositories in
  `src/muscle50/infrastructure/sqlite/nutrition_repository.py`.
- Added a feature-local SQLite schema at
  `src/muscle50/infrastructure/sqlite/nutrition_schema.sql`.
- Added synthetic fixture data in `tests/fixtures/nutrition_meal_v1.json`.
- Added unit tests for domain arithmetic/aggregation, serialization, parser
  ports, and SQLite repository behavior.
- Added pytest coverage for SQLite supersession trigger rejection of wrong-unit
  and cross-owner corrections.
- Added `src/muscle50/py.typed` marker.

## Current repository state

- Current branch: `feature/nutrition-core`.
- Current pre-finalization branch HEAD: `6ce0e4d`.
- Latest local `main` inspected during finalization: `a856705`, which contains
  Garmin Activity Sync, Strength Sets, Swim Details, and repository-level
  `AGENTS.md` / `docs/CURRENT_STATE.md` / `docs/HANDOFF.md`.
- `feature/nutrition-core` and latest local `main` have diverged. This branch has
  not been merged or rebased onto latest `main`.
- Existing branch commits:
  - `f3ff849 feat: add Nutrition Core domain, ports, and interchange schema`
  - `6ce0e4d feat: add SQLite nutrition repositories`
- Before this handoff file was written, `git status --short --branch` showed no
  unstaged or staged changes.
- `git diff` and `git diff --staged` were empty before this file was added.
- `AGENTS.md` and `docs/CURRENT_STATE.md` do not exist in this worktree, but were
  read from `main`.
- `uv build` creates ignored artifacts under `dist/`, which is listed in
  `.gitignore`.

## Feature-owned files to carry forward

- `docs/nutrition-core.md`
- `docs/nutrition-core-handoff.md`
- `src/muscle50/application/nutrition.py`
- `src/muscle50/domain/nutrition.py`
- `src/muscle50/infrastructure/decimal_text.py`
- `src/muscle50/infrastructure/nutrition_serialization.py`
- `src/muscle50/infrastructure/sqlite/nutrition_repository.py`
- `src/muscle50/infrastructure/sqlite/nutrition_schema.sql`
- `src/muscle50/py.typed`
- `src/muscle50/schemas/nutrition_meal_v1.schema.json`
- `tests/fixtures/nutrition_meal_v1.json`
- `tests/test_nutrition_domain.py`
- `tests/test_nutrition_ports.py`
- `tests/test_nutrition_repository.py`
- `tests/test_nutrition_serialization.py`

The previous untracked `docs/HANDOFF.md` content was preserved here instead of
committing it at the shared path. Latest `main` already owns the repository-level
`docs/HANDOFF.md`, so keeping this branch-specific handoff at that path would
create an avoidable add/add conflict during integration.

## What appears internally consistent

- Nutrition calculation uses `Decimal` with a fixed local context for scaling
  and aggregation.
- Unknown nutrient values remain `None`; aggregation does not turn missing data
  into zero.
- `known_subtotals` exposes partial known values separately from complete
  `totals`.
- Provenance is retained per nutrient through `CalculatedNutrient`.
- Source priority matches the requested order:
  nutrition label, user-provided values, known product, food database, then
  estimates. Visual and language estimates share the estimate tier.
- Exact facts cannot carry estimate ranges; visual/language facts must be
  estimated.
- Superseded facts remain in history, and supersession is resolved per nutrient.
- Unit conversion is intentionally not inferred. Facts only apply when item unit
  and fact basis unit match.
- Parser output is structural only; nutrient calculations remain outside the
  parser boundary.
- SQLite facts are append-only via triggers, with repository methods for saving
  new meals/profiles and appending facts.
- Existing Garmin CLI, activity migration, and shared database bootstrap were not
  modified.
- SQLite scope decision: keep `SqliteMealRepository`,
  `SqliteFoodNutritionRepository`, and `nutrition_schema.sql` in this branch as
  feature-local persistence adapters. Do not wire them into shared `database.py`,
  public CLI, or numbered migrations until integration.

## Remaining work

- Integrate Nutrition repositories into the application/CLI only after shared CLI
  and migration conflicts are resolved.
- Promote `nutrition_schema.sql` into the consolidated numbered migration plan
  after reconciling parallel branches, or replace it with the final migration
  while preserving the current repository tests as the behavior contract.
- Reviewer Agent re-review found no High/Medium issues.
- If product reuse should automatically attach profile facts to meal items, add a
  service/use case layer. Current domain stores `food_profile_id`, but meal items
  calculate only from their own snapshotted `nutrition_facts`.
- Add an explicit conversion model later if verified conversions such as
  `1 pack = 120 g` must allow per-gram facts to be applied to pack/count units.
- Add migration evolution/backfill logic if `nutrition_schema.sql` changes after
  any database already contains Nutrition tables.

## Known issues / risks

- `nutrition_schema.sql` uses idempotent `CREATE TABLE IF NOT EXISTS`; it will
  not alter existing Nutrition tables if the draft schema evolves.
- SQLite DDL intentionally does not enforce all canonical Decimal, positivity,
  confidence, or point-within-range checks; those are enforced by domain and
  repository serialization paths.
- Search for food profiles is exact case-insensitive matching only, not fuzzy or
  full text.
- JSON Schema packaging is covered by direct file lookup in tests, not by
  inspecting the built wheel contents.
- No production dependency was added for JSON Schema validation; the manual
  schema check used `uv run --with jsonschema`.
- JSON Schema fixture validation is currently covered by a manual
  `uv run --with jsonschema` command rather than regular pytest.

## Verification performed in finalization

- `AGENTS.md`, `docs/CURRENT_STATE.md`, and repository-level `docs/HANDOFF.md`
  were read from `main`; this worktree does not yet contain those files.
- `git status --short --branch`: inspected.
- `git diff`: inspected.
- `git diff --staged`: inspected.
- `git log --oneline -15`: inspected.
- `git diff --name-status HEAD..main`: inspected.
- `git diff --name-status main..HEAD`: inspected.
- `git merge-tree $(git merge-base HEAD main) HEAD main`: inspected.
- `uv run pytest tests/test_nutrition_repository.py -q`: passed, `20 passed`.
- `uv run pytest -q`: passed, `90 passed in 1.93s`.
- `uv run ruff check .`: passed.
- `uv run mypy src tests`: passed, `35 source files`.
- `git diff --check`: passed.

Previous supplementary checks also validated the JSON Schema fixture with
`uv run --with jsonschema` and built the package with `uv build`.

## Recommended next action

After this branch is committed cleanly, the next integration session should merge
or rebase it against latest `main`, preserve `nutrition_schema.sql` as
provisional until final migration numbering is assigned, and keep repository
documentation paths in favor of `main`'s global `docs/HANDOFF.md`.
