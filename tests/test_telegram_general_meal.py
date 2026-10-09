"""Telegram `/log <meal>[+] 일반식 [메모]` (Nutrition General Meal v1), grammar and end to end.

No network (`urllib.request.urlopen` fails the test), no Garmin login, a fake Bot API, a temporary
MUSCLE50_HOME and synthetic values only.
"""

from __future__ import annotations

import json
import sqlite3
import urllib.request
from datetime import date, datetime, timedelta, timezone, tzinfo
from pathlib import Path
from typing import Any

import pytest
from test_telegram_bot import FakeTelegramApi, update

import muscle50.cli as cli
from muscle50.cli import main
from muscle50.domain.telegram_commands import (
    CliInvocation,
    ReplyKind,
    UsageReason,
    UsageReply,
    parse_bot_message,
    usage_text,
)
from muscle50.infrastructure.garmin.client import PythonGarminConnector
from muscle50.presentation.telegram_summary import TelegramSummaries

KST = timezone(timedelta(hours=9))
TODAY = date(2026, 10, 6)
NOW = datetime(2026, 10, 6, 12, 0, tzinfo=KST)
TOKEN = "123456789:AAFakeSyntheticToken_ab-cd"
ALLOWED = 111
BOT = "muscle50_example_bot"
LUNCH = "2026-10-06-lunch-1"
LOG = ("nutrition", "log", "--meal")
CHICKEN = ["--id", "chicken-breast", "--name", "닭가슴살", "--per", "100", "g"]
CHICKEN += ["--kcal", "110", "--protein", "23", "--carbs", "0", "--fat", "1"]
CHICKEN += ["--source", "user_provided", "--accuracy", "exact"]


def _fail_network(*args: object, **kwargs: object) -> object:
    pytest.fail("no network in tests")


@pytest.fixture(autouse=True)
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "home"
    monkeypatch.setenv("MUSCLE50_HOME", str(root))
    monkeypatch.setattr(urllib.request, "urlopen", _fail_network)
    monkeypatch.setattr(
        PythonGarminConnector, "authenticate", lambda *args, **kwargs: pytest.fail("must not use Garmin")
    )

    def fixed_timezone(day: date) -> tzinfo:
        return KST

    monkeypatch.setattr(cli, "_local_timezone", fixed_timezone)
    monkeypatch.setattr(cli, "_today", lambda: TODAY)
    monkeypatch.setattr(cli, "_now", lambda: NOW)
    monkeypatch.setattr(cli, "_telegram_sleep", lambda seconds: None)
    _configure(root)
    return root


def _configure(root: Path) -> None:
    config = root / "config" / "telegram.json"
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(json.dumps({"bot_token": TOKEN, "allowed_chat_ids": [ALLOWED]}), encoding="utf-8", newline="\n")


def _parse(text: str) -> CliInvocation | UsageReply:
    return parse_bot_message(text, bot_username=BOT, today=TODAY)


def _bot(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], *texts: str, first_id: int = 1
) -> FakeTelegramApi:
    """One `telegram run` session handling ``texts`` as updates first_id.. in order (then Ctrl+C)."""
    fake = FakeTelegramApi([update(index, text) for index, text in enumerate(texts, start=first_id)])
    monkeypatch.setattr(cli, "_telegram_api", lambda token: fake)
    code = main(["telegram", "run"])
    captured = capsys.readouterr()
    assert (code, captured.out) == (130, "")
    return fake


def _cli(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, str, str]:
    code = main(list(argv))
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def _ok(capsys: pytest.CaptureFixture[str], *argv: str) -> str:
    code, out, err = _cli(capsys, *argv)
    assert code == 0, err
    return out


def _database(root: Path) -> Path:
    return root / "db" / "muscle50.sqlite3"


def _tables(database: Path) -> dict[str, list[tuple[Any, ...]]]:
    connection = sqlite3.connect(database)
    try:
        names = [
            row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name")
        ]
        return {name: sorted(connection.execute(f"SELECT * FROM {name}").fetchall(), key=repr) for name in names}
    finally:
        connection.close()


# --- grammar ------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "argv"),
    [
        ("/log lunch 일반식", (*LOG, "lunch", "--general")),
        ("/log lunch 일반식 구내식당", (*LOG, "lunch", "--general", "--general-note=구내식당")),
        ("/log lunch 일반식   제육   볶음 ", (*LOG, "lunch", "--general", "--general-note=제육 볶음")),
        ("/log dinner 일반식, 닭가슴살 100 g", (*LOG, "dinner", "--general", "--item", "닭가슴살", "100", "g")),
        ("/log dinner 닭가슴살 100 g,일반식", (*LOG, "dinner", "--item", "닭가슴살", "100", "g", "--general")),
        (
            "/log lunch+ 일반식 구내식당, 일반식 배달",
            (*LOG, "lunch", "--general", "--general-note=구내식당", "--general", "--general-note=배달", "--additional"),
        ),
        # Only a plain number followed by a unit is the catalog quantity position; anything else is memo.
        ("/log lunch 일반식 1 cup", (*LOG, "lunch", "--general", "--general-note=1 cup")),
        ("/log lunch 일반식 serving", (*LOG, "lunch", "--general", "--general-note=serving")),
        ("/log lunch 일반식 도시락 1", (*LOG, "lunch", "--general", "--general-note=도시락 1")),
        ("/log lunch 일반식 1인분 pack", (*LOG, "lunch", "--general", "--general-note=1인분 pack")),
        # Exactly the word `일반식`: similar words are catalog items, never guessed as a general meal.
        ("/log lunch 일반 1 serving", (*LOG, "lunch", "--item", "일반", "1", "serving")),
        ("/log lunch 일반식사 1 serving", (*LOG, "lunch", "--item", "일반식사", "1", "serving")),
        ("/log lunch 오늘 일반식 1 serving", (*LOG, "lunch", "--item", "오늘 일반식", "1", "serving")),
    ],
)
def test_general_meal_items_map_to_exact_cli_argv(text: str, argv: tuple[str, ...]) -> None:
    result = _parse(text)
    assert isinstance(result, CliInvocation)
    assert result.argv == argv
    assert (result.migrates, result.is_daily, result.adds_undo, result.reply) == (True, False, True, ReplyKind.TEXT)


