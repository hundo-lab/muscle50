"""Explicitly refresh one already-imported Garmin activity."""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Any

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

        detail_summary = _detail_summary(raw.activity)
        normalized = normalize_activity(detail_summary, {}, raw.exercise_sets)
        if source_type_key == "lap_swimming":
            normalized = replace(
                normalized,
                swim_detail=normalize_garmin_swim(
                    detail_summary,
                    {},
                    raw.splits,
                    pool_length_factor_applies=not isinstance(raw.activity.get("summaryDTO"), Mapping),
                ),
            )
        normalized = _preserve_missing_canonical_values(normalized, existing)
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


def _detail_summary(activity: Mapping[str, Any]) -> Mapping[str, Any]:
    """Flatten the scalar summary embedded by Garmin's activity-detail endpoint.

    ``get_activity`` is not shaped like an activity-list item: identity, name, type,
    and timezone live at the top level, while measurements live in ``summaryDTO``.
    The fallback keeps synthetic/legacy payloads that already use the flat shape.
    """
    summary = activity.get("summaryDTO")
    if not isinstance(summary, Mapping):
        return activity
    source = dict(activity)
    # When both shapes happen to expose the same scalar, summaryDTO owns the
    # measurement in the detail endpoint. Top-level identity/type/timezone remain.
    source.update(summary)
    return source


def _preserve_missing_canonical_values(
    refreshed: NormalizedActivity,
    existing: NormalizedActivity,
) -> NormalizedActivity:
    """Keep stored canonical values when the detail endpoint omits their source fields."""
    refreshed_metrics = list(refreshed.metrics)
    refreshed_metric_keys = {metric.key for metric in refreshed.metrics}
    for metric in existing.metrics:
        if metric.key not in refreshed_metric_keys:
            refreshed_metrics.append(metric)

    refreshed_swim = refreshed.swim_detail
    existing_swim = existing.swim_detail
    if refreshed_swim is not None and existing_swim is not None:
        refreshed_swim = replace(
            refreshed_swim,
            pool_length_meters=(
                refreshed_swim.pool_length_meters
                if refreshed_swim.pool_length_meters is not None
                else existing_swim.pool_length_meters
            ),
            source_pool_length=(
                refreshed_swim.source_pool_length
                if refreshed_swim.source_pool_length is not None
                else existing_swim.source_pool_length
            ),
            source_pool_length_unit=(
                refreshed_swim.source_pool_length_unit
                if refreshed_swim.source_pool_length_unit is not None
                else existing_swim.source_pool_length_unit
            ),
            source_active_length_count=(
                refreshed_swim.source_active_length_count
                if refreshed_swim.source_active_length_count is not None
                else existing_swim.source_active_length_count
            ),
        )

    return replace(
        refreshed,
        name=refreshed.name if refreshed.name is not None else existing.name,
        started_at_utc=(
            refreshed.started_at_utc if refreshed.started_at_utc is not None else existing.started_at_utc
        ),
        started_at_local=(
            refreshed.started_at_local
            if refreshed.started_at_local is not None
            else existing.started_at_local
        ),
        timezone_name=(
            refreshed.timezone_name if refreshed.timezone_name is not None else existing.timezone_name
        ),
        elapsed_seconds=(
            refreshed.elapsed_seconds if refreshed.elapsed_seconds is not None else existing.elapsed_seconds
        ),
        moving_seconds=(
            refreshed.moving_seconds if refreshed.moving_seconds is not None else existing.moving_seconds
        ),
        distance_meters=(
            refreshed.distance_meters if refreshed.distance_meters is not None else existing.distance_meters
        ),
        calories_kcal=(
            refreshed.calories_kcal if refreshed.calories_kcal is not None else existing.calories_kcal
        ),
        average_hr_bpm=(
            refreshed.average_hr_bpm if refreshed.average_hr_bpm is not None else existing.average_hr_bpm
        ),
        max_hr_bpm=refreshed.max_hr_bpm if refreshed.max_hr_bpm is not None else existing.max_hr_bpm,
        elevation_gain_meters=(
            refreshed.elevation_gain_meters
            if refreshed.elevation_gain_meters is not None
            else existing.elevation_gain_meters
        ),
        metrics=tuple(refreshed_metrics),
        swim_detail=refreshed_swim,
    )
