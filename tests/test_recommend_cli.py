from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from analytics_builders import activity, recovery, strength_set, swim_detail, uniform_lap

from muscle50.cli import main
from muscle50.domain.activity import ActivityType, NormalizedActivity
from muscle50.infrastructure.garmin.client import PythonGarminConnector
from muscle50.infrastructure.raw_store import RawArtifact, RecoveryCapture
from muscle50.infrastructure.sqlite.database import ActivityRepository, DailyRecoveryRepository


def _save(database: Path, item: NormalizedActivity) -> None:
    artifact = RawArtifact("activity", f"raw/{item.source_activity_id}/activity.json", "application/json", "0" * 64, 2)
    ActivityRepository(database).save(item, (artifact,))


def _save_recovery(database: Path, calendar_date: str, **overrides: object) -> None:
    capture = RecoveryCapture(
        capture_id=f"capture-{calendar_date}",
        requested_date=calendar_date,
        manifest_relative_path=f"recovery/{calendar_date}/manifest.json",
        artifacts=(RawArtifact("sleep", f"recovery/{calendar_date}/sleep.json", "application/json", "0" * 64, 2),),
    )
    DailyRecoveryRepository(database).save(recovery(calendar_date, **overrides), capture)


def _bench(source_id: str, day: str, *, unknown: bool = False) -> NormalizedActivity:
    sets = [strength_set(index, reps=10, weight_kg=50.0) for index in range(1, 4)]
    if unknown:
        sets.append(strength_set(4, category="UNKNOWN", reps=8, weight_kg=40.0))
    return activity(source_id, f"{day}T12:00:00", ActivityType.STRENGTH, strength_sets=tuple(sets))


@pytest.fixture
def database(tmp_path: Path) -> Path:
    path = tmp_path / "db" / "muscle50.sqlite3"
    ActivityRepository(path).migrate()
    _save(path, _bench("8001", "2026-03-10", unknown=True))
    _save(path, _bench("8002", "2026-03-13"))
    _save(path, _bench("8003", "2026-03-16"))  # same day as the requested date below
    _save(
        path,
        activity(
            "8100",
            "2026-03-16T06:00:00",
            ActivityType.SWIMMING,
            distance_meters=400.0,
            swim_detail=swim_detail("8100", (uniform_lap(0, 16, 25.0, 30.0),)),
        ),
    )
    _save_recovery(path, "2026-03-15")
    _save_recovery(path, "2026-03-16", sleep_seconds=None)
    return path


