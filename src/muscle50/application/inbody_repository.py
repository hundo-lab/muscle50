"""Persistence port and an in-memory implementation for InBody measurements."""

from __future__ import annotations

from dataclasses import dataclass
from threading import Lock
from typing import Protocol

from muscle50.domain.body_composition import (
    MeasurementKey,
    NormalizedBodyComposition,
    SourceMeasurementIdentity,
)
from muscle50.infrastructure.inbody.raw_store import InBodyRawArtifact


@dataclass(frozen=True)
class BodyCompositionSaveResult:
    measurement: NormalizedBodyComposition
    created: bool
    raw_artifact_added: bool


class BodyCompositionRepository(Protocol):
    def find(self, identity: SourceMeasurementIdentity) -> NormalizedBodyComposition | None: ...

    def save(
        self,
        measurement: NormalizedBodyComposition,
        artifact: InBodyRawArtifact,
    ) -> BodyCompositionSaveResult: ...


class InMemoryBodyCompositionRepository:
    """Thread-safe source-local identity adapter.

    Canonical fingerprints are comparison hints only. They never merge records
    from different sources, or an ID-less import with a later official ID.
    """

    def __init__(self) -> None:
        self._measurements: dict[MeasurementKey, NormalizedBodyComposition] = {}
        self._artifacts: dict[MeasurementKey, set[str]] = {}
        self._lock = Lock()

    def find(self, identity: SourceMeasurementIdentity) -> NormalizedBodyComposition | None:
        with self._lock:
            return self._measurements.get(identity.key)

    def save(
        self,
        measurement: NormalizedBodyComposition,
        artifact: InBodyRawArtifact,
    ) -> BodyCompositionSaveResult:
        with self._lock:
            identity = measurement.source_identity
            existing = self._measurements.get(identity.key)
            storage_key = identity.key
            artifacts = self._artifacts.setdefault(storage_key, set())
            raw_artifact_added = artifact.sha256 not in artifacts
            artifacts.add(artifact.sha256)
            if existing is not None:
                return BodyCompositionSaveResult(existing, False, raw_artifact_added)
            self._measurements[identity.key] = measurement
            return BodyCompositionSaveResult(measurement, True, True)
