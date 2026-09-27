from __future__ import annotations

import json
import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest

from muscle50.application.inbody_repository import InMemoryBodyCompositionRepository
from muscle50.application.inbody_source import (
    InBodySourceError,
    InBodySourcePermissionDeniedError,
    InBodySourcePermissionRevokedError,
    InBodySourceUnavailableError,
)
from muscle50.application.sync_inbody import SyncInBody
from muscle50.domain.body_composition import RawInBodyDocument, SourceField
from muscle50.domain.inbody_normalization import (
    InBodyNormalizationError,
    normalize_inbody_measurement,
)
from muscle50.infrastructure.inbody.connector import InBodyResponseChangedError
from muscle50.infrastructure.inbody.raw_store import InBodyRawStore
from muscle50.infrastructure.inbody.synthetic import (
    SyntheticInBodyConnector,
    SyntheticInBodyMeasurementSource,
)
from muscle50.infrastructure.sqlite.body_composition import SqliteBodyCompositionRepository

FIXTURES = Path(__file__).parent / "fixtures" / "inbody"
LIST_FORMAT = "muscle50.synthetic.inbody.list.v1"
DETAIL_FORMAT = "muscle50.synthetic.inbody.v1"


def _payload(*, keep: set[str] | None = None) -> bytes:
    value = json.loads((FIXTURES / "synthetic_full.json").read_text(encoding="utf-8"))
    if keep is not None:
        value["fields"] = {
            name: field for name, field in value["fields"].items() if name == "measured_at" or name in keep
        }
        value["segments"] = []
    return json.dumps(value, separators=(",", ":")).encode()


def _source(
    source_type: str,
    *,
    detail: bytes | None = None,
    source_record_id: str = "synthetic-20260913-070000",
) -> SyntheticInBodyMeasurementSource:
    list_document = RawInBodyDocument(
        document=json.dumps(
            {
                "schema": LIST_FORMAT,
                "measurements": [
                    {
                        "source_profile_key": "synthetic-primary",
                        "source_measurement_id": source_record_id,
                        "measured_at": "2026-09-13T07:00:00+09:00",
                        "detail_key": "measurement-1",
                    }
                ],
            },
            separators=(",", ":"),
        ).encode(),
        content_type="application/json",
        source_format=LIST_FORMAT,
        source_type=source_type,
        source_application="com.example.synthetic.inbody",
        source_schema_version="1",
    )
    detail_document = RawInBodyDocument(
        document=detail if detail is not None else _payload(),
        content_type="application/json",
        source_format=DETAIL_FORMAT,
        source_type=source_type,
        source_record_id=source_record_id,
        source_application="com.example.synthetic.inbody",
        source_schema_version="1",
    )
    connector = SyntheticInBodyConnector(
        None,
        list_document=list_document,
        detail_documents={"measurement-1": detail_document},
    )
    return SyntheticInBodyMeasurementSource(connector)


def _sync(
    tmp_path: Path,
    source: SyntheticInBodyMeasurementSource,
    repository: InMemoryBodyCompositionRepository | SqliteBodyCompositionRepository | None = None,
) -> SyncInBody:
    root = tmp_path / "private-muscle50"
    return SyncInBody(
        source,
        repository or InMemoryBodyCompositionRepository(),
        InBodyRawStore(root / "raw" / "inbody" / "measurements", root, root / "tmp"),
    )


def test_synthetic_samsung_source_preserves_provenance_and_is_full(tmp_path: Path) -> None:
    database_path = tmp_path / "db" / "muscle50.sqlite3"
    repository = SqliteBodyCompositionRepository(database_path)
    repository.migrate()

    result = _sync(
        tmp_path,
        _source("inbody_samsung_health"),
        repository,
    ).execute()

    item = result.items[0]
    assert item.is_full_measurement is True
    assert item.measurement.source_identity.source_type == "inbody_samsung_health"
    with sqlite3.connect(database_path) as connection:
        raw = connection.execute(
            """
            SELECT source_type, source_record_id, source_application, source_schema_version
            FROM inbody_raw_artifacts
            """
        ).fetchone()
    assert raw == (
        "inbody_samsung_health",
        "synthetic-20260913-070000",
        "com.example.synthetic.inbody",
        "1",
    )


@pytest.mark.parametrize(
    ("source_type", "fields", "missing"),
    [
        (
            "inbody_health_connect",
            {"weight"},
            ("skeletal_muscle_mass_kg", "body_fat_mass_kg_or_body_fat_percent"),
        ),
        (
            "inbody_health_connect",
            {"body_fat_percent"},
            ("weight_kg", "skeletal_muscle_mass_kg"),
        ),
        (
            "inbody_health_connect",
            {"weight", "body_fat_percent"},
            ("skeletal_muscle_mass_kg",),
        ),
        (
            "inbody_samsung_health",
            {"weight", "skeletal_muscle_mass", "body_fat_percent"},
            (),
        ),
    ],
)
def test_partial_source_is_reported_without_inventing_missing_metrics(
    tmp_path: Path,
    source_type: str,
    fields: set[str],
    missing: tuple[str, ...],
) -> None:
    result = _sync(
        tmp_path,
        _source(source_type, detail=_payload(keep=fields)),
    ).execute()

    item = result.items[0]
    assert item.missing_minimum_fields == missing
    if "skeletal_muscle_mass" not in fields:
        assert item.measurement.skeletal_muscle_mass_kg is None


