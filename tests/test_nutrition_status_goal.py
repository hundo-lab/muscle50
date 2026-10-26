"""`nutrition status` with a training goal: cut reference lines (PRO-05, PRO-04), otherwise unchanged."""

from __future__ import annotations

import json
from datetime import date, timedelta, timezone
from pathlib import Path

import goal_mode_builders as goal
import pytest
from inbody_trend_builders import measurement, save_measurements

import muscle50.cli as cli
from muscle50.cli import main
from muscle50.infrastructure.garmin.client import PythonGarminConnector

KST = timezone(timedelta(hours=9))
STATUS = ("nutrition", "status", "--date", "2026-03-16")
REFERENCE = [
    "",
    "Cut goal reference (nutrition targets are not changed):",
    "  Protein [PRO-05]: 2.3-3.1 g/kg fat-free mass = 145-195 g/day",
    "    (fat-free mass = weight - body fat mass, InBody 2026-03-16 [design])",
    "  Energy deficit [PRO-04]: keep it at or under about 500 kcal/day; muscle50 cannot measure it "
    "(maintenance kcal unknown)",
]


@pytest.fixture(autouse=True)
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "home"
    monkeypatch.setenv("MUSCLE50_HOME", str(root))
    monkeypatch.setattr(
        PythonGarminConnector, "authenticate", lambda *args, **kwargs: pytest.fail("nutrition must not use Garmin")
    )
    monkeypatch.setattr(cli, "_local_timezone", lambda day: KST)
    monkeypatch.setattr(cli, "_today", lambda: date(2026, 10, 2))
    return root


def _ok(capsys: pytest.CaptureFixture[str], *argv: str) -> str:
    code = main(list(argv))
    captured = capsys.readouterr()
    assert code == 0, captured.err
    return captured.out


@pytest.fixture
def database(home: Path, capsys: pytest.CaptureFixture[str]) -> Path:
    _ok(capsys, "nutrition", "target", "set", "protein", "--range", "120", "140")  # creates and migrates the DB
    path = home / "db" / "muscle50.sqlite3"
    goal.add_inbody(path)
    return path


def test_no_goal_and_non_cut_goals_leave_the_status_unchanged(
    database: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    text, document = _ok(capsys, *STATUS), _ok(capsys, *STATUS, "--json")
    assert "goal" not in text.lower() and "goal_reference" not in document
    for argv in (goal.GAIN_GOAL, ("goal", "set", "--mode", "maintain")):
        _ok(capsys, *argv)
        assert (_ok(capsys, *STATUS), _ok(capsys, *STATUS, "--json")) == (text, document)
    _ok(capsys, *goal.CUT_GOAL)
    _ok(capsys, "goal", "unset")
    assert (_ok(capsys, *STATUS), _ok(capsys, *STATUS, "--json")) == (text, document)


def test_cut_appends_the_reference_lines_and_a_trailing_key(
    home: Path, database: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    targets = home / "config" / "nutrition_targets.json"
    targets_before = targets.read_bytes()
    text, document = _ok(capsys, *STATUS), json.loads(_ok(capsys, *STATUS, "--json"))
    _ok(capsys, *goal.CUT_GOAL)

    cut_text = _ok(capsys, *STATUS)
    output = _ok(capsys, *STATUS, "--json")
    assert _ok(capsys, *STATUS, "--json") == output  # deterministic
    assert cut_text == text.rstrip("\n") + "\n" + "\n".join(REFERENCE) + "\n"
    cut_document = json.loads(output)
    assert list(cut_document)[-1] == "goal_reference"
    reference = cut_document.pop("goal_reference")
    assert cut_document == document
    assert output == json.dumps({**document, "goal_reference": reference}, indent=2) + "\n"
    assert reference == {
        "goal_reference_version": 1,
        "status": "known",
        "mode": "cut",
        "protein": {
            "g_per_kg_fat_free_mass": {"minimum": "2.3", "maximum": "3.1"},
            "min_g": "145",
            "max_g": "195",
            "measurement_date": "2026-03-16",
            "evidence": ["PRO-05", "design"],
        },
        "energy_deficit": {"limit_kcal_per_day": 500, "measurable": False, "evidence": ["PRO-04"]},
        "targets_changed": False,
        "reason": None,
    }
    # D1: the fat-free mass itself (63.0 kg) and the measured values are not printed.
    for measured in ("63", "78", "15.0"):
        assert measured not in cut_text and f'"{measured}' not in output
    assert targets.read_bytes() == targets_before  # targets are never changed
    assert cut_text.isascii()


def test_missing_body_fat_mass_gives_unknown_protein(home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _ok(capsys, "nutrition", "target", "show")
    save_measurements(
        home / "db" / "muscle50.sqlite3", (measurement("only", "2026-03-16T07:00:00+09:00", weight=78.0),)
    )
    _ok(capsys, *goal.CUT_GOAL)
    lines = _ok(capsys, *STATUS).split("\n")
    assert (
        "  Protein [PRO-05]: 2.3-3.1 g/kg fat-free mass = unknown (no InBody date with both weight and body fat "
        "mass on or before this date)" in lines
    )
    reference = json.loads(_ok(capsys, *STATUS, "--json"))["goal_reference"]
    assert (reference["status"], reference["protein"]["min_g"]) == ("unknown", None)


def test_a_corrupt_goal_file_degrades_to_one_line(
    home: Path, database: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    text = _ok(capsys, *STATUS)
    path = home / "config" / "training_goal.json"
    path.write_text('{"schema_version": 1, "goal": {"mode": "secret"}}', encoding="utf-8")

    degraded = _ok(capsys, *STATUS)
    lines = degraded.split("\n")
    assert "\n".join(lines[:-3]) + "\n" == text
    assert lines[-3] == ""
    assert lines[-2].startswith("Goal reference: unavailable (training goal file ")
    assert lines[-2].endswith("); nutrition targets are not changed.")
    assert "secret" not in degraded
    reference = json.loads(_ok(capsys, *STATUS, "--json"))["goal_reference"]
    assert (reference["status"], reference["protein"], reference["energy_deficit"]) == ("unavailable", None, None)
