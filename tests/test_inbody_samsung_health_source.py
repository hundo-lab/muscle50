"""Synthetic Samsung Health diagnostic payload coverage for SamsungHealthInBodySource.

No real personal Samsung/InBody record is used anywhere in this file; every payload is
hand-built to match docs/samsung-health-payload-contract.md's Samsung-SDK-confirmed field
shapes. Values are made up, not observed from a live device.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from muscle50.application.inbody_repository import InMemoryBodyCompositionRepository
from muscle50.application.inbody_source import (
    InBodySourcePermissionDeniedError,
    InBodySourceResponseChangedError,
    InBodySourceUnavailableError,
)
from muscle50.application.sync_inbody import SyncInBody
from muscle50.infrastructure.inbody.raw_store import InBodyRawStore
from muscle50.infrastructure.inbody.samsung_health import SamsungHealthInBodySource
from muscle50.infrastructure.inbody.samsung_health_smoke import main as smoke_main

PROFILE_KEY = "5e6f2c9a-0000-0000-0000-000000000000"
INBODY_APP_ID = "com.inbody2014.inbody"


def _record(
    *,
    source_record_id: str = "samsung-uid-1",
    measured_at: str = "2026-09-17T08:55:00",
    zone_offset: str | None = "+09:00",
    data_source_app_id: str | None = INBODY_APP_ID,
    weight: float | None = 70.0,
    skeletal_muscle_mass: float | None = 31.2,
    body_fat_mass: float | None = None,
    body_fat_percent: float | None = 20.1,
    bmi: float | None = 22.9,
    basal_metabolic_rate: float | None = 1589.9,
    total_body_water: float | None = 39.8,
    weight_unit: str = "kg",
    extra_fields: dict[str, Any] | None = None,
) -> dict[str, Any]:
    def field(value: float | None, unit: str | None, path: str) -> dict[str, Any] | None:
        return None if value is None else {"value": value, "unit": unit, "path": path}

    fields: dict[str, Any] = {
        "weight": field(weight, weight_unit, "BodyCompositionType.WEIGHT"),
        "skeletal_muscle_mass": field(skeletal_muscle_mass, "kg", "BodyCompositionType.SKELETAL_MUSCLE_MASS"),
        "body_fat_mass": field(body_fat_mass, "kg", "BodyCompositionType.BODY_FAT_MASS"),
        "body_fat_percent": field(body_fat_percent, "%", "BodyCompositionType.BODY_FAT"),
        "bmi": field(bmi, None, "BodyCompositionType.BODY_MASS_INDEX"),
        "basal_metabolic_rate": field(basal_metabolic_rate, "kcal/day", "BodyCompositionType.BASAL_METABOLIC_RATE"),
        "total_body_water": field(total_body_water, "L", "BodyCompositionType.TOTAL_BODY_WATER"),
    }
    if extra_fields:
        fields.update(extra_fields)
    return {
        "source_record_id": source_record_id,
        "measured_at": measured_at,
        "zone_offset": zone_offset,
        "data_source_app_id": data_source_app_id,
        "data_source_device_id": None,
        "fields": fields,
    }


def _envelope(
    records: list[dict[str, Any]],
    *,
    schema: str = "muscle50.samsung_health.inbody_diagnostic_export.v1",
    schema_version: str = "1",
    source_type: str = "inbody_samsung_health",
    exported_at: str = "2026-09-17T09:00:00Z",
    profile_key: str = PROFILE_KEY,
    companion_app_id: str = "com.example.muscle50.inbodydiagnostic",
) -> dict[str, Any]:
    return {
        "schema": schema,
        "schema_version": schema_version,
        "source_type": source_type,
        "exported_at": exported_at,
        "source_sdk_name": "Samsung Health Data SDK",
        "source_sdk_version": "1.0.0-test",
        "profile_key": profile_key,
        "companion_app_id": companion_app_id,
        "records": records,
    }


def _write(tmp_path: Path, envelope: dict[str, Any], name: str = "export.json") -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(envelope, ensure_ascii=True, sort_keys=True), encoding="utf-8")
    return path


def _sync(tmp_path: Path, payload_path: Path, repository: InMemoryBodyCompositionRepository) -> SyncInBody:
    root = tmp_path / "raw-root"
    source = SamsungHealthInBodySource(payload_path)
    return SyncInBody(source, repository, InBodyRawStore(root, tmp_path, tmp_path / "tmp"))


def test_full_body_composition_record_syncs_as_a_full_measurement(tmp_path: Path) -> None:
    payload = _write(tmp_path, _envelope([_record()]))
    result = _sync(tmp_path, payload, InMemoryBodyCompositionRepository()).execute()

    assert result.created_count == 1
    item = result.items[0]
    assert item.is_full_measurement
    assert item.measurement.weight_kg == 70.0
    assert item.measurement.skeletal_muscle_mass_kg == 31.2
    assert item.measurement.body_fat_percent == 20.1
    assert item.measurement.source_identity.source_record_id == "samsung-uid-1"
    assert item.measurement.source_identity.source_type == "inbody_samsung_health"
    # SMM identity comes from Samsung's uid directly; there is no fingerprint fallback here.
    assert item.measurement.source_identity.source_fingerprint is None
    assert item.raw_artifact.source_record_id == "samsung-uid-1"
    assert item.raw_artifact.source_application == INBODY_APP_ID
    assert item.raw_artifact.source_schema_version == "1"


def test_smm_missing_is_reported_as_partial_and_never_backfilled_from_fat_free_mass(tmp_path: Path) -> None:
    payload = _write(
        tmp_path,
        _envelope(
            [_record(skeletal_muscle_mass=None, extra_fields={"fat_free_mass": {
                "value": 55.9, "unit": "kg", "path": "BodyCompositionType.FAT_FREE_MASS",
            }})]
        ),
    )
    result = _sync(tmp_path, payload, InMemoryBodyCompositionRepository()).execute()

    item = result.items[0]
    assert item.measurement.skeletal_muscle_mass_kg is None
    assert not item.is_full_measurement
    assert "skeletal_muscle_mass_kg" in item.missing_minimum_fields


def test_weight_and_pbf_only_record_is_partial(tmp_path: Path) -> None:
    payload = _write(
        tmp_path,
        _envelope([_record(skeletal_muscle_mass=None, body_fat_mass=None, bmi=None,
                            basal_metabolic_rate=None, total_body_water=None)]),
    )
    result = _sync(tmp_path, payload, InMemoryBodyCompositionRepository()).execute()

    item = result.items[0]
    assert item.measurement.weight_kg == 70.0
    assert item.measurement.body_fat_percent == 20.1
    assert not item.is_full_measurement


def test_zero_body_fat_mass_is_preserved_and_distinct_from_missing(tmp_path: Path) -> None:
    payload = _write(tmp_path, _envelope([_record(body_fat_mass=0.0)]))
    result = _sync(tmp_path, payload, InMemoryBodyCompositionRepository()).execute()

    assert result.items[0].measurement.body_fat_mass_kg == 0.0


def test_absent_body_fat_mass_field_normalizes_to_none_not_zero(tmp_path: Path) -> None:
    payload = _write(tmp_path, _envelope([_record(body_fat_mass=None)]))
    result = _sync(tmp_path, payload, InMemoryBodyCompositionRepository()).execute()

    assert result.items[0].measurement.body_fat_mass_kg is None


def test_duplicate_uid_in_one_export_is_not_double_counted(tmp_path: Path) -> None:
    payload = _write(tmp_path, _envelope([_record(), _record()]))
    result = _sync(tmp_path, payload, InMemoryBodyCompositionRepository()).execute()

    assert result.listed_count == 1
    assert result.created_count == 1


def test_same_uid_and_same_measured_at_with_different_values_is_rejected(tmp_path: Path) -> None:
    # A reference-only equality check (source_type/profile/id/measured_at/detail_key) would treat
    # these two records as an identical duplicate and silently keep whichever came first, even
    # though their weight/SMM differ. The adapter must reject this as a malformed export instead.
    payload = _write(
        tmp_path,
        _envelope([_record(weight=70.0, skeletal_muscle_mass=31.2), _record(weight=71.0, skeletal_muscle_mass=30.0)]),
    )
    with pytest.raises(InBodySourceResponseChangedError):
        _sync(tmp_path, payload, InMemoryBodyCompositionRepository()).execute()


def test_same_uid_with_conflicting_measured_at_is_rejected(tmp_path: Path) -> None:
    payload = _write(
        tmp_path,
        _envelope([_record(measured_at="2026-09-17T08:55:00"), _record(measured_at="2026-09-18T08:55:00")]),
    )
    with pytest.raises(InBodySourceResponseChangedError):
        _sync(tmp_path, payload, InMemoryBodyCompositionRepository()).execute()


def test_same_uid_changed_payload_preserves_new_raw_but_keeps_normalized_row_immutable(
    tmp_path: Path,
) -> None:
    repository = InMemoryBodyCompositionRepository()
    first_payload = _write(tmp_path, _envelope([_record(weight=70.0)]), name="first.json")
    first = _sync(tmp_path, first_payload, repository).execute()
    assert first.created_count == 1
    original_weight = first.items[0].measurement.weight_kg

    second_payload = _write(tmp_path, _envelope([_record(weight=71.5)]), name="second.json")
    second = _sync(tmp_path, second_payload, repository).execute(refresh_existing=True)

    assert second.created_count == 0
    assert second.items[0].created is False
    assert second.items[0].raw_changed is True
    assert second.changed_count == 1
    # Normalized data is immutable; the changed weight in the new export is not applied.
    assert second.items[0].measurement.weight_kg == original_weight


def test_timestamp_with_zone_offset_is_preserved(tmp_path: Path) -> None:
    payload = _write(tmp_path, _envelope([_record(measured_at="2026-09-17T08:55:00", zone_offset="+09:00")]))
    result = _sync(tmp_path, payload, InMemoryBodyCompositionRepository()).execute()

    assert result.items[0].measurement.measured_at.endswith("+09:00")


def test_timestamp_without_zone_offset_still_normalizes(tmp_path: Path) -> None:
    payload = _write(tmp_path, _envelope([_record(zone_offset=None)]))
    result = _sync(tmp_path, payload, InMemoryBodyCompositionRepository()).execute()

    assert result.items[0].measurement.measured_at == "2026-09-17T08:55:00"


def test_malformed_envelope_schema_is_rejected(tmp_path: Path) -> None:
    envelope = _envelope([_record()])
    envelope["schema"] = "not-the-right-schema"
    payload = _write(tmp_path, envelope)

    with pytest.raises(InBodySourceResponseChangedError):
        _sync(tmp_path, payload, InMemoryBodyCompositionRepository()).execute()

    raw_documents = list((tmp_path / "raw-root").rglob("*.json"))
    assert len(raw_documents) == 1
    assert raw_documents[0].read_bytes() == payload.read_bytes()


def test_unsupported_schema_version_is_rejected(tmp_path: Path) -> None:
    payload = _write(tmp_path, _envelope([_record()], schema_version="2"))

    with pytest.raises(InBodySourceResponseChangedError):
        _sync(tmp_path, payload, InMemoryBodyCompositionRepository()).execute()


def test_wrong_source_type_is_rejected(tmp_path: Path) -> None:
    payload = _write(tmp_path, _envelope([_record()], source_type="inbody_health_connect"))

    with pytest.raises(InBodySourceResponseChangedError):
        _sync(tmp_path, payload, InMemoryBodyCompositionRepository()).execute()


def test_missing_source_application_is_not_classified_as_inbody(tmp_path: Path) -> None:
    payload = _write(
        tmp_path,
        _envelope([_record(data_source_app_id=None)]),
    )
    result = _sync(tmp_path, payload, InMemoryBodyCompositionRepository()).execute()

    assert result.listed_count == 0
    assert result.created_count == 0
    assert result.items == ()


def test_other_samsung_source_application_is_not_classified_as_inbody(tmp_path: Path) -> None:
    payload = _write(
        tmp_path,
        _envelope(
            [
                _record(source_record_id="inbody-uid"),
                _record(
                    source_record_id="other-uid",
                    data_source_app_id="com.example.other.health.source",
                ),
            ]
        ),
    )

    result = _sync(tmp_path, payload, InMemoryBodyCompositionRepository()).execute()

    assert result.listed_count == 1
    assert result.created_count == 1
    assert result.items[0].measurement.source_identity.source_record_id == "inbody-uid"
    assert result.items[0].raw_artifact.source_application == INBODY_APP_ID


def test_unrecognized_unit_is_rejected_as_payload_schema_drift(tmp_path: Path) -> None:
    payload = _write(tmp_path, _envelope([_record(weight_unit="stone")]))

    with pytest.raises(InBodySourceResponseChangedError):
        _sync(tmp_path, payload, InMemoryBodyCompositionRepository()).execute()


def test_missing_uid_is_rejected_not_treated_as_idless(tmp_path: Path) -> None:
    record = _record()
    del record["source_record_id"]
    payload = _write(tmp_path, _envelope([record]))

    with pytest.raises(InBodySourceResponseChangedError):
        _sync(tmp_path, payload, InMemoryBodyCompositionRepository()).execute()


def test_list_snapshot_and_detail_artifacts_are_both_preserved(tmp_path: Path) -> None:
    payload = _write(tmp_path, _envelope([_record()]))
    result = _sync(tmp_path, payload, InMemoryBodyCompositionRepository()).execute()

    assert result.list_snapshot.source_type == "inbody_samsung_health"
    assert result.list_snapshot.kind == "measurement_list"
    assert result.items[0].measurement.weight_kg == 70.0
    assert result.items[0].raw_artifact.kind == "measurement_detail"


def test_unknown_metric_is_rejected_as_schema_drift(tmp_path: Path) -> None:
    payload = _write(tmp_path, _envelope([_record(extra_fields={"generic_muscle_mass": None})]))

    with pytest.raises(InBodySourceResponseChangedError):
        _sync(tmp_path, payload, InMemoryBodyCompositionRepository()).execute()


def test_unitless_bmi_requires_explicit_json_null_unit_key(tmp_path: Path) -> None:
    record = _record()
    del record["fields"]["bmi"]["unit"]
    payload = _write(tmp_path, _envelope([record]))

    with pytest.raises(InBodySourceResponseChangedError):
        _sync(tmp_path, payload, InMemoryBodyCompositionRepository()).execute()


def test_missing_payload_is_source_unavailable(tmp_path: Path) -> None:
    source = SamsungHealthInBodySource(tmp_path / "missing.json")

    with pytest.raises(InBodySourceUnavailableError):
        source.list_measurements()


def test_payload_permission_error_is_distinct(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    payload = tmp_path / "export.json"

    def denied(_: Path) -> bytes:
        raise PermissionError

    monkeypatch.setattr(Path, "read_bytes", denied)
    with pytest.raises(InBodySourcePermissionDeniedError):
        SamsungHealthInBodySource(payload).list_measurements()


def test_same_payload_refresh_is_idempotent_and_not_reported_as_changed(tmp_path: Path) -> None:
    repository = InMemoryBodyCompositionRepository()
    payload = _write(tmp_path, _envelope([_record()]))

    first = _sync(tmp_path, payload, repository).execute(refresh_existing=True)
    second = _sync(tmp_path, payload, repository).execute(refresh_existing=True)

    assert first.created_count == 1
    assert second.created_count == 0
    assert second.existing_count == 1
    assert second.changed_count == 0
    assert second.items[0].raw_changed is False


def test_developer_smoke_import_is_presence_only_and_duplicate_safe(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    payload = _write(tmp_path, _envelope([_record()]))
    local_data = tmp_path / "local-data"
    monkeypatch.setenv("MUSCLE50_HOME", str(local_data))

    assert smoke_main([str(payload)]) == 0
    first_output = capsys.readouterr().out
    assert "Inserted: 1" in first_output
    assert "SMM present: 1/1" in first_output
    assert "31.2" not in first_output
    assert smoke_main([str(payload)]) == 0
    second_output = capsys.readouterr().out
    assert "Inserted: 0" in second_output
    assert "Already existing: 1" in second_output
    assert "Changed RAW conflicts: 0" in second_output


def test_developer_smoke_reports_same_uid_changed_raw_without_overwrite(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    payload = _write(tmp_path, _envelope([_record(weight=70.0)]))
    monkeypatch.setenv("MUSCLE50_HOME", str(tmp_path / "local-data"))
    assert smoke_main([str(payload)]) == 0
    capsys.readouterr()

    _write(tmp_path, _envelope([_record(weight=71.5)]))
    assert smoke_main([str(payload)]) == 2
    captured = capsys.readouterr()
    assert "Changed RAW conflicts: 1" in captured.out
    assert "normalized row was not overwritten" in captured.err
    assert "71.5" not in captured.out + captured.err
