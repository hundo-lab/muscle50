"""Telegram LLM v2.3 pure code: the schema and parser keys, label values, assumed portions, the dish name in the memo,
the estimate reference, and (further down) the matching and overlap rules. No I/O."""

from __future__ import annotations

import copy
import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from importlib.resources import files
from pathlib import Path
from typing import Any

import pytest
from test_telegram_llm_domain import NULL_ESTIMATE, interpretation

from muscle50.application.nutrition_logging import general_meal_item, parse_general_estimate
from muscle50.domain.nutrition import Meal, MealItem, MealType, NutrientField, QuantityUnit
from muscle50.domain.telegram_llm import (
    EditAction,
    Intent,
    LlmOutputError,
    LlmState,
    MenuChoice,
    Portion,
    Proposal,
    ProposalCommand,
    ProposalKind,
    ProposalState,
    Refers,
    parse_interpretation,
    parse_llm_command,
)
from muscle50.domain.telegram_llm_check import CheckCode, check_estimate
from muscle50.domain.telegram_llm_corrections import (
    Candidate,
    find_overlaps,
    general_ranges,
    match_items,
    menu_block,
    menu_name_matches,
    merge_estimate,
    normalize_memo,
    pick_meals,
    plan_fix,
    recent_meal_ids,
    recent_meals_block,
    recent_menu,
)
from muscle50.domain.telegram_llm_meals import (
    CHECK_NEEDED_NOTE,
    ESTIMATE_REFERENCE_MAX,
    dish_memo,
    estimate_reference,
    is_label_estimate,
    portions_reference,
    portions_text,
)
from muscle50.infrastructure.telegram.llm_state_store import JsonLlmStateStore

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


# --- schema and parser keys ---


def test_the_schema_and_the_parser_have_the_same_keys_at_every_level() -> None:
    root = schema()
    document = interpretation()
    assert set(root["required"]) == set(root["properties"]) == set(document) and len(document) == 12
    item = root["properties"]["items"]["items"]
    assert set(item["required"]) == set(item["properties"]) == set(document["items"][0]) and len(item["required"]) == 15
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
    assert item["properties"]["join_existing"]["type"] == "boolean"  # v2.5: the 15th item key
    assert root["properties"]["question_topics"]["items"]["enum"] == ["training", "nutrition", "body", "bot"]
    assert edit["properties"]["target_meal_ordinal"]["type"] == ["integer", "null"]
    assert "change_estimate" in edit["properties"]["action"]["enum"]
    assert root["properties"]["refers_to"]["enum"] == ["open_proposal", "last_recorded", None]
    assert "sync_request" in root["properties"]["intent"]["enum"]  # v2.4: the only change to the 12 root keys
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


# --- label values ---


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


# --- estimate reference ---


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


# --- the dish name stays in the memo ---


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


# --- the chat's last recorded meals, the meal and the item ---

KST = timezone(timedelta(hours=9))


def entry(
    kind: str, *, chat: int = 111, exit_code: int | None = 0, meal_id: str | None = None, meal_ids: Any = None
) -> Any:
    result: dict[str, Any] | None = None
    if exit_code is not None:
        result = {"exit_code": exit_code, "meal_id": meal_id}
        if meal_ids is not None:
            result["meal_ids"] = meal_ids
    return {"chat_id": chat, "kind": kind, "result": result}


def test_recent_meal_ids_are_newest_first_for_this_chat_and_successful_records_only() -> None:
    entries = [
        entry("confirm", meal_id="2026-10-06-breakfast-1"),
        entry("confirm", chat=222, meal_id="2026-10-06-lunch-1"),  # another chat
        entry("text", meal_id="2026-10-06-lunch-9"),  # not a record
        entry("confirm", exit_code=1, meal_id=None),  # failed
        entry("cancel", exit_code=None),
        entry("plain", meal_id="2026-10-06-lunch-1"),
        entry("confirm", meal_id="x", meal_ids=["2026-10-06-dinner-1", "2026-10-06-snack-1"], exit_code=0),
        entry("edit", meal_id="2026-10-06-breakfast-1"),  # an edit repeats the meal it corrected
    ]
    assert recent_meal_ids(entries, chat_id=111) == (
        "2026-10-06-breakfast-1",
        "2026-10-06-snack-1",
        "2026-10-06-dinner-1",
        "2026-10-06-lunch-1",
    )
    assert recent_meal_ids([], chat_id=111) == ()
    assert recent_meal_ids([entry("fix", meal_id="2026-10-06-lunch-1")], chat_id=111) == ()


def make_meal(meal_id: str, meal_type: MealType, *items: MealItem) -> Meal:
    return Meal(meal_id, datetime(2026, 10, 6, 8, 0, tzinfo=KST), meal_type, "synthetic", items=items)


