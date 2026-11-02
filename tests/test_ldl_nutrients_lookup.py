"""LDL Nutrients B (ldl-nutrients-lookup): saturated fat and fiber ranges in the Telegram interpret item estimate.

Pure tests: the schema, the parser, the `satfat_exceeds_fat` check, the proposal line, the label rule (D8), the
prompt sentences and the history code. Synthetic values only; nothing here is a real food's nutrition.
"""

from __future__ import annotations

import copy
import json
from decimal import Decimal
from importlib.resources import files
from pathlib import Path
from typing import Any

import pytest
from test_telegram_llm_domain import ITEM_ESTIMATE, NULL_EDIT, NULL_ESTIMATE, NULL_LDL_ESTIMATE, interpretation

from muscle50.domain.nutrition import NutrientField, OptionalNutrient
from muscle50.domain.telegram_llm import (
    RECHECK_CODES,
    LlmOutputError,
    check_history_entry,
    history_entry,
    parse_interpretation,
    parse_suggestions,
)
from muscle50.domain.telegram_llm_check import (
    CHECK_REASON_TEXTS,
    CheckCode,
    CheckFailure,
    check_estimate,
    recheck_note,
    satfat_over_fat,
)
from muscle50.domain.telegram_llm_corrections import optional_summary
from muscle50.domain.telegram_llm_meals import is_label_estimate
from muscle50.domain.telegram_llm_prompt import (
    FIXED_RULE_LINES,
    FIXED_RULES,
    TASKS,
    PromptTask,
    fixed_rules_web,
)
from muscle50.infrastructure.telegram.history_log import JsonlHistoryLog

KCAL, PROTEIN, CARBS, FAT = (
    NutrientField.CALORIES_KCAL,
    NutrientField.PROTEIN_G,
    NutrientField.CARBOHYDRATE_G,
    NutrientField.FAT_G,
)
SATFAT, FIBER = OptionalNutrient.SATURATED_FAT_G, OptionalNutrient.FIBER_G
LDL_KEYS = ["satfat_min", "satfat_max", "fiber_min", "fiber_max"]


def _schema(name: str) -> dict[str, Any]:
    document: dict[str, Any] = json.loads(files("muscle50").joinpath("schemas", name).read_text("utf-8"))
    return document


def _with_item_estimate(**values: Any) -> dict[str, Any]:
    document = copy.deepcopy(interpretation())
    document["items"][0]["estimate"].update(values)
    return document


def _d(text: str) -> Decimal:
    return Decimal(text)


# --- AC1: the schema ---------------------------------------------------------------------------------------------


def test_the_item_estimate_has_twelve_required_keys_with_the_four_nullable_ones_after_fat() -> None:
    schema = _schema("telegram_llm_interpret_v1.schema.json")
    estimate = schema["properties"]["items"]["items"]["properties"]["estimate"]
    assert estimate["required"] == [
        *("kcal_min", "kcal_max", "protein_min", "protein_max", "carbs_min", "carbs_max", "fat_min", "fat_max"),
        *LDL_KEYS,
    ]
    assert list(estimate["properties"]) == estimate["required"]
    assert estimate["additionalProperties"] is False
    for name in LDL_KEYS:
        assert estimate["properties"][name] == {"type": ["number", "null"]}
    assert "satfat" in estimate["description"] and "never 0" in estimate["description"]
    assert set(ITEM_ESTIMATE) == set(estimate["required"])


def test_the_edit_menu_and_suggest_estimates_keep_eight_keys() -> None:
    interpret = _schema("telegram_llm_interpret_v1.schema.json")
    edit = interpret["properties"]["edit"]["properties"]["estimate"]
    menu = interpret["properties"]["menu"]["properties"]["items"]["items"]["properties"]["estimate"]
    suggest = _schema("telegram_llm_suggest_v1.schema.json")["properties"]["suggestions"]["items"]["properties"]
    for estimate in (edit, menu, suggest["estimate"]):
        assert set(estimate["required"]) == set(estimate["properties"]) == set(NULL_ESTIMATE)


def test_the_schema_file_is_the_canonical_json_dump() -> None:
    text = files("muscle50").joinpath("schemas", "telegram_llm_interpret_v1.schema.json").read_text("utf-8")
    assert json.dumps(json.loads(text), indent=2, ensure_ascii=False) + "\n" == text


# --- AC1: the parser ---------------------------------------------------------------------------------------------


def test_null_pairs_give_no_optional_ranges() -> None:
    item = parse_interpretation(interpretation()).items[0]
    assert item.optional_ranges == ()
    assert item.estimate == ((KCAL, Decimal(300), Decimal(400)), (PROTEIN, Decimal(10), Decimal(20)))


