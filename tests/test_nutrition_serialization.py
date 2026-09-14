from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import pytest

from muscle50.infrastructure.nutrition_serialization import (
    NutritionSerializationError,
    meal_from_dict,
    meal_to_dict,
)


def _fixture() -> dict[str, Any]:
    path = Path(__file__).parent / "fixtures" / "nutrition_meal_v1.json"
    loaded: object = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return cast(dict[str, Any], loaded)


def test_synthetic_fixture_round_trips_without_decimal_or_provenance_loss() -> None:
    raw = _fixture()

    meal = meal_from_dict(raw)
    serialized = meal_to_dict(meal)

    assert serialized == raw
    assert meal.original_text == raw["original_text"]
    assert meal.parser_version == "synthetic-parser-v1"
    assert meal.model_version == "synthetic-model-v1"
    assert meal.items[0].nutrition_facts[0].provenance.source_reference == "synthetic-label://recovery-bar-v1"
    assert serialized["items"][0]["nutrition_facts"][0]["values"]["carbohydrate_g"] == "8.25"


@pytest.mark.parametrize("quantity", [2, "1E+2", "-1", "01"])
def test_noncanonical_json_values_are_rejected_to_protect_decimal_determinism(quantity: object) -> None:
    raw = _fixture()
    raw["items"][0]["quantity"] = quantity

    with pytest.raises(NutritionSerializationError, match="decimal string"):
        meal_from_dict(raw)


def test_unknown_schema_version_is_rejected() -> None:
    raw = _fixture()
    raw["schema_version"] = 99

    with pytest.raises(NutritionSerializationError, match="unsupported"):
        meal_from_dict(raw)


@pytest.mark.parametrize("case", ["missing", "unknown", "nested_missing"])
def test_decoder_enforces_schema_field_contract(case: str) -> None:
    raw = _fixture()
    if case == "missing":
        raw.pop("notes")
    elif case == "unknown":
        raw["unknown"] = "field"
    else:
        raw["items"][0]["nutrition_facts"][0]["values"].pop("protein_g")

    with pytest.raises(NutritionSerializationError, match="missing fields|unexpected fields"):
        meal_from_dict(raw)


def test_json_schema_is_packaged_and_versioned() -> None:
    schema_path = Path(__file__).parents[1] / "src" / "muscle50" / "schemas" / "nutrition_meal_v1.schema.json"

    schema = json.loads(schema_path.read_text(encoding="utf-8"))

    assert schema["properties"]["schema_version"] == {"const": 1}
    assert schema["$defs"]["nullable_decimal"]["type"] == ["string", "null"]
