"""Telegram LLM v2 `today_totals`: confirmed values and estimated ranges apart; unknown is never 0.

The documents are produced by the real CLI (`nutrition status/day --json`) on a temporary home.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone, tzinfo
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

import muscle50.cli as cli
from muscle50.cli import main
from muscle50.domain.llm_number_guard import allowed_numbers, unknown_numbers
from muscle50.domain.llm_today_totals import (
    NutrientTotal,
    TodayTotals,
    display_amount,
    today_totals,
    totals_text,
)
from muscle50.domain.nutrition import NutrientField

KST = timezone(timedelta(hours=9))
DAY = "2026-10-12"
CHICKEN = ["--id", "chicken-breast", "--name", "닭가슴살", "--per", "100", "g", "--kcal", "110", "--protein", "23.3"]
CHICKEN += ["--carbs", "0", "--fat", "unknown", "--source", "nutrition_label", "--accuracy", "exact"]


@pytest.fixture(autouse=True)
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "home"
    monkeypatch.setenv("MUSCLE50_HOME", str(root))

    def fixed_timezone(day: date) -> tzinfo:
        return KST

    monkeypatch.setattr(cli, "_local_timezone", fixed_timezone)
    monkeypatch.setattr(cli, "_today", lambda: date(2026, 10, 12))
    monkeypatch.setattr(cli, "_now", lambda: datetime(2026, 10, 12, 12, 0, tzinfo=KST))
    return root


def _cli(capsys: pytest.CaptureFixture[str], *argv: str) -> Any:
    assert main(list(argv)) == 0
    out = capsys.readouterr().out
    return json.loads(out) if "--json" in argv else out


def _totals(capsys: pytest.CaptureFixture[str]) -> TodayTotals:
    status = _cli(capsys, "nutrition", "status", "--date", DAY, "--json")
    day = _cli(capsys, "nutrition", "day", "--date", DAY, "--json")
    return today_totals(status, day)


def _log(capsys: pytest.CaptureFixture[str], meal: str, *entries: str) -> None:
    _cli(capsys, "nutrition", "log", "--date", DAY, "--meal", meal, "--additional", *entries)


def test_no_meals_is_no_record_not_zero(capsys: pytest.CaptureFixture[str]) -> None:
    totals = _totals(capsys)
    assert totals.meal_count == 0
    assert totals_text(totals) == "오늘 누적: 오늘 기록 없음 (0이 아님)"


def test_confirmed_only(capsys: pytest.CaptureFixture[str]) -> None:
    _cli(capsys, "nutrition", "food", "add", *CHICKEN)
    _log(capsys, "lunch", "--item", "chicken-breast", "150", "g")
    assert totals_text(_totals(capsys)) == "\n".join(
        [
            "오늘 누적:",
            "  kcal 165",
            "  단백질 35 g",  # 34.95 is shown the way the CLI rounds it (0.1, half-even)
            "  탄수화물 0 g",
            "  지방 알 수 없음 (값 모르는 항목 1개 빠짐)",
        ]
    )


def test_estimates_only_and_mixed_with_an_unknown_general_meal(capsys: pytest.CaptureFixture[str]) -> None:
    _log(capsys, "dinner", "--general", "--general-estimate=visual_estimate:kcal=700-950,protein=30-45")
    estimated = _totals(capsys)
    assert estimated.get(NutrientField.CALORIES_KCAL).confirmed is None
    assert totals_text(estimated).split("\n")[:3] == ["오늘 누적 (추정 포함):", "  kcal 700~950", "  단백질 30~45 g"]
    _cli(capsys, "nutrition", "food", "add", *CHICKEN)
    _log(capsys, "lunch", "--item", "chicken-breast", "100", "g")
    _log(capsys, "snack", "--general", "--general-estimate=language_estimate:kcal=100.5-200,protein=5-10.25")
    _log(capsys, "snack", "--general", "--general-note=모름")
    totals = _totals(capsys)
    kcal = totals.get(NutrientField.CALORIES_KCAL)
    assert (kcal.confirmed, kcal.estimate_min, kcal.estimate_max, kcal.unknown_items) == (
        Decimal(110),
        Decimal("800.5"),
        Decimal(1150),
        1,
    )
    assert totals_text(totals).split("\n")[1:3] == [
        "  kcal 910.5~1260 (값 모르는 항목 1개 빠짐)",
        "  단백질 58.3~78.6 g (값 모르는 항목 1개 빠짐)",
    ]


def test_voided_meal_is_left_out(capsys: pytest.CaptureFixture[str]) -> None:
    _log(capsys, "dinner", "--general", "--general-estimate=visual_estimate:kcal=700-950")
    _cli(capsys, "nutrition", "meal", "void", f"{DAY}-dinner-1")
    assert _totals(capsys).meal_count == 0


def test_unexpected_shape_is_an_error() -> None:
    with pytest.raises((ValueError, KeyError)):
        today_totals({"meal_count": "1"}, {"meals": []})


# --- v2.3: one range per nutrient, the logged day, CLI display rounding ---------------------------------------------


def _total(nutrient: NutrientField, confirmed: str | None, low: str | None, high: str | None, unknown: int = 0) -> Any:
    return NutrientTotal(
        nutrient,
        Decimal(confirmed) if confirmed is not None else None,
        Decimal(low) if low is not None else None,
        Decimal(high) if high is not None else None,
        unknown,
    )


def _all_nutrients(**by_nutrient: Any) -> TodayTotals:
    nutrients = []
    for nutrient in NutrientField:
        nutrients.append(by_nutrient.get(nutrient.name) or _total(nutrient, "1", None, None))
    return TodayTotals(1, tuple(nutrients))


def test_the_range_adds_confirmed_values_to_the_estimate_bounds() -> None:
    totals = _all_nutrients(CALORIES_KCAL=_total(NutrientField.CALORIES_KCAL, "240", "360", "380"))
    assert totals_text(totals).split("\n")[:2] == ["오늘 누적 (추정 포함):", "  kcal 600~620"]


def test_equal_bounds_are_one_number_and_no_estimate_means_no_marker() -> None:
    totals = _all_nutrients(CALORIES_KCAL=_total(NutrientField.CALORIES_KCAL, "240", "360", "360"))
    assert totals_text(totals).split("\n")[:2] == ["오늘 누적 (추정 포함):", "  kcal 600"]
    assert totals_text(_all_nutrients()).split("\n")[0] == "오늘 누적:"


def test_an_unknown_item_is_counted_and_never_added_as_zero() -> None:
    totals = _all_nutrients(
        FAT_G=_total(NutrientField.FAT_G, None, None, None, 2),
        CARBOHYDRATE_G=_total(NutrientField.CARBOHYDRATE_G, "37", None, None, 1),
    )
    lines = totals_text(totals).split("\n")
    assert lines[3] == "  탄수화물 37 g (값 모르는 항목 1개 빠짐)"
    assert lines[4] == "  지방 알 수 없음 (값 모르는 항목 2개 빠짐)"


def test_another_day_is_labelled_with_its_date_and_an_empty_day_is_not_zero() -> None:
    totals = _all_nutrients(PROTEIN_G=_total(NutrientField.PROTEIN_G, "20", "3", "5"))
    assert totals_text(totals, "10-14").split("\n")[0] == "10-14 누적 (추정 포함):"
    assert totals_text(TodayTotals(0, ()), "10-14") == "10-14 기록 없음 (0이 아님)"
    assert totals_text(TodayTotals(0, ())) == "오늘 누적: 오늘 기록 없음 (0이 아님)"


@pytest.mark.parametrize(
    ("value", "shown"),
    [
        ("1.95", "2"),  # the failing case of 2026-10-15: CLI says `P 2 g`
        ("0.05", "0"),
        ("0.15", "0.2"),
        ("0.25", "0.2"),
        ("34.95", "35"),
        ("1150", "1150"),
        ("30.5", "30.5"),
        ("0.04", "0"),
    ],
)
def test_display_amount_rounds_like_the_cli(value: str, shown: str) -> None:
    assert display_amount(Decimal(value)) == shown


def test_a_quoted_range_passes_the_number_guard_and_an_invented_sum_does_not() -> None:
    totals = _all_nutrients(CALORIES_KCAL=_total(NutrientField.CALORIES_KCAL, "240", "360", "380"))
    allowed = allowed_numbers([totals_text(totals)])
    assert unknown_numbers("오늘 kcal은 600에서 620 사이예요.", allowed) == ()
    assert unknown_numbers("오늘 kcal은 611이에요.", allowed) == (Decimal(611),)
