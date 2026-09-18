from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping, Sequence
from datetime import date
from pathlib import Path
from typing import Any

import pytest

import muscle50.application.ingest_activity_range as ingest_activity_range
from muscle50.application.ingest_activity_range import IngestGarminActivityRange, InvalidDateRangeError
from muscle50.config import AppPaths
from muscle50.infrastructure.garmin.client import GarminConnectorError, GarminRawActivity
from muscle50.infrastructure.raw_store import RawStore
from muscle50.infrastructure.sqlite.database import ActivityRepository


def _summary(
    activity_id: int,
    type_key: str,
    local_date: str,
    *,
    local_time: str = "08:00:00",
    gmt_date: str | None = None,
    **extra: Any,
) -> dict[str, Any]:
    gmt_date = gmt_date or local_date
    return {
        "activityId": activity_id,
        "activityName": f"Synthetic Activity {activity_id}",
        "activityType": {"typeKey": type_key},
        "startTimeLocal": f"{local_date} {local_time}",
        "startTimeGMT": f"{gmt_date} {local_time}",
        "duration": 1800.0,
        "distance": 3000.0,
        **extra,
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


class FakeRangeConnector:
    """Fake Garmin adapter that pages a fixed, newest-first activity list like Garmin does."""

    def __init__(
        self,
        summaries: Sequence[Mapping[str, Any]],
        *,
        activities_by_id: Mapping[str, Mapping[str, Any]] | None = None,
        splits_by_id: Mapping[str, Mapping[str, Any]] | None = None,
        exercise_sets_by_id: Mapping[str, Mapping[str, Any]] | None = None,
        fail_ids: frozenset[str] = frozenset(),
        splits_warning_ids: frozenset[str] = frozenset(),
    ):
        self._summaries = list(summaries)
        self._activities_by_id = activities_by_id or {}
        self._splits_by_id = splits_by_id or {}
        self._exercise_sets_by_id = exercise_sets_by_id or {}
        self._fail_ids = fail_ids
        self._splits_warning_ids = splits_warning_ids
        self.list_calls: list[tuple[int, int]] = []
        self.raw_calls: list[str] = []

    def latest_summary(self) -> Mapping[str, Any] | None:
        raise NotImplementedError("range ingestion must not call latest_summary")

    def list_activities(self, start: int, limit: int) -> tuple[Mapping[str, Any], ...]:
        self.list_calls.append((start, limit))
        return tuple(self._summaries[start : start + limit])

    def fetch_raw_activity(self, activity_id: str, source_type_key: str) -> GarminRawActivity:
        self.raw_calls.append(activity_id)
        if activity_id in self._fail_ids:
            raise GarminConnectorError("synthetic failure")
        activity = self._activities_by_id.get(activity_id, {"activityId": int(activity_id)})
        if activity_id in self._splits_warning_ids:
            splits: Mapping[str, Any] | None = None
            warnings: tuple[str, ...] = ("splits 원본을 가져오지 못했습니다.",)
        else:
            splits = self._splits_by_id.get(activity_id, {"lapDTOs": []})
            warnings = ()
        return GarminRawActivity(
            summary={},
            activity=dict(activity),
            details={"activityId": int(activity_id), "metricDescriptors": []},
            splits=splits,
            exercise_sets=self._exercise_sets_by_id.get(activity_id),
            original_archive=b"synthetic-original-archive",
            warnings=warnings,
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


def _use_case(paths: AppPaths, connector: FakeRangeConnector) -> IngestGarminActivityRange:
    repository = ActivityRepository(paths.database_path)
    repository.migrate()
    return IngestGarminActivityRange(connector, repository, RawStore(paths.raw_dir, paths.root, paths.tmp_dir))


def _activity_count(paths: AppPaths) -> int:
    with sqlite3.connect(paths.database_path) as connection:
        return int(connection.execute("SELECT COUNT(*) FROM activities").fetchone()[0])


def test_empty_range_returns_zero_results(paths: AppPaths) -> None:
    connector = FakeRangeConnector([])
    result = _use_case(paths, connector).execute(date(2026, 1, 1), date(2026, 1, 31))

    assert result.discovered_count == 0
    assert result.outcomes == ()
    assert result.inserted_count == 0
    assert connector.list_calls == [(0, 20)]


def test_single_activity_in_range_is_ingested(paths: AppPaths) -> None:
    connector = FakeRangeConnector([_summary(1, "running", "2026-01-15")])
    result = _use_case(paths, connector).execute(date(2026, 1, 1), date(2026, 1, 31))

    assert result.discovered_count == 1
    assert result.inserted_count == 1
    assert result.outcomes[0].status == "inserted"
    assert result.outcomes[0].source_activity_id == "1"
    assert _activity_count(paths) == 1


def test_multiple_activities_are_all_ingested_in_deterministic_order(paths: AppPaths) -> None:
    activities = [
        _summary(3, "running", "2026-01-20"),
        _summary(2, "cycling", "2026-01-10"),
        _summary(1, "walking", "2026-01-05"),
    ]
    connector = FakeRangeConnector(activities)
    result = _use_case(paths, connector).execute(date(2026, 1, 1), date(2026, 1, 31))

    assert [outcome.source_activity_id for outcome in result.outcomes] == ["1", "2", "3"]
    assert all(outcome.status == "inserted" for outcome in result.outcomes)


def test_pagination_walks_multiple_pages_and_stops_once_range_is_covered(paths: AppPaths) -> None:
    in_range = [_summary(i, "running", f"2026-01-{((i - 1) % 28) + 1:02d}") for i in range(1, 26)]
    older = _summary(999, "running", "2025-12-01")
    connector = FakeRangeConnector([*in_range, older])
    result = _use_case(paths, connector).execute(date(2026, 1, 1), date(2026, 1, 31))

    assert result.discovered_count == 25
    assert "999" not in [o.source_activity_id for o in result.outcomes]
    assert connector.list_calls == [(0, 20), (20, 20)]
    assert _activity_count(paths) == 25


def test_range_boundary_stops_pagination_once_range_is_covered(paths: AppPaths) -> None:
    in_range = [_summary(i, "running", "2026-01-15") for i in range(1, 21)]
    also_in_range = _summary(21, "running", "2026-01-10")
    older = _summary(999, "running", "2025-12-01")
    connector = FakeRangeConnector([*in_range, also_in_range, older])
    result = _use_case(paths, connector).execute(date(2026, 1, 1), date(2026, 1, 31))

    ids = {o.source_activity_id for o in result.outcomes}
    assert result.discovered_count == 21
    assert "21" in ids  # same page as the older activity; must still be captured
    assert "999" not in ids
    assert connector.list_calls == [(0, 20), (20, 20)]


def test_boundary_dates_are_inclusive_and_local_date_governs(paths: AppPaths) -> None:
    on_from = _summary(1, "running", "2026-01-01")
    on_to = _summary(2, "running", "2026-01-31")
    straddling_midnight = _summary(3, "running", "2026-01-01", local_time="00:30:00", gmt_date="2025-12-31")
    connector = FakeRangeConnector([on_from, on_to, straddling_midnight])
    result = _use_case(paths, connector).execute(date(2026, 1, 1), date(2026, 1, 31))

    ids = {o.source_activity_id for o in result.outcomes}
    assert ids == {"1", "2", "3"}


def test_duplicate_activity_across_pages_is_ingested_once(paths: AppPaths) -> None:
    page0 = [_summary(i, "running", "2026-01-15") for i in range(1, 21)]
    page1 = [_summary(20, "running", "2026-01-15"), _summary(21, "running", "2026-01-14")]
    connector = FakeRangeConnector([*page0, *page1])
    result = _use_case(paths, connector).execute(date(2026, 1, 1), date(2026, 1, 31))

    assert result.discovered_count == 21
    assert connector.raw_calls.count("20") == 1
    assert _activity_count(paths) == 21


def test_repeated_range_ingestion_is_idempotent(paths: AppPaths) -> None:
    activities = [_summary(i, "running", "2026-01-10") for i in range(1, 4)]
    connector = FakeRangeConnector(activities)
    use_case = _use_case(paths, connector)

    first = use_case.execute(date(2026, 1, 1), date(2026, 1, 31))
    raw_calls_after_first = len(connector.raw_calls)
    second = use_case.execute(date(2026, 1, 1), date(2026, 1, 31))

    assert first.inserted_count == 3
    assert second.inserted_count == 0
    assert second.skipped_count == 3
    assert len(connector.raw_calls) == raw_calls_after_first
    assert _activity_count(paths) == 3


def test_mixed_activity_types_are_all_ingested(paths: AppPaths) -> None:
    activities = [
        _summary(1, "running", "2026-01-05"),
        _summary(2, "open_water_swimming", "2026-01-06"),
        _summary(4, "road_biking", "2026-01-08"),
        _summary(5, "walking", "2026-01-09"),
    ]
    connector = FakeRangeConnector(activities)
    result = _use_case(paths, connector).execute(date(2026, 1, 1), date(2026, 1, 31))

    types = {o.source_activity_id: o.source_type_key for o in result.outcomes}
    assert types == {
        "1": "running",
        "2": "open_water_swimming",
        "4": "road_biking",
        "5": "walking",
    }
    assert all(o.status == "inserted" for o in result.outcomes)


def test_unknown_activity_type_does_not_crash_ingestion(paths: AppPaths) -> None:
    connector = FakeRangeConnector([_summary(1, "kayaking_v2", "2026-01-05")])
    result = _use_case(paths, connector).execute(date(2026, 1, 1), date(2026, 1, 31))

    assert result.outcomes[0].status == "inserted"
    with sqlite3.connect(paths.database_path) as connection:
        row = connection.execute("SELECT source_type_key, canonical_type FROM activities").fetchone()
    assert row == ("kayaking_v2", "other")


def test_strength_activity_uses_existing_strength_normalization_and_persistence(paths: AppPaths) -> None:
    exercise_sets = _synthetic_strength_sets()
    summary = _summary(222, "strength_training", "2026-01-05")
    connector = FakeRangeConnector([summary], exercise_sets_by_id={"222": exercise_sets})
    result = _use_case(paths, connector).execute(date(2026, 1, 1), date(2026, 1, 31))

    assert result.outcomes[0].status == "inserted"
    with sqlite3.connect(paths.database_path) as db:
        assert db.execute("SELECT COUNT(*) FROM strength_sets").fetchone()[0] == 5
        active_count, active_reps = db.execute(
            "SELECT COUNT(*), SUM(reps) FROM strength_sets WHERE set_type = 'ACTIVE'"
        ).fetchone()
    assert (active_count, active_reps) == (3, 30)


def test_swim_activity_uses_existing_swim_normalization_and_persistence(paths: AppPaths) -> None:
    payload = _synthetic_pool_swim()
    summary = {**payload["summary"], "startTimeLocal": "2026-01-06 08:00:00", "startTimeGMT": "2026-01-06 08:00:00"}
    connector = FakeRangeConnector(
        [summary],
        activities_by_id={"900001": payload["activity"]},
        splits_by_id={"900001": payload["splits"]},
    )
    result = _use_case(paths, connector).execute(date(2026, 1, 1), date(2026, 1, 31))

    assert result.outcomes[0].status == "inserted"
    with sqlite3.connect(paths.database_path) as db:
        assert db.execute("SELECT COUNT(*) FROM swim_activities").fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM swim_laps").fetchone()[0] == 3
        assert db.execute("SELECT COUNT(*) FROM swim_lengths").fetchone()[0] == 5


def test_normal_activity_without_exercise_sets_ingests_cleanly(paths: AppPaths) -> None:
    connector = FakeRangeConnector([_summary(1, "running", "2026-01-05")])
    result = _use_case(paths, connector).execute(date(2026, 1, 1), date(2026, 1, 31))

    assert result.outcomes[0].status == "inserted"


def test_optional_endpoint_failure_does_not_fail_the_activity(paths: AppPaths) -> None:
    connector = FakeRangeConnector(
        [_summary(1, "running", "2026-01-05")],
        splits_warning_ids=frozenset({"1"}),
    )
    result = _use_case(paths, connector).execute(date(2026, 1, 1), date(2026, 1, 31))

    assert result.outcomes[0].status == "inserted"


def test_one_failed_activity_does_not_block_others(paths: AppPaths) -> None:
    activities = [
        _summary(1, "running", "2026-01-05"),
        _summary(2, "running", "2026-01-06"),
        _summary(3, "running", "2026-01-07"),
    ]
    connector = FakeRangeConnector(activities, fail_ids=frozenset({"2"}))
    result = _use_case(paths, connector).execute(date(2026, 1, 1), date(2026, 1, 31))

    outcomes = {o.source_activity_id: o.status for o in result.outcomes}
    assert outcomes == {"1": "inserted", "2": "failed", "3": "inserted"}
    assert result.failed_count == 1
    with sqlite3.connect(paths.database_path) as db:
        ids = {row[0] for row in db.execute("SELECT source_activity_id FROM activities")}
    assert ids == {"1", "3"}


def test_malformed_swim_failure_preserves_raw_evidence_but_not_db_row(paths: AppPaths) -> None:
    summary = _summary(714, "lap_swimming", "2026-01-05")
    connector = FakeRangeConnector(
        [summary],
        splits_by_id={"714": {"activityId": 714, "lapDTOs": {"invalid": True}}},
    )
    result = _use_case(paths, connector).execute(date(2026, 1, 1), date(2026, 1, 31))

    assert result.outcomes[0].status == "failed"
    assert (paths.raw_dir / "714" / "splits.json").is_file()
    assert _activity_count(paths) == 0


def test_raw_artifacts_are_preserved_for_ingested_activity(paths: AppPaths) -> None:
    connector = FakeRangeConnector([_summary(1, "running", "2026-01-05")])
    _use_case(paths, connector).execute(date(2026, 1, 1), date(2026, 1, 31))

    activity_dir = paths.raw_dir / "1"
    assert (activity_dir / "activity.json").is_file()
    assert (activity_dir / "details.json").is_file()
    assert (activity_dir / "splits.json").is_file()
    assert (activity_dir / "original.zip").read_bytes() == b"synthetic-original-archive"
    assert (activity_dir / "manifest.json").is_file()


def test_db_rejects_duplicate_activities_across_range_reruns(paths: AppPaths) -> None:
    connector = FakeRangeConnector([_summary(1, "running", "2026-01-05")])
    use_case = _use_case(paths, connector)
    use_case.execute(date(2026, 1, 1), date(2026, 1, 31))
    use_case.execute(date(2026, 1, 1), date(2026, 1, 31))

    assert _activity_count(paths) == 1


def test_invalid_range_is_rejected(paths: AppPaths) -> None:
    connector = FakeRangeConnector([])
    with pytest.raises(InvalidDateRangeError):
        _use_case(paths, connector).execute(date(2026, 2, 1), date(2026, 1, 1))


def test_page_limit_reached_is_reported_when_range_cannot_be_fully_walked(
    paths: AppPaths, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ingest_activity_range, "_MAX_PAGES", 2)
    activities = [_summary(i, "running", "2026-01-01") for i in range(1, 45)]
    connector = FakeRangeConnector(activities)
    result = _use_case(paths, connector).execute(date(2020, 1, 1), date(2026, 12, 31))

    assert result.page_limit_reached is True


def test_undated_activity_is_excluded_but_does_not_stop_discovery(paths: AppPaths) -> None:
    undated = {"activityId": 99, "activityType": {"typeKey": "running"}}
    connector = FakeRangeConnector([undated, _summary(1, "running", "2026-01-05")])
    result = _use_case(paths, connector).execute(date(2026, 1, 1), date(2026, 1, 31))

    assert result.undated_count == 1
    assert result.discovered_count == 1
    assert result.outcomes[0].source_activity_id == "1"
