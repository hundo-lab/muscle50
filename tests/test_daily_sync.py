from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Iterable, Mapping, Sequence
from datetime import date
from pathlib import Path
from typing import Any

import pytest

import muscle50.cli as cli
from muscle50.application.backfill_activity_load_metrics import ActivityLoadBackfillResult
from muscle50.application.daily_sync import (
    STAGE_ACTIVITIES,
    STAGE_GARMIN_LOGIN,
    STAGE_LOAD_METRICS,
    STAGE_RECOMMENDATION,
    STAGE_RECOVERY,
    DailyGarminConnector,
    DailyMode,
    DailySyncResult,
    RunDailySync,
    StageStatus,
)
from muscle50.application.ingest_activity_range import RangeIngestOutcome, RangeIngestResult
from muscle50.application.nutrition_recommendation import NutritionContext
from muscle50.application.sync_garmin_recovery import RecoveryRangeOutcome, RecoveryRangeSyncResult
from muscle50.cli import build_parser, main
from muscle50.domain.exercise_taxonomy import MuscleGroup
from muscle50.domain.nutrition_guidance import unavailable_guidance
from muscle50.domain.strength_recommendation import StrengthFocus
from muscle50.domain.training_recommendation import TrainingRecommendation, build_training_recommendation
from muscle50.infrastructure.garmin.client import (
    GarminAuthenticationError,
    GarminConnectorError,
    GarminRawActivity,
    GarminRawRecovery,
    PythonGarminConnector,
)
from muscle50.infrastructure.sqlite.analytics_reader import AnalyticsDatabaseError

TODAY = date(2026, 10, 2)
YESTERDAY = date(2026, 10, 1)


# --- stage policy with stub collaborators ---------------------------------------------


class StubIngest:
    def __init__(self, result: RangeIngestResult | None = None, error: Exception | None = None):
        self.result = result
        self.error = error
        self.calls: list[tuple[date, date]] = []

    def execute(self, from_date: date, to_date: date) -> RangeIngestResult:
        self.calls.append((from_date, to_date))
        if self.error is not None:
            raise self.error
        return self.result or _range_result(from_date, to_date)


class StubBackfill:
    def __init__(self, result: ActivityLoadBackfillResult | None = None, error: Exception | None = None):
        self.result = result or _backfill_result()
        self.error = error
        self.calls = 0

    def execute(self, *, dry_run: bool = False) -> ActivityLoadBackfillResult:
        assert dry_run is False
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.result


class StubRecovery:
    def __init__(self, result: RecoveryRangeSyncResult | None = None, error: Exception | None = None):
        self.result = result
        self.error = error
        self.calls: list[tuple[date, date]] = []

    def execute_range(self, from_date: date, to_date: date) -> RecoveryRangeSyncResult:
        self.calls.append((from_date, to_date))
        if self.error is not None:
            raise self.error
        return self.result or _recovery_result(from_date, to_date, "created")


class StubRecommender:
    def __init__(self, error: Exception | None = None):
        self.error = error
        self.calls: list[tuple[date, tuple[MuscleGroup, ...], StrengthFocus | None]] = []

    def execute(
        self,
        as_of: date,
        avoid_muscles: Iterable[MuscleGroup] = (),
        requested_focus: StrengthFocus | None = None,
    ) -> TrainingRecommendation:
        self.calls.append((as_of, tuple(avoid_muscles), requested_focus))
        if self.error is not None:
            raise self.error
        return build_training_recommendation(
            as_of, [], [], avoid_muscles=avoid_muscles, requested_focus=requested_focus
        )


class StubNutrition:
    def __init__(self) -> None:
        self.calls: list[tuple[date, TrainingRecommendation]] = []

    def execute(self, as_of: date, training: TrainingRecommendation) -> NutritionContext:
        self.calls.append((as_of, training))
        return NutritionContext(as_of, "+09:00", None, unavailable_guidance(training), "synthetic: not read")


class StubConnector:
    """Never called by the stubs; it only proves the same session reaches every Garmin stage."""


