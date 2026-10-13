"""Telegram LLM v2.2: meal grouping, the catalog list, estimate provenance and the item schema (pure), then the
bot end to end (multi-meal proposals, linking and the `/ok` sequence). Synthetic foods only; no real CLI."""

from __future__ import annotations

import json
import sqlite3
from decimal import Decimal
from importlib.resources import files
from pathlib import Path

import pytest
from test_nutrition_domain import _fact
from test_telegram_llm_domain import ITEM_ESTIMATE, interpretation

from muscle50.application.nutrition_logging import GENERAL_ESTIMATE_REFERENCE_MAX_LENGTH
from muscle50.domain.nutrition import (
    FoodNutritionProfile,
    MealType,
    NutrientField,
    NutritionValue,
    QuantityUnit,
)
from muscle50.domain.telegram_llm import InterpretItem, ItemKind, LlmOutputError, parse_interpretation
from muscle50.domain.telegram_llm_meals import (
    CATALOG_HEADER,
    CATALOG_MAX_CHARS,
    CATALOG_MAX_FOODS,
    ESTIMATE_REFERENCE_MAX,
    MealGroup,
    catalog_prompt,
    estimate_reference,
    group_meals,
    is_meal_word,
    registered_units,
)
from muscle50.infrastructure.sqlite.food_catalog_reader import SqliteFoodCatalogReader
from muscle50.infrastructure.sqlite.nutrition_repository import SqliteFoodNutritionRepository

# --- helpers -----------------------------------------------------------------------------------------------


def item(food: str = "음식", meal: MealType | None = None) -> InterpretItem:
    return InterpretItem(ItemKind.GENERAL, food, None, None, False, None, (), meal_type=meal)


def profile(profile_id: str, name: str, *units: QuantityUnit, aliases: tuple[str, ...] = ()) -> FoodNutritionProfile:
    facts = tuple(
        _fact(f"{profile_id}-{unit.value}", NutritionValue(calories_kcal=Decimal(100)), basis_unit=unit)
        for unit in units
    )
    return FoodNutritionProfile(profile_id, name, facts, aliases)


# --- the item schema ---------------------------------------------------------------------------------------


def test_the_json_schema_item_and_the_parser_agree() -> None:
    schema = json.loads(
        files("muscle50").joinpath("schemas", "telegram_llm_interpret_v1.schema.json").read_text("utf-8")
    )
    entry = schema["properties"]["items"]["items"]
    document_item = interpretation()["items"][0]
    assert set(entry["required"]) == set(entry["properties"]) == set(document_item)
    assert entry["additionalProperties"] is False
    estimate = entry["properties"]["estimate"]
    assert set(estimate["required"]) == set(estimate["properties"])
    for name in ("kcal_min", "kcal_max", "protein_min", "protein_max"):
        assert estimate["properties"][name] == {"type": "number"}
    for name in ("carbs_min", "carbs_max", "fat_min", "fat_max"):
        assert estimate["properties"][name]["type"] == ["number", "null"]
    # menu items keep their all-nullable estimates
    menu_estimate = schema["properties"]["menu"]["properties"]["items"]["items"]["properties"]["estimate"]
    assert menu_estimate["properties"]["kcal_min"]["type"] == ["number", "null"]
    assert "$schema" not in schema


def test_reference_limit_matches_the_cli_limit() -> None:
    assert ESTIMATE_REFERENCE_MAX == GENERAL_ESTIMATE_REFERENCE_MAX_LENGTH


def test_mixed_typed_and_untyped_items_without_a_default_meal_are_bad_output() -> None:
    document = interpretation(meal_type=None)
    typed = {**document["items"][0], "meal_type": "lunch"}
    with pytest.raises(LlmOutputError):
        parse_interpretation({**document, "items": [typed, dict(document["items"][0])]})
    # all typed, or none typed, or untyped with a default meal: fine
    assert parse_interpretation({**document, "items": [typed, {**typed, "meal_type": "dinner"}]})
    assert parse_interpretation({**document, "items": [dict(document["items"][0])] * 2})
    assert parse_interpretation({**interpretation(meal_type="snack"), "items": [typed, dict(document["items"][0])]})


