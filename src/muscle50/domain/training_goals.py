"""Stable training goals used by the recommendation layer.

v1 keeps goals as code defaults (no persistence, no migration). They describe what the
user wants, not physiological truth; every rule that uses them names the field it used.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RepRange:
    minimum: int
    maximum: int


@dataclass(frozen=True)
class TrainingGoals:
    strength_priority: str = "hypertrophy"
    skeletal_muscle_mass_milestone_kg: float = 43.0
    skeletal_muscle_mass_long_term_kg: float = 50.0
    strength_sessions_per_week: int = 5
    strength_session_minutes: int = 40
    # Each major muscle region should usually be trained this many times per week.
    region_min_sessions_per_week: int = 1
    region_max_sessions_per_week: int = 2
    compound_rep_range: RepRange = RepRange(5, 12)
    isolation_rep_range: RepRange = RepRange(10, 20)
    # Advice only: the data never records reps in reserve.
    reps_in_reserve_min: int = 1
    reps_in_reserve_max: int = 3
    swim_sessions_per_week: int = 3
    # The user's stated practical continuous swim; recent data may under-represent it.
    continuous_swim_baseline_meters: float = 1000.0
    continuous_swim_target_meters: float = 1500.0
    target_1500m_fastest_seconds: int = 24 * 60
    target_1500m_slowest_seconds: int = 27 * 60 + 30


DEFAULT_TRAINING_GOALS = TrainingGoals()
