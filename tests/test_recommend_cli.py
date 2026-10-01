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
        "== Data quality / UNKNOWN notices ==",
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


def test_recommend_avoid_option(home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["recommend", "--date", "2026-03-16", "--avoid", "chest", "--json"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["strength"]["avoided_muscles"] == ["chest"]
    assert payload["strength"]["exercises"] == []


@pytest.mark.parametrize(
    "argv",
    [
        ["recommend", "--date", "2026-3-16"],
        ["recommend"],
        ["recommend", "--date", "2026-03-16", "--avoid", "calves"],
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
