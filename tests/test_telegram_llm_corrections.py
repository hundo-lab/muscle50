"""Telegram LLM v2.3 pure code: the schema and parser keys, label values, assumed portions, the dish name in the memo,
the estimate reference, and (further down) the matching and overlap rules. No I/O."""

from __future__ import annotations

import copy
import json
from decimal import Decimal
from importlib.resources import files
from typing import Any

import pytest
from test_telegram_llm_domain import NULL_ESTIMATE, interpretation

from muscle50.domain.nutrition import MealType, NutrientField
from muscle50.domain.telegram_llm import (
    EditAction,
    Intent,
    LlmOutputError,
    Portion,
    Refers,
    parse_interpretation,
)
from muscle50.domain.telegram_llm_check import CheckCode, check_estimate
from muscle50.domain.telegram_llm_meals import (
    CHECK_NEEDED_NOTE,
    ESTIMATE_REFERENCE_MAX,
    dish_memo,
    estimate_reference,
    is_label_estimate,
    portions_reference,
    portions_text,
)

KCAL, PROTEIN = NutrientField.CALORIES_KCAL, NutrientField.PROTEIN_G
CARBS, FAT = NutrientField.CARBOHYDRATE_G, NutrientField.FAT_G
LABEL = ((KCAL, Decimal(185), Decimal(185)), (PROTEIN, Decimal(5), Decimal(5)), (CARBS, Decimal(37), Decimal(37)))


def schema() -> dict[str, Any]:
    text = files("muscle50").joinpath("schemas", "telegram_llm_interpret_v1.schema.json").read_text("utf-8")
    document: dict[str, Any] = json.loads(text)
    return document


def broken(path: tuple[Any, ...], value: Any) -> dict[str, Any]:
    document = copy.deepcopy(interpretation())
    target: Any = document
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    return document


# --- schema and parser keys ----------------------------------------------------------------------------------


def test_the_schema_and_the_parser_have_the_same_keys_at_every_level() -> None:
    root = schema()
    document = interpretation()
    assert set(root["required"]) == set(root["properties"]) == set(document) and len(document) == 12
    item = root["properties"]["items"]["items"]
    assert set(item["required"]) == set(item["properties"]) == set(document["items"][0]) and len(item["required"]) == 14
    edit = root["properties"]["edit"]
    assert set(edit["required"]) == set(edit["properties"]) == set(document["edit"]) and len(edit["required"]) == 10
    # Codex strict mode: every nested object lists all its keys as required and forbids extra ones
    portion = item["properties"]["portions"]["items"]
    assert portion["additionalProperties"] is False and set(portion["required"]) == set(portion["properties"])
    estimate = edit["properties"]["estimate"]
    assert estimate["additionalProperties"] is False and set(estimate["required"]) == set(estimate["properties"])
    assert set(estimate["properties"]) == set(NULL_ESTIMATE)
    assert all(estimate["properties"][name]["type"] == ["number", "null"] for name in estimate["properties"])
    assert item["properties"]["menu_ref"]["type"] == ["integer", "null"]
    assert edit["properties"]["target_meal_ordinal"]["type"] == ["integer", "null"]
    assert "change_estimate" in edit["properties"]["action"]["enum"]
    assert root["properties"]["refers_to"]["enum"] == ["open_proposal", "last_recorded", None]
    assert "sync_request" not in root["properties"]["intent"]["enum"]  # that is v2.4
    assert "$schema" not in root