def test_ranges_with_only_kcal_and_protein_are_enough() -> None:
    parsed = parse_interpretation(interpretation())
    assert [field for field, _low, _high in parsed.items[0].estimate] == [
        NutrientField.CALORIES_KCAL,
        NutrientField.PROTEIN_G,
    ]
    assert ITEM_ESTIMATE["carbs_min"] is None


# --- meal words and grouping ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "word",
    [
        "아침",
        "점심",
        "저녁",
        "간식",
        "야식",
        "아침식사",
        "점심 식사",
        "저녁식사",
        " 저녁 ",
        "Lunch",
        "BREAKFAST",
        "snack!",
    ],
)
def test_meal_words_are_recognised(word: str) -> None:
    assert is_meal_word(word)


@pytest.mark.parametrize("word", ["", "김밥", "저녁 김밥", "점심 도시락", "닭가슴살", "아침밥"])
def test_foods_are_not_meal_words(word: str) -> None:
    assert not is_meal_word(word)


def test_group_meals_orders_canonically_and_merges_the_same_meal() -> None:
    items = [
        item("a", MealType.DINNER),
        item("b", MealType.BREAKFAST),
        item("c", MealType.DINNER),
        item("d", MealType.SNACK),
        item("e", MealType.LUNCH),
        item("f", MealType.SNACK),
    ]
    groups = group_meals(items, None)
    assert [group.meal_type for group in groups] == [
        MealType.BREAKFAST,
        MealType.LUNCH,
        MealType.DINNER,
        MealType.SNACK,
    ]
    assert [[entry.food_text for entry in group.items] for group in groups] == [["b"], ["e"], ["a", "c"], ["d", "f"]]


def test_group_meals_default_and_no_meal() -> None:
    assert group_meals([item("a"), item("b")], None) == (MealGroup(None, (item("a"), item("b"))),)
    groups = group_meals([item("a"), item("b", MealType.DINNER)], MealType.LUNCH)
    assert [group.meal_type for group in groups] == [MealType.LUNCH, MealType.DINNER]
    assert group_meals([], None) == ()


# --- the catalog list ------------------------------------------------------------------------------------------


def test_registered_units_are_the_units_with_a_value() -> None:
    food = profile("hetbahn", "CJ 햇반", QuantityUnit.COUNT, QuantityUnit.GRAM)
    assert registered_units(food) == (QuantityUnit.GRAM, QuantityUnit.COUNT)
    assert registered_units(profile("empty", "빈 음식")) == ()


def test_catalog_prompt_text_excludes_the_general_meal_and_unitless_foods() -> None:
    foods = [
        profile("hetbahn", "CJ 햇반 백미밥 210g", QuantityUnit.COUNT, QuantityUnit.GRAM),
        profile("chicken", "닭가슴살", QuantityUnit.PACK, aliases=("chicken", "치킨|브레스트", "a", "b")),
        profile("general-meal", "일반식"),
        profile("nounit", "단위 없음"),
    ]
    prompt = catalog_prompt(foods, "햇반")
    assert prompt is not None
    assert prompt.text == "\n".join(
        [
            CATALOG_HEADER,
            "chicken | 닭가슴살 | chicken, 치킨/브레스트, a | pack",
            "hetbahn | CJ 햇반 백미밥 210g | - | g, count",
        ]
    )
    assert (prompt.shown, prompt.total) == (2, 2)
    assert catalog_prompt([profile("general-meal", "일반식"), profile("nounit", "x")], "") is None
    assert catalog_prompt([], "") is None


def test_catalog_prompt_clips_long_names() -> None:
    prompt = catalog_prompt([profile("long", "가" * 80, QuantityUnit.GRAM)], "")
    assert prompt is not None and prompt.text.splitlines()[1] == f"long | {'가' * 40} | - | g"


def test_catalog_prompt_cap_keeps_relevant_foods_first_then_id_order() -> None:
    foods = [profile(f"food-{number:03d}", f"음식{number:03d}", QuantityUnit.GRAM) for number in range(130)]
    foods.append(profile("zz-target", "특별한밥", QuantityUnit.PACK))
    prompt = catalog_prompt(foods, "오늘 특별한밥 먹었어")
    assert prompt is not None
    assert (prompt.shown, prompt.total) == (CATALOG_MAX_FOODS, 131)
    lines = prompt.text.splitlines()[1:]
    assert len(lines) == CATALOG_MAX_FOODS
    assert any(line.startswith("zz-target ") for line in lines)
    ids = [line.split(" | ")[0] for line in lines]
    assert ids == sorted(ids)
    assert ids[-2] == "food-118" and ids[0] == "food-000"
    assert catalog_prompt(foods, "오늘 특별한밥 먹었어") == prompt  # deterministic


