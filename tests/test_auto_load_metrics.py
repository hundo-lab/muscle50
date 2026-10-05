"""`garmin latest` / `garmin activities` fill activity-load metrics after ingesting (auto-load-metrics).

Real use cases and a temporary home; a fake Garmin session and synthetic RAW only.
"""

from __future__ import annotations

import hashlib
import sqlite3
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest

from muscle50.application.backfill_activity_load_metrics import (
    ActivityLoadBackfillResult,
    ActivityLoadValueReport,
    BackfillActivityLoadMetrics,
)
from muscle50.application.imported_load_metrics import (
    FillImportedLoadMetrics,
    ImportedLoadMetricsResult,
    LoadMetricCheck,
    check_imported_load_metrics,
)
from muscle50.cli import main
from muscle50.domain.activity_load import ACTIVITY_LOAD_METRIC_KEYS, ActivityLoadValueIssue
from muscle50.infrastructure.garmin.client import GarminConnectorError, GarminRawActivity, PythonGarminConnector
from muscle50.infrastructure.raw_store import RawStore, RawStoreError

LOAD_FIELDS: dict[str, Any] = {
    "activityTrainingLoad": 55.5,
    "aerobicTrainingEffect": 2.4,
    "anaerobicTrainingEffect": 0.8,
    "hrTimeInZone_1": 120.0,
    "hrTimeInZone_2": 600.0,
    "hrTimeInZone_3": 700.0,
    "hrTimeInZone_4": 300.0,
    "hrTimeInZone_5": 80.0,
    "moderateIntensityMinutes": 10,
    "vigorousIntensityMinutes": 20,
}
STDERR_FAILED = (
    "오류: 이번 실행에서 저장한 activity의 load metric을 채우지 못했습니다. "
    "저장된 activity와 RAW는 그대로 남아 있습니다.\n"
)


def _summary(activity_id: int, local_date: str, **extra: Any) -> dict[str, Any]:
    return {
        "activityId": activity_id,
        "activityName": f"Synthetic Activity {activity_id}",
        "activityType": {"typeKey": "running"},
        "startTimeLocal": f"{local_date} 07:00:00",
        "startTimeGMT": f"{local_date} 07:00:00",
        "duration": 1800.0,
        **LOAD_FIELDS,
        **extra,
    }


class FakeGarmin:
    """Activity endpoints only, newest first; never a real login."""

    def __init__(
        self,
        summaries: Sequence[Mapping[str, Any]],
        *,
        fail_activity_ids: frozenset[str] = frozenset(),
        list_error: bool = False,
    ):
        self._summaries = list(summaries)
        self._fail_activity_ids = fail_activity_ids
        self._list_error = list_error
        self.activity_calls: list[str] = []

    def latest_summary(self) -> Mapping[str, Any] | None:
        return self._summaries[0] if self._summaries else None

    def list_activities(self, start: int, limit: int) -> Sequence[Mapping[str, Any]]:
        if self._list_error:
            raise GarminConnectorError("synthetic activity list failure")
        return self._summaries[start : start + limit]

    def fetch_raw_activity(self, activity_id: str, source_type_key: str) -> GarminRawActivity:
        self.activity_calls.append(activity_id)
        if activity_id in self._fail_activity_ids:
            raise GarminConnectorError("synthetic activity failure")
        return GarminRawActivity(
            summary={},
            activity={"activityId": int(activity_id)},
            details={"activityId": int(activity_id), "metricDescriptors": []},
            splits={"lapDTOs": []},
            exercise_sets=None,
            original_archive=b"synthetic-original-archive",
            warnings=(),
        )


def _account(**kwargs: Any) -> FakeGarmin:
    return FakeGarmin(
        [
            _summary(9002, "2026-10-05"),
            _summary(9001, "2026-10-03", activityTrainingLoad=40.0),
            _summary(8001, "2026-09-20", activityTrainingLoad=30.0),
        ],
        **kwargs,
    )


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "home"
    monkeypatch.setenv("MUSCLE50_HOME", str(root))
    return root


def _use(monkeypatch: pytest.MonkeyPatch, garmin: FakeGarmin) -> None:
    monkeypatch.setattr(PythonGarminConnector, "authenticate", lambda *_args, **_kwargs: garmin)


def _run(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, str, str]:
    code = main(list(argv))
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def _summary_path(root: Path, activity_id: str) -> Path:
    return root / "raw" / "garmin" / "activities" / activity_id / "summary.json"


