"""AC4 of docs/specs/telegram-llm-reliability.md: the bot survives what it did not expect.

- The Bot API adapter raises only `TelegramUnavailableError` (ASCII, no token, no chained error).
- An unexpected exception while handling a message is logged and the next message is handled; five in a row
  stop the bot (exit 1); a state-file error still stops it at once.
- A failed `os.replace` is retried on `PermissionError`.
- A console that went away does not stop the bot.

No network, no Garmin, a temporary MUSCLE50_HOME, synthetic values only.
"""

from __future__ import annotations

import http.client
import io
import json
import ssl
import sys
import traceback
import urllib.error
import urllib.request
from collections.abc import Callable, Sequence
from datetime import date
from pathlib import Path
from typing import Any

import pytest
import test_telegram_bot as v1

import muscle50.cli as cli
from muscle50.application.telegram_bot import (
    MAX_UNEXPECTED_IN_A_ROW,
    BotIdentity,
    CommandOutcome,
    HandledUpdates,
    IncomingMessage,
    IncomingUpdate,
    RunTelegramBot,
    TelegramRunStoppedError,
    TelegramStateError,
    TelegramTokenRejectedError,
    TelegramUnavailableError,
)
from muscle50.cli import main
from muscle50.domain.telegram_commands import HELP_TEXT, unexpected_error_text
from muscle50.infrastructure.telegram import bot_api
from muscle50.infrastructure.telegram.bot_api import UrllibTelegramBotApi
from muscle50.infrastructure.telegram.llm_state_store import JsonLlmStateStore
from muscle50.infrastructure.telegram.state_store import REPLACE_RETRY_DELAYS_S, JsonHandledUpdateStore
from muscle50.presentation.telegram_summary import TelegramSummaries

# The autouse fixtures of the v1 bot tests: a temporary MUSCLE50_HOME (never production) and a recorded sleep.
home = v1.home
sleeps = v1.sleeps

TOKEN = v1.TOKEN
CHAT = v1.ALLOWED
NOW = 1_790_000_000


# --- the adapter raises only TelegramUnavailableError -----------------------------------------------------


def _raising(exc: BaseException) -> Callable[..., Any]:
    def respond(*args: object, **kwargs: object) -> Any:
        raise exc

    return respond


UNEXPECTED: list[BaseException] = [
    ConnectionResetError(10054, "reset"),
    TimeoutError("timed out"),
    http.client.RemoteDisconnected(f"closed {TOKEN}"),
    ssl.SSLError(1, f"bad {TOKEN}"),
    RuntimeError(f"surprise carrying {TOKEN} and 연결"),
    KeyError(TOKEN),
]


def _calls(api: UrllibTelegramBotApi) -> dict[str, Callable[[], object]]:
    return {
        "get_me": api.get_me,
        "webhook_is_set": api.webhook_is_set,
        "get_updates": lambda: api.get_updates(None, 10),
        "send_message": lambda: api.send_message(CHAT, "<pre>x</pre>"),
        "download_photo": lambda: api.download_photo("file-1", 1000),
    }


@pytest.mark.parametrize("exc", UNEXPECTED, ids=lambda exc: type(exc).__name__)
@pytest.mark.parametrize("method", ["get_me", "webhook_is_set", "get_updates", "send_message", "download_photo"])
def test_the_adapter_raises_only_telegram_unavailable_error(
    monkeypatch: pytest.MonkeyPatch, method: str, exc: BaseException
) -> None:
    monkeypatch.setattr(urllib.request, "urlopen", _raising(exc))
    with pytest.raises(TelegramUnavailableError) as raised:
        _calls(UrllibTelegramBotApi(TOKEN))[method]()
    message = str(raised.value)
    assert message.isascii() and TOKEN not in message
    assert raised.value.__cause__ is None and raised.value.__context__ is None
    rendered = "".join(traceback.format_exception(raised.value))
    assert TOKEN not in rendered


def test_an_exception_outside_the_expected_families_is_an_unexpected_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(urllib.request, "urlopen", _raising(RuntimeError(f"carries {TOKEN}")))
    with pytest.raises(TelegramUnavailableError) as raised:
        UrllibTelegramBotApi(TOKEN).get_me()
    assert str(raised.value) == "unexpected error (RuntimeError)"
    assert not isinstance(raised.value, TelegramTokenRejectedError)


def test_a_file_download_failure_names_the_number(monkeypatch: pytest.MonkeyPatch) -> None:
    def respond(request: urllib.request.Request, timeout: float) -> Any:
        if "/file/bot" in request.full_url:
            raise ConnectionResetError(10054, "reset")
        return io.BytesIO(json.dumps({"ok": True, "result": {"file_path": "photos/a.jpg"}}).encode("utf-8"))

    monkeypatch.setattr(urllib.request, "urlopen", respond)
    with pytest.raises(TelegramUnavailableError) as raised:
        UrllibTelegramBotApi(TOKEN).download_photo("file-1", 1000)
    assert str(raised.value) == "network error (WinError 10054 connection reset by remote host)"


