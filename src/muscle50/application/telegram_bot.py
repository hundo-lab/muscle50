"""Telegram Command Bot v1: long-poll the Bot API and answer allowed chats with CLI output.

The bot is a transport. Every command runs through the CLI code path (`CliCommandRunner`), so
its reply is the CLI's stdout or `오류:` text; the bot adds no calculation or judgement. Rules
held here:

- Allowlist: a message from any other chat is logged and ignored. Nothing is sent or written.
- At most once: an allowed update's id is saved to the handled-updates state *before* its command
  runs, so a crash or Ctrl+C can lose a reply but never run a command twice.
- Stale messages: a message sent more than `STALE_MARGIN_S` before `run` started is not run.
- Migrations: a command whose CLI handler migrates is refused while the code has a migration the
  database lacks (the bot never applies one; that is a human gate).
- Network and API errors are logged and retried with backoff; `run` stops only on Ctrl+C.

The Bot API token never reaches this module: the adapter holds it and redacts its messages.
"""

from __future__ import annotations

import re
import traceback
from collections.abc import Callable, Sequence
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Protocol

from muscle50.domain.telegram_commands import (
    DAILY_PROGRESS_TEXT,
    GARMIN_LOGIN_TEXT,
    MIGRATION_STATUS_UNKNOWN_TEXT,
    CliInvocation,
    UsageReason,
    UsageReply,
    empty_output_text,
    parse_bot_message,
    pending_migration_text,
    stale_text,
    undo_line,
    unexpected_error_text,
    usage_reply_text,
)

MAX_HANDLED_UPDATES = 100
STALE_MARGIN_S = 60
POLL_TIMEOUT_S = 10
SEND_ATTEMPTS = 3
BACKOFF_S: tuple[float, ...] = (5, 10, 20, 40, 60)

# The `render_logged_meal` headline (`nutrition log` stdout line 1); the Undo line needs its meal ID.
_RECORDED_MEAL = re.compile(r"Recorded meal (\S+)\.")
# `daily` writes this progress line to stderr before it starts syncing.
_DAILY_PROGRESS_PREFIX = "muscle50 daily "


