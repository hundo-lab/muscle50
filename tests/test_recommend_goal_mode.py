"""recommend/daily with a training goal (AC2-AC6, AC8): goldens without a goal, additive changes with one."""

from __future__ import annotations

import copy
import json
import sqlite3
from pathlib import Path
from typing import Any

import goal_mode_builders as goal
import inbody_trend_builders as inbody
import pytest
import sync_coverage_builders as builders

import muscle50.cli as cli
from muscle50.cli import main
from muscle50.infrastructure.garmin.client import PythonGarminConnector

MIGRATIONS_DIR = Path(__file__).parents[1] / "src" / "muscle50" / "infrastructure" / "sqlite" / "migrations"
RECOMMEND = ("recommend", "--date", builders.RECOMMEND_DATE)
FRESHNESS = "== Data freshness =="


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


def _run(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, str, str]:
    code = main(list(argv))
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def _out(capsys: pytest.CaptureFixture[str], *argv: str) -> str:
    code, out, err = _run(capsys, *argv)
    assert code == 0, err
    return out


def _without_goal_section(text: str) -> str:
    """The text with the goal section (and the blank line before it) removed."""
    lines = text.split("\n")
    start = next(index for index, line in enumerate(lines) if line.startswith("== Goal: "))
    end = lines.index(FRESHNESS)
    assert lines[start - 1] == "" and lines[end - 1] == ""
    return "\n".join(lines[: start - 1] + lines[end - 1 :])


def _goal_section(text: str) -> list[str]:
    lines = text.split("\n")
    start = next(index for index, line in enumerate(lines) if line.startswith("== Goal: "))
    return lines[start : lines.index(FRESHNESS) - 1]


# --- AC2: no goal -> byte-identical ------------------------------------------------------------


@pytest.mark.parametrize("sleep_file", [False, True])
def test_without_a_goal_recommend_equals_the_goldens(
    home: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], sleep_file: bool
) -> None:
    database = builders.build_recommend_database(home)
    goal.add_inbody(database)  # InBody rows alone change nothing
    _no_garmin(monkeypatch)
    if sleep_file:
        # A sleep thresholds file equal to the defaults is behaviour-identical.
        _out(capsys, "settings", "sleep", "set", "--hold-below-hours", "5", "--reduce-below-hours", "4")
    assert _out(capsys, *RECOMMEND) == builders.golden(f"recommend_{builders.RECOMMEND_DATE}.txt")
    assert _out(capsys, *RECOMMEND, "--json") == builders.golden(f"recommend_{builders.RECOMMEND_DATE}.json")
    for argv in builders.TARGET_COMMANDS:
        _out(capsys, *argv)
    assert _out(capsys, *RECOMMEND) == builders.golden(f"recommend_{builders.RECOMMEND_DATE}_targets.txt")
    assert _out(capsys, *RECOMMEND, "--json") == builders.golden(f"recommend_{builders.RECOMMEND_DATE}_targets.json")


def test_analytics_snapshot_ignores_a_goal(
    home: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    database = builders.build_recommend_database(home)
    inbody.save_measurements(database, inbody.NEIGHBOUR_ROWS)
    _no_garmin(monkeypatch)
    _out(capsys, *goal.CUT_GOAL)
    _out(capsys, "settings", "sleep", "set", "--hold-below-hours", "6")
    snapshot = _out(capsys, "analytics", "snapshot", "--date", builders.RECOMMEND_DATE, "--json")
    assert snapshot == inbody.golden(f"analytics_snapshot_{builders.RECOMMEND_DATE}.json")


def test_without_a_goal_daily_is_unchanged_by_a_default_sleep_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # The no-file daily output is pinned against its golden by test_recommend_sync_coverage.py;
    # a sleep file equal to the defaults must give the same bytes.
    outputs = []
    for name, sleep_file in (("plain", False), ("sleep", True)):
        monkeypatch.setenv("MUSCLE50_HOME", str(tmp_path / name))
        _use(monkeypatch, builders.daily_account())
        if sleep_file:
            _out(capsys, "settings", "sleep", "set", "--hold-below-score", "50")
        outputs.append((_out(capsys, "daily"), _out(capsys, "daily", "--json")))
    assert outputs[0] == outputs[1]
    assert "== Goal:" not in outputs[0][0]
    assert "goal_mode" not in json.loads(outputs[0][1])["recommendation"]


# --- gain/maintain: plan unchanged, section and key added ----------------------------------------


@pytest.mark.parametrize("argv", [goal.GAIN_GOAL, ("goal", "set", "--mode", "maintain")])
def test_gain_or_maintain_adds_only_the_section_and_a_trailing_key(
    home: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], argv: tuple[str, ...]
) -> None:
    builders.build_recommend_database(home)
    _no_garmin(monkeypatch)
    _out(capsys, *argv)
    text = _out(capsys, *RECOMMEND)
    document = json.loads(_out(capsys, *RECOMMEND, "--json"))

    assert _without_goal_section(text) == builders.golden(f"recommend_{builders.RECOMMEND_DATE}.txt")
    assert list(document)[-1] == "goal_mode"
    report = document.pop("goal_mode")
    assert json.dumps(document, indent=2) + "\n" == builders.golden(f"recommend_{builders.RECOMMEND_DATE}.json")
    assert report["progression"] == []
    assert _goal_section(text)[2] == "  Progression [design]: unchanged (the default gain rules)"