def test_ranges_are_rounded_to_a_tenth_and_kept_in_nutrient_order() -> None:
    document = _with_item_estimate(satfat_min=8.04, satfat_max=14, fiber_min=4.25, fiber_max=8.0)
    assert parse_interpretation(document).items[0].optional_ranges == (
        (SATFAT, Decimal(8), Decimal(14)),
        (FIBER, _d("4.2"), Decimal(8)),
    )


def test_a_single_value_and_zero_are_accepted() -> None:
    document = _with_item_estimate(satfat_min=0.5, satfat_max=0.5, fiber_min=0, fiber_max=0)
    assert parse_interpretation(document).items[0].optional_ranges == (
        (SATFAT, _d("0.5"), _d("0.5")),
        (FIBER, Decimal(0), Decimal(0)),
    )


def test_only_one_of_the_two_may_be_given() -> None:
    document = _with_item_estimate(fiber_min=3, fiber_max=5)
    assert parse_interpretation(document).items[0].optional_ranges == ((FIBER, Decimal(3), Decimal(5)),)


@pytest.mark.parametrize(
    ("values", "message"),
    [
        ({"satfat_min": 3}, r"items\[1\]\.estimate\.satfat needs both min and max or neither"),
        ({"fiber_max": 3}, r"items\[1\]\.estimate\.fiber needs both min and max or neither"),
        ({"satfat_min": 9, "satfat_max": 8}, r"items\[1\]\.estimate\.satfat_min is above satfat_max"),
        ({"fiber_min": -1, "fiber_max": 2}, r"items\[1\]\.estimate\.fiber_min is outside 0-300"),
        ({"satfat_min": 10, "satfat_max": 300.1}, r"items\[1\]\.estimate\.satfat_max is outside 0-300"),
        ({"satfat_min": "3", "satfat_max": 4}, r"items\[1\]\.estimate\.satfat_min must be a number"),
    ],
)
def test_broken_optional_ranges_are_a_format_failure(values: dict[str, Any], message: str) -> None:
    with pytest.raises(LlmOutputError, match=message):
        parse_interpretation(_with_item_estimate(**values))


def test_an_item_estimate_needs_exactly_twelve_keys() -> None:
    eight = copy.deepcopy(interpretation())
    for key in LDL_KEYS:
        del eight["items"][0]["estimate"][key]
    with pytest.raises(LlmOutputError, match=r"items\[1\]\.estimate must have exactly the schema keys"):
        parse_interpretation(eight)
    thirteen = _with_item_estimate(cholesterol_mg=None)
    with pytest.raises(LlmOutputError, match=r"items\[1\]\.estimate must have exactly the schema keys"):
        parse_interpretation(thirteen)


def test_edit_menu_and_suggestion_estimates_refuse_twelve_keys() -> None:
    edit = {**NULL_EDIT, "estimate": {**NULL_ESTIMATE, **NULL_LDL_ESTIMATE}}
    with pytest.raises(LlmOutputError, match=r"edit\.estimate must have exactly the schema keys"):
        parse_interpretation(interpretation(edit=edit))
    menu_item = {
        "slot": "lunch",
        "corner": None,
        "name": "SynMenu",
        "printed_kcal": None,
        "printed_protein_g": None,
        "estimate": {**NULL_ESTIMATE, **NULL_LDL_ESTIMATE},
    }
    menu = {"slots_visible": ["lunch"], "items": [menu_item]}
    with pytest.raises(LlmOutputError, match=r"menu\.items\[1\]\.estimate must have exactly the schema keys"):
        parse_interpretation(interpretation(intent="menu", photo_kind="menu_capture", items=[], menu=menu))
    suggestion = {
        "name": "SynBowl",
        "category": "delivery",
        "description": "",
        "estimate": {**NULL_ESTIMATE, **NULL_LDL_ESTIMATE},
        "note": "",
    }
    with pytest.raises(LlmOutputError, match=r"suggestions\[1\]\.estimate must have exactly the schema keys"):
        parse_suggestions({"lead": "", "suggestions": [suggestion], "memory_summary": ""})


# --- AC5: the satfat_exceeds_fat check (rule 6) ------------------------------------------------------------------

BASE = ((KCAL, Decimal(800), Decimal(1000)), (PROTEIN, Decimal(20), Decimal(30)), (FAT, Decimal(10), Decimal(15)))


