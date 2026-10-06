"""`muscle50 telegram run` / `telegram check` end to end, through `cli.main`, with a fake Bot API.

No network (`urllib.request.urlopen` fails the test), no Garmin login, a temporary MUSCLE50_HOME
and synthetic values only. Covers AC1-AC9 of docs/specs/telegram-bot.md, `/daily`, Ctrl+C, the
pending-migration refusal (gate 1 D3) and the stdout/stderr/stdin restore of the in-process runner.
"""

from __future__ import annotations

import hashlib
import html
import io
import json
import sqlite3
import sys
import traceback
import urllib.error
import urllib.request
from collections.abc import Callable, Sequence
from datetime import UTC, date, datetime, timedelta, timezone, tzinfo
from pathlib import Path
from typing import Any

import inbody_trend_builders as inbody
import pytest
import sync_coverage_builders as builders

import muscle50.cli as cli
from muscle50.application.telegram_bot import (
    BotIdentity,
    IncomingMessage,
    IncomingUpdate,
    TelegramUnavailableError,
)
from muscle50.cli import main
from muscle50.domain.telegram_commands import (
    DAILY_PROGRESS_TEXT,
    GARMIN_LOGIN_TEXT,
    HELP_TEXT,
    MIGRATION_STATUS_UNKNOWN_TEXT,
    pending_migration_text,
    stale_text,
    unexpected_error_text,
    usage_text,
)
from muscle50.infrastructure.garmin.client import GarminConnectorError, PythonGarminConnector
from muscle50.infrastructure.sqlite.schema_status import code_migration_versions, pending_migrations
from muscle50.infrastructure.telegram.bot_api import UrllibTelegramBotApi
from muscle50.infrastructure.telegram.cli_runner import InProcessCliRunner
from muscle50.infrastructure.telegram.config_file import load_telegram_config
from muscle50.presentation.telegram_format import TELEGRAM_MESSAGE_LIMIT, telegram_messages, utf16_units

KST = timezone(timedelta(hours=9))
TODAY = date(2026, 10, 6)
NOW = datetime(2026, 10, 6, 12, 0, tzinfo=KST)
NOW_TS = int(NOW.timestamp())
TOKEN = "123456789:AAFakeSyntheticToken_ab-cd"
ALLOWED = 111
OTHER = 987654321
IDENTITY = BotIdentity(1234567890, "muscle50_example_bot")
START_LINE = "telegram run: bot @muscle50_example_bot is polling for 1 allowed chat. Press Ctrl+C to stop."
STOPPED = "\n취소되었습니다.\n"
LUNCH = "2026-10-06-lunch-1"

FOOD_COMMON = ["--source", "user_provided", "--accuracy", "exact"]
CHICKEN = ["--id", "chicken-breast", "--name", "닭가슴살", "--per", "100", "g"]
CHICKEN += ["--kcal", "110", "--protein", "23", "--carbs", "0", "--fat", "1", *FOOD_COMMON]
RICE = ["--id", "hetbahn-210", "--name", "햇반", "--per", "1", "pack"]
RICE += ["--kcal", "315", "--protein", "5", "--carbs", "70", "--fat", "unknown", *FOOD_COMMON]
BROWN_RICE = ["--id", "brown-rice-pack", "--name", "현미 햇반", "--per", "1", "pack"]
BROWN_RICE += ["--kcal", "300", "--protein", "6", "--carbs", "65", "--fat", "2", *FOOD_COMMON]
LOG_ARGV = ("nutrition", "log", "--meal", "lunch", "--item", "닭가슴살", "150", "g", "--item", "햇반", "1", "pack")
LOG_TEXT = "/log lunch 닭가슴살 150 g, 햇반 1 pack"


class FakeTelegramApi:
    """Scripted Bot API. When the getUpdates script runs out it raises KeyboardInterrupt (Ctrl+C)."""

    def __init__(
        self,
        *batches: Sequence[IncomingUpdate] | Exception,
        me_errors: Sequence[Exception] = (),
        send_errors: Sequence[Exception] = (),
        webhook: bool = False,
    ) -> None:
        self.batches = list(batches)
        self.me_errors = list(me_errors)
        self.send_errors = list(send_errors)
        self.webhook = webhook
        self.sent: list[tuple[int, str]] = []
        self.offsets: list[int | None] = []
        self.calls: list[str] = []

    def get_me(self) -> BotIdentity:
        self.calls.append("getMe")
        if self.me_errors:
            raise self.me_errors.pop(0)
        return IDENTITY

    def webhook_is_set(self) -> bool:
        self.calls.append("getWebhookInfo")
        return self.webhook

    def get_updates(self, offset: int | None, timeout_s: int) -> tuple[IncomingUpdate, ...]:
        self.calls.append("getUpdates")
        assert timeout_s == 10
        self.offsets.append(offset)
        if not self.batches:
            raise KeyboardInterrupt
        batch = self.batches.pop(0)
        if isinstance(batch, Exception):
            raise batch
        return tuple(batch)

    def send_message(self, chat_id: int, html_text: str) -> None:
        self.calls.append("sendMessage")
        if self.send_errors:
            raise self.send_errors.pop(0)
        self.sent.append((chat_id, html_text))

    def replies(self) -> list[str]:
        return [_body(message) for _, message in self.sent]


