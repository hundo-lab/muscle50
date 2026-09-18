BEGIN IMMEDIATE;

CREATE TABLE IF NOT EXISTS inbody_raw_artifacts (
    id INTEGER PRIMARY KEY,
    provider TEXT NOT NULL CHECK (provider = 'inbody'),
    artifact_kind TEXT NOT NULL CHECK (
        artifact_kind IN ('measurement_list', 'measurement_detail')
    ),
    relative_path TEXT NOT NULL,
    metadata_relative_path TEXT NOT NULL,
    content_type TEXT NOT NULL,
    source_format TEXT NOT NULL,
    source_type TEXT NOT NULL,
    source_fetched_at TEXT NOT NULL,
    source_record_id TEXT,
    source_application TEXT,
    source_schema_version TEXT,
    sha256 TEXT NOT NULL,
    byte_size INTEGER NOT NULL CHECK (byte_size >= 0),
    fetched_at_utc TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS inbody_raw_artifacts_source_snapshot
ON inbody_raw_artifacts(
    provider,
    source_type,
    COALESCE(source_application, ''),
    artifact_kind,
    COALESCE(source_record_id, ''),
    source_format,
    COALESCE(source_schema_version, ''),
    sha256
);

CREATE TABLE IF NOT EXISTS body_composition_measurements (
    id INTEGER PRIMARY KEY,
    provider TEXT NOT NULL CHECK (provider = 'inbody'),
    canonical_fingerprint_version INTEGER,
    canonical_fingerprint TEXT,
    measured_at TEXT NOT NULL,
    weight_kg REAL,
    skeletal_muscle_mass_kg REAL,
    body_fat_mass_kg REAL,
    body_fat_percent REAL,
    bmi REAL,
    waist_hip_ratio REAL,
    visceral_fat_level REAL,
    basal_metabolic_rate_kcal_per_day REAL,
    total_body_water_l REAL,
    protein_kg REAL,
    minerals_kg REAL,
    ecw_ratio REAL,
    inbody_score REAL,
    device_model TEXT,
    primary_raw_artifact_id INTEGER NOT NULL REFERENCES inbody_raw_artifacts(id),
    normalizer_version INTEGER NOT NULL,
    imported_at_utc TEXT NOT NULL,
    CHECK (
        (canonical_fingerprint_version IS NULL AND canonical_fingerprint IS NULL)
        OR (canonical_fingerprint_version IS NOT NULL AND canonical_fingerprint IS NOT NULL)
    )
);

-- Source identities are unique only inside their source namespace. Canonical
-- fingerprints above are intentionally not unique: equal Samsung Health and
-- export records are comparison candidates, never automatically merged.
CREATE TABLE IF NOT EXISTS body_composition_source_identities (
    id INTEGER PRIMARY KEY,
    measurement_id INTEGER NOT NULL REFERENCES body_composition_measurements(id) ON DELETE CASCADE,
    source_type TEXT NOT NULL,
    source_profile_key TEXT NOT NULL,
    identity_kind TEXT NOT NULL CHECK (identity_kind IN ('source_id', 'fingerprint')),
    source_record_id TEXT,
    source_fingerprint_version INTEGER,
    source_fingerprint TEXT,
    is_primary INTEGER NOT NULL DEFAULT 0 CHECK (is_primary IN (0, 1)),
    CHECK (
        (identity_kind = 'source_id' AND source_record_id IS NOT NULL
            AND source_fingerprint_version IS NULL AND source_fingerprint IS NULL)
        OR
        (identity_kind = 'fingerprint' AND source_record_id IS NULL
            AND source_fingerprint_version IS NOT NULL AND source_fingerprint IS NOT NULL)
    )
);

CREATE UNIQUE INDEX IF NOT EXISTS body_composition_source_identities_record
ON body_composition_source_identities(source_type, source_profile_key, source_record_id)
WHERE identity_kind = 'source_id';

CREATE UNIQUE INDEX IF NOT EXISTS body_composition_source_identities_fingerprint
ON body_composition_source_identities(
    source_type, source_profile_key, source_fingerprint_version, source_fingerprint
)
WHERE identity_kind = 'fingerprint';

CREATE UNIQUE INDEX IF NOT EXISTS body_composition_source_identities_primary
ON body_composition_source_identities(measurement_id) WHERE is_primary = 1;

CREATE TABLE IF NOT EXISTS body_composition_raw_artifact_links (
    measurement_id INTEGER NOT NULL REFERENCES body_composition_measurements(id) ON DELETE CASCADE,
    raw_artifact_id INTEGER NOT NULL REFERENCES inbody_raw_artifacts(id),
    linked_at_utc TEXT NOT NULL,
    PRIMARY KEY (measurement_id, raw_artifact_id)
);

-- ordinal preserves the original tuple order so reconstruction round-trips exactly.
CREATE TABLE IF NOT EXISTS body_composition_provenance (
    id INTEGER PRIMARY KEY,
    measurement_id INTEGER NOT NULL REFERENCES body_composition_measurements(id) ON DELETE CASCADE,
    normalized_field TEXT NOT NULL,
    source_path TEXT NOT NULL,
    source_value_json TEXT NOT NULL,
    source_unit TEXT,
    transformation TEXT NOT NULL,
    ordinal INTEGER NOT NULL,
    UNIQUE (measurement_id, normalized_field)
);

CREATE TABLE IF NOT EXISTS body_composition_segmental_metrics (
    id INTEGER PRIMARY KEY,
    measurement_id INTEGER NOT NULL REFERENCES body_composition_measurements(id) ON DELETE CASCADE,
    region TEXT NOT NULL,
    metric_key TEXT NOT NULL,
    numeric_value REAL NOT NULL,
    unit TEXT NOT NULL,
    source_path TEXT NOT NULL,
    source_value_json TEXT NOT NULL,
    source_unit TEXT,
    transformation TEXT NOT NULL,
    ordinal INTEGER NOT NULL,
    UNIQUE (measurement_id, region, metric_key)
);

-- Normalized model-specific outputs (for example phase angle or a future field)
-- belong here instead of requiring a new wide-table column for every device.
-- normalized_field is stored explicitly: unlike the segmental table, nothing ties
-- metric_key to a fixed provenance field name for this open-ended extension point.
CREATE TABLE IF NOT EXISTS body_composition_metrics (
    id INTEGER PRIMARY KEY,
    measurement_id INTEGER NOT NULL REFERENCES body_composition_measurements(id) ON DELETE CASCADE,
    metric_key TEXT NOT NULL,
    numeric_value REAL,
    text_value TEXT,
    unit TEXT,
    source_path TEXT NOT NULL,
    source_value_json TEXT NOT NULL,
    source_unit TEXT,
    transformation TEXT NOT NULL,
    normalized_field TEXT NOT NULL,
    ordinal INTEGER NOT NULL,
    CHECK (
        (numeric_value IS NOT NULL AND text_value IS NULL)
        OR (numeric_value IS NULL AND text_value IS NOT NULL)
    ),
    UNIQUE (measurement_id, metric_key)
);

INSERT OR IGNORE INTO schema_migrations(version, applied_at_utc)
VALUES (7, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'));

COMMIT;