def test_a_malformed_get_updates_item_is_an_unavailable_error(monkeypatch: pytest.MonkeyPatch) -> None:
    body = json.dumps({"ok": True, "result": [{"update_id": 1, "message": {}}]}).encode("utf-8")
    monkeypatch.setattr(urllib.request, "urlopen", lambda request, timeout: io.BytesIO(body))

    def explode(item: object) -> IncomingUpdate:
        raise ValueError(f"cannot parse {TOKEN}")

    monkeypatch.setattr(bot_api, "_update", explode)
    with pytest.raises(TelegramUnavailableError) as raised:
        UrllibTelegramBotApi(TOKEN).get_updates(None, 10)
    assert str(raised.value) == "unexpected error (ValueError)"
    assert raised.value.__cause__ is None and raised.value.__context__ is None


# --- the loop guard ------------------------------------------------------------------------------------------


class MemoryStore:
    def __init__(self, fail: Exception | None = None) -> None:
        self.saved: list[HandledUpdates] = []
        self.fail = fail

    def load(self) -> HandledUpdates | None:
        return None

    def save(self, handled: HandledUpdates) -> None:
        if self.fail is not None:
            raise self.fail
        self.saved.append(handled)


class ScriptedApi:
    """Returns each batch once; a batch that is an Exception is raised; at the end it raises Ctrl+C."""

    def __init__(self, *batches: Sequence[IncomingUpdate] | Exception) -> None:
        self.batches = list(batches)
        self.sent: list[tuple[int, str]] = []
        self.send_error: Exception | None = None

    def get_me(self) -> BotIdentity:
        return v1.IDENTITY

    def webhook_is_set(self) -> bool:
        return False

    def get_updates(self, offset: int | None, timeout_s: int) -> tuple[IncomingUpdate, ...]:
        if not self.batches:
            raise KeyboardInterrupt
        batch = self.batches.pop(0)
        if isinstance(batch, Exception):
            raise batch
        return tuple(batch)

    def send_message(self, chat_id: int, html: str) -> None:
        if self.send_error is not None:
            raise self.send_error
        self.sent.append((chat_id, html))


class Runner:
    def __init__(self) -> None:
        self.runs: list[tuple[str, ...]] = []

    def run(self, argv: Sequence[str]) -> CommandOutcome:
        self.runs.append(tuple(argv))
        return CommandOutcome(0, "ok\n", "")


def _message(update_id: int, text: str = "/status", chat: int = CHAT) -> IncomingUpdate:
    return IncomingUpdate(update_id, IncomingMessage(chat, text, NOW))


def _bot(
    api: ScriptedApi,
    *,
    store: MemoryStore | None = None,
    pending: Callable[[], tuple[int, ...] | None] = lambda: (),
    format_reply: Callable[[str], Sequence[str]] = lambda text: [text],
    log: Callable[[str], None] | None = None,
    runner: Runner | None = None,
    lines: list[str] | None = None,
    on_idle: Callable[[], None] | None = None,
) -> RunTelegramBot:
    sink = lines if lines is not None else []
    return RunTelegramBot(
        api,
        store or MemoryStore(),
        runner or Runner(),
        allowed_chat_ids=frozenset({CHAT}),
        today=lambda: date(2026, 10, 6),
        pending_migrations=pending,
        format_reply=format_reply,
        summaries=TelegramSummaries(),
        unknown_sets=lambda activity_id: None,
        log=log or sink.append,
        sleep=lambda seconds: None,
        clock=lambda: float(NOW),
        on_idle=on_idle,
    )


def _boom_on(texts: set[str]) -> Callable[[str], Sequence[str]]:
    def format_reply(text: str) -> Sequence[str]:
        if text in texts:
            raise RuntimeError("synthetic reply failure")
        return [text]

    return format_reply


def test_a_raising_hook_is_logged_and_the_next_message_is_handled() -> None:
    runner = Runner()
    lines: list[str] = []
    calls = {"count": 0}

    def pending() -> tuple[int, ...]:
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("synthetic")
        return ()

    # /log migrates, so `pending` runs for it; /status does not.
    api = ScriptedApi([_message(1, "/log lunch 닭가슴살 150 g"), _message(2, "/log lunch 닭가슴살 150 g")])
    store = MemoryStore()
    stopped = _bot(api, store=store, pending=pending, runner=runner, lines=lines).execute()
    assert stopped.interrupted_command is None
    assert runner.runs == [("nutrition", "log", "--meal", "lunch", "--item", "닭가슴살", "150", "g")]
    assert [saved.update_ids for saved in store.saved] == [(1,), (1, 2)]
    assert "update 1: unexpected RuntimeError; the message will not be run again" in lines
    assert any(line.startswith("Traceback") for line in lines)
    # The user got the unexpected-error text for the failed one and the reply for the next.
    assert len(api.sent) == 2


