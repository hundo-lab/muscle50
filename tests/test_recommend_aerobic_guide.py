"""recommend/daily with the Aerobic Guide (AC1-AC8): exact lines and keys, unchanged neighbours, FATEX-04."""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import aerobic_builders as aerobic
import goal_mode_builders as goal
import pytest
import sync_coverage_builders as builders
from analytics_builders import activity
from inbody_trend_builders import measurement, save_measurements

import muscle50.cli as cli
from muscle50.application.recommend_training import BuildTrainingRecommendation
from muscle50.cli import main
from muscle50.domain.activity import ActivityType
from muscle50.domain.training_goal import GoalMode, TrainingGoal, WeeklyRateRange
from muscle50.infrastructure.garmin.client import PythonGarminConnector
from muscle50.infrastructure.sqlite.analytics_reader import TrainingData

MIGRATIONS_DIR = Path(__file__).parents[1] / "src" / "muscle50" / "infrastructure" / "sqlite" / "migrations"
RECOMMEND = ("recommend", "--date", aerobic.AS_OF)
FRESHNESS = "== Data freshness =="
FORBIDDEN_REFERENCE_WORDS = ("stop", "ceiling", "limit", "upper", "max")
COMPARATIVE_WORDS = ("weaker", "less effective", "better", "best", "recommended", "should", "first")

TAIL_LINES = [
    "  Aerobic minutes 2026-11-13..2026-11-19 (running, swimming): moderate 140 + vigorous 60 = 200 min "
    "[EXL-03; design: Garmin intensity minutes, vigorous not doubled]",
    "    reference marks: 150 min/week, the guideline minimum (or 75 vigorous) [EXL-03]; 300 min/week, the end of "
    "the studied range [FATEX-02]",
    "    lower bound: 1 activity without intensity minutes not counted (duration 45 min, intensity unknown) [design]",
    "  Run length vs the longest run in the 30 days before it, 2026-11-13..2026-11-20 "
    "[RUNPROG-03: observational link with overuse injury; notice only]:",
    "    2026-11-19 30001: 12.5 km, 25.0 % longer than 10 km (2026-11-02)",
    "  Plateau check [design: user setting, 3 weeks below 0.3 %/week loss, >= 2 InBody intervals]: met",
    "    InBody 2026-10-23 -> 2026-11-06 -> 2026-11-20 (28 d): -0.11, -0.05 %/week [PLAT-01, PLAT-02]",
    "    note: weight moves about 0.35 % within a week [PLAT-02]; your target is 0.3-0.5 %/week (user setting); "
    "compare same-device, same-condition InBody only [PLAT-02]",
    "    options, no ranking (fixed display order) [PLAT-06]; your preference and what you can keep up are valid "
    "reasons to choose [FATEX-07]:",
    "      a) check that meals are logged completely (missed meals, general-meal estimates, weekends) [PLAT-04]",
    "      b) eat 100-150 kcal/day less; keep the deficit at or under about 500 kcal/day (muscle50 cannot measure it) "
    "[design: goals.md step; PRO-04]",
    "      c) keep intake, add activity: the same deficit gave the same fat loss, but extra eating can offset part of "
    "it [FATEX-05, FATEX-04]; watch run length and the 3 h run/legs gap [RUNPROG-03, CONC-04]",
    "      d) one maintenance week: weight may rise from glycogen and water, and the deadline moves by a week "
    "[PLAT-05]",
]
AEROBIC_DOCUMENT: dict[str, Any] = {
    "from": "2026-11-13",
    "to": "2026-11-19",
    "activity_types": ["running", "swimming"],
    "status": "lower_bound",
    "moderate_minutes": 140.0,
    "vigorous_minutes": 60.0,
    "total_minutes": 200.0,
    "vigorous_counted_as": "minutes",
    "activities": [
        {
            "source_activity_id": "30003",
            "date": "2026-11-14",
            "type": "running",
            "moderate_minutes": 100.0,
            "vigorous_minutes": 40.0,
            "duration_minutes": 48,
        },
        {
            "source_activity_id": "30002",
            "date": "2026-11-15",
            "type": "swimming",
            "moderate_minutes": None,
            "vigorous_minutes": None,
            "duration_minutes": 45,
        },
        {
            "source_activity_id": "30001",
            "date": "2026-11-19",
            "type": "running",
            "moderate_minutes": 40.0,
            "vigorous_minutes": 20.0,
            "duration_minutes": 62,
        },
    ],
    "without_intensity_minutes": {
        "activity_count": 1,
        "duration_minutes": 45,
        "without_duration": 0,
        "one_metric_only_count": 0,
    },
    "reference_minutes_per_week": [
        {"minutes": 150, "meaning": "guideline_minimum", "evidence": ["EXL-03"]},
        {"minutes": 300, "meaning": "end_of_studied_range", "evidence": ["FATEX-02"]},
    ],
    "evidence": ["EXL-03", "FATEX-02", "design"],
}


