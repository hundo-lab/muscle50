"""Daily Catch-up v1: where `daily` starts so that days it missed are not left unsynced.

`daily` used to sync D-1..D only. It now starts the day after the last day whose coverage
(`domain/sync_coverage.py`) is complete, but never later than D-1 (the old minimum) and never
earlier than D-7 (`CATCH_UP_LIMIT_DAYS`, about 9 recovery requests per day). Older unsynced days
are only reported, with the command that fetches them.

A day is complete when every kind it needs (activities, plus recovery outside after-workout
mode) has a ``synced`` row written on a later local date than the day itself. A row written on
the same day (for example by a morning `daily`, which records today too) only covers that day up
to that moment, so it does not count. ``partial``, ``failed`` and missing rows are not complete.

Pure and deterministic: no I/O, no clock. The records and the computer's fixed UTC offset are
passed in.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta, tzinfo

from muscle50.domain.sync_coverage import CoverageKind, CoverageStatus, RecordedCoverage

CATCH_UP_LIMIT_DAYS = 7
"""`daily` syncs at most D-7..D (eight days including today)."""
CATCH_UP_LOOKBACK_DAYS = 31
"""Coverage rows of D-31..D-1 are read to find the last complete day."""
GARMIN_SYNC_UNCONFIRMED_MAX_DAYS = 7
"""`garmin sync` (and Telegram `/sync`) asks for a confirmation above this many days, like `garmin recovery`."""


@dataclass(frozen=True)
class DailyCatchUp:
    as_of: date
    start: date
    """First day `daily` syncs: between D-7 and D-1."""
    last_synced: date | None
    """The latest complete day in D-31..D-1, or None."""
    older_unsynced: tuple[date, date] | None
    """Unsynced days before ``start`` that `daily` does not fetch (inclusive), or None."""
    activities_only: bool
    """After-workout mode: only activity coverage was read."""

    @property
    def reported(self) -> bool:
        """True when the range starts before D-1, so the output says why."""
        return self.start < self.as_of - timedelta(days=1)


def plan_catch_up(
    as_of: date,
    records: Sequence[RecordedCoverage],
    *,
    activities_only: bool,
    local_timezone: Callable[[date], tzinfo],
) -> DailyCatchUp:
    yesterday = as_of - timedelta(days=1)
    earliest = as_of - timedelta(days=CATCH_UP_LIMIT_DAYS)
    window_start = as_of - timedelta(days=CATCH_UP_LOOKBACK_DAYS)
    kinds = (CoverageKind.ACTIVITIES,) if activities_only else (CoverageKind.ACTIVITIES, CoverageKind.RECOVERY)
    relevant = [
        record
        for record in records
        if record.entry.kind in kinds and window_start <= record.entry.calendar_date <= yesterday
    ]
    if not relevant:
        # No record at all (a new install, or a database from before coverage): the old D-1 range.
        return DailyCatchUp(as_of, yesterday, None, None, activities_only)
    complete_kinds: dict[date, set[CoverageKind]] = {}
    for record in relevant:
        if _complete(record, local_timezone):
            complete_kinds.setdefault(record.entry.calendar_date, set()).add(record.entry.kind)
    complete_days = [day for day, found in complete_kinds.items() if all(kind in found for kind in kinds)]
    last_synced = max(complete_days) if complete_days else None
    if last_synced is not None:
        gap_start = last_synced + timedelta(days=1)
    else:
        gap_start = min(record.entry.calendar_date for record in relevant)
    start = max(min(gap_start, yesterday), earliest)
    older = (gap_start, earliest - timedelta(days=1)) if gap_start < earliest else None
    return DailyCatchUp(as_of, start, last_synced, older, activities_only)


def _complete(record: RecordedCoverage, local_timezone: Callable[[date], tzinfo]) -> bool:
    if record.entry.status is not CoverageStatus.SYNCED:
        return False
    written = _local_date(record.synced_at_utc, local_timezone)
    return written is not None and written > record.entry.calendar_date


def _local_date(synced_at_utc: str, local_timezone: Callable[[date], tzinfo]) -> date | None:
    """The local date a row was written on; None (never complete) when the timestamp cannot be read."""
    try:
        instant = datetime.fromisoformat(synced_at_utc)
    except ValueError:
        return None
    if instant.tzinfo is None:
        instant = instant.replace(tzinfo=UTC)  # the column is UTC by contract
    return instant.astimezone(local_timezone(instant.astimezone(UTC).date())).date()