def _range_result(from_date: date, to_date: date, *outcomes: RangeIngestOutcome, **extra: Any) -> RangeIngestResult:
    return RangeIngestResult(from_date, to_date, len(outcomes), tuple(outcomes), **extra)


def _backfill_result(*, missing: tuple[str, ...] = (), unreadable: tuple[str, ...] = ()) -> ActivityLoadBackfillResult:
    return ActivityLoadBackfillResult(
        False, 3, 3 - len(missing) - len(unreadable), 0, 0, 0, 30, missing, unreadable, (), ()
    )


def _recovery_result(
    from_date: date, to_date: date, *statuses: str, aborted: str | None = None
) -> RecoveryRangeSyncResult:
    """One status per day of the two-day range; a single status applies to both days."""
    per_day = statuses * 2 if len(statuses) == 1 else statuses
    outcomes = tuple(
        RecoveryRangeOutcome(day, status, error="boom" if status == "failed" else None)  # type: ignore[arg-type]
        for day, status in zip((from_date.isoformat(), to_date.isoformat()), per_day, strict=True)
    )
    return RecoveryRangeSyncResult(from_date, to_date, outcomes, aborted)


class Harness:
    def __init__(
        self,
        *,
        login_error: Exception | None = None,
        ingest: StubIngest | None = None,
        backfill: StubBackfill | None = None,
        recovery: StubRecovery | None = None,
        recommender: StubRecommender | None = None,
        nutrition: StubNutrition | None = None,
    ):
        self.login_error = login_error
        self.connector = StubConnector()
        self.ingest = ingest or StubIngest()
        self.backfill = backfill or StubBackfill()
        self.recovery = recovery or StubRecovery()
        self.recommender = recommender or StubRecommender()
        self.nutrition = nutrition
        self.sessions: list[object] = []

    def _connect(self) -> DailyGarminConnector:
        if self.login_error is not None:
            raise self.login_error
        return self.connector  # type: ignore[return-value]

    def _ingest(self, connector: DailyGarminConnector) -> StubIngest:
        self.sessions.append(connector)
        return self.ingest

    def _recovery(self, connector: DailyGarminConnector) -> StubRecovery:
        self.sessions.append(connector)
        return self.recovery

    def run(self, mode: DailyMode = DailyMode.FULL, **kwargs: Any) -> DailySyncResult:
        use_case = RunDailySync(
            self._connect, self._ingest, self.backfill, self._recovery, self.recommender, self.nutrition
        )
        return use_case.execute(TODAY, mode, **kwargs)


def _statuses(result: DailySyncResult) -> dict[str, StageStatus]:
    return {item.stage: item.status for item in result.stages}


def _stage(result: DailySyncResult, stage: str) -> Any:
    return next(item for item in result.stages if item.stage == stage)


def test_full_run_syncs_yesterday_to_today_and_plans_today() -> None:
    harness = Harness()

    result = harness.run()

    assert result.ok and result.failed_stages == ()
    assert [item.stage for item in result.stages] == [
        STAGE_GARMIN_LOGIN,
        STAGE_ACTIVITIES,
        STAGE_LOAD_METRICS,
        STAGE_RECOVERY,
        STAGE_RECOMMENDATION,
    ]
    assert set(_statuses(result).values()) == {StageStatus.OK}
    assert harness.ingest.calls == [(YESTERDAY, TODAY)]
    assert harness.backfill.calls == 1
    assert harness.recovery.calls == [(YESTERDAY, TODAY)]
    assert harness.recommender.calls == [(TODAY, (), None)]
    assert harness.sessions == [harness.connector, harness.connector]  # one login for every Garmin stage
    assert result.sync_from == YESTERDAY
    assert result.recommendation is not None and result.recommendation.as_of == TODAY


def test_focus_and_avoid_reach_the_recommendation_unchanged() -> None:
    harness = Harness()
    avoid = [MuscleGroup.TRICEPS, MuscleGroup.CHEST]

    result = harness.run(avoid_muscles=avoid, requested_focus=StrengthFocus.SHOULDERS)

    assert harness.recommender.calls == [(TODAY, (MuscleGroup.TRICEPS, MuscleGroup.CHEST), StrengthFocus.SHOULDERS)]
    assert result.recommendation is not None
    assert result.recommendation.strength.focus == "shoulders"


