"""AC5 of docs/specs/telegram-llm-reliability.md: `telegram\\run-YYYY-MM.log`.

The file keeps the console lines (redacted, ASCII) and the file-only lines `run started`, `alive` and
`run stopped: <reason>`. It holds no message text and no token, it is append-only, and a write failure is
ignored. The fixtures are those of the Telegram LLM bot tests: a temporary MUSCLE50_HOME, never production.
"""

from __future__ import annotations

import ctypes
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import test_telegram_bot as v1
import test_telegram_llm_bot as llm

from muscle50.cli import main
from muscle50.domain.telegram_commands import HELP_TEXT
from muscle50.infrastructure.telegram import run_log
from muscle50.infrastructure.telegram.run_log import (
    RunLog,
    console_event_handler,
    install_console_event_hook,
)

# Autouse fixtures: a temporary MUSCLE50_HOME (never production), fixed clock, no real sleep.
home = llm.home

KST = timezone(timedelta(hours=9))
START = datetime(2026, 10, 16, 9, 0, 0, tzinfo=KST)
LOG_NAME = "run-2026-10.log"


class Clock:
    def __init__(self, now: datetime = START) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


def _lines(path: Path) -> list[str]:
    return path.read_text(encoding="ascii").splitlines()


# --- RunLog ---------------------------------------------------------------------------------------------------


def test_started_line_stamp_and_ascii(tmp_path: Path) -> None:
    directory = tmp_path / "telegram"
    log = RunLog(directory, Clock())
    log.started(4242, llm_on=True)
    log.line("telegram run: bot @example_bot is polling for 1 allowed chat. Press Ctrl+C to stop.")
    log.line("reply to chat 111 was not delivered (연결)")
    log.stopped("ctrl_c")
    assert _lines(directory / LOG_NAME) == [
        "2026-10-16 09:00:00 run started pid=4242 llm=on",
        "2026-10-16 09:00:00 telegram run: bot @example_bot is polling for 1 allowed chat. Press Ctrl+C to stop.",
        "2026-10-16 09:00:00 reply to chat 111 was not delivered (\\uc5f0\\uacb0)",
        "2026-10-16 09:00:00 run stopped: ctrl_c",
    ]


def test_llm_off_is_recorded(tmp_path: Path) -> None:
    log = RunLog(tmp_path, Clock())
    log.started(7, llm_on=False)
    assert _lines(tmp_path / LOG_NAME) == ["2026-10-16 09:00:00 run started pid=7 llm=off"]


def test_a_multi_line_text_is_one_stamped_line_per_line(tmp_path: Path) -> None:
    log = RunLog(tmp_path, Clock())
    log.line("Traceback (most recent call last):\n  File x\nRuntimeError")
    assert _lines(tmp_path / LOG_NAME) == [
        "2026-10-16 09:00:00 Traceback (most recent call last):",
        "2026-10-16 09:00:00   File x",
        "2026-10-16 09:00:00 RuntimeError",
    ]


def test_the_file_is_appended_to_by_a_second_run(tmp_path: Path) -> None:
    RunLog(tmp_path, Clock()).started(1, llm_on=False)
    RunLog(tmp_path, Clock()).started(2, llm_on=False)
    assert [line.split(" ", 2)[2] for line in _lines(tmp_path / LOG_NAME)] == [
        "run started pid=1 llm=off",
        "run started pid=2 llm=off",
    ]


def test_the_month_comes_from_the_clock_on_each_write(tmp_path: Path) -> None:
    clock = Clock(datetime(2026, 10, 31, 23, 59, 59, tzinfo=KST))
    log = RunLog(tmp_path, clock)
    log.line("before midnight")
    clock.advance(2)
    log.line("after midnight")
    assert _lines(tmp_path / "run-2026-10.log") == ["2026-10-31 23:59:59 before midnight"]
    assert _lines(tmp_path / "run-2026-11.log") == ["2026-11-01 00:00:01 after midnight"]


