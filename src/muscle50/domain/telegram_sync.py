"""Telegram `/sync FROM TO` (Daily Catch-up v1): the date grammar, the limits and the bot's own Korean texts.

`/sync` runs `muscle50 garmin sync --from --to --json` (activities, load metrics and recovery; no
recommendation). Up to `SYNC_UNCONFIRMED_MAX_DAYS` days it runs at once; a longer range first gets an
offer with a one-time `/sync_ok_<id>` command, valid for `SYNC_CONFIRM_TTL_S` seconds, kept in the bot's
memory only. Dates are `YYYY-MM-DD` or `MM-DD` (this year: never guessed otherwise).

Pure and deterministic: no I/O, no clock (today is passed in). It does not import
`domain/telegram_commands.py`, which builds the bot invocation from these pieces.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from muscle50.domain.sync_catch_up import CATCH_UP_LIMIT_DAYS

SYNC_MAX_DAYS = 31
"""The `garmin recovery`/`garmin sync` range limit (`MAX_RECOVERY_RANGE_DAYS`)."""
SYNC_UNCONFIRMED_MAX_DAYS = 7
"""Longer ranges need the `/sync_ok_` confirmation (`garmin sync --yes`)."""
SYNC_CONFIRM_TTL_S = 600
SYNC_REQUESTS_PER_DAY = 9
"""Garmin recovery requests per date (`RECOVERY_ENDPOINTS_PER_DATE`); activity requests come on top."""

_ISO_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
_MONTH_DAY = re.compile(r"[0-9]{2}-[0-9]{2}")
SYNC_CONFIRM_COMMAND = re.compile(r"sync_ok_([0-9a-f]{4})")
"""The command name (without `/`) of a confirmation; the 4 hex digits are the offer's token."""


@dataclass(frozen=True)
class SyncRange:
    start: date
    end: date

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1


@dataclass(frozen=True)
class SyncConfirmNeeded:
    """A valid `/sync` over more than `SYNC_UNCONFIRMED_MAX_DAYS` days: the bot offers a `/sync_ok_` command."""

    range: SyncRange


@dataclass(frozen=True)
class SyncConfirm:
    """`/sync_ok_<token>`."""

    token: str


@dataclass(frozen=True)
class BotRefusal:
    """A well-formed command the bot refuses itself, with this `오류:` reply; nothing runs."""

    text: str


def parse_sync_arguments(tokens: Sequence[str], today: date) -> SyncRange | BotRefusal | None:
    """The range of `/sync A B`, a refusal, or None when the shape is wrong (the bot sends the usage)."""
    if len(tokens) != 2:
        return None
    if not all(_ISO_DATE.fullmatch(token) or _MONTH_DAY.fullmatch(token) for token in tokens):
        return None
    days = []
    for token in tokens:
        text = token if _ISO_DATE.fullmatch(token) else f"{today.year:04d}-{token}"
        try:
            days.append(date.fromisoformat(text))
        except ValueError:
            return BotRefusal(f"오류: 없는 날짜입니다: {token}. 날짜는 YYYY-MM-DD 또는 MM-DD(올해)로 씁니다.")
    start, end = days
    if start > end:
        return BotRefusal(f"오류: 시작 날짜({start.isoformat()})가 끝 날짜({end.isoformat()})보다 늦습니다.")
    if end > today:
        return BotRefusal(
            f"오류: 끝 날짜({end.isoformat()})가 오늘({today.isoformat()}) 이후입니다. 작년 날짜는 YYYY-MM-DD로 쓰세요."
        )
    requested = SyncRange(start, end)
    if requested.days > SYNC_MAX_DAYS:
        return BotRefusal(
            f"오류: 한 번에 최대 {SYNC_MAX_DAYS}일까지 받을 수 있습니다(요청: {requested.days}일). "
            "기간을 나눠 보내세요."
        )
    return requested


def sync_argv(requested: SyncRange, *, confirmed: bool) -> tuple[str, ...]:
    """The CLI argv; `--yes` only after a confirmation (the CLI refuses a long range without it)."""
    yes: tuple[str, ...] = ("--yes",) if confirmed else ()
    return ("garmin", "sync", "--from", requested.start.isoformat(), "--to", requested.end.isoformat(), *yes, "--json")


def needs_confirmation(requested: SyncRange) -> bool:
    return requested.days > SYNC_UNCONFIRMED_MAX_DAYS


def date_text(day: date, today: date) -> str:
    """`MM-DD` in today's year (how the user types it), otherwise `YYYY-MM-DD`."""
    return day.isoformat()[5:] if day.year == today.year else day.isoformat()


def range_text(start: date, end: date, today: date) -> str:
    if start.year == end.year == today.year:
        return f"{start.isoformat()[5:]} ~ {end.isoformat()[5:]}"
    return f"{start.isoformat()} ~ {end.isoformat()}"


def sync_command_text(start: date, end: date, today: date) -> str:
    """The `/sync` command for a range: `MM-DD` only when both dates are in today's year (MM-DD means this year)."""
    if start.year == end.year == today.year:
        return f"/sync {start.isoformat()[5:]} {end.isoformat()[5:]}"
    return f"/sync {start.isoformat()} {end.isoformat()}"


def sync_progress_text(requested: SyncRange, today: date) -> str:
    return (
        f"동기화 실행 중: {range_text(requested.start, requested.end, today)} "
        f"({requested.days}일, Garmin 요청 약 {requested.days * SYNC_REQUESTS_PER_DAY}회). 끝나면 결과를 보냅니다."
    )


def sync_offer_text(requested: SyncRange, today: date) -> str:
    minutes = SYNC_CONFIRM_TTL_S // 60
    return (
        f"{requested.days}일({range_text(requested.start, requested.end, today)}), "
        f"Garmin 요청 약 {requested.days * SYNC_REQUESTS_PER_DAY}회입니다. 받아오려면 누르세요({minutes}분 유효):"
    )


def sync_confirm_command(token: str) -> str:
    return f"/sync_ok_{token}"


SYNC_CONFIRM_INVALID_TEXT = (
    "오류: 이 확인 명령은 없거나, 10분이 지났거나, 이미 쓰였습니다. 다시 받으려면 /sync 시작 끝을 보내세요."
)


def sync_login_text(requested: SyncRange) -> str:
    yes = " --yes" if needs_confirmation(requested) else ""
    return (
        "오류: Garmin에 다시 로그인해야 합니다. PC 터미널에서 "
        f"muscle50 garmin sync --from {requested.start.isoformat()} --to {requested.end.isoformat()}{yes}를 "
        "한 번 실행하세요(로그인한 뒤 그대로 받습니다)."
    )


def sync_summary_failed_text(exit_code: int) -> str:
    return (
        f"오류: 동기화는 끝났지만 결과를 요약하지 못했습니다 (exit {exit_code}). "
        "받은 날짜는 PC에서 muscle50 garmin coverage로 확인하세요."
    )


def older_unsynced_line(start: date, end: date, today: date, *, daily: str) -> str:
    """The `/daily` summary and LLM hint line for days the next `daily` leaves out (without the command)."""
    return (
        f"아직 동기화되지 않은 날: {range_text(start, end, today)} "
        f"({daily}는 {CATCH_UP_LIMIT_DAYS}일 전까지만 받습니다). 받기: "
    )