def general(meal_id: str, sequence: int, memo: str | None, spec: str | None = None) -> MealItem:
    estimate = parse_general_estimate(spec, None, datetime(2026, 10, 6, 8, 0, tzinfo=KST), label="") if spec else None
    return general_meal_item(meal_id, sequence, memo, label="", estimate=estimate)


def catalog(meal_id: str, sequence: int, food_id: str, name: str) -> MealItem:
    return MealItem(meal_id, sequence, name, Decimal(1), QuantityUnit.PACK, food_profile_id=food_id)


def test_the_nth_meal_follows_the_recording_number_not_the_id_text() -> None:
    numbers = (1, 2, 10)
    day = [
        make_meal(f"2026-10-06-breakfast-{n}", MealType.BREAKFAST, general(f"2026-10-06-breakfast-{n}", 1, "a"))
        for n in numbers
    ]
    # a text sort would put -10 before -2
    shuffled = [day[2], day[0], day[1]]
    assert pick_meals(shuffled, MealType.BREAKFAST, 2)[0].meal_id == "2026-10-06-breakfast-2"
    assert pick_meals(shuffled, MealType.BREAKFAST, 3)[0].meal_id == "2026-10-06-breakfast-10"
    assert pick_meals(shuffled, MealType.BREAKFAST, 4) == ()
    assert len(pick_meals(shuffled, MealType.BREAKFAST, None)) == 3
    assert len(pick_meals(shuffled, None, 1)) == 3  # an ordinal without a type narrows nothing
    assert pick_meals(shuffled, MealType.LUNCH, None) == ()
    only_second = [day[1], day[2]]  # the first breakfast was voided: "1식" is the next active one
    assert pick_meals(only_second, MealType.BREAKFAST, 1)[0].meal_id == "2026-10-06-breakfast-2"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (" 깻잎닭갈비 삼각김밥, 1개! ", "깻잎닭갈비삼각김밥1개"),
        ("ＫＩＭＢＡＰ（한 줄）", "kimbap한줄"),
        ("", ""),
        (None, ""),
    ],
)
def test_normalize_memo(text: str | None, expected: str) -> None:
    assert normalize_memo(text) == expected


def test_match_items_prefers_an_exact_memo_then_a_contained_one_and_unions_the_catalog() -> None:
    meal = make_meal(
        "2026-10-06-breakfast-1",
        MealType.BREAKFAST,
        general("2026-10-06-breakfast-1", 1, "삼각김밥"),
        general("2026-10-06-breakfast-1", 2, "참치마요 삼각김밥 1개"),
        catalog("2026-10-06-breakfast-1", 3, "chicken-breast", "닭가슴살"),
        general("2026-10-06-breakfast-1", 4, None),
    )

    def found(food_id: str | None, text: str | None) -> list[int]:
        return [ref.item.sequence for ref in match_items([meal], food_id=food_id, text=text)]

    assert found(None, "삼각 김밥") == [1]  # the exact memo wins over the longer one that merely contains it
    assert found(None, "참치마요") == [2]  # no exact memo: the memo that contains it
    assert found(None, "삼각김밥 1개") == [2]
    assert found(None, "김") == []  # one character is not searched
    assert found("chicken-breast", None) == [3]
    assert found("chicken-breast", "참치마요") == [2, 3]  # the union, in item order
    assert found(None, None) == [] and found(None, "존재하지않음") == []
    assert found("general-meal", None) == []  # the reserved profile is never a catalog match


def test_merge_estimate_replaces_only_the_named_nutrients() -> None:
    current = ((KCAL, Decimal(180), Decimal(200)), (PROTEIN, Decimal(5), Decimal(6)))
    merged = merge_estimate(current, ((FAT, Decimal(2), Decimal(2)), (KCAL, Decimal(185), Decimal(185))))
    assert merged == (
        (KCAL, Decimal(185), Decimal(185)),
        (PROTEIN, Decimal(5), Decimal(6)),
        (FAT, Decimal(2), Decimal(2)),
    )
    assert merge_estimate((), ((FAT, Decimal(2), Decimal(2)),)) == (
        (FAT, Decimal(2), Decimal(2)),
    )  # carbs stay unknown
    assert merge_estimate(current, ()) == current


