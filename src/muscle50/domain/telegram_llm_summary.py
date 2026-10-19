"""Telegram LLM v2.4: the short Korean summary of a meal the bot just recorded or edited (pure).

The input is the CLI's own `nutrition meal show <id> --json` document, read after the write. Nothing is
calculated here that the CLI has not already calculated: the item values are the stored values, and the meal
line adds them with the same rules as the day totals (`nutrient_totals`): the confirmed subtotal of the items
that have a value, the estimate ranges of the items that only have a range, and a count of the items with
neither. A missing value is never 0.

A shape the code does not expect raises `KeyError`, `TypeError`, `ValueError` or `InvalidOperation`; the caller
then keeps the CLI's own text.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from muscle50.domain.llm_today_totals import TodayTotals, amount_text, nutrient_totals
from muscle50.domain.nutrition import MealType, NutrientField
from muscle50.domain.telegram_llm_meals import LABEL_NOTE

NO_VALUE_TEXT = "값 없음"
LABEL_PREFIX = "라벨"
ESTIMATE_PREFIX = "추정"


class SummaryVerb(StrEnum):
    RECORDED = "recorded"
    EDITED = "edited"
    VOIDED = "voided"


# The `nutrition meal ...` commands an edit proposal runs, by what they do to the meal.
EDIT_VERBS = {
    "replace-item": SummaryVerb.EDITED,
    "add-item": SummaryVerb.EDITED,
    "remove-item": SummaryVerb.EDITED,
    "edit": SummaryVerb.EDITED,
    "void": SummaryVerb.VOIDED,
}


def edit_verb(argv: tuple[str, ...]) -> SummaryVerb:
    """The verb of an edit proposal's command (`nutrition meal <verb> <meal_id> ...`); unknown reads as edited."""
    return EDIT_VERBS.get(argv[2], SummaryVerb.EDITED) if len(argv) > 2 else SummaryVerb.EDITED


@dataclass(frozen=True)
class SummaryValue:
    nutrient: NutrientField
    low: Decimal
    high: Decimal


@dataclass(frozen=True)
class SummaryItem:
    sequence: int
    text: str
    """`일반식 (메모: ...)` for a general item, `닭가슴살 (chicken-breast) 1 pack` for a catalog item."""
    values: tuple[SummaryValue, ...]
    """In nutrient order. A nutrient with no value and no range is left out (never shown as 0)."""
    prefix: str
    """`라벨` (a value printed on a label), `추정` (an estimated range) or empty (exact values)."""


@dataclass(frozen=True)
class MealSummary:
    meal_id: str
    meal_type: MealType
    day: date
    items: tuple[SummaryItem, ...]
    totals: TodayTotals
    """The meal as a `TodayTotals` (one meal): confirmed, estimated range and unknown count per nutrient."""


def parse_meal_summary(document: Any) -> MealSummary | None:
    """The summary of a `meal show --json` document; None when the meal is voided (there is nothing to summarize)."""
    meal = _object(document)
    if meal.get("voided") is True:
        return None
    item_documents = _list(meal["items"])
    known = _object(_object(meal["total"])["known_subtotals"])
    totals = nutrient_totals(item_documents, lambda nutrient: _decimal(known[nutrient.value]))
    return MealSummary(
        meal_id=_text(meal["meal_id"]),
        meal_type=MealType(meal["meal_type"]),
        day=datetime.fromisoformat(_text(meal["eaten_at"])).date(),
        items=tuple(_item(_object(item)) for item in item_documents),
        totals=TodayTotals(1, totals),
    )


def _item(document: dict[str, Any]) -> SummaryItem:
    values: list[SummaryValue] = []
    ranged = False
    all_points = True
    nutrients = _object(document["nutrients"])
    for nutrient in NutrientField:
        entry = nutrients[nutrient.value]
        if entry is None:
            continue
        entry = _object(entry)
        value, low, high = _decimal(entry["value"]), _decimal(entry["minimum"]), _decimal(entry["maximum"])
        if value is not None:
            values.append(SummaryValue(nutrient, value, value))
        elif low is not None and high is not None:
            values.append(SummaryValue(nutrient, low, high))
            ranged = True
            all_points = all_points and low == high
    prefix = ""
    if ranged:
        prefix = LABEL_PREFIX if all_points and _has_label_fact(document) else ESTIMATE_PREFIX
    return SummaryItem(int(document["sequence"]), _item_text(document), tuple(values), prefix)


def _has_label_fact(document: dict[str, Any]) -> bool:
    """A range fact whose reference is `... ; 라벨 ...` (the marker the proposal wrote after the base reference)."""
    for fact in _list(document["facts"]):
        fact = _object(fact)
        reference = fact["source_reference"]
        if (
            fact["has_estimate_range"] is True
            and isinstance(reference, str)
            and LABEL_NOTE in reference.split("; ")[1:]
        ):
            return True
    return False


def _item_text(document: dict[str, Any]) -> str:
    if document.get("general_meal") is True:
        note = document.get("note")
        return f"일반식 (메모: {note})" if isinstance(note, str) and note else "일반식"
    name = _text(document["food_name"])
    food_id = document["food_id"]
    quantity, unit = _decimal(document["quantity"]), document["unit"]
    shown = f"{name} ({food_id})" if isinstance(food_id, str) and food_id else name
    if quantity is not None and isinstance(unit, str):
        return f"{shown} {amount_text(quantity)} {unit}"
    return shown


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


def _text(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError("expected text")
    return value
