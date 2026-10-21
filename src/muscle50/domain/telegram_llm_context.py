"""Telegram LLM v2.5: what the coach is told about the bot itself (its commands) and about Garmin sync coverage.

Pure and deterministic: the documents come from the CLI's own JSON (`garmin coverage --json`) and the bot's help
text; the date is passed in. Missing is not zero: a database without the coverage table reads "알 수 없음", never
"빠진 날 없음". Nothing here holds a token, a chat id or account data.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import date, timedelta
from typing import Any

COVERAGE_DAYS = 14
"""The coach sees the last 14 days, today included; gaps are judged on the 13 days before today."""
MAX_COMMAND_LINES = 4
NO_GAPS_TEXT = "빠진 날 없음"
NO_TABLE_TEXT = "동기화 기록이 이 DB에 아직 없습니다(알 수 없음)."
_COMMAND = re.compile(r"/[a-z_]+")
_STATE_NAMES = {"synced": "동기화됨", "not_synced": "동기화 안 됨", "failed": "동기화 실패", "partial": "일부만"}


def coverage_range(today: date) -> tuple[date, date]:
    """The first and last date of the coverage the coach is told about."""
    return today - timedelta(days=COVERAGE_DAYS - 1), today


def coverage_summary(document: Any, today: date) -> str:
    """The `<동기화 상태>` text of a `garmin coverage --from D-13 --to D --json` document.

    Raises KeyError, TypeError or ValueError when the document is not that shape (the caller leaves the block out).
    """
    if document["coverage_table_present"] is not True:
        return NO_TABLE_TEXT
    start, end = coverage_range(today)
    days: dict[date, dict[str, Any]] = {}
    for day in document["days"]:
        days[date.fromisoformat(day["date"])] = day
    past = [start + timedelta(days=offset) for offset in range(COVERAGE_DAYS - 1)]
    activity_lines: list[str] = []
    recovery_lines: list[str] = []
    for status, label in (("not_synced", "운동 동기화 안 됨"), ("failed", "운동 동기화 실패")):
        found = [day for day in past if _status(days, day, "activities") == status]
        if found:
            activity_lines.append(f"{label}: {_ranges(found)}")
    for status, label in (
        ("not_synced", "회복 동기화 안 됨"),
        ("failed", "회복 동기화 실패"),
        ("partial", "회복 일부만"),
    ):
        found = [day for day in past if _status(days, day, "recovery") == status]
        if found:
            recovery_lines.append(f"{label}: {_ranges(found)}")
    lines = [f"기간 {start:%m-%d}~{end:%m-%d} ({COVERAGE_DAYS}일, 오늘 포함)"]
    if activity_lines:
        lines.append(" · ".join(activity_lines))
    if recovery_lines:
        lines.append(" · ".join(recovery_lines))
    if not activity_lines and not recovery_lines:
        lines.append(NO_GAPS_TEXT)
    empty = [day for day in past if _status(days, day, "activities") == "synced" and _stored(days, day) == 0]
    if empty:
        lines.append(f"동기화했고 운동 없음: {_ranges(empty)}")
    lines.append(f"오늘: 운동 {_today_state(days, end, 'activities')}, 회복 {_today_state(days, end, 'recovery')}")
    return "\n".join(lines)


def known_commands(help_text: str) -> tuple[str, ...]:
    """The bot's commands as listed in its help text (the first word of each line that starts with `/`)."""
    found: list[str] = []
    for line in help_text.splitlines():
        if line.startswith("/"):
            command = line.split(maxsplit=1)[0]
            if command not in found:
                found.append(command)
    return tuple(found)


def command_lines(answer: str, known: Sequence[str]) -> tuple[str, ...]:
    """The known commands an answer names, in order of appearance, without repeats, at most `MAX_COMMAND_LINES`:
    sent as their own lines so that one tap runs them. A command the help text does not list is never offered."""
    found: list[str] = []
    for match in _COMMAND.finditer(answer):
        command = match.group(0)
        if command in known and command not in found:
            found.append(command)
    return tuple(found[:MAX_COMMAND_LINES])


def _status(days: dict[date, dict[str, Any]], day: date, kind: str) -> str:
    entry = days.get(day)
    if entry is None:
        return "not_synced"
    status = entry[kind]["status"]
    if not isinstance(status, str):
        raise ValueError(f"{kind}.status is not a string")
    return status


def _stored(days: dict[date, dict[str, Any]], day: date) -> int | None:
    stored = days[day]["activities"].get("stored_activities")
    return stored if type(stored) is int else None


def _today_state(days: dict[date, dict[str, Any]], day: date, kind: str) -> str:
    status = _status(days, day, kind)
    if kind == "activities" and status == "synced" and _stored(days, day) == 0:
        return "동기화했고 운동 없음"
    return _STATE_NAMES.get(status, status)


def _ranges(days: Sequence[date]) -> str:
    """`10-09~10-18, 10-20`: consecutive dates as one range."""
    groups: list[list[date]] = []
    for day in sorted(days):
        if groups and day - groups[-1][-1] == timedelta(days=1):
            groups[-1].append(day)
        else:
            groups.append([day])
    return ", ".join(
        f"{group[0]:%m-%d}" if len(group) == 1 else f"{group[0]:%m-%d}~{group[-1]:%m-%d}" for group in groups
    )
