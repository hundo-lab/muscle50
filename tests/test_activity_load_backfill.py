from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest

from muscle50.application.backfill_activity_load_metrics import BackfillActivityLoadMetrics
from muscle50.application.ingest_activity import IngestGarminActivity
from muscle50.application.refresh_garmin_activity import RefreshGarminActivity
from muscle50.cli import main
from muscle50.config import AppPaths
from muscle50.domain.activity import ActivityMetric
from muscle50.domain.activity_load import ACTIVITY_LOAD_METRIC_KEYS, extract_activity_load_metrics
from muscle50.domain.normalization import normalize_activity
from muscle50.infrastructure.garmin.client import GarminRawActivity, PythonGarminConnector
from muscle50.infrastructure.raw_store import RawStore
from muscle50.infrastructure.sqlite.database import ActivityRepository
from muscle50.presentation.terminal import render_activity_load_backfill_result

FIXTURES = Path(__file__).parent / "fixtures"

# Values copied from the real RAW shape: float32-derived scores, float zone seconds,
# integer intensity minutes.
LOAD_FIELDS: dict[str, Any] = {
    "activityTrainingLoad": 9.5030517578125,
    "aerobicTrainingEffect": 0.20000000298023224,
    "anaerobicTrainingEffect": 0.6000000238418579,
    "hrTimeInZone_1": 453.111,
    "hrTimeInZone_2": 22.998,
    "hrTimeInZone_3": 3.0,
    "hrTimeInZone_4": 0.0,
    "hrTimeInZone_5": 0.0,
    "moderateIntensityMinutes": 8,
    "vigorousIntensityMinutes": 0,
}

EXPECTED_METRICS = {
    "training_load": (9.5030517578125, "score", "activityTrainingLoad"),
    "aerobic_training_effect": (0.20000000298023224, "score", "aerobicTrainingEffect"),
    "anaerobic_training_effect": (0.6000000238418579, "score", "anaerobicTrainingEffect"),
    "hr_time_in_zone_1_seconds": (453.111, "s", "hrTimeInZone_1"),
    "hr_time_in_zone_2_seconds": (22.998, "s", "hrTimeInZone_2"),
    "hr_time_in_zone_3_seconds": (3.0, "s", "hrTimeInZone_3"),
    "hr_time_in_zone_4_seconds": (0.0, "s", "hrTimeInZone_4"),
    "hr_time_in_zone_5_seconds": (0.0, "s", "hrTimeInZone_5"),
    "moderate_intensity_minutes": (8.0, "min", "moderateIntensityMinutes"),
    "vigorous_intensity_minutes": (0.0, "min", "vigorousIntensityMinutes"),
}


def _load_fixture(name: str) -> dict[str, Any]:
    data: object = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def _strength_summary(**extra: Any) -> dict[str, Any]:
    return {
        "activityId": 222,
        "activityName": "Synthetic Strength",
        "activityType": {"typeKey": "strength_training"},
        "startTimeGMT": "2026-09-24 12:13:00",
        "startTimeLocal": "2026-09-24 21:13:00",
        "duration": 2400.0,
        "calories": 300,
        **extra,
    }


def _swim_summary(**extra: Any) -> dict[str, Any]:
    fixture = _load_fixture("garmin_pool_swim.json")
    return {**fixture["summary"], "avgSwolf": 42, "lapCount": 3, **extra}


