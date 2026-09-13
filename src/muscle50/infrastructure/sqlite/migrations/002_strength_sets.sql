BEGIN IMMEDIATE;

CREATE TABLE IF NOT EXISTS strength_sets (
    id INTEGER PRIMARY KEY,
    activity_id INTEGER NOT NULL REFERENCES activities(id) ON DELETE CASCADE,
    sequence INTEGER NOT NULL CHECK (sequence > 0),
    source_message_index INTEGER,
    source_exercise_category TEXT,
    source_exercise_name TEXT,
    source_exercise_key TEXT,
    display_exercise_name TEXT,
    source_exercise_probability REAL,
    set_type TEXT,
    reps INTEGER CHECK (reps IS NULL OR reps >= 0),
    source_weight REAL,
    source_weight_unit TEXT,
    normalized_weight_kg REAL,
    duration_seconds REAL,
    started_at TEXT,
    workout_step_index INTEGER,
    UNIQUE (activity_id, sequence)
);

INSERT OR IGNORE INTO schema_migrations(version, applied_at_utc)
VALUES (2, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'));

COMMIT;
