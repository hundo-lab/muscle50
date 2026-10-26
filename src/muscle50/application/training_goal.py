"""Set, show and remove the training goal and the sleep thresholds (user settings, no database)."""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from decimal import Decimal
from typing import Protocol

from muscle50.domain.recovery_assessment import SleepThresholds
from muscle50.domain.training_goal import (
    SleepThresholdSetting,
    TrainingGoal,
    TrainingGoalError,
    validate_goal,
    validate_sleep_thresholds,
)

SECONDS_PER_HOUR = 3600


class TrainingGoalRepository(Protocol):
    def load(self) -> TrainingGoal | None: ...

    def save(self, goal: TrainingGoal) -> None: ...

    def delete(self) -> bool:
        """Remove the goal; False when none was stored."""
        ...


class SleepThresholdRepository(Protocol):
    def load(self) -> SleepThresholdSetting: ...

    def save(self, thresholds: SleepThresholds) -> None: ...

    def delete(self) -> bool: ...


class SetTrainingGoal:
    def __init__(self, repository: TrainingGoalRepository) -> None:
        self._repository = repository

    def execute(self, goal: TrainingGoal, *, today: date) -> TrainingGoal:
        """Validate, then replace the whole stored goal (fields not given are not kept)."""
        self._repository.save(validate_goal(goal, today=today))
        stored = self._repository.load()
        assert stored is not None
        return stored


class ShowTrainingGoal:
    def __init__(self, repository: TrainingGoalRepository) -> None:
        self._repository = repository

    def execute(self) -> TrainingGoal | None:
        return self._repository.load()


class UnsetTrainingGoal:
    def __init__(self, repository: TrainingGoalRepository) -> None:
        self._repository = repository

    def execute(self) -> bool:
        return self._repository.delete()


class SetSleepThresholds:
    def __init__(self, repository: SleepThresholdRepository) -> None:
        self._repository = repository

    def execute(
        self,
        *,
        hold_below_hours: Decimal | None = None,
        reduce_below_hours: Decimal | None = None,
        hold_below_score: int | None = None,
    ) -> SleepThresholdSetting:
        """Merge the given values into the current thresholds, validate, then save."""
        current = self._repository.load().thresholds
        updated = replace(
            current,
            short_sleep_seconds=_seconds(hold_below_hours, "hold_below_seconds", current.short_sleep_seconds),
            very_short_sleep_seconds=_seconds(
                reduce_below_hours, "reduce_below_seconds", current.very_short_sleep_seconds
            ),
            low_sleep_score=current.low_sleep_score if hold_below_score is None else hold_below_score,
        )
        self._repository.save(validate_sleep_thresholds(updated))
        return self._repository.load()


class ShowSleepThresholds:
    def __init__(self, repository: SleepThresholdRepository) -> None:
        self._repository = repository

    def execute(self) -> SleepThresholdSetting:
        return self._repository.load()


class ResetSleepThresholds:
    def __init__(self, repository: SleepThresholdRepository) -> None:
        self._repository = repository

    def execute(self) -> bool:
        return self._repository.delete()


def _seconds(hours: Decimal | None, key: str, current: int) -> int:
    if hours is None:
        return current
    seconds = hours * SECONDS_PER_HOUR
    if seconds != seconds.to_integral_value():
        flag = "--hold-below-hours" if key == "hold_below_seconds" else "--reduce-below-hours"
        raise TrainingGoalError(f"{flag}는 정수 초가 되는 시간이어야 합니다(예: 5, 5.5, 5.25).", key)
    return int(seconds)
