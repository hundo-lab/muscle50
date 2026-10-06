"""`muscle50 inbody trend` end to end, plus the neighbour outputs it must leave byte-identical (AC9)."""

from __future__ import annotations

from pathlib import Path

import inbody_trend_builders as inbody
import pytest
import sync_coverage_builders as builders

import muscle50.cli as cli
from muscle50.cli import main
from muscle50.infrastructure.garmin.client import PythonGarminConnector

SAMSUNG_FIXTURE = Path(__file__).parent / "fixtures" / "inbody" / "synthetic_samsung_health_export_v1.json"


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "home"
    monkeypatch.setenv("MUSCLE50_HOME", str(root))
    monkeypatch.setattr(
        PythonGarminConnector, "authenticate", lambda *args, **kwargs: pytest.fail("must not use Garmin")
    )
    monkeypatch.setattr(cli, "_local_timezone", lambda day: builders.KST)
    monkeypatch.setattr(cli, "_today", lambda: builders.DAILY_TODAY)
    return root


def _out(capsys: pytest.CaptureFixture[str], *argv: str) -> str:
    code = main(list(argv))
    captured = capsys.readouterr()
    assert code == 0, captured.err
    assert captured.err == ""
    return captured.out


# --- AC9: neighbours stay byte-identical (goldens captured before this feature) ---------------


@pytest.mark.parametrize(
    ("flags", "name"), [((), "inbody_sync.txt"), (("--show-values",), "inbody_sync_show_values.txt")]
)
def test_inbody_sync_output_equals_the_golden(
    home: Path, capsys: pytest.CaptureFixture[str], flags: tuple[str, ...], name: str
) -> None:
    assert _out(capsys, "inbody", "sync", "--file", str(SAMSUNG_FIXTURE), *flags) == inbody.golden(name)


def test_recommend_and_analytics_ignore_inbody_rows(home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    database = builders.build_recommend_database(home)
    inbody.save_measurements(database, inbody.NEIGHBOUR_ROWS)

    text = _out(capsys, "recommend", "--date", builders.RECOMMEND_DATE)
    document = _out(capsys, "recommend", "--date", builders.RECOMMEND_DATE, "--json")
    snapshot = _out(capsys, "analytics", "snapshot", "--date", builders.RECOMMEND_DATE, "--json")

    assert text == builders.golden(f"recommend_{builders.RECOMMEND_DATE}.txt")
    assert document == builders.golden(f"recommend_{builders.RECOMMEND_DATE}.json")
    assert snapshot == inbody.golden(f"analytics_snapshot_{builders.RECOMMEND_DATE}.json")
