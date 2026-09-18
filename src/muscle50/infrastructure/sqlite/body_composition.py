"""SQLite adapter for source-local body-composition identity."""

from __future__ import annotations

import json
import sqlite3
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from muscle50.application.inbody_repository import (
    BodyCompositionSaveResult,
)
from muscle50.domain.body_composition import (
    BodyCompositionMetric,
    CanonicalMeasurementIdentity,
    FieldProvenance,
    NormalizedBodyComposition,
    SegmentalMeasurement,
    SourceMeasurementIdentity,
)
from muscle50.infrastructure.inbody.raw_store import InBodyRawArtifact
from muscle50.infrastructure.sqlite.database import ActivityRepository


class SqliteBodyCompositionRepository:
    def __init__(self, database_path: Path):
        self._database_path = database_path

    def migrate(self) -> None:
        ActivityRepository(self._database_path).migrate()

    def find(self, identity: SourceMeasurementIdentity) -> NormalizedBodyComposition | None:
        with _connect(self._database_path) as connection:
            measurement_id = self._find_measurement_id(connection, identity)
            if measurement_id is None:
                return None
            return _load_measurement(connection, measurement_id)

    def save(
        self,
        measurement: NormalizedBodyComposition,
        artifact: InBodyRawArtifact,
    ) -> BodyCompositionSaveResult:
        timestamp = _now()
        try:
            with _connect(self._database_path) as connection:
                connection.execute("BEGIN IMMEDIATE")
                artifact_id = _upsert_artifact(connection, artifact, timestamp)
                identity = measurement.source_identity
                measurement_id = self._find_measurement_id(connection, identity)
                if measurement_id is not None:
                    link = connection.execute(
                        """
                        INSERT OR IGNORE INTO body_composition_raw_artifact_links (
                            measurement_id, raw_artifact_id, linked_at_utc
                        ) VALUES (?, ?, ?)
                        """,
                        (measurement_id, artifact_id, timestamp),
                    )
                    loaded = _load_measurement(connection, measurement_id)
                    return BodyCompositionSaveResult(loaded, False, link.rowcount == 1)
                _insert_measurement(connection, measurement, artifact_id, timestamp)
        except sqlite3.IntegrityError:
            existing = self.find(measurement.source_identity)
            if existing is not None:
                return BodyCompositionSaveResult(existing, False, False)
            raise
        return BodyCompositionSaveResult(measurement, True, True)

    def _find_measurement_id(self, connection: sqlite3.Connection, identity: SourceMeasurementIdentity) -> int | None:
        if identity.source_record_id is not None:
            row = connection.execute(
                """
                SELECT m.id AS id FROM body_composition_measurements m
                JOIN body_composition_source_identities s ON s.measurement_id = m.id
                WHERE s.source_type = ? AND s.source_profile_key = ?
                  AND s.identity_kind = 'source_id' AND s.source_record_id = ?
                """,
                (identity.source_type, identity.source_profile_key, identity.source_record_id),
            ).fetchone()
            return int(row["id"]) if row is not None else None
        if identity.source_fingerprint_version is None or identity.source_fingerprint is None:
            return None
        row = connection.execute(
            """
            SELECT m.id AS id FROM body_composition_measurements m
            JOIN body_composition_source_identities s ON s.measurement_id = m.id
            WHERE s.source_type = ? AND s.source_profile_key = ?
              AND s.identity_kind = 'fingerprint'
              AND s.source_fingerprint_version = ? AND s.source_fingerprint = ?
            """,
            (
                identity.source_type,
                identity.source_profile_key,
                identity.source_fingerprint_version,
                identity.source_fingerprint,
            ),
        ).fetchone()
        return int(row["id"]) if row is not None else None


@contextmanager
def _connect(database_path: Path) -> Iterator[sqlite3.Connection]:
    database_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(database_path, timeout=5, isolation_level=None)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 5000")
    _enable_wal(connection)
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _enable_wal(connection: sqlite3.Connection) -> None:
    for attempt in range(5):
        try:
            connection.execute("PRAGMA journal_mode = WAL")
            return
        except sqlite3.OperationalError as exc:
            if "locked" not in str(exc).lower() or attempt == 4:
                raise
            time.sleep(0.05 * (attempt + 1))


