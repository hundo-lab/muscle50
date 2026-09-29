from __future__ import annotations

import copy
import json
import sqlite3
from collections.abc import Mapping, Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

import muscle50.application.refresh_garmin_activity as refresh_module
from muscle50.application.ingest_activity import IngestGarminActivity
from muscle50.application.refresh_garmin_activity import (
    ActivityRefreshError,
    IncompleteActivityRefreshError,
    RefreshGarminActivity,
)
from muscle50.config import AppPaths
from muscle50.domain.activity_review import ActivityReviewReasonCode, derive_activity_review
from muscle50.domain.normalization import NormalizationError
from muscle50.infrastructure.garmin.client import GarminRawActivity
from muscle50.infrastructure.raw_store import RawStore
from muscle50.infrastructure.sqlite.database import ActivityRepository
from muscle50.presentation.terminal import render_refresh_result


def _strength_summary(name: str = "Synthetic Strength") -> dict[str, Any]:
    return {
        "activityId": 222,
        "activityName": name,
        "activityType": {"typeKey": "strength_training"},
        "duration": 1200,
    }


def _strength_activity(name: str = "Synthetic Strength") -> dict[str, Any]:
    summary = _strength_summary(name)
    summary["activityTypeDTO"] = summary.pop("activityType")
    return summary


def _unknown_sets(*, payload_activity_id: int = 222) -> dict[str, Any]:
    return {
        "activityId": payload_activity_id,
        "exerciseSets": [
            {
                "messageIndex": 0,
                "setType": "ACTIVE",
                "repetitionCount": 10,
                "weight": 60000,
                "exercises": [{"category": "UNKNOWN", "probability": 0}],
            },
            {"messageIndex": 1, "setType": "REST", "duration": 45},
        ],
    }


def _corrected_sets() -> dict[str, Any]:
    return {
        "activityId": 222,
        "exerciseSets": [
            {
                "messageIndex": 0,
                "setType": "ACTIVE",
                "repetitionCount": 10,
                "weight": 60000,
                "exercises": [{"category": "BENCH_PRESS", "name": "BARBELL_BENCH_PRESS"}],
            },
            {"messageIndex": 1, "setType": "REST", "duration": 45},
            {
                "messageIndex": 2,
                "setType": "ACTIVE",
                "repetitionCount": 8,
                "weight": 65000,
                "exercises": [{"category": "BENCH_PRESS", "name": "BARBELL_BENCH_PRESS"}],
            },
        ],
    }


