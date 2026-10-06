"""Telegram Command Bot v1: one chat message -> one muscle50 CLI argv, or a usage reply.

Pure and deterministic: no I/O, no clock (today's date is passed in). The bot never guesses: a
message that does not match the grammar exactly gets the help or that command's usage, and
nothing runs. Every reply text the bot writes itself (as opposed to the CLI output it relays) is
a constant or a small function here, in Korean (user decision, gate 1 D4), so tests can pin them.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum

from muscle50.domain.nutrition import MealType


@dataclass(frozen=True)
class CliInvocation:
    """A well-formed bot command and the exact `muscle50` argv that serves it."""

    command: str
    argv: tuple[str, ...]
    migrates: bool
    """The CLI handler runs `migrate()` (all `nutrition` commands and `daily`), so the bot checks pending migrations."""
    is_daily: bool
    adds_undo: bool


class UsageReason(StrEnum):
    HELP = "help"
    UNKNOWN_COMMAND = "unknown_command"
    NOT_A_COMMAND = "not_a_command"
    MALFORMED = "malformed"


@dataclass(frozen=True)
class UsageReply:
    reason: UsageReason
    command: str | None
    """The command as typed (unknown command), the known command name (help/malformed), or None."""


# --- bot-own reply texts (Korean; command results are relayed unchanged) -------------------------

HELP_TEXT = "\n".join(
    [
        "muscle50 명령:",
        "/today - 오늘 운동 추천",
        "/status - 오늘 영양 상태(목표 대비)",
        "/day [YYYY-MM-DD] - 그날 식사와 합계(기본: 오늘)",
        "/log <meal>[+] <food> <qty> <unit>[, <food> <qty> <unit> ...] - 식사 기록",
        "     meal: breakfast, lunch, dinner, snack, other. 끝에 +를 붙이면 같은 종류 식사를 하나 더 기록",
        "/void <meal_id> [이유] - 기록한 식사 취소(void)",
        "/show <meal_id> - 기록한 식사 하나 보기",
        "/inbody - InBody 체성분 추세",
        "/daily - Garmin 동기화 후 오늘 계획(시간이 걸림)",
        "/help - 이 목록",
    ]
)

_USAGE: dict[str, tuple[str, str]] = {
    "today": ("/today", "/today"),
    "status": ("/status", "/status"),
    "day": ("/day [YYYY-MM-DD]", "/day 2026-10-05"),
    "log": (
        "/log <meal>[+] <food> <qty> <unit>[, <food> <qty> <unit> ...]\n"
        "meal은 breakfast, lunch, dinner, snack, other 중 하나이고, 끝에 +를 붙이면 같은 종류 식사를 하나 더 "
        "기록합니다. 각 item은 쉼표로 나누고, 마지막 두 단어가 수량과 단위입니다.",
        "/log lunch 닭가슴살 150 g, 햇반 1 pack",
    ),
    "void": ("/void <meal_id> [이유]", "/void 2026-10-06-snack-1 중복 기록"),
    "show": ("/show <meal_id>", "/show 2026-10-06-lunch-1"),
    "inbody": ("/inbody", "/inbody"),
    "daily": ("/daily", "/daily"),
    "help": ("/help", "/help"),
    "start": ("/start", "/start"),
}

DAILY_PROGRESS_TEXT = "daily 실행 중: 어제와 오늘의 Garmin 동기화 후 오늘 계획을 만듭니다. 끝나면 결과를 보냅니다."

GARMIN_LOGIN_TEXT = (
    "오류: Garmin에 다시 로그인해야 합니다. "
    "PC 터미널에서 muscle50 daily를 한 번 실행해 로그인한 뒤 /daily를 다시 보내세요."
)

MIGRATION_STATUS_UNKNOWN_TEXT = (
    "오류: DB의 migration 상태를 읽을 수 없어 실행하지 않았습니다. bot은 migration을 적용하지 않습니다. "
    "PC 터미널에서 DB를 확인하세요."
)


def usage_text(command: str) -> str:
    """`사용법:` and `예:` lines of one known command."""
    usage, example = _USAGE[command]
    return f"사용법: {usage}\n예: {example}"


def usage_reply_text(reply: UsageReply) -> str:
    if reply.reason is UsageReason.HELP:
        return HELP_TEXT
    if reply.reason is UsageReason.UNKNOWN_COMMAND:
        return f"모르는 명령입니다: {reply.command}\n\n{HELP_TEXT}"
    if reply.reason is UsageReason.NOT_A_COMMAND:
        return f"명령이 아닙니다.\n\n{HELP_TEXT}"
    return usage_text(reply.command if reply.command is not None else "help")


def undo_line(meal_id: str) -> str:
    return f"취소: /void {meal_id}"


def stale_text(sent_at_local: datetime) -> str:
    return (
        f"실행하지 않음: 이 메시지는 bot이 시작되기 전({sent_at_local:%Y-%m-%d %H:%M})에 보낸 것입니다. "
        "아직 필요하면 다시 보내세요."
    )


def pending_migration_text(versions: Sequence[int]) -> str:
    numbers = ", ".join(f"{version:03d}" for version in versions)
    return (
        f"오류: DB에 아직 적용하지 않은 migration {numbers}이 있습니다. bot은 migration을 적용하지 않습니다. "
        "DB를 백업한 뒤 PC 터미널에서 muscle50 명령 하나로 적용하고 다시 보내세요."
    )


def empty_output_text(exit_code: int) -> str:
    return f"오류: 명령이 아무것도 출력하지 않았습니다 (exit {exit_code})."


def unexpected_error_text(exception_type: str) -> str:
    return f"오류: 예상하지 못한 오류로 명령을 마치지 못했습니다 ({exception_type}). telegram run 콘솔을 확인하세요."


# --- grammar -----------------------------------------------------------------------------------

_NO_ARGUMENT_COMMANDS = frozenset({"today", "status", "inbody", "daily", "help", "start"})
KNOWN_COMMANDS = frozenset(_USAGE)
_MEAL_TOKEN = re.compile(rf"({'|'.join(meal.value for meal in MealType)})(\+)?")


def parse_bot_message(text: str | None, *, bot_username: str, today: date) -> CliInvocation | UsageReply:
    """The CLI invocation for a well-formed command; otherwise the help or a usage reply.

    A token that starts with ``-`` is refused in every command, so no message can inject a CLI flag
    (for example ``/show --json``).
    """
    if text is None:
        return UsageReply(UsageReason.NOT_A_COMMAND, None)
    head, rest = _split_first_token(text)
    if not head.startswith("/"):
        return UsageReply(UsageReason.NOT_A_COMMAND, None)
    name, at, suffix = head.partition("@")
    if at and suffix.lower() != bot_username.lower():
        return UsageReply(UsageReason.UNKNOWN_COMMAND, head)
    command = name[1:]
    if command not in KNOWN_COMMANDS:
        return UsageReply(UsageReason.UNKNOWN_COMMAND, head)
    tokens = rest.split()
    malformed = UsageReply(UsageReason.MALFORMED, command)
    if any(token.startswith("-") for token in tokens):
        return malformed
    if command in _NO_ARGUMENT_COMMANDS:
        if tokens:
            return malformed
        return _no_argument_command(command, today)
    if command == "day":
        if len(tokens) > 1:
            return malformed
        return CliInvocation(
            command, ("nutrition", "day", *(("--date", *tokens) if tokens else ())), True, False, False
        )
    if command == "show":
        if len(tokens) != 1:
            return malformed
        return CliInvocation(command, ("nutrition", "meal", "show", tokens[0]), True, False, False)
    if command == "void":
        if not tokens:
            return malformed
        meal_id, reason = _split_first_token(rest)
        # The `=` form keeps the reason one argv item whatever it contains.
        argv = ("nutrition", "meal", "void", meal_id, *((f"--reason={reason.strip()}",) if reason.strip() else ()))
        return CliInvocation(command, argv, True, False, False)
    return _log_command(rest)


def _no_argument_command(command: str, today: date) -> CliInvocation | UsageReply:
    if command in ("help", "start"):
        return UsageReply(UsageReason.HELP, command)
    if command == "today":
        return CliInvocation(command, ("recommend", "--date", today.isoformat()), False, False, False)
    if command == "status":
        return CliInvocation(command, ("nutrition", "status"), True, False, False)
    if command == "inbody":
        return CliInvocation(command, ("inbody", "trend"), False, False, False)
    return CliInvocation(command, ("daily",), True, True, False)


def _log_command(rest: str) -> CliInvocation | UsageReply:
    """`/log <meal>[+] <food> <qty> <unit>[, ...]`: the last two words of an item are quantity and unit."""
    malformed = UsageReply(UsageReason.MALFORMED, "log")
    meal_token, items_text = _split_first_token(rest)
    match = _MEAL_TOKEN.fullmatch(meal_token)
    if match is None or not items_text:
        return malformed
    argv: list[str] = ["nutrition", "log", "--meal", match.group(1)]
    for item in items_text.split(","):
        words = item.split()
        if len(words) < 3:
            return malformed
        argv.extend(["--item", " ".join(words[:-2]), words[-2], words[-1]])
    if match.group(2):
        argv.append("--additional")
    return CliInvocation("log", tuple(argv), True, False, True)


def _split_first_token(text: str) -> tuple[str, str]:
    """The first whitespace-separated word and the stripped rest (inner whitespace kept)."""
    parts = text.split(maxsplit=1)
    if not parts:
        return "", ""
    return parts[0], parts[1].strip() if len(parts) > 1 else ""
