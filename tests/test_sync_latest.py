from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

import muscle50.application.sync_latest_garmin as sync_module
from muscle50.application.sync_latest_garmin import SyncLatestGarminActivity
from muscle50.config import AppPaths
from muscle50.domain.swim_normalization import SwimNormalizationError, normalize_garmin_swim
from muscle50.domain.swimming import NormalizedSwimActivity
from muscle50.infrastructure.garmin.client import GarminRawActivity
from muscle50.infrastructure.raw_store import RawStore
from muscle50.infrastructure.sqlite.database import ActivityRepository
from muscle50.presentation.terminal import render_sync_result

RUN_SUMMARY: dict[str, Any] = {
    "activityId": 987654321,
    "activityName": "Synthetic Morning Run",
    "activityType": {"typeKey": "running"},
    "startTimeGMT": "2026-01-02 21:00:00",
    "startTimeLocal": "2026-01-03 06:00:00",
    "duration": 1800.0,
    "movingDuration": 1740.0,
    "distance": 5000.0,
    "calories": 321.0,
    "averageHR": 145.0,
    "maxHR": 171.0,
}


def _synthetic_strength_sets() -> dict[str, Any]:
    path = Path(__file__).parent / "fixtures" / "synthetic_strength_sets.json"
    data: object = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def _synthetic_pool_swim() -> dict[str, Any]:
    path = Path(__file__).parent / "fixtures" / "garmin_pool_swim.json"
    data: object = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


class FakeConnector:
    def __init__(
        self,
        summary: Mapping[str, Any],
        *,
        activity: Mapping[str, Any] | None = None,
        splits: Mapping[str, Any] | None = None,
        include_splits: bool = True,
        exercise_sets: Mapping[str, Any] | None = None,
    ):
        self.summary = summary
        self.activity = activity if activity is not None else summary
        self.splits = (splits if splits is not None else {"lapDTOs": []}) if include_splits else None
        self.exercise_sets = exercise_sets
        self.latest_calls = 0
        self.raw_calls = 0

    def latest_summary(self) -> Mapping[str, Any]:
        self.latest_calls += 1
        return self.summary

    def fetch_raw_activity(self, activity_id: str, source_type_key: str) -> GarminRawActivity:
        self.raw_calls += 1
        assert activity_id == str(self.summary["activityId"])
        return GarminRawActivity(
            summary={},
            activity=dict(self.activity),
            details={"activityId": int(activity_id), "metricDescriptors": []},
            splits=self.splits,
            exercise_sets=self.exercise_sets,
            original_archive=b"synthetic-original-archive",
            warnings=(),
        )


@pytest.fixture
def paths(tmp_path: Path) -> AppPaths:
    root = tmp_path / "private-muscle50"
    result = AppPaths(
        root=root,
        auth_dir=root / "auth" / "garmin",
        raw_dir=root / "raw" / "garmin" / "activities",
        database_path=root / "db" / "muscle50.sqlite3",
        tmp_dir=root / "tmp",
    )
    result.ensure_directories()
    return result


def _use_case(paths: AppPaths, connector: FakeConnector) -> SyncLatestGarminActivity:
    repository = ActivityRepository(paths.database_path)
    repository.migrate()
    return SyncLatestGarminActivity(
        connector,
        repository,
        RawStore(paths.raw_dir, paths.root, paths.tmp_dir),
    )


def test_first_sync_preserves_raw_and_normalized_data(paths: AppPaths) -> None:
    connector = FakeConnector(RUN_SUMMARY)
    result = _use_case(paths, connector).execute()

    assert result.created is True
    assert result.activity.source_activity_id == "987654321"
    assert result.activity.canonical_type.value == "running"
    assert result.activity.started_at_utc == "2026-01-02T21:00:00+00:00"
    assert result.activity.started_at_local == "2026-01-03T06:00:00"
    activity_dir = paths.raw_dir / "987654321"
    assert json.loads((activity_dir / "summary.json").read_text(encoding="utf-8")) == RUN_SUMMARY
    assert (activity_dir / "activity.json").is_file()
    assert (activity_dir / "details.json").is_file()
    assert (activity_dir / "splits.json").is_file()
    assert (activity_dir / "original.zip").read_bytes() == b"synthetic-original-archive"

    with sqlite3.connect(paths.database_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM activities").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM raw_artifacts").fetchone()[0] == 5
        correction_columns = {row[1] for row in connection.execute("PRAGMA table_info(activity_corrections)")}
        assert {"field_key", "revision", "corrected_value_json"} <= correction_columns

    output = render_sync_result(result)
    assert "새 activity 저장 완료" in output
    assert "Garmin activity ID: 987654321" in output
    assert "종류: 러닝 (running)" in output
    assert "평균 페이스: 5:48 /km" in output


