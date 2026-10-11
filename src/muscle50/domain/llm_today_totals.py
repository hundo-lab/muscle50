"""Telegram LLM v2: today's running totals, confirmed values and estimated ranges kept apart.

Per nutrient, from the CLI's own JSON (`nutrition status --json` and `nutrition day --json`):

- confirmed: `known_subtotal` of the status (the items that have a value);
- estimated: the exact Decimal sum of the `minimum`/`maximum` of day items whose value is null and
  that carry a range (estimated general meals);
- unknown: the count of items with neither a value nor a range.

Nothing unknown becomes 0, and a day with no meals is "no record", not 0 kcal. A shape the code
does not expect raises ValueError (the caller then leaves the totals out).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
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
    totals = []
    for nutrient in NutrientField:
        confirmed = _decimal(_object(nutrients[nutrient.value])["known_subtotal"])
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
    return TodayTotals(meal_count, tuple(totals))


def totals_text(totals: TodayTotals) -> str:
    """`오늘 누적: ...` with one line per nutrient (Korean bot text)."""
    if totals.meal_count == 0:
        return "오늘 누적: 오늘 기록 없음 (0이 아님)"
    return "\n".join(["오늘 누적:", *(f"  {nutrient_total_text(item)}" for item in totals.nutrients)])


def nutrient_total_text(item: NutrientTotal) -> str:
    unit = "" if item.nutrient is NutrientField.CALORIES_KCAL else " g"
    parts = []
    if item.confirmed is not None:
        parts.append(f"확인 {amount_text(item.confirmed)}{unit}")
    if item.estimate_min is not None and item.estimate_max is not None:
        parts.append(f"추정 {amount_text(item.estimate_min)}~{amount_text(item.estimate_max)}{unit}")
    text = f"{NUTRIENT_NAMES[item.nutrient]} {' + '.join(parts) if parts else '알 수 없음'}"
    if item.unknown_items:
        text += f" (값 모르는 항목 {item.unknown_items}개)"
    return text


def amount_text(value: Decimal) -> str:
    """Plain decimal text (`1150`, `30.5`), the way the CLI JSON writes amounts."""
    text = format(value, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


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
