"""The details artifact reader, the RAW heart-rate source and the use case. Synthetic data only."""

from __future__ import annotations

import hashlib
import sqlite3
from datetime import date
from pathlib import Path

import pytest
from strength_set_timing_builders import (
    Active,
    Rest,
    build_session,
    details_payload,
    heart_rate_samples,
    json_bytes,
    raw_artifact,
    save_with_details,
    strength_activity,
)

from muscle50.application.strength_set_timing import BuildSnapshotWithSetTiming
from muscle50.application.training_snapshot import BuildTrainingSnapshot
from muscle50.domain.strength_set_timing import HeartRateLoad, HeartRateStatus, TimingMethod
from muscle50.infrastructure.heart_rate_raw import RawHeartRateSource
from muscle50.infrastructure.raw_store import ActivityCapture, RawArtifact
from muscle50.infrastructure.sqlite.analytics_reader import SqliteAnalyticsReader
from muscle50.infrastructure.sqlite.database import ActivityRepository

SOURCE_ID = "9101"
AS_OF = date(2026, 3, 14)


def _rows() -> list[Active | Rest]:
    rows: list[Active | Rest] = [Active(10, 20.0)]
    for _ in range(5):
        rows.extend((Rest(40.0), Active(10, 20.0)))
    rows.extend((Rest(50.0), Active(4, 1.629, hidden_s=20.0)))
    return rows


@pytest.fixture
def home(tmp_path: Path) -> Path:
    return tmp_path / "home"


def _database(home: Path) -> Path:
    return home / "db" / "muscle50.sqlite3"


def _source(home: Path) -> RawHeartRateSource:
    reader = SqliteAnalyticsReader(_database(home))
    return RawHeartRateSource(reader, home, home / "raw" / "garmin" / "activities")


def _store(home: Path, *, details: bool = True) -> RawArtifact | None:
    session = build_session(_rows())
    payload = details_payload(heart_rate_samples(session)) if details else None
    return save_with_details(home, strength_activity(SOURCE_ID, session), payload)


def _refresh(home: Path, payload: object) -> RawArtifact:
    capture_id = "c" * 64
    subdir = f"snapshots/{capture_id}/"
    artifact = raw_artifact(home, SOURCE_ID, "details", "details.json", json_bytes(payload), subdir)
    activity_artifact = raw_artifact(home, SOURCE_ID, "activity", "activity.json", json_bytes({"a": 1}), subdir)
    capture = ActivityCapture(
        capture_id,
        SOURCE_ID,
        f"raw/garmin/activities/{SOURCE_ID}/{subdir}manifest.json",
        (activity_artifact, artifact),
    )
    repository = ActivityRepository(_database(home))
    repository.record_refresh_capture(capture)
    repository.refresh(strength_activity(SOURCE_ID, build_session(_rows())), capture)
    return artifact


def _set_db_artifact(home: Path, current_path: str, **values: object) -> None:
    """Tamper with the stored artifact row (test setup only; the code under test never writes)."""
    connection = sqlite3.connect(_database(home))
    try:
        assignments = ", ".join(f"{key} = ?" for key in values)
        connection.execute(
            f"UPDATE raw_artifacts SET {assignments} WHERE relative_path = ?", (*values.values(), current_path)
        )
        connection.commit()
    finally:
        connection.close()


def test_reader_returns_the_initial_details_artifact(home: Path) -> None:
    stored = _store(home)

    assert SqliteAnalyticsReader(_database(home)).details_artifact(SOURCE_ID) == stored
    assert SqliteAnalyticsReader(_database(home)).details_artifact("9999") is None


def test_reader_prefers_the_current_refresh_capture(home: Path) -> None:
    _store(home)
    refreshed = _refresh(home, details_payload(heart_rate_samples(build_session(_rows()))))

    artifact = SqliteAnalyticsReader(_database(home)).details_artifact(SOURCE_ID)

    assert artifact == refreshed
    assert artifact is not None and "/snapshots/" in artifact.relative_path


def test_source_loads_the_refresh_snapshot_inside_the_activity_dir(home: Path) -> None:
    _store(home)
    _refresh(home, details_payload(heart_rate_samples(build_session(_rows()))))

    load = _source(home).load(SOURCE_ID)

    assert load.status is HeartRateStatus.AVAILABLE
    assert load.artifact_relative_path is not None and "/snapshots/" in load.artifact_relative_path


def test_source_without_details_artifact_is_raw_missing(home: Path) -> None:
    _store(home, details=False)

    assert _source(home).load(SOURCE_ID) == HeartRateLoad(HeartRateStatus.RAW_MISSING, (), None)


def test_source_with_a_missing_file_is_raw_missing(home: Path) -> None:
    stored = _store(home)
    assert stored is not None
    (home / stored.relative_path).unlink()

    load = _source(home).load(SOURCE_ID)

    assert (load.status, load.samples) == (HeartRateStatus.RAW_MISSING, ())


