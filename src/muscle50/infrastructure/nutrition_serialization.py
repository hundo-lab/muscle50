"""Versioned JSON-compatible serialization for Nutrition Core meals."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from decimal import Decimal
from typing import Any

from muscle50.domain.nutrition import (
    Accuracy,
    Meal,
    MealItem,
    MealType,
    NutritionFact,
    NutritionProvenance,
    NutritionRange,
    NutritionSourceType,
    NutritionValue,
    QuantityUnit,
)
from muscle50.infrastructure.decimal_text import decimal_from_text, decimal_to_text

SCHEMA_VERSION = 1


class NutritionSerializationError(ValueError):
    """Raised when serialized nutrition data is invalid or unsupported."""


def meal_to_dict(meal: Meal) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "meal_id": meal.meal_id,
        "eaten_at": meal.eaten_at.isoformat(),
        "meal_type": meal.meal_type.value,
        "original_text": meal.original_text,
        "parser_version": meal.parser_version,
        "model_version": meal.model_version,
        "notes": meal.notes,
        "items": [_item_to_dict(item) for item in meal.items],
    }


def meal_from_dict(raw: Mapping[str, Any]) -> Meal:
    try:
        _check_keys(
            raw,
            {
                "schema_version",
                "meal_id",
                "eaten_at",
                "meal_type",
                "original_text",
                "parser_version",
                "model_version",
                "notes",
                "items",
            },
            "meal",
        )
        version = raw["schema_version"]
        if version != SCHEMA_VERSION:
            raise NutritionSerializationError(f"unsupported nutrition schema version: {version!r}")
        raw_items = _sequence(raw["items"], "items")
        meal = Meal(
            meal_id=_string(raw["meal_id"], "meal_id"),
            eaten_at=_datetime(raw["eaten_at"], "eaten_at"),
            meal_type=MealType(_string(raw["meal_type"], "meal_type")),
            original_text=_string(raw["original_text"], "original_text"),
            parser_version=_optional_string(raw["parser_version"], "parser_version"),
            model_version=_optional_string(raw["model_version"], "model_version"),
            notes=_optional_string(raw["notes"], "notes"),
            items=tuple(_item_from_dict(_mapping(item, "item")) for item in raw_items),
        )
    except NutritionSerializationError:
        raise
    except (KeyError, TypeError, ValueError) as exc:
        raise NutritionSerializationError(f"invalid serialized meal: {exc}") from exc
    return meal


def _item_to_dict(item: MealItem) -> dict[str, Any]:
    return {
        "meal_id": item.meal_id,
        "sequence": item.sequence,
        "food_name": item.food_name,
        "food_profile_id": item.food_profile_id,
        "quantity": _decimal_to_string(item.quantity),
        "quantity_unit": item.quantity_unit.value if item.quantity_unit is not None else None,
        "serving_description": item.serving_description,
        "nutrition_facts": [_fact_to_dict(fact) for fact in item.nutrition_facts],
    }


def _item_from_dict(raw: Mapping[str, Any]) -> MealItem:
    _check_keys(
        raw,
        {
            "meal_id",
            "sequence",
            "food_name",
            "food_profile_id",
            "quantity",
            "quantity_unit",
            "serving_description",
            "nutrition_facts",
        },
        "item",
    )
    facts = _sequence(raw["nutrition_facts"], "nutrition_facts")
    unit = raw["quantity_unit"]
    return MealItem(
        meal_id=_string(raw["meal_id"], "item.meal_id"),
        sequence=_integer(raw["sequence"], "sequence"),
        food_name=_string(raw["food_name"], "food_name"),
        food_profile_id=_optional_string(raw["food_profile_id"], "food_profile_id"),
        quantity=_optional_decimal(raw["quantity"], "quantity"),
        quantity_unit=QuantityUnit(_string(unit, "quantity_unit")) if unit is not None else None,
        serving_description=_optional_string(raw["serving_description"], "serving_description"),
        nutrition_facts=tuple(_fact_from_dict(_mapping(fact, "nutrition_fact")) for fact in facts),
    )


def _fact_to_dict(fact: NutritionFact) -> dict[str, Any]:
    return {
        "fact_id": fact.fact_id,
        "values": _value_to_dict(fact.values),
        "basis_quantity": _decimal_to_string(fact.basis_quantity),
        "basis_unit": fact.basis_unit.value,
        "provenance": {
            "source_type": fact.provenance.source_type.value,
            "source_reference": fact.provenance.source_reference,
            "confidence": _decimal_to_string(fact.provenance.confidence),
            "accuracy": fact.provenance.accuracy.value,
            "parser_version": fact.provenance.parser_version,
            "model_version": fact.provenance.model_version,
            "created_at": fact.provenance.created_at.isoformat(),
        },
        "value_range": _range_to_dict(fact.value_range),
        "supersedes_fact_id": fact.supersedes_fact_id,
    }


def _fact_from_dict(raw: Mapping[str, Any]) -> NutritionFact:
    _check_keys(
        raw,
        {
            "fact_id",
            "values",
            "basis_quantity",
            "basis_unit",
            "provenance",
            "value_range",
            "supersedes_fact_id",
        },
        "nutrition_fact",
    )
    provenance = _mapping(raw["provenance"], "provenance")
    _check_keys(
        provenance,
        {
            "source_type",
            "source_reference",
            "confidence",
            "accuracy",
            "parser_version",
            "model_version",
            "created_at",
        },
        "provenance",
    )
    raw_range = raw["value_range"]
    return NutritionFact(
        fact_id=_string(raw["fact_id"], "fact_id"),
        values=_value_from_dict(_mapping(raw["values"], "values")),
        basis_quantity=_decimal(raw["basis_quantity"], "basis_quantity"),
        basis_unit=QuantityUnit(_string(raw["basis_unit"], "basis_unit")),
        provenance=NutritionProvenance(
            source_type=NutritionSourceType(_string(provenance["source_type"], "source_type")),
            source_reference=_string(provenance["source_reference"], "source_reference"),
            confidence=_optional_decimal(provenance["confidence"], "confidence"),
            accuracy=Accuracy(_string(provenance["accuracy"], "accuracy")),
            parser_version=_optional_string(provenance["parser_version"], "parser_version"),
            model_version=_optional_string(provenance["model_version"], "model_version"),
            created_at=_datetime(provenance["created_at"], "created_at"),
        ),
        value_range=_range_from_dict(_mapping(raw_range, "value_range")) if raw_range is not None else None,
        supersedes_fact_id=_optional_string(raw["supersedes_fact_id"], "supersedes_fact_id"),
    )


def _value_to_dict(value: NutritionValue) -> dict[str, str | None]:
    return {
        "calories_kcal": _decimal_to_string(value.calories_kcal),
        "protein_g": _decimal_to_string(value.protein_g),
        "carbohydrate_g": _decimal_to_string(value.carbohydrate_g),
        "fat_g": _decimal_to_string(value.fat_g),
    }


def _value_from_dict(raw: Mapping[str, Any]) -> NutritionValue:
    _check_keys(raw, {"calories_kcal", "protein_g", "carbohydrate_g", "fat_g"}, "nutrition_value")
    return NutritionValue(
        calories_kcal=_optional_decimal(raw["calories_kcal"], "calories_kcal"),
        protein_g=_optional_decimal(raw["protein_g"], "protein_g"),
        carbohydrate_g=_optional_decimal(raw["carbohydrate_g"], "carbohydrate_g"),
        fat_g=_optional_decimal(raw["fat_g"], "fat_g"),
    )


def _range_to_dict(value_range: NutritionRange | None) -> dict[str, Any] | None:
    if value_range is None:
        return None
    return {"minimum": _value_to_dict(value_range.minimum), "maximum": _value_to_dict(value_range.maximum)}


def _range_from_dict(raw: Mapping[str, Any]) -> NutritionRange:
    _check_keys(raw, {"minimum", "maximum"}, "value_range")
    return NutritionRange(
        minimum=_value_from_dict(_mapping(raw["minimum"], "minimum")),
        maximum=_value_from_dict(_mapping(raw["maximum"], "maximum")),
    )


def _mapping(value: Any, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise NutritionSerializationError(f"{field_name} must be an object")
    return value


def _check_keys(raw: Mapping[str, Any], expected: set[str], field_name: str) -> None:
    actual = set(raw)
    missing = expected - actual
    unexpected = actual - expected
    if missing:
        raise NutritionSerializationError(f"{field_name} is missing fields: {sorted(missing)}")
    if unexpected:
        raise NutritionSerializationError(f"{field_name} has unexpected fields: {sorted(unexpected)}")


def _sequence(value: Any, field_name: str) -> Sequence[Any]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise NutritionSerializationError(f"{field_name} must be an array")
    return value


def _string(value: Any, field_name: str) -> str:
    if not isinstance(value, str):
        raise NutritionSerializationError(f"{field_name} must be a string")
    return value


def _optional_string(value: Any, field_name: str) -> str | None:
    return None if value is None else _string(value, field_name)


def _integer(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise NutritionSerializationError(f"{field_name} must be an integer")
    return int(value)


def _decimal(value: Any, field_name: str) -> Decimal:
    if not isinstance(value, str):
        raise NutritionSerializationError(f"{field_name} must be a decimal string")
    try:
        return decimal_from_text(value)
    except ValueError as exc:
        raise NutritionSerializationError(f"{field_name} must be a decimal string") from exc


def _optional_decimal(value: Any, field_name: str) -> Decimal | None:
    return None if value is None else _decimal(value, field_name)


def _decimal_to_string(value: Decimal | None) -> str | None:
    return None if value is None else decimal_to_text(value)


def _datetime(value: Any, field_name: str) -> datetime:
    text = _string(value, field_name)
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise NutritionSerializationError(f"{field_name} must be an ISO 8601 datetime") from exc
