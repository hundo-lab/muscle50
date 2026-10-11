"""Telegram LLM v2 menu ranking (E3): golden orders for modes K, R and P, every tie-break, mode selection,
the targets-met flag, and determinism."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest

from muscle50.domain.llm_today_totals import NutrientTotal, TodayTotals
from muscle50.domain.menu_ranking import (
    REASON_NO_KCAL_TARGET,
    REASON_NO_MEALS,
    REASON_STATUS_UNREADABLE,
    REASON_UNKNOWN_ITEMS,
    UNREADABLE,
    KcalContext,
    RankItem,
    RankMode,
    kcal_context,
    rank_menu,
)
from muscle50.domain.nutrition import NutrientField


def D(value: str | int) -> Decimal:
    return Decimal(value)


def item(index: int, kcal: tuple[int, int] | None, protein: tuple[int, int] | None) -> RankItem:
    return RankItem(
        index,
        (D(kcal[0]), D(kcal[1])) if kcal is not None else None,
        (D(protein[0]), D(protein[1])) if protein is not None else None,
    )


def context(**overrides: Any) -> KcalContext:
    fields: dict[str, Any] = {
        "readable": True,
        "target_max": D(2500),
        "status": "below_range",
        "complete": True,
        "budget": D(800),
        "meal_count": 1,
        "confirmed": D(1700),
        "estimate_min": None,
        "estimate_max": None,
        "unknown_items": 0,
        "remaining_to_maximum": D(800),
    }
    fields.update(overrides)
    return KcalContext(**fields)


ITEMS = (
    item(1, (900, 1100), (20, 30)),  # over B: fit 2
    item(2, (600, 700), (30, 40)),  # fits, protein mid 35
    item(3, (700, 900), (40, 50)),  # may exceed: fit 1
    item(4, (500, 600), (30, 40)),  # fits, protein mid 35, smaller kcal than 2
    item(5, (300, 400), None),  # fits, protein unknown
    item(6, None, (50, 60)),  # kcal unknown: fit 2
    item(7, (500, 600), (30, 40)),  # same as 4: capture order
)


def test_mode_k_golden_order_and_labels() -> None:
    ranking = rank_menu(ITEMS, context())
    assert ranking.mode is RankMode.KNOWN
    assert [entry.index for entry in ranking.order] == [4, 7, 2, 5, 3, 6, 1]
    labels = {entry.index: entry.label for entry in ranking.order}
    assert labels[4] is None and labels[3] == "(남은 kcal을 넘을 수 있음)"
    assert labels[1] == labels[6] == "(남은 kcal 초과 또는 알 수 없음)"
    assert (ranking.budget_low, ranking.budget_high, ranking.reasons) == (D(800), D(800), ())


def test_printed_value_is_a_point_interval() -> None:
    ranked = rank_menu((item(1, (800, 800), (30, 30)), item(2, (790, 810), (30, 30))), context())
    assert [entry.index for entry in ranked.order] == [1, 2]
    assert ranked.order[1].label == "(남은 kcal을 넘을 수 있음)"


def test_mode_r_uses_the_headroom_range() -> None:
    ctx = context(complete=False, budget=None, status="indeterminate", confirmed=D(1000), estimate_min=D(700))
    ctx = KcalContext(**{**ctx.__dict__, "estimate_max": D(950)})
    ranking = rank_menu(ITEMS, ctx)
    assert ranking.mode is RankMode.RANGE
    assert (ranking.budget_low, ranking.budget_high) == (D(550), D(800))
    # B_low 550: only 5 (300-400) fits surely; 2, 3, 4, 7 have kmin <= 800 (fit 1).
    assert [entry.index for entry in ranking.order] == [5, 3, 4, 7, 2, 6, 1]


def test_mode_r_counts_no_confirmed_value_as_the_empty_sum() -> None:
    ctx = KcalContext(**{**context().__dict__, "complete": False, "budget": None, "confirmed": None})
    ctx = KcalContext(**{**ctx.__dict__, "estimate_min": D(700), "estimate_max": D(950)})
    ranking = rank_menu((item(1, (900, 1000), None),), ctx)
    assert (ranking.mode, ranking.budget_low, ranking.budget_high) == (RankMode.RANGE, D(1550), D(1800))


@pytest.mark.parametrize(
    ("ctx", "reasons"),
    [
        (context(target_max=None, status="no_target", budget=None), (REASON_NO_KCAL_TARGET,)),
        (context(meal_count=0, complete=False, budget=None, status="no_intake_logged"), (REASON_NO_MEALS,)),
        (context(complete=False, budget=None, unknown_items=1, status="indeterminate"), (REASON_UNKNOWN_ITEMS,)),
        (
            context(target_max=None, meal_count=0, complete=False, budget=None, status="no_target"),
            (REASON_NO_KCAL_TARGET, REASON_NO_MEALS),
        ),
        (UNREADABLE, (REASON_STATUS_UNREADABLE,)),
    ],
)
def test_mode_p_ranks_by_protein_per_kcal_with_reasons(ctx: KcalContext, reasons: tuple[str, ...]) -> None:
    ranking = rank_menu(ITEMS, ctx)
    assert ranking.mode is RankMode.RATIO and ranking.reasons == reasons
    # ratios: 4 = 7: 35/550, 3: 45/800, 2: 35/650, 1: 25/1000; 5 and 6 lack a value (last).
    assert [entry.index for entry in ranking.order] == [4, 7, 3, 2, 1, 5, 6]
    assert all(entry.label is None for entry in ranking.order)


@pytest.mark.parametrize(
    ("status", "to_maximum", "met"),
    [
        ("target_reached", None, True),
        ("above_range", D(0), True),
        ("within_range", D(0), True),
        ("within_range", D(100), False),
        ("below_range", D(800), False),
    ],
)
def test_targets_met_flag(status: str, to_maximum: Decimal | None, met: bool) -> None:
    assert rank_menu(ITEMS, context(status=status, remaining_to_maximum=to_maximum)).target_met is met


def test_same_input_same_order() -> None:
    reversed_items = tuple(reversed(ITEMS))
    assert rank_menu(ITEMS, context()) == rank_menu(ITEMS, context())
    assert [entry.index for entry in rank_menu(reversed_items, context()).order] == [4, 7, 2, 5, 3, 6, 1]


def _status(kind: str, *, complete: bool, meal_count: int = 1, **values: Any) -> dict[str, Any]:
    target = {"kind": kind, "value": "2000"} if kind == "exact" else {"kind": kind}
    if kind == "range":
        target = {"kind": "range", "minimum": "2200", "maximum": "2500"}
    entry = {
        "target": target,
        "status": values.get("status", "below_target"),
        "complete": complete,
        "known_subtotal": values.get("known", "1200"),
        "remaining": values.get("remaining", "800"),
        "remaining_to_maximum": values.get("to_maximum"),
    }
    return {"meal_count": meal_count, "nutrients": {NutrientField.CALORIES_KCAL.value: entry}}


def test_kcal_context_reads_exact_and_range_targets() -> None:
    exact = kcal_context(_status("exact", complete=True), None)
    assert (exact.target_max, exact.budget, exact.unknown_items) == (D(2000), D(800), 0)
    ranged = kcal_context(_status("range", complete=True, to_maximum="1300"), None)
    assert (ranged.target_max, ranged.budget) == (D(2500), D(1300))
    unset = kcal_context(_status("unset", complete=False, remaining=None), None)
    assert unset.target_max is None and unset.unknown_items == 1
    totals = TodayTotals(1, (NutrientTotal(NutrientField.CALORIES_KCAL, D(100), D(700), D(950), 0),))
    with_totals = kcal_context(_status("exact", complete=False, remaining=None), totals)
    assert (with_totals.estimate_min, with_totals.estimate_max, with_totals.unknown_items) == (D(700), D(950), 0)
    with pytest.raises(ValueError):
        kcal_context(_status("weird", complete=True), None)