def _lose_summary_after_preserve(
    monkeypatch: pytest.MonkeyPatch, root: Path, activity_id: str, content: bytes | None
) -> None:
    """The real preserve, then that activity's summary.json is deleted (None) or overwritten."""
    original_preserve = RawStore.preserve

    def preserve(self: RawStore, preserved_id: str, raw: GarminRawActivity) -> Any:
        artifacts = original_preserve(self, preserved_id, raw)
        if preserved_id == activity_id:
            path = _summary_path(root, activity_id)
            if content is None:
                path.unlink()
            else:
                path.write_bytes(content)
        return artifacts

    monkeypatch.setattr(RawStore, "preserve", preserve)


def _load_rows(root: Path) -> dict[tuple[str, str], tuple[Any, ...]]:
    placeholders = ", ".join("?" for _ in ACTIVITY_LOAD_METRIC_KEYS)
    with sqlite3.connect(root / "db" / "muscle50.sqlite3") as connection:
        rows = connection.execute(
            f"""
            SELECT activity.source_activity_id, metric.metric_key, metric.numeric_value, metric.unit, metric.source_path
            FROM activity_metrics AS metric JOIN activities AS activity ON activity.id = metric.activity_id
            WHERE metric.metric_key IN ({placeholders})
            """,
            sorted(ACTIVITY_LOAD_METRIC_KEYS),
        ).fetchall()
    return {(row[0], row[1]): tuple(row[2:]) for row in rows}


def _activity_ids(root: Path) -> list[str]:
    with sqlite3.connect(root / "db" / "muscle50.sqlite3") as connection:
        return [row[0] for row in connection.execute("SELECT source_activity_id FROM activities ORDER BY 1")]


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


def _lines(*lines: str) -> str:
    return "\n".join(lines) + "\n"


LATEST_9002 = (
    "새 activity 저장 완료",
    "Garmin activity ID: 9002",
    "종류: 러닝 (running)",
    "이름: Synthetic Activity 9002",
    "시작: 2026-10-05T07:00:00",
    "시간: 00:30:00",
)
RANGE_HEADER = ("기간: 2026-10-01 ~ 2026-10-05",)


def _range(discovered: int, inserted: int, skipped: int, failed: int) -> tuple[str, ...]:
    return (
        *RANGE_HEADER,
        f"발견: {discovered}건",
        f"신규 저장: {inserted}건",
        f"이미 저장됨: {skipped}건",
        f"실패: {failed}건",
    )


ACTIVITIES = ("garmin", "activities", "--from", "2026-10-01", "--to", "2026-10-05")


# --- AC1: garmin latest -------------------------------------------------------------------


