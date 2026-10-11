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
from muscle50.domain.llm_today_totals import TodayTotals, today_totals, totals_text
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
            "  kcal 확인 165",
            "  단백질 확인 34.95 g",
            "  탄수화물 확인 0 g",
            "  지방 알 수 없음 (값 모르는 항목 1개)",
        ]
    )


def test_estimates_only_and_mixed_with_an_unknown_general_meal(capsys: pytest.CaptureFixture[str]) -> None:
    _log(capsys, "dinner", "--general", "--general-estimate=visual_estimate:kcal=700-950,protein=30-45")
    estimated = _totals(capsys)
    assert estimated.get(NutrientField.CALORIES_KCAL).confirmed is None
    assert totals_text(estimated).split("\n")[1:3] == ["  kcal 추정 700~950", "  단백질 추정 30~45 g"]
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
        "  kcal 확인 110 + 추정 800.5~1150 (값 모르는 항목 1개)",
        "  단백질 확인 23.3 g + 추정 35~55.25 g (값 모르는 항목 1개)",
    ]


def test_voided_meal_is_left_out(capsys: pytest.CaptureFixture[str]) -> None:
    _log(capsys, "dinner", "--general", "--general-estimate=visual_estimate:kcal=700-950")
    _cli(capsys, "nutrition", "meal", "void", f"{DAY}-dinner-1")
    assert _totals(capsys).meal_count == 0


def test_unexpected_shape_is_an_error() -> None:
    with pytest.raises((ValueError, KeyError)):
        today_totals({"meal_count": "1"}, {"meals": []})