def test_alive_is_written_every_30_minutes_of_the_injected_clock(tmp_path: Path) -> None:
    clock = Clock()
    log = RunLog(tmp_path, clock)
    log.started(1, llm_on=False)
    clock.advance(1799)
    log.tick()
    assert len(_lines(tmp_path / LOG_NAME)) == 1  # not yet
    clock.advance(1)
    log.tick()
    log.tick()  # the same instant: once only
    assert _lines(tmp_path / LOG_NAME)[1:] == ["2026-10-16 09:30:00 alive"]
    clock.advance(1800)
    log.tick()
    assert _lines(tmp_path / LOG_NAME)[2:] == ["2026-10-16 10:00:00 alive"]


def test_a_write_failure_is_ignored(tmp_path: Path) -> None:
    blocker = tmp_path / "telegram"
    blocker.write_text("not a directory", encoding="utf-8")  # mkdir and open both fail
    log = RunLog(blocker, Clock())
    log.started(1, llm_on=True)
    log.line("x")
    log.tick()
    log.stopped("ctrl_c")
    assert blocker.read_text(encoding="utf-8") == "not a directory"


def test_a_failing_clock_does_not_reach_the_caller(tmp_path: Path) -> None:
    clock = Clock()
    log = RunLog(tmp_path, clock)

    def broken() -> datetime:
        raise RuntimeError("clock")

    log._now = broken
    log.tick()
    log.line("x")
    assert not (tmp_path / LOG_NAME).exists()


# --- the console event hook -----------------------------------------------------------------------------------


def test_the_handler_returns_zero_for_every_event_and_reports_only_the_closing_ones() -> None:
    seen: list[int] = []
    handler = console_event_handler(seen.append)
    assert [handler(event) for event in range(0, 8)] == [0] * 8
    assert seen == [1, 2, 5, 6]


def test_the_handler_swallows_a_failing_callback() -> None:
    def broken(event: int) -> None:
        raise RuntimeError("log failure")

    assert console_event_handler(broken)(2) == 0


def test_installing_the_hook_does_not_raise_without_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[int] = []
    remove = install_console_event_hook(seen.append, platform="linux")
    remove()
    monkeypatch.setattr(ctypes, "windll", None, raising=False)
    install_console_event_hook(seen.append, platform="win32")()
    monkeypatch.delattr(ctypes, "windll", raising=False)
    install_console_event_hook(seen.append, platform="win32")()
    assert seen == []


@pytest.mark.skipif(sys.platform != "win32", reason="SetConsoleCtrlHandler is Windows only")
def test_the_hook_registers_and_removes_on_windows() -> None:
    remove = install_console_event_hook(lambda event: None)
    assert len(run_log._CALLBACKS) == 1
    remove()
    assert run_log._CALLBACKS == []


# --- through `telegram run` -----------------------------------------------------------------------------------

STAMP = "2026-10-06 12:00:00 "


def _expected_console(*extra: str) -> list[str]:
    return [v1.START_LINE, *extra]


