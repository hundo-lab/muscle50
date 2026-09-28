"""Explicitly refresh one already-imported Garmin activity."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, replace

from muscle50.domain.activity import NormalizedActivity
from muscle50.domain.activity_review import ActivityReviewState, derive_activity_review
from muscle50.domain.normalization import (
    activity_id_from,
    has_exercise_set_list,
    normalize_activity,
    source_type_from,
)
from muscle50.domain.swim_normalization import normalize_garmin_swim
from muscle50.infrastructure.garmin.client import GarminConnector
from muscle50.infrastructure.raw_store import ActivityCapture, RawStore
from muscle50.infrastructure.sqlite.database import ActivityRepository


class ActivityRefreshError(RuntimeError):
    """A safe-to-display refresh failure."""


class ActivityNotFoundError(ActivityRefreshError):
    """Raised when refresh is requested for an activity not imported locally."""


class IncompleteActivityRefreshError(ActivityRefreshError):
    """Raised when a required sport-specific optional endpoint was unavailable."""


@dataclass(frozen=True)
class ActivityRefreshResult:
    activity: NormalizedActivity
    capture: ActivityCapture
    strength_set_count: int
    swim_lap_count: int
    swim_length_count: int
    review: ActivityReviewState
    warnings: tuple[str, ...]


class RefreshGarminActivity:
    def __init__(self, connector: GarminConnector, repository: ActivityRepository, raw_store: RawStore):
        self._connector = connector
        self._repository = repository
        self._raw_store = raw_store

    def execute(self, source_activity_id: str) -> ActivityRefreshResult:
        activity_id = activity_id_from({"activityId": source_activity_id})
        existing = self._repository.find(activity_id)
        if existing is None:
            raise ActivityNotFoundError(f"local Garmin activity not found: {activity_id}")

        raw = self._connector.fetch_raw_activity(activity_id, existing.source_type_key)
        raw = replace(raw, summary=raw.activity)

        # RAW registration deliberately commits before validation and normalization so
        # evidence survives every later failure while canonical data remains untouched.
        capture = self._raw_store.preserve_snapshot(activity_id, raw)
        try:
            self._repository.record_refresh_capture(capture)
        except (sqlite3.Error, RuntimeError, ValueError) as exc:
            raise ActivityRefreshError(
                "RAW snapshot was captured, but its metadata could not be registered"
            ) from exc

        if activity_id_from(raw.activity) != activity_id:
            raise ActivityRefreshError("Garmin refresh activity ID does not match the requested activity")
        source_type_key = source_type_from(raw.activity)
        if source_type_key == "unknown" and existing.source_type_key != "unknown":
            raise IncompleteActivityRefreshError(
                "Garmin activity type was unavailable; previous canonical data was preserved"
            )
        if source_type_key == "strength_training" and (
            raw.exercise_sets is None or not has_exercise_set_list(raw.exercise_sets)
        ):
            raise IncompleteActivityRefreshError(
                "Garmin exercise sets were unavailable; previous canonical data was preserved"
            )
        if source_type_key == "lap_swimming" and raw.splits is None:
            raise IncompleteActivityRefreshError(
                "Garmin swim splits were unavailable; previous canonical data was preserved"
            )

        normalized = normalize_activity(raw.activity, raw.activity, raw.exercise_sets)
        if source_type_key == "lap_swimming":
            normalized = replace(
                normalized,
                swim_detail=normalize_garmin_swim(raw.activity, raw.activity, raw.splits),
            )
        if normalized.source_activity_id != activity_id:
            raise ActivityRefreshError("normalized Garmin activity ID does not match the requested activity")

        try:
            saved = self._repository.refresh(normalized, capture)
        except (sqlite3.Error, RuntimeError, ValueError) as exc:
            raise ActivityRefreshError(
                "canonical refresh failed; previous canonical data was preserved"
            ) from exc
        swim = saved.swim_detail
        return ActivityRefreshResult(
            activity=saved,
            capture=capture,
            strength_set_count=len(saved.strength_sets),
            swim_lap_count=len(swim.laps) if swim is not None else 0,
            swim_length_count=(sum(len(lap.lengths) for lap in swim.laps) if swim is not None else 0),
            review=derive_activity_review(saved),
            warnings=raw.warnings,
        )
