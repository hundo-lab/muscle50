BEGIN IMMEDIATE;

CREATE TABLE IF NOT EXISTS activity_raw_captures (
    id TEXT PRIMARY KEY,
    provider TEXT NOT NULL,
    source_activity_id TEXT NOT NULL,
    manifest_relative_path TEXT NOT NULL UNIQUE,
    captured_at_utc TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS activity_raw_capture_artifacts (
    id INTEGER PRIMARY KEY,
    capture_id TEXT NOT NULL REFERENCES activity_raw_captures(id),
    artifact_kind TEXT NOT NULL,
    relative_path TEXT NOT NULL UNIQUE,
    content_type TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    byte_size INTEGER NOT NULL CHECK (byte_size >= 0),
    UNIQUE (capture_id, artifact_kind)
);

CREATE TABLE IF NOT EXISTS activity_refresh_state (
    activity_id INTEGER PRIMARY KEY REFERENCES activities(id) ON DELETE CASCADE,
    current_capture_id TEXT NOT NULL REFERENCES activity_raw_captures(id),
    refreshed_at_utc TEXT NOT NULL
);

INSERT OR IGNORE INTO schema_migrations(version, applied_at_utc)
VALUES (6, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'));

COMMIT;
