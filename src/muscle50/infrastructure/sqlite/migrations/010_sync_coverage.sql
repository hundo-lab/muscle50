-- Garmin Sync Coverage v1: the latest sync result per (provider, data kind, calendar date), so
-- "synced, Garmin had no data" differs from "never synced". No row means not synced: 'not_synced'
-- is never stored. Latest-state like daily_recovery: a later sync of the same date replaces the
-- row; the recovery RAW backfill only inserts where no row exists.
-- No existing table is altered and no other migration's table is referenced; sync_runs stays unused.

BEGIN IMMEDIATE;

CREATE TABLE IF NOT EXISTS sync_coverage (
    provider TEXT NOT NULL,
    data_kind TEXT NOT NULL CHECK (data_kind IN ('activities', 'recovery')),
    calendar_date TEXT NOT NULL CHECK (calendar_date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
    status TEXT NOT NULL CHECK (status IN ('synced', 'partial', 'failed')),
    source TEXT NOT NULL CHECK (source IN ('sync', 'raw_backfill')),
    command TEXT NOT NULL CHECK (command <> ''),
    -- Comma-separated recovery endpoint kinds; partial rows only.
    missing_endpoints TEXT,
    -- Comma-separated Garmin activity IDs; failed activity rows only.
    failed_activity_ids TEXT,
    -- Sync time (UTC ISO-8601); for raw_backfill rows, the accepted capture's captured_at_utc.
    synced_at_utc TEXT NOT NULL,
    PRIMARY KEY (provider, data_kind, calendar_date),
    CHECK (status <> 'partial' OR data_kind = 'recovery'),
    CHECK ((status = 'partial') = (missing_endpoints IS NOT NULL)),
    CHECK ((data_kind = 'activities' AND status = 'failed') = (failed_activity_ids IS NOT NULL)),
    CHECK (source = 'sync' OR (data_kind = 'recovery' AND status IN ('synced', 'partial')))
);

INSERT OR IGNORE INTO schema_migrations(version, applied_at_utc)
VALUES (10, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'));

COMMIT;