def test_after_workout_imports_and_fills_metrics_only() -> None:
    harness = Harness()

    result = harness.run(DailyMode.AFTER_WORKOUT)

    assert result.ok
    assert _statuses(result) == {
        STAGE_GARMIN_LOGIN: StageStatus.OK,
        STAGE_ACTIVITIES: StageStatus.OK,
        STAGE_LOAD_METRICS: StageStatus.OK,
        STAGE_RECOVERY: StageStatus.SKIPPED,
        STAGE_RECOMMENDATION: StageStatus.SKIPPED,
    }
    assert harness.ingest.calls == [(YESTERDAY, TODAY)]
    assert harness.backfill.calls == 1
    assert harness.recovery.calls == []
    assert harness.recommender.calls == []
    assert result.recovery is None and result.recommendation is None


@pytest.mark.parametrize("mode", [DailyMode.FULL, DailyMode.AFTER_WORKOUT])
def test_login_failure_runs_nothing(mode: DailyMode) -> None:
    harness = Harness(login_error=GarminAuthenticationError("token expired"))

    result = harness.run(mode)

    assert not result.ok
    assert result.failed_stages == (STAGE_GARMIN_LOGIN,)
    assert _stage(result, STAGE_GARMIN_LOGIN).error == "token expired"
    statuses = _statuses(result)
    assert statuses[STAGE_ACTIVITIES] is StageStatus.NOT_RUN
    assert statuses[STAGE_LOAD_METRICS] is StageStatus.NOT_RUN
    expected_rest = StageStatus.NOT_RUN if mode is DailyMode.FULL else StageStatus.SKIPPED
    assert statuses[STAGE_RECOVERY] is expected_rest
    assert statuses[STAGE_RECOMMENDATION] is expected_rest
    assert harness.ingest.calls == [] and harness.backfill.calls == 0 and harness.recovery.calls == []
    assert harness.recommender.calls == []


def test_activity_discovery_failure_still_syncs_recovery_but_never_plans() -> None:
    harness = Harness(ingest=StubIngest(error=GarminConnectorError("list failed")))

    result = harness.run()

    assert result.failed_stages == (STAGE_ACTIVITIES,)
    statuses = _statuses(result)
    assert statuses[STAGE_LOAD_METRICS] is StageStatus.NOT_RUN  # nothing to backfill from
    assert statuses[STAGE_RECOVERY] is StageStatus.OK  # independent work is still preserved
    assert statuses[STAGE_RECOMMENDATION] is StageStatus.NOT_RUN
    assert harness.backfill.calls == 0 and harness.recovery.calls == [(YESTERDAY, TODAY)]
    assert harness.recommender.calls == [] and result.recommendation is None
    assert result.activities is None


def test_one_failed_activity_fails_the_stage_but_keeps_the_rest_of_the_import() -> None:
    outcomes = (
        RangeIngestOutcome("1", "strength_training", "inserted"),
        RangeIngestOutcome("2", "lap_swimming", "failed", "synthetic failure"),
    )
    harness = Harness(ingest=StubIngest(_range_result(YESTERDAY, TODAY, *outcomes)))

    result = harness.run()

    assert result.failed_stages == (STAGE_ACTIVITIES,)
    error = _stage(result, STAGE_ACTIVITIES).error
    assert error == "activity 2 (lap_swimming) failed: synthetic failure"
    assert result.activities is not None and result.activities.inserted_count == 1
    assert _statuses(result)[STAGE_LOAD_METRICS] is StageStatus.OK  # the inserted activity still gets metrics
    assert harness.backfill.calls == 1
    assert _statuses(result)[STAGE_RECOMMENDATION] is StageStatus.NOT_RUN


def test_activity_page_limit_is_a_stage_failure() -> None:
    harness = Harness(ingest=StubIngest(_range_result(YESTERDAY, TODAY, page_limit_reached=True)))

    result = harness.run()

    assert result.failed_stages == (STAGE_ACTIVITIES,)
    assert "page limit" in (_stage(result, STAGE_ACTIVITIES).error or "")


