"""The user's training goal mode (Training Goal Mode v1).

A goal is a user setting (``config\\training_goal.json``), not a physiological fact and not a
computed target. Without a goal file every existing output is unchanged (the code defaults in
``training_goals`` keep describing a gain phase). Validation never echoes a value: errors name the
flag (or the file key) and the allowed range only.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum

from muscle50.domain.recovery_assessment import (
    DEFAULT_SLEEP_THRESHOLDS,
    SleepThresholds,
)

# Body fat percent target bounds come from the spec (3-60 %).
TARGET_BODY_FAT_PERCENT_RANGE = (Decimal("3"), Decimal("60"))
# The remaining bounds are design choices (plausibility limits, not evidence).
TARGET_WEIGHT_KG_RANGE = (Decimal("30"), Decimal("250"))
MIN_SKELETAL_MUSCLE_MASS_KG_RANGE = (Decimal("10"), Decimal("100"))
WEEKLY_LOSS_PERCENT_RANGE = (Decimal("0.05"), Decimal("2.0"))
# Sleep threshold bounds (design): 0 < reduce < hold <= 12 h, score 1-100.
MAX_SLEEP_THRESHOLD_SECONDS = 12 * 3600
SLEEP_SCORE_RANGE = (1, 100)

# Where each goal field comes from on the command line (errors name the flag, never the value).
GOAL_FLAGS = {
    "mode": "--mode",
    "target_body_fat_percent": "--target-body-fat",
    "target_weight_kg": "--target-weight",
    "target_date": "--by",
    "min_skeletal_muscle_mass_kg": "--min-smm",
    "weekly_loss_percent": "--weekly-loss",
}
SLEEP_FLAGS = {
    "hold_below_seconds": "--hold-below-hours",
    "reduce_below_seconds": "--reduce-below-hours",
    "hold_below_score": "--hold-below-score",
}


class GoalMode(StrEnum):
    CUT = "cut"
    """Lose body fat while keeping muscle: progression keeps load and reps (MAINT-02)."""
    MAINTAIN = "maintain"
    GAIN = "gain"


class TrainingGoalError(ValueError):
    """A goal or sleep-threshold value is outside its allowed range; ``key`` is the file key."""

    def __init__(self, message: str, key: str) -> None:
        super().__init__(message)
        self.key = key


class GoalSettingsError(RuntimeError):
    """A stored goal or sleep-threshold file cannot be read without guessing."""


@dataclass(frozen=True)
class WeeklyRateRange:
    """An inclusive range of weekly body-weight change, in percent of body weight per week."""

    minimum: Decimal
    maximum: Decimal


@dataclass(frozen=True)
class TrainingGoal:
    mode: GoalMode
    target_body_fat_percent: Decimal | None = None
    target_weight_kg: Decimal | None = None
    target_date: date | None = None
    min_skeletal_muscle_mass_kg: Decimal | None = None
    weekly_loss_percent: WeeklyRateRange | None = None
    """Cut only: the user's own target loss range (MAINT-05 gives 0.5-1.0 as the evidence range)."""


@dataclass(frozen=True)
class SleepThresholdSetting:
    thresholds: SleepThresholds
    source: str
    """``default`` (no settings file) or ``user_setting``."""


DEFAULT_SLEEP_SETTING = SleepThresholdSetting(DEFAULT_SLEEP_THRESHOLDS, "default")


def validate_goal(goal: TrainingGoal, *, today: date | None = None) -> TrainingGoal:
    """Check every rule; ``today`` (``goal set`` only) also requires the deadline to be after it.

    A stored goal is read without ``today``, so a deadline that has passed still loads (and is
    reported as passed) instead of making the file invalid.
    """
    if goal.target_body_fat_percent is not None and goal.target_weight_kg is not None:
        raise TrainingGoalError(
            "--target-body-fat와 --target-weight는 함께 쓸 수 없습니다(목표는 하나만).", "target_weight_kg"
        )
    _check_range(goal.target_body_fat_percent, TARGET_BODY_FAT_PERCENT_RANGE, "target_body_fat_percent")
    _check_range(goal.target_weight_kg, TARGET_WEIGHT_KG_RANGE, "target_weight_kg")
    _check_range(goal.min_skeletal_muscle_mass_kg, MIN_SKELETAL_MUSCLE_MASS_KG_RANGE, "min_skeletal_muscle_mass_kg")
    if goal.target_date is not None:
        if goal.target_body_fat_percent is None and goal.target_weight_kg is None:
            raise TrainingGoalError(
                "--by에는 목표(--target-body-fat 또는 --target-weight)가 필요합니다.", "target_date"
            )
        if today is not None and goal.target_date <= today:
            raise TrainingGoalError("--by는 오늘 이후 날짜여야 합니다.", "target_date")
    rate = goal.weekly_loss_percent
    if rate is not None:
        if goal.mode is not GoalMode.CUT:
            raise TrainingGoalError("--weekly-loss는 --mode cut에서만 쓸 수 있습니다.", "weekly_loss_percent")
        _check_range(rate.minimum, WEEKLY_LOSS_PERCENT_RANGE, "weekly_loss_percent")
        _check_range(rate.maximum, WEEKLY_LOSS_PERCENT_RANGE, "weekly_loss_percent")
        if rate.minimum > rate.maximum:
            raise TrainingGoalError("--weekly-loss는 MIN <= MAX여야 합니다.", "weekly_loss_percent")
    return goal


def validate_sleep_thresholds(thresholds: SleepThresholds) -> SleepThresholds:
    hold, reduce = thresholds.short_sleep_seconds, thresholds.very_short_sleep_seconds
    if not 0 < hold <= MAX_SLEEP_THRESHOLD_SECONDS:
        raise TrainingGoalError("--hold-below-hours는 0보다 크고 12 이하여야 합니다.", "hold_below_seconds")
    if not 0 < reduce < hold:
        raise TrainingGoalError(
            "--reduce-below-hours는 0보다 크고 hold 기준(--hold-below-hours)보다 작아야 합니다.",
            "reduce_below_seconds",
        )
    low, high = SLEEP_SCORE_RANGE
    if not low <= thresholds.low_sleep_score <= high:
        raise TrainingGoalError(f"--hold-below-score는 {low}~{high} 사이의 정수여야 합니다.", "hold_below_score")
    return thresholds


def _check_range(value: Decimal | None, bounds: tuple[Decimal, Decimal], key: str) -> None:
    if value is None:
        return
    low, high = bounds
    if not low <= value <= high:
        raise TrainingGoalError(f"{GOAL_FLAGS[key]}은 {low}~{high} 사이여야 합니다.", key)
