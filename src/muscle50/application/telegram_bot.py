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
- v1.1 summaries: `/today`, `/status`, `/daily` and `/unknown` run the CLI's `--json` form once and
  reply with a short summary of that document (`ReplySummaries`); `full` is the v1 text. `/refresh`
  runs `garmin refresh` and reports the activity's UNKNOWN set count read before and after it.
- v1.2 bare `/refresh`: the `/unknown` list (read once), then `garmin refresh` for each entry in JSON
  order, at most `REFRESH_ALL_CAP`, `REFRESH_ALL_PAUSE_S` apart; it stops on a Garmin login need, on
  any unexpected exception and after `MAX_CONSECUTIVE_REFRESH_FAILURES` failures in a row. One result
  reply with each activity's before/after count and how many still have UNKNOWN sets (a second read of
  the same list; never 0 when it cannot be read). The whole run is one handled update.

The Bot API token never reaches this module: the adapter holds it and redacts its messages.
"""

from __future__ import annotations

import json
import re
import traceback
from collections.abc import Callable, Sequence
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Any, Protocol

from muscle50.application.activity_unknown_sets import ActivityUnknownSets
from muscle50.domain.telegram_commands import (
    DAILY_PROGRESS_TEXT,
    GARMIN_LOGIN_TEXT,
    MIGRATION_STATUS_UNKNOWN_TEXT,
    REFRESH_ALL_CAP,
    REFRESH_ALL_TARGETS_FAILED_TEXT,
    CliInvocation,
    ReplyKind,
    UsageReason,
    UsageReply,
    daily_summary_failed_text,
    empty_output_text,
    parse_bot_message,
    pending_migration_text,
    refresh_all_empty_text,
    refresh_all_progress_text,
    refresh_login_text,
    refresh_progress_text,
    stale_text,
    summary_failed_text,
    undo_line,
    unexpected_error_text,
    usage_reply_text,
)

MAX_HANDLED_UPDATES = 100
STALE_MARGIN_S = 60
POLL_TIMEOUT_S = 10
SEND_ATTEMPTS = 3
BACKOFF_S: tuple[float, ...] = (5, 10, 20, 40, 60)
# v1.2 bare `/refresh`. The same rule as `sync_garmin_recovery.MAX_CONSECUTIVE_DATE_FAILURES`: this many
# failed activities in a row look like a Garmin-side limit or outage, so the rest are not requested.
MAX_CONSECUTIVE_REFRESH_FAILURES = 3
REFRESH_ALL_PAUSE_S = 2
"""Seconds between two activities of one bulk run (not before the first or after the last)."""

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


class SummaryUnavailableError(ValueError):
    """The CLI JSON did not have the shape a summary reads; the message is the underlying error type."""


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


class RefreshItemStatus(StrEnum):
    DONE = "done"
    FAILED = "failed"
    NOT_RUN = "not_run"


class RefreshStop(StrEnum):
    CONSECUTIVE_FAILURES = "consecutive_failures"
    GARMIN_LOGIN = "garmin_login"
    UNEXPECTED_ERROR = "unexpected_error"


@dataclass(frozen=True)
class RefreshTarget:
    """One `strength.unknown_notices` entry of `recommend --json`, as written there."""

    source_activity_id: str
    """Checked to be ASCII digits."""
    local_date: str
    """`YYYY-MM-DD`."""
    unknown_set_count: int


@dataclass(frozen=True)
class RefreshItem:
    target: RefreshTarget
    status: RefreshItemStatus
    before: ActivityUnknownSets | None = None
    after: ActivityUnknownSets | None = None
    cli_stdout: str = ""
    """DONE: the `garmin refresh` stdout (headline fallback and `경고: ` lines)."""
    error: str | None = None
    """FAILED by a CLI error: its `오류:` text verbatim. None when an unexpected exception stopped the run."""


@dataclass(frozen=True)
class BulkRefreshResult:
    items: tuple[RefreshItem, ...]
    """The first `REFRESH_ALL_CAP` targets, in JSON order (newest first)."""
    over_cap: int
    """Targets not taken because of the cap."""
    stopped: RefreshStop | None
    stop_detail: str | None
    """GARMIN_LOGIN: the activity id it stopped at; UNEXPECTED_ERROR: the exception type."""
    remaining: int | None
    """Activities that still have UNKNOWN sets after the run; None when that could not be read (never 0)."""


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


class ReplySummaries(Protocol):
    def summary(self, kind: ReplyKind, document: Any) -> Sequence[str]:
        """HTML messages summarizing one CLI JSON document; `SummaryUnavailableError` on an unexpected shape."""
        ...

    def refresh(
        self,
        activity_id: str,
        before: ActivityUnknownSets | None,
        after: ActivityUnknownSets | None,
        cli_stdout: str,
    ) -> Sequence[str]:
        """HTML messages for a successful `garmin refresh`."""
        ...

    def refresh_targets(self, document: Any) -> tuple[RefreshTarget, ...]:
        """The `strength.unknown_notices` of a `recommend --json` document; `SummaryUnavailableError` on shape."""
        ...

    def refresh_all(self, result: BulkRefreshResult) -> Sequence[str]:
        """HTML messages for the result of a bare `/refresh`."""
        ...


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
        summaries: ReplySummaries,
        unknown_sets: Callable[[str], ActivityUnknownSets | None],
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
        self._summaries = summaries
        self._unknown_sets = unknown_sets
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
        if invocation.reply is ReplyKind.REFRESH_ALL:
            return self._refresh_all(chat_id, invocation)
        refresh_id = invocation.activity_id if invocation.reply is ReplyKind.REFRESH else None
        if invocation.is_daily:
            self._reply(chat_id, DAILY_PROGRESS_TEXT)
        elif refresh_id is not None:
            self._reply(chat_id, refresh_progress_text(refresh_id))
        # Read-only, before the refresh writes anything.
        before = self._count_unknown(chat_id, refresh_id) if refresh_id is not None else None
        self._running = (name, chat_id)
        try:
            outcome = self._commands.run(invocation.argv)
        except EOFError:
            # `daily`/`garmin refresh` asked for a Garmin login on stdin, which the bot does not have.
            self._running = None
            self._log(f"chat {chat_id}: /{name} needs a Garmin login in a terminal")
            self._reply(chat_id, GARMIN_LOGIN_TEXT if refresh_id is None else refresh_login_text(refresh_id))
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
        if refresh_id is not None and outcome.exit_code == 0:
            after = self._count_unknown(chat_id, refresh_id)
            self._send_all(chat_id, self._summaries.refresh(refresh_id, before, after, outcome.stdout))
            return False
        if invocation.reply not in (ReplyKind.TEXT, ReplyKind.REFRESH) and outcome.stdout:
            self._summary_reply(chat_id, invocation, outcome)
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

    def _refresh_all(self, chat_id: int, invocation: CliInvocation) -> bool:
        """v1.2 bare `/refresh` (the migration check has passed); True when the bot must stop (Ctrl+C).

        `invocation.argv` is the read-only `recommend --json` of `/unknown`: it fixes the targets once,
        and its second run after the refreshes gives the remaining count.
        """
        # Held for the whole run (both list reads, every refresh and the pauses): Ctrl+C anywhere stops the bot.
        self._running = ("refresh", chat_id)
        try:
            outcome = self._commands.run(invocation.argv)
        except Exception as exc:
            self._running = None
            self._log(f"chat {chat_id}: /refresh failed with {type(exc).__name__}")
            self._log("".join(traceback.format_exception(exc)).rstrip("\n"))
            self._reply(chat_id, unexpected_error_text(type(exc).__name__))
            return False
        if outcome.exit_code == 130:
            return True
        self._log(f"chat {chat_id}: /refresh targets -> exit {outcome.exit_code}")
        targets, failure = self._refresh_targets(chat_id, outcome)
        if targets is None:
            self._running = None
            self._reply(chat_id, failure)
            return False
        if not targets:
            self._running = None
            self._log(f"chat {chat_id}: /refresh all: no UNKNOWN activities")
            self._reply(chat_id, refresh_all_empty_text())  # no Garmin call
            return False
        selected = targets[:REFRESH_ALL_CAP]
        count = f"{len(selected)}" if len(selected) == len(targets) else f"{len(selected)} of {len(targets)}"
        self._log(f"chat {chat_id}: /refresh all: {count} activities (cap {REFRESH_ALL_CAP})")
        self._reply(chat_id, refresh_all_progress_text(len(selected), len(targets)))

        items: list[RefreshItem] = []
        stopped: RefreshStop | None = None
        stop_detail: str | None = None
        failures = 0
        for index, target in enumerate(selected):
            if stopped is not None:
                items.append(RefreshItem(target, RefreshItemStatus.NOT_RUN))
                continue
            if index:
                self._sleep(REFRESH_ALL_PAUSE_S)
            activity_id = target.source_activity_id
            before = self._count_unknown(chat_id, activity_id)  # read-only, before the refresh writes anything
            try:
                result = self._commands.run(("garmin", "refresh", activity_id))
            except EOFError:
                # The login prompt met the bot's empty stdin before anything was written: not fetched.
                self._log(f"chat {chat_id}: /refresh all needs a Garmin login in a terminal")
                stopped, stop_detail = RefreshStop.GARMIN_LOGIN, activity_id
                items.append(RefreshItem(target, RefreshItemStatus.NOT_RUN))
                continue
            except Exception as exc:
                # It did run, so it is a failure; the rest are not run (the error could repeat on each one).
                self._log(f"chat {chat_id}: /refresh all failed with {type(exc).__name__}")
                self._log("".join(traceback.format_exception(exc)).rstrip("\n"))
                stopped, stop_detail = RefreshStop.UNEXPECTED_ERROR, type(exc).__name__
                items.append(RefreshItem(target, RefreshItemStatus.FAILED, before))
                continue
            if result.exit_code == 130:
                return True
            self._log(f"chat {chat_id}: /refresh all {index + 1}/{len(selected)} -> exit {result.exit_code}")
            if result.exit_code == 0:
                failures = 0
                after = self._count_unknown(chat_id, activity_id)
                items.append(RefreshItem(target, RefreshItemStatus.DONE, before, after, result.stdout))
                continue
            failures += 1
            items.append(RefreshItem(target, RefreshItemStatus.FAILED, before, error=_reply_text(result)))
            if failures >= MAX_CONSECUTIVE_REFRESH_FAILURES:
                self._log(f"chat {chat_id}: /refresh all stopped after {failures} consecutive failures")
                stopped = RefreshStop.CONSECUTIVE_FAILURES

        try:
            final = self._commands.run(invocation.argv)
        except Exception as exc:
            self._log(f"chat {chat_id}: /refresh remaining failed with {type(exc).__name__}")
            remaining = None
        else:
            if final.exit_code == 130:
                return True
            self._log(f"chat {chat_id}: /refresh remaining -> exit {final.exit_code}")
            remaining = self._remaining(chat_id, final)
        self._running = None
        summary = BulkRefreshResult(tuple(items), len(targets) - len(selected), stopped, stop_detail, remaining)
        self._send_all(chat_id, self._summaries.refresh_all(summary))
        return False

    def _refresh_targets(self, chat_id: int, outcome: CommandOutcome) -> tuple[tuple[RefreshTarget, ...] | None, str]:
        """The `/unknown` list, or None and the reply that says why nothing was fetched."""
        if not outcome.stdout:
            return None, _reply_text(outcome)
        try:
            document = json.loads(outcome.stdout)
        except ValueError:
            self._log(f"chat {chat_id}: /refresh reply was not JSON; relayed as text")
            return None, _reply_text(outcome)
        try:
            return self._summaries.refresh_targets(document), ""
        except SummaryUnavailableError as exc:
            self._log(f"chat {chat_id}: /refresh summary failed ({exc})")
            return None, REFRESH_ALL_TARGETS_FAILED_TEXT

    def _remaining(self, chat_id: int, outcome: CommandOutcome) -> int | None:
        """How many activities the list holds after the run; None (shown as unknown, never 0) when unreadable."""
        try:
            return len(self._summaries.refresh_targets(json.loads(outcome.stdout)))
        except (ValueError, SummaryUnavailableError) as exc:  # JSONDecodeError is a ValueError
            self._log(f"chat {chat_id}: /refresh remaining count unknown ({type(exc).__name__})")
            return None

    def _count_unknown(self, chat_id: int, activity_id: str) -> ActivityUnknownSets | None:
        """The read-only UNKNOWN count; any failure is None (the reply then falls back to the CLI headline)."""
        try:
            return self._unknown_sets(activity_id)
        except Exception as exc:
            self._log(f"chat {chat_id}: /refresh could not count UNKNOWN sets ({type(exc).__name__})")
            return None

    def _summary_reply(self, chat_id: int, invocation: CliInvocation, outcome: CommandOutcome) -> None:
        """A summary of the CLI JSON, whatever the exit code (`daily` prints JSON and exits 1 on a failed stage)."""
        name = invocation.command
        try:
            document = json.loads(outcome.stdout)
        except ValueError:
            self._log(f"chat {chat_id}: /{name} reply was not JSON; relayed as text")
            self._reply(chat_id, _reply_text(outcome))
            return
        try:
            messages = self._summaries.summary(invocation.reply, document)
        except SummaryUnavailableError as exc:
            self._log(f"chat {chat_id}: /{name} summary failed ({exc})")
            failed = (
                daily_summary_failed_text(outcome.exit_code)
                if invocation.reply is ReplyKind.DAILY_SUMMARY
                else summary_failed_text(name)
            )
            self._reply(chat_id, failed)
            return
        self._send_all(chat_id, messages)

    def _reply(self, chat_id: int, text: str) -> None:
        self._send_all(chat_id, self._format_reply(text))

    def _send_all(self, chat_id: int, messages: Sequence[str]) -> None:
        for html in messages:
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
