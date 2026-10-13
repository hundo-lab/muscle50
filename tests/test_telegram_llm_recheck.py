"""Telegram LLM v2.2 numeric re-check: the deterministic checks (pure, constants pinned), the machine-written
re-ask note, and the bot flow (one corrective re-ask, the `(값 확인 필요)` marker, history)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from muscle50.domain.nutrition import NutrientField
from muscle50.domain.telegram_llm import NutrientRanges
from muscle50.domain.telegram_llm_check import (
    ATWATER_CARBS,
    ATWATER_FAT,
    ATWATER_PROTEIN,
    KCAL_WIDTH_FLOOR,
    MAX_NOTE_LINES,
    PROTEIN_WIDTH_FLOOR,
    RECHECK_INTRO,
    TOLERANCE_KCAL,
    TOLERANCE_RATIO,
    WIDTH_RATIO,
    CheckCode,
    CheckFailure,
    check_estimate,
    recheck_note,
)

KCAL, PROTEIN = NutrientField.CALORIES_KCAL, NutrientField.PROTEIN_G
CARBS, FAT = NutrientField.CARBOHYDRATE_G, NutrientField.FAT_G


def ranges(
    kcal: tuple[int, int] | None = (650, 950),
    protein: tuple[int, int] | None = (25, 40),
    carbs: tuple[int, int] | None = None,
    fat: tuple[int, int] | None = None,
) -> NutrientRanges:
    out = []
    for field, bounds in ((KCAL, kcal), (PROTEIN, protein), (CARBS, carbs), (FAT, fat)):
        if bounds is not None:
            out.append((field, Decimal(bounds[0]), Decimal(bounds[1])))
    return tuple(out)


def codes(value: NutrientRanges, assumption: str | None = None, quantity: Decimal | None = None) -> list[CheckCode]:
    return [failure.code for failure in check_estimate(value, assumption=assumption, quantity=quantity)]


def test_constants_are_pinned() -> None:
    assert (Decimal("0.7"), Decimal(150), Decimal(10)) == (WIDTH_RATIO, KCAL_WIDTH_FLOOR, PROTEIN_WIDTH_FLOOR)
    assert (Decimal(4), Decimal(4), Decimal(9)) == (ATWATER_PROTEIN, ATWATER_CARBS, ATWATER_FAT)
    assert (Decimal("0.2"), Decimal(20), 5) == (TOLERANCE_RATIO, TOLERANCE_KCAL, MAX_NOTE_LINES)


def test_plausible_dishes_pass() -> None:
    assert codes(ranges()) == []  # 650~950 kcal, 25~40 g
    assert codes(ranges((700, 1000), (20, 32), (110, 150), (18, 32))) == []  # 김밥 두 줄 shaped
    assert codes(ranges((150, 300), (10, 20))) == []  # 오뎅국 shaped
    assert codes(ranges((300, 450), (55, 70))) == []  # 닭가슴살 shaped
    assert codes(ranges((0, 0), (0, 0))) == []  # water: an explicit 0~0 range is fine
    assert codes(ranges((0, 5), (0, 5))) == []


@pytest.mark.parametrize(
    ("kcal", "protein", "expected"),
    [
        ((100, 900), (25, 40), [CheckCode.RANGE_TOO_WIDE]),
        ((650, 950), (2, 40), [CheckCode.RANGE_TOO_WIDE]),
        ((300, 300), (25, 40), [CheckCode.RANGE_IS_A_POINT]),
        ((650, 950), (30, 30), [CheckCode.RANGE_IS_A_POINT]),
        ((200, 700), (25, 40), [CheckCode.RANGE_TOO_WIDE]),
    ],
)
def test_width_and_point_failures(kcal: tuple[int, int], protein: tuple[int, int], expected: list[CheckCode]) -> None:
    assert codes(ranges(kcal, protein)) == expected


def test_width_needs_both_the_ratio_and_the_floor() -> None:
    # the floor saves a narrow range that is still wide relative to its max
    assert codes(ranges((0, 150), (25, 40))) == []  # width 150 is above 70% of 150 but not above the floor
    assert codes(ranges((0, 151), (25, 40))) == [CheckCode.RANGE_TOO_WIDE]
    assert codes(ranges((650, 950), (0, 10))) == []
    assert codes(ranges((650, 950), (0, 11))) == [CheckCode.RANGE_TOO_WIDE]
    # the ratio saves a wide range that is not wide relative to its max
    assert codes(ranges((300, 1000), (25, 40))) == []  # width 700 is exactly 70% of 1000
    assert codes(ranges((299, 1000), (25, 40))) == [CheckCode.RANGE_TOO_WIDE]


def test_macros_against_kcal_with_all_three_ranges() -> None:
    assert codes(ranges((650, 950), (35, 55), (20, 30), (5, 10))) == [CheckCode.MACROS_VS_KCAL]  # 265~410 vs 500~1180
    assert codes(ranges((650, 950), (35, 55), (60, 80), (20, 30))) == []
    # overlap is enough: macro 4*40 + 4*60 + 9*20 = 580 .. kcal widened to 500~1180
    assert codes(ranges((650, 950), (40, 50), (60, 70), (20, 25))) == []


def test_atwater_tolerance_edges() -> None:
    # kcal 500~650 is widened to 380~800 (500*0.8-20, 650*1.2+20)
    assert CheckCode.MACROS_VS_KCAL not in codes(
        ranges((500, 650), (20, 45), (50, 60), (6, 12))
    )  # high 4*45+4*60+9*12=528
    # macro high exactly on the lower edge (380) still overlaps: 4*20 + 4*30 + 9*20 = 380
    assert CheckCode.MACROS_VS_KCAL not in codes(ranges((500, 650), (20, 20), (30, 30), (20, 20)))
    # one below the edge does not: 4*20 + 4*30 + 9*19 = 371
    assert CheckCode.MACROS_VS_KCAL in codes(ranges((500, 650), (20, 20), (30, 30), (19, 19)))
    # macro low exactly on the upper edge (800) overlaps: 4*50 + 4*100 + 9*22.2 is not exact, use 4*80+4*120
    assert CheckCode.MACROS_VS_KCAL not in codes(ranges((500, 650), (80, 80), (120, 120), (0, 0)))
    assert CheckCode.MACROS_VS_KCAL in codes(ranges((500, 650), (80, 80), (121, 121), (0, 0)))


def test_present_macros_cannot_exceed_kcal_even_if_the_missing_one_were_zero() -> None:
    # protein min 60 -> 240 kcal > widened kcal max 50..100 -> 140
    assert codes(ranges((50, 100), (60, 80))) == [CheckCode.MACROS_EXCEED_KCAL]
    assert codes(ranges((300, 400), (60, 70))) == []  # 240 <= 500
    # exactly on the edge: kcal max 100 -> 140; protein min 35 -> 140 is allowed, 36 is not
    assert codes(ranges((50, 100), (35, 80))) == []
    assert codes(ranges((50, 100), (36, 80))) == [CheckCode.MACROS_EXCEED_KCAL]
    # only carbs present (no fat), only fat present (no carbs)
    assert codes(ranges((100, 200), (5, 10), carbs=(70, 80))) == [CheckCode.MACROS_EXCEED_KCAL]
    assert codes(ranges((100, 200), (5, 10), fat=(30, 35))) == [CheckCode.MACROS_EXCEED_KCAL]
    assert codes(ranges((300, 400), (10, 20), fat=(30, 35))) == []


def test_assumption_numbers_must_be_the_items_own() -> None:
    value = ranges((650, 950), (25, 40))
    assert codes(value, "일반 미역국 정식으로 추정") == []
    assert codes(value, "2.5줄 기준으로 추정", Decimal("2.5")) == []
    assert codes(value, "2.5줄 기준으로 추정", None) == [CheckCode.ASSUMPTION_NUMBER]
    assert codes(value, "650 kcal 정도로 추정") == []  # an estimate bound
    assert codes(value, "한 그릇 약 700 kcal로 추정") == [CheckCode.ASSUMPTION_NUMBER]
    assert codes(value, "") == [] and codes(value, None) == []


def test_failures_come_in_a_fixed_order_and_carry_computed_numbers() -> None:
    value = ranges((100, 900), (200, 250), (200, 250), (50, 60))
    failures = check_estimate(value, assumption="777g", quantity=None)
    assert [failure.code for failure in failures] == [
        CheckCode.RANGE_TOO_WIDE,
        CheckCode.MACROS_VS_KCAL,
        CheckCode.ASSUMPTION_NUMBER,
    ]
    assert failures[0].detail == "kcal 100-900"
    assert failures[1].detail == "kcal 100-900, 영양소 합 2050-2540"
    assert failures[2].detail == "1 numbers"


def test_recheck_note_has_only_indexes_codes_and_numbers() -> None:
    failure = CheckFailure(CheckCode.MACROS_VS_KCAL, "kcal 650-950, 영양소 합 1200-1500")
    note = recheck_note([(3, failure)])
    assert note == f"{RECHECK_INTRO}\n- items[3]: macros_vs_kcal (kcal 650-950, 영양소 합 1200-1500)"


def test_recheck_note_lists_at_most_five_failures() -> None:
    failure = CheckFailure(CheckCode.RANGE_TOO_WIDE, "kcal 1-9")
    note = recheck_note([(index, failure) for index in range(1, 9)])
    assert note.count("\n- items[") == MAX_NOTE_LINES
    assert "items[6]" not in note
