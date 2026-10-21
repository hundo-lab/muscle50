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
from muscle50.domain.telegram_llm_prompt import SYNC_HINT_TEXT
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


def test_no_database_keeps_the_plain_hint(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    bot._llm_config(home)
    _no_cli(monkeypatch)
    replies, _err, _fake = bot._session(monkeypatch, capsys, bot.FakeProvider(SYNC_REQUEST), bot.text(1, "동기화 해줘"))
    assert replies == [SYNC_REPLY]
    assert not (home / "db").exists()  # the hint reads read-only and creates nothing