def test_latest_fills_the_new_activitys_load_metrics_and_prints_the_block(
    home: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _use(monkeypatch, _account())

    code, out, err = _run(capsys, "garmin", "latest")

    assert (code, err) == (0, "")
    assert out == _lines(*LATEST_9002, "Load metrics: metric rows inserted 10, updated 0, unchanged 0")
    rows = _load_rows(home)
    assert {key for activity_id, key in rows if activity_id == "9002"} == ACTIVITY_LOAD_METRIC_KEYS
    assert rows[("9002", "training_load")] == (55.5, "score", "activityTrainingLoad")
    assert rows[("9002", "vigorous_intensity_minutes")] == (20.0, "min", "vigorousIntensityMinutes")

    code, out, _ = _run(capsys, "garmin", "backfill-load-metrics", "--dry-run")
    assert code == 0
    assert "Metric rows inserted: 0\nMetric rows updated: 0\n" in out  # already filled: nothing left to backfill


def test_latest_rerun_reports_unchanged_only_and_writes_nothing(
    home: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _use(monkeypatch, _account())
    assert _run(capsys, "garmin", "latest")[0] == 0
    counts, raw, rows = _table_counts(home), _raw_files(home), _load_rows(home)

    code, out, err = _run(capsys, "garmin", "latest")

    assert (code, err) == (0, "")
    assert out == _lines(
        "이미 저장된 activity (변경 없음)",
        *LATEST_9002[1:],
        "Load metrics: metric rows inserted 0, updated 0, unchanged 10",
    )
    assert (_table_counts(home), _raw_files(home), _load_rows(home)) == (counts, raw, rows)


# --- AC2: garmin activities --from/--to ----------------------------------------------------


def test_activities_fills_every_new_activity_in_the_range(
    home: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    garmin = _account()
    _use(monkeypatch, garmin)

    code, out, err = _run(capsys, *ACTIVITIES)

    assert (code, err) == (0, "")
    assert out == _lines(*_range(2, 2, 0, 0), "Load metrics: metric rows inserted 20, updated 0, unchanged 0")
    assert sorted(garmin.activity_calls) == ["9001", "9002"]  # 8001 is outside the range
    rows = _load_rows(home)
    assert {activity_id for activity_id, _key in rows} == {"9001", "9002"}
    assert rows[("9001", "training_load")] == (40.0, "score", "activityTrainingLoad")


def test_activities_rerun_with_only_stored_activities_is_unchanged_only(
    home: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _use(monkeypatch, _account())
    assert _run(capsys, *ACTIVITIES)[0] == 0
    counts, raw, rows = _table_counts(home), _raw_files(home), _load_rows(home)

    code, out, err = _run(capsys, *ACTIVITIES)

    assert (code, err) == (0, "")
    assert out == _lines(*_range(2, 0, 2, 0), "Load metrics: metric rows inserted 0, updated 0, unchanged 20")
    assert (_table_counts(home), _raw_files(home), _load_rows(home)) == (counts, raw, rows)


def test_activities_over_an_empty_range_still_checks_the_stored_activities(
    home: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _use(monkeypatch, _account())
    assert _run(capsys, *ACTIVITIES)[0] == 0

    code, out, err = _run(capsys, "garmin", "activities", "--from", "2026-09-25", "--to", "2026-09-26")

    assert (code, err) == (0, "")
    assert out == _lines(
        "기간: 2026-09-25 ~ 2026-09-26",
        "발견: 0건",
        "신규 저장: 0건",
        "이미 저장됨: 0건",
        "실패: 0건",
        "Load metrics: metric rows inserted 0, updated 0, unchanged 20",
    )


# --- AC3: a new activity without a readable RAW summary -----------------------------------


def test_latest_new_activity_without_raw_summary_exits_1_and_keeps_the_activity(
    home: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _use(monkeypatch, _account())
    assert _run(capsys, "garmin", "activities", "--from", "2026-10-03", "--to", "2026-10-03")[0] == 0
    older_rows = _load_rows(home)
    _lose_summary_after_preserve(monkeypatch, home, "9002", None)

    code, out, err = _run(capsys, "garmin", "latest")

    assert code == 1
    assert out == _lines(
        *LATEST_9002,
        "Load metrics: metric rows inserted 0, updated 0, unchanged 10",
        "Load metrics failed: no readable RAW summary for activities imported in this run: 9002",
    )
    assert err == STDERR_FAILED
    assert _activity_ids(home) == ["9001", "9002"]  # the activity row stays stored
    assert sorted(path.name for path in _summary_path(home, "9002").parent.iterdir()) == [
        "activity.json",
        "details.json",
        "manifest.json",
        "original.zip",
        "splits.json",
    ]
    assert _load_rows(home) == older_rows  # no load rows for 9002; the older activity's rows untouched


@pytest.mark.parametrize("content", [None, b"{not json"], ids=["missing", "unreadable"])
def test_activities_new_activity_without_readable_raw_summary_exits_1(
    home: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    content: bytes | None,
) -> None:
    _use(monkeypatch, _account())
    _lose_summary_after_preserve(monkeypatch, home, "9002", content)

    code, out, err = _run(capsys, *ACTIVITIES)

    assert code == 1
    assert out == _lines(
        *_range(2, 2, 0, 0),
        "Load metrics: metric rows inserted 10, updated 0, unchanged 0",
        "Load metrics failed: no readable RAW summary for activities imported in this run: 9002",
    )
    assert err == STDERR_FAILED
    assert _activity_ids(home) == ["9001", "9002"]
    assert {activity_id for activity_id, _key in _load_rows(home)} == {"9001"}


# --- warnings: exit 0 ----------------------------------------------------------------------


def test_an_older_activitys_raw_gap_is_a_warning(
    home: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _use(monkeypatch, _account())
    assert _run(capsys, "garmin", "activities", "--from", "2026-09-20", "--to", "2026-09-20")[0] == 0
    _summary_path(home, "8001").unlink()

    code, out, err = _run(capsys, *ACTIVITIES)

    assert (code, err) == (0, "")
    assert out == _lines(
        *_range(2, 2, 0, 0),
        "Load metrics: metric rows inserted 20, updated 0, unchanged 0",
        "Load metrics warning: 1 previously stored activities have no readable RAW summary (not from this run): 8001",
    )


def test_a_malformed_value_in_a_new_activity_warns_and_valid_metrics_are_stored(
    home: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _use(monkeypatch, FakeGarmin([_summary(9002, "2026-10-05", aerobicTrainingEffect="2.5")]))

    code, out, err = _run(capsys, "garmin", "latest")

    assert (code, err) == (0, "")
    assert out == _lines(
        *LATEST_9002,
        "Load metrics: metric rows inserted 9, updated 0, unchanged 0",
        "Load metrics warning: malformed load-metric values in activities imported in this run: 9002",
    )
    assert {key for _activity_id, key in _load_rows(home)} == ACTIVITY_LOAD_METRIC_KEYS - {"aerobic_training_effect"}


def test_a_failed_activity_in_the_range_keeps_exit_0_and_the_load_step_still_runs(
    home: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _use(monkeypatch, _account(fail_activity_ids=frozenset({"9002"})))

    code, out, err = _run(capsys, *ACTIVITIES)

    assert (code, err) == (0, "")
    assert out == _lines(
        *_range(2, 1, 0, 1),
        "실패: Garmin activity ID 9002 (running)",
        "Load metrics: metric rows inserted 10, updated 0, unchanged 0",
    )
    assert _activity_ids(home) == ["9001"]


# --- a load-step exception: exit 1, the ingest output is kept ------------------------------


@pytest.mark.parametrize(
    ("argv", "ingest_lines", "stored"),
    [(("garmin", "latest"), LATEST_9002, ["9002"]), (ACTIVITIES, _range(2, 2, 0, 0), ["9001", "9002"])],
    ids=["latest", "activities"],
)
@pytest.mark.parametrize(
    ("error", "message"),
    [(sqlite3.OperationalError("database is locked"), "database is locked"), (RawStoreError("synthetic"), "synthetic")],
    ids=["sqlite", "raw-store"],
)
def test_a_backfill_exception_fails_the_command_after_the_ingest_output(
    home: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    argv: tuple[str, ...],
    ingest_lines: tuple[str, ...],
    stored: list[str],
    error: Exception,
    message: str,
) -> None:
    _use(monkeypatch, _account())

    def fail(self: BackfillActivityLoadMetrics, *, dry_run: bool = False) -> ActivityLoadBackfillResult:
        raise error

    monkeypatch.setattr(BackfillActivityLoadMetrics, "execute", fail)

    code, out, err = _run(capsys, *argv)

    assert code == 1
    assert out == _lines(*ingest_lines, f"Load metrics failed: {message}")
    assert err == STDERR_FAILED
    assert _activity_ids(home) == stored  # the ingest result stays stored


def test_ctrl_c_during_the_load_step_exits_130_after_the_ingest_output(
    home: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _use(monkeypatch, _account())

    def interrupt(self: BackfillActivityLoadMetrics, *, dry_run: bool = False) -> ActivityLoadBackfillResult:
        raise KeyboardInterrupt

    monkeypatch.setattr(BackfillActivityLoadMetrics, "execute", interrupt)

    code, out, err = _run(capsys, "garmin", "latest")

    assert (code, out, err) == (130, _lines(*LATEST_9002), "\n취소되었습니다.\n")


# --- AC4: ingestion failures never run the load step --------------------------------------


@pytest.fixture
def no_backfill(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(self: BackfillActivityLoadMetrics, *, dry_run: bool = False) -> ActivityLoadBackfillResult:
        pytest.fail("the load step must not run after an ingestion failure")

    monkeypatch.setattr(BackfillActivityLoadMetrics, "execute", fail)


@pytest.mark.usefixtures("home", "no_backfill")
@pytest.mark.parametrize(
    ("argv", "garmin", "stderr"),
    [
        (("garmin", "latest"), FakeGarmin([]), "오류: Garmin Connect에 activity가 없습니다.\n"),
        (
            ("garmin", "latest"),
            _account(fail_activity_ids=frozenset({"9002"})),
            "오류: synthetic activity failure\n",
        ),
        (ACTIVITIES, _account(list_error=True), "오류: synthetic activity list failure\n"),
    ],
    ids=["latest-no-activities", "latest-fetch-failure", "activities-discovery-failure"],
)
def test_ingestion_failures_skip_the_load_step_and_keep_their_output(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    argv: tuple[str, ...],
    garmin: FakeGarmin,
    stderr: str,
) -> None:
    _use(monkeypatch, garmin)

    assert _run(capsys, *argv) == (1, "", stderr)


@pytest.mark.usefixtures("home", "no_backfill")
@pytest.mark.parametrize("argv", [("garmin", "latest"), ACTIVITIES], ids=["latest", "activities"])
def test_a_login_failure_skips_the_load_step(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], argv: tuple[str, ...]
) -> None:
    def authenticate(*_args: Any, **_kwargs: Any) -> FakeGarmin:
        raise GarminConnectorError("synthetic login failure")

    monkeypatch.setattr(PythonGarminConnector, "authenticate", authenticate)

    assert _run(capsys, *argv) == (1, "", "오류: synthetic login failure\n")


# --- determinism -----------------------------------------------------------------------------


def test_output_is_deterministic_and_the_block_is_ascii(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    outputs = []
    for name in ("first-home", "second-home"):
        monkeypatch.setenv("MUSCLE50_HOME", str(tmp_path / name))
        _use(monkeypatch, _account())
        outputs.append((_run(capsys, *ACTIVITIES), _run(capsys, "garmin", "latest")))

    assert outputs[0] == outputs[1]
    for _code, out, _err in outputs[0]:
        block = [line for line in out.splitlines() if line.startswith("Load metrics")]
        assert block and all(line.isascii() for line in block)


# --- the shared rule and the use case ------------------------------------------------------


def _result(
    *,
    missing: tuple[str, ...] = (),
    unreadable: tuple[str, ...] = (),
    malformed: tuple[str, ...] = (),
) -> ActivityLoadBackfillResult:
    issue = ActivityLoadValueIssue("aerobicTrainingEffect", "aerobic_training_effect", "malformed")
    return ActivityLoadBackfillResult(
        dry_run=False,
        activities_examined=5,
        raw_summaries_found=5 - len(missing) - len(unreadable),
        activities_changed=0,
        metrics_inserted=1,
        metrics_updated=2,
        metrics_unchanged=3,
        missing_raw=missing,
        unreadable_raw=unreadable,
        malformed_values=tuple(ActivityLoadValueReport(item, issue) for item in malformed),
        skipped_values=(),
    )


def test_check_fails_on_new_gaps_only_and_reports_no_warnings_then() -> None:
    result = _result(missing=("9", "10"), unreadable=("11", "3"), malformed=("9",))

    assert check_imported_load_metrics(result, {"9", "11", "12"}) == LoadMetricCheck(
        "no readable RAW summary for activities imported in this run: 11, 9"
    )


def test_check_warns_on_older_gaps_and_new_malformed_values_in_order() -> None:
    result = _result(missing=("2",), unreadable=("1",), malformed=("7", "5", "1"))

    assert check_imported_load_metrics(result, frozenset({"5", "7"})) == LoadMetricCheck(
        None,
        (
            "2 previously stored activities have no readable RAW summary (not from this run): 1, 2",
            "malformed load-metric values in activities imported in this run: 5, 7",
        ),
    )


def test_check_ignores_malformed_values_in_older_activities() -> None:
    assert check_imported_load_metrics(_result(malformed=("1",)), frozenset()) == LoadMetricCheck(None, ())


class RecordingBackfill:
    def __init__(self, result: ActivityLoadBackfillResult | Exception):
        self._result = result
        self.calls: list[bool] = []

    def execute(self, *, dry_run: bool = False) -> ActivityLoadBackfillResult:
        self.calls.append(dry_run)
        if isinstance(self._result, Exception):
            raise self._result
        return self._result


def test_fill_writes_for_real_and_wraps_the_check() -> None:
    result = _result(missing=("4",))
    backfill = RecordingBackfill(result)

    filled = FillImportedLoadMetrics(backfill).execute(frozenset({"4"}))

    assert backfill.calls == [False]
    assert filled == ImportedLoadMetricsResult(
        result, "no readable RAW summary for activities imported in this run: 4", ()
    )
    assert not filled.ok


def test_fill_reports_a_backfill_exception_as_a_failure_without_counts() -> None:
    filled = FillImportedLoadMetrics(RecordingBackfill(sqlite3.OperationalError("database is locked"))).execute(
        frozenset()
    )

    assert filled == ImportedLoadMetricsResult(None, "database is locked", ())
    assert not filled.ok


def test_fill_does_not_swallow_unexpected_errors() -> None:
    with pytest.raises(ValueError, match="integrity"):
        FillImportedLoadMetrics(RecordingBackfill(ValueError("integrity"))).execute(frozenset())
