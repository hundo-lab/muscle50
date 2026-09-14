"""Source-neutral application port for InBody-derived measurements."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

from muscle50.domain.body_composition import RawInBodyDocument, RawInBodyMeasurement


class InBodySourceError(RuntimeError):
    """Safe-to-display source failure without health data or credentials."""

    _safe_message = "InBody measurement source failed"

    def __init__(self) -> None:
        super().__init__(self._safe_message)


class InBodySourcePermissionDeniedError(InBodySourceError):
    _safe_message = "InBody measurement source permission was denied"


class InBodySourcePermissionRevokedError(InBodySourceError):
    _safe_message = "InBody measurement source permission was revoked"


class InBodySourceUnavailableError(InBodySourceError):
    _safe_message = "InBody measurement source is temporarily unavailable"


class InBodySourceResponseChangedError(InBodySourceError):
    def __init__(self, operation: Literal["measurement_list", "measurement_detail"]) -> None:
        safe_operation = operation if operation in {"measurement_list", "measurement_detail"} else "unknown"
        RuntimeError.__init__(
            self,
            f"InBody {safe_operation} response format is unsupported or changed",
        )


@dataclass(frozen=True)
class InBodyMeasurementReference:
    """Source-local list item used to request one exact source record."""

    source_type: str
    source_profile_key: str
    source_record_id: str | None
    measured_at: str | None
    detail_key: str


class InBodyMeasurementSource(Protocol):
    """A source may own OAuth, Android permissions, files, or no auth at all."""

    def list_measurements(self) -> RawInBodyDocument:
        """Return the exact source list/export snapshot."""
        ...

    def extract_measurement_references(self, document: RawInBodyDocument) -> tuple[InBodyMeasurementReference, ...]:
        """Extract source-local references without normalization."""
        ...

    def get_measurement(self, reference: InBodyMeasurementReference) -> RawInBodyDocument:
        """Return the exact source record for one listed measurement."""
        ...

    def extract_measurement(self, document: RawInBodyDocument) -> RawInBodyMeasurement:
        """Extract source values and paths without conversion or inference."""
        ...
