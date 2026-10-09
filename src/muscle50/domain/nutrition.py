"""Deterministic nutrition domain values and aggregation.

Parsing is deliberately outside this module.  The domain accepts already
structured quantities and nutrition facts, then performs only exact Decimal
arithmetic and deterministic source selection.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from datetime import date, datetime, tzinfo
from decimal import ROUND_HALF_EVEN, Context, Decimal, localcontext
from enum import StrEnum


class MealType(StrEnum):
    BREAKFAST = "breakfast"
    LUNCH = "lunch"
    DINNER = "dinner"
    SNACK = "snack"
    OTHER = "other"


class QuantityUnit(StrEnum):
    GRAM = "g"
    MILLILITER = "ml"
    COUNT = "count"
    PACK = "pack"
    PIECE = "piece"
    ANIMAL = "animal"
    SERVING = "serving"


class NutrientField(StrEnum):
    CALORIES_KCAL = "calories_kcal"
    PROTEIN_G = "protein_g"
    CARBOHYDRATE_G = "carbohydrate_g"
    FAT_G = "fat_g"


class NutritionSourceType(StrEnum):
    NUTRITION_LABEL = "nutrition_label"
    USER_PROVIDED = "user_provided"
    KNOWN_PRODUCT = "known_product"
    FOOD_DATABASE = "food_database"
    VISUAL_ESTIMATE = "visual_estimate"
    LANGUAGE_ESTIMATE = "language_estimate"


class Accuracy(StrEnum):
    EXACT = "exact"
    ESTIMATED = "estimated"


SOURCE_PRIORITY: dict[NutritionSourceType, int] = {
    NutritionSourceType.NUTRITION_LABEL: 600,
    NutritionSourceType.USER_PROVIDED: 500,
    NutritionSourceType.KNOWN_PRODUCT: 400,
    NutritionSourceType.FOOD_DATABASE: 300,
    NutritionSourceType.VISUAL_ESTIMATE: 200,
    NutritionSourceType.LANGUAGE_ESTIMATE: 200,
}

NUTRITION_DECIMAL_PRECISION = 28
_NUTRITION_CONTEXT = Context(prec=NUTRITION_DECIMAL_PRECISION, rounding=ROUND_HALF_EVEN)

# General meal (Nutrition General Meal v1): "I ate a meal whose menu and numbers I do not know".
# It is a reserved system profile with no facts and no aliases; a general item points to it and has
# no quantity, no unit and no facts, so every nutrient of that item is unknown (never 0).
GENERAL_MEAL_FOOD_ID = "general-meal"
GENERAL_MEAL_NAME = "일반식"
GENERAL_MEAL_NOTE_MAX_LENGTH = 100
_RESERVED_FOOD_REFERENCES = frozenset({GENERAL_MEAL_FOOD_ID, GENERAL_MEAL_NAME})


@dataclass(frozen=True)
class NutritionValue:
    calories_kcal: Decimal | None = None
    protein_g: Decimal | None = None
    carbohydrate_g: Decimal | None = None
    fat_g: Decimal | None = None

    def __post_init__(self) -> None:
        for nutrient in NutrientField:
            value = self.get(nutrient)
            if value is not None:
                _validate_non_negative_decimal(value, nutrient.value)

    def get(self, nutrient: NutrientField) -> Decimal | None:
        if nutrient is NutrientField.CALORIES_KCAL:
            return self.calories_kcal
        if nutrient is NutrientField.PROTEIN_G:
            return self.protein_g
        if nutrient is NutrientField.CARBOHYDRATE_G:
            return self.carbohydrate_g
        return self.fat_g

    def scaled(self, factor: Decimal) -> NutritionValue:
        _validate_non_negative_decimal(factor, "factor")
        return NutritionValue(**{nutrient.value: _scale(self.get(nutrient), factor) for nutrient in NutrientField})

    def scaled_ratio(self, numerator: Decimal, denominator: Decimal) -> NutritionValue:
        _validate_non_negative_decimal(numerator, "numerator")
        _validate_positive_decimal(denominator, "denominator")
        return NutritionValue(
            **{
                nutrient.value: _scale_ratio(self.get(nutrient), numerator, denominator)
                for nutrient in NutrientField
            }
        )

    def plus(self, other: NutritionValue) -> NutritionValue:
        """Add values without treating unknown components as zero."""
        return NutritionValue(
            **{
                nutrient.value: _strict_sum(self.get(nutrient), other.get(nutrient))
                for nutrient in NutrientField
            }
        )

    @property
    def has_any_value(self) -> bool:
        return any(self.get(nutrient) is not None for nutrient in NutrientField)


@dataclass(frozen=True)
class NutritionRange:
    minimum: NutritionValue
    maximum: NutritionValue

    def __post_init__(self) -> None:
        for nutrient in NutrientField:
            minimum = self.minimum.get(nutrient)
            maximum = self.maximum.get(nutrient)
            if (minimum is None) != (maximum is None):
                raise ValueError(f"{nutrient.value} range requires both minimum and maximum")
            if minimum is not None and maximum is not None and minimum > maximum:
                raise ValueError(f"{nutrient.value} minimum cannot exceed maximum")

    def scaled(self, factor: Decimal) -> NutritionRange:
        return NutritionRange(self.minimum.scaled(factor), self.maximum.scaled(factor))

    def scaled_ratio(self, numerator: Decimal, denominator: Decimal) -> NutritionRange:
        return NutritionRange(
            self.minimum.scaled_ratio(numerator, denominator),
            self.maximum.scaled_ratio(numerator, denominator),
        )

    def bounds(self, nutrient: NutrientField) -> tuple[Decimal, Decimal] | None:
        minimum = self.minimum.get(nutrient)
        maximum = self.maximum.get(nutrient)
        if minimum is None or maximum is None:
            return None
        return minimum, maximum

    @property
    def has_any_value(self) -> bool:
        return self.minimum.has_any_value


@dataclass(frozen=True)
class NutritionProvenance:
    source_type: NutritionSourceType
    accuracy: Accuracy
    source_reference: str
    created_at: datetime
    confidence: Decimal | None = None
    parser_version: str | None = None
    model_version: str | None = None

    def __post_init__(self) -> None:
        _require_text(self.source_reference, "source_reference")
        _require_aware(self.created_at, "created_at")
        if self.confidence is not None:
            _validate_non_negative_decimal(self.confidence, "confidence")
            if self.confidence > Decimal(1):
                raise ValueError("confidence must be between 0 and 1")
        if self.source_type in {
            NutritionSourceType.VISUAL_ESTIMATE,
            NutritionSourceType.LANGUAGE_ESTIMATE,
        } and self.accuracy is not Accuracy.ESTIMATED:
            raise ValueError(f"{self.source_type.value} must be marked estimated")


@dataclass(frozen=True)
class NutritionFact:
    """A nutrient declaration for a quantity basis, retained append-only."""

    fact_id: str
    values: NutritionValue
    basis_quantity: Decimal
    basis_unit: QuantityUnit
    provenance: NutritionProvenance
    value_range: NutritionRange | None = None
    supersedes_fact_id: str | None = None

    def __post_init__(self) -> None:
        _require_text(self.fact_id, "fact_id")
        _validate_positive_decimal(self.basis_quantity, "basis_quantity")
        if self.supersedes_fact_id == self.fact_id:
            raise ValueError("a nutrition fact cannot supersede itself")
        if self.provenance.accuracy is Accuracy.EXACT and self.value_range is not None:
            raise ValueError("exact nutrition facts cannot carry an estimate range")
        if not self.values.has_any_value and (self.value_range is None or not self.value_range.has_any_value):
            raise ValueError("a nutrition fact requires at least one value or range")
        if self.value_range is not None:
            for nutrient in NutrientField:
                value = self.values.get(nutrient)
                bounds = self.value_range.bounds(nutrient)
                if value is not None and bounds is not None and not bounds[0] <= value <= bounds[1]:
                    raise ValueError(f"{nutrient.value} must fall within its estimate range")

    def calculate(self, quantity: Decimal, unit: QuantityUnit) -> CalculatedNutrition:
        _validate_positive_decimal(quantity, "quantity")
        if unit is not self.basis_unit:
            raise ValueError(f"cannot convert {unit.value} to {self.basis_unit.value} without an explicit conversion")
        values = self.values.scaled_ratio(quantity, self.basis_quantity)
        value_range = (
            self.value_range.scaled_ratio(quantity, self.basis_quantity) if self.value_range is not None else None
        )
        nutrients = tuple(
            CalculatedNutrient(
                nutrient=nutrient,
                fact_id=self.fact_id,
                value=values.get(nutrient),
                minimum=value_range.minimum.get(nutrient) if value_range is not None else None,
                maximum=value_range.maximum.get(nutrient) if value_range is not None else None,
                provenance=self.provenance,
            )
            for nutrient in NutrientField
            if values.get(nutrient) is not None
            or (value_range is not None and value_range.bounds(nutrient) is not None)
        )
        return CalculatedNutrition(nutrients)


@dataclass(frozen=True)
class CalculatedNutrient:
    nutrient: NutrientField
    fact_id: str
    value: Decimal | None
    minimum: Decimal | None
    maximum: Decimal | None
    provenance: NutritionProvenance


@dataclass(frozen=True)
class CalculatedNutrition:
    nutrients: tuple[CalculatedNutrient, ...]

    def __post_init__(self) -> None:
        fields = [item.nutrient for item in self.nutrients]
        if len(fields) != len(set(fields)):
            raise ValueError("calculated nutrition fields must be unique")

    def get(self, nutrient: NutrientField) -> CalculatedNutrient | None:
        return next((item for item in self.nutrients if item.nutrient is nutrient), None)

    @property
    def values(self) -> NutritionValue:
        return NutritionValue(
            **{
                nutrient.value: (selection.value if (selection := self.get(nutrient)) is not None else None)
                for nutrient in NutrientField
            }
        )


@dataclass(frozen=True)
class FoodNutritionProfile:
    """Reusable nutrition declarations for a known food or product."""

    profile_id: str
    name: str
    facts: tuple[NutritionFact, ...]
    aliases: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_text(self.profile_id, "profile_id")
        _require_text(self.name, "name")
        _validate_fact_history(self.facts)
        if len(set(self.aliases)) != len(self.aliases):
            raise ValueError("profile aliases must be unique")
        for alias in self.aliases:
            _require_text(alias, "alias")

    def preferred_fact(self, unit: QuantityUnit, nutrient: NutrientField | None = None) -> NutritionFact | None:
        return select_preferred_fact(self.facts, unit, nutrient)


@dataclass(frozen=True)
class MealItem:
    meal_id: str
    sequence: int
    food_name: str
    quantity: Decimal | None
    quantity_unit: QuantityUnit | None
    food_profile_id: str | None = None
    serving_description: str | None = None
    nutrition_facts: tuple[NutritionFact, ...] = ()

    def __post_init__(self) -> None:
        _require_text(self.meal_id, "meal_id")
        if isinstance(self.sequence, bool) or not isinstance(self.sequence, int) or self.sequence < 1:
            raise ValueError("sequence must be a positive integer")
        _require_text(self.food_name, "food_name")
        if self.food_profile_id is not None:
            _require_text(self.food_profile_id, "food_profile_id")
        if (self.quantity is None) != (self.quantity_unit is None):
            raise ValueError("quantity and quantity_unit must both be present or both be absent")
        if self.quantity is not None:
            _validate_positive_decimal(self.quantity, "quantity")
        _validate_fact_history(self.nutrition_facts)

    @property
    def is_general(self) -> bool:
        """A general meal item: the reserved profile with no quantity, no unit and no facts.

        The reserved profile ID is required: an item without a quantity that points to any other
        food (for example one written by a future parser) is not a general meal.
        """
        return (
            self.food_profile_id == GENERAL_MEAL_FOOD_ID
            and self.quantity is None
            and self.quantity_unit is None
            and not self.nutrition_facts
        )

    def preferred_fact(self, nutrient: NutrientField | None = None) -> NutritionFact | None:
        if self.quantity_unit is None:
            return None
        return select_preferred_fact(self.nutrition_facts, self.quantity_unit, nutrient)

    def calculated_nutrition(self) -> CalculatedNutrition | None:
        if self.quantity is None or self.quantity_unit is None:
            return None
        nutrients: list[CalculatedNutrient] = []
        for nutrient in NutrientField:
            fact = self.preferred_fact(nutrient)
            if fact is None:
                continue
            selection = fact.calculate(self.quantity, self.quantity_unit).get(nutrient)
            if selection is not None:
                nutrients.append(selection)
        return CalculatedNutrition(tuple(nutrients)) if nutrients else None


@dataclass(frozen=True)
class Meal:
    meal_id: str
    eaten_at: datetime
    meal_type: MealType
    original_text: str
    parser_version: str | None = None
    model_version: str | None = None
    notes: str | None = None
    items: tuple[MealItem, ...] = ()

    def __post_init__(self) -> None:
        _require_text(self.meal_id, "meal_id")
        _require_aware(self.eaten_at, "eaten_at")
        _require_text(self.original_text, "original_text")
        if self.parser_version is not None:
            _require_text(self.parser_version, "parser_version")
        if self.model_version is not None:
            _require_text(self.model_version, "model_version")
        sequences = [item.sequence for item in self.items]
        if len(sequences) != len(set(sequences)):
            raise ValueError("meal item sequences must be unique")
        if any(item.meal_id != self.meal_id for item in self.items):
            raise ValueError("every item must reference its containing meal")


@dataclass(frozen=True)
class NutritionAggregate:
    totals: NutritionValue
    known_subtotals: NutritionValue
    value_range: NutritionRange | None
    incomplete_fields: frozenset[NutrientField]
    estimated_fields: frozenset[NutrientField]
    item_count: int
    uncalculated_items: tuple[MealItemReference, ...]


@dataclass(frozen=True)
class MealItemReference:
    meal_id: str
    sequence: int


@dataclass(frozen=True)
class MealNutritionSummary:
    meal_id: str
    eaten_at: datetime
    meal_type: MealType
    nutrition: NutritionAggregate


@dataclass(frozen=True)
class DailyNutritionSummary:
    day: date
    timezone_name: str
    meals: tuple[MealNutritionSummary, ...]
    nutrition: NutritionAggregate


def normalize_general_meal_note(text: str | None) -> str | None:
    """The general meal memo as stored: surrounding whitespace stripped, empty meaning no memo.

    Raises ValueError when the memo is longer than GENERAL_MEAL_NOTE_MAX_LENGTH characters or is
    not a single line of text (it contains a control character such as a line break or a tab).
    """
    if text is None:
        return None
    note = text.strip()
    if not note:
        return None
    if len(note) > GENERAL_MEAL_NOTE_MAX_LENGTH:
        raise ValueError(f"must be at most {GENERAL_MEAL_NOTE_MAX_LENGTH} characters (got {len(note)})")
    if any(unicodedata.category(character) == "Cc" for character in note):
        raise ValueError("must be a single line of text")
    return note


def is_reserved_food_reference(text: str) -> bool:
    """True when ``text`` names the general meal (its ID or name, whitespace and case ignored)."""
    return text.strip().lower() in _RESERVED_FOOD_REFERENCES


def select_preferred_fact(
    facts: tuple[NutritionFact, ...],
    unit: QuantityUnit,
    nutrient: NutrientField | None = None,
) -> NutritionFact | None:
    """Select the best active compatible fact using a stable priority order."""
    superseded_ids = {
        fact.supersedes_fact_id
        for fact in facts
        if fact.supersedes_fact_id is not None and (nutrient is None or _fact_has(fact, nutrient))
    }
    candidates = [
        fact
        for fact in facts
        if fact.fact_id not in superseded_ids
        and fact.basis_unit is unit
        and (nutrient is None or _fact_has(fact, nutrient))
    ]
    if not candidates:
        return None
    return max(candidates, key=_fact_selection_key)


def aggregate_meal(meal: Meal) -> MealNutritionSummary:
    nutrition = _aggregate_items(meal.items)
    return MealNutritionSummary(meal.meal_id, meal.eaten_at, meal.meal_type, nutrition)


def aggregate_day(
    meals: tuple[Meal, ...],
    day: date,
    timezone: tzinfo,
    *,
    timezone_name: str,
) -> DailyNutritionSummary:
    _require_text(timezone_name, "timezone_name")
    selected = tuple(
        sorted(
            (meal for meal in meals if meal.eaten_at.astimezone(timezone).date() == day),
            key=lambda meal: (meal.eaten_at, meal.meal_id),
        )
    )
    summaries = tuple(aggregate_meal(meal) for meal in selected)
    items = tuple(item for meal in selected for item in meal.items)
    return DailyNutritionSummary(day, timezone_name, summaries, _aggregate_items(items))


def _aggregate_items(items: tuple[MealItem, ...]) -> NutritionAggregate:
    calculated = tuple((item, item.calculated_nutrition()) for item in items)
    totals: dict[str, Decimal | None] = {}
    known_subtotals: dict[str, Decimal | None] = {}
    minimums: dict[str, Decimal | None] = {}
    maximums: dict[str, Decimal | None] = {}
    incomplete: set[NutrientField] = set()
    estimated: set[NutrientField] = set()
    if not items:
        incomplete.update(NutrientField)

    for nutrient in NutrientField:
        known_values: list[Decimal] = []
        lower_bounds: list[Decimal] = []
        upper_bounds: list[Decimal] = []
        bounds_complete = bool(items)
        has_estimated_range = False

        for _item, result in calculated:
            if result is None:
                incomplete.add(nutrient)
                bounds_complete = False
                continue

            selection = result.get(nutrient)
            if selection is None:
                incomplete.add(nutrient)
                bounds_complete = False
                continue

            value = selection.value
            if value is None:
                incomplete.add(nutrient)
            else:
                known_values.append(value)

            if selection.provenance.accuracy is Accuracy.ESTIMATED:
                if value is not None or (selection.minimum is not None and selection.maximum is not None):
                    estimated.add(nutrient)
                if selection.minimum is None or selection.maximum is None:
                    bounds_complete = False
                else:
                    lower_bounds.append(selection.minimum)
                    upper_bounds.append(selection.maximum)
                    has_estimated_range = True
            elif value is None:
                bounds_complete = False
            else:
                lower_bounds.append(value)
                upper_bounds.append(value)

        known_subtotal = _sum_decimals(known_values) if known_values else None
        known_subtotals[nutrient.value] = known_subtotal
        totals[nutrient.value] = None if nutrient in incomplete else known_subtotal
        if bounds_complete and has_estimated_range:
            minimums[nutrient.value] = _sum_decimals(lower_bounds)
            maximums[nutrient.value] = _sum_decimals(upper_bounds)
        else:
            minimums[nutrient.value] = None
            maximums[nutrient.value] = None

    range_value = NutritionRange(NutritionValue(**minimums), NutritionValue(**maximums))
    uncalculated = tuple(
        MealItemReference(item.meal_id, item.sequence) for item, result in calculated if result is None
    )
    return NutritionAggregate(
        totals=NutritionValue(**totals),
        known_subtotals=NutritionValue(**known_subtotals),
        value_range=range_value if range_value.has_any_value else None,
        incomplete_fields=frozenset(incomplete),
        estimated_fields=frozenset(estimated),
        item_count=len(items),
        uncalculated_items=uncalculated,
    )


def _fact_selection_key(fact: NutritionFact) -> tuple[int, int, Decimal, datetime, str]:
    return (
        SOURCE_PRIORITY[fact.provenance.source_type],
        1 if fact.provenance.accuracy is Accuracy.EXACT else 0,
        fact.provenance.confidence if fact.provenance.confidence is not None else Decimal(-1),
        fact.provenance.created_at,
        fact.fact_id,
    )


def _validate_fact_history(facts: tuple[NutritionFact, ...]) -> None:
    ids = {fact.fact_id for fact in facts}
    if len(ids) != len(facts):
        raise ValueError("nutrition fact IDs must be unique")
    if any(fact.supersedes_fact_id is not None and fact.supersedes_fact_id not in ids for fact in facts):
        raise ValueError("superseded nutrition facts must be retained in history")
    by_id = {fact.fact_id: fact for fact in facts}
    if any(
        fact.supersedes_fact_id is not None
        and fact.basis_unit is not by_id[fact.supersedes_fact_id].basis_unit
        for fact in facts
    ):
        raise ValueError("a nutrition fact can only supersede a fact with the same basis unit")
    supersedes = {fact.fact_id: fact.supersedes_fact_id for fact in facts}
    for fact in facts:
        seen: set[str] = set()
        current: str | None = fact.fact_id
        while current is not None:
            if current in seen:
                raise ValueError("nutrition fact supersession history cannot contain a cycle")
            seen.add(current)
            current = supersedes[current]


def _scale(value: Decimal | None, factor: Decimal) -> Decimal | None:
    if value is None:
        return None
    with localcontext(_NUTRITION_CONTEXT):
        return value * factor


def _scale_ratio(value: Decimal | None, numerator: Decimal, denominator: Decimal) -> Decimal | None:
    if value is None:
        return None
    with localcontext(_NUTRITION_CONTEXT):
        return value * numerator / denominator


def _strict_sum(left: Decimal | None, right: Decimal | None) -> Decimal | None:
    if left is None or right is None:
        return None
    return _sum_decimals([left, right])


def _sum_decimals(values: list[Decimal]) -> Decimal:
    with localcontext(_NUTRITION_CONTEXT):
        total = Decimal(0)
        for value in values:
            total += value
        return total


def _fact_has(fact: NutritionFact, nutrient: NutrientField) -> bool:
    return fact.values.get(nutrient) is not None or (
        fact.value_range is not None and fact.value_range.bounds(nutrient) is not None
    )


def _require_text(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must not be blank")


def _require_aware(value: datetime, field_name: str) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


def _validate_non_negative_decimal(value: Decimal, field_name: str) -> None:
    if not isinstance(value, Decimal) or not value.is_finite() or value < 0:
        raise ValueError(f"{field_name} must be a finite non-negative Decimal")


def _validate_positive_decimal(value: Decimal, field_name: str) -> None:
    _validate_non_negative_decimal(value, field_name)
    if value == 0:
        raise ValueError(f"{field_name} must be greater than zero")
