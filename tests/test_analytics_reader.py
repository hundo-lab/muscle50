from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import date
from pathlib import Path

import pytest
from analytics_builders import activity, recovery, strength_set, swim_detail, uniform_lap

from muscle50.application.training_snapshot import BuildTrainingSnapshot
from muscle50.cli import main
from muscle50.domain.activity import ActivityType, NormalizedActivity
from muscle50.domain.analytics import InvalidSnapshotWindowError
from muscle50.infrastructure.garmin.client import PythonGarminConnector
from muscle50.infrastructure.raw_store import RawArtifact, RecoveryCapture
from muscle50.infrastructure.sqlite.analytics_reader import AnalyticsDatabaseError, SqliteAnalyticsReader
from muscle50.infrastructure.sqlite.database import ActivityRepository, DailyRecoveryRepository


def _artifact(source_id: str) -> RawArtifact:
    return RawArtifact("activity", f"raw/{source_id}/activity.json", "application/json", "0" * 64, 2)


def _save(database: Path, item: NormalizedActivity) -> None:
    ActivityRepository(database).save(item, (_artifact(item.source_activity_id),))


def _save_recovery(database: Path, calendar_date: str, **overrides: object) -> None:
    capture = RecoveryCapture(
        capture_id=f"capture-{calendar_date}",
        requested_date=calendar_date,
        manifest_relative_path=f"recovery/{calendar_date}/manifest.json",
        artifacts=(
            RawArtifact("sleep", f"recovery/{calendar_date}/sleep.json", "application/json", "0" * 64, 2),
        ),
    )
    DailyRecoveryRepository(database).save(recovery(calendar_date, **overrides), capture)


@pytest.fixture
def database(tmp_path: Path) -> Path:
    path = tmp_path / "db" / "muscle50.sqlite3"
    ActivityRepository(path).migrate()
    swim_id = "9002"
    _save(
        path,
        activity(
            "9001",
            "2026-03-10T07:30:00",
            ActivityType.STRENGTH,
            strength_sets=(strength_set(1), strength_set(2, set_type="REST", category=None)),
        ),
    )
    _save(
        path,
        activity(
            swim_id,
            "2026-03-12T19:00:00",
            ActivityType.SWIMMING,
            distance_meters=200.0,
            swim_detail=swim_detail(swim_id, (uniform_lap(0, 4, 25.0, 30.0), uniform_lap(1, 4, 25.0, 30.0))),
        ),
    )
    _save(path, activity("9003", "2026-03-20T07:00:00"))  # outside the default window
    _save(path, activity("9004", None))  # undated
    _save_recovery(path, "2026-03-11")
    _save_recovery(path, "2026-03-13", sleep_seconds=None)
    return path


def _file_state(path: Path) -> tuple[str, int]:
    return hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_mtime_ns


def test_reader_round_trips_canonical_activities_and_recovery_for_the_window(database: Path) -> None:
    data = SqliteAnalyticsReader(database).load(date(2026, 3, 8), date(2026, 3, 14))

    assert [item.source_activity_id for item in data.activities] == ["9001", "9002"]
    assert data.undated_source_activity_ids == ("9004",)
    assert [item.calendar_date for item in data.recoveries] == ["2026-03-11", "2026-03-13"]
    assert data.recoveries[1].sleep_seconds is None
    strength, swim = data.activities
    assert len(strength.strength_sets) == 2
    assert {metric.key for metric in strength.metrics} >= {"training_load", "vigorous_intensity_minutes"}
    assert swim.swim_detail is not None
    assert [len(lap.lengths) for lap in swim.swim_detail.laps] == [4, 4]


def test_snapshot_from_database_matches_stored_data(database: Path) -> None:
    snapshot = BuildTrainingSnapshot(SqliteAnalyticsReader(database)).execute(date(2026, 3, 14))

    assert snapshot.activities.source_activity_ids == ("9001", "9002")
    assert snapshot.strength.active_set_count == 1
    assert snapshot.strength.rest_set_count == 1
    assert snapshot.swimming.summary_distance_meters.value == 200.0
    assert snapshot.swimming.plausible_detail_distance_meters.value == 200.0
    assert snapshot.recovery.dates_with_row == (date(2026, 3, 11), date(2026, 3, 13))


