"""Nutrition targets and the daily status of logged intake against them.

Targets are one current, user-set document. They live apart from meals, so changing a target
never rewrites logged data; a status for any date compares that date's intake with the targets
configured now. The intake comes from ShowDailyIntake unchanged (same meals, same aggregation).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, tzinfo
from typing import Protocol

from muscle50.application.nutrition import MealRepository
from muscle50.application.nutrition_logging import DailyIntake, ShowDailyIntake
from muscle50.domain.nutrition import NutrientField
from muscle50.domain.nutrition_targets import (
    NutrientTarget,
    NutrientTargetStatus,
    NutritionTargets,
    evaluate_targets,
)


class NutritionTargetRepository(Protocol):
    def load(self) -> NutritionTargets: ...

    def save(self, targets: NutritionTargets) -> None: ...


@dataclass(frozen=True)
class MissingItem:
    """A logged item that has no value for a nutrient."""

    meal_id: str
    sequence: int
    food_id: str | None
    food_name: str


@dataclass(frozen=True)
class NutrientDayStatus:
    status: NutrientTargetStatus
    missing_items: tuple[MissingItem, ...]


@dataclass(frozen=True)
class DailyNutritionStatus:
    intake: DailyIntake
    targets: NutritionTargets
    nutrients: tuple[NutrientDayStatus, ...]


class SetNutritionTarget:
    def __init__(self, repository: NutritionTargetRepository) -> None:
        self._repository = repository

    def execute(self, nutrient: NutrientField, target: NutrientTarget | None) -> NutritionTargets:
        """Set (or, with ``None``, unset) one nutrient's target; the others are kept."""
        targets = self._repository.load().with_target(nutrient, target)
        self._repository.save(targets)
        return self._repository.load()


class ShowNutritionTargets:
    def __init__(self, repository: NutritionTargetRepository) -> None:
        self._repository = repository

    def execute(self) -> NutritionTargets:
        return self._repository.load()


class ShowDailyNutritionStatus:
    def __init__(self, meals: MealRepository, targets: NutritionTargetRepository) -> None:
        self._intake = ShowDailyIntake(meals)
        self._targets = targets

    def execute(self, day: date, timezone: tzinfo, *, timezone_name: str) -> DailyNutritionStatus:
        targets = self._targets.load()
        intake = self._intake.execute(day, timezone, timezone_name=timezone_name)
        statuses = evaluate_targets(targets, intake.summary.nutrition)
        return DailyNutritionStatus(
            intake,
            targets,
            tuple(NutrientDayStatus(status, _missing_items(intake, status.nutrient)) for status in statuses),
        )


def _missing_items(intake: DailyIntake, nutrient: NutrientField) -> tuple[MissingItem, ...]:
    return tuple(
        MissingItem(meal.meal.meal_id, item.item.sequence, item.item.food_profile_id, item.item.food_name)
        for meal in intake.meals
        for item in meal.items
        if nutrient in item.missing_fields
    )