def test_the_stored_estimate_is_read_back_as_ranges_and_the_blocks_are_deterministic() -> None:
    meal_id = "2026-10-06-breakfast-1"
    item = general(meal_id, 1, "삼각김밥", "visual_estimate:kcal=185-185,protein=5-5,carbs=37-37")
    assert general_ranges(item) == LABEL
    assert general_ranges(general(meal_id, 2, "모름")) == ()
    meal = make_meal(meal_id, MealType.BREAKFAST, item, catalog(meal_id, 3, "chicken-breast", "닭가슴살"))
    block = recent_meals_block([meal])
    assert block == (
        "2026-10-06-breakfast-1 | 아침\n"
        "1. 일반식 (메모: 삼각김밥) | kcal 185, 단백질 5 g, 탄수화물 37 g\n"
        "3. 닭가슴살 (chicken-breast) 1 pack"
    )
    assert recent_meals_block([meal]) == block


# --- overlap with a recorded meal and the one-command fix -------------------------------------------------------------

MEAL_ID = "2026-10-06-breakfast-1"


def recorded() -> Meal:
    return make_meal(
        MEAL_ID,
        MealType.BREAKFAST,
        general(MEAL_ID, 1, "깻잎닭갈비 삼각김밥 1개", "visual_estimate:kcal=185-185,protein=5-5"),
        catalog(MEAL_ID, 2, "chicken-breast", "닭가슴살"),
        general(MEAL_ID, 3, None),
    )


def memo_candidate(
    memo: str | None, ranges: Any = ((KCAL, Decimal(185), Decimal(185)), (PROTEIN, Decimal(5), Decimal(5)))
) -> Candidate:
    return Candidate(None, memo, ranges, None, None)


def food_candidate(food_id: str, quantity: int = 1) -> Candidate:
    return Candidate(food_id, None, (), Decimal(quantity), QuantityUnit.PACK)


def test_overlap_is_a_catalog_food_id_or_an_equal_normalized_memo() -> None:
    meal = recorded()
    found = find_overlaps(
        [meal], [food_candidate("chicken-breast"), memo_candidate("깻잎닭갈비삼각김밥, 1개"), memo_candidate("라면")]
    )
    assert [(overlap.index, overlap.item.sequence) for overlap in found] == [(0, 2), (1, 1)]
    assert find_overlaps([], [food_candidate("chicken-breast")]) == ()


def test_the_general_meal_profile_and_an_empty_memo_never_overlap() -> None:
    meal = recorded()
    # every general item has the reserved food ID: it must not make two different dishes overlap
    assert find_overlaps([meal], [food_candidate("general-meal")]) == ()
    assert find_overlaps([meal], [memo_candidate("전혀 다른 음식")]) == ()
    assert find_overlaps([meal], [memo_candidate(None), memo_candidate(""), memo_candidate("  ")]) == ()
    # the recorded general item without a memo (item 3) is not matched by an empty memo either


def test_a_catalog_candidate_is_not_matched_by_a_general_item_and_a_memo_not_by_a_catalog_item() -> None:
    meal = make_meal(MEAL_ID, MealType.BREAKFAST, catalog(MEAL_ID, 1, "chicken-breast", "닭가슴살"))
    assert find_overlaps([meal], [memo_candidate("닭가슴살")]) == ()


def test_plan_fix_counts_the_commands_needed() -> None:
    meal = recorded()
    same = [food_candidate("chicken-breast"), memo_candidate("깻잎닭갈비 삼각김밥 1개")]
    plan = plan_fix(find_overlaps([meal], same), len(same))
    assert plan is not None and plan.operations == 0  # identical values: already recorded
    changed = [food_candidate("chicken-breast", 2)]
    plan = plan_fix(find_overlaps([meal], changed), 1)
    assert plan is not None and plan.operations == 1 and plan.replacements[0].item.sequence == 2 and not plan.additions
    added = [food_candidate("chicken-breast"), food_candidate("hetbahn-210"), food_candidate("banana")]
    plan = plan_fix(find_overlaps([meal], added), 3)
    assert plan is not None and plan.operations == 1 and plan.additions == (1, 2) and not plan.replacements
    two = [
        food_candidate("chicken-breast", 2),
        memo_candidate("깻잎닭갈비 삼각김밥 1개", ((KCAL, Decimal(190), Decimal(200)),)),
    ]
    plan = plan_fix(find_overlaps([meal], two), 2)
    assert plan is not None and plan.operations == 2
    one_and_one = [food_candidate("chicken-breast", 2), food_candidate("hetbahn-210")]
    plan = plan_fix(find_overlaps([meal], one_and_one), 2)
    assert plan is not None and plan.operations == 2  # a replace and an add


def test_a_proposal_without_values_never_replaces_recorded_values() -> None:
    meal = recorded()
    plan = plan_fix(find_overlaps([meal], [memo_candidate("깻잎닭갈비 삼각김밥 1개", ())]), 1)
    assert plan is not None and plan.operations == 0