def _body(message: str) -> str:
    assert message.startswith("<pre>") and message.endswith("</pre>")
    return html.unescape(message[len("<pre>") : -len("</pre>")])


def _pre(text: str) -> str:
    return f"<pre>{html.escape(text, quote=False)}</pre>"


def update(update_id: int, text: str | None, *, chat: int = ALLOWED, sent: int = NOW_TS) -> IncomingUpdate:
    return IncomingUpdate(update_id, IncomingMessage(chat, text, sent))


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
    _configure(root)
    return root


@pytest.fixture(autouse=True)
def sleeps(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    recorded: list[float] = []
    monkeypatch.setattr(cli, "_telegram_sleep", recorded.append)
    return recorded


def _configure(root: Path, document: Any | None = None) -> Path:
    path = root / "config" / "telegram.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    content = document if document is not None else {"bot_token": TOKEN, "allowed_chat_ids": [ALLOWED]}
    path.write_text(json.dumps(content), encoding="utf-8", newline="\n")
    return path


def _install(monkeypatch: pytest.MonkeyPatch, fake: FakeTelegramApi) -> list[str]:
    tokens: list[str] = []

    def api(token: str) -> FakeTelegramApi:
        tokens.append(token)
        return fake

    monkeypatch.setattr(cli, "_telegram_api", api)
    return tokens


def _run_bot(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], fake: FakeTelegramApi
) -> tuple[int, str]:
    tokens = _install(monkeypatch, fake)
    code = main(["telegram", "run"])
    captured = capsys.readouterr()
    assert tokens == [TOKEN]
    assert captured.out == ""
    return code, captured.err


def _bot(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], *texts: str, first_id: int = 1
) -> list[str]:
    """One `run` session handling ``texts`` as updates first_id.. in order; returns the reply bodies."""
    fake = FakeTelegramApi([update(index, text) for index, text in enumerate(texts, start=first_id)])
    code, _ = _run_bot(monkeypatch, capsys, fake)
    assert code == 130
    return fake.replies()


def _cli(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, str, str]:
    code = main(list(argv))
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def _ok(capsys: pytest.CaptureFixture[str], *argv: str) -> str:
    code, out, err = _cli(capsys, *argv)
    assert code == 0, err
    return out


def _catalog(capsys: pytest.CaptureFixture[str]) -> None:
    for food in (CHICKEN, RICE, BROWN_RICE):
        _ok(capsys, "nutrition", "food", "add", *food)


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