def test_zero_is_a_value_and_missing_is_none() -> None:
    source = _source("inbody_samsung_health", detail=_payload(keep={"weight", "body_fat_percent"}))
    document = source.list_measurements()
    reference = source.extract_measurement_references(document)[0]
    raw = source.extract_measurement(source.get_measurement(reference))

    zero = replace(
        raw,
        weight=SourceField(0, "kg", "$.result.weight"),
        body_fat_percent=SourceField(0, "%", "$.result.pbf"),
    )
    normalized = normalize_inbody_measurement(zero)

    assert normalized.weight_kg == 0
    assert normalized.body_fat_percent == 0
    assert normalized.skeletal_muscle_mass_kg is None


def test_health_connect_lean_mass_is_not_used_as_skeletal_muscle_mass(
    tmp_path: Path,
) -> None:
    value = json.loads(_payload(keep={"weight", "body_fat_percent"}))
    value["fields"]["lean_body_mass"] = {
        "value": 54.2,
        "unit": "kg",
        "path": "$.records.LeanBodyMassRecord.mass",
    }

    result = _sync(
        tmp_path,
        _source("inbody_health_connect", detail=json.dumps(value).encode()),
    ).execute()

    assert result.items[0].measurement.skeletal_muscle_mass_kg is None
    assert result.items[0].missing_minimum_fields == ("skeletal_muscle_mass_kg",)


def test_same_measurement_from_two_sources_is_not_automatically_merged(tmp_path: Path) -> None:
    repository = InMemoryBodyCompositionRepository()

    samsung = _sync(tmp_path, _source("inbody_samsung_health"), repository).execute()
    exported = _sync(tmp_path, _source("inbody_export"), repository).execute()

    assert samsung.created_count == 1
    assert exported.created_count == 1
    assert samsung.items[0].measurement.canonical_identity == exported.items[0].measurement.canonical_identity


@pytest.mark.parametrize(
    "error",
    [
        InBodySourcePermissionDeniedError(),
        InBodySourcePermissionRevokedError(),
        InBodySourceUnavailableError(),
    ],
)
def test_source_access_failures_are_distinct_and_redacted(tmp_path: Path, error: InBodySourceError) -> None:
    source = SyntheticInBodyMeasurementSource(
        SyntheticInBodyConnector(None),
        list_error=error,
    )

    with pytest.raises(type(error)) as captured:
        _sync(tmp_path, source).execute()

    assert "synthetic-secret" not in str(captured.value)


def test_unit_mismatch_is_rejected_without_guessing(tmp_path: Path) -> None:
    value = json.loads(_payload())
    value["fields"]["skeletal_muscle_mass"]["unit"] = "percent"
    source = _source("inbody_samsung_health", detail=json.dumps(value).encode())

    with pytest.raises(InBodyNormalizationError, match="unsupported unit"):
        _sync(tmp_path, source).execute()


def test_source_record_metadata_mismatch_is_preserved_then_rejected(tmp_path: Path) -> None:
    source = _source("inbody_samsung_health")
    document = source.list_measurements()
    reference = source.extract_measurement_references(document)[0]
    detail = source.get_measurement(reference)
    connector = SyntheticInBodyConnector(
        None,
        list_document=document,
        detail_documents={"measurement-1": replace(detail, source_record_id="different-record")},
    )

    with pytest.raises(InBodyResponseChangedError):
        _sync(tmp_path, SyntheticInBodyMeasurementSource(connector)).execute()

    assert any(path.read_bytes() == detail.document for path in (tmp_path / "private-muscle50" / "raw").rglob("*.json"))


@pytest.mark.parametrize(
    "detail",
    [b"not-json", b'{"schema":"unexpected"}'],
)
def test_malformed_or_drifted_source_schema_is_preserved_then_rejected(
    tmp_path: Path,
    detail: bytes,
) -> None:
    source = _source("inbody_samsung_health", detail=detail)

    with pytest.raises(InBodyResponseChangedError):
        _sync(tmp_path, source).execute()

    raw_files = list((tmp_path / "private-muscle50" / "raw").rglob("*.json"))
    assert any(path.read_bytes() == detail for path in raw_files)
    metadata = [
        json.loads(path.read_text(encoding="utf-8")) for path in (tmp_path / "private-muscle50" / "raw").rglob("*.meta")
    ]
    failed_detail = next(item for item in metadata if item["kind"] == "measurement_detail")
    assert failed_detail["source_type"] == "inbody_samsung_health"
    assert failed_detail["source_record_id"] == "synthetic-20260913-070000"
    assert failed_detail["source_application"] == "com.example.synthetic.inbody"
    assert failed_detail["source_schema_version"] == "1"
    assert failed_detail["source_fetched_at"]
