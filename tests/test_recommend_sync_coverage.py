"""recommend/daily output against goldens captured from main before Sync Coverage v1 (AC5-AC7)."""

from __future__ import annotations

import copy
import hashlib
import json
import sqlite3
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pytest
import sync_coverage_builders as builders

import muscle50.cli as cli
from muscle50.cli import main
from muscle50.domain.sync_coverage import (
    CoverageKind,
    CoverageSource,
    CoverageStatus,
    RecordedCoverage,
    SyncCoverageEntry,
)
from muscle50.infrastructure.garmin.client import PythonGarminConnector
from muscle50.infrastructure.sqlite.database import ActivityRepository
from muscle50.infrastructure.sqlite.sync_coverage import SqliteSyncCoverageRepository

ACT = CoverageKind.ACTIVITIES
REC = CoverageKind.RECOVERY
MIGRATIONS_DIR = Path(__file__).parents[1] / "src" / "muscle50" / "infrastructure" / "sqlite" / "migrations"


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "home"
    monkeypatch.setenv("MUSCLE50_HOME", str(root))
    monkeypatch.setattr(cli, "_local_timezone", lambda day: builders.KST)
    monkeypatch.setattr(cli, "_today", lambda: builders.DAILY_TODAY)
    return root


def _no_garmin(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        PythonGarminConnector, "authenticate", lambda *args, **kwargs: pytest.fail("must not use Garmin")
    )


def _use(monkeypatch: pytest.MonkeyPatch, garmin: builders.FakeGarmin) -> None:
    def authenticate(auth_dir: Path, **_kwargs: Any) -> builders.FakeGarmin:
        return garmin

    monkeypatch.setattr(PythonGarminConnector, "authenticate", authenticate)


def _out(capsys: pytest.CaptureFixture[str], *argv: str) -> str:
    code = main(list(argv))
    captured = capsys.readouterr()
    assert code == 0, captured.err
    return captured.out


@pytest.mark.parametrize("targets", [False, True])
def test_recommend_without_coverage_rows_equals_the_golden(
    home: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], targets: bool
) -> None:
    builders.build_recommend_database(home)
    _no_garmin(monkeypatch)
    if targets:
        for argv in builders.TARGET_COMMANDS:
            _out(capsys, *argv)
    suffix = "_targets" if targets else ""

    text = _out(capsys, "recommend", "--date", builders.RECOMMEND_DATE)
    document = _out(capsys, "recommend", "--date", builders.RECOMMEND_DATE, "--json")

    assert text == builders.golden(f"recommend_{builders.RECOMMEND_DATE}{suffix}.txt")
    assert document == builders.golden(f"recommend_{builders.RECOMMEND_DATE}{suffix}.json")


def _without_coverage(document: dict[str, Any]) -> dict[str, Any]:
    """The document as it was before Sync Coverage v1: no trailing key, recorded flag false."""
    stripped = copy.deepcopy(document)
    freshness = stripped["data_freshness"]
    del freshness["sync_coverage"]
    freshness["sync_coverage_recorded"] = False
    return stripped


def _record(database: Path, *entries: SyncCoverageEntry) -> None:
    SqliteSyncCoverageRepository(database).record(entries, command="daily")


def _recommend_rows(database: Path) -> None:
    _record(
        database,
        SyncCoverageEntry(ACT, date(2026, 3, 12), CoverageStatus.FAILED, failed_activity_ids=("8999",)),
        SyncCoverageEntry(ACT, date(2026, 3, 15), CoverageStatus.SYNCED),
        SyncCoverageEntry(ACT, date(2026, 3, 16), CoverageStatus.SYNCED),
        SyncCoverageEntry(REC, date(2026, 3, 16), CoverageStatus.PARTIAL, missing_endpoints=("hrv",)),
    )
    SqliteSyncCoverageRepository(database).insert_backfill(
        [
            RecordedCoverage(
                SyncCoverageEntry(REC, date(2026, 3, 15), CoverageStatus.SYNCED, CoverageSource.RAW_BACKFILL),
                "garmin backfill-recovery-coverage",
                "2026-03-15T23:00:00.000000+00:00",
            )
        ]
    )


RECOMMEND_LINES = [
    "  sync coverage 2026-02-16..2026-03-16: activities synced 2, failed 1, not synced 26 days; "
    "recovery synced 1 (1 backfilled from RAW), partial 1, failed 0, not synced 27 days",
    "  days with no stored activity: synced, no activity: 2026-03-15; sync failed: 2026-03-12; "
    "not synced: 2026-02-16..2026-03-09, 2026-03-11, 2026-03-14",
]
STATEMENT = "  sync completeness is not recorded: "