def _run_item(source_id: str, day: str, meters: float, increase: str, status: str) -> dict[str, Any]:
    return {
        "source_activity_id": source_id,
        "date": day,
        "distance_meters": meters,
        "longest_previous_meters": 10000.0,
        "longest_previous_activity_id": "29990",
        "longest_previous_date": "2026-11-02",
        "previous_without_distance": 0,
        "baseline_lower_bound": False,
        "increase_percent": increase,
        "status": status,
    }


RUN_LENGTH_DOCUMENT: dict[str, Any] = {
    "from": "2026-11-13",
    "to": "2026-11-20",
    "previous_days": 30,
    "threshold_percent": 10,
    "basis": "distance",
    "notice_only": True,
    "evidence": ["RUNPROG-03"],
    "runs": [
        _run_item("30003", "2026-11-14", 8000.0, "-20.0", "within"),
        _run_item("30001", "2026-11-19", 12500.0, "25.0", "longer_than_threshold"),
    ],
}
PLATEAU_DOCUMENT: dict[str, Any] = {
    "status": "met",
    "weeks": 3,
    "below_loss_percent_per_week": "0.3",
    "source": "user_setting",
    "min_intervals": 2,
    "intervals": [
        {"from_date": "2026-11-06", "to_date": "2026-11-20", "days": 14, "percent_per_week": "-0.05"},
        {"from_date": "2026-10-23", "to_date": "2026-11-06", "days": 14, "percent_per_week": "-0.11"},
    ],
    "span_days": 28,
    "latest_measurement_date": "2026-11-20",
    "days_since_latest_measurement": 0,
    "reason": None,
    "evidence": ["design", "PLAT-01", "PLAT-02"],
    "noise": {"within_week_weight_percent": "0.35", "evidence": ["PLAT-02"]},
    "options_ranked": False,
    "choice_evidence": ["PLAT-06", "FATEX-07"],
    "options": [
        {"code": "check_meal_logging", "evidence": ["PLAT-04"]},
        {
            "code": "eat_less",
            "step_kcal_per_day": {"minimum": 100, "maximum": 150},
            "step_source": "docs/goals.md",
            "deficit_limit_kcal_per_day": 500,
            "deficit_measurable": False,
            "evidence": ["design", "PRO-04"],
        },
        {
            "code": "keep_intake_add_activity",
            "run_length_threshold_percent": 10,
            "run_legs_gap_hours": 3,
            "evidence": ["FATEX-05", "FATEX-04", "RUNPROG-03", "CONC-04"],
        },
        {"code": "maintenance_week", "weeks": 1, "evidence": ["PLAT-05"]},
    ],
}


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "home"
    monkeypatch.setenv("MUSCLE50_HOME", str(root))
    monkeypatch.setattr(cli, "_local_timezone", lambda day: builders.KST)
    monkeypatch.setattr(cli, "_today", lambda: date(2026, 11, 20))
    monkeypatch.setattr(
        PythonGarminConnector, "authenticate", lambda *args, **kwargs: pytest.fail("must not use Garmin")
    )
    return root


def _run(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, str, str]:
    code = main(list(argv))
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def _out(capsys: pytest.CaptureFixture[str], *argv: str) -> str:
    code, out, err = _run(capsys, *argv)
    assert code == 0, err
    return out


def _goal_section(text: str) -> list[str]:
    lines = text.split("\n")
    start = next(index for index, line in enumerate(lines) if line.startswith("== Goal: "))
    return lines[start : lines.index(FRESHNESS) - 1]


