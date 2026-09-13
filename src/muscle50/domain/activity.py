"""Normalized activity domain types."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

type MetricValue = float | int | str
NORMALIZER_VERSION = 2


class ActivityType(StrEnum):
    RUNNING = "running"
    SWIMMING = "swimming"
    STRENGTH = "strength"
    CYCLING = "cycling"
    WALKING = "walking"
    OTHER = "other"


@dataclass(frozen=True)
class ActivityMetric:
    key: str
    value: MetricValue
    unit: str | None
    source_path: str


@dataclass(frozen=True)
class StrengthSet:
    sequence: int
    source_message_index: int | None
    source_exercise_category: str | None
    source_exercise_name: str | None
    source_exercise_key: str | None
    display_exercise_name: str | None
    source_exercise_probability: float | None
    set_type: str | None
    reps: int | None
    source_weight: float | None
    source_weight_unit: str | None
    normalized_weight_kg: float | None
    duration_seconds: float | None
    started_at: str | None
    workout_step_index: int | None


@dataclass(frozen=True)
class NormalizedActivity:
    source_activity_id: str
    source_type_key: str
    canonical_type: ActivityType
    name: str | None
    started_at_utc: str | None
    started_at_local: str | None
    timezone_name: str | None
    elapsed_seconds: float | None
    moving_seconds: float | None
    distance_meters: float | None
    calories_kcal: float | None
    average_hr_bpm: float | None
    max_hr_bpm: float | None
    elevation_gain_meters: float | None
    metrics: tuple[ActivityMetric, ...]
    strength_sets: tuple[StrengthSet, ...] = ()
    normalizer_version: int = NORMALIZER_VERSION
