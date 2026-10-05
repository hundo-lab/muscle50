"""recommend/daily output against goldens captured from main before Sync Coverage v1 (AC5-AC7)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import sync_coverage_builders as builders

import muscle50.cli as cli
from muscle50.cli import main
from muscle50.infrastructure.garmin.client import PythonGarminConnector


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


def test_daily_equals_the_golden(
    home: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _use(monkeypatch, builders.daily_account())
    assert _out(capsys, "daily") == builders.golden("daily_2026-10-02.txt")


def test_daily_json_equals_the_golden(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("MUSCLE50_HOME", str(tmp_path / "json-home"))
    monkeypatch.setattr(cli, "_local_timezone", lambda day: builders.KST)
    monkeypatch.setattr(cli, "_today", lambda: builders.DAILY_TODAY)
    _use(monkeypatch, builders.daily_account())
    assert _out(capsys, "daily", "--json") == builders.golden("daily_2026-10-02.json")