class TelegramUnavailableError(RuntimeError):
    """A network or Bot API failure. The message is ASCII and never contains the token."""

    def __init__(self, message: str, *, status: int | None = None, retry_after_s: float | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.retry_after_s = retry_after_s


class TelegramTokenRejectedError(TelegramUnavailableError):
    """The Bot API refused the token (HTTP 401/404)."""


class TelegramStateError(RuntimeError):
    """The handled-updates state file cannot be read or written."""


@dataclass(frozen=True)
class BotIdentity:
    bot_id: int
    username: str


@dataclass(frozen=True)
class IncomingMessage:
    chat_id: int
    text: str | None
    """None for a message without text (photo, sticker, ...)."""
    sent_at_unix: int


@dataclass(frozen=True)
class IncomingUpdate:
    update_id: int
    message: IncomingMessage | None


@dataclass(frozen=True)
class HandledUpdates:
    bot_id: int
    update_ids: tuple[int, ...]
    """Newest `MAX_HANDLED_UPDATES` ids, in the order they were handled."""


@dataclass(frozen=True)
class CommandOutcome:
    exit_code: int
    stdout: str
    stderr: str
    usage_error: bool = False
    """argparse refused the argv (SystemExit). The bot grammar should make this impossible."""


@dataclass(frozen=True)
class TelegramCheck:
    identity: BotIdentity
    webhook_set: bool
    handled: HandledUpdates | None


@dataclass(frozen=True)
class BotStopped:
    interrupted_command: str | None
    chat_id: int | None


class TelegramBotApi(Protocol):
    def get_me(self) -> BotIdentity: ...

    def webhook_is_set(self) -> bool: ...

    def get_updates(self, offset: int | None, timeout_s: int) -> tuple[IncomingUpdate, ...]: ...

    def send_message(self, chat_id: int, html: str) -> None: ...


class HandledUpdateStore(Protocol):
    def load(self) -> HandledUpdates | None: ...

    def save(self, handled: HandledUpdates) -> None: ...


class CliCommandRunner(Protocol):
    def run(self, argv: Sequence[str]) -> CommandOutcome: ...


class CheckTelegramBot:
    """`telegram check`: state read, getMe and getWebhookInfo. Reads no message and writes nothing."""

    def __init__(self, api: TelegramBotApi, handled: HandledUpdateStore) -> None:
        self._api = api
        self._handled = handled

    def execute(self) -> TelegramCheck:
        handled = self._handled.load()
        identity = self._api.get_me()
        return TelegramCheck(identity, self._api.webhook_is_set(), handled)


class RunTelegramBot:
    def __init__(
        self,
        api: TelegramBotApi,
        handled: HandledUpdateStore,
        commands: CliCommandRunner,
        *,
        allowed_chat_ids: frozenset[int],
        today: Callable[[], date],
        pending_migrations: Callable[[], tuple[int, ...] | None],
        format_reply: Callable[[str], Sequence[str]],
        log: Callable[[str], None],
        sleep: Callable[[float], None],
        clock: Callable[[], float],
        poll_timeout_s: int = POLL_TIMEOUT_S,
    ) -> None:
        self._api = api
        self._handled = handled
        self._commands = commands
        self._allowed = allowed_chat_ids
        self._today = today
        self._pending_migrations = pending_migrations
        self._format_reply = format_reply
        self._log_sink = log
        self._sleep = sleep
        self._clock = clock
        self._poll_timeout_s = poll_timeout_s
        self._bot_id = 0
        self._handled_ids: list[int] = []
        self._running: tuple[str, int] | None = None

    def execute(self) -> BotStopped:
        """Polls until Ctrl+C. Token rejection at startup and state-file errors propagate."""
        with suppress(KeyboardInterrupt):  # Ctrl+C anywhere: stop now (the interrupted update is already handled)
            self._poll()
        if self._running is None:
            return BotStopped(None, None)
        command, chat_id = self._running
        self._log(f"chat {chat_id}: /{command} interrupted by Ctrl+C; it will not be run again")
        return BotStopped(command, chat_id)

    def _poll(self) -> None:
        stored = self._handled.load()
        identity = self._identify()
        self._bot_id = identity.bot_id
        if stored is not None and stored.bot_id != identity.bot_id:
            self._log(f"update state belongs to bot {stored.bot_id}; starting with no handled updates")
        elif stored is not None:
            self._handled_ids = list(stored.update_ids)
        started_at = self._clock()
        count = len(self._allowed)
        self._log(
            f"telegram run: bot @{identity.username} is polling for {count} allowed "
            f"{'chat' if count == 1 else 'chats'}. Press Ctrl+C to stop."
        )
        offset: int | None = None
        failures = 0
        while True:
            try:
                updates = self._api.get_updates(offset, self._poll_timeout_s)
            except TelegramUnavailableError as exc:
                failures += 1
                self._wait_after(exc, failures)
                continue
            failures = 0
            for update in updates:
                offset = max(offset or 0, update.update_id + 1)
                if self._handle(update, identity, started_at):
                    return

    def _identify(self) -> BotIdentity:
        failures = 0
        while True:
            try:
                return self._api.get_me()
            except TelegramTokenRejectedError:
                raise
            except TelegramUnavailableError as exc:
                failures += 1
                self._wait_after(exc, failures)

    def _handle(self, update: IncomingUpdate, identity: BotIdentity, started_at: float) -> bool:
        """Handles one update; True when the bot must stop (the command was interrupted)."""
        if update.update_id in self._handled_ids:
            return False
        message = update.message
        if message is None:
            self._log(f"ignored update {update.update_id} (not a message)")
            return False
        chat_id = message.chat_id
        if chat_id not in self._allowed:
            self._log(f"ignored message from chat {chat_id} (not in allowed_chat_ids)")
            return False
        self._remember(update.update_id)  # before anything runs: at most once
        if message.sent_at_unix < started_at - STALE_MARGIN_S:
            self._log(f"chat {chat_id}: message sent before start, not run")
            sent_at = datetime.fromtimestamp(message.sent_at_unix, UTC).astimezone()
            self._reply(chat_id, stale_text(sent_at))
            return False
        parsed = parse_bot_message(message.text, bot_username=identity.username, today=self._today())
        if isinstance(parsed, UsageReply):
            self._log(f"chat {chat_id}: {_usage_log(parsed)}")
            self._reply(chat_id, usage_reply_text(parsed))
            return False
        return self._run_command(chat_id, parsed)

    def _remember(self, update_id: int) -> None:
        self._handled_ids = [*self._handled_ids, update_id][-MAX_HANDLED_UPDATES:]
        self._handled.save(HandledUpdates(self._bot_id, tuple(self._handled_ids)))

    def _run_command(self, chat_id: int, invocation: CliInvocation) -> bool:
        name = invocation.command
        if invocation.migrates:
            pending = self._pending_migrations()
            if pending is None:
                self._log(f"chat {chat_id}: /{name} not run (cannot read schema_migrations)")
                self._reply(chat_id, MIGRATION_STATUS_UNKNOWN_TEXT)
                return False
            if pending:
                numbers = ", ".join(f"{version:03d}" for version in pending)
                self._log(f"chat {chat_id}: /{name} not run (migration {numbers} not applied)")
                self._reply(chat_id, pending_migration_text(pending))
                return False
        if invocation.is_daily:
            self._reply(chat_id, DAILY_PROGRESS_TEXT)
        self._running = (name, chat_id)
        try:
            outcome = self._commands.run(invocation.argv)
        except EOFError:
            # `daily` asked for a Garmin login on stdin, which the bot does not have.
            self._running = None
            self._log(f"chat {chat_id}: /{name} needs a Garmin login in a terminal")
            self._reply(chat_id, GARMIN_LOGIN_TEXT)
            return False
        except Exception as exc:
            self._running = None
            self._log(f"chat {chat_id}: /{name} failed with {type(exc).__name__}")
            self._log("".join(traceback.format_exception(exc)).rstrip("\n"))
            self._reply(chat_id, unexpected_error_text(type(exc).__name__))
            return False
        if outcome.exit_code == 130:
            return True
        self._running = None
        self._log(f"chat {chat_id}: /{name} -> exit {outcome.exit_code}")
        if outcome.usage_error:
            self._reply(chat_id, usage_reply_text(UsageReply(UsageReason.MALFORMED, name)))
            return False
        text = _reply_text(outcome)
        if invocation.adds_undo and outcome.exit_code == 0:
            meal_id = _recorded_meal_id(outcome.stdout)
            if meal_id is None:
                self._log(f"chat {chat_id}: /{name} reply has no undo line (headline not recognised)")
            else:
                text = f"{text}\n{undo_line(meal_id)}"
        self._reply(chat_id, text)
        return False

    def _reply(self, chat_id: int, text: str) -> None:
        for html in self._format_reply(text):
            if not self._send(chat_id, html):
                return

    def _send(self, chat_id: int, html: str) -> bool:
        for attempt in range(1, SEND_ATTEMPTS + 1):
            try:
                self._api.send_message(chat_id, html)
                return True
            except TelegramUnavailableError as exc:
                if attempt == SEND_ATTEMPTS:
                    self._log(f"reply to chat {chat_id} was not delivered ({exc})")
                    return False
                delay = _delay(exc, attempt)
                self._log(f"telegram: {exc}; retrying the reply to chat {chat_id} in {_seconds(delay)} s")
                self._sleep(delay)
        return False  # pragma: no cover - the loop always returns

    def _wait_after(self, exc: TelegramUnavailableError, failures: int) -> None:
        delay = _delay(exc, failures)
        hint = "; another telegram run or a webhook is using this bot" if exc.status == 409 else ""
        self._log(f"telegram: {exc}{hint}; retrying in {_seconds(delay)} s")
        self._sleep(delay)

    def _log(self, line: str) -> None:
        # Console lines stay ASCII: an OS or API message may carry characters a cp949 console cannot print.
        self._log_sink(line.encode("ascii", "backslashreplace").decode("ascii"))


def _delay(exc: TelegramUnavailableError, failures: int) -> float:
    if exc.retry_after_s is not None:
        return exc.retry_after_s
    return BACKOFF_S[min(failures, len(BACKOFF_S)) - 1]


def _seconds(value: float) -> str:
    return str(int(value)) if value == int(value) else f"{value:g}"


def _usage_log(reply: UsageReply) -> str:
    if reply.reason is UsageReason.MALFORMED:
        return f"usage reply (malformed /{reply.command})"
    return f"usage reply ({reply.reason.value})"


def _reply_text(outcome: CommandOutcome) -> str:
    """The CLI's stdout; when there is none, its stderr without the `daily` progress line."""
    if outcome.stdout:
        return outcome.stdout.removesuffix("\n")
    lines = outcome.stderr.removesuffix("\n").split("\n")
    text = "\n".join(line for line in lines if not line.startswith(_DAILY_PROGRESS_PREFIX))
    return text if text.strip() else empty_output_text(outcome.exit_code)


def _recorded_meal_id(stdout: str) -> str | None:
    match = _RECORDED_MEAL.fullmatch(stdout.split("\n", 1)[0])
    return match.group(1) if match else None
