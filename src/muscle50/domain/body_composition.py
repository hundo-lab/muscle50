"""Provider-neutral body-composition domain types."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

type JsonScalar = str | int | float | bool | None
type MeasurementKey = tuple[str, str, str, int | None, str]


@dataclass(frozen=True)
class SourceField:
    """A value extracted from RAW data without changing its representation."""

    value: JsonScalar
    unit: str | None
    path: str


@dataclass(frozen=True)
class RawInBodyDocument:
    """Exact bytes returned by a source, before field extraction.

    A Samsung Health or Health Connect document is an OS-health snapshot
    derived from InBody data, not an original InBody server/device response.
    The source fields make that distinction explicit.
    """

    document: bytes
    content_type: str
    source_format: str
    source_type: str
    source_fetched_at: str | None = None
    source_record_id: str | None = None
    source_application: str | None = None
    source_schema_version: str | None = None


@dataclass(frozen=True)
class RawSegmentalMeasurement:
    region: str
    metric: str
    field: SourceField


@dataclass(frozen=True)
class RawInBodyMeasurement:
    """Fields extracted from preserved RAW without unit conversion.

    Connectors must supply an opaque stable ``source_profile_key``. Account
    emails and phone numbers are not valid profile keys.
    """

    source_type: str
    source_profile_key: str
    source_record_id: str | None
    measured_at: SourceField
    weight: SourceField | None = None
    skeletal_muscle_mass: SourceField | None = None
    body_fat_mass: SourceField | None = None
    body_fat_percent: SourceField | None = None
    bmi: SourceField | None = None
    waist_hip_ratio: SourceField | None = None
    visceral_fat_level: SourceField | None = None
    basal_metabolic_rate: SourceField | None = None
    total_body_water: SourceField | None = None
    protein: SourceField | None = None
    minerals: SourceField | None = None
    ecw_ratio: SourceField | None = None
    inbody_score: SourceField | None = None
    device_model: SourceField | None = None
    segmental_measurements: tuple[RawSegmentalMeasurement, ...] = ()
    metadata: Mapping[str, Any] | None = None


@dataclass(frozen=True)
class FieldProvenance:
    normalized_field: str
    source_path: str
    source_value: JsonScalar
    source_unit: str | None
    transformation: str


@dataclass(frozen=True)
class SegmentalMeasurement:
    region: str
    metric: str
    value: float
    unit: str
    provenance: FieldProvenance


@dataclass(frozen=True)
class BodyCompositionMetric:
    """Extension point for normalized device/model-specific outputs."""

    key: str
    value: float | str
    unit: str | None
    provenance: FieldProvenance


@dataclass(frozen=True)
class SourceMeasurementIdentity:
    """Identity in one source namespace; never compared across source types."""

    source_type: str
    source_profile_key: str
    source_record_id: str | None
    source_fingerprint_version: int | None
    source_fingerprint: str | None

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[a-z][a-z0-9_]*", self.source_type):
            raise ValueError("source type must be a lowercase identifier")
        if not self.source_profile_key.strip():
            raise ValueError("source profile key cannot be blank")
        if self.source_record_id is not None:
            if not self.source_record_id.strip():
                raise ValueError("source record ID cannot be blank")
            if self.source_fingerprint_version is not None or self.source_fingerprint is not None:
                raise ValueError("source ID identity cannot also be a fallback fingerprint")
        elif (
            self.source_fingerprint_version is None
            or self.source_fingerprint_version < 1
            or not self.source_fingerprint
        ):
            raise ValueError("ID-less source identity requires a versioned fingerprint")

    @property
    def key(self) -> MeasurementKey:
        """Return a structured, collision-free in-process storage key."""
        if self.source_record_id is not None:
            return (
                self.source_type,
                self.source_profile_key,
                "source_id",
                None,
                self.source_record_id,
            )
        if self.source_fingerprint_version is None or self.source_fingerprint is None:
            raise ValueError("measurement identity has neither source ID nor fingerprint")
        return (
            self.source_type,
            self.source_profile_key,
            "fingerprint",
            self.source_fingerprint_version,
            self.source_fingerprint,
        )


@dataclass(frozen=True)
class CanonicalMeasurementIdentity:
    """Cross-source comparison hint; never authorizes automatic merging."""

    fingerprint_version: int
    fingerprint: str

    def __post_init__(self) -> None:
        if self.fingerprint_version < 1 or not self.fingerprint:
            raise ValueError("canonical identity requires a versioned fingerprint")


@dataclass(frozen=True)
class NormalizedBodyComposition:
    source_identity: SourceMeasurementIdentity
    canonical_identity: CanonicalMeasurementIdentity | None
    measured_at: str
    weight_kg: float | None
    skeletal_muscle_mass_kg: float | None
    body_fat_mass_kg: float | None
    body_fat_percent: float | None
    bmi: float | None
    waist_hip_ratio: float | None
    visceral_fat_level: float | None
    basal_metabolic_rate_kcal_per_day: float | None
    total_body_water_l: float | None
    protein_kg: float | None
    minerals_kg: float | None
    ecw_ratio: float | None
    inbody_score: float | None
    device_model: str | None
    segmental_measurements: tuple[SegmentalMeasurement, ...]
    metrics: tuple[BodyCompositionMetric, ...]
    provenance: tuple[FieldProvenance, ...]
    normalizer_version: int = 1
