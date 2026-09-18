from __future__ import annotations

import pytest

from muscle50.cli import build_parser, main
from muscle50.infrastructure.garmin.client import PythonGarminConnector


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
