"""Daily Catch-up v1 AC6: the Telegram LLM sync hint names `/sync` only while the next `daily` would leave days out.

`muscle50 telegram run` with a fake Bot API and a fake LLM provider (the fixtures of `test_telegram_llm_bot.py`:
temporary MUSCLE50_HOME, fixed clock 2026-10-06 12:00 KST, no network, no Garmin), synthetic values only.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
import test_telegram_bot as v1
import test_telegram_llm_bot as bot
from test_telegram_llm_reliability_bot import SYNC_REPLY, SYNC_REQUEST

import muscle50.cli as cli
from muscle50.domain.telegram_commands import help_text
from muscle50.domain.telegram_llm import parse_llm_command
from muscle50.domain.telegram_llm_context import command_lines, known_commands
from muscle50.domain.telegram_llm_prompt import SYNC_HINT_TEXT, TASKS, PromptTask
from muscle50.domain.telegram_sync import SYNC_CONFIRM_INVALID_TEXT
from muscle50.infrastructure.telegram.cli_runner import InProcessCliRunner

home = bot.home  # the autouse fixture of the bot tests
_isolated = v1.sleeps


def _complete(root: Path, day: date) -> None:
    """Activities and recovery `synced` for ``day``, written after it ended."""
    with sqlite3.connect(root / "db" / "muscle50.sqlite3") as connection:
        for kind in ("activities", "recovery"):
            connection.execute(
                "INSERT INTO sync_coverage (provider, data_kind, calendar_date, status, source, command, "
                "synced_at_utc) VALUES ('garmin', ?, ?, 'synced', 'sync', 'daily', ?)",
                (kind, day.isoformat(), datetime(day.year, day.month, day.day, 16, 0, tzinfo=UTC).isoformat()),
            )


def _no_cli(monkeypatch: pytest.MonkeyPatch) -> None:
    def no_cli(self: object, argv: object) -> object:
        pytest.fail("a sync request must not run any CLI command")

    monkeypatch.setattr(InProcessCliRunner, "run", no_cli)


def test_a_gap_older_than_daily_reaches_adds_the_sync_line(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    bot._catalog(capsys)
    bot._llm_config(home)
    _complete(home, date(2026, 9, 23))  # D-13: daily takes 09-29..10-06, 09-24..09-28 stay unsynced
    before = bot._tables(home)
    _no_cli(monkeypatch)

    replies, _err, fake = bot._session(monkeypatch, capsys, bot.FakeProvider(SYNC_REQUEST), bot.text(1, "동기화 해줘"))

    line = "아직 동기화되지 않은 날: 09-24 ~ 09-28 (/daily는 7일 전까지만 받습니다). 받기: /sync 09-24 09-28"
    assert replies == [f"{SYNC_HINT_TEXT}\n{line}\n/daily\n/refresh"]
    assert fake.sent[0][1].endswith("</pre>\n/daily\n/refresh")  # the commands stay /daily and /refresh
    assert bot._tables(home) == before
    (entry,) = bot._history(home)
    assert entry["reply"] == f"{SYNC_HINT_TEXT}\n{line}\n/daily\n/refresh"


def test_a_gap_daily_will_fill_keeps_the_plain_hint(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    bot._catalog(capsys)
    bot._llm_config(home)
    _complete(home, date(2026, 10, 1))  # daily starts on 10-02 and fills the gap itself
    _no_cli(monkeypatch)
    replies, _err, _fake = bot._session(monkeypatch, capsys, bot.FakeProvider(SYNC_REQUEST), bot.text(1, "동기화 해줘"))
    assert replies == [SYNC_REPLY]


def test_an_unreadable_gap_keeps_the_plain_hint(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    bot._catalog(capsys)
    bot._llm_config(home)

    def broken(paths: object) -> object:
        raise RuntimeError("synthetic")

    monkeypatch.setattr(cli, "_older_unsynced", broken)
    _no_cli(monkeypatch)
    replies, err, _fake = bot._session(monkeypatch, capsys, bot.FakeProvider(SYNC_REQUEST), bot.text(1, "동기화 해줘"))
    assert replies == [SYNC_REPLY]
    assert "chat 111: sync gap not read (RuntimeError); sent the plain sync hint" in err


def test_the_answer_rule_points_to_sync_for_days_daily_does_not_fetch() -> None:
    # v2.5's coverage rule named only /daily; with /sync (Daily Catch-up v1) the coach names /sync for days the next
    # /daily leaves out (behind a synced day, or more than 7 days back) and never writes the day count (number guard).
    rule = TASKS[PromptTask.ANSWER]
    assert "/daily 로 동기화하라고 안내합니다" in rule  # the v2.4/v2.5 pin still holds
    assert "/daily 는 마지막으로 동기화된 날의 다음 날부터, 오늘보다 7일 앞까지만 받습니다" in rule
    assert "/daily 대신 /sync <시작> <끝>(적힌 날짜를 MM-DD로)을 안내하고, 일 수는 쓰지 않습니다" in rule


def test_sync_is_a_known_command_and_its_tap_line_is_the_bare_command() -> None:
    # The help line makes /sync a known command (after /daily, so the first three stay /today, /status, /day). An answer
    # naming `/sync 10-09 10-13` gets a bare `/sync` tap line, which sends the usage reply (dates stay in the answer).
    known = known_commands(help_text(True))
    assert known[:3] == ("/today", "/status", "/day")
    assert known.index("/sync") == known.index("/daily") + 1
    answer = "10-09~10-13은 동기화되지 않았습니다. /sync 10-09 10-13 으로 받고, 오늘은 /daily 로 동기화하세요."
    assert command_lines(answer, known) == ("/sync", "/daily")


def test_sync_commands_are_not_llm_commands() -> None:
    for text in ("/sync_ok_a41c", "/sync 10-09 10-18", "/sync"):
        assert parse_llm_command(text, bot_username=v1.IDENTITY.username) is None


def test_sync_commands_reach_the_bot_grammar_with_the_llm_on(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    # With the LLM on every `/...` message meets `parse_llm_command` first; `/sync*` must still be the bot's own.
    bot._llm_config(home)
    _no_cli(monkeypatch)
    provider = bot.FakeProvider()

    replies, _err, _fake = bot._session(
        monkeypatch,
        capsys,
        provider,
        bot.text(1, "/sync 09-20 10-05"),
        bot.text(2, "/sync 10-05 10-09"),
        bot.text(3, "/sync_ok_ffff"),
    )

    assert replies == [
        "16일(09-20 ~ 10-05), Garmin 요청 약 144회입니다. 받아오려면 누르세요(10분 유효):\n/sync_ok_7f3a",
        "오류: 끝 날짜(2026-10-09)가 오늘(2026-10-06) 이후입니다. 작년 날짜는 YYYY-MM-DD로 쓰세요.",
        SYNC_CONFIRM_INVALID_TEXT,
    ]
    assert provider.requests == []  # no LLM call


def test_no_database_keeps_the_plain_hint(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    bot._llm_config(home)
    _no_cli(monkeypatch)
    replies, _err, _fake = bot._session(monkeypatch, capsys, bot.FakeProvider(SYNC_REQUEST), bot.text(1, "동기화 해줘"))
    assert replies == [SYNC_REPLY]
    assert not (home / "db").exists()  # the hint reads read-only and creates nothing
