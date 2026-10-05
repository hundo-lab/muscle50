"""Sync Coverage v1 end to end: fake Garmin, temporary MUSCLE50_HOME, pinned clock (AC1-AC4, isolation)."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import date
from pathlib import Path
from typing import Any

import pytest
import sync_coverage_builders as builders
from sync_coverage_builders import ALL_RECOVERY_KINDS, AUTH_FAILURE, FakeGarmin, summary

import muscle50.application.ingest_activity_range as ingest_range
import muscle50.cli as cli
import muscle50.infrastructure.sqlite.sync_coverage as coverage_repository
from muscle50.cli import main
from muscle50.domain.sync_coverage import CoverageKind, CoverageStatus, SyncCoverageEntry
from muscle50.infrastructure.garmin.client import GarminConnectorError, PythonGarminConnector
from muscle50.infrastructure.sqlite.database import ActivityRepository
from muscle50.infrastructure.sqlite.sync_coverage import SqliteSyncCoverageRepository

TODAY = date(2026, 10, 5)
NOW = "2026-10-05T12:00:00.000000+00:00"
WARNING = "경고: sync coverage를 기록하지 못했습니다 (동기화된 데이터는 저장됨): synthetic coverage failure\n"
RECORDED_BY = (
    "Recorded by: garmin activities --from/--to, garmin recovery, daily. Not recorded: garmin latest, garmin refresh."
)


@pytest.fixture(autouse=True)
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "home"
    monkeypatch.setenv("MUSCLE50_HOME", str(root))
    monkeypatch.setattr(cli, "_today", lambda: TODAY)
    monkeypatch.setattr(cli, "_local_timezone", lambda day: builders.KST)
    monkeypatch.setattr(coverage_repository, "_now", lambda: NOW)
    monkeypatch.setattr(PythonGarminConnector, "authenticate", lambda *args, **kwargs: pytest.fail("no Garmin"))
    return root


def _use(monkeypatch: pytest.MonkeyPatch, garmin: FakeGarmin) -> FakeGarmin:
    def authenticate(auth_dir: Path, **_kwargs: Any) -> FakeGarmin:
        return garmin

    monkeypatch.setattr(PythonGarminConnector, "authenticate", authenticate)
    return garmin


def _run(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, str, str]:
    code = main(list(argv))
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def _ok(capsys: pytest.CaptureFixture[str], *argv: str) -> str:
    code, out, err = _run(capsys, *argv)
    assert code == 0, err
    return out


def _database(root: Path) -> Path:
    return root / "db" / "muscle50.sqlite3"


def _coverage_rows(root: Path) -> list[tuple[Any, ...]]:
    with sqlite3.connect(_database(root)) as connection:
        return connection.execute(
            "SELECT data_kind, calendar_date, status, source, command, missing_endpoints, failed_activity_ids, "
            "synced_at_utc FROM sync_coverage ORDER BY data_kind, calendar_date"
        ).fetchall()


def _count(root: Path, table: str) -> int:
    with sqlite3.connect(_database(root)) as connection:
        return int(connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])


def _coverage_json(capsys: pytest.CaptureFixture[str], start: str, end: str) -> dict[str, Any]:
    document: dict[str, Any] = json.loads(_ok(capsys, "garmin", "coverage", "--from", start, "--to", end, "--json"))
    return document


def _statuses(document: dict[str, Any], kind: str) -> dict[str, str]:
    return {day["date"]: day[kind]["status"] for day in document["days"]}


def _week_account(**kwargs: Any) -> FakeGarmin:
    """Activities on 10-01, 10-03 and 10-05; 10-02 and 10-04 are rest days."""
    return FakeGarmin(
        [
            summary(500, "running", "2026-10-05", "07:00:00"),
            summary(222, "strength_training", "2026-10-03", "18:00:00"),
            summary(300, "running", "2026-10-01", "07:00:00"),
            summary(100, "running", "2026-09-28", "07:00:00"),
        ],
        **kwargs,
    )


def _break_coverage(root: Path) -> None:
    """A migrated database whose coverage writes always fail (the sync tables still work)."""
    ActivityRepository(_database(root)).migrate()
    with sqlite3.connect(_database(root)) as connection:
        connection.execute(
            "CREATE TRIGGER fail_coverage BEFORE INSERT ON sync_coverage "
            "BEGIN SELECT RAISE(ABORT, 'synthetic coverage failure'); END"
        )


# --- AC1 ---------------------------------------------------------------------------------------


def test_activity_range_then_coverage_shows_every_date_synced_including_rest_days(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _use(monkeypatch, _week_account())
    assert "신규 저장: 3건" in _ok(capsys, "garmin", "activities", "--from", "2026-10-01", "--to", "2026-10-05")

    text = _ok(capsys, "garmin", "coverage", "--from", "2026-10-01", "--to", "2026-10-05")

    assert text.splitlines() == [
        "Garmin sync coverage 2026-10-01..2026-10-05 (latest recorded result per date)",
        "date        activities                    recovery",
        "2026-10-01  synced (1 stored)             not synced",
        "2026-10-02  synced (0 stored)             not synced",
        "2026-10-03  synced (1 stored)             not synced",
        "2026-10-04  synced (0 stored)             not synced",
        "2026-10-05  synced (1 stored)             not synced",
        "activities: synced 5, failed 0, not synced 0; recovery: synced 0, partial 0, failed 0, not synced 5",
        RECORDED_BY,
    ]
    assert text.isascii()
    document = _ok(capsys, "garmin", "coverage", "--from", "2026-10-02", "--to", "2026-10-02", "--json")
    expected = {
        "from": "2026-10-02",
        "to": "2026-10-02",
        "coverage_table_present": True,
        "days": [
            {
                "date": "2026-10-02",
                "activities": {
                    "status": "synced",
                    "stored_activities": 0,
                    "failed_activity_ids": [],
                    "source": "sync",
                    "command": "garmin activities",
                    "synced_at_utc": NOW,
                },
                "recovery": {
                    "status": "not_synced",
                    "missing_endpoints": [],
                    "source": None,
                    "command": None,
                    "synced_at_utc": None,
                },
            }
        ],
    }
    assert document == json.dumps(expected, indent=2) + "\n"
    assert _ok(capsys, "garmin", "coverage", "--from", "2026-10-01", "--to", "2026-10-05") == text  # deterministic


def test_dates_after_today_and_failed_activities(
    home: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _use(monkeypatch, _week_account(fail_activity_ids=frozenset({"222"})))
    _ok(capsys, "garmin", "activities", "--from", "2026-10-03", "--to", "2026-10-07")

    lines = _ok(capsys, "garmin", "coverage", "--from", "2026-10-03", "--to", "2026-10-07").splitlines()

    assert lines[2:7] == [
        "2026-10-03  failed (1 failed, 0 stored)   not synced",
        "2026-10-04  synced (0 stored)             not synced",
        "2026-10-05  synced (1 stored)             not synced",
        "2026-10-06  not synced                    not synced",  # after today: never recorded as synced
        "2026-10-07  not synced                    not synced",
    ]
    assert ("activities", "2026-10-03", "failed", "sync", "garmin activities", None, "222", NOW) in _coverage_rows(home)


class _LatestAccount(FakeGarmin):
    def latest_summary(self) -> dict[str, Any]:
        return summary(500, "running", "2026-10-05", "07:00:00")


def test_garmin_latest_records_no_coverage(
    home: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _use(monkeypatch, _LatestAccount([]))

    _ok(capsys, "garmin", "latest")

    assert _count(home, "activities") == 1
    assert _coverage_rows(home) == []  # a latest-activity sync covers no date range


# --- AC2 ---------------------------------------------------------------------------------------


def test_discovery_failure_records_nothing(
    home: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _use(monkeypatch, _week_account(list_error=GarminConnectorError("activity list unavailable")))

    code, _out, err = _run(capsys, "garmin", "activities", "--from", "2026-10-01", "--to", "2026-10-05")

    assert code == 1 and err == "오류: activity list unavailable\n"
    assert _coverage_rows(home) == []


def test_page_limit_records_nothing(
    home: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(ingest_range, "_MAX_PAGES", 1)
    _use(monkeypatch, FakeGarmin([summary(500, "running", "2026-10-05", "07:00:00")]))

    out = _ok(capsys, "garmin", "activities", "--from", "2026-10-01", "--to", "2026-10-05")

    assert "페이지 조회 한도" in out
    assert _coverage_rows(home) == []


def test_an_undated_list_entry_records_nothing(
    home: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    undated = {"activityId": 600, "activityType": {"typeKey": "running"}}
    _use(monkeypatch, FakeGarmin([summary(500, "running", "2026-10-05", "07:00:00"), undated]))

    out = _ok(capsys, "garmin", "activities", "--from", "2026-10-01", "--to", "2026-10-05")

    assert "시작 시각 확인 불가로 제외: 1건" in out
    assert _coverage_rows(home) == []


def test_daily_discovery_failure_records_recovery_only(
    home: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _use(monkeypatch, _week_account(list_error=GarminConnectorError("activity list unavailable")))

    code, _out, _err = _run(capsys, "daily")

    assert code == 1
    assert [row[:3] for row in _coverage_rows(home)] == [
        ("recovery", "2026-10-04", "partial"),
        ("recovery", "2026-10-05", "partial"),
    ]


def test_daily_page_limit_records_no_activity_coverage(
    home: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(ingest_range, "_MAX_PAGES", 1)
    _use(
        monkeypatch, FakeGarmin([summary(500, "running", "2026-10-05", "07:00:00")], recovery_kinds=ALL_RECOVERY_KINDS)
    )

    code, _out, _err = _run(capsys, "daily")

    assert code == 1  # the activities stage fails on the page limit, as before
    assert {row[0] for row in _coverage_rows(home)} == {"recovery"}


def test_daily_records_both_kinds_for_yesterday_and_today(
    home: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _use(monkeypatch, _week_account(recovery_kinds=ALL_RECOVERY_KINDS))

    _ok(capsys, "daily", "--json")

    assert [row[:5] for row in _coverage_rows(home)] == [
        ("activities", "2026-10-04", "synced", "sync", "daily"),
        ("activities", "2026-10-05", "synced", "sync", "daily"),
        ("recovery", "2026-10-04", "synced", "sync", "daily"),
        ("recovery", "2026-10-05", "synced", "sync", "daily"),
    ]


# --- AC3 ---------------------------------------------------------------------------------------


def test_recovery_range_records_synced_partial_failed_and_leaves_unattempted_dates_unrecorded(
    home: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    partial_kinds = tuple(kind for kind in ALL_RECOVERY_KINDS if kind not in ("hrv", "stress"))
    _use(
        monkeypatch,
        FakeGarmin(
            [],
            recovery_kinds=ALL_RECOVERY_KINDS,
            recovery_kinds_by_date={"2026-10-02": partial_kinds},
            recovery_failures={
                "2026-10-03": GarminConnectorError("Garmin recovery 원본을 하나도 가져오지 못했습니다."),
                "2026-10-04": AUTH_FAILURE,
            },
        ),
    )

    code, _out, _err = _run(capsys, "garmin", "recovery", "--from", "2026-10-01", "--to", "2026-10-05")

    assert code == 1  # unchanged: the range is incomplete
    document = _coverage_json(capsys, "2026-10-01", "2026-10-05")
    assert _statuses(document, "recovery") == {
        "2026-10-01": "synced",
        "2026-10-02": "partial",
        "2026-10-03": "failed",
        "2026-10-04": "not_synced",  # authentication failure: never really attempted
        "2026-10-05": "not_synced",  # not attempted after the abort
    }
    assert document["days"][1]["recovery"]["missing_endpoints"] == ["hrv", "stress"]
    lines = _ok(capsys, "garmin", "coverage", "--from", "2026-10-01", "--to", "2026-10-03").splitlines()
    assert [line[42:] for line in lines[2:5]] == ["synced", "partial (2 endpoints failed)", "failed"]
    assert lines[5].endswith("recovery: synced 1, partial 1, failed 1, not synced 0")


def test_single_date_recovery_records_its_result(
    home: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _use(monkeypatch, FakeGarmin([], recovery_kinds_by_date={"2026-10-01": ALL_RECOVERY_KINDS}))
    _ok(capsys, "garmin", "recovery", "2026-10-01")
    _ok(capsys, "garmin", "recovery", "2026-10-02")  # the default three kinds: six endpoints missing
    _ok(capsys, "garmin", "recovery", "2026-10-06")  # after today: synced, but its coverage is not recorded

    rows = _coverage_rows(home)

    missing = "resting_heart_rate,body_battery,stress,training_readiness,training_status,respiration"
    assert rows == [
        ("recovery", "2026-10-01", "synced", "sync", "garmin recovery", None, None, NOW),
        ("recovery", "2026-10-02", "partial", "sync", "garmin recovery", missing, None, NOW),
    ]


def test_single_date_recovery_failure_is_recorded_and_the_error_is_unchanged(
    home: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    message = "Garmin recovery 원본을 하나도 가져오지 못했습니다."
    _use(monkeypatch, FakeGarmin([], recovery_failures={"2026-10-01": GarminConnectorError(message)}))

    code, out, err = _run(capsys, "garmin", "recovery", "2026-10-01")

    assert (code, out, err) == (1, "", f"오류: {message}\n")
    assert _coverage_rows(home) == [("recovery", "2026-10-01", "failed", "sync", "garmin recovery", None, None, NOW)]


def test_single_date_authentication_failure_records_nothing(
    home: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _use(monkeypatch, FakeGarmin([], recovery_failures={"2026-10-01": AUTH_FAILURE}))

    code, _out, err = _run(capsys, "garmin", "recovery", "2026-10-01")

    assert (code, err) == (1, f"오류: {AUTH_FAILURE}\n")
    assert _coverage_rows(home) == []


# --- isolation: a failed coverage write never changes the sync ---------------------------------


@pytest.mark.parametrize(
    "argv",
    [
        ("garmin", "activities", "--from", "2026-10-01", "--to", "2026-10-05"),
        ("garmin", "recovery", "2026-10-03"),
        ("garmin", "recovery", "--from", "2026-10-03", "--to", "2026-10-05"),
    ],
)
def test_a_failed_coverage_write_keeps_the_sync_stdout_exit_code_and_data(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], argv: tuple[str, ...]
) -> None:
    results = {}
    for name in ("clean", "broken"):
        root = tmp_path / name
        monkeypatch.setenv("MUSCLE50_HOME", str(root))
        if name == "broken":
            _break_coverage(root)
        _use(monkeypatch, _week_account(recovery_kinds=ALL_RECOVERY_KINDS))
        results[name] = _run(capsys, *argv)
        assert _count(root, "activities") + _count(root, "daily_recovery") > 0

    clean_code, clean_out, clean_err = results["clean"]
    broken_code, broken_out, broken_err = results["broken"]
    assert (broken_code, broken_out) == (clean_code, clean_out) == (0, clean_out)
    assert broken_err == clean_err + WARNING
    assert _coverage_rows(tmp_path / "broken") == []
    assert _coverage_rows(tmp_path / "clean") != []
    for table in ("activities", "daily_recovery", "recovery_raw_captures"):
        assert _count(tmp_path / "broken", table) == _count(tmp_path / "clean", table)


# --- AC4: recovery backfill from stored RAW ----------------------------------------------------


def _pre_coverage_recovery(root: Path) -> Path:
    """Recovery rows saved the way syncs before this feature stored them (no coverage rows)."""
    path = _database(root)
    ActivityRepository(path).migrate()
    builders.save_recovery(path, "2026-09-01", ALL_RECOVERY_KINDS)
    builders.save_recovery(path, "2026-09-02", ("sleep", "daily_stats", "hrv"))
    builders.save_recovery(path, "2026-09-03", ALL_RECOVERY_KINDS)
    # 2026-09-03 already has a coverage row from a sync; the backfill must leave it alone.
    entry = SyncCoverageEntry(CoverageKind.RECOVERY, date(2026, 9, 3), CoverageStatus.FAILED)
    SqliteSyncCoverageRepository(path).record([entry], command="garmin recovery")
    return path


def _captured_at(path: Path, calendar_date: str) -> str:
    with sqlite3.connect(path) as connection:
        value: str = connection.execute(
            "SELECT captured_at_utc FROM recovery_raw_captures WHERE requested_date = ?", (calendar_date,)
        ).fetchone()[0]
    return value


def _files(root: Path) -> list[str]:
    return sorted(
        path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file() and "db" not in path.parts
    )


def test_recovery_backfill_dry_run_then_run_then_rerun(home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = _pre_coverage_recovery(home)
    before = _coverage_rows(home)
    files_before = _files(home)
    partial = "Partial: 2026-09-02 (missing: resting_heart_rate, body_battery, stress, training_readiness, "
    partial += "training_status, respiration)"

    dry_run = _ok(capsys, "garmin", "backfill-recovery-coverage", "--dry-run")

    assert dry_run.splitlines() == [
        "Recovery coverage backfill from stored RAW (dry run, nothing written)",
        "Recovery dates with an accepted RAW capture: 3",
        "Already recorded (left unchanged): 1",
        "Added as synced (backfilled from RAW): 1",
        "Added as partial (backfilled from RAW): 1",
        partial,
    ]
    assert _coverage_rows(home) == before

    run = _ok(capsys, "garmin", "backfill-recovery-coverage")

    assert run.splitlines() == [
        "Recovery coverage backfill from stored RAW complete",
        *dry_run.splitlines()[1:],
    ]
    command = "garmin backfill-recovery-coverage"
    missing = "resting_heart_rate,body_battery,stress,training_readiness,training_status,respiration"
    assert _coverage_rows(home) == [
        ("recovery", "2026-09-01", "synced", "raw_backfill", command, None, None, _captured_at(path, "2026-09-01")),
        ("recovery", "2026-09-02", "partial", "raw_backfill", command, missing, None, _captured_at(path, "2026-09-02")),
        ("recovery", "2026-09-03", "failed", "sync", "garmin recovery", None, None, NOW),
    ]
    assert _files(home) == files_before  # no RAW file read into a new snapshot or written

    again = _ok(capsys, "garmin", "backfill-recovery-coverage").splitlines()
    assert again[2:5] == [
        "Already recorded (left unchanged): 3",
        "Added as synced (backfilled from RAW): 0",
        "Added as partial (backfilled from RAW): 0",
    ]
    assert len(again) == 5

    lines = _ok(capsys, "garmin", "coverage", "--from", "2026-09-01", "--to", "2026-09-03").splitlines()
    assert [line[42:] for line in lines[2:5]] == [
        "synced (backfilled from RAW)",
        "partial (6 endpoints failed, backfilled from RAW)",
        "failed",
    ]
    assert lines[5].endswith("recovery: synced 1 (1 backfilled from RAW), partial 1, failed 1, not synced 0")
    document = _coverage_json(capsys, "2026-09-01", "2026-09-01")
    assert document["days"][0]["recovery"] == {
        "status": "synced",
        "missing_endpoints": [],
        "source": "raw_backfill",
        "command": command,
        "synced_at_utc": _captured_at(path, "2026-09-01"),
    }


def test_a_later_sync_replaces_a_backfilled_row(
    home: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _pre_coverage_recovery(home)
    _ok(capsys, "garmin", "backfill-recovery-coverage")
    _use(monkeypatch, FakeGarmin([], recovery_kinds=ALL_RECOVERY_KINDS))

    _ok(capsys, "garmin", "recovery", "2026-09-02")

    assert ("recovery", "2026-09-02", "synced", "sync", "garmin recovery", None, None, NOW) in _coverage_rows(home)


# --- refusals and read-only behaviour ----------------------------------------------------------


@pytest.mark.parametrize(
    ("argv", "message"),
    [
        (("--from", "2026-13-01", "--to", "2026-10-05"), "YYYY-MM-DD"),
        (("--from", "2026-10-05", "--to", "2026-10-01"), "이후일 수 없습니다"),
        (("--from", "2025-10-01", "--to", "2026-10-05"), "최대 366일"),
    ],
)
def test_invalid_coverage_requests_are_refused_before_the_database(
    home: Path, capsys: pytest.CaptureFixture[str], argv: tuple[str, ...], message: str
) -> None:
    code, out, err = _run(capsys, "garmin", "coverage", *argv)

    assert (code, out) == (1, "")
    assert err.startswith("오류:") and message in err
    assert not home.exists()


def test_coverage_without_a_database_is_an_error_and_creates_nothing(
    home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, _out, err = _run(capsys, "garmin", "coverage", "--from", "2026-10-01", "--to", "2026-10-05")

    assert code == 1 and err.startswith("오류:") and "not found" in err
    assert not home.exists()


def _file_state(path: Path) -> tuple[str, int]:
    return hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_mtime_ns


def test_coverage_never_writes(home: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    _use(monkeypatch, _week_account())
    _ok(capsys, "garmin", "activities", "--from", "2026-10-01", "--to", "2026-10-05")
    with sqlite3.connect(_database(home)) as connection:
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    before = _file_state(_database(home))
    entries = sorted(path.name for path in _database(home).parent.iterdir())

    _ok(capsys, "garmin", "coverage", "--from", "2026-10-01", "--to", "2026-10-05")
    _ok(capsys, "garmin", "coverage", "--from", "2026-10-01", "--to", "2026-10-05", "--json")

    assert _file_state(_database(home)) == before
    assert sorted(path.name for path in _database(home).parent.iterdir()) == entries
