"""Telegram LLM v2: the bot's fixed menu order (gate 1 decision E3: always rank, say how sure it is).

The LLM only reads a menu (or suggests dishes) and estimates ranges; the order is this rule:

- Mode K (remaining known): a kcal target is set and today's kcal is complete. Budget `B` is
  `remaining_to_maximum` (range target) or `remaining` (exact target). Fit 0: `kmax <= B`; fit 1:
  `kmin <= B < kmax` ("may exceed"); fit 2: `kmin > B` or kcal unknown.
- Mode R (remaining as a range): a kcal target is set, every logged item has a value or a range and at
  least one is an estimate. `B_low = max(0, T_max - (confirmed + est_max))`, `B_high = max(0, T_max -
  (confirmed + est_min))`; fit 0: `kmax <= B_low`; fit 1: `kmin <= B_high`; else 2. (`confirmed` is the
  known subtotal; with no point-valued item it is the empty sum, which is exact here because no item is
  unknown.)
- K and R sort by `(fit, protein unknown, -protein midpoint, kcal midpoint or infinity, capture order)`.
- Mode P (everything else: no kcal target, no meals logged, an item without any value, or the status
  could not be read): `(kcal or protein unknown, -(protein mid / kcal mid), kcal mid, capture order)`,
  with the reasons listed. A remaining amount is never assumed (nothing logged is not "all remains").

Midpoints are exact Decimals `(min + max) / 2`; a printed value is `[v, v]`. Same input, same order.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import Any

from muscle50.domain.llm_today_totals import TodayTotals
from muscle50.domain.nutrition import NutrientField

INFINITY = Decimal("Infinity")

REASON_STATUS_UNREADABLE = "영양 상태를 읽지 못함"
REASON_NO_KCAL_TARGET = "kcal 목표 없음"
REASON_NO_MEALS = "오늘 식사 기록이 없어 남은 양을 알 수 없음 (0 kcal이 아님)"
REASON_UNKNOWN_ITEMS = "값을 모르는 항목(일반식 등)이 있어 남은 양을 알 수 없음"
FIT_LABELS = {1: "(남은 kcal을 넘을 수 있음)", 2: "(남은 kcal 초과 또는 알 수 없음)"}
_MET_STATUSES = frozenset({"target_reached", "above_target", "above_range"})


class RankMode(StrEnum):
    KNOWN = "known"
    RANGE = "range"
    RATIO = "ratio"


@dataclass(frozen=True)
class RankItem:
    index: int
    """Capture (or suggestion) order, from 1."""
    kcal: tuple[Decimal, Decimal] | None
    protein: tuple[Decimal, Decimal] | None


@dataclass(frozen=True)
class KcalContext:
    readable: bool
    target_max: Decimal | None
    """The range maximum or the exact target; None when no kcal target is set."""
    status: str | None
    complete: bool
    budget: Decimal | None
    """Mode K's `B`."""
    meal_count: int
    confirmed: Decimal | None
    estimate_min: Decimal | None
    estimate_max: Decimal | None
    unknown_items: int
    remaining_to_maximum: Decimal | None


UNREADABLE = KcalContext(False, None, None, False, None, 0, None, None, None, 0, None)


@dataclass(frozen=True)
class RankedItem:
    index: int
    label: str | None


@dataclass(frozen=True)
class MenuRanking:
    mode: RankMode
    order: tuple[RankedItem, ...]
    budget_low: Decimal | None
    budget_high: Decimal | None
    reasons: tuple[str, ...]
    target_met: bool