def test_load_metric_failure_withholds_the_recommendation() -> None:
    harness = Harness(backfill=StubBackfill(error=sqlite3.OperationalError("database is locked")))

    result = harness.run()

    assert result.failed_stages == (STAGE_LOAD_METRICS,)
    assert _stage(result, STAGE_LOAD_METRICS).error == "database is locked"
    assert _statuses(result)[STAGE_RECOVERY] is StageStatus.OK
    assert _statuses(result)[STAGE_RECOMMENDATION] is StageStatus.NOT_RUN
    assert harness.recommender.calls == []


def test_missing_raw_fails_load_metrics_only_for_activities_imported_now() -> None:
    imported = _range_result(YESTERDAY, TODAY, RangeIngestOutcome("new-1", "running", "inserted"))
    new_gap = Harness(ingest=StubIngest(imported), backfill=StubBackfill(_backfill_result(missing=("new-1",))))
    old_gap = Harness(ingest=StubIngest(imported), backfill=StubBackfill(_backfill_result(unreadable=("old-9",))))

    failed = new_gap.run()
    passed = old_gap.run()

    assert failed.failed_stages == (STAGE_LOAD_METRICS,)
    assert "new-1" in (_stage(failed, STAGE_LOAD_METRICS).error or "")
    assert passed.ok
    (warning,) = _stage(passed, STAGE_LOAD_METRICS).warnings
    assert "old-9" in warning and "not from this run" in warning


def test_incomplete_recovery_fails_the_stage_and_withholds_the_recommendation() -> None:
    recovery = _recovery_result(YESTERDAY, TODAY, "created", "failed")
    harness = Harness(recovery=StubRecovery(recovery))

    result = harness.run()

    assert result.failed_stages == (STAGE_RECOVERY,)
    assert _stage(result, STAGE_RECOVERY).error == "2026-10-02 failed: boom"
    assert _statuses(result)[STAGE_RECOMMENDATION] is StageStatus.NOT_RUN
    assert harness.recommender.calls == []


def test_recovery_abort_is_reported() -> None:
    recovery = _recovery_result(YESTERDAY, TODAY, "failed", "not_attempted", aborted="token expired")
    result = Harness(recovery=StubRecovery(recovery)).run()

    assert result.failed_stages == (STAGE_RECOVERY,)
    error = _stage(result, STAGE_RECOVERY).error or ""
    assert "2026-10-02 not_attempted" in error and "aborted: token expired" in error


def test_recommendation_failure_is_reported() -> None:
    harness = Harness(recommender=StubRecommender(AnalyticsDatabaseError("cannot open")))

    result = harness.run()

    assert result.failed_stages == (STAGE_RECOMMENDATION,)
    assert not result.ok and result.recommendation is None


def test_nutrition_is_attached_to_a_built_recommendation_without_becoming_a_stage() -> None:
    harness = Harness(nutrition=StubNutrition())

    result = harness.run()

    assert result.ok
    assert [item.stage for item in result.stages][-1] == STAGE_RECOMMENDATION  # no nutrition stage
    assert harness.nutrition is not None
    assert harness.nutrition.calls == [(TODAY, result.recommendation)]
    assert result.nutrition is not None and result.nutrition.unavailable_reason == "synthetic: not read"
    assert result.ok  # unreadable nutrition never fails the run


@pytest.mark.parametrize("mode", [DailyMode.FULL, DailyMode.AFTER_WORKOUT])
def test_nutrition_is_not_built_without_a_recommendation(mode: DailyMode) -> None:
    failing = Harness(
        nutrition=StubNutrition(), backfill=StubBackfill(error=sqlite3.OperationalError("database is locked"))
    )

    result = failing.run(mode)

    assert result.recommendation is None and result.nutrition is None
    assert failing.nutrition is not None and failing.nutrition.calls == []


def test_unexpected_errors_are_not_swallowed() -> None:
    # The range ingest deliberately lets local integrity errors abort; the orchestrator must too.
    harness = Harness(ingest=StubIngest(error=RuntimeError("stored strength set disagrees with RAW")))

    with pytest.raises(RuntimeError, match="disagrees"):
        harness.run()


