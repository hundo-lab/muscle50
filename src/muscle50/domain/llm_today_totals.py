"""Telegram LLM v2: a day's running totals as one range per nutrient.

Per nutrient, from the CLI's own JSON (`nutrition status --json` and `nutrition day --json`):

- confirmed: `known_subtotal` of the status (the items that have a value);
- estimated: the exact Decimal sum of the `minimum`/`maximum` of day items whose value is null and
  that carry a range (estimated general meals);
- unknown: the count of items with neither a value nor a range.

The text adds confirmed and estimated into `low~high` (one number when they agree). Nothing unknown becomes
0, and a day with no meals is "no record", not 0 kcal. A shape the code does not expect raises ValueError
(the caller then leaves the totals out).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Any

from muscle50.domain.nutrition import NutrientField

NUTRIENT_NAMES = {
    NutrientField.CALORIES_KCAL: "kcal",
    NutrientField.PROTEIN_G: "단백질",
    NutrientField.CARBOHYDRATE_G: "탄수화물",
    NutrientField.FAT_G: "지방",
}


@dataclass(frozen=True)
class NutrientTotal:
    nutrient: NutrientField
    confirmed: Decimal | None
    estimate_min: Decimal | None
    estimate_max: Decimal | None
    unknown_items: int


@dataclass(frozen=True)
class TodayTotals:
    meal_count: int
    nutrients: tuple[NutrientTotal, ...]

    def get(self, nutrient: NutrientField) -> NutrientTotal:
        return next(item for item in self.nutrients if item.nutrient is nutrient)


def today_totals(status_doc: Any, day_doc: Any) -> TodayTotals:
    status = _object(status_doc)
    meal_count = status["meal_count"]
    if type(meal_count) is not int:
        raise ValueError("meal_count must be an integer")
    nutrients = _object(status["nutrients"])
    items = [item for meal in _list(_object(day_doc)["meals"]) for item in _list(_object(meal)["items"])]
    totals = nutrient_totals(items, lambda nutrient: _decimal(_object(nutrients[nutrient.value])["known_subtotal"]))
    return TodayTotals(meal_count, totals)


def nutrient_totals(
    items: Sequence[Any], confirmed_of: Callable[[NutrientField], Decimal | None]
) -> tuple[NutrientTotal, ...]:
    """The per-nutrient totals of CLI item documents (`items[].nutrients`), shared by the day and a single meal.

    ``confirmed_of`` gives the confirmed subtotal of a nutrient (the CLI's `known_subtotal`); the estimates and the
    unknown count come from the items: an item with a value is confirmed, one with only a range is an estimate and
    one with neither is counted as unknown, never as 0.
    """
    totals = []
    for nutrient in NutrientField:
        confirmed = confirmed_of(nutrient)
        lows: list[Decimal] = []
        highs: list[Decimal] = []
        unknown = 0
        for item in items:
            entry = _object(item)["nutrients"][nutrient.value]
            if entry is None:
                unknown += 1
                continue
            entry = _object(entry)
            if entry["value"] is not None:
                continue
            low, high = _decimal(entry["minimum"]), _decimal(entry["maximum"])
            if low is None or high is None:
                unknown += 1
            else:
                lows.append(low)
                highs.append(high)
        totals.append(
            NutrientTotal(
                nutrient,
                confirmed,
                sum(lows, Decimal(0)) if lows else None,
                sum(highs, Decimal(0)) if highs else None,
                unknown,
            )
        )
    return tuple(totals)


TODAY_LABEL = "오늘"


def totals_text(totals: TodayTotals, label: str = TODAY_LABEL) -> str:
    """`<label> 누적 ...` with one line per nutrient (Korean bot text).

    ``label`` is `오늘` for today and `MM-DD` for another day (the day the proposal records). The header says
    `(추정 포함)` when some nutrient has an estimated range.
    """
    if totals.meal_count == 0:
        # Today keeps the v2 sentence; another day reads `10-14 기록 없음 (0이 아님)`.
        return "오늘 누적: 오늘 기록 없음 (0이 아님)" if label == TODAY_LABEL else f"{label} 기록 없음 (0이 아님)"
    estimated = any(item.estimate_min is not None for item in totals.nutrients)
    head = f"{label} 누적 (추정 포함):" if estimated else f"{label} 누적:"
    return "\n".join([head, *(f"  {nutrient_total_text(item)}" for item in totals.nutrients)])


def nutrient_total_text(item: NutrientTotal) -> str:
    """One range per nutrient: low = confirmed + estimate minimums, high = confirmed + estimate maximums.

    An unknown item is never added (as 0): it is counted as `(값 모르는 항목 N개 빠짐)`. No value and no
    estimate at all reads `알 수 없음`, never 0.
    """
    unit = "" if item.nutrient is NutrientField.CALORIES_KCAL else " g"
    if item.confirmed is None and item.estimate_min is None:
        value = "알 수 없음"
    else:
        low = (item.confirmed or Decimal(0)) + (item.estimate_min or Decimal(0))
        high = (item.confirmed or Decimal(0)) + (item.estimate_max or Decimal(0))
        low_text, high_text = display_amount(low), display_amount(high)
        value = f"{low_text}{unit}" if low_text == high_text else f"{low_text}~{high_text}{unit}"
    text = f"{NUTRIENT_NAMES[item.nutrient]} {value}"
    if item.unknown_items:
        text += f" (값 모르는 항목 {item.unknown_items}개 빠짐)"
    return text


def amount_text(value: Decimal) -> str:
    """Plain decimal text (`1150`, `30.5`), the way the CLI JSON writes amounts (exact: argv and quantities)."""
    text = format(value, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def display_amount(value: Decimal) -> str:
    """A number as the CLI prints it: rounded to 0.1 (half-even), trailing zeros dropped (`1.95` -> `2`)."""
    return amount_text(value.quantize(Decimal("0.1"), rounding=ROUND_HALF_EVEN))


def display_remaining(value: Decimal) -> str:
    """A remaining amount as the CLI prints a gap: a positive value that rounds to 0 reads `<0.1`, never `0`."""
    if value > 0 and value.quantize(Decimal("0.1"), rounding=ROUND_HALF_EVEN) == 0:
        return "<0.1"
    return display_amount(value)


def _decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("expected a decimal string")
    return Decimal(value)


def _object(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("expected a JSON object")
    return value


def _list(value: Any) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError("expected a JSON array")
    return value