def test_reader_never_modifies_the_database_file(database: Path) -> None:
    before = _file_state(database)

    SqliteAnalyticsReader(database).load(date(2026, 3, 1), date(2026, 3, 31))
    BuildTrainingSnapshot(SqliteAnalyticsReader(database)).execute(date(2026, 3, 14), 30)

    assert _file_state(database) == before
    wal = database.with_name(database.name + "-wal")
    assert not wal.exists() or wal.stat().st_size == 0


def test_reader_rejects_writes_through_its_connection(database: Path) -> None:
    reader = SqliteAnalyticsReader(database)
    with pytest.raises(AnalyticsDatabaseError), reader._read_transaction() as connection:
        connection.execute("DELETE FROM activities")

    assert len(SqliteAnalyticsReader(database).load(date(2026, 1, 1), date(2026, 12, 31)).activities) == 3


def test_missing_database_raises_and_creates_nothing(tmp_path: Path) -> None:
    missing = tmp_path / "absent" / "muscle50.sqlite3"

    with pytest.raises(AnalyticsDatabaseError, match="not found"):
        SqliteAnalyticsReader(missing).load(date(2026, 3, 8), date(2026, 3, 14))

    assert not missing.parent.exists()


def test_unmigrated_database_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "old.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, applied_at_utc TEXT)")
        connection.execute("INSERT INTO schema_migrations VALUES (5, 'x')")
    connection.close()

    with pytest.raises(AnalyticsDatabaseError, match="schema version 5"):
        SqliteAnalyticsReader(path).load(date(2026, 3, 8), date(2026, 3, 14))


def test_invalid_window_is_rejected_before_reading(tmp_path: Path) -> None:
    reader = SqliteAnalyticsReader(tmp_path / "absent.sqlite3")

    with pytest.raises(InvalidSnapshotWindowError):
        BuildTrainingSnapshot(reader).execute(date(2026, 3, 14), 0)


# CLI


@pytest.fixture
def home(database: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = database.parents[1]
    monkeypatch.setenv("MUSCLE50_HOME", str(root))
    monkeypatch.setattr(
        PythonGarminConnector,
        "authenticate",
        lambda auth_dir: pytest.fail("analytics must never authenticate"),
    )
    return root


def test_cli_snapshot_prints_text_and_leaves_home_untouched(
    home: Path, database: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    before_db = _file_state(database)
    before_dirs = sorted(item.name for item in home.iterdir())

    exit_code = main(["analytics", "snapshot", "--date", "2026-03-14"])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "Training snapshot: 2026-03-08 ~ 2026-03-14 (7 days" in output
    assert "Strength: 1 sessions" in output
    assert _file_state(database) == before_db
    assert sorted(item.name for item in home.iterdir()) == before_dirs


def test_cli_snapshot_json_with_custom_window(home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main(["analytics", "snapshot", "--date", "2026-03-20", "--days", "13", "--json"])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["window"]["start"] == "2026-03-08"
    assert payload["activities"]["source_activity_ids"] == ["9001", "9002", "9003"]


@pytest.mark.parametrize(
    "argv",
    [
        ["analytics", "snapshot", "--date", "2026-3-14"],
        ["analytics", "snapshot", "--date", "2026-03-14", "--days", "0"],
        ["analytics", "snapshot", "--date", "2026-03-14", "--days", "91"],
    ],
)
def test_cli_snapshot_rejects_invalid_input(
    home: Path, argv: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(argv) == 1
    assert capsys.readouterr().err


def test_cli_snapshot_requires_date() -> None:
    with pytest.raises(SystemExit):
        main(["analytics", "snapshot"])


def test_cli_snapshot_reports_missing_database(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("MUSCLE50_HOME", str(tmp_path / "empty-home"))

    assert main(["analytics", "snapshot", "--date", "2026-03-14"]) == 1
    assert "not found" in capsys.readouterr().err
    assert not (tmp_path / "empty-home").exists()