# --- CLI end to end: real use cases, fake Garmin, temporary home ------------------------


def _summary(activity_id: int, type_key: str, local_date: str, local_time: str, **extra: Any) -> dict[str, Any]:
    return {
        "activityId": activity_id,
        "activityName": f"Synthetic Activity {activity_id}",
        "activityType": {"typeKey": type_key},
        "startTimeLocal": f"{local_date} {local_time}",
        "startTimeGMT": f"{local_date} {local_time}",
        "duration": 1800.0,
        "distance": 0.0,
        **extra,
    }


def _strength_sets() -> dict[str, Any]:
    data: object = json.loads((Path(__file__).parent / "fixtures" / "synthetic_strength_sets.json").read_text("utf-8"))
    assert isinstance(data, dict)
    return data


def _recovery_payloads(calendar_date: str) -> dict[str, Any]:
    return {
        "sleep": {"dailySleepDTO": {"calendarDate": calendar_date, "sleepTimeSeconds": 27000}},
        "daily_stats": {"calendarDate": calendar_date, "bodyBatteryHighestValue": 90, "bodyBatteryLowestValue": 25},
        "hrv": {"hrvSummary": {"calendarDate": calendar_date, "lastNightAvg": 48}},
    }


class FakeGarmin:
    """One fake session for both activity and recovery endpoints, newest activity first."""

    def __init__(
        self,
        summaries: Sequence[Mapping[str, Any]],
        *,
        fail_activity_ids: frozenset[str] = frozenset(),
        no_exercise_set_ids: frozenset[str] = frozenset(),
        recovery_warnings: tuple[str, ...] = (),
    ):
        self._summaries = list(summaries)
        self._fail_activity_ids = fail_activity_ids
        self._no_exercise_set_ids = no_exercise_set_ids
        self._recovery_warnings = recovery_warnings
        self.list_calls: list[tuple[int, int]] = []
        self.activity_calls: list[str] = []
        self.recovery_calls: list[str] = []

    def latest_summary(self) -> Mapping[str, Any] | None:
        raise AssertionError("daily must use the range ingestion, not latest")

    def list_activities(self, start: int, limit: int) -> Sequence[Mapping[str, Any]]:
        self.list_calls.append((start, limit))
        return self._summaries[start : start + limit]

    def fetch_raw_activity(self, activity_id: str, source_type_key: str) -> GarminRawActivity:
        self.activity_calls.append(activity_id)
        if activity_id in self._fail_activity_ids:
            raise GarminConnectorError("synthetic activity failure")
        # Like PythonGarminConnector: an optional endpoint failure is a warning, not an error.
        missing_sets = activity_id in self._no_exercise_set_ids
        return GarminRawActivity(
            summary={},
            activity={"activityId": int(activity_id)},
            details={"activityId": int(activity_id), "metricDescriptors": []},
            splits={"lapDTOs": []},
            exercise_sets=_strength_sets() if source_type_key == "strength_training" and not missing_sets else None,
            original_archive=b"synthetic-original-archive",
            warnings=("exercise sets 원본을 가져오지 못했습니다.",) if missing_sets else (),
        )

    def fetch_raw_recovery(self, calendar_date: str) -> GarminRawRecovery:
        self.recovery_calls.append(calendar_date)
        return GarminRawRecovery(calendar_date, _recovery_payloads(calendar_date), self._recovery_warnings)


def _account(**kwargs: Any) -> FakeGarmin:
    return FakeGarmin(
        [
            _summary(300, "running", "2026-10-02", "07:00:00", activityTrainingLoad=55.5, aerobicTrainingEffect=2.4),
            _summary(222, "strength_training", "2026-10-01", "18:00:00", activityTrainingLoad=40.0),
            _summary(100, "running", "2026-09-29", "07:00:00", activityTrainingLoad=30.0),  # before D-1: not imported
        ],
        **kwargs,
    )


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "private-muscle50"
    monkeypatch.setenv("MUSCLE50_HOME", str(root))
    monkeypatch.setattr(cli, "_today", lambda: TODAY)
    return root