class RecordingConnector:
    """Serves ingestion and refresh; backfill must never reach any of these methods."""

    def __init__(self, summaries: Sequence[Mapping[str, Any]]):
        self._summaries = {str(item["activityId"]): item for item in summaries}
        self.activity_overrides: dict[str, Mapping[str, Any]] = {}
        self.calls: list[str] = []

    def latest_summary(self) -> Mapping[str, Any] | None:
        self.calls.append("latest_summary")
        return None

    def list_activities(self, start: int, limit: int) -> Sequence[Mapping[str, Any]]:
        self.calls.append("list_activities")
        return ()

    def fetch_raw_activity(self, activity_id: str, source_type_key: str) -> GarminRawActivity:
        self.calls.append(f"fetch_raw_activity:{activity_id}")
        swim = _load_fixture("garmin_pool_swim.json")
        if activity_id == "900001":
            activity: Mapping[str, Any] = swim["activity"]
            splits: Mapping[str, Any] | None = swim["splits"]
            exercise_sets = None
        else:
            activity = {"activityId": int(activity_id), "activityTypeDTO": {"typeKey": source_type_key}}
            splits = {"lapDTOs": []}
            exercise_sets = {**_load_fixture("synthetic_strength_sets.json"), "activityId": int(activity_id)}
        activity = self.activity_overrides.get(activity_id, activity)
        return GarminRawActivity(
            summary={},
            activity=dict(activity),
            details={"activityId": int(activity_id)},
            splits=splits,
            exercise_sets=exercise_sets,
            original_archive=b"synthetic-original",
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


def _import(paths: AppPaths, summaries: Sequence[Mapping[str, Any]]) -> tuple[ActivityRepository, RecordingConnector]:
    repository = ActivityRepository(paths.database_path)
    repository.migrate()
    connector = RecordingConnector(summaries)
    ingest = IngestGarminActivity(connector, repository, RawStore(paths.raw_dir, paths.root, paths.tmp_dir))
    for summary in summaries:
        ingest.execute(summary)
    return repository, connector


def _backfill(paths: AppPaths, repository: ActivityRepository) -> BackfillActivityLoadMetrics:
    return BackfillActivityLoadMetrics(repository, RawStore(paths.raw_dir, paths.root, paths.tmp_dir))


def _table(paths: AppPaths, table: str) -> list[tuple[Any, ...]]:
    with sqlite3.connect(paths.database_path) as connection:
        return [tuple(row) for row in connection.execute(f"SELECT * FROM {table} ORDER BY 1, 2")]


def _load_metric_rows(paths: AppPaths) -> dict[tuple[str, str], tuple[Any, ...]]:
    with sqlite3.connect(paths.database_path) as connection:
        rows = connection.execute(
            """
            SELECT activity.source_activity_id, metric.metric_key, metric.numeric_value,
                   metric.text_value, metric.unit, metric.source_path
            FROM activity_metrics AS metric JOIN activities AS activity ON activity.id = metric.activity_id
            """
        ).fetchall()
    return {(row[0], row[1]): tuple(row[2:]) for row in rows if row[1] in ACTIVITY_LOAD_METRIC_KEYS}


def _other_metric_rows(paths: AppPaths) -> list[tuple[Any, ...]]:
    placeholders = ",".join("?" for _ in ACTIVITY_LOAD_METRIC_KEYS)
    with sqlite3.connect(paths.database_path) as connection:
        return [
            tuple(row)
            for row in connection.execute(
                f"SELECT * FROM activity_metrics WHERE metric_key NOT IN ({placeholders}) ORDER BY id",
                tuple(sorted(ACTIVITY_LOAD_METRIC_KEYS)),
            )
        ]


def _raw_hashes(paths: AppPaths) -> dict[str, str]:
    return {
        path.relative_to(paths.root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted((paths.root / "raw").rglob("*"))
        if path.is_file()
    }


def _protected_state(paths: AppPaths) -> dict[str, Any]:
    return {
        "activities": _table(paths, "activities"),
        "strength_sets": _table(paths, "strength_sets"),
        "swim_activities": _table(paths, "swim_activities"),
        "swim_laps": _table(paths, "swim_laps"),
        "swim_lengths": _table(paths, "swim_lengths"),
        "raw_artifacts": _table(paths, "raw_artifacts"),
        "other_metrics": _other_metric_rows(paths),
        "raw_files": _raw_hashes(paths),
    }


def test_contract_maps_every_raw_field_exactly_with_units() -> None:
    extraction = extract_activity_load_metrics({**_strength_summary(), **LOAD_FIELDS})

    assert extraction.issues == ()
    assert {metric.key: (metric.value, metric.unit, metric.source_path) for metric in extraction.metrics} == (
        EXPECTED_METRICS
    )
    assert {metric.key for metric in extraction.metrics} == ACTIVITY_LOAD_METRIC_KEYS
    assert all(isinstance(metric.value, float) for metric in extraction.metrics)


def test_contract_reports_missing_null_and_malformed_without_coercion() -> None:
    summary = {
        **LOAD_FIELDS,
        "activityTrainingLoad": None,
        "aerobicTrainingEffect": "2.5",
        "anaerobicTrainingEffect": True,
        "hrTimeInZone_1": float("nan"),
        "hrTimeInZone_2": float("inf"),
        "hrTimeInZone_3": {"value": 3},
    }
    del summary["vigorousIntensityMinutes"]

    extraction = extract_activity_load_metrics(summary)

    issues = {issue.source_key: issue.kind for issue in extraction.issues}
    assert issues == {
        "activityTrainingLoad": "null",
        "aerobicTrainingEffect": "malformed",
        "anaerobicTrainingEffect": "malformed",
        "hrTimeInZone_1": "malformed",
        "hrTimeInZone_2": "malformed",
        "hrTimeInZone_3": "malformed",
        "vigorousIntensityMinutes": "missing",
    }
    assert {metric.key for metric in extraction.metrics} == {
        "hr_time_in_zone_4_seconds",
        "hr_time_in_zone_5_seconds",
        "moderate_intensity_minutes",
    }


def test_contract_copies_out_of_range_values_verbatim_for_the_future_quality_layer() -> None:
    extraction = extract_activity_load_metrics({**LOAD_FIELDS, "aerobicTrainingEffect": 5.7, "hrTimeInZone_1": -1})

    values = {metric.key: metric.value for metric in extraction.metrics}
    assert extraction.issues == ()
    assert values["aerobic_training_effect"] == 5.7
    assert values["hr_time_in_zone_1_seconds"] == -1.0


def test_shared_normalization_does_not_emit_load_metrics() -> None:
    normalized = normalize_activity({**_strength_summary(), **LOAD_FIELDS}, {})

    assert not {metric.key for metric in normalized.metrics} & ACTIVITY_LOAD_METRIC_KEYS


def test_backfill_writes_exact_metrics_and_touches_nothing_else(paths: AppPaths) -> None:
    repository, connector = _import(
        paths, [_strength_summary(**LOAD_FIELDS), _swim_summary(**{**LOAD_FIELDS, "hrTimeInZone_3": 812.5})]
    )
    calls_before = list(connector.calls)
    before = _protected_state(paths)
    assert before["strength_sets"] and before["swim_laps"] and before["swim_lengths"]
    assert {row[2] for row in before["other_metrics"]} >= {"set_count", "rep_count", "average_swolf", "lap_count"}

    result = _backfill(paths, repository).execute()

    assert connector.calls == calls_before
    assert _protected_state(paths) == before
    assert (result.activities_examined, result.raw_summaries_found, result.activities_changed) == (2, 2, 2)
    assert (result.metrics_inserted, result.metrics_updated, result.metrics_unchanged) == (20, 0, 0)
    assert result.missing_raw == result.unreadable_raw == ()
    assert result.malformed_values == result.skipped_values == ()

    rows = _load_metric_rows(paths)
    assert len(rows) == 20
    for key, (value, unit, source_path) in EXPECTED_METRICS.items():
        expected_value = 812.5 if key == "hr_time_in_zone_3_seconds" else value
        assert rows[("222", key)] == (value, None, unit, source_path)
        assert rows[("900001", key)] == (expected_value, None, unit, source_path)


def test_second_backfill_is_idempotent(paths: AppPaths) -> None:
    repository, _connector = _import(paths, [_strength_summary(**LOAD_FIELDS)])
    use_case = _backfill(paths, repository)
    use_case.execute()
    after_first = (_load_metric_rows(paths), _table(paths, "activity_metrics"), _protected_state(paths))

    second = use_case.execute()

    assert (second.metrics_inserted, second.metrics_updated, second.metrics_unchanged) == (0, 0, 10)
    assert second.activities_changed == 0
    assert second.canonical_changes == 0
    assert (_load_metric_rows(paths), _table(paths, "activity_metrics"), _protected_state(paths)) == after_first


def test_changed_supported_values_are_updated_and_unrelated_metrics_survive(paths: AppPaths) -> None:
    repository, _connector = _import(paths, [_strength_summary(**LOAD_FIELDS)])
    use_case = _backfill(paths, repository)
    use_case.execute()
    with sqlite3.connect(paths.database_path) as connection:
        connection.execute("UPDATE activity_metrics SET numeric_value = 1.0 WHERE metric_key = 'training_load'")
        connection.execute(
            "UPDATE activity_metrics SET unit = 'minutes' WHERE metric_key = 'moderate_intensity_minutes'"
        )
        connection.execute(
            "UPDATE activity_metrics SET source_path = 'guess' WHERE metric_key = 'hr_time_in_zone_2_seconds'"
        )
        connection.execute(
            """
            INSERT INTO activity_metrics (activity_id, metric_key, numeric_value, unit, source_path)
            SELECT id, 'custom_future_metric', 7.0, 'x', 'manual' FROM activities
            """
        )
    unrelated_before = _other_metric_rows(paths)

    result = use_case.execute()

    assert (result.metrics_inserted, result.metrics_updated, result.metrics_unchanged) == (0, 3, 7)
    assert result.activities_changed == 1
    rows = _load_metric_rows(paths)
    for key, (value, unit, source_path) in EXPECTED_METRICS.items():
        assert rows[("222", key)] == (value, None, unit, source_path)
    assert _other_metric_rows(paths) == unrelated_before
    assert any(row[2] == "custom_future_metric" for row in unrelated_before)


def test_missing_null_and_malformed_raw_values_are_reported_and_existing_rows_kept(paths: AppPaths) -> None:
    bad_fields = {**LOAD_FIELDS, "activityTrainingLoad": None, "aerobicTrainingEffect": "bad"}
    del bad_fields["hrTimeInZone_5"]
    repository, _connector = _import(paths, [_strength_summary(**bad_fields)])
    with sqlite3.connect(paths.database_path) as connection:
        connection.execute(
            """
            INSERT INTO activity_metrics (activity_id, metric_key, numeric_value, unit, source_path)
            SELECT id, 'training_load', 33.0, 'score', 'activityTrainingLoad' FROM activities
            """
        )

    result = _backfill(paths, repository).execute()

    assert [(item.source_activity_id, item.issue.source_key) for item in result.malformed_values] == [
        ("222", "aerobicTrainingEffect")
    ]
    assert sorted((item.issue.source_key, item.issue.kind) for item in result.skipped_values) == [
        ("activityTrainingLoad", "null"),
        ("hrTimeInZone_5", "missing"),
    ]
    assert (result.metrics_inserted, result.metrics_updated) == (7, 0)
    rows = _load_metric_rows(paths)
    # A missing/null source never deletes or overwrites a stored canonical value.
    assert rows[("222", "training_load")] == (33.0, None, "score", "activityTrainingLoad")
    assert ("222", "aerobic_training_effect") not in rows
    assert ("222", "hr_time_in_zone_5_seconds") not in rows
    output = render_activity_load_backfill_result(result)
    assert "Malformed values: 1" in output
    assert "Skipped values (missing/null): 2" in output


def test_missing_and_unreadable_raw_summaries_are_reported_per_activity(paths: AppPaths) -> None:
    repository, _connector = _import(
        paths,
        [
            _strength_summary(**LOAD_FIELDS),
            _strength_summary(activityId=333, **LOAD_FIELDS),
            _strength_summary(activityId=444, **LOAD_FIELDS),
        ],
    )
    (paths.raw_dir / "333" / "summary.json").unlink()
    (paths.raw_dir / "444" / "summary.json").write_text("{not json", encoding="utf-8")

    result = _backfill(paths, repository).execute()

    assert result.activities_examined == 3
    assert result.raw_summaries_found == 1
    assert result.missing_raw == ("333",)
    assert result.unreadable_raw == ("444",)
    assert {key[0] for key in _load_metric_rows(paths)} == {"222"}


def test_backfill_never_reads_refresh_snapshot_summaries(paths: AppPaths) -> None:
    repository, _connector = _import(paths, [_strength_summary()])
    snapshot = paths.raw_dir / "222" / "snapshots" / "deadbeef"
    snapshot.mkdir(parents=True)
    (snapshot / "summary.json").write_text(json.dumps({"summaryDTO": LOAD_FIELDS, **LOAD_FIELDS}), encoding="utf-8")

    result = _backfill(paths, repository).execute()

    assert result.canonical_changes == 0
    assert len(result.skipped_values) == 10
    assert _load_metric_rows(paths) == {}


def test_dry_run_reports_same_counts_and_writes_nothing(paths: AppPaths) -> None:
    repository, _connector = _import(paths, [_strength_summary(**LOAD_FIELDS)])
    before = (_table(paths, "activity_metrics"), _protected_state(paths))
    use_case = _backfill(paths, repository)

    dry = use_case.execute(dry_run=True)

    assert (_table(paths, "activity_metrics"), _protected_state(paths)) == before
    real = use_case.execute()
    assert (dry.metrics_inserted, dry.metrics_updated, dry.metrics_unchanged, dry.activities_changed) == (
        real.metrics_inserted,
        real.metrics_updated,
        real.metrics_unchanged,
        real.activities_changed,
    )
    assert "dry run" in render_activity_load_backfill_result(dry)


def test_upsert_rejects_keys_outside_the_allow_list(paths: AppPaths) -> None:
    repository, _connector = _import(paths, [_strength_summary()])
    before = _table(paths, "activity_metrics")

    with pytest.raises(ValueError, match="not allowed"):
        repository.upsert_activity_metrics(
            "222",
            (
                ActivityMetric("training_load", 1.0, "score", "activityTrainingLoad"),
                ActivityMetric("set_count", 99, "count", "exercise_sets"),
            ),
            ACTIVITY_LOAD_METRIC_KEYS,
        )

    assert _table(paths, "activity_metrics") == before


def test_backfilled_metrics_survive_a_detail_shape_refresh_unchanged(paths: AppPaths) -> None:
    repository, connector = _import(paths, [_strength_summary(**LOAD_FIELDS)])
    _backfill(paths, repository).execute()
    backfilled = _load_metric_rows(paths)
    assert len(backfilled) == 10
    connector.activity_overrides["222"] = {
        "activityId": 222,
        "activityName": "Refreshed Strength",
        "activityTypeDTO": {"typeKey": "strength_training"},
        "summaryDTO": {
            "startTimeGMT": "2026-09-24T12:13:00.0",
            "duration": 2500.0,
            # Detail endpoint values differing from the list summary must not leak in.
            "activityTrainingLoad": 99.0,
            "moderateIntensityMinutes": 99,
        },
    }

    RefreshGarminActivity(connector, repository, RawStore(paths.raw_dir, paths.root, paths.tmp_dir)).execute("222")

    assert _load_metric_rows(paths) == backfilled
    refreshed = repository.find("222")
    assert refreshed is not None and refreshed.elapsed_seconds == 2500.0


def test_cli_backfill_never_authenticates(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    paths: AppPaths,
) -> None:
    repository, _connector = _import(paths, [_strength_summary(**LOAD_FIELDS)])
    monkeypatch.setenv("MUSCLE50_HOME", str(paths.root))
    monkeypatch.setattr(
        PythonGarminConnector,
        "authenticate",
        lambda auth_dir: pytest.fail("backfill must not authenticate with Garmin"),
    )

    assert main(["garmin", "backfill-load-metrics", "--dry-run"]) == 0
    assert "Metric rows inserted: 10" in capsys.readouterr().out
    assert _load_metric_rows(paths) == {}

    assert main(["garmin", "backfill-load-metrics"]) == 0
    assert "Metric rows inserted: 10" in capsys.readouterr().out
    assert main(["garmin", "backfill-load-metrics"]) == 0
    output = capsys.readouterr().out
    assert "Metric rows inserted: 0" in output
    assert "Metrics already identical: 10" in output
    assert len(_load_metric_rows(paths)) == 10
    del repository
