"""Synthetic canonical objects for analytics tests. No real account data."""

from __future__ import annotations

from typing import Any

from muscle50.domain.activity import ActivityMetric, ActivityType, NormalizedActivity, StrengthSet
from muscle50.domain.activity_load import ACTIVITY_LOAD_METRICS
from muscle50.domain.recovery import DailyRecovery
from muscle50.domain.swimming import GarminSource, NormalizedSwimActivity, SwimDistance, SwimLap, SwimLength

_SOURCE = GarminSource(path="synthetic", fields_json="{}")


def load_metrics(**values: float | None) -> tuple[ActivityMetric, ...]:
    """All ten load metrics with value 1.0 unless overridden; None omits the metric."""
    metrics = []
    for spec in ACTIVITY_LOAD_METRICS:
        value = values.get(spec.metric_key, 1.0)
        if value is not None:
            metrics.append(ActivityMetric(spec.metric_key, value, spec.unit, spec.source_key))
    return tuple(metrics)


def activity(
    source_id: str,
    started_at_local: str | None,
    canonical_type: ActivityType = ActivityType.RUNNING,
    **overrides: Any,
) -> NormalizedActivity:
    source_type = {
        ActivityType.STRENGTH: "strength_training",
        ActivityType.SWIMMING: "lap_swimming",
    }.get(canonical_type, canonical_type.value)
    fields: dict[str, Any] = {
        "source_activity_id": source_id,
        "source_type_key": source_type,
        "canonical_type": canonical_type,
        "name": None,
        "started_at_utc": None,
        "started_at_local": started_at_local,
        "timezone_name": None,
        "elapsed_seconds": 600.0,
        "moving_seconds": 500.0,
        "distance_meters": None,
        "calories_kcal": None,
        "average_hr_bpm": None,
        "max_hr_bpm": None,
        "elevation_gain_meters": None,
        "metrics": load_metrics(),
    }
    fields.update(overrides)
    return NormalizedActivity(**fields)


def strength_set(
    sequence: int,
    *,
    set_type: str = "ACTIVE",
    category: str | None = "BENCH_PRESS",
    name: str | None = None,
    reps: int | None = 10,
    weight_kg: float | None = 50.0,
) -> StrengthSet:
    key = name or category
    return StrengthSet(
        sequence=sequence,
        source_message_index=sequence,
        source_exercise_category=category,
        source_exercise_name=name,
        source_exercise_key=key,
        display_exercise_name=key.replace("_", " ").title() if key else None,
        source_exercise_probability=None,
        set_type=set_type,
        reps=reps,
        source_weight=weight_kg * 1000 if weight_kg is not None else None,
        source_weight_unit="g" if weight_kg is not None else None,
        normalized_weight_kg=weight_kg,
        duration_seconds=30.0,
        started_at=None,
        workout_step_index=None,
    )


def length(sequence: int, distance: float | None, duration: float | None) -> SwimLength:
    return SwimLength(
        sequence=sequence,
        sequence_in_lap=sequence,
        source_message_index=None,
        start_time_utc=None,
        length_type=None,
        stroke_type=None,
        distance=SwimDistance(distance),
        duration_seconds=duration,
        moving_seconds=None,
        elapsed_seconds=None,
        rest_duration_seconds=None,
        average_speed_mps=None,
        stroke_count=None,
        swolf=None,
        average_hr_bpm=None,
        max_hr_bpm=None,
        source=_SOURCE,
    )


def lap(sequence: int, distance: float, duration: float, lengths: tuple[SwimLength, ...]) -> SwimLap:
    return SwimLap(
        sequence=sequence,
        source_lap_index=sequence + 1,
        source_message_index=sequence,
        start_time_utc=None,
        intensity_type=None,
        stroke_type=None,
        distance=SwimDistance(distance),
        duration_seconds=duration,
        moving_seconds=None,
        elapsed_seconds=None,
        rest_duration_seconds=None,
        average_speed_mps=None,
        active_length_count=None,
        total_length_count=None,
        stroke_count=None,
        swolf=None,
        average_hr_bpm=None,
        max_hr_bpm=None,
        lengths=lengths,
        source=_SOURCE,
    )


def uniform_lap(sequence: int, count: int, pool: float, seconds_per_length: float) -> SwimLap:
    lengths = tuple(length(index, pool, seconds_per_length) for index in range(count))
    return lap(sequence, pool * count, seconds_per_length * count, lengths)


def swim_detail(source_id: str, laps: tuple[SwimLap, ...], pool: float = 25.0) -> NormalizedSwimActivity:
    return NormalizedSwimActivity(
        source_activity_id=source_id,
        source_type_key="lap_swimming",
        pool_length_meters=pool,
        source_pool_length=pool,
        source_pool_length_unit="meter",
        source_active_length_count=None,
        splits_available=True,
        laps=laps,
        source=_SOURCE,
    )


def recovery(calendar_date: str, **overrides: Any) -> DailyRecovery:
    fields: dict[str, Any] = {
        "calendar_date": calendar_date,
        "sleep_seconds": 25200,
        "deep_sleep_seconds": 3600,
        "light_sleep_seconds": 14400,
        "rem_sleep_seconds": 5400,
        "awake_sleep_seconds": 1800,
        "sleep_start_gmt_ms": None,
        "sleep_end_gmt_ms": None,
        "sleep_score": 80,
        "sleep_avg_hrv_ms": 50.0,
        "hrv_last_night_avg_ms": 48.0,
        "hrv_weekly_avg_ms": 45.0,
        "hrv_status": "BALANCED",
        "resting_heart_rate_bpm": 55.0,
        "body_battery_high": 90,
        "body_battery_low": 20,
        "stress_average": 30,
        "training_readiness_score": 60,
        "training_readiness_level": "MODERATE",
        "recovery_time_minutes": 600,
        "recovery_time_change_phrase": None,
        "training_status_key": "PRODUCTIVE",
        "respiration_avg_brpm": 14.0,
    }
    fields.update(overrides)
    return DailyRecovery(**fields)
