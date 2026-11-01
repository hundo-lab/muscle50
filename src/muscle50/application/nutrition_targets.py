"""Nutrition targets and the daily status of logged intake against them.

Targets are one current, user-set document. They live apart from meals, so changing a target
never rewrites logged data; a status for any date compares that date's intake with the targets
configured now. The intake comes from ShowDailyIntake unchanged (same meals, same aggregation).

LDL Nutrients v1 adds the saturated fat limit and fiber floor next to the four nutrients. They are
evaluated apart (``DailyNutritionStatus.ldl``), so the four nutrient statuses, and every reader of
them (recommend, daily, Telegram), are unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, tzinfo
from typing import Protocol

from muscle50.application.nutrition import MealReader
from muscle50.application.nutrition_logging import DailyIntake, ShowDailyIntake
from muscle50.domain.ldl_nutrients import (
    FiberStatus,
    MealNote,
    SaturatedFatStatus,
    evaluate_fiber,
    evaluate_saturated_fat,
    meal_note,
)
from muscle50.domain.nutrition import NutrientField, OptionalNutrient, OptionalNutrientAggregate, optional_aggregate
from muscle50.domain.nutrition_targets import (
    FiberTarget,
    LdlTargets,
    NutrientTarget,
    NutrientTargetStatus,
    NutritionTargets,
    SaturatedFatTarget,
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
class LdlDayStatus:
    """The day's saturated fat and fiber against the user's LDL targets (advice only)."""

    saturated_fat: SaturatedFatStatus
    saturated_fat_missing: tuple[MissingItem, ...]
    fiber: FiberStatus
    fiber_missing: tuple[MissingItem, ...]
    meal_notes: tuple[MealNote, ...]

    @property
    def has_data(self) -> bool:
        """Some logged item has a saturated fat or fiber value or range."""
        return self.saturated_fat.aggregate.has_data or self.fiber.aggregate.has_data


@dataclass(frozen=True)
class DailyNutritionStatus:
    intake: DailyIntake
    targets: NutritionTargets
    nutrients: tuple[NutrientDayStatus, ...]
    # LDL Nutrients v1; filled by ShowDailyNutritionStatus.
    ldl: LdlDayStatus | None = None


class SetNutritionTarget:
    def __init__(self, repository: NutritionTargetRepository) -> None:
        self._repository = repository

    def execute(self, nutrient: NutrientField, target: NutrientTarget | None) -> NutritionTargets:
        """Set (or, with ``None``, unset) one nutrient's target; the others are kept."""
        targets = self._repository.load().with_target(nutrient, target)
        self._repository.save(targets)
        return self._repository.load()


class SetLdlTarget:
    """Set (or, with ``None``, unset) the saturated fat or fiber target; every other target is kept."""

    def __init__(self, repository: NutritionTargetRepository) -> None:
        self._repository = repository

    def execute(self, nutrient: OptionalNutrient, target: SaturatedFatTarget | FiberTarget | None) -> NutritionTargets:
        current = self._repository.load()
        ldl = current.ldl
        if nutrient is OptionalNutrient.SATURATED_FAT_G:
            if target is not None and not isinstance(target, SaturatedFatTarget):
                raise TypeError("saturated fat takes a SaturatedFatTarget")
            ldl = LdlTargets(target, ldl.fiber_g)
        else:
            if target is not None and not isinstance(target, FiberTarget):
                raise TypeError("fiber takes a FiberTarget")
            ldl = LdlTargets(ldl.saturated_fat_g, target)
        self._repository.save(current.with_ldl(ldl))
        return self._repository.load()


class ShowNutritionTargets:
    def __init__(self, repository: NutritionTargetRepository) -> None:
        self._repository = repository

    def execute(self) -> NutritionTargets:
        return self._repository.load()


class ShowDailyNutritionStatus:
    def __init__(self, meals: MealReader, targets: NutritionTargetRepository) -> None:
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
            ldl_day_status(intake, targets),
        )


def ldl_day_status(intake: DailyIntake, targets: NutritionTargets) -> LdlDayStatus:
    summary = intake.summary
    nutrition = summary.nutrition
    kcal_target = targets.get(NutrientField.CALORIES_KCAL)
    saturated_target = targets.ldl.saturated_fat_g
    complete_kcal = (
        nutrition.totals.calories_kcal
        if nutrition.item_count > 0 and NutrientField.CALORIES_KCAL not in nutrition.incomplete_fields
        else None
    )
    saturated = evaluate_saturated_fat(
        saturated_target,
        kcal_target,
        _aggregate(summary.optional, OptionalNutrient.SATURATED_FAT_G),
        logged_kcal=complete_kcal,
    )
    fiber = evaluate_fiber(targets.ldl.fiber_g, _aggregate(summary.optional, OptionalNutrient.FIBER_G))
    notes = tuple(
        note
        for meal in intake.meals
        if (
            note := meal_note(
                meal.meal.meal_id,
                saturated_target,
                kcal_target,
                _aggregate(meal.summary.optional, OptionalNutrient.SATURATED_FAT_G),
            )
        )
        is not None
    )
    return LdlDayStatus(
        saturated,
        _missing_optional(intake, OptionalNutrient.SATURATED_FAT_G),
        fiber,
        _missing_optional(intake, OptionalNutrient.FIBER_G),
        notes,
    )


def _aggregate(
    aggregates: tuple[OptionalNutrientAggregate, ...], nutrient: OptionalNutrient
) -> OptionalNutrientAggregate:
    aggregate = optional_aggregate(aggregates, nutrient)
    if aggregate is None:
        raise RuntimeError(f"no {nutrient.value} aggregate")
    return aggregate


def _missing_items(intake: DailyIntake, nutrient: NutrientField) -> tuple[MissingItem, ...]:
    return tuple(
        MissingItem(meal.meal.meal_id, item.item.sequence, item.item.food_profile_id, item.item.food_name)
        for meal in intake.meals
        for item in meal.items
        if nutrient in item.missing_fields
    )


def _missing_optional(intake: DailyIntake, nutrient: OptionalNutrient) -> tuple[MissingItem, ...]:
    """Items with no saturated fat / fiber value (a range alone is not a value), in day order."""
    return tuple(
        MissingItem(meal.meal.meal_id, item.item.sequence, item.item.food_profile_id, item.item.food_name)
        for meal in intake.meals
        for item in meal.items
        if not any(selection.nutrient is nutrient and selection.value is not None for selection in item.optional)
    )