def test_a_failed_update_is_never_run_again() -> None:
    api = ScriptedApi([_message(1, "/log lunch 닭가슴살 150 g")], [_message(1, "/log lunch 닭가슴살 150 g")])
    runner = Runner()

    def pending() -> tuple[int, ...]:
        raise RuntimeError("synthetic")

    _bot(api, pending=pending, runner=runner).execute()
    assert runner.runs == []  # the redelivered update 1 is ignored: it was remembered before it failed


def test_five_unexpected_errors_in_a_row_stop_the_bot() -> None:
    updates = [_message(index, "/log lunch 닭가슴살 150 g") for index in range(1, 8)]
    api = ScriptedApi(updates)

    def pending() -> tuple[int, ...]:
        raise RuntimeError("synthetic")

    with pytest.raises(TelegramRunStoppedError) as raised:
        _bot(api, pending=pending).execute()
    assert str(raised.value).startswith(f"예상하지 못한 오류가 연속 {MAX_UNEXPECTED_IN_A_ROW}번 일어나")
    assert "RuntimeError" in str(raised.value)
    assert len(api.batches) == 0  # the batch was consumed; updates 6 and 7 were not handled


def test_a_success_between_failures_resets_the_count() -> None:
    updates = [_message(index, "/log lunch 닭가슴살 150 g") for index in range(1, 10)]
    api = ScriptedApi(updates)
    counter = {"calls": 0}

    def pending() -> tuple[int, ...]:
        counter["calls"] += 1
        if counter["calls"] % 5 != 0:  # four failures, one success, four failures, one success ...
            raise RuntimeError("synthetic")
        return ()

    stopped = _bot(api, pending=pending).execute()
    assert counter["calls"] == 9 and stopped.interrupted_command is None


def test_a_state_error_still_stops_the_bot_at_once() -> None:
    api = ScriptedApi([_message(1), _message(2)])
    with pytest.raises(TelegramStateError):
        _bot(api, store=MemoryStore(TelegramStateError("cannot write"))).execute()


def test_a_reply_that_fails_while_reporting_the_error_does_not_hide_it() -> None:
    api = ScriptedApi([_message(1, "/log lunch 닭가슴살 150 g"), _message(2, "/help")])
    lines: list[str] = []

    def pending() -> tuple[int, ...]:
        raise RuntimeError("synthetic")

    # The best-effort error text for update 1 fails too: it must not replace the original error.
    texts = {unexpected_error_text("RuntimeError")}
    bot = _bot(api, pending=pending, format_reply=_boom_on(texts), lines=lines)
    bot.execute()
    assert "update 1: unexpected RuntimeError; the message will not be run again" in lines


def test_a_chat_that_is_not_allowed_gets_no_error_text() -> None:
    api = ScriptedApi([IncomingUpdate(1, IncomingMessage(999, "/status", NOW))])
    lines: list[str] = []

    def explode(text: str) -> Sequence[str]:
        raise RuntimeError("must not be reached")

    _bot(api, format_reply=explode, lines=lines).execute()
    assert api.sent == [] and lines[-1] == "ignored message from chat 999 (not in allowed_chat_ids)"


def test_get_updates_raising_something_else_is_retried_and_counted() -> None:
    api = ScriptedApi(RuntimeError("synthetic"), [_message(1, "/status")], RuntimeError("again"), [_message(2)])
    lines: list[str] = []
    _bot(api, lines=lines).execute()
    assert lines.count("telegram: unexpected error (RuntimeError); retrying in 5 s") == 2
    assert len(api.sent) == 2


def test_five_failing_get_updates_in_a_row_stop_the_bot() -> None:
    api = ScriptedApi(*[RuntimeError("synthetic") for _ in range(MAX_UNEXPECTED_IN_A_ROW + 2)])
    with pytest.raises(TelegramRunStoppedError):
        _bot(api).execute()
    assert len(api.batches) == 2


