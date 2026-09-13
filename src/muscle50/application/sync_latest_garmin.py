"""Sync the newest Garmin activity exactly once."""

from __future__ import annotations

from dataclasses import dataclass, replace

from muscle50.domain.activity import ActivityType, NormalizedActivity
from muscle50.domain.normalization import (
    activity_id_from,
    has_exercise_set_list,
    normalize_activity,
    normalize_strength_sets,
    source_type_from,
)
from muscle50.infrastructure.garmin.client import GarminConnector
from muscle50.infrastructure.raw_store import RawStore
from muscle50.infrastructure.sqlite.database import ActivityRepository


class NoActivitiesError(RuntimeError):
    """Raised when Garmin has no activities."""


class ActivitySyncError(RuntimeError):
    """Raised when Garmin summary and detail data are inconsistent."""


@dataclass(frozen=True)
class SyncResult:
    activity: NormalizedActivity
    created: bool
    warnings: tuple[str, ...] = ()


class SyncLatestGarminActivity:
    def __init__(
        self,
        connector: GarminConnector,
        repository: ActivityRepository,
        raw_store: RawStore,
    ):
        self._connector = connector
        self._repository = repository
        self._raw_store = raw_store

    def execute(self) -> SyncResult:
        summary = self._connector.latest_summary()
        if summary is None:
            raise NoActivitiesError("Garmin Connect에 activity가 없습니다.")
        activity_id = activity_id_from(summary)
        existing = self._repository.find(activity_id)
        if existing is not None:
            return SyncResult(activity=self._backfill_local_strength_sets(existing), created=False)

        source_type_key = source_type_from(summary)
        raw = self._connector.fetch_raw_activity(activity_id, source_type_key)
        raw = replace(raw, summary=summary)
        normalized = normalize_activity(summary, raw.activity, raw.exercise_sets)
        if normalized.source_activity_id != activity_id:
            raise ActivitySyncError("Garmin summary와 activity 상세의 ID가 일치하지 않습니다.")
        artifacts = self._raw_store.preserve(activity_id, raw)
        saved, created = self._repository.save(normalized, artifacts)
        return SyncResult(activity=saved, created=created, warnings=raw.warnings)

    def _backfill_local_strength_sets(self, activity: NormalizedActivity) -> NormalizedActivity:
        if activity.canonical_type is not ActivityType.STRENGTH or activity.strength_sets:
            return activity
        exercise_sets = self._raw_store.load_exercise_sets(activity.source_activity_id)
        if exercise_sets is None or not has_exercise_set_list(exercise_sets):
            return activity
        normalized_sets = normalize_strength_sets(activity.source_activity_id, exercise_sets)
        self._repository.save_strength_sets(activity.source_activity_id, normalized_sets)
        return self._repository.find(activity.source_activity_id) or activity
