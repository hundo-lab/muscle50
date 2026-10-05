"""Garmin Sync Coverage v1: which calendar dates a Garmin sync actually covered.

One latest result per (provider, data kind, calendar date). A date with no recorded result is
``not_synced``; that status is derived here and never stored. Pure and deterministic: no I/O,
no clock. Coverage is reported only; no recommendation rule reads it.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from enum import StrEnum

PROVIDER_GARMIN = "garmin"
# Longest range `garmin coverage` prints in one run.
MAX_COVERAGE_RANGE_DAYS = 366


class CoverageKind(StrEnum):
    ACTIVITIES = "activities"
    RECOVERY = "recovery"


class CoverageStatus(StrEnum):
    SYNCED = "synced"
    """Activities: the whole range was discovered. Recovery: every endpoint answered."""
    PARTIAL = "partial"
    """Recovery only: some endpoints failed; the others were stored."""
    FAILED = "failed"
    NOT_SYNCED = "not_synced"
    """No recorded result. Never stored."""


class CoverageSource(StrEnum):
    SYNC = "sync"
    RAW_BACKFILL = "raw_backfill"
    """Recovery only: derived from a capture stored before coverage was recorded."""


class InvalidCoverageRangeError(ValueError):
    """Raised when a requested coverage range is reversed or too long."""


@dataclass(frozen=True)
class SyncCoverageEntry:
    kind: CoverageKind
    calendar_date: date
    status: CoverageStatus
    source: CoverageSource = CoverageSource.SYNC
    missing_endpoints: tuple[str, ...] = ()
    """Recovery endpoint kinds that failed (partial only)."""
    failed_activity_ids: tuple[str, ...] = ()
    """Garmin activity IDs that failed to import on this date (failed activities only)."""

    def __post_init__(self) -> None:
        if self.status is CoverageStatus.NOT_SYNCED:
            raise ValueError("not_synced is the absence of a record and is never stored")
        if (self.status is CoverageStatus.PARTIAL) != bool(self.missing_endpoints):
            raise ValueError("missing endpoints are recorded exactly for partial recovery")
        if self.status is CoverageStatus.PARTIAL and self.kind is not CoverageKind.RECOVERY:
            raise ValueError("only recovery coverage can be partial")
        failed_activities = self.kind is CoverageKind.ACTIVITIES and self.status is CoverageStatus.FAILED
        if failed_activities != bool(self.failed_activity_ids):
            raise ValueError("failed activity IDs are recorded exactly for failed activity dates")


@dataclass(frozen=True)
class RecordedCoverage:
    entry: SyncCoverageEntry
    command: str
    synced_at_utc: str


@dataclass(frozen=True)
class SyncCoverageData:
    """What a read-only reader found for an inclusive date range."""

    records: tuple[RecordedCoverage, ...]
    stored_activities: Mapping[date, int] = field(default_factory=dict)
    """Stored Garmin activities per local start date (dates without any are absent)."""
    table_present: bool = True
    """False on a database from before the coverage migration."""


@dataclass(frozen=True)
class CoverageDay:
    """One date of a recommendation window (no timestamps, so repeated runs stay identical)."""

    calendar_date: date
    activities: CoverageStatus
    stored_activities: int
    recovery: CoverageStatus
    recovery_source: CoverageSource | None


@dataclass(frozen=True)
class SyncCoverageWindow:
    start: date
    end: date
    days: tuple[CoverageDay, ...]


@dataclass(frozen=True)
class CoverageReportDay:
    calendar_date: date
    stored_activities: int
    activities: RecordedCoverage | None
    recovery: RecordedCoverage | None


def coverage_range_dates(start: date, end: date) -> tuple[date, ...]:
    """Inclusive dates of a `garmin coverage` range, ascending."""
    if start > end:
        raise InvalidCoverageRangeError("--from은 --to보다 이후일 수 없습니다.")
    day_count = (end - start).days + 1
    if day_count > MAX_COVERAGE_RANGE_DAYS:
        raise InvalidCoverageRangeError(
            f"coverage 범위는 최대 {MAX_COVERAGE_RANGE_DAYS}일입니다 (요청: {day_count}일)."
        )
    return _dates(start, end)


def coverage_report_days(
    start: date, end: date, records: Sequence[RecordedCoverage], stored_activities: Mapping[date, int]
) -> tuple[CoverageReportDay, ...]:
    by_key = _by_key(records)
    return tuple(
        CoverageReportDay(
            calendar_date=day,
            stored_activities=stored_activities.get(day, 0),
            activities=by_key.get((CoverageKind.ACTIVITIES, day)),
            recovery=by_key.get((CoverageKind.RECOVERY, day)),
        )
        for day in coverage_range_dates(start, end)
    )


def coverage_window(
    start: date, end: date, records: Sequence[RecordedCoverage], stored_activities: Mapping[date, int]
) -> SyncCoverageWindow | None:
    """Per-date coverage for a recommendation window, or None when no date in it has a record."""
    by_key = {key: value for key, value in _by_key(records).items() if start <= key[1] <= end}
    if not by_key:
        return None
    days = []
    for day in _dates(start, end):
        activities = by_key.get((CoverageKind.ACTIVITIES, day))
        recovery = by_key.get((CoverageKind.RECOVERY, day))
        days.append(
            CoverageDay(
                calendar_date=day,
                activities=activities.entry.status if activities else CoverageStatus.NOT_SYNCED,
                stored_activities=stored_activities.get(day, 0),
                recovery=recovery.entry.status if recovery else CoverageStatus.NOT_SYNCED,
                recovery_source=recovery.entry.source if recovery else None,
            )
        )
    return SyncCoverageWindow(start, end, tuple(days))


def _by_key(records: Sequence[RecordedCoverage]) -> dict[tuple[CoverageKind, date], RecordedCoverage]:
    return {(item.entry.kind, item.entry.calendar_date): item for item in records}


def _dates(start: date, end: date) -> tuple[date, ...]:
    return tuple(start + timedelta(days=offset) for offset in range((end - start).days + 1))
