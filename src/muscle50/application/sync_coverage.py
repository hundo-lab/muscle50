"""Record, backfill and show Garmin sync coverage (Sync Coverage v1).

Coverage is computed from the result objects the existing sync use cases already return, so
no sync semantics change. It is written in its own transaction after the sync has finished: a
failed coverage write never loses or fails the sync, and a missing row reads as ``not_synced``
(fail-safe: a failed write never claims ``synced``). Dates after ``through`` (this computer's
today, passed in by the CLI) are never recorded.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Protocol

from muscle50.application.ingest_activity_range import RangeIngestResult
from muscle50.application.sync_garmin_recovery import RECOVERY_ENDPOINT_KINDS, RecoveryRangeOutcome
from muscle50.domain.sync_coverage import (
    CoverageKind,
    CoverageReportDay,
    CoverageSource,
    CoverageStatus,
    RecordedCoverage,
    SyncCoverageData,
    SyncCoverageEntry,
    coverage_range_dates,
    coverage_report_days,
)

COMMAND_GARMIN_ACTIVITIES = "garmin activities"
COMMAND_GARMIN_RECOVERY = "garmin recovery"
COMMAND_DAILY = "daily"
COMMAND_RECOVERY_COVERAGE_BACKFILL = "garmin backfill-recovery-coverage"


class SyncCoverageStore(Protocol):
    def record(self, entries: Sequence[SyncCoverageEntry], *, command: str) -> None:
        """Replace the latest result of every entry's date in one all-or-nothing transaction."""
        ...


@dataclass(frozen=True)
class RecoveryBackfillCandidate:
    calendar_date: date
    artifact_kinds: frozenset[str]
    captured_at_utc: str


@dataclass(frozen=True)
class RecoveryBackfillCandidates:
    recovery_dates: int
    """Stored recovery rows (each has an accepted RAW capture)."""
    already_recorded: int
    candidates: tuple[RecoveryBackfillCandidate, ...]
    """Recovery rows with no recovery coverage row yet, ascending by date."""


class RecoveryCoverageBackfillStore(Protocol):
    def recovery_backfill_candidates(self) -> RecoveryBackfillCandidates: ...

    def insert_backfill(self, records: Sequence[RecordedCoverage]) -> tuple[date, ...]:
        """Insert only where no row exists (checked in the writing transaction); returns the dates added."""
        ...


class SyncCoverageSource(Protocol):
    def load_sync_coverage(self, start: date, end: date) -> SyncCoverageData: ...


def activity_range_coverage(result: RangeIngestResult, *, through: date) -> tuple[SyncCoverageEntry, ...]:
    """Every date of a completely discovered range: ``failed`` where an activity failed, else ``synced``.

    A range is complete only if discovery returned, the page limit was not reached, and no listed
    entry lacked a readable date or ID (such an entry could belong to any date of the range).
    """
    if result.page_limit_reached or result.undated_count:
        return ()
    failed: dict[date, list[str]] = {}
    for outcome in result.outcomes:
        if outcome.status != "failed":
            continue
        if outcome.local_date is None:
            return ()  # a failure that cannot be placed on a date: no date is recorded as synced
        failed.setdefault(outcome.local_date, []).append(outcome.source_activity_id)
    entries = []
    for day in _days(result.from_date, min(result.to_date, through)):
        failed_ids = tuple(sorted(failed.get(day, ())))
        status = CoverageStatus.FAILED if failed_ids else CoverageStatus.SYNCED
        entries.append(SyncCoverageEntry(CoverageKind.ACTIVITIES, day, status, failed_activity_ids=failed_ids))
    return tuple(entries)


def recovery_range_coverage(
    outcomes: Sequence[RecoveryRangeOutcome], *, through: date
) -> tuple[SyncCoverageEntry, ...]:
    """``synced``/``partial``/``failed`` per attempted date.

    Dates that failed on authentication or were not attempted stay unrecorded (``not_synced``).
    """
    entries = []
    for outcome in outcomes:
        day = date.fromisoformat(outcome.calendar_date)
        if day > through or outcome.status == "not_attempted":
            continue
        if outcome.status == "failed":
            if not outcome.authentication_failed:
                entries.append(SyncCoverageEntry(CoverageKind.RECOVERY, day, CoverageStatus.FAILED))
            continue
        if outcome.result is None:
            continue
        missing = outcome.result.missing_endpoints
        status = CoverageStatus.PARTIAL if missing else CoverageStatus.SYNCED
        entries.append(SyncCoverageEntry(CoverageKind.RECOVERY, day, status, missing_endpoints=missing))
    return tuple(entries)


