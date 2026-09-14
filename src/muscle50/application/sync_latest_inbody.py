"""Access-independent use case for syncing the latest InBody measurement."""

from __future__ import annotations

from dataclasses import dataclass

from muscle50.application.inbody_repository import BodyCompositionRepository
from muscle50.domain.body_composition import NormalizedBodyComposition
from muscle50.domain.inbody_normalization import normalize_inbody_measurement
from muscle50.infrastructure.inbody.connector import LatestInBodyConnector
from muscle50.infrastructure.inbody.raw_store import InBodyRawStore


class NoInBodyMeasurementsError(RuntimeError):
    """Raised when a connector has no measurement for the current user."""


@dataclass(frozen=True)
class InBodySyncResult:
    measurement: NormalizedBodyComposition
    created: bool


class SyncLatestInBodyMeasurement:
    def __init__(
        self,
        connector: LatestInBodyConnector,
        repository: BodyCompositionRepository,
        raw_store: InBodyRawStore,
    ):
        self._connector = connector
        self._repository = repository
        self._raw_store = raw_store

    def execute(self) -> InBodySyncResult:
        document = self._connector.latest_document()
        if document is None:
            raise NoInBodyMeasurementsError("InBody account contains no measurements")
        artifact = self._raw_store.preserve(document)
        raw = self._connector.extract_measurement(document)
        normalized = normalize_inbody_measurement(raw)
        saved = self._repository.save(normalized, artifact)
        return InBodySyncResult(saved.measurement, saved.created)
