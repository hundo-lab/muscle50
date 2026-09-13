"""Replaceable parser and persistence ports for Nutrition Core."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Protocol

from muscle50.domain.nutrition import FoodNutritionProfile, Meal, MealItem, MealType, NutritionFact, QuantityUnit


@dataclass(frozen=True)
class ParsedMealItem:
    """Parser output only; it contains no inferred nutrient calculation."""

    sequence: int
    food_name: str
    quantity: Decimal | None
    quantity_unit: QuantityUnit | None
    food_profile_id: str | None = None
    serving_description: str | None = None


@dataclass(frozen=True)
class ParsedMeal:
    original_text: str
    meal_type: MealType
    eaten_at: datetime
    items: tuple[ParsedMealItem, ...]
    parser_version: str
    model_version: str | None = None
    notes: str | None = None


class MealParser(Protocol):
    """Boundary for a future rule-based or LLM-backed structure parser."""

    def parse(self, original_text: str, *, reference_time: datetime) -> ParsedMeal: ...


def materialize_parsed_meal(meal_id: str, parsed: ParsedMeal) -> Meal:
    """Create a nutrient-free Meal while retaining structural parser provenance."""
    return Meal(
        meal_id=meal_id,
        eaten_at=parsed.eaten_at,
        meal_type=parsed.meal_type,
        original_text=parsed.original_text,
        parser_version=parsed.parser_version,
        model_version=parsed.model_version,
        notes=parsed.notes,
        items=tuple(
            MealItem(
                meal_id=meal_id,
                sequence=item.sequence,
                food_name=item.food_name,
                food_profile_id=item.food_profile_id,
                quantity=item.quantity,
                quantity_unit=item.quantity_unit,
                serving_description=item.serving_description,
            )
            for item in parsed.items
        ),
    )


class MealRepository(Protocol):
    """Persistence boundary; implementations must retain superseded facts."""

    def save(self, meal: Meal) -> None: ...

    def get(self, meal_id: str) -> Meal | None: ...

    def list_eaten_between(self, start_inclusive: datetime, end_exclusive: datetime) -> tuple[Meal, ...]: ...

    def append_nutrition_fact(self, meal_id: str, item_sequence: int, fact: NutritionFact) -> Meal: ...


class FoodNutritionRepository(Protocol):
    """Catalog boundary for reusing known food/product declarations."""

    def save(self, profile: FoodNutritionProfile) -> None: ...

    def get(self, profile_id: str) -> FoodNutritionProfile | None: ...

    def search(self, name_or_alias: str) -> tuple[FoodNutritionProfile, ...]: ...

    def append_nutrition_fact(self, profile_id: str, fact: NutritionFact) -> FoodNutritionProfile: ...
