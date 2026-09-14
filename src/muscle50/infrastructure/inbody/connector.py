"""Optional authenticated connector boundary for an approved network API."""

from __future__ import annotations

from typing import Protocol

from muscle50.application.inbody_source import (
    InBodyMeasurementReference,
    InBodySourceResponseChangedError,
)
from muscle50.application.inbody_source import InBodySourceError as InBodyConnectorError
from muscle50.domain.body_composition import RawInBodyDocument, RawInBodyMeasurement
from muscle50.infrastructure.inbody.auth import AuthenticatedInBodySession


class InBodyMeasurementListError(InBodyConnectorError):
    _safe_message = "InBody measurement list request failed"


class InBodyMeasurementDetailError(InBodyConnectorError):
    _safe_message = "InBody measurement detail request failed"


InBodyResponseChangedError = InBodySourceResponseChangedError


class InBodyConnector(Protocol):
    def list_measurements(self, session: AuthenticatedInBodySession) -> RawInBodyDocument:
        """Return the exact, uninterpreted measurement-list response."""
        ...

    def extract_measurement_references(self, document: RawInBodyDocument) -> tuple[InBodyMeasurementReference, ...]:
        """Extract list references without fetching or normalizing detail data."""
        ...

    def get_measurement(
        self,
        session: AuthenticatedInBodySession,
        reference: InBodyMeasurementReference,
    ) -> RawInBodyDocument:
        """Return the exact, uninterpreted response for one listed measurement."""
        ...

    def extract_measurement(self, document: RawInBodyDocument) -> RawInBodyMeasurement:
        """Extract source values/paths without normalizing values or units."""
        ...


class LatestInBodyConnector(Protocol):
    """Legacy single-document boundary retained for the Phase 2 use case."""

    def latest_document(self) -> RawInBodyDocument | None: ...

    def extract_measurement(self, document: RawInBodyDocument) -> RawInBodyMeasurement: ...
