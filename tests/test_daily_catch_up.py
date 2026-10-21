"""Daily Catch-up v1 (docs/specs/daily-catch-up.md AC1-AC3): where `daily` starts, and what it says about it.

The planner and `RunDailySync` with stubs, then `muscle50 daily` end to end with the fake Garmin account of
`tests/test_daily_sync.py`. Coverage rows are seeded with an explicit `synced_at_utc`, because the rows a sync
writes carry the real wall clock (R2 compares that time with the row's date). Synthetic values only; Garmin is
never called (fake connectors) and every run uses a temporary MUSCLE50_HOME.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from datetime import UTC, date, datetime, timedelta, timezone, tzinfo
from pathlib import Path
from typing import Any

import pytest
import sync_coverage_builders as builders
from test_daily_sync import Harness

import muscle50.cli as cli
from muscle50.application.daily_catch_up import PlanDailyCatchUp
from muscle50.application.daily_sync import (
    STAGE_ACTIVITIES,
    STAGE_GARMIN_LOGIN,
    STAGE_LOAD_METRICS,
    STAGE_RECOMMENDATION,
    STAGE_RECOVERY,
    DailyMode,
    DailySyncResult,
    StageStatus,
)
from muscle50.cli import main
from muscle50.domain.sync_catch_up import (
    CATCH_UP_LIMIT_DAYS,
    CATCH_UP_LOOKBACK_DAYS,
    GARMIN_SYNC_UNCONFIRMED_MAX_DAYS,
    DailyCatchUp,
    plan_catch_up,
)
from muscle50.domain.sync_coverage import (
    CoverageKind,
    CoverageStatus,
    RecordedCoverage,
    SyncCoverageData,
    SyncCoverageEntry,
)
from muscle50.infrastructure.garmin.client import GarminConnectorError, PythonGarminConnector
from muscle50.infrastructure.sqlite.analytics_reader import AnalyticsDatabaseError, SqliteAnalyticsReader
from muscle50.infrastructure.sqlite.database import ActivityRepository

KST = timezone(timedelta(hours=9))
D = date(2026, 10, 2)  # the daily account's today (builders.DAILY_TODAY)
ACT = CoverageKind.ACTIVITIES
REC = CoverageKind.RECOVERY
SYNCED = CoverageStatus.SYNCED


def _day(offset: int) -> date:
    return D + timedelta(days=offset)


def _kst(day: date) -> tzinfo:
    return KST


def _next_morning(day: date) -> str:
    """01:00 KST on the following day (16:00 UTC on ``day``): a row written after its day ended."""
    return datetime(day.year, day.month, day.day, 16, 0, tzinfo=UTC).isoformat(timespec="microseconds")


def _same_day(day: date) -> str:
    """09:00 KST on ``day`` itself (00:00 UTC): a row written by a morning run of that day."""
    return datetime(day.year, day.month, day.day, 0, 0, tzinfo=UTC).isoformat(timespec="microseconds")


def _record(
    kind: CoverageKind, day: date, status: CoverageStatus = SYNCED, synced_at: str | None = None
) -> RecordedCoverage:
    entry = SyncCoverageEntry(
        kind,
        day,
        status,
        missing_endpoints=("hrv",) if status is CoverageStatus.PARTIAL else (),
        failed_activity_ids=("1",) if status is CoverageStatus.FAILED and kind is ACT else (),
    )
    return RecordedCoverage(entry, "daily", synced_at if synced_at is not None else _next_morning(day))


def _complete(*days: date) -> list[RecordedCoverage]:
    return [_record(kind, day) for day in days for kind in (ACT, REC)]


def _plan(records: Iterable[RecordedCoverage], *, activities_only: bool = False, as_of: date = D) -> DailyCatchUp:
    return plan_catch_up(as_of, tuple(records), activities_only=activities_only, local_timezone=_kst)


# --- the planner ------------------------------------------------------------------------------------------


def test_no_record_keeps_the_old_d_minus_1_range() -> None:
    plan = _plan([])
    assert plan == DailyCatchUp(D, _day(-1), None, None, False)
    assert not plan.reported


def test_every_day_complete_through_yesterday_keeps_d_minus_1() -> None:
    plan = _plan(_complete(*(_day(-offset) for offset in range(1, 32))))
    assert (plan.start, plan.last_synced, plan.older_unsynced, plan.reported) == (_day(-1), _day(-1), None, False)


def test_ac1_starts_the_day_after_the_last_complete_day() -> None:
    plan = _plan(_complete(_day(-5), _day(-6)))
    assert (plan.start, plan.last_synced, plan.older_unsynced, plan.reported) == (_day(-4), _day(-5), None, True)


def test_ac1_with_not_synced_dates_recorded_as_missing_rows_or_failures() -> None:
    records = [*_complete(_day(-5)), _record(ACT, _day(-3), CoverageStatus.FAILED), _record(REC, _day(-2))]
    assert _plan(records).start == _day(-4)


@pytest.mark.parametrize("status", [CoverageStatus.PARTIAL, CoverageStatus.FAILED])
def test_partial_and_failed_recovery_are_gaps(status: CoverageStatus) -> None:
    records = [*_complete(_day(-5), _day(-2)), _record(ACT, _day(-1)), _record(REC, _day(-1), status)]
    plan = _plan(records)
    assert (plan.start, plan.last_synced) == (_day(-1), _day(-2))
    records = [*_complete(_day(-5)), _record(ACT, _day(-4)), _record(REC, _day(-4), status)]
    assert _plan(records).start == _day(-4)


def test_failed_activities_are_a_gap() -> None:
    records = [*_complete(_day(-5)), _record(ACT, _day(-4), CoverageStatus.FAILED), _record(REC, _day(-4))]
    assert _plan(records).start == _day(-4)


def test_a_day_needs_both_kinds() -> None:
    records = [*_complete(_day(-5)), _record(ACT, _day(-3))]
    assert _plan(records).start == _day(-4)


def test_a_row_written_on_its_own_day_does_not_count() -> None:
    # R2: a morning `daily` on D-2 records D-2 as synced, but only up to that moment.
    records = [*_complete(_day(-3))]
    records += [_record(kind, _day(-2), synced_at=_same_day(_day(-2))) for kind in (ACT, REC)]
    plan = _plan(records)
    assert (plan.start, plan.last_synced, plan.reported) == (_day(-2), _day(-3), True)


def test_the_normal_daily_cadence_is_not_a_gap() -> None:
    # `daily` ran on the morning of D-1 (rows D-2 and D-1 written on D-1): today starts on D-1 as before.
    records = [_record(kind, day, synced_at=_same_day(_day(-1))) for day in (_day(-2), _day(-1)) for kind in (ACT, REC)]
    plan = _plan(records)
    assert (plan.start, plan.last_synced, plan.older_unsynced, plan.reported) == (_day(-1), _day(-2), None, False)


def test_the_written_date_uses_the_given_fixed_offset() -> None:
    # 16:00 UTC on D-3 is 01:00 on D-2 in KST (after D-3 ended) but still D-3 in UTC.
    after_utc = datetime(2026, 9, 29, 3, 0, tzinfo=UTC).isoformat()  # D-3 in both zones
    records = [*(_record(kind, _day(-4), synced_at=after_utc) for kind in (ACT, REC)), *_complete(_day(-3))]
    assert _plan(records).last_synced == _day(-3)
    utc = plan_catch_up(D, tuple(records), activities_only=False, local_timezone=lambda day: UTC)
    assert (utc.last_synced, utc.start) == (_day(-4), _day(-3))


def test_naive_timestamps_are_utc_and_unreadable_ones_never_count() -> None:
    naive = [_record(kind, _day(-3), synced_at=f"{_day(-3).isoformat()}T16:00:00") for kind in (ACT, REC)]
    assert _plan([*_complete(_day(-5)), *naive]).last_synced == _day(-3)
    broken = [_record(kind, _day(-3), synced_at="not a time") for kind in (ACT, REC)]
    assert _plan([*_complete(_day(-5)), *broken]).last_synced == _day(-5)
    zulu = [_record(kind, _day(-3), synced_at=f"{_day(-3).isoformat()}T16:00:00.000Z") for kind in (ACT, REC)]
    assert _plan([*_complete(_day(-5)), *zulu]).last_synced == _day(-3)


def test_ac2_caps_the_range_at_d_minus_7_and_reports_the_older_days() -> None:
    plan = _plan(_complete(_day(-13)))
    assert (plan.start, plan.last_synced, plan.older_unsynced) == (_day(-7), _day(-13), (_day(-12), _day(-8)))
    assert CATCH_UP_LIMIT_DAYS == 7


def test_the_cap_boundary() -> None:
    # Last complete D-8: start D-7, nothing older. Last complete D-9: D-8 alone is older.
    assert (_plan(_complete(_day(-8))).start, _plan(_complete(_day(-8))).older_unsynced) == (_day(-7), None)
    assert _plan(_complete(_day(-9))).older_unsynced == (_day(-8), _day(-8))


def test_without_a_complete_day_the_gap_starts_at_the_earliest_record() -> None:
    plan = _plan([_record(REC, _day(-20), CoverageStatus.PARTIAL), _record(ACT, _day(-15))])
    assert (plan.start, plan.last_synced, plan.older_unsynced) == (_day(-7), None, (_day(-20), _day(-8)))
    plan = _plan([_record(ACT, _day(-3))])
    assert (plan.start, plan.last_synced, plan.older_unsynced) == (_day(-3), None, None)


def test_only_the_lookback_window_is_read() -> None:
    # Rows older than D-31 (and rows for D itself) do not exist for the planner.
    assert _plan([*_complete(_day(-32)), *_complete(D)]) == DailyCatchUp(D, _day(-1), None, None, False)
    plan = _plan([_record(ACT, _day(-CATCH_UP_LOOKBACK_DAYS))])
    assert plan.older_unsynced == (_day(-31), _day(-8))


def test_gaps_before_the_last_complete_day_are_not_reported() -> None:
    assert _plan(_complete(_day(-10), _day(-2))) == DailyCatchUp(D, _day(-1), _day(-2), None, False)


def test_after_workout_reads_activity_coverage_only() -> None:
    records = [_record(ACT, _day(-4)), _record(REC, _day(-2))]
    plan = _plan(records, activities_only=True)
    assert plan == DailyCatchUp(D, _day(-3), _day(-4), None, True)
    assert _plan([_record(REC, _day(-4))], activities_only=True) == DailyCatchUp(D, _day(-1), None, None, True)


def test_the_planner_is_deterministic() -> None:
    records = [*_complete(_day(-13)), _record(REC, _day(-6), CoverageStatus.PARTIAL)]
    assert _plan(records) == _plan(list(reversed(records)))


class FakeCoverageSource:
    def __init__(self, records: Iterable[RecordedCoverage] = (), error: Exception | None = None) -> None:
        self.records = tuple(records)
        self.error = error
        self.calls: list[tuple[date, date]] = []

    def load_sync_coverage(self, start: date, end: date) -> SyncCoverageData:
        self.calls.append((start, end))
        if self.error is not None:
            raise self.error
        return SyncCoverageData(self.records)


def test_the_use_case_reads_d_minus_31_to_d_minus_1() -> None:
    source = FakeCoverageSource(_complete(_day(-5)))
    plan = PlanDailyCatchUp(source).execute(D, activities_only=False, local_timezone=_kst)
    assert source.calls == [(_day(-31), _day(-1))]
    assert plan.start == _day(-4)


def test_the_use_case_lets_read_errors_through() -> None:
    source = FakeCoverageSource(error=AnalyticsDatabaseError("synthetic"))
    with pytest.raises(AnalyticsDatabaseError):
        PlanDailyCatchUp(source).execute(D, activities_only=False, local_timezone=_kst)


# --- RunDailySync ranges and the sync mode ----------------------------------------------------------------

TODAY = date(2026, 10, 2)  # test_daily_sync.TODAY, the date Harness runs


def _statuses(result: DailySyncResult) -> list[tuple[str, StageStatus]]:
    return [(item.stage, item.status) for item in result.stages]


def test_a_catch_up_plan_moves_both_sync_ranges() -> None:
    harness = Harness()
    plan = DailyCatchUp(TODAY, date(2026, 9, 28), date(2026, 9, 27), None, False)
    result = harness.run(catch_up=plan)
    assert harness.ingest.calls == [(date(2026, 9, 28), TODAY)]
    assert harness.recovery.calls == [(date(2026, 9, 28), TODAY)]
    assert (result.sync_from, result.catch_up, result.ok) == (date(2026, 9, 28), plan, True)


def test_a_plan_that_keeps_d_minus_1_is_not_attached() -> None:
    plain = Harness().run()
    harness = Harness()
    result = harness.run(catch_up=DailyCatchUp(TODAY, date(2026, 10, 1), date(2026, 9, 30), None, False))
    assert harness.ingest.calls == [(date(2026, 10, 1), TODAY)]
    assert result.catch_up is None
    assert result == plain


def test_a_catch_up_plan_is_kept_when_the_login_fails() -> None:
    plan = DailyCatchUp(TODAY, date(2026, 9, 25), None, (date(2026, 9, 20), date(2026, 9, 24)), False)
    result = Harness(login_error=GarminConnectorError("no login")).run(catch_up=plan)
    assert (result.sync_from, result.catch_up) == (date(2026, 9, 25), plan)


def test_sync_mode_syncs_the_given_range_and_never_recommends() -> None:
    harness = Harness()
    result = harness.run(DailyMode.SYNC, sync_from=date(2026, 9, 20))
    assert harness.ingest.calls == harness.recovery.calls == [(date(2026, 9, 20), TODAY)]
    assert harness.recommender.calls == []
    assert _statuses(result) == [
        (STAGE_GARMIN_LOGIN, StageStatus.OK),
        (STAGE_ACTIVITIES, StageStatus.OK),
        (STAGE_LOAD_METRICS, StageStatus.OK),
        (STAGE_RECOVERY, StageStatus.OK),
        (STAGE_RECOMMENDATION, StageStatus.SKIPPED),
    ]
    assert result.ok and result.recommendation is None and result.mode is DailyMode.SYNC


def test_sync_mode_login_failure_runs_no_sync_stage() -> None:
    harness = Harness(login_error=GarminConnectorError("no login"))
    result = harness.run(DailyMode.SYNC, sync_from=date(2026, 9, 20))
    assert _statuses(result) == [
        (STAGE_GARMIN_LOGIN, StageStatus.FAILED),
        (STAGE_ACTIVITIES, StageStatus.NOT_RUN),
        (STAGE_LOAD_METRICS, StageStatus.NOT_RUN),
        (STAGE_RECOVERY, StageStatus.NOT_RUN),
        (STAGE_RECOMMENDATION, StageStatus.SKIPPED),
    ]
    assert not result.ok and harness.ingest.calls == []


def test_invalid_range_arguments_are_programming_errors() -> None:
    plan = DailyCatchUp(TODAY, date(2026, 9, 28), None, None, False)
    with pytest.raises(ValueError, match="either"):
        Harness().run(sync_from=date(2026, 9, 28), catch_up=plan)
    with pytest.raises(ValueError, match="sync mode"):
        Harness().run(DailyMode.SYNC)
    with pytest.raises(ValueError, match="after"):
        Harness().run(DailyMode.SYNC, sync_from=date(2026, 10, 3))
    with pytest.raises(ValueError, match="another day"):
        Harness().run(catch_up=DailyCatchUp(date(2026, 10, 3), date(2026, 9, 28), None, None, False))


# --- `muscle50 daily` end to end ----------------------------------------------------------------------------


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "home"
    monkeypatch.setenv("MUSCLE50_HOME", str(root))
    monkeypatch.setattr(cli, "_today", lambda: D)
    monkeypatch.setattr(cli, "_local_timezone", _kst)
    return root


def _use(monkeypatch: pytest.MonkeyPatch, garmin: builders.FakeGarmin) -> list[Path]:
    logins: list[Path] = []

    def authenticate(auth_dir: Path, **_kwargs: Any) -> builders.FakeGarmin:
        logins.append(auth_dir)
        return garmin

    monkeypatch.setattr(PythonGarminConnector, "authenticate", authenticate)
    return logins


def _run(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, str, str]:
    code = main(list(argv))
    captured = capsys.readouterr()
    return code, captured.out, captured.err


Row = tuple[CoverageKind, date, CoverageStatus, str]


def _seed(root: Path, rows: Iterable[Row]) -> None:
    """Coverage rows with an explicit write time, on a migrated database (as a past sync would leave them)."""
    database = root / "db" / "muscle50.sqlite3"
    database.parent.mkdir(parents=True, exist_ok=True)
    ActivityRepository(database).migrate()
    with sqlite3.connect(database) as connection:
        for kind, day, status, synced_at in rows:
            connection.execute(
                "INSERT INTO sync_coverage (provider, data_kind, calendar_date, status, source, command, "
                "missing_endpoints, failed_activity_ids, synced_at_utc) VALUES ('garmin', ?, ?, ?, 'sync', 'daily', "
                "?, ?, ?)",
                (
                    kind.value,
                    day.isoformat(),
                    status.value,
                    "hrv" if status is CoverageStatus.PARTIAL else None,
                    "1" if status is CoverageStatus.FAILED and kind is ACT else None,
                    synced_at,
                ),
            )


def _complete_rows(*days: date) -> list[Row]:
    return [(kind, day, SYNCED, _next_morning(day)) for day in days for kind in (ACT, REC)]


def _dates(start: date, end: date) -> list[str]:
    return [(start + timedelta(days=offset)).isoformat() for offset in range((end - start).days + 1)]


def _daily_section(text: str) -> list[str]:
    """The lines before the recommendation report (the daily section)."""
    return text.split("\n\n", 1)[0].split("\n")


def test_ac1_daily_fetches_from_the_day_after_the_last_synced_day(
    home: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _seed(home, _complete_rows(_day(-5)))
    garmin = builders.daily_account()
    logins = _use(monkeypatch, garmin)

    code, out, err = _run(capsys, "daily", "--json")

    assert code == 0, err
    assert err == "muscle50 daily 2026-10-02: syncing 2026-09-28..2026-10-02\n"
    assert len(logins) == 1
    assert garmin.recovery_calls == _dates(_day(-4), D)
    assert sorted(garmin.activity_calls) == ["100", "222", "300"]  # the 09-29 run is inside D-4..D now
    document = json.loads(out)
    assert (document["sync_from"], document["activities"]["from"], document["recovery"]["from"]) == (
        "2026-09-28",
        "2026-09-28",
        "2026-09-28",
    )
    assert list(document)[-1] == "catch_up"
    assert document["catch_up"] == {
        "from": "2026-09-28",
        "limit_days": 7,
        "last_synced": "2026-09-27",
        "older_unsynced": None,
    }
    assert out == json.dumps(document, indent=2) + "\n"


def test_ac2_daily_caps_the_range_and_names_the_older_days_text(
    home: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _seed(home, _complete_rows(_day(-13)))
    garmin = builders.daily_account()
    _use(monkeypatch, garmin)

    code, out, err = _run(capsys, "daily")

    assert code == 0, err
    assert err == "muscle50 daily 2026-10-02: syncing 2026-09-25..2026-10-02\n"
    assert garmin.recovery_calls == _dates(_day(-7), D)
    section = _daily_section(out)
    assert section[-2:] == [
        "Sync range: 2026-09-25..2026-10-02 (caught up after the last fully synced day 2026-09-19; limit 7 days)",
        "Older unsynced days: 2026-09-20..2026-09-24. Run: muscle50 garmin sync --from 2026-09-20 --to 2026-09-24 "
        "(Telegram: /sync 2026-09-20 2026-09-24)",
    ]
    assert section[:7] == [
        "muscle50 daily for 2026-10-02 (full)",
        "Stages:",
        "  garmin_login: ok",
        "  activities: ok (2026-09-25..2026-10-02: found 3, new 3, already stored 0, failed 0)",
        "  load_metrics: ok (metric rows inserted 4, updated 0, unchanged 0)",
        "  recovery: ok (2026-09-25..2026-10-02: created 8, updated 0, unchanged 0, failed 0, not attempted 0)",
        "  recommendation: ok",
    ]
    assert "Training recommendation for 2026-10-02" in out.split("\n\n", 1)[1]
    assert out.isascii()


def test_ac2_daily_json_and_determinism(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cli, "_today", lambda: D)
    monkeypatch.setattr(cli, "_local_timezone", _kst)
    outputs = []
    for name in ("first", "second"):
        root = tmp_path / name
        monkeypatch.setenv("MUSCLE50_HOME", str(root))
        _seed(root, _complete_rows(_day(-13)))
        _use(monkeypatch, builders.daily_account())
        code, out, err = _run(capsys, "daily", "--json")
        assert code == 0, err
        outputs.append(out)
    assert outputs[0] == outputs[1]
    assert outputs[0].isascii()
    document = json.loads(outputs[0])
    assert list(document)[-1] == "catch_up"
    assert document["catch_up"] == {
        "from": "2026-09-25",
        "limit_days": 7,
        "last_synced": "2026-09-19",
        "older_unsynced": {"from": "2026-09-20", "to": "2026-09-24"},
    }
    assert outputs[0] == json.dumps(document, indent=2) + "\n"


def test_an_older_gap_over_seven_days_asks_for_yes_and_no_complete_day_says_so(
    home: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _seed(home, [(REC, _day(-20), CoverageStatus.PARTIAL, _next_morning(_day(-20)))])
    _use(monkeypatch, builders.daily_account())

    code, out, err = _run(capsys, "daily")

    assert code == 0, err
    assert GARMIN_SYNC_UNCONFIRMED_MAX_DAYS == 7
    assert _daily_section(out)[-2:] == [
        "Sync range: 2026-09-25..2026-10-02 (no fully synced day in the last 31 days; limit 7 days)",
        "Older unsynced days: 2026-09-12..2026-09-24. Run: muscle50 garmin sync --from 2026-09-12 --to 2026-09-24 "
        "--yes (Telegram: /sync 2026-09-12 2026-09-24)",
    ]


def test_a_same_day_row_does_not_stop_the_catch_up(
    home: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # Morning run on D-3 (rows D-4 and D-3 written on D-3), nothing on D-2 and D-1: start on D-3.
    _seed(home, [(kind, day, SYNCED, _same_day(_day(-3))) for day in (_day(-4), _day(-3)) for kind in (ACT, REC)])
    garmin = builders.daily_account()
    _use(monkeypatch, garmin)

    code, out, err = _run(capsys, "daily", "--json")

    assert code == 0, err
    assert garmin.recovery_calls == _dates(_day(-3), D)
    assert json.loads(out)["catch_up"]["last_synced"] == "2026-09-28"


def test_the_normal_cadence_is_byte_identical_to_the_old_range(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # AC3: `daily` ran on the morning of D-1. Today's run equals a run without any catch-up planning.
    monkeypatch.setattr(cli, "_today", lambda: D)
    monkeypatch.setattr(cli, "_local_timezone", _kst)
    rows = [(kind, day, SYNCED, _same_day(_day(-1))) for day in (_day(-2), _day(-1)) for kind in (ACT, REC)]
    results = []
    for name, planned in (("planned", True), ("old", False)):
        root = tmp_path / name
        monkeypatch.setenv("MUSCLE50_HOME", str(root))
        if not planned:
            monkeypatch.setattr(cli, "_daily_catch_up", lambda *args, **kwargs: None)
        _seed(root, rows)
        garmin = builders.daily_account()
        _use(monkeypatch, garmin)
        text = _run(capsys, "daily")
        document = _run(capsys, "daily", "--json")
        results.append((text, document, garmin.recovery_calls))
    assert results[0] == results[1]
    (code, out, err), (json_code, json_out, _), recovery_calls = results[0]
    assert (code, json_code) == (0, 0)
    assert err == "muscle50 daily 2026-10-02: syncing 2026-10-01..2026-10-02\n"
    assert "Sync range:" not in out and "catch_up" not in json.loads(json_out)
    assert recovery_calls == ["2026-10-01", "2026-10-02"] * 2


def test_after_workout_catches_up_activities_only(
    home: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # Activities complete on D-4, recovery never: a full run would start earlier; after-workout starts on D-3.
    _seed(home, [(ACT, _day(-4), SYNCED, _next_morning(_day(-4)))])
    garmin = builders.daily_account()
    _use(monkeypatch, garmin)

    code, out, err = _run(capsys, "daily", "--after-workout")

    assert code == 0, err
    assert err == "muscle50 daily 2026-10-02: syncing 2026-09-29..2026-10-02\n"
    assert garmin.recovery_calls == []
    assert sorted(garmin.activity_calls) == ["100", "222", "300"]
    assert out.rstrip("\n").split("\n")[-1] == (
        "Sync range: 2026-09-29..2026-10-02 (caught up after the last day with activities synced 2026-09-28; "
        "limit 7 days)"
    )
    # The run recorded 09-29..10-02 (at the real time, after those days): the next run is back to D-1..D.
    code, out, err = _run(capsys, "daily", "--after-workout", "--json")
    assert (code, err) == (0, "muscle50 daily 2026-10-02: syncing 2026-10-01..2026-10-02\n")
    assert "catch_up" not in json.loads(out)


def test_after_workout_json_has_the_catch_up_key(
    home: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _seed(home, [(ACT, _day(-4), SYNCED, _next_morning(_day(-4)))])
    _use(monkeypatch, builders.daily_account())
    code, out, err = _run(capsys, "daily", "--after-workout", "--json")
    assert code == 0, err
    document = json.loads(out)
    assert (document["mode"], document["recovery"], list(document)[-1]) == ("after_workout", None, "catch_up")
    assert document["catch_up"] == {
        "from": "2026-09-29",
        "limit_days": 7,
        "last_synced": "2026-09-28",
        "older_unsynced": None,
    }


def test_explicit_date_is_the_base_of_the_catch_up(
    home: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _seed(home, _complete_rows(date(2026, 9, 25)))
    garmin = builders.daily_account()
    _use(monkeypatch, garmin)

    code, out, err = _run(capsys, "daily", "--date", "2026-10-01", "--json")

    assert code == 0, err
    assert err == "muscle50 daily 2026-10-01: syncing 2026-09-26..2026-10-01\n"
    assert garmin.recovery_calls == _dates(date(2026, 9, 26), date(2026, 10, 1))
    assert json.loads(out)["catch_up"]["from"] == "2026-09-26"


def test_an_unreadable_coverage_falls_back_to_d_minus_1_with_a_warning(
    home: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _seed(home, _complete_rows(_day(-13)))

    def broken(self: object, start: date, end: date) -> SyncCoverageData:
        raise AnalyticsDatabaseError("synthetic read failure")

    monkeypatch.setattr(SqliteAnalyticsReader, "load_sync_coverage", broken)
    garmin = builders.daily_account()
    _use(monkeypatch, garmin)

    code, out, err = _run(capsys, "daily", "--json")

    assert code == 0
    assert err.split("\n") == [
        "경고: sync coverage를 읽지 못해 어제(2026-10-01)부터 받습니다: synthetic read failure",
        "muscle50 daily 2026-10-02: syncing 2026-10-01..2026-10-02",
        "",
    ]
    assert garmin.recovery_calls == ["2026-10-01", "2026-10-02"]
    assert "catch_up" not in json.loads(out)


def test_a_fresh_home_keeps_the_old_range_and_output(
    home: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # AC3 (no record at all); the byte-for-byte goldens are tests/test_recommend_sync_coverage.py's daily cases.
    garmin = builders.daily_account()
    _use(monkeypatch, garmin)
    code, out, err = _run(capsys, "daily")
    assert code == 0
    assert err == "muscle50 daily 2026-10-02: syncing 2026-10-01..2026-10-02\n"
    assert "Sync range:" not in out
    assert garmin.recovery_calls == ["2026-10-01", "2026-10-02"]


def test_daily_help_describes_the_catch_up(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        main(["--help"])
    assert "from the day after the last synced day" in " ".join(capsys.readouterr().out.split())