def test_saturated_fat_above_fat_fails_last_with_the_computed_numbers() -> None:
    wide = ((KCAL, Decimal(100), Decimal(900)), (PROTEIN, Decimal(20), Decimal(30)), (FAT, Decimal(10), Decimal(15)))
    failures = check_estimate(wide, assumption=None, quantity=None, optional=((SATFAT, Decimal(18), Decimal(25)),))
    assert [failure.code for failure in failures] == [CheckCode.RANGE_TOO_WIDE, CheckCode.SATFAT_EXCEEDS_FAT]
    assert failures[-1] == CheckFailure(CheckCode.SATFAT_EXCEEDS_FAT, "fat 10-15, satfat 18-25")
    assert CHECK_REASON_TEXTS[CheckCode.SATFAT_EXCEEDS_FAT] == "포화지방이 지방보다 큼"
    assert CheckCode.SATFAT_EXCEEDS_FAT.value == "satfat_exceeds_fat"


@pytest.mark.parametrize(
    ("satfat", "fails"),
    [
        ((Decimal(15), Decimal(15)), False),  # equal to the fat maximum: the CLI accepts it
        ((Decimal(12), Decimal(20)), False),  # only the maximum is above fat: not a provable excess
        ((_d("15.1"), Decimal(20)), True),
    ],
)
def test_the_comparison_is_the_clis_lowest_satfat_against_highest_fat(
    satfat: tuple[Decimal, Decimal], fails: bool
) -> None:
    optional = ((SATFAT, *satfat),)
    assert satfat_over_fat(BASE, optional) is fails
    codes = [failure.code for failure in check_estimate(BASE, assumption=None, quantity=None, optional=optional)]
    assert (CheckCode.SATFAT_EXCEEDS_FAT in codes) is fails


def test_without_a_fat_range_saturated_fat_is_not_compared() -> None:
    no_fat = BASE[:2]
    optional = ((SATFAT, Decimal(50), Decimal(60)),)
    assert satfat_over_fat(no_fat, optional) is False
    assert check_estimate(no_fat, assumption=None, quantity=None, optional=optional) == ()


def test_single_values_and_fiber_get_no_width_point_or_carb_checks() -> None:
    low_carbs = (*BASE[:2], (CARBS, Decimal(1), Decimal(2)), BASE[2])
    optional = ((SATFAT, Decimal(3), Decimal(3)), (FIBER, Decimal(40), Decimal(40)))
    plain = check_estimate(low_carbs, assumption=None, quantity=None)
    assert check_estimate(low_carbs, assumption=None, quantity=None, optional=optional) == plain
    assert check_estimate(BASE, assumption=None, quantity=None, optional=((FIBER, Decimal(0), Decimal(90)),)) == ()


def test_the_recheck_note_line_of_the_new_code() -> None:
    failure = CheckFailure(CheckCode.SATFAT_EXCEEDS_FAT, "fat 10-15, satfat 18-25")
    assert recheck_note([(3, failure)]).split("\n")[1] == "- items[3]: satfat_exceeds_fat (fat 10-15, satfat 18-25)"


# --- AC8: the proposal line (rule 9, Q3) -------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("optional", "label", "dropped", "line"),
    [
        (
            ((SATFAT, Decimal(8), Decimal(14)), (FIBER, Decimal(4), Decimal(8))),
            False,
            False,
            "포화지방 8~14 g · 섬유 4~8 g (추정, 정확도 미확인)",
        ),
        (((SATFAT, Decimal(14), Decimal(20)),), False, False, "포화지방 14~20 g · 섬유 모름 (추정, 정확도 미확인)"),
        (((FIBER, Decimal(4), Decimal(8)),), False, False, "포화지방 모름 · 섬유 4~8 g (추정, 정확도 미확인)"),
        (((SATFAT, _d("0.5"), _d("0.5")),), True, False, "포화지방 0.5 g · 섬유 모름 (라벨)"),
        (
            ((FIBER, Decimal(3), Decimal(5)),),
            False,
            True,
            "포화지방 모름(지방보다 커서 뺌) · 섬유 3~5 g (추정, 정확도 미확인)",
        ),
        ((), False, True, "포화지방 모름(지방보다 커서 뺌) · 섬유 모름"),
        ((), False, False, None),
        ((), True, False, None),
    ],
)
def test_the_line_shapes(optional: Any, label: bool, dropped: bool, line: str | None) -> None:
    assert optional_summary(optional, label=label, satfat_dropped=dropped) == line


def test_a_zero_is_shown_as_zero_and_not_as_unknown() -> None:
    line = optional_summary(((FIBER, Decimal(0), Decimal(1)),), label=False, satfat_dropped=False)
    assert line == "포화지방 모름 · 섬유 0~1 g (추정, 정확도 미확인)"