def _use(monkeypatch: pytest.MonkeyPatch, garmin: FakeGarmin) -> list[Path]:
    logins: list[Path] = []

    def authenticate(auth_dir: Path, **_kwargs: Any) -> FakeGarmin:
        logins.append(auth_dir)
        return garmin

    monkeypatch.setattr(PythonGarminConnector, "authenticate", authenticate)
    return logins


def _run(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, str]:
    code = main(list(argv))
    return code, capsys.readouterr().out


def _table_counts(root: Path) -> dict[str, int]:
    with sqlite3.connect(root / "db" / "muscle50.sqlite3") as connection:
        names = [row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY 1")]
        return {name: int(connection.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]) for name in names}


def _raw_files(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted((root / "raw").rglob("*"))
        if path.is_file()
    }


def test_cli_parses_daily_options() -> None:
    args = build_parser().parse_args(["daily"])
    assert (args.command, args.as_of, args.after_workout, args.avoid, args.focus, args.json) == (
        "daily",
        None,
        False,
        [],
        None,
        False,
    )
    args = build_parser().parse_args(
        ["daily", "--date", "2026-10-02", "--focus", "pull", "--avoid", "biceps", "--avoid", "lats", "--json"]
    )
    assert (args.as_of, args.focus, args.avoid, args.json) == ("2026-10-02", "pull", ["biceps", "lats"], True)
    assert build_parser().parse_args(["daily", "--after-workout"]).after_workout is True


