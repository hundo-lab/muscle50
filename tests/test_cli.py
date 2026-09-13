from __future__ import annotations

import pytest

from muscle50.cli import build_parser, main


def test_cli_parses_garmin_latest() -> None:
    args = build_parser().parse_args(["garmin", "latest"])

    assert args.command == "garmin"
    assert args.garmin_command == "latest"


def test_cli_reports_safe_configuration_error(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("MUSCLE50_HOME", raising=False)
    monkeypatch.delenv("LOCALAPPDATA", raising=False)

    exit_code = main(["garmin", "latest"])

    assert exit_code == 1
    assert "LOCALAPPDATA" in capsys.readouterr().err