def _insert_after(text: str, starts_with: str, lines: list[str]) -> str:
    """The golden text with ``lines`` inserted after the one line starting with ``starts_with``."""
    golden_lines = text.split("\n")
    (index,) = [number for number, line in enumerate(golden_lines) if line.startswith(starts_with)]
    return "\n".join(golden_lines[: index + 1] + lines + golden_lines[index + 1 :])


def test_recommend_with_coverage_adds_only_two_lines_and_a_trailing_key(
    home: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _recommend_rows(builders.build_recommend_database(home))
    _no_garmin(monkeypatch)

    text = _out(capsys, "recommend", "--date", builders.RECOMMEND_DATE)
    output = _out(capsys, "recommend", "--date", builders.RECOMMEND_DATE, "--json")

    golden_text = builders.golden(f"recommend_{builders.RECOMMEND_DATE}.txt")
    golden_json = builders.golden(f"recommend_{builders.RECOMMEND_DATE}.json")
    assert text == _insert_after(golden_text, STATEMENT, RECOMMEND_LINES)
    assert text.isascii() and output.isascii()
    document = json.loads(output)
    assert list(document["data_freshness"])[-1] == "sync_coverage"
    assert document["data_freshness"]["sync_coverage_recorded"] is True
    assert json.dumps(_without_coverage(document), indent=2) + "\n" == golden_json
    window = document["data_freshness"]["sync_coverage"]
    assert (window["from"], window["to"], len(window["days"])) == ("2026-02-16", "2026-03-16", 29)
    assert window["days"][-2:] == [
        {
            "date": "2026-03-15",
            "activities": "synced",
            "stored_activities": 0,
            "recovery": "synced",
            "recovery_source": "raw_backfill",
        },
        {
            "date": "2026-03-16",
            "activities": "synced",
            "stored_activities": 2,
            "recovery": "partial",
            "recovery_source": "sync",
        },
    ]
    assert window["days"][0] == {
        "date": "2026-02-16",
        "activities": "not_synced",
        "stored_activities": 0,
        "recovery": "not_synced",
        "recovery_source": None,
    }
    assert _out(capsys, "recommend", "--date", builders.RECOMMEND_DATE, "--json") == output  # deterministic


def test_coverage_outside_the_window_leaves_recommend_byte_identical(
    home: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    database = builders.build_recommend_database(home)
    _record(
        database,
        SyncCoverageEntry(ACT, date(2026, 2, 15), CoverageStatus.SYNCED),  # the day before history_start
        SyncCoverageEntry(REC, date(2026, 3, 17), CoverageStatus.SYNCED),  # the day after the plan date
    )
    _no_garmin(monkeypatch)

    assert _out(capsys, "recommend", "--date", builders.RECOMMEND_DATE) == builders.golden(
        f"recommend_{builders.RECOMMEND_DATE}.txt"
    )
    assert _out(capsys, "recommend", "--date", builders.RECOMMEND_DATE, "--json") == builders.golden(
        f"recommend_{builders.RECOMMEND_DATE}.json"
    )


def test_coverage_never_changes_the_plan(
    home: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # AC7: rows that say "synced, no activity" and "failed" next to the plan date change no decision.
    _recommend_rows(builders.build_recommend_database(home))
    _no_garmin(monkeypatch)

    document = json.loads(_out(capsys, "recommend", "--date", builders.RECOMMEND_DATE, "--json"))

    golden = json.loads(builders.golden(f"recommend_{builders.RECOMMEND_DATE}.json"))
    for key in ("strength", "swimming", "recovery", "notices", "excluded_same_day_strength_ids", "goals"):
        assert document[key] == golden[key], key
    assert document["data_freshness"]["statement"] == golden["data_freshness"]["statement"]  # D5: unchanged text


def _migrated_without_coverage(root: Path) -> Path:
    """A database built from every migration file except 010, as before this feature."""
    path = root / "db" / "muscle50.sqlite3"
    path.parent.mkdir(parents=True)
    connection = sqlite3.connect(path)
    try:
        for migration in sorted(MIGRATIONS_DIR.glob("*.sql")):
            if migration.name != "010_sync_coverage.sql":
                connection.executescript(migration.read_text(encoding="utf-8"))
    finally:
        connection.close()
    builders.fill_recommend_database(path)
    return path


def test_read_only_commands_work_on_a_database_from_before_migration_10(
    home: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    database = _migrated_without_coverage(home)
    _no_garmin(monkeypatch)
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    before = hashlib.sha256(database.read_bytes()).hexdigest(), database.stat().st_mtime_ns

    text = _out(capsys, "recommend", "--date", builders.RECOMMEND_DATE)
    document = _out(capsys, "recommend", "--date", builders.RECOMMEND_DATE, "--json")
    coverage = _out(capsys, "garmin", "coverage", "--from", "2026-03-15", "--to", "2026-03-16")
    coverage_json = json.loads(
        _out(capsys, "garmin", "coverage", "--from", "2026-03-15", "--to", "2026-03-16", "--json")
    )

    assert text == builders.golden(f"recommend_{builders.RECOMMEND_DATE}.txt")
    assert document == builders.golden(f"recommend_{builders.RECOMMEND_DATE}.json")
    assert coverage.splitlines()[2:] == [
        "2026-03-15  not synced                    not synced",
        "2026-03-16  not synced (2 stored)         not synced",
        "activities: synced 0, failed 0, not synced 2; recovery: synced 0, partial 0, failed 0, not synced 2",
        "Recorded by: garmin activities --from/--to, garmin recovery, daily. Not recorded: garmin latest, "
        "garmin refresh.",
        "Sync coverage is not recorded in this database yet (the next Garmin sync command creates it).",
    ]
    assert coverage_json["coverage_table_present"] is False
    assert (hashlib.sha256(database.read_bytes()).hexdigest(), database.stat().st_mtime_ns) == before
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT name FROM sqlite_master WHERE name = 'sync_coverage'").fetchone() is None


DAILY_LINES = [
    "  sync coverage 2026-09-04..2026-10-02: activities synced 2, failed 0, not synced 27 days; "
    "recovery synced 0, partial 2, failed 0, not synced 27 days",
    "  days with no stored activity: synced, no activity: none; sync failed: none; not synced: 2026-09-04..2026-09-30",
]
COVERAGE_WARNING = "sync coverage를 기록하지 못했습니다 (동기화된 데이터는 저장됨): synthetic coverage failure"


def _daily(root: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], *argv: str) -> str:
    monkeypatch.setenv("MUSCLE50_HOME", str(root))
    _use(monkeypatch, builders.daily_account())
    return _out(capsys, "daily", *argv)


def _break_coverage(root: Path) -> None:
    database = root / "db" / "muscle50.sqlite3"
    ActivityRepository(database).migrate()
    with sqlite3.connect(database) as connection:
        connection.execute(
            "CREATE TRIGGER fail_coverage BEFORE INSERT ON sync_coverage "
            "BEGIN SELECT RAISE(ABORT, 'synthetic coverage failure'); END"
        )


def test_daily_adds_only_the_coverage_lines_and_key(
    tmp_path: Path, home: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # AC5(c): a normal daily records coverage before planning, so its plan shows it.
    text = _daily(tmp_path / "text", monkeypatch, capsys)
    output = _daily(tmp_path / "json", monkeypatch, capsys, "--json")

    assert text == _insert_after(builders.golden("daily_2026-10-02.txt"), STATEMENT, DAILY_LINES)
    expected = json.loads(builders.golden("daily_2026-10-02.json"))
    freshness = expected["recommendation"]["data_freshness"]
    freshness["sync_coverage_recorded"] = True
    synced = date(2026, 10, 1)
    freshness["sync_coverage"] = {
        "from": "2026-09-04",
        "to": "2026-10-02",
        "days": [
            {
                "date": day.isoformat(),
                "activities": "synced" if day >= synced else "not_synced",
                "stored_activities": 1 if day >= synced else 0,
                "recovery": "partial" if day >= synced else "not_synced",
                "recovery_source": "sync" if day >= synced else None,
            }
            for day in (date(2026, 9, 4) + timedelta(days=offset) for offset in range(29))
        ],
    }
    assert output == json.dumps(expected, indent=2) + "\n"


def test_daily_with_a_failed_coverage_write_equals_the_golden_plus_two_stage_warnings(
    tmp_path: Path, home: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # AC5(b): no row was written, so the plan is exactly the golden; only the warnings are added.
    for name in ("text", "json"):
        _break_coverage(tmp_path / name)

    text = _daily(tmp_path / "text", monkeypatch, capsys)
    output = _daily(tmp_path / "json", monkeypatch, capsys, "--json")

    warning = [f"    warning: {COVERAGE_WARNING}"]
    expected_text = _insert_after(builders.golden("daily_2026-10-02.txt"), "  activities: ok", warning)
    expected_text = _insert_after(expected_text, "  recovery: ok", warning)
    assert text == expected_text
    expected = json.loads(builders.golden("daily_2026-10-02.json"))
    for stage in expected["stages"]:
        if stage["stage"] in ("activities", "recovery"):
            stage["warnings"].append(COVERAGE_WARNING)
    assert output == json.dumps(expected, indent=2) + "\n"
