"""Telegram LLM v2.2: deterministic checks of an estimated general meal item, and the machine-written re-ask note.

Pure and exact (`Decimal`, nothing rounded). A check never changes a value: it only says that the model's own
numbers do not agree with each other, so the bot can ask once more and, if the answer is still inconsistent,
mark the item `(값 확인 필요)` for the user to decide at `/ok`.

Constants are named here and pinned by tests.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from muscle50.domain.llm_number_guard import allowed_numbers, unknown_numbers
from muscle50.domain.nutrition import NutrientField
from muscle50.domain.telegram_llm import NutrientRanges

WIDTH_RATIO = Decimal("0.7")
"""A range is too wide when `max - min` is above this share of `max` ..."""
KCAL_WIDTH_FLOOR = Decimal(150)
PROTEIN_WIDTH_FLOOR = Decimal(10)
"""... and above this absolute width (kcal; grams of protein), so `0~5 g` never counts as wide."""
ATWATER_PROTEIN = Decimal(4)
ATWATER_CARBS = Decimal(4)
ATWATER_FAT = Decimal(9)
TOLERANCE_RATIO = Decimal("0.2")
TOLERANCE_KCAL = Decimal(20)
"""The kcal range is widened by 20 percent and 20 kcal (fibre, alcohol, rounding) before it is compared."""
MAX_NOTE_LINES = 5

RECHECK_INTRO = "앞선 답에서 다음이 맞지 않았습니다. 같은 메시지를 다시 해석하고 모든 item을 규칙대로 다시 확인하세요."


class CheckCode(StrEnum):
    RANGE_TOO_WIDE = "range_too_wide"
    RANGE_IS_A_POINT = "range_is_a_point"
    MACROS_VS_KCAL = "macros_vs_kcal"
    MACROS_EXCEED_KCAL = "macros_exceed_kcal"
    ASSUMPTION_NUMBER = "assumption_number"


class RecheckOutcome(StrEnum):
    FIXED = "fixed"
    STILL_INCONSISTENT = "still_inconsistent"
    REASK_FAILED = "reask_failed"


CHECK_REASON_TEXTS = {
    CheckCode.RANGE_TOO_WIDE: "범위가 너무 넓음",
    CheckCode.RANGE_IS_A_POINT: "범위가 아니라 한 값임",
    CheckCode.MACROS_VS_KCAL: "열량과 영양소 합이 맞지 않음",
    CheckCode.MACROS_EXCEED_KCAL: "영양소 합이 열량보다 큼",
    CheckCode.ASSUMPTION_NUMBER: "가정에 쓴 숫자가 수량·추정값과 다름",
}
"""The fixed Korean reason line shown under a marked item."""

OUTCOME_HISTORY_TEXTS = {
    RecheckOutcome.FIXED: "고침",
    RecheckOutcome.STILL_INCONSISTENT: "남음",
    RecheckOutcome.REASK_FAILED: "실패",
}


@dataclass(frozen=True)
class CheckFailure:
    code: CheckCode
    detail: str
    """ASCII numbers computed from the model's own answer, for the re-ask note (no names, no message text)."""


def check_estimate(
    ranges: NutrientRanges, *, assumption: str | None, quantity: Decimal | None
) -> tuple[CheckFailure, ...]:
    """The failed checks of one estimated general item, in a fixed order (empty: it passes)."""
    by_field = {nutrient: (low, high) for nutrient, low, high in ranges}
    failures: list[CheckFailure] = []
    kcal = by_field.get(NutrientField.CALORIES_KCAL)
    protein = by_field.get(NutrientField.PROTEIN_G)
    carbs = by_field.get(NutrientField.CARBOHYDRATE_G)
    fat = by_field.get(NutrientField.FAT_G)
    for label, bounds, floor in (("kcal", kcal, KCAL_WIDTH_FLOOR), ("protein", protein, PROTEIN_WIDTH_FLOOR)):
        if bounds is None:
            continue
        low, high = bounds
        if high - low > WIDTH_RATIO * high and high - low > floor:
            failures.append(CheckFailure(CheckCode.RANGE_TOO_WIDE, f"{label} {_range(bounds)}"))
        if low == high and high > 0:
            failures.append(CheckFailure(CheckCode.RANGE_IS_A_POINT, f"{label} {_range(bounds)}"))
    if kcal is not None and protein is not None:
        failures.extend(_macro_failures(kcal, protein, carbs, fat))
    if assumption:
        allowed = allowed_numbers([_numbers_of(ranges, quantity)])
        if unknown_numbers(assumption, allowed):
            failures.append(
                CheckFailure(CheckCode.ASSUMPTION_NUMBER, f"{len(unknown_numbers(assumption, allowed))} numbers")
            )
    return tuple(failures)


def _macro_failures(
    kcal: tuple[Decimal, Decimal],
    protein: tuple[Decimal, Decimal],
    carbs: tuple[Decimal, Decimal] | None,
    fat: tuple[Decimal, Decimal] | None,
) -> list[CheckFailure]:
    kcal_low = kcal[0] * (1 - TOLERANCE_RATIO) - TOLERANCE_KCAL
    kcal_high = kcal[1] * (1 + TOLERANCE_RATIO) + TOLERANCE_KCAL
    if carbs is not None and fat is not None:
        low = ATWATER_PROTEIN * protein[0] + ATWATER_CARBS * carbs[0] + ATWATER_FAT * fat[0]
        high = ATWATER_PROTEIN * protein[1] + ATWATER_CARBS * carbs[1] + ATWATER_FAT * fat[1]
        if high < kcal_low or low > kcal_high:
            return [CheckFailure(CheckCode.MACROS_VS_KCAL, f"kcal {_range(kcal)}, 영양소 합 {_range((low, high))}")]
        return []
    present = ATWATER_PROTEIN * protein[0]
    if carbs is not None:
        present += ATWATER_CARBS * carbs[0]
    if fat is not None:
        present += ATWATER_FAT * fat[0]
    if present > kcal_high:
        return [
            CheckFailure(CheckCode.MACROS_EXCEED_KCAL, f"kcal {_range(kcal)}, 영양소 합 최소 {_number(present)}")
        ]
    return []


def _numbers_of(ranges: NutrientRanges, quantity: Decimal | None) -> list[str]:
    """The item's own numbers as strings (`allowed_numbers` reads numbers out of strings)."""
    values = [] if quantity is None else [_number(quantity)]
    for _nutrient, low, high in ranges:
        values.extend((_number(low), _number(high)))
    return values


def recheck_note(failures: Sequence[tuple[int, CheckFailure]]) -> str:
    """The `[재확인]` text: a fixed sentence and one line per failure (item index, code and computed numbers).

    At most `MAX_NOTE_LINES` lines. It carries no food name, no message text and no memory.
    """
    lines = [f"- items[{index}]: {failure.code.value} ({failure.detail})" for index, failure in failures]
    return "\n".join([RECHECK_INTRO, *lines[:MAX_NOTE_LINES]])


def _range(bounds: tuple[Decimal, Decimal]) -> str:
    return f"{_number(bounds[0])}-{_number(bounds[1])}"


def _number(value: Decimal) -> str:
    return format(value.normalize(), "f") if value else "0"