def test_a_label_item_with_portions_and_a_menu_ref_parses() -> None:
    document = interpretation()
    document["items"][0].update(
        {"from_label": True, "menu_ref": 2, "portions": [{"name": "닭", "g_min": 150, "g_max": 200.04}]}
    )
    item = parse_interpretation(document).items[0]
    assert item.from_label is True and item.menu_ref == 2
    assert item.portions == (Portion("닭", Decimal(150), Decimal(200)),)


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("items", 0, "from_label"), "true"),
        (("items", 0, "from_label"), 1),
        (("items", 0, "menu_ref"), True),
        (("items", 0, "menu_ref"), 1.5),
        (("items", 0, "menu_ref"), "1"),
        (("items", 0, "portions"), [{"name": "닭", "g_min": 150}]),
        (("items", 0, "portions"), [{"name": "닭", "g_min": 200, "g_max": 150}]),
        (("items", 0, "portions"), [{"name": "닭", "g_min": -1, "g_max": 150}]),
        (("items", 0, "portions"), [{"name": "닭", "g_min": 1, "g_max": 3001}]),
        (("items", 0, "portions"), [{"name": "", "g_min": 1, "g_max": 2}]),
        (("items", 0, "portions"), [{"name": "x" * 21, "g_min": 1, "g_max": 2}]),
        (("items", 0, "portions"), [{"name": "http://x", "g_min": 1, "g_max": 2}]),
        (("items", 0, "portions"), [{"name": "닭", "g_min": None, "g_max": 2}]),
        (("items", 0, "portions"), [{"name": "닭", "g_min": 1, "g_max": 2, "x": 1}]),
        (("items", 0, "portions"), [{"name": "닭", "g_min": 1, "g_max": 2}] * 5),
        (("refers_to",), "somewhere"),
        (("edit", "from_label"), "yes"),
        (("edit", "target_meal_ordinal"), 0),
        (("edit", "target_meal_ordinal"), 10),
        (("edit", "target_meal_ordinal"), True),
        (("edit", "target_meal_ordinal"), 1.0),
        (("edit", "new_memo"), "x" * 61),
        (("edit", "estimate", "fat_min"), 2),  # min without max
    ],
)
def test_the_new_keys_are_bounded(path: tuple[Any, ...], value: Any) -> None:
    with pytest.raises(LlmOutputError):
        parse_interpretation(broken(path, value))


def test_the_edit_fields_and_refers_to_parse() -> None:
    document = interpretation(intent="meal_edit", refers_to="last_recorded", meal_type="breakfast")
    document["edit"].update(
        {
            "action": "change_estimate",
            "target_food_text": "삼각김밥",
            "new_memo": "참치마요 삼각김밥",
            "estimate": {**NULL_ESTIMATE, "fat_min": 2, "fat_max": 2},
            "from_label": True,
            "target_meal_ordinal": 1,
        }
    )
    parsed = parse_interpretation(document)
    assert parsed.refers_to is Refers.LAST_RECORDED and parsed.intent is Intent.MEAL_EDIT
    edit = parsed.edit
    assert edit.action is EditAction.CHANGE_ESTIMATE and edit.new_memo == "참치마요 삼각김밥"
    assert edit.estimate == ((FAT, Decimal(2), Decimal(2)),) and edit.from_label is True and edit.ordinal == 1
    assert parsed.meal_type is MealType.BREAKFAST


@pytest.mark.parametrize(
    "overrides",
    [
        {"intent": "meal_edit", "refers_to": "open_proposal"},
        {"intent": "meal_log", "refers_to": "last_recorded"},
        {"intent": "question", "refers_to": "last_recorded"},
    ],
)
def test_a_refers_to_that_does_not_fit_the_intent_is_bad_output(overrides: dict[str, Any]) -> None:
    with pytest.raises(LlmOutputError):
        parse_interpretation(interpretation(**overrides))


def test_change_estimate_needs_an_estimate_or_a_new_memo() -> None:
    document = interpretation(intent="meal_edit", refers_to="last_recorded")
    document["edit"]["action"] = "change_estimate"
    with pytest.raises(LlmOutputError):
        parse_interpretation(document)
    document["edit"]["new_memo"] = "새 메모"
    assert parse_interpretation(document).edit.new_memo == "새 메모"


# --- label values --------------------------------------------------------------------------------------------


def test_is_label_estimate_needs_the_flag_and_only_single_values() -> None:
    assert is_label_estimate(LABEL, True)
    assert not is_label_estimate(LABEL, False)
    assert not is_label_estimate((), True)
    mixed = ((KCAL, Decimal(185), Decimal(185)), (PROTEIN, Decimal(5), Decimal(8)))
    assert not is_label_estimate(mixed, True)  # a real range is an ordinary estimate


def codes(ranges: Any, *, label: bool = False, **more: Any) -> list[CheckCode]:
    more.setdefault("assumption", None)
    more.setdefault("quantity", None)
    return [failure.code for failure in check_estimate(ranges, label=label, **more)]


