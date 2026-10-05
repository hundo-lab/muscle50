"""Sync Coverage v1: coverage rules, repository and the daily stage policy (no CLI, no Garmin)."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable, Sequence
from datetime import date
from pathlib import Path
from typing import Any

import pytest
import sync_coverage_builders as builders

from muscle50.application.daily_sync import (
    STAGE_ACTIVITIES,
    STAGE_RECOVERY,
    DailyGarminConnector,
    DailySyncResult,
    RunDailySync,
    StageStatus,
)
from muscle50.application.ingest_activity_range import RangeIngestOutcome, RangeIngestResult
from muscle50.application.sync_coverage import (
    BackfillRecoveryCoverage,
    CoverageRecordResult,
    RecordSyncCoverage,
    RecoveryBackfillCandidate,
    RecoveryBackfillCandidates,
    activity_range_coverage,
    recovery_range_coverage,
)
from muscle50.application.sync_garmin_recovery import (
    RECOVERY_ENDPOINT_KINDS,
    RecoveryRangeOutcome,
    RecoveryRangeSyncResult,
    RecoverySyncResult,
)
from muscle50.domain.exercise_taxonomy import MuscleGroup
from muscle50.domain.strength_recommendation import StrengthFocus
from muscle50.domain.sync_coverage import (
    CoverageKind,
    CoverageSource,
    CoverageStatus,
    InvalidCoverageRangeError,
    RecordedCoverage,
    SyncCoverageEntry,
    coverage_range_dates,
    coverage_window,
)
from muscle50.domain.training_recommendation import TrainingRecommendation, build_training_recommendation
from muscle50.infrastructure.raw_store import _RECOVERY_ARTIFACT_FILES
from muscle50.infrastructure.sqlite.database import ActivityRepository
from muscle50.infrastructure.sqlite.sync_coverage import SqliteSyncCoverageRepository
from muscle50.presentation.sync_coverage_terminal import sync_coverage_freshness_lines

D1, D2, D3, D4, D5 = (date(2026, 10, day) for day in range(1, 6))
ACT = CoverageKind.ACTIVITIES
REC = CoverageKind.RECOVERY
SYNCED, PARTIAL, FAILED = CoverageStatus.SYNCED, CoverageStatus.PARTIAL, CoverageStatus.FAILED
_STORED = object()  # stands in for the stored DailyRecovery, which coverage never reads


def _range(
    start: date, end: date, *outcomes: RangeIngestOutcome, undated: int = 0, page_limit: bool = False
) -> RangeIngestResult:
    return RangeIngestResult(start, end, len(outcomes), tuple(outcomes), undated, page_limit)


def _outcome(activity_id: str, status: str, day: date | None) -> RangeIngestOutcome:
    return RangeIngestOutcome(activity_id, "running", status, local_date=day)  # type: ignore[arg-type]


def _statuses(entries: Iterable[SyncCoverageEntry]) -> dict[date, CoverageStatus]:
    return {entry.calendar_date: entry.status for entry in entries}


# --- activity rules ----------------------------------------------------------------------------


def test_a_completely_discovered_range_is_synced_on_every_date_including_days_without_activity() -> None:
    result = _range(D1, D3, _outcome("1", "inserted", D1), _outcome("2", "skipped", D3))

    entries = activity_range_coverage(result, through=D5)

    assert _statuses(entries) == {D1: SYNCED, D2: SYNCED, D3: SYNCED}
    assert all(entry.kind is ACT and entry.source is CoverageSource.SYNC for entry in entries)


def test_a_date_with_a_failed_activity_is_failed_with_its_ids() -> None:
    result = _range(D1, D2, _outcome("9", "failed", D2), _outcome("10", "inserted", D2), _outcome("8", "failed", D2))

    entries = activity_range_coverage(result, through=D5)

    assert _statuses(entries) == {D1: SYNCED, D2: FAILED}
    assert entries[1].failed_activity_ids == ("8", "9")
    assert entries[0].failed_activity_ids == ()


@pytest.mark.parametrize("extra", [{"page_limit": True}, {"undated": 1}])
def test_an_incomplete_discovery_records_nothing(extra: dict[str, Any]) -> None:
    assert activity_range_coverage(_range(D1, D3, **extra), through=D5) == ()


def test_a_failure_without_a_date_records_nothing() -> None:
    assert activity_range_coverage(_range(D1, D3, _outcome("1", "failed", None)), through=D5) == ()


def test_activity_dates_after_today_are_not_recorded() -> None:
    assert _statuses(activity_range_coverage(_range(D2, D5), through=D3)) == {D2: SYNCED, D3: SYNCED}
    assert activity_range_coverage(_range(D4, D5), through=D3) == ()


# --- recovery rules ----------------------------------------------------------------------------


def _recovery_outcome(day: date, status: str, missing: tuple[str, ...] = (), **extra: Any) -> RecoveryRangeOutcome:
    result = None
    if status in ("created", "updated", "unchanged"):
        result = RecoverySyncResult(_STORED, status == "created", status == "updated", (), missing)  # type: ignore[arg-type]
    return RecoveryRangeOutcome(day.isoformat(), status, result, **extra)  # type: ignore[arg-type]


def test_recovery_statuses_per_attempted_date() -> None:
    outcomes = [
        _recovery_outcome(D1, "created"),
        _recovery_outcome(D2, "unchanged", ("hrv", "respiration")),
        _recovery_outcome(D3, "failed", error="all endpoints failed"),
        _recovery_outcome(D4, "failed", error="token expired", authentication_failed=True),
        _recovery_outcome(D5, "not_attempted"),
    ]

    entries = recovery_range_coverage(outcomes, through=D5)

    assert _statuses(entries) == {D1: SYNCED, D2: PARTIAL, D3: FAILED}  # D4 auth, D5 not attempted: not synced
    assert entries[1].missing_endpoints == ("hrv", "respiration")
    assert all(entry.kind is REC and entry.source is CoverageSource.SYNC for entry in entries)


def test_recovery_dates_after_today_are_not_recorded() -> None:
    outcomes = [_recovery_outcome(D1, "created"), _recovery_outcome(D2, "updated")]
    assert _statuses(recovery_range_coverage(outcomes, through=D1)) == {D1: SYNCED}


def test_recovery_endpoint_kinds_are_the_nine_raw_artifact_kinds_in_connector_order() -> None:
    assert len(RECOVERY_ENDPOINT_KINDS) == 9
    assert set(RECOVERY_ENDPOINT_KINDS) == set(_RECOVERY_ARTIFACT_FILES)
    assert RECOVERY_ENDPOINT_KINDS == builders.ALL_RECOVERY_KINDS


def test_entries_reject_shapes_the_schema_also_rejects() -> None:
    with pytest.raises(ValueError):
        SyncCoverageEntry(ACT, D1, CoverageStatus.NOT_SYNCED)
    with pytest.raises(ValueError):
        SyncCoverageEntry(ACT, D1, PARTIAL, missing_endpoints=("hrv",))
    with pytest.raises(ValueError):
        SyncCoverageEntry(REC, D1, PARTIAL)
    with pytest.raises(ValueError):
        SyncCoverageEntry(ACT, D1, FAILED)


def test_coverage_range_limits() -> None:
    assert coverage_range_dates(D1, D1) == (D1,)
    assert len(coverage_range_dates(date(2026, 1, 1), date(2027, 1, 1))) == 366
    with pytest.raises(InvalidCoverageRangeError):
        coverage_range_dates(D2, D1)
    with pytest.raises(InvalidCoverageRangeError):
        coverage_range_dates(date(2026, 1, 1), date(2027, 1, 2))


# --- recommendation window ---------------------------------------------------------------------


def _recorded(kind: CoverageKind, day: date, status: CoverageStatus, **extra: Any) -> RecordedCoverage:
    return RecordedCoverage(SyncCoverageEntry(kind, day, status, **extra), "daily", "2026-10-05T00:00:00.000000+00:00")


def test_window_is_absent_without_a_record_in_it() -> None:
    assert coverage_window(D2, D4, [], {}) is None
    assert coverage_window(D2, D4, [_recorded(ACT, D1, SYNCED), _recorded(REC, D5, SYNCED)], {}) is None


def test_window_lines_separate_synced_without_activity_from_not_synced() -> None:
    records = [
        _recorded(ACT, D1, SYNCED),
        _recorded(ACT, D2, FAILED, failed_activity_ids=("7",)),
        _recorded(ACT, D3, SYNCED),
        _recorded(REC, D1, SYNCED, source=CoverageSource.RAW_BACKFILL),
        _recorded(REC, D2, PARTIAL, missing_endpoints=("hrv",)),
        _recorded(REC, D3, SYNCED),
    ]
    window = coverage_window(D1, D5, records, {D3: 2, D5: 1})
    assert window is not None

    assert sync_coverage_freshness_lines(window) == [
        "  sync coverage 2026-10-01..2026-10-05: activities synced 2, failed 1, not synced 2 days; "
        "recovery synced 2 (1 backfilled from RAW), partial 1, failed 0, not synced 2 days",
        "  days with no stored activity: synced, no activity: 2026-10-01; sync failed: 2026-10-02; "
        "not synced: 2026-10-04",
    ]
    assert [day.recovery_source for day in window.days] == [CoverageSource.RAW_BACKFILL, CoverageSource.SYNC] + [
        CoverageSource.SYNC,
        None,
        None,
    ]


def test_consecutive_dates_are_joined_and_empty_segments_say_none() -> None:
    window = coverage_window(D1, D5, [_recorded(REC, D3, SYNCED)], {})
    assert window is not None
    assert sync_coverage_freshness_lines(window)[1] == (
        "  days with no stored activity: synced, no activity: none; sync failed: none; "
        "not synced: 2026-10-01..2026-10-05"
    )


def test_recommendation_decisions_ignore_coverage() -> None:
    records = [_recorded(ACT, D4, SYNCED), _recorded(REC, D5, FAILED)]
    without = build_training_recommendation(D5, [], [])
    with_coverage = build_training_recommendation(D5, [], [], sync_coverage=records)

    assert without.data_freshness.sync_coverage is None and not without.data_freshness.sync_coverage_recorded
    assert with_coverage.data_freshness.sync_coverage_recorded
    for field in ("strength", "swimming", "recovery", "notices", "excluded_same_day_strength_ids"):
        assert getattr(with_coverage, field) == getattr(without, field)


# --- repository --------------------------------------------------------------------------------


@pytest.fixture
def database(tmp_path: Path) -> Path:
    path = tmp_path / "db" / "muscle50.sqlite3"
    ActivityRepository(path).migrate()
    return path


def _rows(database: Path) -> list[tuple[Any, ...]]:
    with sqlite3.connect(database) as connection:
        return connection.execute("SELECT * FROM sync_coverage ORDER BY data_kind, calendar_date").fetchall()


def test_record_replaces_the_latest_result_of_a_date(database: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import muscle50.infrastructure.sqlite.sync_coverage as module

    repository = SqliteSyncCoverageRepository(database)
    monkeypatch.setattr(module, "_now", lambda: "2026-10-01T00:00:00.000000+00:00")
    repository.record([SyncCoverageEntry(REC, D1, PARTIAL, missing_endpoints=("hrv", "stress"))], command="daily")
    monkeypatch.setattr(module, "_now", lambda: "2026-10-02T00:00:00.000000+00:00")
    repository.record([SyncCoverageEntry(REC, D1, SYNCED)], command="garmin recovery")

    assert _rows(database) == [
        (
            "garmin",
            "recovery",
            "2026-10-01",
            "synced",
            "sync",
            "garmin recovery",
            None,
            None,
            "2026-10-02T00:00:00.000000+00:00",
        )
    ]


def test_record_is_all_or_nothing(database: Path) -> None:
    with sqlite3.connect(database) as connection:
        connection.execute(
            "CREATE TRIGGER fail_step BEFORE INSERT ON sync_coverage WHEN NEW.calendar_date = '2026-10-03' "
            "BEGIN SELECT RAISE(ABORT, 'synthetic coverage failure'); END"
        )
    entries = [SyncCoverageEntry(ACT, day, SYNCED) for day in (D1, D2, D3)]

    with pytest.raises(sqlite3.IntegrityError, match="synthetic coverage failure"):
        SqliteSyncCoverageRepository(database).record(entries, command="daily")

    assert _rows(database) == []


@pytest.mark.parametrize(
    "values",
    [
        ("activities", "partial", "sync", "hrv", None),  # only recovery can be partial
        ("recovery", "failed", "raw_backfill", None, None),  # a backfill never records failure
        ("activities", "failed", "sync", None, None),  # failed activity dates name their activities
        ("recovery", "synced", "sync", "hrv", None),  # missing endpoints only on partial
    ],
)
def test_schema_rejects_inconsistent_rows(database: Path, values: tuple[Any, ...]) -> None:
    kind, status, source, missing, failed = values
    with sqlite3.connect(database) as connection, pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            "INSERT INTO sync_coverage VALUES ('garmin', ?, '2026-10-01', ?, ?, 'daily', ?, ?, 'now')",
            (kind, status, source, missing, failed),
        )


def _backfilled(day: date, status: CoverageStatus = SYNCED, **extra: Any) -> RecordedCoverage:
    entry = SyncCoverageEntry(REC, day, status, CoverageSource.RAW_BACKFILL, **extra)
    return RecordedCoverage(entry, "garmin backfill-recovery-coverage", "2026-09-30T21:00:00.000000+00:00")


def test_backfill_insert_never_replaces_an_existing_row(database: Path) -> None:
    # The in-transaction re-check: a sync row written after the candidates were read must win.
    repository = SqliteSyncCoverageRepository(database)
    repository.record([SyncCoverageEntry(REC, D1, FAILED)], command="garmin recovery")
    before = _rows(database)

    added = repository.insert_backfill([_backfilled(D1), _backfilled(D2, PARTIAL, missing_endpoints=("hrv",))])

    assert added == (D2,)
    rows = _rows(database)
    assert rows[0] == before[0]
    assert rows[1][1:8] == (
        "recovery",
        "2026-10-02",
        "partial",
        "raw_backfill",
        "garmin backfill-recovery-coverage",
        "hrv",
        None,
    )


class _RacingStore:
    """Candidates read before a sync recorded D1; the insert then finds D1 already recorded."""

    def __init__(self) -> None:
        self.inserted: list[RecordedCoverage] = []

    def recovery_backfill_candidates(self) -> RecoveryBackfillCandidates:
        kinds = frozenset(RECOVERY_ENDPOINT_KINDS)
        candidates = (
            RecoveryBackfillCandidate(D1, kinds, "2026-10-01T21:00:00.000000+00:00"),
            RecoveryBackfillCandidate(D2, kinds - {"respiration"}, "2026-10-02T21:00:00.000000+00:00"),
        )
        return RecoveryBackfillCandidates(recovery_dates=3, already_recorded=1, candidates=candidates)

    def insert_backfill(self, records: Sequence[RecordedCoverage]) -> tuple[date, ...]:
        self.inserted.extend(records)
        return (D2,)


def test_backfill_counts_a_date_recorded_meanwhile_as_already_recorded() -> None:
    store = _RacingStore()

    result = BackfillRecoveryCoverage(store).execute()
    dry_run = BackfillRecoveryCoverage(_RacingStore()).execute(dry_run=True)

    assert (result.recovery_dates, result.already_recorded) == (3, 2)
    assert result.added_synced == ()
    assert [(item.calendar_date, item.missing_endpoints) for item in result.added_partial] == [(D2, ("respiration",))]
    assert [item.synced_at_utc for item in store.inserted] == [
        "2026-10-01T21:00:00.000000+00:00",
        "2026-10-02T21:00:00.000000+00:00",
    ]
    assert (dry_run.already_recorded, len(dry_run.added_synced), len(dry_run.added_partial)) == (1, 1, 1)


class _FailingStore:
    def __init__(self, error: Exception):
        self.error = error

    def record(self, entries: Sequence[SyncCoverageEntry], *, command: str) -> None:
        raise self.error


def test_a_database_error_is_returned_not_raised() -> None:
    recorder = RecordSyncCoverage(
        _FailingStore(sqlite3.OperationalError("database is locked")), command="x", through=D5
    )

    assert recorder.activities(_range(D1, D2)) == CoverageRecordResult(0, "database is locked")
    assert recorder.recovery([_recovery_outcome(D1, "created")]) == CoverageRecordResult(0, "database is locked")
    assert recorder.activities(_range(D1, D2, page_limit=True)) == CoverageRecordResult(0)  # nothing to write


def test_other_errors_are_not_swallowed() -> None:
    recorder = RecordSyncCoverage(_FailingStore(RuntimeError("bug")), command="x", through=D5)
    with pytest.raises(RuntimeError, match="bug"):
        recorder.activities(_range(D1, D2))


# --- daily stage policy ------------------------------------------------------------------------


class _Log:
    def __init__(self) -> None:
        self.calls: list[str] = []


class _Recorder:
    def __init__(self, log: _Log, error: str | None = None):
        self.log = log
        self.error = error

    def activities(self, result: RangeIngestResult) -> CoverageRecordResult:
        self.log.calls.append("coverage:activities")
        return CoverageRecordResult(0 if self.error else 2, self.error)

    def recovery(self, outcomes: Sequence[RecoveryRangeOutcome]) -> CoverageRecordResult:
        self.log.calls.append("coverage:recovery")
        return CoverageRecordResult(0 if self.error else 2, self.error)


class _Stages:
    """Stub stages that log their order; the recommender builds an empty plan."""

    def __init__(self, log: _Log, ingest_error: Exception | None = None):
        self.log = log
        self.ingest_error = ingest_error

    def execute(self, from_date: date, to_date: date) -> RangeIngestResult:
        self.log.calls.append("activities")
        if self.ingest_error is not None:
            raise self.ingest_error
        return _range(from_date, to_date)

    def execute_range(self, from_date: date, to_date: date) -> RecoveryRangeSyncResult:
        self.log.calls.append("recovery")
        outcomes = (_recovery_outcome(from_date, "created"), _recovery_outcome(to_date, "created"))
        return RecoveryRangeSyncResult(from_date, to_date, outcomes)

    def recommend(
        self, as_of: date, avoid_muscles: Iterable[MuscleGroup] = (), requested_focus: StrengthFocus | None = None
    ) -> TrainingRecommendation:
        self.log.calls.append("recommendation")
        return build_training_recommendation(as_of, [], [])


class _Backfill:
    def execute(self, *, dry_run: bool = False) -> Any:
        from muscle50.application.backfill_activity_load_metrics import ActivityLoadBackfillResult

        return ActivityLoadBackfillResult(False, 0, 0, 0, 0, 0, 0, (), (), (), ())


class _Recommender:
    def __init__(self, stages: _Stages):
        self.stages = stages

    def execute(
        self, as_of: date, avoid_muscles: Iterable[MuscleGroup] = (), requested_focus: StrengthFocus | None = None
    ) -> TrainingRecommendation:
        return self.stages.recommend(as_of, avoid_muscles, requested_focus)


def _daily(log: _Log, recorder: _Recorder | None, ingest_error: Exception | None = None) -> DailySyncResult:
    stages = _Stages(log, ingest_error)

    def connect() -> DailyGarminConnector:
        return object()  # type: ignore[return-value]

    use_case = RunDailySync(
        connect,
        lambda connector: stages,
        _Backfill(),
        lambda connector: stages,
        _Recommender(stages),
        None,
        recorder,
    )
    return use_case.execute(D2)


def test_daily_records_coverage_after_each_sync_stage_and_before_the_recommendation() -> None:
    log = _Log()
    result = _daily(log, _Recorder(log))

    assert log.calls == ["activities", "coverage:activities", "recovery", "coverage:recovery", "recommendation"]
    assert result.ok


def test_a_coverage_write_error_is_a_stage_warning_and_the_stage_stays_ok() -> None:
    log = _Log()
    result = _daily(log, _Recorder(log, error="database is locked"))

    assert result.ok and result.recommendation is not None
    expected = "sync coverage를 기록하지 못했습니다 (동기화된 데이터는 저장됨): database is locked"
    for stage in (STAGE_ACTIVITIES, STAGE_RECOVERY):
        report = next(item for item in result.stages if item.stage == stage)
        assert report.status is StageStatus.OK
        assert report.warnings == (expected,)


def test_without_a_recorder_or_with_a_working_one_the_daily_result_is_the_same() -> None:
    without = _daily(_Log(), None)
    log = _Log()
    with_recorder = _daily(log, _Recorder(log))

    assert with_recorder == without


def test_a_failed_activity_discovery_records_no_activity_coverage() -> None:
    from muscle50.infrastructure.garmin.client import GarminConnectorError

    log = _Log()
    _daily(log, _Recorder(log), ingest_error=GarminConnectorError("list failed"))

    assert "coverage:activities" not in log.calls
    assert log.calls == ["activities", "recovery", "coverage:recovery"]