def test_duplicate_sync_does_not_refetch_or_duplicate(paths: AppPaths) -> None:
    connector = FakeConnector(RUN_SUMMARY)
    first = _use_case(paths, connector).execute()
    before = (paths.raw_dir / "987654321" / "activity.json").read_bytes()
    second = _use_case(paths, connector).execute()

    assert first.created is True
    assert second.created is False
    assert connector.latest_calls == 2
    assert connector.raw_calls == 1
    assert (paths.raw_dir / "987654321" / "activity.json").read_bytes() == before
    with sqlite3.connect(paths.database_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM activities").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM raw_artifacts").fetchone()[0] == 5
    assert "이미 저장된 activity (변경 없음)" in render_sync_result(second)


def test_pool_swim_sync_normalizes_persists_and_renders_detail(
    paths: AppPaths,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _synthetic_pool_swim()
    calls: list[str] = []

    def tracking_normalizer(
        summary: Mapping[str, Any],
        activity: Mapping[str, Any],
        splits: Mapping[str, Any] | None,
    ) -> NormalizedSwimActivity:
        calls.append(str(summary["activityId"]))
        return normalize_garmin_swim(summary, activity, splits)

    monkeypatch.setattr(sync_module, "normalize_garmin_swim", tracking_normalizer)
    connector = FakeConnector(
        payload["summary"],
        activity=payload["activity"],
        splits=payload["splits"],
    )
    use_case = _use_case(paths, connector)

    first = use_case.execute()
    second = use_case.execute()

    assert calls == ["900001"]
    assert first.created is True
    assert second.created is False
    assert connector.raw_calls == 1
    activity_dir = paths.raw_dir / "900001"
    assert (activity_dir / "summary.json").is_file()
    assert (activity_dir / "activity.json").is_file()
    assert (activity_dir / "details.json").is_file()
    assert (activity_dir / "splits.json").is_file()
    assert first.activity.swim_detail is not None
    assert second.activity.swim_detail == first.activity.swim_detail
    assert [lap.source_lap_index for lap in first.activity.swim_detail.laps] == [7, 11, 15]
    assert [
        length.source_message_index
        for lap in first.activity.swim_detail.laps
        for length in lap.lengths
    ] == [101, 102, 103, 104, 105]

    with sqlite3.connect(paths.database_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM swim_activities").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM swim_laps").fetchone()[0] == 3
        assert connection.execute("SELECT COUNT(*) FROM swim_lengths").fetchone()[0] == 5
        assert connection.execute(
            """
            SELECT COUNT(DISTINCT swim_laps.activity_id)
            FROM swim_lengths
            JOIN swim_laps ON swim_laps.id = swim_lengths.swim_lap_id
            JOIN activities ON activities.id = swim_laps.activity_id
            WHERE activities.source_activity_id = '900001'
            """
        ).fetchone()[0] == 1
        idle = connection.execute(
            """
            SELECT swim_lengths.sequence_in_lap, swim_lengths.length_type,
                   swim_lengths.stroke_type, swim_lengths.garmin_distance_meters,
                   swim_lengths.swolf, swim_lengths.average_hr_bpm,
                   swim_laps.sequence
            FROM swim_lengths
            JOIN swim_laps ON swim_laps.id = swim_lengths.swim_lap_id
            WHERE swim_lengths.source_message_index = 103
            """
        ).fetchone()
        assert idle == (2, "idle", None, None, None, None, 0)

    output = render_sync_result(second)
    assert "Swim" in output
    assert "Distance: 150 m" in output
    assert "Laps: 3" in output
    assert "Lengths: 5" in output
    assert "Average pace: 2:04 /100m" in output


@pytest.mark.parametrize(
    "source_type_key",
    ["running", "strength_training", "open_water_swimming"],
)
def test_non_pool_activity_does_not_call_swim_normalizer(
    paths: AppPaths,
    monkeypatch: pytest.MonkeyPatch,
    source_type_key: str,
) -> None:
    monkeypatch.setattr(
        sync_module,
        "normalize_garmin_swim",
        lambda *_args: pytest.fail("swim normalizer must not be called"),
    )
    summary = {
        "activityId": {"running": 710, "strength_training": 711, "open_water_swimming": 712}[source_type_key],
        "activityType": {"typeKey": source_type_key},
    }

    result = _use_case(paths, FakeConnector(summary)).execute()

    assert result.activity.swim_detail is None
    with sqlite3.connect(paths.database_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM swim_activities").fetchone()[0] == 0


def test_pool_swim_with_missing_splits_is_saved_without_inventing_laps(paths: AppPaths) -> None:
    summary = {
        "activityId": 713,
        "activityType": {"typeKey": "lap_swimming"},
        "distance": 500,
    }

    result = _use_case(paths, FakeConnector(summary, include_splits=False)).execute()

    assert result.activity.swim_detail is not None
    assert result.activity.swim_detail.splits_available is False
    assert result.activity.swim_detail.laps == ()
    with sqlite3.connect(paths.database_path) as connection:
        assert connection.execute("SELECT splits_available FROM swim_activities").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM swim_laps").fetchone()[0] == 0


def test_malformed_pool_swim_hierarchy_is_a_normalization_error(paths: AppPaths) -> None:
    summary = {"activityId": 714, "activityType": {"typeKey": "lap_swimming"}}
    connector = FakeConnector(summary, splits={"activityId": 714, "lapDTOs": {"invalid": True}})

    with pytest.raises(SwimNormalizationError, match="splits.lapDTOs must be an array"):
        _use_case(paths, connector).execute()

    assert (paths.raw_dir / "714" / "splits.json").is_file()
    with sqlite3.connect(paths.database_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM activities").fetchone()[0] == 0


def test_existing_pool_swim_backfills_detail_from_local_raw(paths: AppPaths) -> None:
    payload = _synthetic_pool_swim()
    connector = FakeConnector(
        payload["summary"],
        activity=payload["activity"],
        splits=payload["splits"],
    )
    use_case = _use_case(paths, connector)
    use_case.execute()
    with sqlite3.connect(paths.database_path) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("DELETE FROM swim_activities")

    result = _use_case(paths, connector).execute()

    assert result.created is False
    assert result.activity.swim_detail is not None
    assert len(result.activity.swim_detail.laps) == 3
    assert connector.raw_calls == 1
    with sqlite3.connect(paths.database_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM swim_laps").fetchone()[0] == 3
        assert connection.execute("SELECT COUNT(*) FROM swim_lengths").fetchone()[0] == 5


@pytest.mark.parametrize(
    ("summary", "exercise_sets", "expected_lines"),
    [
        (
            {
                "activityId": 111,
                "activityName": "Synthetic Pool Session",
                "activityType": {"typeKey": "lap_swimming"},
                "duration": 1500,
                "distance": 1000,
                "poolLength": 25,
                "poolLengthUnit": {"unitKey": "meter"},
                "lapCount": 40,
                "avgSwolf": 38,
            },
            None,
            ("종류: 수영", "풀 길이: 25 m", "랩: 40", "평균 SWOLF: 38"),
        ),
        (
            {
                "activityId": 222,
                "activityName": "Synthetic Strength Session",
                "activityType": {"typeKey": "strength_training"},
                "duration": 2400,
                "calories": 250,
            },
            _synthetic_strength_sets(),
            (
                "종류: 웨이트",
                "Barbell Bench Press",
                "  60 kg × 10",
                "  65 kg × 8",
                "Seated Cable Row",
                "  50 kg × 12",
                "총 3세트 / 30회",
                "휴식 구간: 1개 (운동 세트/반복 합계 제외)",
            ),
        ),
    ],
)
def test_sport_specific_summaries(
    paths: AppPaths,
    summary: Mapping[str, Any],
    exercise_sets: Mapping[str, Any] | None,
    expected_lines: tuple[str, ...],
) -> None:
    result = _use_case(paths, FakeConnector(summary, exercise_sets=exercise_sets)).execute()
    output = render_sync_result(result)
    assert all(expected in output for expected in expected_lines)


def test_unknown_pool_length_unit_is_not_reported_as_meters(paths: AppPaths) -> None:
    summary = {
        "activityId": 333,
        "activityType": {"typeKey": "lap_swimming"},
        "poolLength": 25,
        "poolLengthUnit": {"unitKey": "unrecognized"},
    }

    output = render_sync_result(_use_case(paths, FakeConnector(summary)).execute())

    assert "풀 길이: 25" in output
    assert "풀 길이: 25 m" not in output


def test_yard_pool_length_is_normalized_to_meters(paths: AppPaths) -> None:
    summary = {
        "activityId": 444,
        "activityType": {"typeKey": "lap_swimming"},
        "poolLength": 25,
        "poolLengthUnit": {"unitKey": "yard"},
    }

    result = _use_case(paths, FakeConnector(summary)).execute()
    pool_length = next(metric for metric in result.activity.metrics if metric.key == "pool_length")

    assert pool_length.value == pytest.approx(22.86)
    assert pool_length.unit == "m"


def test_strength_sets_are_stored_once_and_loaded_on_duplicate_sync(paths: AppPaths) -> None:
    summary = {
        "activityId": 222,
        "activityName": "Synthetic Strength Session",
        "activityType": {"typeKey": "strength_training"},
    }
    connector = FakeConnector(summary, exercise_sets=_synthetic_strength_sets())

    first = _use_case(paths, connector).execute()
    second = _use_case(paths, connector).execute()

    assert first.created is True
    assert second.created is False
    assert len(first.activity.strength_sets) == 5
    assert len(second.activity.strength_sets) == 5
    assert connector.raw_calls == 1
    with sqlite3.connect(paths.database_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM strength_sets").fetchone()[0] == 5
        active_count, active_reps = connection.execute(
            """
            SELECT COUNT(*), SUM(reps)
            FROM strength_sets
            WHERE set_type = 'ACTIVE'
            """
        ).fetchone()
        assert (active_count, active_reps) == (3, 30)
        first_row = connection.execute(
            """
            SELECT sequence, source_message_index, source_exercise_category,
                   source_exercise_name, source_exercise_key, display_exercise_name,
                   set_type, reps, source_weight, source_weight_unit,
                   normalized_weight_kg, duration_seconds, started_at, workout_step_index
            FROM strength_sets
            WHERE sequence = 1
            """
        ).fetchone()
        assert first_row == (
            1,
            0,
            "BENCH_PRESS",
            "BARBELL_BENCH_PRESS",
            "BARBELL_BENCH_PRESS",
            "Barbell Bench Press",
            "ACTIVE",
            10,
            60000,
            "g",
            60,
            35.5,
            "2026-01-03T06:10:00.0",
            1,
        )
        rest_row = connection.execute(
            "SELECT set_type, reps, source_weight, normalized_weight_kg FROM strength_sets WHERE sequence = 2"
        ).fetchone()
        assert rest_row == ("REST", None, None, None)


def test_existing_strength_activity_backfills_sets_from_local_raw(paths: AppPaths) -> None:
    summary = {
        "activityId": 222,
        "activityName": "Synthetic Strength Session",
        "activityType": {"typeKey": "strength_training"},
    }
    connector = FakeConnector(summary, exercise_sets=_synthetic_strength_sets())
    use_case = _use_case(paths, connector)
    use_case.execute()
    with sqlite3.connect(paths.database_path) as connection:
        connection.execute("DELETE FROM strength_sets")
        connection.execute("UPDATE activities SET normalizer_version = 1")
        connection.execute("UPDATE activity_metrics SET numeric_value = 4 WHERE metric_key = 'set_count'")
        connection.execute("UPDATE activity_metrics SET numeric_value = 129 WHERE metric_key = 'rep_count'")

    result = _use_case(paths, connector).execute()

    assert result.created is False
    assert len(result.activity.strength_sets) == 5
    assert result.activity.normalizer_version == 2
    metrics = {metric.key: metric.value for metric in result.activity.metrics}
    assert metrics["set_count"] == 3
    assert metrics["rep_count"] == 30
    assert connector.raw_calls == 1
    with sqlite3.connect(paths.database_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM strength_sets").fetchone()[0] == 5
