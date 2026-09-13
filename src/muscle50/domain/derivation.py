"""Derived, replaceable display values built from normalized data."""

from __future__ import annotations

from dataclasses import dataclass

from muscle50.domain.activity import NormalizedActivity


@dataclass(frozen=True)
class ActivitySummary:
    pace_seconds_per_km: float | None


def derive_summary(activity: NormalizedActivity) -> ActivitySummary:
    duration = activity.moving_seconds or activity.elapsed_seconds
    distance = activity.distance_meters
    pace = None
    if duration is not None and distance is not None and distance > 0:
        pace = duration / (distance / 1000)
    return ActivitySummary(pace_seconds_per_km=pace)
