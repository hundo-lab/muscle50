"""Source adapter for the Samsung Health Data SDK diagnostic export.

This adapter never calls the Samsung Health Data SDK, never assumes Python/Windows can reach a
Galaxy device's Samsung Health store, and never touches InBody or Samsung account credentials. It
consumes exactly one artifact: a versioned JSON payload produced by a separate Android diagnostic
companion (see ``docs/samsung-health-payload-contract.md``) and handed to muscle50 as a local file.

An OS-health record produced this way is provenance-labeled ``InBody-derived Samsung Health
record``, never as original InBody device/server RAW, and a record is never auto-classified as
"from InBody" purely from field presence or timestamp — see the contract's Phase 7 discussion in
``docs/HANDOFF.md``. ``skeletal_muscle_mass`` is populated only from Samsung's
``BodyCompositionType.SKELETAL_MUSCLE_MASS`` field; fat-free mass, fat-free percent, and any
Health Connect lean-mass-shaped value are never substituted for it.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from muscle50.application.inbody_source import (
    InBodyMeasurementReference,
    InBodySourcePermissionDeniedError,
    InBodySourceResponseChangedError,
    InBodySourceUnavailableError,
)
from muscle50.domain.body_composition import (
    RawInBodyDocument,
    RawInBodyMeasurement,
    SourceField,
)

SOURCE_TYPE = "inbody_samsung_health"
INBODY_SOURCE_APPLICATION_ID = "com.inbody2014.inbody"
SUPPORTED_SCHEMA_VERSION = "1"
_ENVELOPE_SCHEMA = "muscle50.samsung_health.inbody_diagnostic_export.v1"
_RECORD_SCHEMA = "muscle50.samsung_health.inbody_record.v1"

# Samsung BodyCompositionType fields this contract maps, and the normalized name each becomes.
# skeletal_muscle_mass maps ONLY from SKELETAL_MUSCLE_MASS (kg). FAT_FREE_MASS/FAT_FREE/MUSCLE_MASS
# percentages are never substituted for it; see docs/samsung-health-payload-contract.md.
_FIELD_CONTRACTS: dict[str, tuple[str | None, str]] = {
    "weight": ("kg", "BodyCompositionType.WEIGHT"),
    "skeletal_muscle_mass": ("kg", "BodyCompositionType.SKELETAL_MUSCLE_MASS"),
    "body_fat_mass": ("kg", "BodyCompositionType.BODY_FAT_MASS"),
    "body_fat_percent": ("%", "BodyCompositionType.BODY_FAT"),
    "bmi": (None, "BodyCompositionType.BODY_MASS_INDEX"),
    "basal_metabolic_rate": ("kcal/day", "BodyCompositionType.BASAL_METABOLIC_RATE"),
    "total_body_water": ("L", "BodyCompositionType.TOTAL_BODY_WATER"),
    "fat_free_mass": ("kg", "BodyCompositionType.FAT_FREE_MASS"),
}
_ENVELOPE_KEYS = {
    "schema",
    "schema_version",
    "source_type",
    "exported_at",
    "source_sdk_name",
    "source_sdk_version",
    "profile_key",
    "companion_app_id",
    "records",
}
_RECORD_KEYS = {
    "source_record_id",
    "measured_at",
    "zone_offset",
    "data_source_app_id",
    "data_source_device_id",
    "fields",
}


class SamsungHealthInBodySource:
    """Reads one companion-exported diagnostic payload; performs no network I/O."""

    def __init__(self, payload_path: Path):
        self._payload_path = payload_path
        self._document: bytes | None = None
        self._envelope: dict[str, Any] | None = None

    def list_measurements(self) -> RawInBodyDocument:
        document = self._read_payload()
        self._document = document
        self._envelope = None
        return RawInBodyDocument(
            document=document,
            content_type="application/json",
            source_format=_ENVELOPE_SCHEMA,
            source_type=SOURCE_TYPE,
            # Parsing happens only after SyncInBody has preserved this exact list snapshot.
            # Valid companion metadata remains in the immutable JSON itself; the sidecar records
            # the parser's expected contract version even if the payload later proves malformed.
            source_schema_version=SUPPORTED_SCHEMA_VERSION,
        )

    def extract_measurement_references(
        self, document: RawInBodyDocument
    ) -> tuple[InBodyMeasurementReference, ...]:
        envelope = _parse_envelope(document.document)
        if self._document == document.document:
            self._envelope = envelope
        profile_key = envelope["profile_key"]
        return tuple(
            _reference(record, profile_key)
            for record in envelope["records"]
            if _is_inbody_record(record)
        )

    def get_measurement(self, reference: InBodyMeasurementReference) -> RawInBodyDocument:
        # Use the exact snapshot returned by list_measurements. Re-reading a file that can be
        # replaced between list/detail calls would break RAW provenance and identity consistency.
        envelope = self._envelope
        if envelope is None:
            document = self._read_payload()
            envelope = _parse_envelope(document)
            self._document = document
            self._envelope = envelope
        for record in envelope["records"]:
            if not _is_inbody_record(record):
                continue
            if reference.detail_key != _detail_key(record):
                continue
            payload = {
                "schema": _RECORD_SCHEMA,
                "schema_version": envelope["schema_version"],
                "profile_key": envelope["profile_key"],
                "record": record,
            }
            encoded = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode()
            source_record_id = _required_string(record, "source_record_id", "measurement_detail")
            return RawInBodyDocument(
                document=encoded,
                content_type="application/json",
                source_format=_RECORD_SCHEMA,
                source_type=SOURCE_TYPE,
                source_fetched_at=envelope["exported_at"],
                source_record_id=source_record_id,
                source_application=record.get("data_source_app_id"),
                source_schema_version=envelope["schema_version"],
            )
        raise InBodySourceResponseChangedError("measurement_detail")

    def extract_measurement(self, document: RawInBodyDocument) -> RawInBodyMeasurement:
        if document.source_format != _RECORD_SCHEMA or document.source_type != SOURCE_TYPE:
            raise InBodySourceResponseChangedError("measurement_detail")
        payload = _json_object(document.document, "measurement_detail")
        if payload.get("schema") != _RECORD_SCHEMA:
            raise InBodySourceResponseChangedError("measurement_detail")
        if payload.get("schema_version") != SUPPORTED_SCHEMA_VERSION:
            raise InBodySourceResponseChangedError("measurement_detail")
        profile_key = _required_string(payload, "profile_key", "measurement_detail")
        record = payload.get("record")
        if not isinstance(record, Mapping):
            raise InBodySourceResponseChangedError("measurement_detail")
        return _measurement(record, profile_key)

    def _read_payload(self) -> bytes:
        try:
            return self._payload_path.read_bytes()
        except PermissionError:
            raise InBodySourcePermissionDeniedError from None
        except OSError:
            raise InBodySourceUnavailableError from None


def _parse_envelope(document: bytes) -> dict[str, Any]:
    payload = _json_object(document, "measurement_list")
    if set(payload) != _ENVELOPE_KEYS:
        raise InBodySourceResponseChangedError("measurement_list")
    if payload.get("schema") != _ENVELOPE_SCHEMA:
        raise InBodySourceResponseChangedError("measurement_list")
    if payload.get("schema_version") != SUPPORTED_SCHEMA_VERSION:
        raise InBodySourceResponseChangedError("measurement_list")
    if payload.get("source_type") != SOURCE_TYPE:
        raise InBodySourceResponseChangedError("measurement_list")
    exported_at = _required_string(payload, "exported_at", "measurement_list")
    _aware_iso_timestamp(exported_at, "measurement_list")
    profile_key = _required_string(payload, "profile_key", "measurement_list")
    source_sdk_name = _required_string(payload, "source_sdk_name", "measurement_list")
    source_sdk_version = _required_string(payload, "source_sdk_version", "measurement_list")
    companion_app_id = _required_string(payload, "companion_app_id", "measurement_list")
    records = payload.get("records")
    if not isinstance(records, Sequence) or isinstance(records, (str, bytes)):
        raise InBodySourceResponseChangedError("measurement_list")
    for record in records:
        if not isinstance(record, Mapping):
            raise InBodySourceResponseChangedError("measurement_list")
        _validate_record_shape(record, "measurement_list")
    _reject_conflicting_duplicate_records(records)
    return {
        "exported_at": exported_at,
        "profile_key": profile_key,
        "schema_version": payload["schema_version"],
        "source_sdk_name": source_sdk_name,
        "source_sdk_version": source_sdk_version,
        "companion_app_id": companion_app_id,
        "records": list(records),
    }


def _reject_conflicting_duplicate_records(records: Sequence[Any]) -> None:
    # SyncInBody's own duplicate-reference detection (_unique_references) only compares
    # InBodyMeasurementReference fields (source_type/profile/id/measured_at/detail_key), none of
    # which carry body-composition values. Two records sharing a uid AND an identical
    # measured_at would therefore build two *equal* references and silently dedupe at that layer
    # even if their weight/SMM/etc. differ. Samsung's uid is documented as globally unique per
    # point, so any repeated uid in one export is either a harmless exact-duplicate re-export (OK)
    # or export corruption (reject) — never a legitimate second measurement to merge or pick from.
    seen: dict[Any, Mapping[str, Any]] = {}
    for record in records:
        key = record.get("source_record_id")
        if key is None:
            continue
        previous = seen.get(key)
        if previous is None:
            seen[key] = record
        elif previous != record:
            raise InBodySourceResponseChangedError("measurement_list")


def _detail_key(record: Mapping[str, Any]) -> str:
    # Keyed on uid alone (never the list index): Samsung's uid is mandatory and globally
    # unique per BodyCompositionType point, so two records sharing a uid must resolve to the
    # same detail_key for SyncInBody's duplicate-reference detection to dedupe or reject them
    # correctly instead of treating list position as part of identity.
    source_record_id = record.get("source_record_id")
    if isinstance(source_record_id, str) and source_record_id.strip():
        return f"record:{source_record_id.strip()}"
    return "record:missing-uid"


def _is_inbody_record(record: Mapping[str, Any]) -> bool:
    """Classify only the source application confirmed by the live Galaxy export."""
    return record.get("data_source_app_id") == INBODY_SOURCE_APPLICATION_ID


def _reference(record: Mapping[str, Any], profile_key: str) -> InBodyMeasurementReference:
    # Samsung's BodyCompositionType.uid is a mandatory SDK field (see the payload contract), so a
    # record without one is a malformed/unsupported export, not a legitimate ID-less measurement.
    # This adapter therefore has no fingerprint-fallback identity path.
    source_record_id = _required_string(record, "source_record_id", "measurement_list")
    measured_at = record.get("measured_at")
    if measured_at is not None and not isinstance(measured_at, str):
        raise InBodySourceResponseChangedError("measurement_list")
    return InBodyMeasurementReference(
        source_type=SOURCE_TYPE,
        source_profile_key=profile_key,
        source_record_id=source_record_id,
        measured_at=measured_at,
        detail_key=_detail_key(record),
    )


def _measurement(record: Mapping[str, Any], profile_key: str) -> RawInBodyMeasurement:
    _validate_record_shape(record, "measurement_detail")
    source_record_id = _required_string(record, "source_record_id", "measurement_detail")
    measured_at = _measured_at_field(record)
    fields = record.get("fields")
    if not isinstance(fields, Mapping):
        raise InBodySourceResponseChangedError("measurement_detail")
    return RawInBodyMeasurement(
        source_type=SOURCE_TYPE,
        source_profile_key=profile_key,
        source_record_id=source_record_id,
        measured_at=measured_at,
        weight=_field(fields, "weight"),
        skeletal_muscle_mass=_field(fields, "skeletal_muscle_mass"),
        body_fat_mass=_field(fields, "body_fat_mass"),
        body_fat_percent=_field(fields, "body_fat_percent"),
        bmi=_field(fields, "bmi"),
        basal_metabolic_rate=_field(fields, "basal_metabolic_rate"),
        total_body_water=_field(fields, "total_body_water"),
        # fat_free_mass is preserved verbatim (with provenance) but is not yet wired into a
        # normalized column: NormalizedBodyComposition has no fat-free-mass field, and the
        # domain's open metrics extension point is not populated by any adapter today. See
        # docs/samsung-health-payload-contract.md ("Not covered by v1") and the session handoff.
        metadata={"fat_free_mass": fields.get("fat_free_mass")} if "fat_free_mass" in fields else None,
    )


def _measured_at_field(record: Mapping[str, Any]) -> SourceField:
    measured_at = record.get("measured_at")
    if not isinstance(measured_at, str) or not measured_at.strip():
        raise InBodySourceResponseChangedError("measurement_detail")
    zone_offset = record.get("zone_offset")
    if zone_offset is not None and (not isinstance(zone_offset, str) or not zone_offset.strip()):
        raise InBodySourceResponseChangedError("measurement_detail")
    local_time = _local_iso_timestamp(measured_at.strip(), "measurement_detail")
    if zone_offset is None:
        return SourceField(value=local_time, unit=None, path="Record.measured_at")
    normalized_offset = _zone_offset(zone_offset.strip(), "measurement_detail")
    return SourceField(
        value=f"{local_time}{normalized_offset}",
        unit=None,
        path="Record.measured_at+zone_offset",
    )


def _field(fields: Mapping[str, Any], name: str) -> SourceField | None:
    if name not in _FIELD_CONTRACTS:  # pragma: no cover - defends against a future typo above
        raise ValueError(f"{name} is not a mapped Samsung Health field")
    value = fields.get(name)
    if value is None:
        return None
    scalar, unit, path = _validated_field_value(name, value, "measurement_detail")
    return SourceField(value=scalar, unit=unit, path=path)


def _validated_field_value(
    name: str,
    value: Any,
    operation: Literal["measurement_list", "measurement_detail"],
) -> tuple[int | float, str | None, str]:
    if not isinstance(value, Mapping) or "value" not in value:
        raise InBodySourceResponseChangedError(operation)
    if set(value) != {"value", "unit", "path"}:
        raise InBodySourceResponseChangedError(operation)
    unit = value.get("unit")
    path = value.get("path")
    if unit is not None and not isinstance(unit, str):
        raise InBodySourceResponseChangedError(operation)
    if not isinstance(path, str) or not path:
        raise InBodySourceResponseChangedError(operation)
    scalar = value["value"]
    if isinstance(scalar, bool) or not isinstance(scalar, (int, float)):
        raise InBodySourceResponseChangedError(operation)
    expected_unit, expected_path = _FIELD_CONTRACTS[name]
    if unit != expected_unit or path != expected_path:
        raise InBodySourceResponseChangedError(operation)
    return scalar, unit, path


def _validate_record_shape(
    record: Mapping[str, Any],
    operation: Literal["measurement_list", "measurement_detail"],
) -> None:
    if set(record) != _RECORD_KEYS:
        raise InBodySourceResponseChangedError(operation)
    _required_string(record, "source_record_id", operation)
    measured_at = _required_string(record, "measured_at", operation)
    _local_iso_timestamp(measured_at, operation)
    for name in ("zone_offset", "data_source_app_id", "data_source_device_id"):
        value = record.get(name)
        if value is not None and (not isinstance(value, str) or not value.strip()):
            raise InBodySourceResponseChangedError(operation)
    zone_offset = record.get("zone_offset")
    if isinstance(zone_offset, str):
        _zone_offset(zone_offset, operation)
    fields = record.get("fields")
    if not isinstance(fields, Mapping) or not set(fields).issubset(_FIELD_CONTRACTS):
        raise InBodySourceResponseChangedError(operation)
    for name, value in fields.items():
        if value is not None:
            _validated_field_value(name, value, operation)


def _aware_iso_timestamp(value: str, operation: Literal["measurement_list", "measurement_detail"]) -> str:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise InBodySourceResponseChangedError(operation) from None
    if parsed.tzinfo is None:
        raise InBodySourceResponseChangedError(operation)
    return value


def _local_iso_timestamp(value: str, operation: Literal["measurement_list", "measurement_detail"]) -> str:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        raise InBodySourceResponseChangedError(operation) from None
    if parsed.tzinfo is not None or "T" not in value:
        raise InBodySourceResponseChangedError(operation)
    return parsed.isoformat()


def _zone_offset(value: str, operation: Literal["measurement_list", "measurement_detail"]) -> str:
    try:
        parsed = datetime.fromisoformat(f"2000-01-01T00:00:00{value}")
    except ValueError:
        raise InBodySourceResponseChangedError(operation) from None
    if parsed.utcoffset() is None:
        raise InBodySourceResponseChangedError(operation)
    return value


def _required_string(
    payload: Mapping[str, Any],
    name: str,
    operation: Literal["measurement_list", "measurement_detail"],
) -> str:
    value = payload.get(name)
    if not isinstance(value, str) or not value.strip():
        raise InBodySourceResponseChangedError(operation)
    return value.strip()


def _json_object(
    document: bytes,
    operation: Literal["measurement_list", "measurement_detail"],
) -> Mapping[str, Any]:
    try:
        payload = json.loads(document)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise InBodySourceResponseChangedError(operation) from None
    if not isinstance(payload, Mapping):
        raise InBodySourceResponseChangedError(operation)
    return payload