def test_overlaps_in_several_recorded_meals_have_no_single_fix() -> None:
    other = make_meal(
        "2026-10-06-breakfast-2", MealType.BREAKFAST, catalog("2026-10-06-breakfast-2", 1, "banana", "바나나")
    )
    candidates = [food_candidate("chicken-breast", 2), food_candidate("banana", 3)]
    overlaps = find_overlaps([recorded(), other], candidates)
    assert len(overlaps) == 2 and plan_fix(overlaps, 2) is None


# --- the command and the state file ---


def test_fix_is_a_proposal_command_like_ok_and_no() -> None:
    assert parse_llm_command("/fix_91c0", bot_username="bot") == ProposalCommand("fix", "91c0")
    assert parse_llm_command("/fix_91c0@Bot", bot_username="bot") == ProposalCommand("fix", "91c0")
    assert parse_llm_command("/fix_91c0 extra", bot_username="bot") is None
    assert parse_llm_command("/fix_xyz1", bot_username="bot") is None


def test_the_state_file_keeps_outline_and_fix_and_loads_files_without_them(tmp_path: Path) -> None:
    store = JsonLlmStateStore(tmp_path / "state.json")
    proposal = Proposal(
        "91c0",
        1,
        ProposalKind.MEAL,
        10,
        20,
        ProposalState.OPEN,
        argv_ok=("nutrition", "log"),
        outline=("1. 일반식 (메모: 삼각김밥) | 추정: kcal 180~200",),
        fix_argv=("nutrition", "meal", "add-item", "2026-10-06-breakfast-1"),
        fix_change="아침 추가",
    )
    store.save(LlmState(None, (proposal,)))
    assert store.load().proposals[0] == proposal
    document = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))
    for key in ("outline", "fix_argv", "fix_change"):
        del document["proposals"][0][key]  # a file written by v2.2
    (tmp_path / "state.json").write_text(json.dumps(document), encoding="utf-8", newline="\n")
    old = store.load().proposals[0]
    assert (old.outline, old.fix_argv, old.fix_change) == ((), (), "")


# --- a recent menu, picked by name ---


def menu_proposal(token: str, created: int, state: ProposalState = ProposalState.OPEN, chat: int = 111) -> Proposal:
    choices = (MenuChoice("한식 얼큰순살감자탕", ((KCAL, Decimal(1022), Decimal(1022)),), True),)
    return Proposal(
        token, chat, ProposalKind.MENU, created, created + 3600, state, choices=choices, label="메뉴 캡처 추정"
    )


def test_recent_menu_is_the_newest_open_or_used_menu_of_the_chat_within_four_hours() -> None:
    now = 100_000
    four_hours = 4 * 3600
    proposals = [
        menu_proposal("0001", now - 100),
        menu_proposal("0002", now - 50, ProposalState.USED),
        menu_proposal("0003", now - 10, ProposalState.CANCELLED),
        menu_proposal("0004", now - 5, chat=222),
        Proposal("0005", 111, ProposalKind.MEAL, now - 1, now + 3000, ProposalState.OPEN),
    ]
    found = recent_menu(proposals, chat_id=111, now_unix=now)
    assert found is not None and found.token == "0002"  # newest open-or-used; cancelled, other chat, meal ignored
    assert recent_menu([menu_proposal("0006", now - four_hours)], chat_id=111, now_unix=now) is not None  # edge
    assert recent_menu([menu_proposal("0007", now - four_hours - 1)], chat_id=111, now_unix=now) is None
    assert recent_menu([menu_proposal("0008", now + 5)], chat_id=111, now_unix=now) is None  # not from the future
    assert recent_menu([], chat_id=111, now_unix=now) is None


def test_menu_block_lists_the_choices_in_the_order_the_user_saw_them() -> None:
    assert menu_block(menu_proposal("0001", 10)) == (
        "/eat_0001 끼니 미정 (메뉴 캡처 추정)\n1. 한식 얼큰순살감자탕 | kcal 1022 (메뉴판 표기 포함)"
    )
    assert menu_block(menu_proposal("0001", 10)) == menu_block(menu_proposal("0001", 10))


@pytest.mark.parametrize(
    ("words", "name", "matches"),
    [
        ("얼큰순살감자탕", "한식 얼큰순살감자탕", True),
        ("한식 얼큰순살감자탕 큰 거", "한식 얼큰순살감자탕", True),
        ("된장찌개", "한식 얼큰순살감자탕", False),
        ("감", "감자탕", False),  # one character is not a name
        ("", "김밥", False),
    ],
)
def test_menu_name_matching_is_plain_containment(words: str, name: str, matches: bool) -> None:
    assert menu_name_matches(words, name) is matches