def test_source_with_a_changed_file_is_unreadable(home: Path) -> None:
    stored = _store(home)
    assert stored is not None
    path = home / stored.relative_path
    content = path.read_bytes()
    path.write_bytes(content.replace(b"91.25", b"91.26", 1))  # same size, other sha256

    assert _source(home).load(SOURCE_ID).status is HeartRateStatus.RAW_UNREADABLE


def test_source_with_a_wrong_recorded_size_is_unreadable(home: Path) -> None:
    stored = _store(home)
    assert stored is not None
    _set_db_artifact(home, stored.relative_path, byte_size=stored.byte_size + 1)

    assert _source(home).load(SOURCE_ID).status is HeartRateStatus.RAW_UNREADABLE


@pytest.mark.parametrize("escape", ["raw/garmin/activities/9102/details.json", "../outside/details.json"])
def test_source_refuses_a_path_outside_the_activity_dir(home: Path, escape: str) -> None:
    stored = _store(home)
    assert stored is not None
    # A valid file outside raw/garmin/activities/<id>/ with matching size and sha.
    content = (home / stored.relative_path).read_bytes()
    outside = (home / escape).resolve()
    outside.parent.mkdir(parents=True, exist_ok=True)
    outside.write_bytes(content)
    _set_db_artifact(home, stored.relative_path, relative_path=escape)

    load = _source(home).load(SOURCE_ID)

    assert load.status is HeartRateStatus.RAW_UNREADABLE
    assert load.samples == ()


def test_source_with_invalid_json_is_unreadable(home: Path) -> None:
    stored = _store(home)
    assert stored is not None
    content = b"{not json"
    (home / stored.relative_path).write_bytes(content)
    _set_db_artifact(home, stored.relative_path, byte_size=len(content), sha256=hashlib.sha256(content).hexdigest())

    assert _source(home).load(SOURCE_ID).status is HeartRateStatus.RAW_UNREADABLE


def _tree_state(root: Path) -> dict[str, tuple[str, int]]:
    """sha256 and mtime of every file except SQLite's -wal/-shm, which a WAL reader may leave empty."""
    return {
        path.relative_to(root).as_posix(): (hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_mtime_ns)
        for path in sorted(root.rglob("*"))
        if path.is_file() and not path.name.endswith(("-wal", "-shm"))
    }


def _assert_wal_empty(home: Path) -> None:
    wal = _database(home).with_name("muscle50.sqlite3-wal")
    assert not wal.exists() or wal.stat().st_size == 0


def test_use_case_reads_raw_without_changing_files_or_directories(home: Path) -> None:
    _store(home)
    before = _tree_state(home)
    directories = sorted(path.as_posix() for path in home.rglob("*") if path.is_dir())

    result = BuildSnapshotWithSetTiming(SqliteAnalyticsReader(_database(home)), _source(home)).execute(AS_OF)

    assert result.set_timing is not None
    assert result.set_timing.suspect_sets[-1].method is TimingMethod.HEART_RATE
    assert _tree_state(home) == before
    assert sorted(path.as_posix() for path in home.rglob("*") if path.is_dir()) == directories
    _assert_wal_empty(home)


def test_use_case_snapshot_equals_the_plain_snapshot(home: Path) -> None:
    _store(home)
    reader = SqliteAnalyticsReader(_database(home))

    result = BuildSnapshotWithSetTiming(reader, _source(home)).execute(AS_OF)

    assert result.snapshot == BuildTrainingSnapshot(reader).execute(AS_OF)


class _SpySource:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def load(self, source_activity_id: str) -> HeartRateLoad:
        self.calls.append(source_activity_id)
        return HeartRateLoad(HeartRateStatus.RAW_MISSING, (), None)


def test_heart_rate_is_not_read_without_a_suspect_set_after_a_rest(home: Path) -> None:
    normal = build_session([Active(10, 20.0), Rest(40.0), Active(10, 20.0)])
    first_row_only = build_session([Active(5, 1.699), Rest(40.0), Active(10, 20.0)])
    save_with_details(home, strength_activity("9101", normal), None)
    save_with_details(home, strength_activity("9102", first_row_only, "2026-03-13T10:00:00"), None)
    spy = _SpySource()

    result = BuildSnapshotWithSetTiming(SqliteAnalyticsReader(_database(home)), spy).execute(AS_OF)

    assert spy.calls == []
    assert result.set_timing is not None
    assert [session.source_activity_id for session in result.set_timing.sessions] == ["9102"]
    assert result.set_timing.sessions[0].heart_rate is None


def test_heart_rate_is_read_once_per_activity_that_needs_it(home: Path) -> None:
    _store(home)
    spy = _SpySource()

    BuildSnapshotWithSetTiming(SqliteAnalyticsReader(_database(home)), spy).execute(AS_OF)

    assert spy.calls == [SOURCE_ID]
