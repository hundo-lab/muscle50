from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from muscle50.application.nutrition import MealParser, ParsedMeal, ParsedMealItem, materialize_parsed_meal
from muscle50.domain.nutrition import MealType, QuantityUnit


class SyntheticParser:
    """Test adapter proving parsers can be replaced without calculation changes."""

    def parse(self, original_text: str, *, reference_time: datetime) -> ParsedMeal:
        return ParsedMeal(
            original_text=original_text,
            meal_type=MealType.SNACK,
            eaten_at=reference_time,
            items=(
                ParsedMealItem(
                    sequence=1,
                    food_name="Synthetic Snack",
                    quantity=Decimal("2"),
                    quantity_unit=QuantityUnit.PIECE,
                    serving_description="2 pieces",
                ),
            ),
            parser_version="synthetic-parser-v1",
            model_version="synthetic-model-v1",
        )


def _parse_with(parser: MealParser, text: str, reference_time: datetime) -> ParsedMeal:
    return parser.parse(text, reference_time=reference_time)


def test_parser_port_preserves_original_text_and_returns_structure_only() -> None:
    reference_time = datetime.fromisoformat("2026-02-03T10:00:00+09:00")

    parsed = _parse_with(SyntheticParser(), "synthetic snack, two pieces", reference_time)

    assert parsed.original_text == "synthetic snack, two pieces"
    assert parsed.items[0].quantity == Decimal("2")
    assert not hasattr(parsed.items[0], "nutrition")

    meal = materialize_parsed_meal("meal-from-synthetic-parser", parsed)
    assert meal.original_text == parsed.original_text
    assert meal.parser_version == "synthetic-parser-v1"
    assert meal.model_version == "synthetic-model-v1"
    assert meal.items[0].meal_id == meal.meal_id
    assert meal.items[0].nutrition_facts == ()