def _tree(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _state(root: Path) -> Any:
    return json.loads((root / "config" / "telegram_state.json").read_text(encoding="utf-8"))


def _seed_reads(capsys: pytest.CaptureFixture[str], root: Path) -> None:
    """Catalog, a target, today's lunch, yesterday's dinner, InBody rows and training rows."""
    _catalog(capsys)
    _ok(capsys, "nutrition", "target", "set", "protein", "--exact", "120")
    _ok(capsys, *LOG_ARGV)
    _ok(capsys, "nutrition", "log", "--date", "2026-10-05", "--meal", "dinner", "--item", "chicken-breast", "200", "g")
    inbody.save_measurements(_database(root), inbody.AC1_ROWS)
    builders.fill_recommend_database(_database(root))


# --- AC1: read commands --------------------------------------------------------------------------

READ_COMMANDS = [
    ("/today", ("recommend", "--date", "2026-10-06")),
    ("/status", ("nutrition", "status")),
    ("/day", ("nutrition", "day")),
    ("/day 2026-10-05", ("nutrition", "day", "--date", "2026-10-05")),
    (f"/show {LUNCH}", ("nutrition", "meal", "show", LUNCH)),
    ("/inbody", ("inbody", "trend")),
]


@pytest.mark.parametrize(("text", "argv"), READ_COMMANDS, ids=[item[0] for item in READ_COMMANDS])
def test_read_commands_reply_equals_cli_stdout(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path, text: str, argv: tuple[str, ...]
) -> None:
    _seed_reads(capsys, home)
    expected = _ok(capsys, *argv)
    fake = FakeTelegramApi([update(1, text)], [update(2, text)])
    code, err = _run_bot(monkeypatch, capsys, fake)
    assert code == 130
    command = text.split()[0]
    # Byte for byte: the CLI stdout without its final newline, HTML-escaped inside <pre>.
    reply = expected.removesuffix("\n")
    messages = [(ALLOWED, message) for message in telegram_messages(reply)]
    assert fake.sent == messages * 2  # deterministic: the second run sends the same bytes
    if len(messages) == 1:
        assert messages == [(ALLOWED, _pre(reply))]
    else:  # `/today` is longer than one Telegram message; every cut here is at a line end
        assert "\n".join(_body(message) for _, message in messages) == reply
    assert err == "\n".join([START_LINE, f"chat 111: {command} -> exit 0", f"chat 111: {command} -> exit 0"]) + (
        "\n" + STOPPED
    )
    assert fake.offsets == [None, 2, 3]


# --- AC2: /log ---------------------------------------------------------------------------------------


def test_log_stores_the_same_rows_as_the_cli_and_adds_the_undo_line(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path, tmp_path: Path
) -> None:
    cli_home = tmp_path / "cli-home"
    monkeypatch.setenv("MUSCLE50_HOME", str(cli_home))
    _catalog(capsys)
    cli_text = _ok(capsys, *LOG_ARGV)
    cli_show = _ok(capsys, "nutrition", "meal", "show", LUNCH)
    cli_rows = _tables(_database(cli_home))

    monkeypatch.setenv("MUSCLE50_HOME", str(home))
    _catalog(capsys)
    replies = _bot(monkeypatch, capsys, LOG_TEXT)
    assert cli_text.startswith(f"Recorded meal {LUNCH}.\n")
    assert replies == [cli_text.removesuffix("\n") + f"\n취소: /void {LUNCH}"]
    assert _ok(capsys, "nutrition", "meal", "show", LUNCH) == cli_show
    bot_rows = _tables(_database(home))
    for table in ("nutrition_meals", "nutrition_meal_items"):
        assert bot_rows[table] == cli_rows[table]


def test_log_plus_is_additional_and_without_it_the_cli_refusal_is_relayed(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _catalog(capsys)
    replies = _bot(monkeypatch, capsys, "/log lunch 닭가슴살 100 g", "/log lunch 닭가슴살 100 g")
    code, out, refusal = _cli(capsys, "nutrition", "log", "--meal", "lunch", "--item", "닭가슴살", "100", "g")
    replies += _bot(monkeypatch, capsys, "/log lunch+ 닭가슴살 100 g", first_id=3)
    assert (code, out) == (1, "")
    assert refusal.startswith("오류: ")
    assert replies[0].endswith("\n취소: /void 2026-10-06-lunch-1")
    assert replies[1] == refusal.removesuffix("\n")
    assert replies[2].startswith("Recorded meal 2026-10-06-lunch-2.\n")
    assert replies[2].endswith("\n취소: /void 2026-10-06-lunch-2")


LOG_REFUSALS = [
    ("/log lunch 닭가슴살 150 g, 없는음식 1 g", ("--item", "닭가슴살", "150", "g", "--item", "없는음식", "1", "g")),
    ("/log lunch 닭가슴살 0 g", ("--item", "닭가슴살", "0", "g")),
    ("/log lunch 닭가슴살 abc g", ("--item", "닭가슴살", "abc", "g")),
    ("/log lunch 닭가슴살 1 cup", ("--item", "닭가슴살", "1", "cup")),
    ("/log lunch 햇반 100 g", ("--item", "햇반", "100", "g")),
]


@pytest.mark.parametrize(("text", "items"), LOG_REFUSALS, ids=[item[0] for item in LOG_REFUSALS])
def test_refused_log_relays_the_cli_error_and_writes_nothing(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path, text: str, items: tuple[str, ...]
) -> None:
    _catalog(capsys)
    before = _tables(_database(home))
    replies = _bot(monkeypatch, capsys, text)
    code, out, err = _cli(capsys, "nutrition", "log", "--meal", "lunch", *items)
    assert (code, out) == (1, "")
    assert replies == [err.removesuffix("\n")]
    assert replies[0].startswith("오류: ")
    assert _tables(_database(home)) == before


def test_food_name_with_a_space_resolves_like_the_cli(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _catalog(capsys)
    replies = _bot(monkeypatch, capsys, "/log dinner 현미 햇반 1 pack")
    assert replies[0].startswith("Recorded meal 2026-10-06-dinner-1.\n")
    assert "현미 햇반 (brown-rice-pack) 1 pack" in replies[0]


# --- AC3: /void --------------------------------------------------------------------------------------


def test_void_matches_the_cli_and_refusals_write_nothing(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path, tmp_path: Path
) -> None:
    cli_home = tmp_path / "cli-home"
    monkeypatch.setenv("MUSCLE50_HOME", str(cli_home))
    _catalog(capsys)
    _ok(capsys, *LOG_ARGV)
    cli_text = _ok(capsys, "nutrition", "meal", "void", LUNCH, "--reason", "중복 기록")
    cli_rows = _tables(_database(cli_home))

    monkeypatch.setenv("MUSCLE50_HOME", str(home))
    _catalog(capsys)
    _ok(capsys, *LOG_ARGV)
    replies = _bot(monkeypatch, capsys, f"/void {LUNCH} 중복 기록")
    assert replies == [cli_text.removesuffix("\n")]
    bot_rows = _tables(_database(home))
    for table in ("nutrition_meal_voids", "nutrition_meals", "nutrition_meal_items"):
        assert bot_rows[table] == cli_rows[table]

    before = _tables(_database(home))
    replies = _bot(monkeypatch, capsys, f"/void {LUNCH}", "/void 2026-10-06-dinner-9", first_id=2)
    _, _, again = _cli(capsys, "nutrition", "meal", "void", LUNCH)
    _, _, unknown = _cli(capsys, "nutrition", "meal", "void", "2026-10-06-dinner-9")
    assert replies == [again.removesuffix("\n"), unknown.removesuffix("\n")]
    assert all(reply.startswith("오류: ") for reply in replies)
    assert _tables(_database(home)) == before


# --- AC4: allowlist ----------------------------------------------------------------------------------


def test_unlisted_chat_is_ignored_without_reply_or_file_change(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    _catalog(capsys)
    before = _tree(home)
    fake = FakeTelegramApi([update(1, LOG_TEXT, chat=OTHER), update(2, "/status", chat=OTHER)])
    code, err = _run_bot(monkeypatch, capsys, fake)
    assert code == 130
    assert fake.sent == []
    assert "sendMessage" not in fake.calls
    assert err == "\n".join(
        [
            START_LINE,
            "ignored message from chat 987654321 (not in allowed_chat_ids)",
            "ignored message from chat 987654321 (not in allowed_chat_ids)",
        ]
    ) + ("\n" + STOPPED)
    assert _tree(home) == before
    assert not (home / "config" / "telegram_state.json").exists()


# --- AC5: usage --------------------------------------------------------------------------------------

USAGE_CASES = [
    ("/foo", "모르는 명령입니다: /foo\n\n" + HELP_TEXT),
    ("hello", "명령이 아닙니다.\n\n" + HELP_TEXT),
    ("/log", usage_text("log")),
    ("/log brunch x 1 g", usage_text("log")),
    ("/log lunch 150 g", usage_text("log")),
    ("/log lunch a 1 g,", usage_text("log")),
    ("/show", usage_text("show")),
    ("/show a b", usage_text("show")),
    ("/show --json", usage_text("show")),
    ("/day a b", usage_text("day")),
    ("/status now", usage_text("status")),
    ("/start", HELP_TEXT),
    ("/help@muscle50_example_bot", HELP_TEXT),
]


def test_usage_replies_write_nothing_but_the_state_file(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    texts = [text for text, _ in USAGE_CASES]
    fake = FakeTelegramApi([*[update(index, text) for index, text in enumerate(texts, start=1)], update(99, None)])
    code, err = _run_bot(monkeypatch, capsys, fake)
    assert code == 130
    assert fake.replies() == [reply for _, reply in USAGE_CASES] + ["명령이 아닙니다.\n\n" + HELP_TEXT]
    assert not (home / "db").exists()
    assert sorted(_tree(home)) == ["config/telegram.json", "config/telegram_state.json"]
    assert "chat 111: usage reply (unknown_command)" in err.split("\n")
    assert "chat 111: usage reply (malformed /log)" in err.split("\n")
    # Message text never reaches the console.
    assert "brunch" not in err and "hello" not in err


# --- AC6: at most once, restart, stale messages -----------------------------------------------------


def test_same_update_twice_in_one_session_logs_once(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    _catalog(capsys)
    fake = FakeTelegramApi([update(7, LOG_TEXT)], [update(7, LOG_TEXT)])
    code, _ = _run_bot(monkeypatch, capsys, fake)
    assert code == 130
    assert len(fake.sent) == 1
    assert len(_tables(_database(home))["nutrition_meals"]) == 1


def test_restart_does_not_rerun_log(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    _catalog(capsys)
    first = FakeTelegramApi([update(5500, LOG_TEXT)])
    assert _run_bot(monkeypatch, capsys, first)[0] == 130
    assert len(first.sent) == 1
    assert (home / "config" / "telegram_state.json").read_bytes() == (
        b'{\n  "schema_version": 1,\n  "bot_id": 1234567890,\n  "handled_update_ids": [\n    5500\n  ]\n}\n'
    )
    # The first session was "killed" before Telegram saw the acknowledgement: the update comes again.
    second = FakeTelegramApi([update(5500, LOG_TEXT), update(5501, "/help")])
    assert _run_bot(monkeypatch, capsys, second)[0] == 130
    assert second.replies() == [HELP_TEXT]
    assert len(_tables(_database(home))["nutrition_meals"]) == 1
    assert _state(home)["handled_update_ids"] == [5500, 5501]


def test_state_saved_before_command_runs(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    seen: list[Any] = []

    def spy(argv: Sequence[str] | None = None) -> int:
        seen.append(_state(home)["handled_update_ids"])
        return main(argv)

    monkeypatch.setattr(cli, "main", spy)
    _bot(monkeypatch, capsys, "/status", "/day")
    assert seen == [[1], [1, 2]]


def test_state_keeps_the_newest_100_ids(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    _bot(monkeypatch, capsys, *["/help"] * 105)
    assert _state(home) == {"schema_version": 1, "bot_id": 1234567890, "handled_update_ids": list(range(6, 106))}


def test_state_of_another_bot_is_not_used(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    state = home / "config" / "telegram_state.json"
    state.write_text(json.dumps({"schema_version": 1, "bot_id": 999, "handled_update_ids": [1]}), encoding="utf-8")
    fake = FakeTelegramApi([update(1, "/help")])
    _, err = _run_bot(monkeypatch, capsys, fake)
    assert fake.replies() == [HELP_TEXT]
    assert "update state belongs to bot 999; starting with no handled updates" in err.split("\n")
    assert _state(home) == {"schema_version": 1, "bot_id": 1234567890, "handled_update_ids": [1]}


def test_message_sent_before_start_is_not_run(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    _catalog(capsys)
    before = _tables(_database(home))
    stale = NOW_TS - 61
    fake = FakeTelegramApi([update(1, LOG_TEXT, sent=stale), update(2, "/status", sent=NOW_TS - 60)])
    _, err = _run_bot(monkeypatch, capsys, fake)
    replies = fake.replies()
    assert replies[0] == stale_text(datetime.fromtimestamp(stale, UTC).astimezone())
    assert replies[0].startswith("실행하지 않음: 이 메시지는 bot이 시작되기 전(")
    assert "chat 111: message sent before start, not run" in err.split("\n")
    assert _tables(_database(home))["nutrition_meals"] == before["nutrition_meals"]
    # 60 s before the start is still within the margin: it runs.
    assert "chat 111: /status -> exit 0" in err.split("\n")
    assert _state(home)["handled_update_ids"] == [1, 2]


# --- AC7: config and state errors --------------------------------------------------------------------

CONFIG_ERRORS = [
    ("missing", None),
    ("bad json", "{"),
    ("empty ids", {"bot_token": TOKEN, "allowed_chat_ids": []}),
    ("extra key", {"bot_token": TOKEN, "allowed_chat_ids": [1], "x": 1}),
]


@pytest.mark.parametrize("command", ["check", "run"])
@pytest.mark.parametrize(("case", "content"), CONFIG_ERRORS, ids=[item[0] for item in CONFIG_ERRORS])
def test_check_and_run_refuse_bad_config_without_network(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    home: Path,
    command: str,
    case: str,
    content: Any,
) -> None:
    path = home / "config" / "telegram.json"
    if content is None:
        path.unlink()
    elif isinstance(content, str):
        path.write_text(content, encoding="utf-8")
    else:
        _configure(home, content)
    with pytest.raises(Exception) as expected:
        load_telegram_config(path)
    monkeypatch.setattr(cli, "_telegram_api", lambda token: pytest.fail("no Bot API before the config is valid"))
    before = _tree(home)
    code, out, err = _cli(capsys, "telegram", command)
    assert (code, out) == (1, "")
    assert err == f"오류: {expected.value}\n"
    assert TOKEN not in err
    assert _tree(home) == before


@pytest.mark.parametrize("command", ["check", "run"])
def test_corrupt_state_file_stops_check_and_run(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path, command: str
) -> None:
    state = home / "config" / "telegram_state.json"
    state.write_text("{", encoding="utf-8")
    fake = FakeTelegramApi([update(1, "/help")])
    _install(monkeypatch, fake)
    code, out, err = _cli(capsys, "telegram", command)
    assert (code, out) == (1, "")
    assert err == (
        f"오류: telegram 상태 파일이 올바르지 않습니다: {state} (not valid JSON: line 1, column 2). "
        "telegram run이 만드는 파일입니다. "
        "지우고 다시 시작해도 됩니다(bot 시작 전에 보낸 메시지는 실행하지 않습니다).\n"
    )
    assert fake.calls == []


# --- telegram check ----------------------------------------------------------------------------------


def test_check_shows_the_bot_and_reads_or_writes_nothing(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    fake = FakeTelegramApi([update(1, "/help")])
    _install(monkeypatch, fake)
    before = _tree(home)
    code, out, err = _cli(capsys, "telegram", "check")
    assert (code, err) == (0, "")
    assert out.split("\n") == [
        f"Telegram config: {home.resolve() / 'config' / 'telegram.json'}",
        "Bot: @muscle50_example_bot (id 1234567890)",
        "Allowed chats: 111",
        "Webhook: not set",
        "Handled updates on record: none",
        "No messages were read or answered.",
        "",
    ]
    assert fake.calls == ["getMe", "getWebhookInfo"]
    assert _tree(home) == before
    assert not (home / "db").exists()


def test_rejected_token_ends_check_and_run_with_exit_1(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    rejected = _adapter_error(monkeypatch, _http_error(401, "Unauthorized"))
    for command in ("check", "run"):
        fake = FakeTelegramApi(me_errors=[rejected])
        _install(monkeypatch, fake)
        code, out, err = _cli(capsys, "telegram", command)
        assert (code, out) == (1, "")
        assert err == (
            "오류: Telegram이 bot token을 받아들이지 않았습니다 (API error 401 (Unauthorized)). "
            "telegram.json의 bot_token을 확인하세요.\n"
        )
        assert "getUpdates" not in fake.calls


# --- AC8: the token never appears ---------------------------------------------------------------------


def _http_error(code: int, description: str) -> urllib.error.HTTPError:
    body = io.BytesIO(json.dumps({"ok": False, "error_code": code, "description": description}).encode("utf-8"))
    url = f"https://api.telegram.org/bot{TOKEN}/getUpdates"
    return urllib.error.HTTPError(url, code, description, None, body)  # type: ignore[arg-type]


def _adapter_error(monkeypatch: pytest.MonkeyPatch, exc: Exception) -> TelegramUnavailableError:
    """The error the real adapter raises for ``exc`` (urlopen patched only for this call)."""

    def raise_it(*args: object, **kwargs: object) -> object:
        raise exc

    monkeypatch.setattr(urllib.request, "urlopen", raise_it)
    try:
        UrllibTelegramBotApi(TOKEN).get_updates(None, 10)
    except TelegramUnavailableError as error:
        return error
    finally:
        monkeypatch.setattr(urllib.request, "urlopen", _fail_network)
    raise AssertionError("the adapter did not raise")


def test_token_never_appears_in_output_replies_or_errors(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    errors = [
        _adapter_error(monkeypatch, _http_error(500, "Internal Server Error")),
        _adapter_error(monkeypatch, urllib.error.URLError(f"no route to https://api.telegram.org/bot{TOKEN}/getMe")),
        _adapter_error(monkeypatch, ValueError(f"URL can't contain control characters. '/bot{TOKEN}/getMe'")),
    ]

    def leaky(*args: object, **kwargs: object) -> int:
        raise RuntimeError(f"synthetic failure near {TOKEN}")

    monkeypatch.setattr(cli, "_recommend", leaky)
    fake = FakeTelegramApi(errors[0], errors[1], [update(1, "/today"), update(2, "/help")], me_errors=[errors[2]])
    code, err = _run_bot(monkeypatch, capsys, fake)
    assert code == 130
    assert fake.replies() == [unexpected_error_text("RuntimeError"), HELP_TEXT]
    assert "chat 111: /today failed with RuntimeError" in err.split("\n")
    assert "synthetic failure near <redacted>" in err  # the traceback is logged, redacted
    texts = [err, *(message for _, message in fake.sent)]
    for error in errors:
        texts += [str(error), repr(error), "".join(traceback.format_exception(error))]
    texts.append(repr(load_telegram_config(home / "config" / "telegram.json")))
    for text in texts:
        assert TOKEN not in text
        assert "AAFakeSyntheticToken" not in text


# --- AC9: errors do not stop run, long replies ---------------------------------------------------------


def test_run_survives_network_and_http_errors(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], sleeps: list[float]
) -> None:
    network = TelegramUnavailableError("network error (<urlopen error [Errno 11001] getaddrinfo failed>)")
    fake = FakeTelegramApi(
        TelegramUnavailableError("API error 500 (Internal Server Error)", status=500),
        TelegramUnavailableError("API error 409 (Conflict: terminated by other getUpdates request)", status=409),
        _adapter_error(monkeypatch, _http_error(401, "Unauthorized")),
        TelegramUnavailableError("API error 429 (Too Many Requests: retry after 3)", status=429, retry_after_s=3),
        network,
        [update(1, "/help")],
        network,
        [update(2, "/help")],
        me_errors=[network],
    )
    code, err = _run_bot(monkeypatch, capsys, fake)
    assert code == 130
    assert fake.replies() == [HELP_TEXT, HELP_TEXT]
    assert sleeps == [5, 5, 10, 20, 3, 60, 5]
    assert err.split("\n")[:8] == [
        "telegram: network error (<urlopen error [Errno 11001] getaddrinfo failed>); retrying in 5 s",
        START_LINE,
        "telegram: API error 500 (Internal Server Error); retrying in 5 s",
        "telegram: API error 409 (Conflict: terminated by other getUpdates request); "
        "another telegram run or a webhook is using this bot; retrying in 10 s",
        "telegram: API error 401 (Unauthorized); retrying in 20 s",
        "telegram: API error 429 (Too Many Requests: retry after 3); retrying in 3 s",
        "telegram: network error (<urlopen error [Errno 11001] getaddrinfo failed>); retrying in 60 s",
        "chat 111: usage reply (help)",
    ]
    assert fake.offsets == [None, None, None, None, None, None, 2, 2, 3]


def test_failed_sends_are_retried_then_given_up(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], sleeps: list[float]
) -> None:
    down = TelegramUnavailableError("network error (synthetic)")
    fake = FakeTelegramApi([update(1, "/help"), update(2, "/help"), update(3, "/start")], send_errors=[down] * 5)
    code, err = _run_bot(monkeypatch, capsys, fake)
    assert code == 130
    # Update 1: three attempts fail. Update 2: two fail, the third is delivered. Update 3: delivered.
    assert fake.replies() == [HELP_TEXT, HELP_TEXT]
    assert sleeps == [5, 10, 5, 10]
    assert "reply to chat 111 was not delivered (network error (synthetic))" in err.split("\n")


def test_long_reply_is_split_without_loss(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    text = "\n".join(f"{index:04d} <synthetic> & 닭가슴살 " + "=" * (index % 50) for index in range(400))
    assert len(text) > 10_000

    def long_output(*args: object, **kwargs: object) -> int:
        print(text)
        return 0

    monkeypatch.setattr(cli, "_recommend", long_output)
    fake = FakeTelegramApi([update(1, "/today")])
    _run_bot(monkeypatch, capsys, fake)
    assert len(fake.sent) > 2
    for _, message in fake.sent:
        assert utf16_units(message) <= TELEGRAM_MESSAGE_LIMIT
    assert "\n".join(fake.replies()) == text


# --- /daily ---------------------------------------------------------------------------------------------


def test_daily_sends_progress_then_the_daily_stdout(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def refused(*args: object, **kwargs: object) -> object:
        raise GarminConnectorError("Garmin 인증에 실패했습니다.")

    monkeypatch.setattr(PythonGarminConnector, "authenticate", refused)
    replies = _bot(monkeypatch, capsys, "/daily", "/help")
    code, out, err = _cli(capsys, "daily")
    assert code == 1
    assert err.startswith("muscle50 daily 2026-10-06: syncing 2026-10-05..2026-10-06")
    assert replies == [DAILY_PROGRESS_TEXT, out.removesuffix("\n"), HELP_TEXT]


def test_daily_needing_a_garmin_login_gets_the_login_reply_and_writes_no_sync_data(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    def interactive(auth_dir: Path, *, input_fn: Callable[[str], str], **kwargs: object) -> object:
        input_fn("Garmin email: ")
        raise AssertionError("input must raise EOFError: the bot has no keyboard")

    monkeypatch.setattr(PythonGarminConnector, "authenticate", interactive)
    fake = FakeTelegramApi([update(1, "/daily"), update(2, "/help")])
    code, err = _run_bot(monkeypatch, capsys, fake)
    assert code == 130
    assert fake.replies() == [DAILY_PROGRESS_TEXT, GARMIN_LOGIN_TEXT, HELP_TEXT]
    assert "chat 111: /daily needs a Garmin login in a terminal" in err.split("\n")
    tables = _tables(_database(home))
    for table in ("activities", "raw_artifacts", "daily_recovery", "sync_coverage", "recovery_raw_captures"):
        assert tables[table] == []
    assert not [path for path in (home / "raw").rglob("*") if path.is_file()]


# --- Ctrl+C ---------------------------------------------------------------------------------------------


def test_ctrl_c_during_a_command_stops_at_once_and_the_update_is_never_rerun(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    def interrupted(*args: object, **kwargs: object) -> int:
        raise KeyboardInterrupt

    monkeypatch.setattr(cli, "_recommend", interrupted)
    fake = FakeTelegramApi([update(1, "/today"), update(2, "/help")])
    code, err = _run_bot(monkeypatch, capsys, fake)
    assert code == 130
    assert fake.sent == []
    assert err == "\n".join([START_LINE, "chat 111: /today interrupted by Ctrl+C; it will not be run again"]) + (
        "\n" + STOPPED
    )
    assert _state(home)["handled_update_ids"] == [1]


def test_a_command_returning_130_also_stops_the_bot(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    def cancelled(*args: object, **kwargs: object) -> int:
        print("\n취소되었습니다.", file=sys.stderr)
        return 130

    monkeypatch.setattr(cli, "_recommend", cancelled)
    fake = FakeTelegramApi([update(1, "/today"), update(2, "/help")])
    code, err = _run_bot(monkeypatch, capsys, fake)
    assert code == 130
    assert fake.sent == []
    assert "chat 111: /today interrupted by Ctrl+C; it will not be run again" in err.split("\n")
    assert _state(home)["handled_update_ids"] == [1]


def test_runner_restores_the_streams_after_success_error_and_ctrl_c() -> None:
    original = (sys.stdout, sys.stderr, sys.stdin)

    def prints(argv: Sequence[str]) -> int:
        print("out")
        print("err", file=sys.stderr)
        assert sys.stdin.read() == ""
        return 0

    assert InProcessCliRunner(prints).run(["x"]).stdout == "out\n"
    assert (sys.stdout, sys.stderr, sys.stdin) == original

    def usage(argv: Sequence[str]) -> int:
        raise SystemExit(2)

    outcome = InProcessCliRunner(usage).run(["x"])
    assert (outcome.exit_code, outcome.usage_error) == (2, True)
    assert (sys.stdout, sys.stderr, sys.stdin) == original

    for exc in (RuntimeError("boom"), KeyboardInterrupt(), EOFError()):

        def raises(argv: Sequence[str], exc: BaseException = exc) -> int:
            print("partial")
            raise exc

        with pytest.raises(type(exc)):
            InProcessCliRunner(raises).run(["x"])
        assert sys.stdout is original[0] and sys.stderr is original[1] and sys.stdin is original[2]


# --- D3: pending migrations ---------------------------------------------------------------------------


def _drop_migration_marker(database: Path, version: int) -> None:
    connection = sqlite3.connect(database)
    try:
        connection.execute("DELETE FROM schema_migrations WHERE version = ?", (version,))
        connection.commit()
    finally:
        connection.close()


def test_commands_that_migrate_are_refused_while_a_migration_is_pending(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    _seed_reads(capsys, home)
    database = _database(home)
    _drop_migration_marker(database, 10)
    before = _tables(database)
    today = _ok(capsys, "recommend", "--date", "2026-10-06")
    trend = _ok(capsys, "inbody", "trend")
    replies = _bot(
        monkeypatch,
        capsys,
        LOG_TEXT,
        "/status",
        "/day",
        f"/show {LUNCH}",
        f"/void {LUNCH}",
        "/daily",
        "/today",
        "/inbody",
    )
    refusal = pending_migration_text((10,))
    assert refusal == (
        "오류: DB에 아직 적용하지 않은 migration 010이 있습니다. bot은 migration을 적용하지 않습니다. "
        "DB를 백업한 뒤 PC 터미널에서 muscle50 명령 하나로 적용하고 다시 보내세요."
    )
    relayed = [_body(message) for text in (today, trend) for message in telegram_messages(text.removesuffix("\n"))]
    assert replies == [refusal] * 6 + relayed
    assert _tables(database) == before
    assert pending_migrations(database) == (10,)


def test_unreadable_migration_state_is_refused(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    database = _database(home)
    database.parent.mkdir(parents=True)
    connection = sqlite3.connect(database)
    connection.execute("CREATE TABLE unrelated (x INTEGER)")
    connection.close()
    before = _tree(home)
    assert pending_migrations(database) is None
    replies = _bot(monkeypatch, capsys, "/status")
    assert replies == [MIGRATION_STATUS_UNKNOWN_TEXT]
    assert {path: digest for path, digest in _tree(home).items() if path.startswith("db/")} == {
        path: digest for path, digest in before.items() if path.startswith("db/")
    }


def test_fresh_home_without_a_database_runs_the_command(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    assert pending_migrations(_database(home)) == ()
    replies = _bot(monkeypatch, capsys, "/status")
    assert replies[0] == _ok(capsys, "nutrition", "status").removesuffix("\n")
    assert pending_migrations(_database(home)) == ()


def test_code_migration_versions_are_listed_from_the_package() -> None:
    assert code_migration_versions() == tuple(range(1, 11))


# --- console ----------------------------------------------------------------------------------------------


def test_console_lines_are_ascii_and_never_contain_message_text(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _catalog(capsys)
    fake = FakeTelegramApi(
        [
            update(1, LOG_TEXT),
            update(2, "아무 말"),
            update(3, "/void 2026-10-06-lunch-1 중복"),
            update(4, "x", chat=OTHER),
        ],
        TelegramUnavailableError("network error (\\uc5f0\\uacb0)"),
    )
    _, err = _run_bot(monkeypatch, capsys, fake)
    lines = err.removesuffix(STOPPED).split("\n")
    assert all(line.isascii() for line in lines)
    assert "닭가슴살" not in err and "중복" not in err