def test_daily_defaults_to_today_and_syncs_yesterday_to_today(
    home: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    garmin = _account()
    logins = _use(monkeypatch, garmin)

    code, output = _run(capsys, "daily", "--json")

    assert code == 0
    document = json.loads(output)
    assert (document["as_of"], document["sync_from"], document["ok"]) == ("2026-10-02", "2026-10-01", True)
    assert [stage["status"] for stage in document["stages"]] == ["ok"] * 5
    assert len(logins) == 1
    assert sorted(garmin.activity_calls) == ["222", "300"]  # 2026-09-29 is outside D-1..D
    assert garmin.recovery_calls == ["2026-10-01", "2026-10-02"]
    activities = document["activities"]
    assert (activities["from"], activities["to"], activities["inserted"]) == ("2026-10-01", "2026-10-02", 2)
    assert document["load_metrics"]["metric_rows_inserted"] == 3  # 2 for activity 300, 1 for 222
    assert [item["status"] for item in document["recovery"]["outcomes"]] == ["created", "created"]
    assert document["recommendation"]["as_of"] == "2026-10-02"
    assert _table_counts(home)["daily_recovery"] == 2


def test_daily_explicit_date_moves_both_ranges(
    home: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    garmin = _account()
    _use(monkeypatch, garmin)

    code, output = _run(capsys, "daily", "--date", "2026-10-01", "--json")

    assert code == 0
    document = json.loads(output)
    assert (document["as_of"], document["sync_from"]) == ("2026-10-01", "2026-09-30")
    assert garmin.activity_calls == ["222"]
    assert garmin.recovery_calls == ["2026-09-30", "2026-10-01"]
    assert document["recommendation"]["as_of"] == "2026-10-01"


@pytest.mark.parametrize(
    "options",
    [(), ("--focus", "pull"), ("--focus", "shoulders", "--avoid", "triceps", "--avoid", "chest"), ("--avoid", "lats")],
)
def test_daily_recommendation_equals_standalone_recommend(
    home: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], options: tuple[str, ...]
) -> None:
    _use(monkeypatch, _account())

    code, daily_json = _run(capsys, "daily", *options, "--json")
    assert code == 0
    code, standalone_json = _run(capsys, "recommend", "--date", "2026-10-02", *options, "--json")
    assert code == 0
    assert json.loads(daily_json)["recommendation"] == json.loads(standalone_json)

    code, daily_text = _run(capsys, "daily", *options)
    assert code == 0
    code, standalone_text = _run(capsys, "recommend", "--date", "2026-10-02", *options)
    assert code == 0
    assert daily_text.endswith(standalone_text)  # the unchanged recommend text, after the stage block
    stage_block = daily_text[: -len(standalone_text)]
    assert "Stages:" in stage_block and "Stored data now: activity 2026-10-02" in stage_block


def test_repeated_daily_runs_are_idempotent(
    home: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _use(monkeypatch, _account())
    code, first = _run(capsys, "daily", "--json")
    assert code == 0
    counts, raw = _table_counts(home), _raw_files(home)

    code, second = _run(capsys, "daily", "--json")

    assert code == 0
    document = json.loads(second)
    assert (document["activities"]["inserted"], document["activities"]["already_stored"]) == (0, 2)
    load = document["load_metrics"]
    assert (load["metric_rows_inserted"], load["metric_rows_updated"], load["metric_rows_unchanged"]) == (0, 0, 3)
    assert [item["status"] for item in document["recovery"]["outcomes"]] == ["unchanged", "unchanged"]
    assert _table_counts(home) == counts
    assert _raw_files(home) == raw  # no new RAW file or snapshot: the underlying semantics are untouched
    assert document["recommendation"] == json.loads(first)["recommendation"]


def test_daily_json_is_deterministic_for_identical_input(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cli, "_today", lambda: TODAY)
    outputs = []
    for name in ("first-home", "second-home"):
        monkeypatch.setenv("MUSCLE50_HOME", str(tmp_path / name))
        _use(monkeypatch, _account(recovery_warnings=("synthetic endpoint warning",)))
        code, output = _run(capsys, "daily", "--focus", "push", "--json")
        assert code == 0
        outputs.append(output)

    assert outputs[0] == outputs[1]
    assert outputs[0].isascii()


def test_after_workout_mode_imports_without_recovery_or_recommendation(
    home: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    garmin = _account()
    _use(monkeypatch, garmin)

    code, output = _run(capsys, "daily", "--after-workout")

    assert code == 0
    assert sorted(garmin.activity_calls) == ["222", "300"]
    assert garmin.recovery_calls == []
    assert "recovery: skipped" in output and "recommendation: skipped" in output
    assert "Training recommendation" not in output
    assert "The next `muscle50 daily` will count this workout." in output
    counts = _table_counts(home)
    assert counts["activities"] == 2 and counts["daily_recovery"] == 0
    assert counts["activity_metrics"] > 0

    code, output = _run(capsys, "daily", "--after-workout", "--json")
    document = json.loads(output)
    assert code == 0 and document["recommendation"] is None and document["recovery"] is None
    assert document["mode"] == "after_workout"


def test_recovery_endpoint_warnings_stay_warnings(
    home: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _use(monkeypatch, _account(recovery_warnings=("hrv endpoint unavailable",)))

    code, output = _run(capsys, "daily")

    assert code == 0
    assert "warning: 2026-10-01: hrv endpoint unavailable" in output
    assert "Training recommendation for 2026-10-02" in output


def test_activity_endpoint_warnings_are_surfaced_with_the_refresh_repair(
    home: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # A strength activity stored without its sets is skipped by later runs, so only refresh repairs it.
    _use(monkeypatch, _account(no_exercise_set_ids=frozenset({"222"})))

    code, output = _run(capsys, "daily", "--json")

    assert code == 0
    document = json.loads(output)
    activities_stage = next(stage for stage in document["stages"] if stage["stage"] == "activities")
    assert activities_stage["status"] == "ok"
    (warning,) = activities_stage["warnings"]
    assert warning.startswith("activity 222 (strength_training) imported with Garmin warning: exercise sets")
    assert warning.endswith("to re-fetch it: muscle50 garmin refresh 222")
    outcome = next(item for item in document["activities"]["outcomes"] if item["source_activity_id"] == "222")
    assert outcome["warnings"] == ["exercise sets 원본을 가져오지 못했습니다."]
    assert document["recommendation"] is not None

    _use(monkeypatch, _account(no_exercise_set_ids=frozenset({"222"})))
    code, text = _run(capsys, "daily")
    assert code == 0
    assert "muscle50 garmin refresh 222" not in text  # already stored now: the range skips it, no repeat warning


def test_failed_activity_exits_nonzero_and_builds_no_recommendation(
    home: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    garmin = _account(fail_activity_ids=frozenset({"300"}))
    _use(monkeypatch, garmin)

    code, output = _run(capsys, "daily", "--json")

    assert code == 1
    document = json.loads(output)
    assert document["ok"] is False and document["failed_stages"] == ["activities"]
    assert document["recommendation"] is None
    statuses = {stage["stage"]: stage["status"] for stage in document["stages"]}
    assert statuses == {
        "garmin_login": "ok",
        "activities": "failed",
        "load_metrics": "ok",
        "recovery": "ok",
        "recommendation": "not_run",
    }
    assert garmin.recovery_calls == ["2026-10-01", "2026-10-02"]
    assert _table_counts(home)["activities"] == 1  # activity 222 was kept

    code, text = _run(capsys, "daily")
    assert code == 1
    assert "FAILED stages: activities" in text
    assert "muscle50 recommend --date 2026-10-02" in text
    assert "Training recommendation" not in text


def test_login_failure_exits_nonzero_without_garmin_calls(
    home: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def authenticate(auth_dir: Path, **_kwargs: Any) -> FakeGarmin:
        raise GarminConnectorError("Garmin 인증에 실패했습니다.")

    monkeypatch.setattr(PythonGarminConnector, "authenticate", authenticate)

    code, output = _run(capsys, "daily", "--json")

    assert code == 1
    document = json.loads(output)
    assert document["failed_stages"] == ["garmin_login"]
    assert [stage["status"] for stage in document["stages"]][1:] == ["not_run"] * 4
    assert document["activities"] is None and document["recommendation"] is None


@pytest.mark.parametrize(
    "argv",
    [
        ("daily", "--date", "2026-13-01"),
        ("daily", "--date", "yesterday"),
        ("daily", "--after-workout", "--focus", "pull"),
        ("daily", "--after-workout", "--avoid", "biceps"),
    ],
)
def test_invalid_daily_requests_are_rejected_before_authentication(
    home: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], argv: tuple[str, ...]
) -> None:
    def authenticate(auth_dir: Path, **_kwargs: Any) -> FakeGarmin:
        raise AssertionError("must not authenticate")

    monkeypatch.setattr(PythonGarminConnector, "authenticate", authenticate)

    assert main(list(argv)) == 1
    assert "오류" in capsys.readouterr().err
    assert not home.exists()  # rejected before any directory or database is created


def test_daily_nutrition_equals_standalone_recommend(
    home: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # Synthetic food and targets in the temporary home only.
    food = ["nutrition", "food", "add", "--id", "syn-bar", "--name", "SynBar", "--per", "1", "count"]
    food += ["--kcal", "250", "--protein", "20", "--carbs", "30", "--fat", "8"]
    food += ["--source", "nutrition_label", "--accuracy", "exact"]
    for argv in (
        food,
        ["nutrition", "log", "--date", "2026-10-02", "--meal", "breakfast", "--item", "syn-bar", "1", "count"],
        ["nutrition", "target", "set", "protein", "--exact", "120"],
        ["nutrition", "target", "set", "carbs", "--range", "150", "220"],
    ):
        code, _ = _run(capsys, *argv)
        assert code == 0
    _use(monkeypatch, _account())

    code, daily_json = _run(capsys, "daily", "--json")
    assert code == 0
    code, standalone_json = _run(capsys, "recommend", "--date", "2026-10-02", "--json")
    assert code == 0
    recommendation = json.loads(daily_json)["recommendation"]
    assert recommendation == json.loads(standalone_json)
    nutrition = recommendation["nutrition"]
    assert (nutrition["availability"], nutrition["date"]) == ("evaluated", "2026-10-02")
    assert nutrition["nutrients"]["protein_g"]["status"] == "below_target"
    assert nutrition["actions"][0]["code"] == "protein_below_target"

    code, daily_text = _run(capsys, "daily")
    assert code == 0
    code, standalone_text = _run(capsys, "recommend", "--date", "2026-10-02")
    assert code == 0
    assert daily_text.endswith(standalone_text)
    assert "== Nutrition: logged intake 2026-10-02" in standalone_text
