---
name: add-migration
description: How to add a muscle50 SQLite schema migration safely - use the number reserved in the spec, the BEGIN IMMEDIATE / INSERT OR IGNORE schema_migrations / COMMIT template, append-only trigger pattern, update the migration-version expectations in tests, keep read-only readers working on older databases, and leave the production migration to the user. Use whenever a spec has migration reserved:NNN or a change needs a new table, column, index or trigger.
user-invocable: false
---

# Adding a muscle50 migration

Sources: `src/muscle50/infrastructure/sqlite/migrations/001_initial.sql` through
`008_nutrition_meal_item_removals.sql`; `src/muscle50/infrastructure/sqlite/database.py`
(`ActivityRepository.migrate`); `src/muscle50/infrastructure/sqlite/nutrition_repository.py`
(`_removed_sequences`); `nutrition_reader.py` / `analytics_reader.py` (`MINIMUM_SCHEMA_VERSION`,
`_require_schema`); `tests/test_database.py` (`EXPECTED_VERSIONS`); `tests/test_cli.py` (migration
versions assertion); docs/CURRENT_STATE.md "SQLite migrations", "Important decisions", "Verification"
(production migration 8); docs/HANDOFF.md "Nutrition Meal Edit v1" (commit `b234ac8`).

## 0. Do you need one?

Prefer **no migration**. Most features so far shipped without one: analytics, taxonomy, recommendation,
nutrition targets (a JSON file), fact versioning (`supersedes_fact_id` already existed), and meal repeat.
A migration is justified only when the data cannot be represented without bending an existing column or
disabling a trigger. Meal Edit's audit is the example: it rejected "a hidden flag in an existing column"
and "turning the trigger off", and added table 8. Say why in the design.

## 1. The number comes from the orchestrator, not from you

- The orchestrator reserves the number with `python .claude/scripts/feature_state.py reserve-migration <id>`.
  The reservation is atomic and checks every local branch, every worktree and every existing
  reservation. It reaches you as `reserved:NNN`. Use exactly that number. If you were given `none`, stop
  and send the question back to design. The integrator writes `migration: reserved:NNN` into the
  committed spec frontmatter.
- Parallel features can be integrated in either order (for example 010 before 009). Each migration must
  stand alone: no reference to another in-flight feature's tables. The loader applies whatever files are
  present, and the production check compares the **set** of numbers, not the maximum.
- Why: the migration marker is `INSERT OR IGNORE`. When two branches both used `006`, the second file's
  DDL ran with **no version marker and no error**. InBody had to be renumbered to `007`
  (docs/CURRENT_STATE.md "SQLite migrations").
- File name: `NNN_<snake_case_purpose>.sql`, three digits. The loader runs every `*.sql` in that package
  sorted by name, on every `migrate()` call.

## 2. Template

The loader runs each file with `connection.executescript(...)`. `executescript` commits any pending
transaction first, so **the file owns its own transaction**. Every statement must be idempotent
(`IF NOT EXISTS`), because a migration interrupted halfway is completed on the next start
(`test_migration_completes_partial_ddl_without_version_marker`).

```sql
-- <Feature name>: <why this table/column exists, in 2-5 lines>.
-- <Which existing invariant it keeps (append-only, FK RESTRICT, ...)>.

BEGIN IMMEDIATE;

CREATE TABLE IF NOT EXISTS <table_name> (
    ...,
    PRIMARY KEY (...),
    FOREIGN KEY (...) REFERENCES <parent>(...) ON DELETE RESTRICT,
    CHECK (...)
);

CREATE INDEX IF NOT EXISTS <table_name>_<cols>_idx ON <table_name>(<cols>);

INSERT OR IGNORE INTO schema_migrations(version, applied_at_utc)
VALUES (NNN, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'));

COMMIT;
```