def test_catalog_prompt_character_cap() -> None:
    foods = [
        profile(
            f"food-{number:03d}", "가" * 40, QuantityUnit.GRAM, aliases=tuple(f"{letter}" * 40 for letter in "나다라")
        )
        for number in range(60)
    ]
    prompt = catalog_prompt(foods, "")
    assert prompt is not None
    assert len(prompt.text) <= CATALOG_MAX_CHARS and prompt.shown < 60 and prompt.total == 60


def test_list_all_reader_is_read_only_and_ordered(tmp_path: Path) -> None:
    database = tmp_path / "db" / "muscle50.sqlite3"
    reader = SqliteFoodCatalogReader(database)
    assert reader.list_all() == ()
    assert not (tmp_path / "db").exists()
    repository = SqliteFoodNutritionRepository(database)
    repository.migrate()
    connection = sqlite3.connect(database)
    connection.execute("INSERT INTO nutrition_food_profiles (profile_id, name) VALUES ('rice', '햇반')")
    connection.execute("INSERT INTO nutrition_food_profiles (profile_id, name) VALUES ('apple', '사과')")
    connection.commit()
    connection.close()
    assert [found.profile_id for found in reader.list_all()] == ["apple", "rice"]
    old = tmp_path / "old.sqlite3"
    sqlite3.connect(old).close()
    assert SqliteFoodCatalogReader(old).list_all() == ()


# --- estimate provenance ---------------------------------------------------------------------------------------


BASE = "telegram-llm text (claude haiku)"


def test_reference_without_a_note_is_the_base() -> None:
    assert estimate_reference(BASE, None, None) == BASE
    assert estimate_reference(BASE, "", "") == BASE


def test_reference_carries_source_assumption_and_marker() -> None:
    assert (
        estimate_reference(BASE, "namu.wiki", "일반 미역국으로 추정")
        == f"{BASE}; 출처: namu.wiki; 가정: 일반 미역국으로 추정"
    )
    assert estimate_reference(BASE, None, "가정만") == f"{BASE}; 가정: 가정만"
    assert estimate_reference(BASE, None, None, check_needed=True) == f"{BASE}; 값 확인 필요"
    assert estimate_reference(BASE, "a", "b", check_needed=True) == f"{BASE}; 값 확인 필요; 출처: a; 가정: b"


def test_reference_is_clipped_by_cutting_the_note() -> None:
    long = estimate_reference(BASE, "s" * 30, "가" * 80)
    assert len(long) == ESTIMATE_REFERENCE_MAX and long.startswith(f"{BASE}; 출처: ")
    marked = estimate_reference(BASE, "s" * 30, "가" * 80, check_needed=True)
    assert len(marked) <= ESTIMATE_REFERENCE_MAX and marked.startswith(f"{BASE}; 값 확인 필요; 출처: ")


def test_reference_drops_a_note_with_less_than_ten_characters_of_room() -> None:
    kept = estimate_reference("x" * 85, "namu.wiki", "가정")
    assert kept.startswith("x" * 85 + "; ") and len(kept) == ESTIMATE_REFERENCE_MAX  # 13 characters of room: kept, cut
    base = "x" * 90
    assert estimate_reference(base, "namu.wiki", "가정") == base  # 8 characters of room: dropped
    assert len(estimate_reference("x" * 95, "namu.wiki", None)) <= ESTIMATE_REFERENCE_MAX


def test_a_long_model_name_still_fits_the_limit() -> None:
    base = f"telegram-llm text (claude {'m' * 64})"
    assert len(base) > ESTIMATE_REFERENCE_MAX - 10
    for marked in (False, True):
        reference = estimate_reference(base, "namu.wiki", "가정", check_needed=marked)
        assert len(reference) <= ESTIMATE_REFERENCE_MAX
    huge = estimate_reference("m" * 200, None, None, check_needed=True)
    assert len(huge) == ESTIMATE_REFERENCE_MAX and huge.endswith("; 값 확인 필요")
