"""Telegram LLM v2.3 end to end: label values, follow-up corrections, overlap with `/fix_`, the logged day's totals,
portions and a recent menu item picked by name. `muscle50 telegram run` with a fake Bot API and a fake LLM provider
(never the real `claude`/`codex`, never the network), a temporary MUSCLE50_HOME and synthetic foods only. Covers
AC1-AC13 of docs/specs/telegram-llm-corrections.md."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import test_telegram_llm_bot as bot
import test_telegram_llm_meals_bot as meals
from test_telegram_llm_meals_bot import catalog_item, dishes, est, item

home = bot.home  # the autouse fixture of the bot tests: temporary MUSCLE50_HOME, fake clock, no network


def prepare(capsys: pytest.CaptureFixture[str], home: Path) -> None:
    bot._catalog(capsys)
    bot._llm_config(home)


def say(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    document: dict[str, Any] | None,
    update_id: int,
    words: str,
) -> tuple[list[str], bot.FakeProvider]:
    provider = bot.FakeProvider(*([document] if document is not None else []))
    replies, _err, _fake = bot._session(monkeypatch, capsys, provider, bot.text(update_id, words))
    return replies, provider


# --- AC11: the totals are those of the logged day ---------------------------------------------------------------------


def test_a_past_day_is_confirmed_with_that_days_totals_and_today_keeps_its_label(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    prepare(capsys, home)
    yesterday = dishes(item("국밥", "dinner", estimate=est((600, 700), (20, 30))), date_expression="yesterday")
    say(monkeypatch, capsys, yesterday, 1, "어제 저녁 국밥")
    replies, _provider = say(monkeypatch, capsys, None, 2, "/ok_7f3a")
    assert replies[0].split("\n")[-4:] == [
        "  kcal 600~700",
        "  단백질 20~30 g",
        "  탄수화물 알 수 없음 (값 모르는 항목 1개 빠짐)",
        "  지방 알 수 없음 (값 모르는 항목 1개 빠짐)",
    ]
    assert "10-05 누적 (추정 포함):" in replies[0] and "오늘 누적" not in replies[0]
    # a record for today keeps the v2 label; the other day's meal is not in it
    say(monkeypatch, capsys, dishes(catalog_item("닭가슴살", "lunch", 1, "pack")), 3, "점심 닭가슴살")
    replies, _provider = say(monkeypatch, capsys, None, 4, "/ok_91c0")
    assert "\n오늘 누적:\n  kcal 165\n" in replies[0] and "10-05" not in replies[0].split("취소: /void")[1]
    assert meals.meal_tables(home)["nutrition_meals"]
