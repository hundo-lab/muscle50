BEGIN IMMEDIATE;

CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at_utc TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sync_runs (
    id INTEGER PRIMARY KEY,
    provider TEXT NOT NULL,
    command TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('running', 'succeeded', 'skipped', 'failed')),
    source_activity_id TEXT,
    error_code TEXT,
    started_at_utc TEXT NOT NULL,
    finished_at_utc TEXT
);

CREATE TABLE IF NOT EXISTS raw_artifacts (
    id INTEGER PRIMARY KEY,
    provider TEXT NOT NULL,
    source_activity_id TEXT NOT NULL,
    artifact_kind TEXT NOT NULL,
    relative_path TEXT NOT NULL,
    content_type TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    byte_size INTEGER NOT NULL CHECK (byte_size >= 0),
    fetched_at_utc TEXT NOT NULL,
    UNIQUE (provider, source_activity_id, artifact_kind, sha256),
    UNIQUE (relative_path)
);

CREATE TABLE IF NOT EXISTS activities (
    id INTEGER PRIMARY KEY,
    provider TEXT NOT NULL,
    source_activity_id TEXT NOT NULL,
    source_type_key TEXT NOT NULL,
    canonical_type TEXT NOT NULL CHECK (
        canonical_type IN ('running', 'swimming', 'strength', 'cycling', 'walking', 'other')
    ),
    name TEXT,
    started_at_utc TEXT,
    started_at_local TEXT,
    timezone_name TEXT,
    elapsed_seconds REAL,
    moving_seconds REAL,
    distance_meters REAL,
    calories_kcal REAL,
    average_hr_bpm REAL,
    max_hr_bpm REAL,
    elevation_gain_meters REAL,
    primary_raw_artifact_id INTEGER NOT NULL REFERENCES raw_artifacts(id),
    normalizer_version INTEGER NOT NULL,
    imported_at_utc TEXT NOT NULL,
    UNIQUE (provider, source_activity_id)
);

CREATE TABLE IF NOT EXISTS activity_metrics (
    id INTEGER PRIMARY KEY,
    activity_id INTEGER NOT NULL REFERENCES activities(id) ON DELETE CASCADE,
    metric_key TEXT NOT NULL,
    numeric_value REAL,
    text_value TEXT,
    unit TEXT,
    source_path TEXT NOT NULL,
    CHECK (
        (numeric_value IS NOT NULL AND text_value IS NULL)
        OR (numeric_value IS NULL AND text_value IS NOT NULL)
    ),
    UNIQUE (activity_id, metric_key)
);

-- Corrections are append-only overlays. Garmin-normalized activity columns are never overwritten.
CREATE TABLE IF NOT EXISTS activity_corrections (
    id INTEGER PRIMARY KEY,
    activity_id INTEGER NOT NULL REFERENCES activities(id) ON DELETE CASCADE,
    field_key TEXT NOT NULL,
    revision INTEGER NOT NULL CHECK (revision > 0),
    corrected_value_json TEXT NOT NULL,
    reason TEXT,
    corrected_at_utc TEXT NOT NULL,
    UNIQUE (activity_id, field_key, revision)
);

INSERT OR IGNORE INTO schema_migrations(version, applied_at_utc)
VALUES (1, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'));

COMMIT;