# --- AC4 / D8: the label rule ------------------------------------------------------------------------------------

LABEL = ((KCAL, Decimal(185), Decimal(185)), (PROTEIN, Decimal(5), Decimal(5)), (FAT, Decimal(2), Decimal(2)))


def test_a_label_needs_single_saturated_fat_and_fiber_values_too() -> None:
    assert is_label_estimate(LABEL, True) is True
    assert is_label_estimate(LABEL, True, ((SATFAT, _d("0.5"), _d("0.5")),)) is True
    assert is_label_estimate(LABEL, True, ((SATFAT, _d("0.5"), Decimal(1)),)) is False
    assert is_label_estimate(LABEL, True, ((FIBER, Decimal(1), Decimal(2)),)) is False
    assert is_label_estimate(LABEL, False, ((SATFAT, _d("0.5"), _d("0.5")),)) is False


# --- AC11 / D2 / D9: the prompt -----------------------------------------------------------------------------------

INTERPRET_SENTENCES = (
    "estimate의 satfat(포화지방 g)과 fiber(식이섬유 g): 말한 양 기준의 범위를 알 수 있을 때만 적고 모르면 "
    "null입니다(0으로 채우지 않습니다).",
    "포화지방은 총지방의 일부라서 satfat를 적으면 fat도 적고 satfat_min이 fat_max보다 크지 않게 합니다.",
    "라벨(from_label)에 인쇄된 값이면 한 값(min과 max를 같게), 라벨에 없으면 null.",
    "웹 검색으로 찾은 페이지에 포화지방·식이섬유가 있으면 그 값을 쓰되, 라벨이 아니면 한 숫자여도 그 값을 포함하는 "
    "범위로 적습니다.",
    "이미 기록한 식사의 포화지방·식이섬유만 고치는 말은 고칠 수 없으니 edit.action을 null로 둡니다.",
    "사용자가 그 음식을 검색해 달라고 하면('검색해서', '찾아서', '찾아봐') 흔한 음식이어도 true.",
)
WEB_RULE_SENTENCE = "사용자가 검색해 달라고 한 음식은 흔한 음식이어도 검색할 수 있습니다."


def test_the_interpret_task_has_every_new_sentence() -> None:
    task = TASKS[PromptTask.INTERPRET]
    for sentence in INTERPRET_SENTENCES:
        assert sentence in task
    lookup = next(line for line in task.split("\n") if line.startswith("- lookup_wanted:"))
    assert lookup.endswith("흔한 음식이어도 true.")
    estimate_index = next(index for index, line in enumerate(task.split("\n")) if line.startswith("- estimate:"))
    assert task.split("\n")[estimate_index + 1].startswith("- estimate의 satfat")


def test_web_rule_twelve_allows_a_search_the_user_asked_for() -> None:
    web = fixed_rules_web(3)
    rule = next(line for line in web.split("\n") if line.startswith("12. "))
    assert rule.endswith("흔한 음식은 검색하지 않습니다. " + WEB_RULE_SENTENCE)
    assert WEB_RULE_SENTENCE not in FIXED_RULES


def test_the_shared_fixed_rules_and_the_other_tasks_are_unchanged() -> None:
    assert FIXED_RULE_LINES[6] == (
        "6. 영양값을 추정할 때는 항상 범위(min, max)로 적습니다. 영양정보 라벨에 인쇄된 값(from_label)만 한 값으로 "
        "적을 수 있습니다. 모르는 값은 null이고 0으로 채우지 않습니다."
    )
    assert len(FIXED_RULE_LINES) == 11
    for task in (PromptTask.ANSWER, PromptTask.SUGGEST):
        assert "satfat" not in TASKS[task] and "포화지방" not in TASKS[task]
    assert "satfat" not in FIXED_RULES


# --- the history code --------------------------------------------------------------------------------------------


def test_every_check_code_is_a_history_recheck_code() -> None:
    assert {code.value for code in CheckCode} == RECHECK_CODES


def test_a_history_line_with_the_new_code_round_trips(tmp_path: Path) -> None:
    entry = history_entry(
        update_id=1,
        at="2026-11-05T12:00:00+09:00",
        chat_id=111,
        kind="text",
        text="점심 SynPasta",
        recheck={"reasons": ["satfat_exceeds_fat"], "outcome": "still_inconsistent"},
    )
    assert check_history_entry(entry) is entry
    log = JsonlHistoryLog(tmp_path / "history")
    log.append(entry)
    assert log.read() == (entry,)
