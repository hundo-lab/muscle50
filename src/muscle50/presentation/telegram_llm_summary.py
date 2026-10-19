"""Telegram LLM v2.4 presentation: the short Korean reply after `/ok`, `/plain`, an edit or a void.

Plain text for a `<pre>` body (the bot sends it like any CLI reply). The numbers are those of the CLI's own
`meal show --json`, rounded the way the CLI prints them (0.1, half-even). A missing value is `값 없음`, never 0.
"""

from __future__ import annotations

from muscle50.domain.llm_today_totals import NUTRIENT_NAMES, NutrientTotal, display_amount, nutrient_total_text
from muscle50.domain.nutrition import NutrientField
from muscle50.domain.telegram_llm_prompt import MEAL_NAMES
from muscle50.domain.telegram_llm_summary import (
    NO_VALUE_TEXT,
    MealSummary,
    SummaryItem,
    SummaryValue,
    SummaryVerb,
)

_HEADLINES = {
    SummaryVerb.RECORDED: "기록했습니다",
    SummaryVerb.EDITED: "수정했습니다",
    SummaryVerb.VOIDED: "취소(void)했습니다",
}


def render_meal_summary(summary: MealSummary, verb: SummaryVerb) -> str:
    """The recorded or edited meal: headline, one line per item, the meal's own range and the next commands."""
    lines = [f"{_HEADLINES[verb]}: {MEAL_NAMES[summary.meal_type]} {summary.meal_id} ({summary.day:%m-%d})"]
    lines.extend(_item_line(item) for item in summary.items)
    lines.append(_meal_line(summary))
    lines.append(_commands_line(summary.meal_id, verb))
    return "\n".join(lines)


def render_voided(meal_id: str) -> str:
    """A voided meal needs no read: the id is the proposal's own."""
    return f"{_HEADLINES[SummaryVerb.VOIDED]}: {meal_id}\n확인: /show {meal_id}"


def _item_line(item: SummaryItem) -> str:
    if not item.values:
        return f"{item.sequence}. {item.text} - {NO_VALUE_TEXT}"
    values = ", ".join(_value_text(value) for value in item.values)
    prefix = f"{item.prefix} " if item.prefix else ""
    return f"{item.sequence}. {item.text} - {prefix}{values}"


def _value_text(value: SummaryValue) -> str:
    unit = "" if value.nutrient is NutrientField.CALORIES_KCAL else " g"
    low, high = display_amount(value.low), display_amount(value.high)
    amount = low if low == high else f"{low}~{high}"
    return f"{NUTRIENT_NAMES[value.nutrient]} {amount}{unit}"


def _meal_line(summary: MealSummary) -> str:
    totals = summary.totals.nutrients
    if all(_nothing_known(total) for total in totals):
        return f"이 끼니: {NO_VALUE_TEXT} (0이 아님)"
    estimated = any(total.estimate_min is not None for total in totals)
    head = "이 끼니 (추정 포함):" if estimated else "이 끼니:"
    return f"{head} " + ", ".join(nutrient_total_text(total) for total in totals)


def _nothing_known(total: NutrientTotal) -> bool:
    return total.confirmed is None and total.estimate_min is None


def _commands_line(meal_id: str, verb: SummaryVerb) -> str:
    if verb is SummaryVerb.RECORDED:
        return f"취소: /void {meal_id}   전체 보기: /show {meal_id}"
    return f"확인: /show {meal_id}"
