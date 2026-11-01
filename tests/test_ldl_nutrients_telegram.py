"""LDL Nutrients v1, D10: a Telegram `change_estimate` keeps the stored satfat=/fiber= ranges.

`muscle50 telegram run` with a fake Bot API and a fake LLM provider (never the real CLIs, never the
network), a temporary MUSCLE50_HOME and synthetic values only.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import test_telegram_llm_bot as bot
import test_telegram_llm_meals_bot as meals
from test_telegram_llm_corrections_bot import edit_doc, prepare, say
from test_telegram_llm_domain import NULL_ESTIMATE

home = bot.home  # the autouse fixture of the bot tests: temporary MUSCLE50_HOME, fake clock, no network

ESTIMATE = "language_estimate:kcal=800-1100,fat=50-70,satfat=15-25,fiber=2-4"


def _log_general(capsys: pytest.CaptureFixture[str]) -> None:
    bot._ok(
        capsys,
        *("nutrition", "log", "--meal", "dinner", "--general", "--general-note=SynBBQ"),
        f"--general-estimate={ESTIMATE}",
    )


def _stored_optional(capsys: pytest.CaptureFixture[str]) -> object:
    document = json.loads(bot._ok(capsys, "nutrition", "meal", "show", "2026-10-06-dinner-1", "--json"))
    return {
        name: (entry["minimum"], entry["maximum"]) if entry is not None else None
        for name, entry in document["items"][-1]["ldl_nutrients"].items()
    }


def test_a_memo_only_edit_keeps_the_stored_satfat_and_fiber_ranges(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    prepare(capsys, home)
    _log_general(capsys)
    document = edit_doc(
        "change_estimate", refers=None, meal_type="dinner", target_food_text="SynBBQ", new_memo="SynBBQ big"
    )
    say(monkeypatch, capsys, document, 1, "그거 큰 거였어")
    argv = meals.state_proposals(home)[0]["argv_ok"]
    assert "--general-estimate=language_estimate:kcal=800-1100,fat=50-70,satfat=15-25,fiber=2-4" in argv
    say(monkeypatch, capsys, None, 2, "/ok_7f3a")
    assert _stored_optional(capsys) == {"saturated_fat_g": ("15", "25"), "fiber_g": ("2", "4")}


def test_an_estimate_edit_keeps_the_stored_satfat_and_fiber_ranges(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    prepare(capsys, home)
    _log_general(capsys)
    document = edit_doc(
        "change_estimate",
        refers=None,
        meal_type="dinner",
        target_food_text="SynBBQ",
        estimate={**NULL_ESTIMATE, "kcal_min": 900, "kcal_max": 1000},
    )
    say(monkeypatch, capsys, document, 1, "900에서 1000 kcal 정도")
    argv = meals.state_proposals(home)[0]["argv_ok"]
    estimate = next(arg for arg in argv if arg.startswith("--general-estimate="))
    assert estimate == "--general-estimate=language_estimate:kcal=900-1000,fat=50-70,satfat=15-25,fiber=2-4"


def test_an_estimate_without_satfat_or_fiber_is_sent_exactly_as_before(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    prepare(capsys, home)
    bot._ok(
        capsys,
        *("nutrition", "log", "--meal", "dinner", "--general", "--general-note=SynBBQ"),
        "--general-estimate=language_estimate:kcal=800-1100,fat=50-70",
    )
    document = edit_doc(
        "change_estimate", refers=None, meal_type="dinner", target_food_text="SynBBQ", new_memo="SynBBQ big"
    )
    say(monkeypatch, capsys, document, 1, "그거 큰 거였어")
    argv = meals.state_proposals(home)[0]["argv_ok"]
    assert "--general-estimate=language_estimate:kcal=800-1100,fat=50-70" in argv