def test_the_run_stops_with_exit_1_through_main(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    def explode(text: str) -> list[str]:
        raise RuntimeError("synthetic")

    monkeypatch.setattr(cli, "telegram_messages", explode)
    fake = v1.FakeTelegramApi([v1.update(index, "hello") for index in range(1, 8)])
    code, err = v1._run_bot(monkeypatch, capsys, fake)
    assert code == 1
    last = err.rstrip("\n").split("\n")[-1]
    assert last.startswith("오류: 예상하지 못한 오류가 연속 5번 일어나 bot을 멈춥니다 (마지막: RuntimeError)")
    state = json.loads((home / "config" / "telegram_state.json").read_text(encoding="utf-8"))
    assert state["handled_update_ids"] == [1, 2, 3, 4, 5]


def test_a_working_run_is_unchanged_by_the_guard(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert v1._bot(monkeypatch, capsys, "/help") == [HELP_TEXT]


# --- a console that went away --------------------------------------------------------------------------------


@pytest.mark.parametrize("error", [OSError("closed"), ValueError("I/O operation on closed file")])
def test_a_raising_log_sink_does_not_stop_the_bot(error: Exception) -> None:
    api = ScriptedApi([_message(1, "/status"), _message(2, "/status")])

    def broken(line: str) -> None:
        raise error

    _bot(api, log=broken).execute()
    assert len(api.sent) == 2


class BrokenStderr(io.StringIO):
    def write(self, text: str) -> int:
        raise OSError("the console window is gone")

    def flush(self) -> None:
        raise OSError("the console window is gone")


def test_a_broken_stderr_does_not_stop_a_run_through_main(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fake = v1.FakeTelegramApi([v1.update(1, "/help"), v1.update(2, "/help")])
    v1._install(monkeypatch, fake)
    monkeypatch.setattr(sys, "stderr", BrokenStderr())
    code = main(["telegram", "run"])
    assert code == 130
    assert len(fake.sent) == 2


def test_the_idle_hook_runs_each_iteration_and_its_errors_are_ignored() -> None:
    api = ScriptedApi([_message(1)], [])
    ticks: list[int] = []

    def idle() -> None:
        ticks.append(1)
        raise RuntimeError("run log failure")

    _bot(api, on_idle=idle).execute()
    assert len(ticks) == 3  # before each of the two batches and before the Ctrl+C one


# --- os.replace retry -----------------------------------------------------------------------------------------


def _llm_state() -> Any:
    from muscle50.domain.telegram_llm import EMPTY_STATE

    return EMPTY_STATE


STORES: list[
    tuple[str, Callable[[Path, Callable[[Path, Path], None], Callable[[float], None]], Any], Callable[[Any], Any]]
] = [
    (
        "handled",
        lambda path, replace, sleep: JsonHandledUpdateStore(path, replace=replace, sleep=sleep),
        lambda store: store.save(HandledUpdates(1, (10,))),
    ),
    (
        "llm",
        lambda path, replace, sleep: JsonLlmStateStore(path, replace=replace, sleep=sleep),
        lambda store: store.save(_llm_state()),
    ),
]


@pytest.mark.parametrize(("name", "make", "save"), STORES, ids=[item[0] for item in STORES])
def test_replace_failing_twice_then_saving(tmp_path: Path, name: str, make: Any, save: Any) -> None:
    import os

    path = tmp_path / "config" / "state.json"
    failures = {"left": 2}
    sleeps: list[float] = []

    def replace(source: Path, target: Path) -> None:
        if failures["left"]:
            failures["left"] -= 1
            raise PermissionError(13, "held by another process")
        os.replace(source, target)

    save(make(path, replace, sleeps.append))
    assert sleeps == [0.05, 0.1]
    assert path.exists() and [item.name for item in path.parent.iterdir()] == ["state.json"]


@pytest.mark.parametrize(("name", "make", "save"), STORES, ids=[item[0] for item in STORES])
def test_replace_failing_always_raises_the_state_error_after_every_delay(
    tmp_path: Path, name: str, make: Any, save: Any
) -> None:
    path = tmp_path / "config" / "state.json"
    sleeps: list[float] = []

    def replace(source: Path, target: Path) -> None:
        raise PermissionError(13, "held by another process")

    with pytest.raises(TelegramStateError) as raised:
        save(make(path, replace, sleeps.append))
    assert sleeps == list(REPLACE_RETRY_DELAYS_S) == [0.05, 0.1, 0.2, 0.4, 0.8]
    assert "(EACCES)" in str(raised.value) and "held by another process" not in str(raised.value)
    assert not path.exists() and [item.name for item in path.parent.iterdir()] == []


@pytest.mark.parametrize(("name", "make", "save"), STORES, ids=[item[0] for item in STORES])
def test_a_replace_error_other_than_permission_fails_at_once(tmp_path: Path, name: str, make: Any, save: Any) -> None:
    path = tmp_path / "config" / "state.json"
    sleeps: list[float] = []
    calls: list[int] = []

    def replace(source: Path, target: Path) -> None:
        calls.append(1)
        raise OSError(28, "no space")

    with pytest.raises(TelegramStateError) as raised:
        save(make(path, replace, sleeps.append))
    assert calls == [1] and sleeps == []
    assert "(ENOSPC)" in str(raised.value)
    assert [item.name for item in path.parent.iterdir()] == []