def kcal_context(status_doc: Any, totals: TodayTotals | None) -> KcalContext:
    """The kcal facts the rule needs, from `nutrition status --json` (and today's totals); ValueError on shape."""
    if not isinstance(status_doc, dict):
        raise ValueError("expected a JSON object")
    entry = status_doc["nutrients"][NutrientField.CALORIES_KCAL.value]
    target = entry["target"]
    kind = target["kind"]
    if kind == "exact":
        target_max: Decimal | None = Decimal(target["value"])
    elif kind == "range":
        target_max = Decimal(target["maximum"])
    elif kind == "unset":
        target_max = None
    else:
        raise ValueError("unknown target kind")
    complete = entry["complete"]
    meal_count = status_doc["meal_count"]
    if type(complete) is not bool or type(meal_count) is not int:
        raise ValueError("unexpected status shape")
    remaining = _optional(entry["remaining"])
    to_maximum = _optional(entry["remaining_to_maximum"])
    kcal_total = totals.get(NutrientField.CALORIES_KCAL) if totals is not None else None
    return KcalContext(
        readable=True,
        target_max=target_max,
        status=str(entry["status"]),
        complete=complete,
        budget=to_maximum if kind == "range" else remaining,
        meal_count=meal_count,
        confirmed=_optional(entry["known_subtotal"]),
        estimate_min=kcal_total.estimate_min if kcal_total is not None else None,
        estimate_max=kcal_total.estimate_max if kcal_total is not None else None,
        unknown_items=kcal_total.unknown_items if kcal_total is not None else (0 if complete else 1),
        remaining_to_maximum=to_maximum,
    )


def rank_menu(items: tuple[RankItem, ...], context: KcalContext) -> MenuRanking:
    target_met = context.readable and (
        context.status in _MET_STATUSES
        or (context.status == "within_range" and context.remaining_to_maximum == Decimal(0))
    )
    if context.readable and context.target_max is not None and context.complete and context.budget is not None:
        budget = context.budget
        ranked = sorted(items, key=lambda item: _fit_key(item, _fit(item, budget, budget)))
        order = tuple(RankedItem(item.index, FIT_LABELS.get(_fit(item, budget, budget))) for item in ranked)
        return MenuRanking(RankMode.KNOWN, order, budget, budget, (), target_met)
    if (
        context.readable
        and context.target_max is not None
        and context.meal_count > 0
        and context.unknown_items == 0
        and context.estimate_min is not None
        and context.estimate_max is not None
    ):
        confirmed = context.confirmed if context.confirmed is not None else Decimal(0)
        low = max(Decimal(0), context.target_max - (confirmed + context.estimate_max))
        high = max(Decimal(0), context.target_max - (confirmed + context.estimate_min))
        ranked = sorted(items, key=lambda item: _fit_key(item, _fit(item, low, high)))
        order = tuple(RankedItem(item.index, FIT_LABELS.get(_fit(item, low, high))) for item in ranked)
        return MenuRanking(RankMode.RANGE, order, low, high, (), target_met)
    reasons = []
    if not context.readable:
        reasons.append(REASON_STATUS_UNREADABLE)
    else:
        if context.target_max is None:
            reasons.append(REASON_NO_KCAL_TARGET)
        if context.meal_count == 0:
            reasons.append(REASON_NO_MEALS)
        elif context.unknown_items > 0:
            reasons.append(REASON_UNKNOWN_ITEMS)
    ranked = sorted(items, key=_ratio_key)
    order = tuple(RankedItem(item.index, None) for item in ranked)
    return MenuRanking(RankMode.RATIO, order, None, None, tuple(reasons), target_met)


def midpoint(bounds: tuple[Decimal, Decimal]) -> Decimal:
    return (bounds[0] + bounds[1]) / 2


def _fit(item: RankItem, low: Decimal, high: Decimal) -> int:
    if item.kcal is None:
        return 2
    if item.kcal[1] <= low:
        return 0
    if item.kcal[0] <= high:
        return 1
    return 2


def _fit_key(item: RankItem, fit: int) -> tuple[int, int, Decimal, Decimal, int]:
    protein = midpoint(item.protein) if item.protein is not None else Decimal(0)
    kcal = midpoint(item.kcal) if item.kcal is not None else INFINITY
    return (fit, 0 if item.protein is not None else 1, -protein, kcal, item.index)


def _ratio_key(item: RankItem) -> tuple[int, Decimal, Decimal, int]:
    kcal = midpoint(item.kcal) if item.kcal is not None else None
    if item.protein is None or kcal is None or kcal == 0:
        return (1, Decimal(0), kcal if kcal is not None else INFINITY, item.index)
    return (0, -(midpoint(item.protein) / kcal), kcal, item.index)


def _optional(value: Any) -> Decimal | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("expected a decimal string")
    return Decimal(value)