Rules seen in 001-008:
- No `ALTER`/`DROP` of existing tables. 001-008 only add tables, indexes and triggers. Migration 8
  "기존 table ALTER 없음" (docs/HANDOFF.md).
- Decimal values are stored as canonical TEXT, never REAL (`003_nutrition.sql`). Timestamps are ISO-8601
  UTC TEXT.
- Put invariants in the schema: `CHECK`, composite FKs, `CHECK ((a IS NULL) = (b IS NULL))` pairs.

### Append-only history (facts, tombstones)

When rows record history, forbid rewriting them (`003_nutrition.sql`, `008_...sql`):

```sql
CREATE TRIGGER IF NOT EXISTS <table_name>_prevent_update
BEFORE UPDATE ON <table_name>
BEGIN
    SELECT RAISE(ABORT, '<table description> are append-only');
END;

CREATE TRIGGER IF NOT EXISTS <table_name>_prevent_delete
BEFORE DELETE ON <table_name>
BEGIN
    SELECT RAISE(ABORT, '<table description> are append-only');
END;
```

To "change" or "remove" something, append a superseding row or a tombstone and make the readers skip it.
Migration 8's `_load_meal` skips removed items, and the removed rows stay for audit.

## 3. Repository and transaction code

- Writes go through the repository, inside one `BEGIN IMMEDIATE` transaction. Re-check every guard
  (exists, not already removed, not the last item, ...) inside that transaction, then write.
- Test that a failed step rolls everything back. `tests/test_nutrition_meal_edit.py` injects a
  `CREATE TRIGGER fail_step BEFORE INSERT ...` to force the failure.

## 4. Update the tests that pin the migration list

Both must list the new version, or the suite fails:
- `tests/test_database.py`: `EXPECTED_VERSIONS = [(1,), ..., (NNN,)]` and the literal
  `[1, 2, ..., NNN]` assertion in the same file.
- `tests/test_cli.py`: `assert migration_versions == [(1,), ..., (NNN,)]`.

These are the only existing-test edits a migration normally needs. Say so in the report.

## 5. Read-only readers must keep working on older databases

Readers never migrate. A user may run `recommend` before any writing command has applied the new
migration.
- If the new table is optional for the reader, check that it exists and fall back:

  ```python
  has_table = connection.execute(
      "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = '<table_name>'"
  ).fetchone()
  if has_table is None:
      return frozenset()   # an older DB cannot have rows in it either
  ```
- Raise `MINIMUM_SCHEMA_VERSION` in `nutrition_reader.py` / `analytics_reader.py` only if the reader truly
  cannot work without the new schema. The error message then tells the user how to migrate.
- Add a test that builds a database at the previous version (migrate, then delete the marker and the new
  table, or apply files 001..NNN-1) and shows that the read-only command still gives the old output.

## 6. Production is a human gate

- Agents never apply a migration to `%LOCALAPPDATA%\muscle50` on their own. Any writing command there
  would apply it. The PreToolUse hook therefore blocks every `muscle50` run against production while main
  contains a migration that production has not applied, and it blocks production runs from feature
  worktrees at all times.
- After integration, the user applies it, in their own terminal, or by asking Claude to do the backup and
  verification and then running the one migrating command themselves. The recorded procedure for migration 8
  (docs/CURRENT_STATE.md "Verification", 2026-10-03):
  1. Back up the production DB to a named copy (for example `db_backup_<YYYYMMDD>_pre_migrationNNN`), with SHA-256.
  2. Run one writing command, for example `uv run muscle50 nutrition food list`.
  3. Verify: `schema_migrations` contains 1..NNN once each; only the new objects were added; every existing
     table's rows are unchanged against the backup; `PRAGMA integrity_check` is ok and
     `PRAGMA foreign_key_check` is clean; the key read outputs (`nutrition day`/`status`, `recommend`) are
     byte-identical to before.
- In the spec and the final report, list "production migration NNN" under the remaining user gates, with
  this procedure.
