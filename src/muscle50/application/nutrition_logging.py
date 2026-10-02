"""Nutrition Logging MVP: a personal food catalog, structured meal entry and daily intake.

Every nutrient comes from a fact the user supplied for a catalog food. Logging a meal
snapshots the food's fact history for the logged unit onto the meal item (provenance and
supersession copied verbatim), so a later catalog correction never rewrites a historical meal. Units are
never converted: a food declared per 100 g cannot be logged in packs. Missing nutrients stay
missing; totals are reported only when every item contributes the nutrient.

No targets, remaining amounts or recommendations live here; this is intake only.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, tzinfo
from decimal import Decimal

from muscle50.application.nutrition import FoodNutritionRepository, MealReader, MealRepository
from muscle50.domain.nutrition import (
    Accuracy,
    CalculatedNutrition,
    DailyNutritionSummary,
    FoodNutritionProfile,
    Meal,
    MealItem,
    MealNutritionSummary,
    MealType,
    NutrientField,
    NutritionFact,
    NutritionProvenance,
    NutritionSourceType,
    NutritionValue,
    QuantityUnit,
    aggregate_day,
    aggregate_meal,
)

# Letters (including Hangul), digits, "_", "." and "-": no whitespace, so an ID is one CLI token.
FOOD_ID_PATTERN = re.compile(r"\w[\w.-]*\Z")

# Only sources where a person supplied the numbers. Visual/language estimates belong to a
# future parser and are deliberately not offered by the catalog.
CATALOG_SOURCE_TYPES: tuple[NutritionSourceType, ...] = (
    NutritionSourceType.NUTRITION_LABEL,
    NutritionSourceType.USER_PROVIDED,
    NutritionSourceType.KNOWN_PRODUCT,
    NutritionSourceType.FOOD_DATABASE,
)

MEAL_TYPE_ORDER: dict[MealType, int] = {meal_type: index for index, meal_type in enumerate(MealType)}


class NutritionLoggingError(ValueError):
    """A request that cannot be recorded or answered without guessing."""


@dataclass(frozen=True)
class NewFood:
    food_id: str
    name: str
    basis_quantity: Decimal
    basis_unit: QuantityUnit
    values: NutritionValue
    source_type: NutritionSourceType
    accuracy: Accuracy
    source_reference: str
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True)
class MealEntryItem:
    food_id: str
    quantity: Decimal
    unit: QuantityUnit


@dataclass(frozen=True)
class ItemIntake:
    item: MealItem
    calculated: CalculatedNutrition | None
    # Nutrients this item cannot supply a value for, in NutrientField order.
    missing_fields: tuple[NutrientField, ...]


@dataclass(frozen=True)
class MealIntake:
    meal: Meal
    summary: MealNutritionSummary
    items: tuple[ItemIntake, ...]


@dataclass(frozen=True)
class DailyIntake:
    day: date
    timezone_name: str
    meals: tuple[MealIntake, ...]
    summary: DailyNutritionSummary


class AddFood:
    def __init__(self, repository: FoodNutritionRepository, clock: Callable[[], datetime]) -> None:
        self._repository = repository
        self._clock = clock

    def execute(self, food: NewFood) -> FoodNutritionProfile:
        if FOOD_ID_PATTERN.fullmatch(food.food_id) is None:
            raise NutritionLoggingError(
                f"food id {food.food_id!r} must be one token of letters, digits, '_', '.' or '-'"
            )
        name = food.name.strip()
        if not name:
            raise NutritionLoggingError("food name must not be blank")
        if food.source_type not in CATALOG_SOURCE_TYPES:
            raise NutritionLoggingError(f"source {food.source_type.value!r} cannot be entered into the food catalog")
        if not food.values.has_any_value:
            raise NutritionLoggingError("at least one of kcal/protein/carbohydrate/fat must be a number")
        if self._repository.get(food.food_id) is not None:
            raise NutritionLoggingError(f"food id {food.food_id!r} already exists; nothing was changed")
        aliases = tuple(alias.strip() for alias in food.aliases)
        for label in (name, *aliases):
            clashes = self._repository.search(label)
            if clashes:
                owner = ", ".join(profile.profile_id for profile in clashes)
                raise NutritionLoggingError(
                    f"name or alias {label!r} is already used by food {owner}; nothing was changed"
                )
        try:
            profile = FoodNutritionProfile(
                profile_id=food.food_id,
                name=name,
                aliases=aliases,
                facts=(
                    NutritionFact(
                        fact_id=f"food:{food.food_id}:1",
                        values=food.values,
                        basis_quantity=food.basis_quantity,
                        basis_unit=food.basis_unit,
                        provenance=NutritionProvenance(
                            source_type=food.source_type,
                            accuracy=food.accuracy,
                            source_reference=food.source_reference,
                            created_at=self._clock(),
                        ),
                    ),
                ),
            )
            self._repository.save(profile)
        except ValueError as exc:
            raise NutritionLoggingError(str(exc)) from exc
        return profile


class ListFoods:
    def __init__(self, repository: FoodNutritionRepository) -> None:
        self._repository = repository

    def execute(self) -> tuple[FoodNutritionProfile, ...]:
        return self._repository.list_all()


class ShowFood:
    def __init__(self, repository: FoodNutritionRepository) -> None:
        self._repository = repository

    def execute(self, food_id: str) -> FoodNutritionProfile:
        profile = self._repository.get(food_id)
        if profile is None:
            raise NutritionLoggingError(f"no food with id {food_id!r}")
        return profile


class LogMeal:
    def __init__(self, meals: MealRepository, foods: FoodNutritionRepository) -> None:
        self._meals = meals
        self._foods = foods

    def execute(
        self,
        day: date,
        meal_type: MealType,
        items: tuple[MealEntryItem, ...],
        *,
        timezone: tzinfo,
        eaten_time: time | None = None,
        additional: bool = False,
    ) -> MealIntake:
        if not items:
            raise NutritionLoggingError("a meal needs at least one item")
        existing = tuple(
            meal
            for meal in self._meals.list_eaten_between(*local_day_bounds(day, timezone))
            if meal.meal_type is meal_type
        )
        if existing and not additional:
            ids = ", ".join(meal.meal_id for meal in existing)
            raise NutritionLoggingError(
                f"{meal_type.value} on {day.isoformat()} is already recorded ({ids}); "
                "pass --additional to record another one. Nothing was changed."
            )
        meal_id = self._next_meal_id(day, meal_type)
        meal_items = tuple(
            self._snapshot_item(meal_id, sequence, entry) for sequence, entry in enumerate(items, start=1)
        )
        # Without --time the meal is dated, not timed: it is stored at local 00:00 of the day.
        eaten_at = datetime.combine(day, eaten_time or time(0), tzinfo=timezone)
        try:
            meal = Meal(
                meal_id=meal_id,
                eaten_at=eaten_at,
                meal_type=meal_type,
                original_text=_structured_text(meal_type, day, eaten_time, items),
                items=meal_items,
            )
            self._meals.save(meal)
        except ValueError as exc:
            raise NutritionLoggingError(str(exc)) from exc
        stored = self._meals.get(meal_id)
        if stored is None:
            raise RuntimeError(f"meal {meal_id!r} was not found after saving")
        return meal_intake(stored)

    def _next_meal_id(self, day: date, meal_type: MealType) -> str:
        number = 1
        while self._meals.get(f"{day.isoformat()}-{meal_type.value}-{number}") is not None:
            number += 1
        return f"{day.isoformat()}-{meal_type.value}-{number}"

    def _snapshot_item(self, meal_id: str, sequence: int, entry: MealEntryItem) -> MealItem:
        profile = self._foods.get(entry.food_id)
        if profile is None:
            raise NutritionLoggingError(
                f"item {sequence}: no food with id {entry.food_id!r} (see `muscle50 nutrition food list`)"
            )
        if all(profile.preferred_fact(entry.unit, nutrient) is None for nutrient in NutrientField):
            units = sorted({fact.basis_unit.value for fact in profile.facts})
            raise NutritionLoggingError(
                f"item {sequence}: food {profile.profile_id!r} has nutrition per {', '.join(units) or 'nothing'}, "
                f"not per {entry.unit.value}; units are never converted. Nothing was changed."
            )

        # Copy the whole same-unit fact history, not only today's winners: supersession is decided
        # per nutrient, so the item must keep the links to select exactly what the catalog selects.
        # Numbers and provenance are verbatim; each copy's ID names its catalog fact. Supersession
        # never crosses units, so every link target is part of this copy.
        def snapshot_id(fact_id: str) -> str:
            return f"{meal_id}:{sequence}:{fact_id}"

        snapshots = tuple(
            NutritionFact(
                fact_id=snapshot_id(fact.fact_id),
                values=fact.values,
                basis_quantity=fact.basis_quantity,
                basis_unit=fact.basis_unit,
                provenance=fact.provenance,
                value_range=fact.value_range,
                supersedes_fact_id=snapshot_id(fact.supersedes_fact_id) if fact.supersedes_fact_id else None,
            )
            for fact in profile.facts
            if fact.basis_unit is entry.unit
        )
        try:
            return MealItem(
                meal_id=meal_id,
                sequence=sequence,
                food_name=profile.name,
                food_profile_id=profile.profile_id,
                quantity=entry.quantity,
                quantity_unit=entry.unit,
                nutrition_facts=snapshots,
            )
        except ValueError as exc:
            raise NutritionLoggingError(f"item {sequence}: {exc}") from exc


class ShowDailyIntake:
    def __init__(self, meals: MealReader) -> None:
        self._meals = meals

    def execute(self, day: date, timezone: tzinfo, *, timezone_name: str) -> DailyIntake:
        meals = self._meals.list_eaten_between(*local_day_bounds(day, timezone))
        summary = aggregate_day(meals, day, timezone, timezone_name=timezone_name)
        selected = {meal.meal_id for meal in summary.meals}
        ordered = sorted(
            (meal for meal in meals if meal.meal_id in selected),
            key=lambda meal: (meal.eaten_at, MEAL_TYPE_ORDER[meal.meal_type], meal.meal_id),
        )
        return DailyIntake(day, timezone_name, tuple(meal_intake(meal) for meal in ordered), summary)


def meal_intake(meal: Meal) -> MealIntake:
    return MealIntake(meal, aggregate_meal(meal), tuple(_item_intake(item) for item in meal.items))


def local_day_bounds(day: date, timezone: tzinfo) -> tuple[datetime, datetime]:
    start = datetime.combine(day, time(0), tzinfo=timezone)
    end = datetime.combine(day + timedelta(days=1), time(0), tzinfo=timezone)
    return start, end


def offset_name(timezone: tzinfo, day: date) -> str:
    """'+09:00' style name from the UTC offset (tzname() can be a localized string on Windows)."""
    offset = datetime.combine(day, time(12), tzinfo=timezone).utcoffset() or timedelta(0)
    minutes = int(offset.total_seconds()) // 60
    sign = "-" if minutes < 0 else "+"
    hours, rest = divmod(abs(minutes), 60)
    return f"{sign}{hours:02d}:{rest:02d}"


def _item_intake(item: MealItem) -> ItemIntake:
    calculated = item.calculated_nutrition()
    missing = tuple(
        nutrient
        for nutrient in NutrientField
        if calculated is None or (selection := calculated.get(nutrient)) is None or selection.value is None
    )
    return ItemIntake(item, calculated, missing)


def _structured_text(meal_type: MealType, day: date, eaten_time: time | None, items: tuple[MealEntryItem, ...]) -> str:
    when = day.isoformat() + (f" {eaten_time.strftime('%H:%M')}" if eaten_time is not None else "")
    entries = "; ".join(f"{item.food_id} {item.quantity} {item.unit.value}" for item in items)
    return f"structured entry {meal_type.value} {when}: {entries}"