def _upsert_artifact(connection: sqlite3.Connection, artifact: InBodyRawArtifact, fetched_at: str) -> int:
    connection.execute(
        """
        INSERT OR IGNORE INTO inbody_raw_artifacts (
            provider, artifact_kind, relative_path, content_type, source_format,
            metadata_relative_path,
            source_type, source_fetched_at, source_record_id, source_application,
            source_schema_version, sha256, byte_size, fetched_at_utc
        ) VALUES ('inbody', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            artifact.kind,
            artifact.relative_path,
            artifact.content_type,
            artifact.source_format,
            artifact.metadata_relative_path,
            artifact.source_type,
            artifact.source_fetched_at or fetched_at,
            artifact.source_record_id,
            artifact.source_application,
            artifact.source_schema_version,
            artifact.sha256,
            artifact.byte_size,
            fetched_at,
        ),
    )
    stored = connection.execute(
        """
        SELECT * FROM inbody_raw_artifacts
        WHERE provider = 'inbody' AND source_type = ?
          AND COALESCE(source_application, '') = COALESCE(?, '')
          AND artifact_kind = ? AND COALESCE(source_record_id, '') = COALESCE(?, '')
          AND source_format = ?
          AND COALESCE(source_schema_version, '') = COALESCE(?, '')
          AND sha256 = ?
        """,
        (
            artifact.source_type,
            artifact.source_application,
            artifact.kind,
            artifact.source_record_id,
            artifact.source_format,
            artifact.source_schema_version,
            artifact.sha256,
        ),
    ).fetchone()
    if stored is None or any(
        (
            stored["artifact_kind"] != artifact.kind,
            stored["relative_path"] != artifact.relative_path,
            stored["content_type"] != artifact.content_type,
            stored["source_format"] != artifact.source_format,
            stored["source_type"] != artifact.source_type,
            stored["source_record_id"] != artifact.source_record_id,
            stored["source_application"] != artifact.source_application,
            stored["source_schema_version"] != artifact.source_schema_version,
            stored["byte_size"] != artifact.byte_size,
        )
    ):
        raise RuntimeError("stored InBody RAW artifact metadata does not match the file")
    return int(stored["id"])


def _insert_measurement(
    connection: sqlite3.Connection,
    measurement: NormalizedBodyComposition,
    artifact_id: int,
    imported_at: str,
) -> int:
    identity = measurement.source_identity
    canonical = measurement.canonical_identity
    cursor = connection.execute(
        """
        INSERT INTO body_composition_measurements (
            provider, canonical_fingerprint_version, canonical_fingerprint,
            measured_at, weight_kg, skeletal_muscle_mass_kg, body_fat_mass_kg, body_fat_percent,
            bmi, waist_hip_ratio, visceral_fat_level, basal_metabolic_rate_kcal_per_day,
            total_body_water_l, protein_kg, minerals_kg, ecw_ratio, inbody_score, device_model,
            primary_raw_artifact_id, normalizer_version, imported_at_utc
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "inbody",
            canonical.fingerprint_version if canonical is not None else None,
            canonical.fingerprint if canonical is not None else None,
            measurement.measured_at,
            measurement.weight_kg,
            measurement.skeletal_muscle_mass_kg,
            measurement.body_fat_mass_kg,
            measurement.body_fat_percent,
            measurement.bmi,
            measurement.waist_hip_ratio,
            measurement.visceral_fat_level,
            measurement.basal_metabolic_rate_kcal_per_day,
            measurement.total_body_water_l,
            measurement.protein_kg,
            measurement.minerals_kg,
            measurement.ecw_ratio,
            measurement.inbody_score,
            measurement.device_model,
            artifact_id,
            measurement.normalizer_version,
            imported_at,
        ),
    )
    if cursor.lastrowid is None:
        raise RuntimeError("SQLite did not return a body composition measurement ID")
    measurement_id = cursor.lastrowid
    identity_kind = "source_id" if identity.source_record_id is not None else "fingerprint"
    connection.execute(
        """
        INSERT INTO body_composition_source_identities (
            measurement_id, source_type, source_profile_key, identity_kind,
            source_record_id, source_fingerprint_version, source_fingerprint, is_primary
        ) VALUES (?, ?, ?, ?, ?, ?, ?, 1)
        """,
        (
            measurement_id,
            identity.source_type,
            identity.source_profile_key,
            identity_kind,
            identity.source_record_id,
            identity.source_fingerprint_version if identity_kind == "fingerprint" else None,
            identity.source_fingerprint if identity_kind == "fingerprint" else None,
        ),
    )
    for ordinal, provenance in enumerate(measurement.provenance):
        connection.execute(
            """
            INSERT INTO body_composition_provenance (
                measurement_id, normalized_field, source_path, source_value_json, source_unit,
                transformation, ordinal
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                measurement_id,
                provenance.normalized_field,
                provenance.source_path,
                json.dumps(provenance.source_value),
                provenance.source_unit,
                provenance.transformation,
                ordinal,
            ),
        )
    for ordinal, segment in enumerate(measurement.segmental_measurements):
        connection.execute(
            """
            INSERT INTO body_composition_segmental_metrics (
                measurement_id, region, metric_key, numeric_value, unit, source_path,
                source_value_json, source_unit, transformation, ordinal
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                measurement_id,
                segment.region,
                segment.metric,
                segment.value,
                segment.unit,
                segment.provenance.source_path,
                json.dumps(segment.provenance.source_value),
                segment.provenance.source_unit,
                segment.provenance.transformation,
                ordinal,
            ),
        )
    for ordinal, metric in enumerate(measurement.metrics):
        numeric, text = (None, metric.value) if isinstance(metric.value, str) else (metric.value, None)
        connection.execute(
            """
            INSERT INTO body_composition_metrics (
                measurement_id, metric_key, numeric_value, text_value, unit, source_path,
                source_value_json, source_unit, transformation, normalized_field, ordinal
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                measurement_id,
                metric.key,
                numeric,
                text,
                metric.unit,
                metric.provenance.source_path,
                json.dumps(metric.provenance.source_value),
                metric.provenance.source_unit,
                metric.provenance.transformation,
                metric.provenance.normalized_field,
                ordinal,
            ),
        )
    connection.execute(
        """
        INSERT OR IGNORE INTO body_composition_raw_artifact_links (
            measurement_id, raw_artifact_id, linked_at_utc
        ) VALUES (?, ?, ?)
        """,
        (measurement_id, artifact_id, imported_at),
    )
    return measurement_id


def _load_measurement(connection: sqlite3.Connection, measurement_id: int) -> NormalizedBodyComposition:
    row = connection.execute("SELECT * FROM body_composition_measurements WHERE id = ?", (measurement_id,)).fetchone()
    if row is None:
        raise RuntimeError("body composition measurement disappeared inside its own transaction")
    identity_row = connection.execute(
        """
        SELECT * FROM body_composition_source_identities
        WHERE measurement_id = ? AND is_primary = 1
        """,
        (measurement_id,),
    ).fetchone()
    if identity_row is None:
        raise RuntimeError("body composition measurement is missing its source identity")
    source_identity = SourceMeasurementIdentity(
        source_type=identity_row["source_type"],
        source_profile_key=identity_row["source_profile_key"],
        source_record_id=identity_row["source_record_id"],
        source_fingerprint_version=identity_row["source_fingerprint_version"],
        source_fingerprint=identity_row["source_fingerprint"],
    )
    canonical_identity = (
        CanonicalMeasurementIdentity(
            fingerprint_version=row["canonical_fingerprint_version"],
            fingerprint=row["canonical_fingerprint"],
        )
        if row["canonical_fingerprint"] is not None
        else None
    )
    provenance_rows = connection.execute(
        "SELECT * FROM body_composition_provenance WHERE measurement_id = ? ORDER BY ordinal",
        (measurement_id,),
    ).fetchall()
    provenance = tuple(_provenance_from_row(item) for item in provenance_rows)
    segmental_rows = connection.execute(
        "SELECT * FROM body_composition_segmental_metrics WHERE measurement_id = ? ORDER BY ordinal",
        (measurement_id,),
    ).fetchall()
    segmental = tuple(
        SegmentalMeasurement(
            region=item["region"],
            metric=item["metric_key"],
            value=item["numeric_value"],
            unit=item["unit"],
            provenance=FieldProvenance(
                normalized_field=f"segmental.{item['region']}.{item['metric_key']}",
                source_path=item["source_path"],
                source_value=json.loads(item["source_value_json"]),
                source_unit=item["source_unit"],
                transformation=item["transformation"],
            ),
        )
        for item in segmental_rows
    )
    metric_rows = connection.execute(
        "SELECT * FROM body_composition_metrics WHERE measurement_id = ? ORDER BY ordinal",
        (measurement_id,),
    ).fetchall()
    metrics = tuple(
        BodyCompositionMetric(
            key=item["metric_key"],
            value=item["numeric_value"] if item["numeric_value"] is not None else item["text_value"],
            unit=item["unit"],
            provenance=FieldProvenance(
                normalized_field=item["normalized_field"],
                source_path=item["source_path"],
                source_value=json.loads(item["source_value_json"]),
                source_unit=item["source_unit"],
                transformation=item["transformation"],
            ),
        )
        for item in metric_rows
    )
    return NormalizedBodyComposition(
        source_identity=source_identity,
        canonical_identity=canonical_identity,
        measured_at=row["measured_at"],
        weight_kg=row["weight_kg"],
        skeletal_muscle_mass_kg=row["skeletal_muscle_mass_kg"],
        body_fat_mass_kg=row["body_fat_mass_kg"],
        body_fat_percent=row["body_fat_percent"],
        bmi=row["bmi"],
        waist_hip_ratio=row["waist_hip_ratio"],
        visceral_fat_level=row["visceral_fat_level"],
        basal_metabolic_rate_kcal_per_day=row["basal_metabolic_rate_kcal_per_day"],
        total_body_water_l=row["total_body_water_l"],
        protein_kg=row["protein_kg"],
        minerals_kg=row["minerals_kg"],
        ecw_ratio=row["ecw_ratio"],
        inbody_score=row["inbody_score"],
        device_model=row["device_model"],
        segmental_measurements=segmental,
        metrics=metrics,
        provenance=provenance,
        normalizer_version=row["normalizer_version"],
    )


def _provenance_from_row(row: sqlite3.Row) -> FieldProvenance:
    return FieldProvenance(
        normalized_field=row["normalized_field"],
        source_path=row["source_path"],
        source_value=json.loads(row["source_value_json"]),
        source_unit=row["source_unit"],
        transformation=row["transformation"],
    )