@pytest.mark.parametrize(
    "text",
    [
        "/log lunch 일반식 1 serving",
        "/log lunch 일반식 제육 2 pack",
        "/log lunch 일반식 1.5 g",
        "/log dinner 닭가슴살 100 g, 일반식 1 serving",
        "/log lunch 일반식 -메모",
        "/log lunch 일반식 --json",
        "/log lunch 일반식,",
        "/log lunch 일반식, , 일반식",
        "/log lunch 일반식구내식당",
        "/log lunch 밥",
        "/log lunch 식사",
        "/log 일반식",
        "/log brunch 일반식",
    ],
)
def test_ambiguous_or_malformed_general_items_get_the_log_usage(text: str) -> None:
    assert _parse(text) == UsageReply(UsageReason.MALFORMED, "log")


# --- end to end -----------------------------------------------------------------------------------------


def test_log_general_stores_the_same_rows_as_the_cli_and_adds_the_undo_line(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path, tmp_path: Path
) -> None:
    cli_home = tmp_path / "cli-home"
    monkeypatch.setenv("MUSCLE50_HOME", str(cli_home))
    cli_text = _ok(capsys, "nutrition", "log", "--meal", "lunch", "--general", "--general-note", "구내식당")
    cli_rows = _tables(_database(cli_home))

    monkeypatch.setenv("MUSCLE50_HOME", str(home))
    fake = _bot(monkeypatch, capsys, "/log lunch 일반식 구내식당")

    assert cli_text.startswith(f"Recorded meal {LUNCH}.\n")
    assert "  1. 일반식 (general meal; note: 구내식당): nutrition unknown\n" in cli_text
    assert fake.replies() == [cli_text.removesuffix("\n") + f"\n취소: /void {LUNCH}"]
    bot_rows = _tables(_database(home))
    for table in ("nutrition_meals", "nutrition_meal_items", "nutrition_food_profiles", "nutrition_facts"):
        assert bot_rows[table] == cli_rows[table]
    assert bot_rows["nutrition_meal_items"] == [(LUNCH, 1, "일반식", "general-meal", None, None, "구내식당")]


def test_mixed_log_and_the_ambiguous_form(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    _ok(capsys, "nutrition", "food", "add", *CHICKEN)
    before = _tables(_database(home))

    fake = _bot(monkeypatch, capsys, "/log lunch 일반식 1 serving", "/log dinner 일반식, 닭가슴살 100 g")

    replies = fake.replies()
    assert replies[0] == usage_text("log")
    assert replies[1].startswith("Recorded meal 2026-10-06-dinner-1.\n")
    assert "  1. 일반식 (general meal): nutrition unknown" in replies[1]
    assert "  2. 닭가슴살 (chicken-breast) 100 g: kcal 110 | P 23 g | C 0 g | F 1 g" in replies[1]
    # The refused message wrote nothing; only the dinner was recorded.
    assert before["nutrition_meals"] == []
    assert [row[0] for row in _tables(_database(home))["nutrition_meals"]] == ["2026-10-06-dinner-1"]


def test_a_too_long_memo_relays_the_cli_error_and_writes_nothing(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    _ok(capsys, "nutrition", "food", "add", *CHICKEN)
    before = _tables(_database(home))
    memo = "가" * 101

    fake = _bot(monkeypatch, capsys, f"/log lunch 일반식 {memo}")

    code, out, err = _cli(capsys, "nutrition", "log", "--meal", "lunch", "--general", f"--general-note={memo}")
    assert (code, out) == (1, "")
    assert fake.replies() == [err.removesuffix("\n")]
    assert fake.replies() == [
        "오류: item 1: --general-note must be at most 100 characters (got 101). Nothing was changed."
    ]
    assert _tables(_database(home)) == before


def test_status_summary_of_a_general_meal_day_is_unknown_without_remaining(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _ok(capsys, "nutrition", "target", "set", "kcal", "--range", "2200", "2500")
    _ok(capsys, "nutrition", "target", "set", "protein", "--exact", "120")
    _bot(monkeypatch, capsys, "/log lunch 일반식")
    status = json.loads(_ok(capsys, "nutrition", "status", "--json"))

    fake = _bot(monkeypatch, capsys, "/status", first_id=2)

    assert [message for _, message in fake.sent] == TelegramSummaries().summary(ReplyKind.STATUS_SUMMARY, status)
    text = fake.sent[0][1]
    assert "kcal 알 수 없음 / 목표 2200-2500 (indeterminate)" in text
    assert "단백질 알 수 없음 / 목표 120 g (indeterminate)" in text
    assert "남음" not in text