def _tail(text: str) -> list[str]:
    """The goal-section lines from the aerobic line on (the lines this feature adds)."""
    section = _goal_section(text)
    start = next(index for index, line in enumerate(section) if line.startswith("  Aerobic minutes "))
    return section[start:]


def _new_documents(report: dict[str, Any]) -> list[dict[str, Any]]:
    """Every JSON object this feature adds that is not a per-item row of a tagged list."""
    plateau = report["plateau"]
    documents = [
        report["aerobic_minutes"],
        report["run_length"],
        *report["aerobic_minutes"]["reference_minutes_per_week"],
    ]
    if plateau is not None:
        documents += [plateau, plateau["noise"], *plateau["options"]]
    return documents


# --- AC7: no goal, no new output ----------------------------------------------------------------


def test_without_a_goal_nothing_is_added(home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    aerobic.build_database(home)
    text = _out(capsys, *RECOMMEND)
    output = _out(capsys, *RECOMMEND, "--json")
    assert "== Goal:" not in text and "Aerobic minutes" not in text and "Plateau" not in text
    assert "goal_mode" not in json.loads(output)
    assert "aerobic_minutes" not in output and "run_length" not in output and "plateau" not in output


# --- the cut scenario: exact lines and documents (AC1, AC3, AC4, AC8) ------------------------------


def test_cut_with_a_plateau_setting_adds_the_exact_lines_and_keys(
    home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    aerobic.build_database(home)
    _out(capsys, *aerobic.CUT_PLATEAU_GOAL)
    text = _out(capsys, *RECOMMEND)
    output = _out(capsys, *RECOMMEND, "--json")
    assert _out(capsys, *RECOMMEND) == text  # deterministic
    assert _out(capsys, *RECOMMEND, "--json") == output
    assert text.isascii()
    document = json.loads(output)
    assert output == json.dumps(document, indent=2) + "\n"
    assert list(document)[-1] == "goal_mode"

    assert _tail(text) == TAIL_LINES
    report = document["goal_mode"]
    assert report["goal_mode_version"] == 1 and document["recommendation_version"] == 1
    assert list(report)[-3:] == ["aerobic_minutes", "run_length", "plateau"]
    assert report["aerobic_minutes"] == AEROBIC_DOCUMENT
    assert report["run_length"] == RUN_LENGTH_DOCUMENT
    assert report["plateau"] == PLATEAU_DOCUMENT
    # The opted-in setting is part of the goal (before the goal's source and evidence keys).
    assert list(report["goal"])[-3:] == ["plateau_weeks", "source", "evidence"]
    assert report["goal"]["plateau_weeks"] == 3


def test_every_new_line_and_object_carries_evidence(home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    # AC8: a tagged line per item; indented continuation lines belong to the tagged line above them.
    aerobic.build_database(home)
    _out(capsys, *aerobic.CUT_PLATEAU_GOAL)
    tail = _tail(_out(capsys, *RECOMMEND))
    tagged = re.compile(r"\[(?:[A-Z]+-\d\d|design)[^\]]*\]")
    for line in tail:
        if not line.startswith("    "):
            assert tagged.search(line), line
    for line in tail:
        if line.startswith("      "):  # each option
            assert tagged.search(line), line
    report = json.loads(_out(capsys, *RECOMMEND, "--json"))["goal_mode"]
    for item in _new_documents(report):
        assert item["evidence"], item
    assert report["plateau"]["choice_evidence"] == ["PLAT-06", "FATEX-07"]


def test_the_reference_wording_and_the_options_make_no_ranking_or_ceiling_claim(
    home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # AC2 (FATEX-02) and PLAT-06: the 150/300 marks are references; the options are unranked.
    aerobic.build_database(home)
    _out(capsys, *aerobic.CUT_PLATEAU_GOAL)
    tail = _tail(_out(capsys, *RECOMMEND))
    reference = next(line for line in tail if line.startswith("    reference marks: "))
    for word in FORBIDDEN_REFERENCE_WORDS:
        assert word not in reference.lower(), word
    report = json.loads(_out(capsys, *RECOMMEND, "--json"))["goal_mode"]
    for item in report["aerobic_minutes"]["reference_minutes_per_week"]:
        assert not any(word in item["meaning"] for word in FORBIDDEN_REFERENCE_WORDS)
    options = [line for line in tail if line.startswith("      ")]
    assert [line[6:8] for line in options] == ["a)", "b)", "c)", "d)"]
    for line in options:
        for word in COMPARATIVE_WORDS:
            assert word not in line.lower(), (word, line)
    assert report["plateau"]["options_ranked"] is False


def test_no_measured_kg_in_the_new_text_or_json(home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    # AC6 / D1: rates, dates, distances and counts only.
    aerobic.build_database(home)
    _out(capsys, *aerobic.CUT_PLATEAU_GOAL)
    section = "\n".join(_goal_section(_out(capsys, *RECOMMEND)))
    serialized = json.dumps(json.loads(_out(capsys, *RECOMMEND, "--json"))["goal_mode"])
    for measured in aerobic.MEASURED_TEXTS:
        assert measured not in section, measured
        assert f'"{measured}' not in serialized and f" {measured}," not in serialized, measured


# --- the other states (AC1, AC3, AC4) ------------------------------------------------------------


def test_options_appear_only_when_the_plateau_is_met(home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    database = aerobic.build_database(home, with_inbody=False)
    # The first interval loses -0.64 %/week: faster than the 0.3 MIN, so not a plateau.
    save_measurements(
        database,
        (
            measurement("fast-1", "2026-10-23T08:00:00+09:00", weight=93.6),
            measurement("fast-2", "2026-11-06T08:00:00+09:00", weight=92.4),
            measurement("fast-3", "2026-11-20T08:00:00+09:00", weight=92.3),
        ),
    )
    _out(capsys, *aerobic.CUT_PLATEAU_GOAL)
    tail = _tail(_out(capsys, *RECOMMEND))
    assert tail[-2:] == [
        "  Plateau check [design: user setting, 3 weeks below 0.3 %/week loss, >= 2 InBody intervals]: not met",
        "    InBody 2026-10-23 -> 2026-11-06 -> 2026-11-20 (28 d): -0.64, -0.05 %/week [PLAT-01, PLAT-02]",
    ]
    plateau = json.loads(_out(capsys, *RECOMMEND, "--json"))["goal_mode"]["plateau"]
    assert (plateau["status"], plateau["options"]) == ("not_met", [])


def test_one_inbody_interval_is_insufficient(home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    database = aerobic.build_database(home, with_inbody=False)
    save_measurements(database, (aerobic.PLATEAU_WEIGHTS[0], aerobic.PLATEAU_WEIGHTS[2]))
    _out(capsys, *aerobic.CUT_PLATEAU_GOAL)
    assert _tail(_out(capsys, *RECOMMEND))[-1] == (
        "  Plateau check [design: user setting, 3 weeks below 0.3 %/week loss, >= 2 InBody intervals]: insufficient "
        "InBody data (2 weights cover 1 interval; the check needs 3 weeks and at least 2 intervals [PLAT-02])"
    )


CLOSENESS_WORDS = ("close", "similar", "near", "about the size", "comparable", "same as", "like your")


def test_the_noise_note_makes_no_claim_about_a_far_target(home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    # A valid but far target (1.5-2.0 %/week): the note shows both values and compares nothing.
    aerobic.build_database(home)
    far = list(aerobic.CUT_PLATEAU_GOAL)
    far[far.index("--weekly-loss") + 1 : far.index("--weekly-loss") + 3] = ["1.5", "2.0"]
    _out(capsys, *far)
    tail = _tail(_out(capsys, *RECOMMEND))
    note = next(line for line in tail if line.startswith("    note: "))
    assert note == (
        "    note: weight moves about 0.35 % within a week [PLAT-02]; your target is 1.5-2.0 %/week (user setting); "
        "compare same-device, same-condition InBody only [PLAT-02]"
    )
    for word in CLOSENESS_WORDS:
        assert word not in note.lower(), word
    pinned = next(line for line in TAIL_LINES if line.startswith("    note: "))
    for word in CLOSENESS_WORDS:
        assert word not in pinned.lower(), word


@pytest.mark.parametrize("argv", [goal.GAIN_GOAL, ("goal", "set", "--mode", "maintain")])
def test_gain_and_maintain_have_no_plateau_line(
    home: Path, capsys: pytest.CaptureFixture[str], argv: tuple[str, ...]
) -> None:
    aerobic.build_database(home)
    _out(capsys, *argv)
    tail = _tail(_out(capsys, *RECOMMEND))
    assert not any("Plateau" in line or line.startswith("      ") for line in tail)
    assert tail[0] == TAIL_LINES[0]  # aerobic minutes and the run notice show in every mode
    assert json.loads(_out(capsys, *RECOMMEND, "--json"))["goal_mode"]["plateau"] is None


def test_cut_without_the_setting_says_not_set(home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    aerobic.build_database(home)
    _out(capsys, *goal.CUT_GOAL)
    assert _tail(_out(capsys, *RECOMMEND))[-1] == (
        "  Plateau check: not set (goal set ... --plateau-weeks N; there is no evidence-based plateau definition) "
        "[design; PLAT-01]"
    )
    plateau = json.loads(_out(capsys, *RECOMMEND, "--json"))["goal_mode"]["plateau"]
    assert (plateau["status"], plateau["weeks"], plateau["source"], plateau["options"]) == ("not_set", None, None, [])


def test_no_aerobic_activity_is_none_stored_and_no_run_is_said(home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    aerobic.build_database(home, with_activities=False)
    _out(capsys, *aerobic.CUT_PLATEAU_GOAL)
    tail = _tail(_out(capsys, *RECOMMEND))
    assert tail[0] == (
        "  Aerobic minutes 2026-11-13..2026-11-19 (running, swimming): none stored (may be unsynced, not a "
        "confirmed rest week) [EXL-03; design]"
    )
    assert tail[3] == "    no run stored in this window"
    report = json.loads(_out(capsys, *RECOMMEND, "--json"))["goal_mode"]
    assert (report["aerobic_minutes"]["status"], report["aerobic_minutes"]["total_minutes"]) == ("none_stored", None)
    assert report["run_length"]["runs"] == []


def test_a_baseline_run_without_distance_is_named(home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    database = aerobic.build_database(home)
    goal.save(database, aerobic.run("29995", "2026-11-05T07:00:00", None))
    _out(capsys, *aerobic.CUT_PLATEAU_GOAL)
    expected = (
        "    2026-11-19 30001: 12.5 km, 25.0 % longer than 10 km (2026-11-02; 1 earlier run had no distance, so the "
        "longest may be longer)"
    )
    assert expected in _tail(_out(capsys, *RECOMMEND))


# --- AC6: the plan, nutrition and the settings files never change --------------------------------


def test_the_new_data_changes_no_plan_or_nutrition_field(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cli, "_local_timezone", lambda day: builders.KST)
    monkeypatch.setattr(cli, "_today", lambda: date(2026, 11, 20))
    documents = []
    for name, full in (("plain", False), ("full", True)):
        root = tmp_path / name
        monkeypatch.setenv("MUSCLE50_HOME", str(root))
        database = aerobic.build_database(root, with_activities=False, with_inbody=full)
        for item in aerobic.scenario_activities():
            if full or item.source_activity_id != "30001":  # the spike run only in the full data
                goal.save(database, item)
        for argv in builders.TARGET_COMMANDS:
            _out(capsys, *argv)
        _out(capsys, *aerobic.CUT_PLATEAU_GOAL)
        files = {path: path.read_bytes() for path in (root / "config").iterdir()}
        documents.append(json.loads(_out(capsys, *RECOMMEND, "--json")))
        assert {path: path.read_bytes() for path in (root / "config").iterdir()} == files
    plain, full_document = documents
    assert plain["goal_mode"]["plateau"]["status"] == "insufficient_measurements"
    assert full_document["goal_mode"]["plateau"]["status"] == "met"
    assert plain["goal_mode"]["run_length"]["runs"][-1]["status"] == "within"
    for key in ("strength", "swimming", "recovery", "goals", "nutrition"):
        assert full_document[key] == plain[key], key


def test_exercise_calories_are_never_added_to_intake_targets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # AC5 / FATEX-04: a run with 900 kcal on the day changes no nutrition output.
    monkeypatch.setattr(cli, "_local_timezone", lambda day: builders.KST)
    monkeypatch.setattr(cli, "_today", lambda: date(2026, 11, 20))
    outputs = []
    for name, with_run in (("no-run", False), ("run", True)):
        root = tmp_path / name
        monkeypatch.setenv("MUSCLE50_HOME", str(root))
        database = aerobic.build_database(root, with_activities=False)
        if with_run:
            goal.save(
                database,
                activity(
                    "40001", "2026-11-20T07:00:00", ActivityType.RUNNING, distance_meters=9000.0, calories_kcal=900.0
                ),
            )
        for argv in builders.TARGET_COMMANDS:
            _out(capsys, *argv)
        _out(capsys, *aerobic.CUT_PLATEAU_GOAL)
        status = ("nutrition", "status", "--date", aerobic.AS_OF)
        outputs.append(
            (
                _out(capsys, *status),
                _out(capsys, *status, "--json"),
                json.loads(_out(capsys, *RECOMMEND, "--json"))["nutrition"],
            )
        )
    assert outputs[0] == outputs[1]
    assert "900" not in outputs[1][0] and "900" not in outputs[1][1]


# --- daily, an old database and the second read --------------------------------------------------


def test_daily_embeds_the_recommend_document(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("MUSCLE50_HOME", str(tmp_path / "home"))
    monkeypatch.setattr(cli, "_local_timezone", lambda day: builders.KST)
    monkeypatch.setattr(cli, "_today", lambda: builders.DAILY_TODAY)
    garmin = builders.daily_account()
    monkeypatch.setattr(PythonGarminConnector, "authenticate", lambda *args, **kwargs: garmin)
    _out(capsys, *aerobic.CUT_PLATEAU_GOAL)
    text = _out(capsys, "daily")
    recommendation = json.loads(_out(capsys, "daily", "--json"))["recommendation"]
    standalone = json.loads(_out(capsys, "recommend", "--date", builders.DAILY_TODAY.isoformat(), "--json"))
    assert recommendation == standalone
    assert list(recommendation["goal_mode"])[-3:] == ["aerobic_minutes", "run_length", "plateau"]
    assert "  Aerobic minutes 2026-09-25..2026-10-01 (running, swimming): " in text


def test_no_inbody_table_gives_an_unknown_plateau_and_exit_0(home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = home / "db" / "muscle50.sqlite3"
    path.parent.mkdir(parents=True)
    connection = sqlite3.connect(path)
    try:
        for migration in sorted(MIGRATIONS_DIR.glob("*.sql")):
            if migration.name != "007_inbody.sql":
                connection.executescript(migration.read_text(encoding="utf-8"))
    finally:
        connection.close()
    for item in aerobic.scenario_activities():
        goal.save(path, item)
    _out(capsys, *aerobic.CUT_PLATEAU_GOAL)
    text = _out(capsys, *RECOMMEND)
    plateau = json.loads(_out(capsys, *RECOMMEND, "--json"))["goal_mode"]["plateau"]
    assert plateau["status"] == "unknown"
    assert plateau["reason"].startswith("InBody data unavailable: muscle50 database has no InBody")
    assert _tail(text)[-1].startswith(
        "  Plateau check [design: user setting, 3 weeks below 0.3 %/week loss, >= 2 InBody intervals]: unknown "
        "(InBody data unavailable: "
    )


class _RecordingReader:
    def __init__(self) -> None:
        self.calls: list[tuple[date, date]] = []

    def load(self, start: date, end: date) -> TrainingData:
        self.calls.append((start, end))
        return TrainingData((), (), ())


def test_the_longer_history_is_read_only_with_a_goal() -> None:
    day = date(2026, 11, 20)
    plain = _RecordingReader()
    BuildTrainingRecommendation(plain).execute(day)
    assert plain.calls == [(day - timedelta(days=28), day)]
    with_goal = _RecordingReader()
    cut = TrainingGoal(GoalMode.CUT, weekly_loss_percent=WeeklyRateRange(Decimal("0.3"), Decimal("0.5")))
    report = BuildTrainingRecommendation(with_goal, goal=cut).execute(day).goal_mode
    assert with_goal.calls == [(day - timedelta(days=28), day), (day - timedelta(days=37), day)]
    assert report is not None and report.aerobic_minutes.status == "none_stored"