def coverage_not_recorded_message(error: str) -> str:
    return f"sync coverage를 기록하지 못했습니다 (동기화된 데이터는 저장됨): {error}"


@dataclass(frozen=True)
class CoverageRecordResult:
    entries: int
    error: str | None = None
    """The database error when the coverage write failed (nothing was recorded)."""


class RecordSyncCoverage:
    def __init__(self, store: SyncCoverageStore, *, command: str, through: date) -> None:
        self._store = store
        self._command = command
        self._through = through

    def activities(self, result: RangeIngestResult) -> CoverageRecordResult:
        return self._record(activity_range_coverage(result, through=self._through))

    def recovery(self, outcomes: Sequence[RecoveryRangeOutcome]) -> CoverageRecordResult:
        return self._record(recovery_range_coverage(outcomes, through=self._through))

    def _record(self, entries: tuple[SyncCoverageEntry, ...]) -> CoverageRecordResult:
        if not entries:
            return CoverageRecordResult(0)
        try:
            self._store.record(entries, command=self._command)
        except sqlite3.Error as exc:
            # The sync itself already committed; losing its coverage only leaves the dates not_synced.
            return CoverageRecordResult(0, str(exc))
        return CoverageRecordResult(len(entries))


@dataclass(frozen=True)
class RecoveryCoverageBackfillResult:
    dry_run: bool
    recovery_dates: int
    already_recorded: int
    added_synced: tuple[SyncCoverageEntry, ...]
    added_partial: tuple[SyncCoverageEntry, ...]


class BackfillRecoveryCoverage:
    """Record recovery coverage for dates stored before coverage existed, from their accepted capture.

    RAW-metadata only: no Garmin call and no RAW file is read or written. A capture artifact kind
    that is absent means that endpoint failed, so the date is ``partial``. Dates that already
    have a coverage row are never changed, so it is idempotent.
    """

    def __init__(self, store: RecoveryCoverageBackfillStore) -> None:
        self._store = store

    def execute(self, *, dry_run: bool = False) -> RecoveryCoverageBackfillResult:
        found = self._store.recovery_backfill_candidates()
        records = tuple(
            RecordedCoverage(_backfill_entry(item), COMMAND_RECOVERY_COVERAGE_BACKFILL, item.captured_at_utc)
            for item in found.candidates
        )
        if dry_run:
            added = tuple(item.entry for item in records)
        else:
            inserted = set(self._store.insert_backfill(records))
            added = tuple(item.entry for item in records if item.entry.calendar_date in inserted)
        return RecoveryCoverageBackfillResult(
            dry_run=dry_run,
            recovery_dates=found.recovery_dates,
            # A candidate that gained a row before the write is counted as already recorded.
            already_recorded=found.already_recorded + len(records) - len(added),
            added_synced=tuple(item for item in added if item.status is CoverageStatus.SYNCED),
            added_partial=tuple(item for item in added if item.status is CoverageStatus.PARTIAL),
        )


def _backfill_entry(candidate: RecoveryBackfillCandidate) -> SyncCoverageEntry:
    missing = tuple(kind for kind in RECOVERY_ENDPOINT_KINDS if kind not in candidate.artifact_kinds)
    return SyncCoverageEntry(
        CoverageKind.RECOVERY,
        candidate.calendar_date,
        CoverageStatus.PARTIAL if missing else CoverageStatus.SYNCED,
        CoverageSource.RAW_BACKFILL,
        missing_endpoints=missing,
    )


@dataclass(frozen=True)
class SyncCoverageReport:
    start: date
    end: date
    table_present: bool
    days: tuple[CoverageReportDay, ...]


class ShowSyncCoverage:
    def __init__(self, source: SyncCoverageSource) -> None:
        self._source = source

    def execute(self, from_date: date, to_date: date) -> SyncCoverageReport:
        coverage_range_dates(from_date, to_date)  # validate before touching the database
        data = self._source.load_sync_coverage(from_date, to_date)
        days = coverage_report_days(from_date, to_date, data.records, data.stored_activities)
        return SyncCoverageReport(from_date, to_date, data.table_present, days)


def _days(start: date, end: date) -> tuple[date, ...]:
    return tuple(start + timedelta(days=offset) for offset in range((end - start).days + 1))