def test_a_label_skips_only_the_single_value_check() -> None:
    assert codes(LABEL) == [CheckCode.RANGE_IS_A_POINT, CheckCode.RANGE_IS_A_POINT]
    assert codes(LABEL, label=True) == []  # 185 kcal, P5, C37 and no fat: 4*5 + 4*37 = 168 is within the tolerance
    full = (*LABEL, (FAT, Decimal(2), Decimal(2)))
    assert codes(full, label=True) == []  # 20 + 148 + 18 = 186 against 185
    # every other check still runs on a label
    wrong_sum = (
        (KCAL, Decimal(500), Decimal(500)),
        (PROTEIN, Decimal(5), Decimal(5)),
        (CARBS, Decimal(37), Decimal(37)),
    )
    assert codes((*wrong_sum, (FAT, Decimal(2), Decimal(2))), label=True) == [CheckCode.MACROS_VS_KCAL]
    too_much = ((KCAL, Decimal(100), Decimal(100)), (PROTEIN, Decimal(40), Decimal(40)))
    assert codes(too_much, label=True) == [CheckCode.MACROS_EXCEED_KCAL]
    wide = ((KCAL, Decimal(100), Decimal(900)), (PROTEIN, Decimal(5), Decimal(5)))
    assert codes(wide, label=True) == [CheckCode.RANGE_TOO_WIDE]
    assert codes(LABEL, label=True, assumption="약 77개로 가정", quantity=None) == [CheckCode.ASSUMPTION_NUMBER]


def test_portion_numbers_are_allowed_in_the_assumption() -> None:
    ranges = ((KCAL, Decimal(400), Decimal(600)), (PROTEIN, Decimal(30), Decimal(45)))
    portions = (Portion("닭", Decimal(150), Decimal(200)),)
    assert codes(ranges, assumption="닭 150 g 기준", portions=portions) == []
    assert codes(ranges, assumption="닭 150 g 기준") == [CheckCode.ASSUMPTION_NUMBER]


# --- estimate reference --------------------------------------------------------------------------------------


BASE = "telegram-llm photo sha256:1a2b3c4d5e6f (claude sonnet)"


def test_the_reference_without_a_label_or_portions_is_the_v22_text() -> None:
    assert estimate_reference(BASE, None, None) == BASE
    assert estimate_reference(BASE, "namu.wiki", "가정 문장", check_needed=True) == (
        f"{BASE}; {CHECK_NEEDED_NOTE}; 출처: namu.wiki; 가정: 가정 문장"
    )


def test_the_reference_orders_label_check_portions_source_assumption() -> None:
    portions = (Portion("닭", Decimal(150), Decimal(200)), Portion("감자", Decimal(100), Decimal(150)))
    text = estimate_reference(BASE, "namu.wiki", "가정", check_needed=True, label=True, portions=portions)
    assert text == f"{BASE}; 라벨; 값 확인 필요; 양: 닭 150-200g, 감자 100-150g; 출처: namu.wiki; 가정: 가정"[:100]
    assert len(text) <= ESTIMATE_REFERENCE_MAX


def test_the_note_is_cut_first_and_the_markers_are_kept() -> None:
    portions = tuple(Portion(f"재료{n}", Decimal(100), Decimal(150)) for n in range(4))
    text = estimate_reference(BASE, "namu.wiki", "가정 문장", check_needed=True, label=True, portions=portions)
    assert len(text) <= ESTIMATE_REFERENCE_MAX
    assert text.startswith(f"{BASE}; 라벨; 값 확인 필요; 양: 재료0 100-150g, 재료1")
    assert "출처" not in text  # cut from the end of the note
    long_base = "x" * 98
    cut = estimate_reference(long_base, None, None, label=True)
    assert len(cut) <= ESTIMATE_REFERENCE_MAX and cut.endswith("; 라벨")


def test_portions_are_written_in_grams() -> None:
    portions = (Portion("닭", Decimal(150), Decimal(200)), Portion("밥", Decimal("100.5"), Decimal("100.5")))
    assert portions_reference(portions) == "닭 150-200g, 밥 100.5-100.5g"
    assert portions_text(portions) == "닭 150~200 g, 밥 100.5 g"


# --- the dish name stays in the memo -------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("food_text", "memo", "expected"),
    [
        ("안동찜닭 닭 및 감자 위주", "닭 및 감자 위주", "안동찜닭 닭 및 감자 위주"),
        ("김밥 2.5줄", "김밥 2.5줄", "김밥 2.5줄"),
        ("오뎅국 1그릇", None, "오뎅국 1그릇"),
        ("닭 및 감자", "감자 위주", "감자 위주"),  # a one-character first word is not enough to test
        ("Chicken Bowl", "bowl of rice", "Chicken bowl of rice"),
        ("ＫＩＭＢＡＰ 한 줄", "kimbap 한 줄", "kimbap 한 줄"),  # NFKC and case are ignored
    ],
)
def test_dish_memo_starts_from_the_users_dish_name(food_text: str, memo: str | None, expected: str) -> None:
    assert dish_memo(food_text, memo) == expected
