"""Synthetic connector used by tests and integration development."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from muscle50.application.inbody_source import (
    InBodyMeasurementReference,
    InBodySourceError,
)
from muscle50.domain.body_composition import (
    RawInBodyDocument,
    RawInBodyMeasurement,
    RawSegmentalMeasurement,
    SourceField,
)
from muscle50.infrastructure.inbody.auth import (
    AuthenticatedInBodySession,
    InBodyAuthenticationError,
)
from muscle50.infrastructure.inbody.connector import (
    InBodyMeasurementDetailError,
    InBodyMeasurementListError,
    InBodyResponseChangedError,
)

_DETAIL_FORMAT = "muscle50.synthetic.inbody.v1"
_LIST_FORMAT = "muscle50.synthetic.inbody.list.v1"


@dataclass(frozen=True, repr=False)
class FakeAuthenticatedInBodySession:
    sequence: int
    expired: bool = False

    def __repr__(self) -> str:
        return "FakeAuthenticatedInBodySession(<redacted>)"


class FakeInBodyAuthProvider:
    """Deterministic auth provider with no credential or token material."""

    def __init__(
        self,
        *,
        cached_session: FakeAuthenticatedInBodySession | None = None,
        authenticated_session: FakeAuthenticatedInBodySession | None = None,
        refreshed_session: FakeAuthenticatedInBodySession | None = None,
        authenticate_error: InBodyAuthenticationError | None = None,
        refresh_error: InBodyAuthenticationError | None = None,
    ) -> None:
        self._cached_session = cached_session
        self._authenticated_session = authenticated_session or FakeAuthenticatedInBodySession(1)
        self._refreshed_session = refreshed_session or FakeAuthenticatedInBodySession(2)
        self._authenticate_error = authenticate_error
        self._refresh_error = refresh_error
        self.load_calls = 0
        self.authenticate_calls = 0
        self.refresh_calls = 0

    def load_cached_session(self) -> AuthenticatedInBodySession | None:
        self.load_calls += 1
        return self._cached_session

    def authenticate(self) -> AuthenticatedInBodySession:
        self.authenticate_calls += 1
        if self._authenticate_error is not None:
            raise self._authenticate_error
        self._cached_session = self._authenticated_session
        return self._authenticated_session

    def refresh_session(self, session: AuthenticatedInBodySession) -> AuthenticatedInBodySession:
        del session
        self.refresh_calls += 1
        if self._refresh_error is not None:
            raise self._refresh_error
        self._cached_session = self._refreshed_session
        return self._refreshed_session


class SyntheticInBodyConnector:
    """Deterministic connector; it never performs network or authentication I/O."""

    def __init__(
        self,
        document: RawInBodyDocument | None,
        *,
        list_document: RawInBodyDocument | None = None,
        detail_documents: Mapping[str, RawInBodyDocument] | None = None,
    ):
        self._document = document
        self._list_document = list_document
        self._detail_documents = dict(detail_documents or {})
        self.calls = 0
        self.list_calls = 0
        self.detail_calls = 0

    @classmethod
    def from_fixture(cls, path: Path) -> SyntheticInBodyConnector:
        return cls(
            RawInBodyDocument(
                document=path.read_bytes(),
                content_type="application/json",
                source_format=_DETAIL_FORMAT,
                source_type="inbody_synthetic",
                source_application="muscle50-test-fixture",
                source_schema_version="1",
            )
        )

    @classmethod
    def from_account_fixtures(
        cls,
        list_path: Path,
        detail_paths: Mapping[str, Path],
    ) -> SyntheticInBodyConnector:
        details: dict[str, RawInBodyDocument] = {}
        for key, path in detail_paths.items():
            document = path.read_bytes()
            payload = json.loads(document)
            source_record_id = payload.get("source_measurement_id")
            details[key] = RawInBodyDocument(
                document,
                "application/json",
                _DETAIL_FORMAT,
                source_type="inbody_synthetic",
                source_record_id=(source_record_id if isinstance(source_record_id, str) else None),
                source_application="muscle50-test-fixture",
                source_schema_version="1",
            )
        return cls(
            None,
            list_document=RawInBodyDocument(
                list_path.read_bytes(),
                "application/json",
                _LIST_FORMAT,
                source_type="inbody_synthetic",
                source_application="muscle50-test-fixture",
                source_schema_version="1",
            ),
            detail_documents=details,
        )

    def list_measurements(self, session: AuthenticatedInBodySession) -> RawInBodyDocument:
        del session
        self.list_calls += 1
        if self._list_document is None:
            raise InBodyMeasurementListError
        return self._list_document

    def extract_measurement_references(self, document: RawInBodyDocument) -> tuple[InBodyMeasurementReference, ...]:
        payload = _json_object(document, _LIST_FORMAT, "measurement_list")
        if payload.get("schema") != _LIST_FORMAT:
            raise InBodyResponseChangedError("measurement_list")
        values = payload.get("measurements")
        if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
            raise InBodyResponseChangedError("measurement_list")
        return tuple(_reference(value, document.source_type) for value in values)

    def get_measurement(
        self,
        session: AuthenticatedInBodySession,
        reference: InBodyMeasurementReference,
    ) -> RawInBodyDocument:
        del session
        self.detail_calls += 1
        document = self._detail_documents.get(reference.detail_key)
        if document is None:
            raise InBodyMeasurementDetailError
        return document

    def latest_document(self) -> RawInBodyDocument | None:
        self.calls += 1
        return self._document

    def extract_measurement(self, document: RawInBodyDocument) -> RawInBodyMeasurement:
        payload = _json_object(document, _DETAIL_FORMAT, "measurement_detail")
        return _measurement(payload, document.source_type)


class SyntheticInBodyMeasurementSource:
    """Session-free source used to test permission/file/OS-health boundaries."""

    def __init__(
        self,
        connector: SyntheticInBodyConnector,
        *,
        list_error: InBodySourceError | None = None,
        detail_error: InBodySourceError | None = None,
    ) -> None:
        self._connector = connector
        self._list_error = list_error
        self._detail_error = detail_error

    def list_measurements(self) -> RawInBodyDocument:
        if self._list_error is not None:
            raise self._list_error
        return self._connector.list_measurements(FakeAuthenticatedInBodySession(0))

    def extract_measurement_references(self, document: RawInBodyDocument) -> tuple[InBodyMeasurementReference, ...]:
        return self._connector.extract_measurement_references(document)

    def get_measurement(self, reference: InBodyMeasurementReference) -> RawInBodyDocument:
        if self._detail_error is not None:
            raise self._detail_error
        return self._connector.get_measurement(FakeAuthenticatedInBodySession(0), reference)

    def extract_measurement(self, document: RawInBodyDocument) -> RawInBodyMeasurement:
        return self._connector.extract_measurement(document)


def _json_object(
    document: RawInBodyDocument,
    expected_format: str,
    operation: Literal["measurement_list", "measurement_detail"],
) -> Mapping[str, Any]:
    if document.source_format != expected_format:
        raise InBodyResponseChangedError(operation)
    try:
        payload = json.loads(document.document)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise InBodyResponseChangedError(operation) from None
    if not isinstance(payload, Mapping):
        raise InBodyResponseChangedError(operation)
    return payload


def _reference(value: Any, source_type: str) -> InBodyMeasurementReference:
    if not isinstance(value, Mapping):
        raise InBodyResponseChangedError("measurement_list")
    profile_key = value.get("source_profile_key")
    source_id = value.get("source_measurement_id")
    measured_at = value.get("measured_at")
    detail_key = value.get("detail_key")
    if not isinstance(profile_key, str) or not profile_key.strip():
        raise InBodyResponseChangedError("measurement_list")
    if source_id is not None and (not isinstance(source_id, str) or not source_id.strip()):
        raise InBodyResponseChangedError("measurement_list")
    if measured_at is not None and not isinstance(measured_at, str):
        raise InBodyResponseChangedError("measurement_list")
    if not isinstance(detail_key, str) or not detail_key.strip():
        raise InBodyResponseChangedError("measurement_list")
    return InBodyMeasurementReference(
        source_type=source_type,
        source_profile_key=profile_key.strip(),
        source_record_id=source_id.strip() if isinstance(source_id, str) else None,
        measured_at=measured_at.strip() if isinstance(measured_at, str) else None,
        detail_key=detail_key.strip(),
    )


def _measurement(payload: Mapping[str, Any], source_type: str) -> RawInBodyMeasurement:
    if payload.get("schema") != _DETAIL_FORMAT:
        raise InBodyResponseChangedError("measurement_detail")
    fields = payload.get("fields")
    if not isinstance(fields, Mapping):
        raise InBodyResponseChangedError("measurement_detail")
    measured_at = _required_field(fields, "measured_at")
    segments_value = payload.get("segments", [])
    if not isinstance(segments_value, Sequence) or isinstance(segments_value, (str, bytes)):
        raise InBodyResponseChangedError("measurement_detail")
    segments = tuple(_segment(item, index) for index, item in enumerate(segments_value))
    source_id = payload.get("source_measurement_id")
    if source_id is not None and not isinstance(source_id, str):
        raise InBodyResponseChangedError("measurement_detail")
    profile_key = payload.get("source_profile_key")
    if not isinstance(profile_key, str) or not profile_key.strip():
        raise InBodyResponseChangedError("measurement_detail")
    return RawInBodyMeasurement(
        source_type=source_type,
        source_profile_key=profile_key.strip(),
        source_record_id=source_id,
        measured_at=measured_at,
        weight=_field(fields, "weight"),
        skeletal_muscle_mass=_field(fields, "skeletal_muscle_mass"),
        body_fat_mass=_field(fields, "body_fat_mass"),
        body_fat_percent=_field(fields, "body_fat_percent"),
        bmi=_field(fields, "bmi"),
        waist_hip_ratio=_field(fields, "waist_hip_ratio"),
        visceral_fat_level=_field(fields, "visceral_fat_level"),
        basal_metabolic_rate=_field(fields, "basal_metabolic_rate"),
        total_body_water=_field(fields, "total_body_water"),
        protein=_field(fields, "protein"),
        minerals=_field(fields, "minerals"),
        ecw_ratio=_field(fields, "ecw_ratio"),
        inbody_score=_field(fields, "inbody_score"),
        device_model=_field(fields, "device_model"),
        segmental_measurements=segments,
    )


def _required_field(fields: Mapping[str, Any], name: str) -> SourceField:
    result = _field(fields, name)
    if result is None:
        raise InBodyResponseChangedError("measurement_detail")
    return result


def _field(fields: Mapping[str, Any], name: str) -> SourceField | None:
    value = fields.get(name)
    if value is None:
        return None
    if not isinstance(value, Mapping) or "value" not in value:
        raise InBodyResponseChangedError("measurement_detail")
    unit = value.get("unit")
    path = value.get("path")
    if unit is not None and not isinstance(unit, str):
        raise InBodyResponseChangedError("measurement_detail")
    if not isinstance(path, str) or not path:
        raise InBodyResponseChangedError("measurement_detail")
    scalar = value["value"]
    if not isinstance(scalar, (str, int, float, bool)) and scalar is not None:
        raise InBodyResponseChangedError("measurement_detail")
    return SourceField(value=scalar, unit=unit, path=path)


def _segment(value: Any, index: int) -> RawSegmentalMeasurement:
    if not isinstance(value, Mapping):
        raise InBodyResponseChangedError("measurement_detail")
    region = value.get("region")
    metric = value.get("metric")
    if not isinstance(region, str) or not region or not isinstance(metric, str) or not metric:
        raise InBodyResponseChangedError("measurement_detail")
    field = _field({"segment": value.get("field")}, "segment")
    if field is None:
        raise InBodyResponseChangedError("measurement_detail")
    return RawSegmentalMeasurement(region=region, metric=metric, field=field)
