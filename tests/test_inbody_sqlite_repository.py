from __future__ import annotations

import sqlite3
from dataclasses import replace
from pathlib import Path

from muscle50.application.sync_latest_inbody import SyncLatestInBodyMeasurement
from muscle50.domain.body_composition import BodyCompositionMetric, FieldProvenance
from muscle50.domain.inbody_normalization import normalize_inbody_measurement
from muscle50.infrastructure.inbody.raw_store import InBodyRawArtifact, InBodyRawStore
from muscle50.infrastructure.inbody.synthetic import SyntheticInBodyConnector
from muscle50.infrastructure.sqlite.body_composition import SqliteBodyCompositionRepository

FIXTURES = Path(__file__).parent / "fixtures" / "inbody"


def _artifact(
    relative_path: str = "raw/a.json",
    sha256: str = "a" * 64,
    byte_size: int = 1,
) -> InBodyRawArtifact:
    return InBodyRawArtifact(
        relative_path=relative_path,
        metadata_relative_path=f"{relative_path}.meta",
        content_type="application/json",
        source_format="synthetic",
        sha256=sha256,
        byte_size=byte_size,
        source_type="inbody_synthetic",
        source_fetched_at="2026-09-13T00:00:00+00:00",
    )


def _normalized_without_id():
    connector = SyntheticInBodyConnector.from_fixture(FIXTURES / "synthetic_without_id.json")
    document = connector.latest_document()
    assert document is not None
    return normalize_inbody_measurement(connector.extract_measurement(document))


def _repository(tmp_path: Path) -> SqliteBodyCompositionRepository:
    repository = SqliteBodyCompositionRepository(tmp_path / "db" / "muscle50.sqlite3")
    repository.migrate()
    return repository


def _normalized_full():
    connector = SyntheticInBodyConnector.from_fixture(FIXTURES / "synthetic_full.json")
    document = connector.latest_document()
    assert document is not None
    return normalize_inbody_measurement(connector.extract_measurement(document))


def test_duplicate_sync_stores_one_measurement_and_one_artifact_link(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    root = tmp_path / "private-muscle50"
    raw_store = InBodyRawStore(root / "raw" / "inbody" / "measurements", root, root / "tmp")
    connector = SyntheticInBodyConnector.from_fixture(FIXTURES / "synthetic_full.json")
    use_case = SyncLatestInBodyMeasurement(connector, repository, raw_store)

    first = use_case.execute()
    second = use_case.execute()

    assert first.created is True
    assert second.created is False
    assert second.measurement == first.measurement

    with sqlite3.connect(tmp_path / "db" / "muscle50.sqlite3") as connection:
        measurement_count = connection.execute("SELECT COUNT(*) FROM body_composition_measurements").fetchone()[0]
        link_count = connection.execute("SELECT COUNT(*) FROM body_composition_raw_artifact_links").fetchone()[0]
        artifact_count = connection.execute("SELECT COUNT(*) FROM inbody_raw_artifacts").fetchone()[0]
    assert measurement_count == 1
    assert link_count == 1
    assert artifact_count == 1


def test_equal_canonical_fingerprint_from_two_sources_is_not_merged(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    base = _normalized_full()
    artifact = _artifact()
    first = replace(
        base,
        source_identity=replace(base.source_identity, source_record_id="official-a"),
    )
    second = replace(
        base,
        source_identity=replace(
            base.source_identity,
            source_type="inbody_export",
            source_record_id="official-a",
        ),
    )

    assert repository.save(first, artifact).created is True
    assert repository.save(second, artifact).created is True


def test_idless_measurement_does_not_gain_heuristic_official_alias(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    base = _normalized_without_id()
    artifact = _artifact()
    with_id = replace(
        base,
        source_identity=replace(
            base.source_identity,
            source_record_id="official-a",
            source_fingerprint_version=None,
            source_fingerprint=None,
        ),
    )
    assert with_id.canonical_identity is not None
    changed_payload_same_id = replace(
        with_id,
        canonical_identity=replace(with_id.canonical_identity, fingerprint="b" * 64),
    )

    assert repository.save(base, artifact).created is True
    assert repository.save(with_id, artifact).created is True
    assert repository.save(changed_payload_same_id, artifact).created is False

    with sqlite3.connect(tmp_path / "db" / "muscle50.sqlite3") as connection:
        measurement_rows = connection.execute("SELECT id FROM body_composition_measurements").fetchall()
        alias_rows = connection.execute(
            "SELECT source_record_id, is_primary FROM body_composition_source_identities ORDER BY source_record_id"
        ).fetchall()

    assert len(measurement_rows) == 2
    assert alias_rows == [(None, 1), ("official-a", 1)]


def test_full_round_trip_reloads_equal_measurement_with_provenance_segmental_and_metrics(
    tmp_path: Path,
) -> None:
    repository = _repository(tmp_path)
    base = _normalized_full()
    extra_metric = BodyCompositionMetric(
        key="phase_angle_50khz",
        value=6.4,
        unit="deg",
        provenance=FieldProvenance(
            normalized_field="metrics.phase_angle_50khz",
            source_path="$.result.phaseAngle",
            source_value=6.4,
            source_unit="deg",
            transformation="identity",
        ),
    )
    text_metric = BodyCompositionMetric(
        key="device_serial",
        value="SN-0001",
        unit=None,
        provenance=FieldProvenance(
            normalized_field="metrics.device_serial",
            source_path="$.device.serial",
            source_value="SN-0001",
            source_unit=None,
            transformation="identity",
        ),
    )
    measurement = replace(base, metrics=(extra_metric, text_metric))
    artifact = _artifact("raw/full.json", "b" * 64, 42)

    saved = repository.save(measurement, artifact)
    assert saved.created is True

    reloaded = repository.find(measurement.source_identity)
    assert reloaded is not None
    assert reloaded == measurement
    assert reloaded.provenance == measurement.provenance
    assert reloaded.segmental_measurements == measurement.segmental_measurements
    assert reloaded.metrics == measurement.metrics

    # Segmental provenance.normalized_field is reconstructed rather than stored;
    # pin the exact string the normalizer produces.
    first_segment = reloaded.segmental_measurements[0]
    assert first_segment.provenance.normalized_field == f"segmental.{first_segment.region}.{first_segment.metric}"
