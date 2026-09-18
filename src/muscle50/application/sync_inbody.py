"""Incremental synchronization from any InBody-derived measurement source."""

from __future__ import annotations

from dataclasses import dataclass

from muscle50.application.inbody_repository import BodyCompositionRepository
from muscle50.application.inbody_source import (
    InBodyMeasurementReference,
    InBodyMeasurementSource,
    InBodySourceResponseChangedError,
)
from muscle50.domain.body_composition import (
    NormalizedBodyComposition,
    SourceMeasurementIdentity,
)
from muscle50.domain.inbody_normalization import normalize_inbody_measurement
from muscle50.infrastructure.inbody.raw_store import InBodyRawArtifact, InBodyRawStore


@dataclass(frozen=True)
class InBodySyncItem:
    measurement: NormalizedBodyComposition
    created: bool
    raw_changed: bool
    raw_artifact: InBodyRawArtifact
    missing_minimum_fields: tuple[str, ...]

    @property
    def is_full_measurement(self) -> bool:
        return not self.missing_minimum_fields


@dataclass(frozen=True)
class SyncInBodyResult:
    listed_count: int
    fetched_count: int
    created_count: int
    existing_count: int
    list_snapshot: InBodyRawArtifact
    items: tuple[InBodySyncItem, ...]

    @property
    def changed_count(self) -> int:
        return sum(item.raw_changed for item in self.items)


class SyncInBody:
    """List source records and persist only required details.

    By default, a reference with an already-stored official source ID is not
    fetched again. With ``refresh_existing=True``, its newest RAW detail is
    preserved and linked, but the existing normalized row remains immutable.

    Authentication, Android permission, and file access belong to the source
    adapter. This use case intentionally has no OAuth/session dependency.
    """

    def __init__(
        self,
        source: InBodyMeasurementSource,
        repository: BodyCompositionRepository,
        raw_store: InBodyRawStore,
    ) -> None:
        self._source = source
        self._repository = repository
        self._raw_store = raw_store

    def execute(self, *, refresh_existing: bool = False) -> SyncInBodyResult:
        list_document = self._source.list_measurements()
        list_snapshot = self._raw_store.preserve(list_document, kind="measurement_list")
        references = _unique_references(self._source.extract_measurement_references(list_document))
        if any(reference.source_type != list_document.source_type for reference in references):
            raise InBodySourceResponseChangedError("measurement_list")

        items: list[InBodySyncItem] = []
        skipped_count = 0
        for reference in references:
            source_identity = _source_identity(reference)
            if (
                not refresh_existing
                and source_identity is not None
                and self._repository.find(source_identity) is not None
            ):
                skipped_count += 1
                continue

            document = self._source.get_measurement(reference)
            artifact = self._raw_store.preserve(document, kind="measurement_detail")
            raw = self._source.extract_measurement(document)
            _validate_detail_identity(
                reference,
                document.source_type,
                document.source_record_id,
                raw.source_type,
                raw.source_profile_key,
                raw.source_record_id,
            )
            normalized = normalize_inbody_measurement(raw)
            saved = self._repository.save(normalized, artifact)
            items.append(
                InBodySyncItem(
                    saved.measurement,
                    saved.created,
                    not saved.created and saved.raw_artifact_added,
                    artifact,
                    _missing_minimum_fields(saved.measurement),
                )
            )

        created_count = sum(item.created for item in items)
        fetched_existing_count = len(items) - created_count
        return SyncInBodyResult(
            listed_count=len(references),
            fetched_count=len(items),
            created_count=created_count,
            existing_count=skipped_count + fetched_existing_count,
            list_snapshot=list_snapshot,
            items=tuple(items),
        )


def _source_identity(reference: InBodyMeasurementReference) -> SourceMeasurementIdentity | None:
    if reference.source_record_id is None:
        return None
    return SourceMeasurementIdentity(
        source_type=reference.source_type,
        source_profile_key=reference.source_profile_key,
        source_record_id=reference.source_record_id,
        source_fingerprint_version=None,
        source_fingerprint=None,
    )


def _unique_references(
    references: tuple[InBodyMeasurementReference, ...],
) -> tuple[InBodyMeasurementReference, ...]:
    seen: dict[tuple[str, str, str, str], InBodyMeasurementReference] = {}
    result: list[InBodyMeasurementReference] = []
    for reference in references:
        if reference.source_record_id is not None:
            key = (
                reference.source_type,
                reference.source_profile_key,
                "source_id",
                reference.source_record_id,
            )
        else:
            key = (
                reference.source_type,
                reference.source_profile_key,
                "detail_key",
                reference.detail_key,
            )
        previous = seen.get(key)
        if previous is None:
            seen[key] = reference
            result.append(reference)
        elif previous != reference:
            raise InBodySourceResponseChangedError("measurement_list")
    return tuple(result)


def _validate_detail_identity(
    reference: InBodyMeasurementReference,
    document_source_type: str,
    document_record_id: str | None,
    detail_source_type: str,
    detail_profile_key: str,
    detail_measurement_id: str | None,
) -> None:
    if document_source_type.strip() != reference.source_type:
        raise InBodySourceResponseChangedError("measurement_detail")
    if document_record_id is not None and document_record_id.strip() != (reference.source_record_id or ""):
        raise InBodySourceResponseChangedError("measurement_detail")
    if detail_source_type.strip() != reference.source_type:
        raise InBodySourceResponseChangedError("measurement_detail")
    if detail_profile_key.strip() != reference.source_profile_key:
        raise InBodySourceResponseChangedError("measurement_detail")
    if reference.source_record_id is not None and (detail_measurement_id or "").strip() != reference.source_record_id:
        raise InBodySourceResponseChangedError("measurement_detail")


def _missing_minimum_fields(
    measurement: NormalizedBodyComposition,
) -> tuple[str, ...]:
    missing: list[str] = []
    if measurement.weight_kg is None:
        missing.append("weight_kg")
    if measurement.skeletal_muscle_mass_kg is None:
        missing.append("skeletal_muscle_mass_kg")
    if measurement.body_fat_mass_kg is None and measurement.body_fat_percent is None:
        missing.append("body_fat_mass_kg_or_body_fat_percent")
    return tuple(missing)