# --- cut: progression action/load/reps/basis only (AC3) -------------------------------------------


def test_cut_changes_only_the_progression_target(
    home: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    builders.build_recommend_database(home)
    _no_garmin(monkeypatch)
    _out(capsys, *goal.CUT_GOAL)
    text = _out(capsys, *RECOMMEND)
    output = _out(capsys, *RECOMMEND, "--json")
    assert _out(capsys, *RECOMMEND, "--json") == output  # deterministic
    document = json.loads(output)

    golden = json.loads(builders.golden(f"recommend_{builders.RECOMMEND_DATE}.json"))
    assert list(document)[-1] == "goal_mode"
    report = document.pop("goal_mode")
    expected = copy.deepcopy(golden)
    progression = expected["strength"]["exercises"][0]["progression"]
    assert (progression["action"], progression["load_kg"], progression["target_reps"]) == ("add_reps", 50.0, 11)
    progression["action"] = "maintain_load"
    progression["target_reps"] = 10
    progression["basis"].append(
        "cut goal (user setting): keep 50 kg x 10 instead of add_reps; that target is optional "
        "[MAINT-02, MAINT-06; optional PROG-03]"
    )
    assert document == expected  # sets, exercises, focus and everything else unchanged
    assert report["progression"] == [
        {
            "label": "BENCH_PRESS/-",
            "action": "maintain_load",
            "load_kg": 50.0,
            "target_reps": 10,
            "optional": {
                "action": "add_reps",
                "load_kg": 50.0,
                "load_increase_from_kg": None,
                "load_step": None,
                "target_reps": 11,
            },
            "evidence": ["MAINT-02", "MAINT-06", "PROG-03"],
        }
    ]

    golden_text = builders.golden(f"recommend_{builders.RECOMMEND_DATE}.txt")
    expected_text = (
        golden_text.replace(
            "  1. [key] BENCH_PRESS/-: 3 sets x 11 reps @ 50 kg (range 5-12)",
            "  1. [key] BENCH_PRESS/-: 3 sets x 10 reps @ 50 kg (range 5-12)",
        )
        .replace(
            "  BENCH_PRESS/- [add_reps, load confidence normal]",
            "  BENCH_PRESS/- [maintain_load, load confidence normal]",
        )
        .replace(
            "    - 2-session trend (work load x best reps): 03-10 50 kgx10, 03-13 50 kgx10\n",
            "    - 2-session trend (work load x best reps): 03-10 50 kgx10, 03-13 50 kgx10\n"
            "    - cut goal (user setting): keep 50 kg x 10 instead of add_reps; that target is optional "
            "[MAINT-02, MAINT-06; optional PROG-03]\n",
        )
    )
    assert _without_goal_section(text) == expected_text
    assert text.isascii()


CUT_SECTION = [
    "== Goal: cut (user setting) ==",
    "  Target [design: user setting]: body fat 18 % by 2027-02-28; SMM floor 41 kg; weekly loss 0.3-0.5 %/week",
    "  Progression [MAINT-02, MAINT-06; optional PROG-03]: keep load and reps; the increase is optional",
    "    SQUAT/- [maintain_load]: keep 60 kg x 10 (optional: 60 kg x 11)",
    "  Weekly sets below 10, 2026-03-09..2026-03-15 (primary 1, secondary 0.5) [VOL-04; counting VOL-02]:",
    "    quadriceps 3, hamstrings 0, glutes 1.5, lats 0, upper_back 0, posterior_deltoid 0, biceps 0, forearms 0, "
    "chest 6, anterior_deltoid 3, lateral_deltoid 0, triceps 3 (lower bounds: 1 UNKNOWN sets not counted)",
    "  Weight change 2026-02-16 -> 2026-03-16 (28 d; latest InBody 2026-03-16, 0 d ago): -0.62 %/week "
    "[MAINT-05; design: >= 7 d apart]",
    "    evidence 0.5-1.0 [MAINT-05]; your target 0.3-0.5 (user setting)",
    "    -> outside your target range [design: user setting]",
    "  SMM: below your 41 kg floor (InBody 2026-03-16) [design: user setting]",
    "  Goal progress [design: fat-free mass assumed constant]: needs -0.03 %/week to reach body fat 18 % by "
    "2027-02-28; actual -0.62 %/week",
    "  Same-day run and legs under 3 h, 2026-03-09..2026-03-16 [design; CONC-03, CONC-04]:",
    "    2026-03-12: run 07:00, legs 08:00 (1 h apart): lift first next time [CONC-05]",
    "  Nights under 7 h, 2026-03-10..2026-03-16: 0 of 1 with sleep data, 6 without [SLEEP-05, display only]",
    "    training sleep rules [design]: hold < 5 h, reduce < 4 h, score < 50 (default; not evidence-based, SLEEP-05)",
]


def test_cut_section_with_inbody_and_a_run_before_legs(
    home: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    database = builders.build_recommend_database(home)
    goal.add_run_and_legs(database)
    goal.add_inbody(database)
    _no_garmin(monkeypatch)
    _out(capsys, *goal.CUT_GOAL)
    text = _out(capsys, *RECOMMEND)
    document = json.loads(_out(capsys, *RECOMMEND, "--json"))

    assert _goal_section(text) == CUT_SECTION
    report = document["goal_mode"]
    assert list(report) == [
        "goal_mode_version",
        "goal",
        "progression",
        "weekly_sets",
        "weight_change",
        "smm_floor",
        "goal_progress",
        "run_legs",
        "sleep",
    ]
    assert report["weight_change"]["percent_per_week"] == "-0.62"
    assert report["weight_change"]["flags"] == ["outside_user_target"]
    assert report["smm_floor"] == {
        "status": "below",
        "measurement_date": "2026-03-16",
        "floor_kg": "41",
        "evidence": ["design"],
    }
    assert report["run_legs"]["pairs"][0]["advice"] == "lift_first"
    # AC8: every new JSON item carries evidence (continuation items inherit their section's).
    for key in ("goal", "weekly_sets", "weight_change", "smm_floor", "goal_progress", "run_legs", "sleep"):
        assert report[key]["evidence"], key
    assert all(item["evidence"] for item in report["progression"])
    assert report["sleep"]["training_rules"]["evidence"] == ["design", "SLEEP-05"]
    # D1: no measured body-composition value in the document (only rates, flags, dates, user settings).
    serialized = json.dumps(report)
    for measured in ("78.0", "80.0", "35.9", "36.0", "15.0", "16.0", "63", "76.8"):
        assert f'"{measured}' not in serialized and f" {measured}," not in serialized, measured
    # AC8 text: every section line has a tag; indented continuation lines belong to the line above.
    for line in CUT_SECTION[1:]:
        if not line.startswith("    "):
            assert "[" in line and "]" in line, line


def test_a_run_on_a_legs_day_changes_no_plan_field(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # AC6: the same legs history with and without the run gives the same strength and swim plan.
    documents = []
    for name, with_run in (("legs", False), ("run", True)):
        root = tmp_path / name
        monkeypatch.setenv("MUSCLE50_HOME", str(root))
        database = builders.build_recommend_database(root)
        goal.save(database, goal.legs("9002", "2026-03-12T08:00:00", "2026-03-11T23:00:00+00:00"))
        if with_run:
            goal.save(database, goal.run("9001", "2026-03-12T07:00:00", "2026-03-11T22:00:00+00:00"))
        _no_garmin(monkeypatch)
        _out(capsys, *goal.CUT_GOAL)
        documents.append(json.loads(_out(capsys, *RECOMMEND, "--json")))
    without_run, with_run_document = documents
    for key in ("strength", "swimming", "recovery", "goals"):
        assert with_run_document[key] == without_run[key], key
    assert without_run["goal_mode"]["run_legs"]["pairs"] == []
    assert len(with_run_document["goal_mode"]["run_legs"]["pairs"]) == 1


# --- unreadable settings and InBody --------------------------------------------------------------


def _corrupt_goal(home: Path) -> None:
    path = home / "config" / "training_goal.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"schema_version": 1, "goal": "secret"}', encoding="utf-8")


@pytest.mark.parametrize("which", ["goal", "sleep"])
def test_an_invalid_settings_file_stops_recommend(
    home: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], which: str
) -> None:
    builders.build_recommend_database(home)
    _no_garmin(monkeypatch)
    if which == "goal":
        _corrupt_goal(home)
    else:
        path = home / "config" / "sleep_thresholds.json"
        path.parent.mkdir(parents=True)
        path.write_text('{"schema_version": 1, "sleep_thresholds": {"hold_below_seconds": 1}}', encoding="utf-8")
    code, out, err = _run(capsys, *RECOMMEND)
    assert (code, out) == (1, "")
    assert err.startswith("오류: ") and "is not valid" in err and "secret" not in err


def test_an_invalid_goal_stops_daily_before_garmin_and_before_any_write(
    home: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _no_garmin(monkeypatch)
    _corrupt_goal(home)
    code, out, err = _run(capsys, "daily")
    assert (code, out) == (1, "")
    assert "training goal file" in err
    assert sorted(path.name for path in home.iterdir()) == ["config"]  # no db, auth or raw directories


def test_garmin_sync_and_after_workout_never_read_the_goal(
    home: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _corrupt_goal(home)
    _use(monkeypatch, builders.daily_account())
    assert _run(capsys, "garmin", "sync", "--from", "2026-10-01", "--to", "2026-10-02")[0] == 0
    assert _run(capsys, "daily", "--after-workout")[0] == 0


def test_daily_with_a_cut_goal_embeds_the_recommend_document(
    home: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _use(monkeypatch, builders.daily_account())
    _out(capsys, *goal.CUT_GOAL)
    text = _out(capsys, "daily")
    daily = json.loads(_out(capsys, "daily", "--json"))
    recommendation = daily["recommendation"]
    assert list(recommendation)[-1] == "goal_mode"
    standalone = json.loads(_out(capsys, "recommend", "--date", builders.DAILY_TODAY.isoformat(), "--json"))
    assert recommendation == standalone
    assert "== Goal: cut (user setting) ==" in text


def _migrated_without_inbody(root: Path) -> Path:
    path = root / "db" / "muscle50.sqlite3"
    path.parent.mkdir(parents=True)
    connection = sqlite3.connect(path)
    try:
        for migration in sorted(MIGRATIONS_DIR.glob("*.sql")):
            if migration.name != "007_inbody.sql":
                connection.executescript(migration.read_text(encoding="utf-8"))
    finally:
        connection.close()
    builders.fill_recommend_database(path)
    return path


def test_no_inbody_table_gives_unknown_lines_and_exit_0(
    home: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _migrated_without_inbody(home)
    _no_garmin(monkeypatch)
    _out(capsys, *goal.CUT_GOAL)
    text = _out(capsys, *RECOMMEND)
    report = json.loads(_out(capsys, *RECOMMEND, "--json"))["goal_mode"]
    assert report["weight_change"]["status"] == "unknown"
    assert report["weight_change"]["reason"].startswith("InBody data unavailable: muscle50 database has no InBody")
    assert report["smm_floor"]["status"] == "unknown"
    assert report["goal_progress"]["status"] == "unknown"
    section = _goal_section(text)
    assert any(line.startswith("  Weight change: unknown (InBody data unavailable: ") for line in section)
    assert "  SMM: unknown against your 41 kg floor (no InBody skeletal muscle mass) [design: user setting]" in section
