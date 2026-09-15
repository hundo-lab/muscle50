-- Normalized Garmin pool-swimming lap and length hierarchy.

BEGIN IMMEDIATE;

CREATE TABLE IF NOT EXISTS swim_activities (
    activity_id INTEGER PRIMARY KEY REFERENCES activities(id) ON DELETE CASCADE,
    source_type_key TEXT NOT NULL,
    pool_length_meters REAL,
    source_pool_length REAL,
    source_pool_length_unit TEXT,
    source_active_length_count INTEGER,
    splits_available INTEGER NOT NULL CHECK (splits_available IN (0, 1)),
    garmin_source_path TEXT NOT NULL,
    garmin_source_json TEXT NOT NULL,
    normalizer_version INTEGER NOT NULL CHECK (normalizer_version > 0)
);

CREATE TABLE IF NOT EXISTS swim_laps (
    id INTEGER PRIMARY KEY,
    activity_id INTEGER NOT NULL REFERENCES swim_activities(activity_id) ON DELETE CASCADE,
    sequence INTEGER NOT NULL CHECK (sequence >= 0),
    source_lap_index INTEGER,
    source_message_index INTEGER,
    start_time_utc TEXT,
    intensity_type TEXT,
    stroke_type TEXT,
    garmin_distance_meters REAL,
    corrected_distance_meters REAL,
    duration_seconds REAL,
    moving_seconds REAL,
    elapsed_seconds REAL,
    garmin_rest_duration_seconds REAL,
    average_speed_mps REAL,
    active_length_count INTEGER,
    total_length_count INTEGER,
    stroke_count INTEGER,
    swolf REAL,
    average_hr_bpm REAL,
    max_hr_bpm REAL,
    garmin_source_path TEXT NOT NULL,
    garmin_source_json TEXT NOT NULL,
    UNIQUE (activity_id, sequence)
);

CREATE TABLE IF NOT EXISTS swim_lengths (
    id INTEGER PRIMARY KEY,
    swim_lap_id INTEGER NOT NULL REFERENCES swim_laps(id) ON DELETE CASCADE,
    sequence INTEGER NOT NULL CHECK (sequence >= 0),
    sequence_in_lap INTEGER NOT NULL CHECK (sequence_in_lap >= 0),
    source_message_index INTEGER,
    start_time_utc TEXT,
    length_type TEXT,
    stroke_type TEXT,
    garmin_distance_meters REAL,
    corrected_distance_meters REAL,
    duration_seconds REAL,
    moving_seconds REAL,
    elapsed_seconds REAL,
    garmin_rest_duration_seconds REAL,
    average_speed_mps REAL,
    stroke_count INTEGER,
    swolf REAL,
    average_hr_bpm REAL,
    max_hr_bpm REAL,
    garmin_source_path TEXT NOT NULL,
    garmin_source_json TEXT NOT NULL,
    UNIQUE (swim_lap_id, sequence_in_lap)
);

CREATE INDEX IF NOT EXISTS swim_laps_activity_id_idx ON swim_laps(activity_id);
CREATE INDEX IF NOT EXISTS swim_lengths_lap_id_idx ON swim_lengths(swim_lap_id);

INSERT OR IGNORE INTO schema_migrations(version, applied_at_utc)
VALUES (4, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'));

COMMIT;