@pytest.fixture
def home(database: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = database.parents[1]
    monkeypatch.setenv("MUSCLE50_HOME", str(root))
    monkeypatch.setattr(
        PythonGarminConnector,
        "authenticate",
        lambda auth_dir: pytest.fail("recommend must never authenticate"),
    )
    return root


def _file_state(path: Path) -> tuple[str, int]:
    return hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_mtime_ns


def test_recommend_prints_ascii_sections_and_never_writes(
    home: Path, database: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    before = _file_state(database)
    before_dirs = sorted(item.name for item in home.iterdir())

    exit_code = main(["recommend", "--date", "2026-03-16"])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert output.isascii()
    for heading in (
        "== Strength ==",
        "== Progression targets ==",
        "== Recovery adjustment",
        "== Next swim goal",
        "== Data freshness ==",
        "== Data quality / UNKNOWN / no-rule notices ==",
    ):
        assert heading in output
    assert "BENCH_PRESS/-" in output
    assert "[same_day_strength_excluded] 2026-03-16 8003" in output
    assert "[strength_unknown_exercise] 2026-03-10 8001" in output
    assert "muscle50 garmin refresh 8001" in output
    assert "sleep_seconds [2026-03-16]: missing (not treated as poor)" in output
    assert "swim earlier today (8100)" in output
    assert _file_state(database) == before
    assert sorted(item.name for item in home.iterdir()) == before_dirs


def test_recommend_json_is_deterministic(home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["recommend", "--date", "2026-03-16", "--json"]) == 0
    first = capsys.readouterr().out
    assert main(["recommend", "--date", "2026-03-16", "--json"]) == 0
    second = capsys.readouterr().out

    payload = json.loads(first)
    assert first == second
    assert first.isascii()
    assert payload["as_of"] == "2026-03-16"
    assert payload["excluded_same_day_strength_ids"] == ["8003"]
    key = payload["strength"]["exercises"][0]
    assert (key["category"], key["exercise_name"]) == ("BENCH_PRESS", None)
    # History is 8001 and 8002 only: 10/10/10 at 50 kg, so one more rep.
    assert key["progression"]["action"] == "add_reps"
    assert (key["progression"]["load_kg"], key["progression"]["target_reps"]) == (50.0, 11)
    assert payload["recovery"]["level"] == "normal"


def test_recommend_reports_coverage_gap_and_missing_recovery_row(
    home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["recommend", "--date", "2026-03-30"]) == 0

    output = capsys.readouterr().out
    assert "[activity_coverage_gap]" in output
    assert "newest stored activity is 2026-03-16" in output
    assert "[recovery_row_missing]" in output
    assert "Recovery adjustment: normal" in output


def test_recommend_heading_separates_recovery_from_a_rest_rule_reduce(
    home: Path, database: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _save(database, _bench("8004", "2026-03-16"))  # 6 chest sets on 2026-03-16 with 8003
    _save_recovery(database, "2026-03-17", training_readiness_level="LOW")  # recovery hold

    assert main(["recommend", "--date", "2026-03-17", "--focus", "push"]) == 0

    output = capsys.readouterr().out
    assert "== Recovery adjustment: hold; session adjustment: reduce ==" in output
    assert "-> recovery hold: " in output
    assert "48 h rest rule reduce: one set fewer" in output
    assert "recovery reduce" not in output


def test_recommend_small_load_increase_shows_the_next_available_step_not_an_invented_load(
    home: Path, database: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    lateral = [
        strength_set(index, category="LATERAL_RAISE", name="ONE_ARM_CABLE_LATERAL_RAISE", reps=20, weight_kg=6.0)
        for index in range(1, 3)
    ]
    _save(database, activity("8005", "2026-03-13T18:00:00", ActivityType.STRENGTH, strength_sets=tuple(lateral)))
    argv = ["recommend", "--date", "2026-03-16", "--focus", "shoulders"]

    assert main(argv) == 0
    output = capsys.readouterr().out
    assert main(argv) == 0
    assert capsys.readouterr().out == output
    assert main([*argv, "--json"]) == 0
    first = capsys.readouterr().out
    assert main([*argv, "--json"]) == 0
    assert capsys.readouterr().out == first

    assert "LATERAL_RAISE/ONE_ARM_CABLE_LATERAL_RAISE" in output
    assert "@ next available step above 6 kg (range 10-20)" in output
    assert "8.5 kg" not in output
    (exercise,) = json.loads(first)["strength"]["exercises"]
    progression = exercise["progression"]
    assert progression["action"] == "increase_load"
    assert progression["load_kg"] is None
    assert (progression["load_increase_from_kg"], progression["load_step"]) == (6.0, "smallest_available")
    assert "8.5" not in json.dumps(exercise)


def test_recommend_avoid_option(home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["recommend", "--date", "2026-03-16", "--avoid", "chest", "--json"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["strength"]["avoided_muscles"] == ["chest"]
    assert payload["strength"]["exercises"] == []


def test_recommend_marks_an_automatic_focus(home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["recommend", "--date", "2026-03-16"]) == 0
    assert "Focus: push (chest, anterior_deltoid, lateral_deltoid, triceps) [auto-selected]" in capsys.readouterr().out

    assert main(["recommend", "--date", "2026-03-16", "--json"]) == 0
    strength = json.loads(capsys.readouterr().out)["strength"]
    assert (strength["focus"], strength["focus_source"], strength["auto_focus"]) == ("push", "auto", "push")


def test_recommend_focus_option_is_kept_without_history_and_never_writes(
    home: Path, database: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    before = _file_state(database)

    assert main(["recommend", "--date", "2026-03-16", "--focus", "legs", "--json"]) == 0
    strength = json.loads(capsys.readouterr().out)["strength"]
    assert main(["recommend", "--date", "2026-03-16", "--focus", "legs"]) == 0
    output = capsys.readouterr().out

    # Only bench press history exists: the request is kept, nothing is invented or switched.
    assert (strength["focus"], strength["focus_source"], strength["auto_focus"]) == ("legs", "user", "push")
    assert strength["exercises"] == []
    assert any(text.startswith("history is limited") for text in strength["reasons"])
    assert "Focus: legs (quadriceps, hamstrings, glutes) [user-selected; automatic would be push]" in output
    assert "[strength_unknown_exercise] 2026-03-10 8001" in output  # warnings still apply
    assert output.isascii()
    assert _file_state(database) == before


@pytest.mark.parametrize(
    "argv",
    [
        ["recommend", "--date", "2026-3-16"],
        ["recommend"],
        ["recommend", "--date", "2026-03-16", "--avoid", "calves"],
        ["recommend", "--date", "2026-03-16", "--focus", "arms"],
    ],
)
def test_recommend_rejects_invalid_input(home: Path, argv: list[str]) -> None:
    try:
        assert main(argv) == 1
    except SystemExit as exc:  # argparse rejects missing/invalid choices
        assert exc.code == 2


def test_recommend_reports_missing_database(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("MUSCLE50_HOME", str(tmp_path / "empty-home"))

    assert main(["recommend", "--date", "2026-03-16"]) == 1
    assert "not found" in capsys.readouterr().err
    assert not (tmp_path / "empty-home").exists()


def test_recommend_reports_freshness_and_a_partial_recovery_row(home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["recommend", "--date", "2026-03-16", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert main(["recommend", "--date", "2026-03-16"]) == 0
    output = capsys.readouterr().out

    freshness = payload["data_freshness"]
    assert freshness["latest_swim_date"] == "2026-03-16"
    assert freshness["latest_strength_date"] == "2026-03-16"
    assert (freshness["requested_date_recovery_row"], freshness["requested_date_sleep_recorded"]) == (True, False)
    assert freshness["sync_coverage_recorded"] is False
    codes = [item["code"] for item in payload["notices"]]
    assert "recovery_row_partial" in codes
    assert "swim_gap" not in codes
    assert payload["recovery"]["lookback"]["reason"] == "no sleep recorded for 2026-03-16 (row is partial)"
    assert "== Data freshness ==" in output
    assert "2026-03-16 recovery row: present, no sleep (partial)" in output
    assert "not a confirmed rest day" in output


def test_recommend_after_a_long_gap_warns_and_plans_an_easy_swim(
    home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["recommend", "--date", "2026-03-30", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)

    codes = [item["code"] for item in payload["notices"]]
    assert {"activity_coverage_gap", "recovery_row_missing", "recovery_coverage_gap", "swim_gap"} <= set(codes)
    assert payload["swimming"]["goal"]["session_type"] == "return_easy"
    assert payload["swimming"]["baseline"]["days_since_last_swim"] == 14