class MutableConnector:
    def __init__(
        self,
        activity: Mapping[str, Any],
        *,
        exercise_sets: Mapping[str, Any] | None = None,
        splits: Mapping[str, Any] | None = None,
    ):
        self.activity = activity
        self.exercise_sets = exercise_sets
        self.splits = splits if splits is not None else {"lapDTOs": []}
        self.warnings: tuple[str, ...] = ()
        self.version = 1
        self.raw_calls = 0

    def latest_summary(self) -> Mapping[str, Any] | None:
        return self.activity

    def list_activities(self, start: int, limit: int) -> Sequence[Mapping[str, Any]]:
        return (self.activity,) if start == 0 and limit else ()

    def fetch_raw_activity(self, activity_id: str, source_type_key: str) -> GarminRawActivity:
        self.raw_calls += 1
        return GarminRawActivity(
            summary={},
            activity=dict(self.activity),
            details={"activityId": int(activity_id), "version": self.version},
            splits=self.splits,
            exercise_sets=self.exercise_sets,
            original_archive=f"synthetic-{self.version}".encode(),
            warnings=self.warnings,
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


def _components(paths: AppPaths, connector: MutableConnector) -> tuple[ActivityRepository, RawStore]:
    repository = ActivityRepository(paths.database_path)
    repository.migrate()
    return repository, RawStore(paths.raw_dir, paths.root, paths.tmp_dir)


def _initial_import(paths: AppPaths, connector: MutableConnector) -> ActivityRepository:
    repository, raw_store = _components(paths, connector)
    IngestGarminActivity(connector, repository, raw_store).execute(connector.activity)
    return repository


def test_strength_refresh_replaces_sets_clears_review_and_preserves_raw(paths: AppPaths) -> None:
    connector = MutableConnector(_strength_summary(), exercise_sets=_unknown_sets())
    repository = _initial_import(paths, connector)
    old_raw = (paths.raw_dir / "222" / "exercise_sets.json").read_bytes()
    before = repository.find("222")
    assert before is not None and before.strength_sets[0].source_exercise_key == "UNKNOWN"
    before_review = derive_activity_review(before)
    assert before_review.required is True
    assert before_review.reasons[0].code is ActivityReviewReasonCode.UNKNOWN_EXERCISE_CLASSIFICATION

    connector.activity = _strength_activity("Corrected Synthetic Strength")
    connector.exercise_sets = _corrected_sets()
    connector.version = 2
    result = RefreshGarminActivity(connector, repository, RawStore(paths.raw_dir, paths.root, paths.tmp_dir)).execute(
        "222"
    )

    assert result.activity.name == "Corrected Synthetic Strength"
    assert [item.source_exercise_key for item in result.activity.strength_sets] == [
        "BARBELL_BENCH_PRESS",
        None,
        "BARBELL_BENCH_PRESS",
    ]
    assert result.review.required is False
    assert result.strength_set_count == 3
    assert (paths.raw_dir / "222" / "exercise_sets.json").read_bytes() == old_raw
    snapshot_file = paths.root / next(
        item.relative_path for item in result.capture.artifacts if item.kind == "exercise_sets"
    )
    assert json.loads(snapshot_file.read_text(encoding="utf-8")) == _corrected_sets()
    with sqlite3.connect(paths.database_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM strength_sets").fetchone()[0] == 3
        assert connection.execute("SELECT COUNT(*) FROM activity_raw_captures").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM activity_refresh_state").fetchone()[0] == 1
    output = render_refresh_result(result)
    assert "Strength sets replaced: 3" in output
    assert "Review warnings remaining: none" in output


def test_repeated_identical_refresh_reuses_content_addressed_snapshot(paths: AppPaths) -> None:
    connector = MutableConnector(_strength_summary(), exercise_sets=_unknown_sets())
    repository = _initial_import(paths, connector)
    use_case = RefreshGarminActivity(connector, repository, RawStore(paths.raw_dir, paths.root, paths.tmp_dir))

    first = use_case.execute("222")
    second = use_case.execute("222")

    assert first.capture.capture_id == second.capture.capture_id
    assert second.review.required is True
    assert "Review warning: unknown_exercise_classification (sets: 1)" in render_refresh_result(second)
    assert connector.raw_calls == 3
    with sqlite3.connect(paths.database_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM activity_raw_captures").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM strength_sets").fetchone()[0] == 2


def test_changed_refresh_preserves_previous_refresh_snapshot(paths: AppPaths) -> None:
    connector = MutableConnector(_strength_summary(), exercise_sets=_corrected_sets())
    repository = _initial_import(paths, connector)
    use_case = RefreshGarminActivity(connector, repository, RawStore(paths.raw_dir, paths.root, paths.tmp_dir))
    first = use_case.execute("222")
    first_manifest = paths.root / first.capture.manifest_relative_path

    changed = copy.deepcopy(_corrected_sets())
    changed["exerciseSets"][0]["repetitionCount"] = 12
    connector.exercise_sets = changed
    connector.version = 2
    second = use_case.execute("222")

    assert second.capture.capture_id != first.capture.capture_id
    assert first_manifest.is_file()
    assert (paths.root / second.capture.manifest_relative_path).is_file()
    assert second.activity.strength_sets[0].reps == 12
    with sqlite3.connect(paths.database_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM activity_raw_captures").fetchone()[0] == 2


def test_normalization_failure_preserves_snapshot_and_previous_canonical(paths: AppPaths) -> None:
    connector = MutableConnector(_strength_summary(), exercise_sets=_corrected_sets())
    repository = _initial_import(paths, connector)
    before = repository.find("222")
    connector.exercise_sets = _unknown_sets(payload_activity_id=999)
    connector.version = 2

    with pytest.raises(NormalizationError, match="does not match"):
        RefreshGarminActivity(
            connector, repository, RawStore(paths.raw_dir, paths.root, paths.tmp_dir)
        ).execute("222")

    assert repository.find("222") == before
    with sqlite3.connect(paths.database_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM activity_raw_captures").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM activity_refresh_state").fetchone()[0] == 0


def test_persistence_failure_rolls_back_all_canonical_changes(
    paths: AppPaths, monkeypatch: pytest.MonkeyPatch
) -> None:
    connector = MutableConnector(_strength_summary(), exercise_sets=_corrected_sets())
    repository = _initial_import(paths, connector)
    before = repository.find("222")
    assert before is not None and before.metrics
    connector.activity = _strength_summary("Must Not Persist")
    connector.version = 2
    duplicate_metric = before.metrics[0]
    monkeypatch.setattr(
        refresh_module,
        "normalize_activity",
        lambda *_args: replace(before, name="Must Not Persist", metrics=(duplicate_metric, duplicate_metric)),
    )

    with pytest.raises(ActivityRefreshError, match="previous canonical data was preserved"):
        RefreshGarminActivity(
            connector, repository, RawStore(paths.raw_dir, paths.root, paths.tmp_dir)
        ).execute("222")

    assert repository.find("222") == before
    with sqlite3.connect(paths.database_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM activity_raw_captures").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM activity_refresh_state").fetchone()[0] == 0


def test_required_optional_endpoint_failure_preserves_previous_canonical(paths: AppPaths) -> None:
    connector = MutableConnector(_strength_summary(), exercise_sets=_corrected_sets())
    repository = _initial_import(paths, connector)
    before = repository.find("222")
    connector.exercise_sets = None
    connector.warnings = ("exercise sets unavailable",)
    connector.version = 2

    with pytest.raises(IncompleteActivityRefreshError, match="previous canonical data was preserved"):
        RefreshGarminActivity(
            connector, repository, RawStore(paths.raw_dir, paths.root, paths.tmp_dir)
        ).execute("222")

    assert repository.find("222") == before
    with sqlite3.connect(paths.database_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM activity_raw_captures").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM activity_refresh_state").fetchone()[0] == 0


def test_swim_refresh_replaces_laps_and_lengths(paths: AppPaths) -> None:
    fixture = json.loads((Path(__file__).parent / "fixtures" / "garmin_pool_swim.json").read_text(encoding="utf-8"))
    connector = MutableConnector({**fixture["summary"], **fixture["activity"]}, splits=fixture["splits"])
    repository = _initial_import(paths, connector)
    before = repository.find("900001")
    assert before is not None and before.swim_detail is not None
    assert len(before.swim_detail.laps) == 3

    refreshed_splits = copy.deepcopy(fixture["splits"])
    refreshed_splits["lapDTOs"] = refreshed_splits["lapDTOs"][:1]
    connector.splits = refreshed_splits
    connector.version = 2
    result = RefreshGarminActivity(
        connector, repository, RawStore(paths.raw_dir, paths.root, paths.tmp_dir)
    ).execute("900001")

    assert result.swim_lap_count == 1
    assert result.swim_length_count == len(refreshed_splits["lapDTOs"][0]["lengthDTOs"])
    with sqlite3.connect(paths.database_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM swim_laps").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM swim_lengths").fetchone()[0] == result.swim_length_count


def test_strength_refresh_reads_summary_dto_and_preserves_missing_parent_metadata(paths: AppPaths) -> None:
    initial = {
        **_strength_summary(),
        "startTimeGMT": "2026-09-24 12:13:00",
        "startTimeLocal": "2026-09-24 21:13:00",
        "timeZoneId": "Asia/Seoul",
        "elapsedDuration": 1201,
        "movingDuration": 900,
        "distance": 0,
        "calories": 334,
        "averageHR": 115,
        "maxHR": 154,
        "elevationGain": 12,
    }
    connector = MutableConnector(initial, exercise_sets=_unknown_sets())
    repository = _initial_import(paths, connector)
    connector.activity = {
        "activityId": 222,
        "activityName": "Refreshed Strength",
        "activityTypeDTO": {"typeKey": "strength_training"},
        "timeZoneUnitDTO": {"unitKey": "Asia/Seoul"},
        "summaryDTO": {
            "startTimeGMT": "2026-09-24T12:13:00.0",
            "startTimeLocal": "2026-09-24T21:13:00.0",
            "duration": 1300,
            "elapsedDuration": 1301,
            "movingDuration": 950,
            "calories": 350,
        },
    }
    connector.exercise_sets = _corrected_sets()

    result = RefreshGarminActivity(
        connector, repository, RawStore(paths.raw_dir, paths.root, paths.tmp_dir)
    ).execute("222")

    assert result.activity.name == "Refreshed Strength"
    assert result.activity.elapsed_seconds == 1301
    assert result.activity.moving_seconds == 950
    assert result.activity.calories_kcal == 350
    assert result.activity.distance_meters == 0
    assert result.activity.average_hr_bpm == 115
    assert result.activity.max_hr_bpm == 154
    assert result.activity.elevation_gain_meters == 12
    assert result.activity.timezone_name == "Asia/Seoul"
    assert len(result.activity.strength_sets) == 3


def test_swim_refresh_preserves_pool_metadata_when_detail_omits_pool_length(paths: AppPaths) -> None:
    fixture = json.loads((Path(__file__).parent / "fixtures" / "garmin_pool_swim.json").read_text(encoding="utf-8"))
    connector = MutableConnector({**fixture["summary"], **fixture["activity"]}, splits=fixture["splits"])
    repository = _initial_import(paths, connector)
    before = repository.find("900001")
    assert before is not None and before.swim_detail is not None

    connector.activity = {
        "activityId": 900001,
        "activityName": "Pool Swim",
        "activityTypeDTO": {"typeKey": "lap_swimming"},
        "summaryDTO": {"duration": 999},
    }
    connector.splits = {"activityId": 900001, "lapDTOs": fixture["splits"]["lapDTOs"][:1]}
    result = RefreshGarminActivity(
        connector, repository, RawStore(paths.raw_dir, paths.root, paths.tmp_dir)
    ).execute("900001")

    assert result.activity.swim_detail is not None
    assert result.activity.swim_detail.pool_length_meters == before.swim_detail.pool_length_meters
    assert result.activity.swim_detail.source_pool_length == before.swim_detail.source_pool_length
    assert result.activity.swim_detail.source_pool_length_unit == before.swim_detail.source_pool_length_unit
    assert result.swim_lap_count == 1
    assert "summaryDTO" in result.activity.swim_detail.source.fields_json


def test_swim_refresh_does_not_rescale_detail_summary_dto_pool_length(paths: AppPaths) -> None:
    fixture = json.loads((Path(__file__).parent / "fixtures" / "garmin_pool_swim.json").read_text(encoding="utf-8"))
    connector = MutableConnector({**fixture["summary"], **fixture["activity"]}, splits=fixture["splits"])
    repository = _initial_import(paths, connector)
    connector.activity = {
        "activityId": 900001,
        "activityName": "Pool Swim",
        "activityTypeDTO": {"typeKey": "lap_swimming"},
        "summaryDTO": {
            "poolLength": 25,
            "unitOfPoolLength": {"factor": 100, "unitKey": "meter"},
        },
    }

    result = RefreshGarminActivity(
        connector, repository, RawStore(paths.raw_dir, paths.root, paths.tmp_dir)
    ).execute("900001")

    assert result.activity.swim_detail is not None
    assert result.activity.swim_detail.pool_length_meters == 25
    assert result.activity.swim_detail.source_pool_length == 25
    assert result.activity.swim_detail.source_pool_length_unit == "meter"
