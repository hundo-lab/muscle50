"""Sync the newest Garmin activity exactly once."""

from __future__ import annotations

from dataclasses import dataclass

from muscle50.application.ingest_activity import IngestGarminActivity
from muscle50.domain.activity import NormalizedActivity
from muscle50.infrastructure.garmin.client import GarminConnector
from muscle50.infrastructure.raw_store import RawStore
from muscle50.infrastructure.sqlite.database import ActivityRepository


class NoActivitiesError(RuntimeError):
    """Raised when Garmin has no activities."""


@dataclass(frozen=True)
class SyncResult:
    activity: NormalizedActivity
    created: bool
    warnings: tuple[str, ...] = ()


class SyncLatestGarminActivity:
    """Thin wrapper around the canonical per-activity ingestion path for `garmin latest`."""

    def __init__(
        self,
        connector: GarminConnector,
        repository: ActivityRepository,
        raw_store: RawStore,
    ):
        self._connector = connector
        self._ingest = IngestGarminActivity(connector, repository, raw_store)

    def execute(self) -> SyncResult:
        summary = self._connector.latest_summary()
        if summary is None:
            raise NoActivitiesError("Garmin Connect에 activity가 없습니다.")
        result = self._ingest.execute(summary)
        return SyncResult(activity=result.activity, created=result.created, warnings=result.warnings)
