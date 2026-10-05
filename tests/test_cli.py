from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from muscle50.cli import build_parser, main
from muscle50.infrastructure.garmin.client import PythonGarminConnector

SAMSUNG_FIXTURE = Path(__file__).parent / "fixtures" / "inbody" / "synthetic_samsung_health_export_v1.json"


def test_cli_parses_garmin_latest() -> None:
    args = build_parser().parse_args(["garmin", "latest"])

    assert args.command == "garmin"
    assert args.garmin_command == "latest"


def test_cli_parses_garmin_activities_range() -> None:
    args = build_parser().parse_args(["garmin", "activities", "--from", "2026-01-01", "--to", "2026-01-31"])

    assert args.command == "garmin"
    assert args.garmin_command == "activities"
    assert args.from_date == "2026-01-01"
    assert args.to_date == "2026-01-31"


def test_cli_garmin_activities_requires_from_and_to() -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args(["garmin", "activities", "--from", "2026-01-01"])


def test_cli_rejects_malformed_activities_date_before_authentication(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        PythonGarminConnector,
        "authenticate",
        lambda auth_dir: pytest.fail("authentication must not be attempted"),
    )

    exit_code = main(["garmin", "activities", "--from", "not-a-date", "--to", "2026-01-31"])

    assert exit_code == 1
    assert "YYYY-MM-DD" in capsys.readouterr().err


def test_cli_rejects_from_after_to_before_authentication(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        PythonGarminConnector,
        "authenticate",
        lambda auth_dir: pytest.fail("authentication must not be attempted"),
    )

    exit_code = main(["garmin", "activities", "--from", "2026-02-01", "--to", "2026-01-01"])

    assert exit_code == 1
    assert capsys.readouterr().err


def test_cli_parses_garmin_recovery_date() -> None:
    args = build_parser().parse_args(["garmin", "recovery", "2026-09-15"])

    assert args.command == "garmin"
    assert args.garmin_command == "recovery"
    assert args.date == "2026-09-15"


def test_cli_parses_garmin_refresh_activity_id() -> None:
    args = build_parser().parse_args(["garmin", "refresh", "24481518495"])

    assert args.command == "garmin"
    assert args.garmin_command == "refresh"
    assert args.activity_id == "24481518495"


def test_cli_rejects_invalid_refresh_id_before_authentication(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        PythonGarminConnector,
        "authenticate",
        lambda auth_dir: pytest.fail("authentication must not be attempted"),
    )

    exit_code = main(["garmin", "refresh", "not-an-id"])

    assert exit_code == 1
    assert "activityId" in capsys.readouterr().err


def test_cli_rejects_unknown_local_refresh_id_before_authentication(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("MUSCLE50_HOME", str(tmp_path / "private-muscle50"))
    monkeypatch.setattr(
        PythonGarminConnector,
        "authenticate",
        lambda auth_dir: pytest.fail("authentication must not be attempted"),
    )

    exit_code = main(["garmin", "refresh", "24481518495"])

    assert exit_code == 1
    assert "local Garmin activity not found" in capsys.readouterr().err


def test_cli_parses_inbody_sync_file() -> None:
    args = build_parser().parse_args(["inbody", "sync", "--file", "export.json"])

    assert args.command == "inbody"
    assert args.inbody_command == "sync"
    assert args.file == Path("export.json")
    assert args.show_values is False


def test_cli_rejects_invalid_recovery_date_before_authentication(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        PythonGarminConnector,
        "authenticate",
        lambda auth_dir: pytest.fail("authentication must not be attempted"),
    )

    exit_code = main(["garmin", "recovery", "invalid"])

    assert exit_code == 1
    assert "YYYY-MM-DD" in capsys.readouterr().err


def test_cli_reports_safe_configuration_error(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("MUSCLE50_HOME", raising=False)
    monkeypatch.delenv("LOCALAPPDATA", raising=False)

    exit_code = main(["garmin", "latest"])

    assert exit_code == 1
    assert "LOCALAPPDATA" in capsys.readouterr().err


def test_cli_inbody_sync_is_private_idempotent_and_uses_shared_database(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    payload = SAMSUNG_FIXTURE
    muscle50_home = tmp_path / "muscle50-home"
    monkeypatch.setenv("MUSCLE50_HOME", str(muscle50_home))

    assert main(["inbody", "sync", "--file", str(payload)]) == 0
    first = capsys.readouterr()
    assert "Source: Samsung Health / InBody" in first.out
    assert "Records discovered: 1" in first.out
    assert "Inserted: 1" in first.out
    assert "70.0" not in first.out + first.err

    assert main(["inbody", "sync", "--file", str(payload)]) == 0
    second = capsys.readouterr()
    assert "Inserted: 0" in second.out
    assert "Already existing: 1" in second.out
    assert "Changed RAW conflicts: 0" in second.out

    database_path = muscle50_home / "db" / "muscle50.sqlite3"
    with sqlite3.connect(database_path) as connection:
        measurement_count = connection.execute("SELECT COUNT(*) FROM body_composition_measurements").fetchone()[0]
        detail_raw_count = connection.execute("SELECT COUNT(*) FROM inbody_raw_artifacts").fetchone()[0]
        migration_versions = connection.execute(
            "SELECT version FROM schema_migrations ORDER BY version"
        ).fetchall()
    raw_json_count = len(list((muscle50_home / "raw" / "inbody" / "samsung_health").rglob("*.json")))

    assert measurement_count == 1
    assert detail_raw_count == 1
    assert raw_json_count == 2
    assert migration_versions == [(1,), (2,), (3,), (4,), (5,), (6,), (7,), (8,), (9,), (10,)]


def test_cli_inbody_show_values_requires_explicit_option(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    payload = SAMSUNG_FIXTURE
    monkeypatch.setenv("MUSCLE50_HOME", str(tmp_path / "muscle50-home"))

    assert main(["inbody", "sync", "--file", str(payload), "--show-values"]) == 0

    assert "weight_kg=70.0" in capsys.readouterr().out