def test_llm_off_run_writes_the_file_and_leaves_the_console_unchanged(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    fake = v1.FakeTelegramApi([v1.update(1, "/help", sent=v1.NOW_TS), v1.update(2, "hello", chat=v1.OTHER)])
    code, err = v1._run_bot(monkeypatch, capsys, fake)
    assert code == 130
    assert err.split("\n") == [
        v1.START_LINE,
        "chat 111: usage reply (help)",
        "ignored message from chat 987654321 (not in allowed_chat_ids)",
        "",
        "취소되었습니다.",
        "",
    ]
    lines = _lines(home / "telegram" / LOG_NAME)
    assert lines[0] == f"{STAMP}run started pid={os.getpid()} llm=off"
    assert lines[1:4] == [
        f"{STAMP}{v1.START_LINE}",
        f"{STAMP}chat 111: usage reply (help)",
        f"{STAMP}ignored message from chat 987654321 (not in allowed_chat_ids)",
    ]
    assert lines[-1] == f"{STAMP}run stopped: ctrl_c"
    assert not any("alive" in line for line in lines)


def test_the_console_has_no_file_only_lines(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fake = v1.FakeTelegramApi([])
    _, err = v1._run_bot(monkeypatch, capsys, fake)
    assert "run started" not in err and "run stopped" not in err and "alive" not in err


def test_llm_on_run_records_llm_on(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    llm._llm_config(home)
    replies, err, _fake = llm._session(monkeypatch, capsys, llm.FakeProvider())
    assert replies == []
    lines = _lines(home / "telegram" / LOG_NAME)
    assert lines[0] == f"{STAMP}run started pid={os.getpid()} llm=on"
    assert any(line.startswith(f"{STAMP}telegram llm: on, provider claude") for line in lines)
    assert lines[-1] == f"{STAMP}run stopped: ctrl_c"
    assert "telegram llm: on" in err


def test_no_message_text_and_no_token_reach_the_file(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    secret = "비밀메시지-secret-phrase"
    fake = v1.FakeTelegramApi(
        [v1.update(1, secret), v1.update(2, f"/log lunch {secret} 1 g"), v1.update(3, secret, chat=v1.OTHER)]
    )
    v1._run_bot(monkeypatch, capsys, fake)
    content = (home / "telegram" / LOG_NAME).read_text(encoding="ascii")
    assert secret not in content and "secret-phrase" not in content and v1.TOKEN not in content
    assert content.isascii()


def test_a_corrupt_state_file_records_the_stop_reason(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    (home / "config" / "telegram_state.json").write_text("{not json", encoding="utf-8")
    fake = v1.FakeTelegramApi([v1.update(1, "/help")])
    v1._install(monkeypatch, fake)
    assert main(["telegram", "run"]) == 1
    capsys.readouterr()
    lines = _lines(home / "telegram" / LOG_NAME)
    assert lines[0].endswith("llm=off") and lines[-1] == f"{STAMP}run stopped: error TelegramStateError"


def test_a_bad_llm_config_stops_before_the_log_exists(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    (home / "config" / "telegram_llm.json").write_text("{bad", encoding="utf-8")
    v1._install(monkeypatch, v1.FakeTelegramApi())
    assert main(["telegram", "run"]) == 1
    capsys.readouterr()
    assert not (home / "telegram").exists()


def test_an_unexpected_exception_is_recorded_and_still_raised(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    class Crash(Exception):
        pass

    def crash(*args: object, **kwargs: object) -> None:
        raise Crash("synthetic")

    monkeypatch.setattr("muscle50.cli.RunTelegramBot.execute", crash)
    v1._install(monkeypatch, v1.FakeTelegramApi())
    with pytest.raises(Crash):
        main(["telegram", "run"])
    capsys.readouterr()
    assert _lines(home / "telegram" / LOG_NAME)[-1] == f"{STAMP}run stopped: error Crash"


def test_a_run_log_that_cannot_be_written_does_not_change_the_run(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    (home / "telegram").write_text("a file where the directory should be", encoding="utf-8")
    fake = v1.FakeTelegramApi([v1.update(1, "/help")])
    code, err = v1._run_bot(monkeypatch, capsys, fake)
    assert code == 130 and fake.replies() == [HELP_TEXT]
    assert err.split("\n")[0] == v1.START_LINE


def test_the_console_event_hook_is_installed_and_removed_around_the_run(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    events: list[str] = []

    def install(on_event: object) -> object:
        events.append("install")
        return lambda: events.append("remove")

    monkeypatch.setattr("muscle50.cli.install_console_event_hook", install)
    v1._run_bot(monkeypatch, capsys, v1.FakeTelegramApi([]))
    assert events == ["install", "remove"]
