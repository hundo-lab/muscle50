BEGIN IMMEDIATE;

CREATE TABLE IF NOT EXISTS recovery_raw_captures (
    id TEXT PRIMARY KEY,
    provider TEXT NOT NULL,
    requested_date TEXT NOT NULL,
    manifest_relative_path TEXT NOT NULL UNIQUE,
    captured_at_utc TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS recovery_raw_artifacts (
    id INTEGER PRIMARY KEY,
    capture_id TEXT NOT NULL REFERENCES recovery_raw_captures(id),
    artifact_kind TEXT NOT NULL,
    relative_path TEXT NOT NULL UNIQUE,
    content_type TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    byte_size INTEGER NOT NULL CHECK (byte_size >= 0),
    UNIQUE (capture_id, artifact_kind)
);

CREATE TABLE IF NOT EXISTS daily_recovery (
    id INTEGER PRIMARY KEY,
    provider TEXT NOT NULL,
    calendar_date TEXT NOT NULL,
    sleep_seconds INTEGER,
    deep_sleep_seconds INTEGER,
    light_sleep_seconds INTEGER,
    rem_sleep_seconds INTEGER,
    awake_sleep_seconds INTEGER,
    sleep_start_gmt_ms INTEGER,
    sleep_end_gmt_ms INTEGER,
    sleep_score INTEGER,
    sleep_avg_hrv_ms REAL,
    hrv_last_night_avg_ms REAL,
    hrv_weekly_avg_ms REAL,
    hrv_status TEXT,
    resting_heart_rate_bpm REAL,
    body_battery_high INTEGER,
    body_battery_low INTEGER,
    stress_average INTEGER,
    training_readiness_score INTEGER,
    training_readiness_level TEXT,
    recovery_time_minutes INTEGER,
    recovery_time_change_phrase TEXT,
    training_status_key TEXT,
    respiration_avg_brpm REAL,
    primary_raw_capture_id TEXT NOT NULL REFERENCES recovery_raw_captures(id),
    normalizer_version INTEGER NOT NULL,
    imported_at_utc TEXT NOT NULL,
    updated_at_utc TEXT NOT NULL,
    UNIQUE (provider, calendar_date)
);

INSERT OR IGNORE INTO schema_migrations(version, applied_at_utc)
VALUES (5, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'));

COMMIT;
