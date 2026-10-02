"""`muscle50 recommend` with the day's nutrition status, over a temporary MUSCLE50_HOME.

Foods, meals and targets are synthetic test values (not real food data or the user's targets).
The nutrition statuses come from the real `nutrition status` path; these tests pin how the
recommendation surfaces them, and that it never writes and never changes the training plan.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, timedelta, timezone, tzinfo
from pathlib import Path
from typing import Any

import pytest
from analytics_builders import activity, recovery, strength_set

import muscle50.cli as cli
from muscle50.application.recommend_training import BuildTrainingRecommendation
from muscle50.cli import main
from muscle50.domain.activity import ActivityType, NormalizedActivity
from muscle50.infrastructure.garmin.client import PythonGarminConnector
from muscle50.infrastructure.raw_store import RawArtifact, RecoveryCapture
from muscle50.infrastructure.sqlite.analytics_reader import SqliteAnalyticsReader
from muscle50.infrastructure.sqlite.database import ActivityRepository, DailyRecoveryRepository
from muscle50.presentation.terminal import render_training_recommendation, render_training_recommendation_json

KST = timezone(timedelta(hours=9))
DAY = "2026-03-16"
SHAKE = (
    ["--id", "shake", "--name", "SynShake", "--per", "1", "count"]
    + ["--kcal", "200", "--protein", "30", "--carbs", "10", "--fat", "5"]
    + ["--source", "nutrition_label", "--accuracy", "exact"]
)
# Protein and fat unknown; a non-ASCII name proves the recommendation text never prints food names.
MYSTERY = (
    ["--id", "mystery", "--name", "미스터리", "--per", "1", "count"]
    + ["--kcal", "150", "--protein", "unknown", "--carbs", "20", "--fat", "unknown"]
    + ["--source", "user_provided", "--accuracy", "estimated"]
)


def _save(database: Path, item: NormalizedActivity) -> None:
    artifact = RawArtifact("activity", f"raw/{item.source_activity_id}/activity.json", "application/json", "0" * 64, 2)
    ActivityRepository(database).save(item, (artifact,))


def _bench(source_id: str, day: str) -> NormalizedActivity:
    sets = tuple(strength_set(index, reps=10, weight_kg=50.0) for index in range(1, 4))
    return activity(source_id, f"{day}T12:00:00", ActivityType.STRENGTH, strength_sets=sets)


def _home(root: Path, monkeypatch: pytest.MonkeyPatch, *, strength: bool) -> Path:
    database = root / "db" / "muscle50.sqlite3"
    ActivityRepository(database).migrate()
    if strength:
        _save(database, _bench("9001", "2026-03-10"))
        _save(database, _bench("9002", "2026-03-13"))
    monkeypatch.setenv("MUSCLE50_HOME", str(root))
    monkeypatch.setattr(
        PythonGarminConnector, "authenticate", lambda *args, **kwargs: pytest.fail("recommend must never authenticate")
    )

    def fixed_timezone(day: date) -> tzinfo:
        return KST

    monkeypatch.setattr(cli, "_local_timezone", fixed_timezone)
    monkeypatch.setattr(cli, "_today", lambda: date(2026, 3, 16))
    return root


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A strength day: two bench sessions in history, so a strength session is planned."""
    return _home(tmp_path / "home", monkeypatch, strength=True)


@pytest.fixture
def rest_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """No training history: no strength session and an easy next swim."""
    return _home(tmp_path / "rest-home", monkeypatch, strength=False)


def _ok(capsys: pytest.CaptureFixture[str], *argv: str) -> str:
    code = main(list(argv))
    captured = capsys.readouterr()
    assert code == 0, captured.err
    return captured.out


def _foods(capsys: pytest.CaptureFixture[str]) -> None:
    _ok(capsys, "nutrition", "food", "add", *SHAKE)
    _ok(capsys, "nutrition", "food", "add", *MYSTERY)


def _log(capsys: pytest.CaptureFixture[str], *items: tuple[str, str, str]) -> None:
    argv = ["nutrition", "log", "--date", DAY, "--meal", "breakfast"]
    for food_id, quantity, unit in items:
        argv += ["--item", food_id, quantity, unit]
    _ok(capsys, *argv)


def _target(capsys: pytest.CaptureFixture[str], nutrient: str, *spec: str) -> None:
    _ok(capsys, "nutrition", "target", "set", nutrient, *spec)


def _recommend_json(capsys: pytest.CaptureFixture[str]) -> dict[str, Any]:
    document: dict[str, Any] = json.loads(_ok(capsys, "recommend", "--date", DAY, "--json"))
    return document


def _nutrition_section(text: str) -> list[str]:
    lines = text.splitlines()
    start = next(index for index, line in enumerate(lines) if line.startswith("== Nutrition"))
    end = next(index for index in range(start + 1, len(lines)) if lines[index].startswith("== "))
    return [line for line in lines[start:end] if line]


def _training_only(document: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in document.items() if key != "nutrition"}


# --- no usable nutrition data: training output unchanged ------------------------------------


def test_without_targets_the_text_is_exactly_the_training_recommendation(
    home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _foods(capsys)
    _log(capsys, ("shake", "1", "count"))  # intake exists but nothing to compare it with

    text = _ok(capsys, "recommend", "--date", DAY)

    training = BuildTrainingRecommendation(SqliteAnalyticsReader(home / "db" / "muscle50.sqlite3")).execute(
        date(2026, 3, 16)
    )
    assert text == render_training_recommendation(training) + "\n"
    assert "Nutrition" not in text
    assert not (home / "config").exists()


def test_without_targets_json_adds_only_a_trailing_nutrition_state(
    home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    document = _recommend_json(capsys)

    training = BuildTrainingRecommendation(SqliteAnalyticsReader(home / "db" / "muscle50.sqlite3")).execute(
        date(2026, 3, 16)
    )
    assert _training_only(document) == json.loads(render_training_recommendation_json(training))
    assert list(document)[-1] == "nutrition"
    nutrition = document["nutrition"]
    assert (nutrition["availability"], nutrition["actions"], nutrition["meal_count"]) == (
        "no_targets_configured",
        [],
        0,
    )
    assert {entry["status"] for entry in nutrition["nutrients"].values()} == {"no_target"}


# --- no intake logged -----------------------------------------------------------------------


def test_no_intake_logged_is_not_zero_and_creates_no_action(home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _target(capsys, "protein", "--exact", "100")
    _target(capsys, "kcal", "--exact", "2000")
    _target(capsys, "carbs", "--range", "200", "260")

    section = _nutrition_section(_ok(capsys, "recommend", "--date", DAY))
    document = _recommend_json(capsys)

    assert section[1:] == [
        "  [no_intake_logged] no meals logged for this date, so nutrition status is not used "
        "(not counted as 0 kcal or 0 g)"
    ]
    nutrition = document["nutrition"]
    assert (nutrition["availability"], nutrition["meal_count"], nutrition["item_count"]) == ("no_intake_logged", 0, 0)
    assert nutrition["actions"] == []
    protein = nutrition["nutrients"]["protein_g"]
    assert protein["status"] == "no_intake_logged"
    assert (protein["consumed"], protein["known_subtotal"], protein["remaining"]) == (None, None, None)


# --- complete data with targets -------------------------------------------------------------


def test_below_targets_on_a_strength_day(home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _foods(capsys)
    _log(capsys, ("shake", "1", "count"))
    _target(capsys, "protein", "--exact", "100")
    _target(capsys, "kcal", "--exact", "2000")
    _target(capsys, "carbs", "--range", "200", "260")

    section = _nutrition_section(_ok(capsys, "recommend", "--date", DAY))

    assert section[0] == "== Nutrition: logged intake 2026-03-16 (UTC+09:00) vs current targets =="
    assert section[1] == "  Logged so far: 1 meal, 1 item"
    assert "  kcal          200; target 2000 (exact): below target, 1800 to go" in section
    assert "  Protein       30 g; target 100 g (exact): below target, 70 g to go" in section
    assert (
        "  Carbohydrate  10 g; target 200-260 g (range): below range, 190 g to minimum, 250 g to maximum"
    ) in section
    assert not any(line.lstrip().startswith("Fat") for line in section)  # fat target unset: not listed
    actions = [line for line in section if line.startswith("  -> ")]
    assert [line.split("]")[0] for line in actions] == [
        "  -> [protein_below_target",
        "  -> [energy_below_target",
        "  -> [carbohydrate_below_target_for_training",
    ]
    assert "today's planned strength session" in actions[1] and "today's planned strength session" in actions[2]

    nutrition = _recommend_json(capsys)["nutrition"]
    assert nutrition["availability"] == "evaluated"
    assert nutrition["training_context"] == {
        "strength_session_planned": True,
        "strength_adjustment_level": "normal",
        "next_swim_session_type": "return_easy",
        "fuel_relevant": True,
        "description": "today's planned strength session",
    }
    assert [(item["code"], item["nutrient"]) for item in nutrition["actions"]] == [
        ("protein_below_target", "protein_g"),
        ("energy_below_target", "calories_kcal"),
        ("carbohydrate_below_target_for_training", "carbohydrate_g"),
    ]
    assert nutrition["nutrients"]["protein_g"]["remaining"] == "70"


def test_protein_below_range(home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _foods(capsys)
    _log(capsys, ("shake", "1", "count"))
    _target(capsys, "protein", "--range", "90", "110")

    section = _nutrition_section(_ok(capsys, "recommend", "--date", DAY))

    assert "  Protein       30 g; target 90-110 g (range): below range, 60 g to minimum, 80 g to maximum" in section
    assert [line for line in section if line.startswith("  -> ")] == [
        "  -> [protein_below_target] logged protein is below the configured range minimum; if meals remain today, "
        "include a protein source in them"
    ]


def test_protein_within_range_and_every_target_met_has_no_action(
    home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _foods(capsys)
    _log(capsys, ("shake", "1", "count"))
    _target(capsys, "protein", "--range", "25", "35")
    _target(capsys, "kcal", "--exact", "200")
    _target(capsys, "carbs", "--range", "5", "15")

    section = _nutrition_section(_ok(capsys, "recommend", "--date", DAY))

    assert "  Protein       30 g; target 25-35 g (range): within range, 5 g left to maximum" in section
    assert "  kcal          200; target 200 (exact): target reached" in section
    assert not any("->" in line for line in section)
    assert _recommend_json(capsys)["nutrition"]["actions"] == []


def test_carbohydrate_shortfall_on_a_rest_day_is_status_only(
    rest_home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _foods(capsys)
    _log(capsys, ("shake", "1", "count"))
    _target(capsys, "kcal", "--exact", "2000")
    _target(capsys, "carbs", "--exact", "250")

    section = _nutrition_section(_ok(capsys, "recommend", "--date", DAY))

    assert "  Carbohydrate  10 g; target 250 g (exact): below target, 240 g to go" in section
    actions = [line for line in section if line.startswith("  -> ")]
    assert actions == [
        "  -> [energy_below_target] logged energy is below the configured target; "
        "if meals remain today, aim to reach it"
    ]
    context = _recommend_json(capsys)["nutrition"]["training_context"]
    assert (context["strength_session_planned"], context["fuel_relevant"]) == (False, False)


def test_above_target_is_reported_factually_without_compensation(
    home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _foods(capsys)
    _log(capsys, ("shake", "2", "count"))
    _target(capsys, "protein", "--exact", "40")
    _target(capsys, "kcal", "--range", "100", "300")

    text = _ok(capsys, "recommend", "--date", DAY)
    section = _nutrition_section(text)

    assert "  Protein       60 g; target 40 g (exact): above target by 20 g" in section
    assert "  kcal          400; target 100-300 (range): above range by 100" in section
    assert not any("->" in line for line in section)
    assert not any(word in " ".join(section).lower() for word in ("skip", "burn", "extra", "cardio"))


# --- missing nutrient values ---------------------------------------------------------------


def test_missing_value_is_indeterminate_with_an_explicit_lower_bound(
    home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _foods(capsys)
    _log(capsys, ("shake", "1", "count"), ("mystery", "1", "count"))
    _target(capsys, "protein", "--exact", "100")

    text = _ok(capsys, "recommend", "--date", DAY)
    section = _nutrition_section(text)

    assert text.isascii()
    assert (
        "  Protein       incomplete (known items only: 30 g); target 100 g (exact): "
        "cannot tell yet (incomplete); remaining unknown"
    ) in section
    assert "    1 logged item has no protein value: the known amount is a lower bound, not a total" in section
    assert not any("->" in line for line in section)
    protein = _recommend_json(capsys)["nutrition"]["nutrients"]["protein_g"]
    assert protein["status"] == "indeterminate"
    assert (protein["consumed"], protein["known_subtotal"], protein["remaining"], protein["excess"]) == (
        None,
        "30",
        None,
        None,
    )
    assert protein["missing_items"] == [
        {"meal_id": "2026-03-16-breakfast-1", "sequence": 2, "food_id": "mystery", "food_name": "미스터리"}
    ]


def test_known_subtotal_equal_to_the_maximum_is_still_indeterminate(
    home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _foods(capsys)
    _log(capsys, ("shake", "1", "count"), ("mystery", "1", "count"))
    _target(capsys, "protein", "--range", "20", "30")

    protein = _recommend_json(capsys)["nutrition"]["nutrients"]["protein_g"]

    assert (protein["status"], protein["known_subtotal"], protein["excess"]) == ("indeterminate", "30", None)


def test_known_subtotal_above_the_maximum_proves_above_without_an_excess(
    home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _foods(capsys)
    _log(capsys, ("shake", "1", "count"), ("mystery", "1", "count"))
    _target(capsys, "protein", "--range", "20", "25")

    section = _nutrition_section(_ok(capsys, "recommend", "--date", DAY))
    nutrition = _recommend_json(capsys)["nutrition"]

    assert (
        "  Protein       incomplete (known items only: 30 g); target 20-25 g (range): "
        "above range (the known items alone exceed it; exact excess unknown)"
    ) in section
    protein = nutrition["nutrients"]["protein_g"]
    assert (protein["status"], protein["excess"], protein["remaining"]) == ("above_range", None, None)
    assert nutrition["actions"] == []


# --- contract, determinism, read-only ---------------------------------------------------------


def test_nutrients_are_exactly_the_nutrition_status_document(home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _foods(capsys)
    _log(capsys, ("shake", "1", "count"), ("mystery", "1", "count"))
    _target(capsys, "protein", "--exact", "100")
    _target(capsys, "carbs", "--range", "200", "260")

    nutrition = _recommend_json(capsys)["nutrition"]
    status = json.loads(_ok(capsys, "nutrition", "status", "--date", DAY, "--json"))

    assert nutrition["nutrients"] == status["nutrients"]
    assert (nutrition["date"], nutrition["timezone"], nutrition["scope"]) == (
        status["date"],
        status["timezone"],
        status["scope"],
    )
    assert (nutrition["meal_count"], nutrition["item_count"]) == (status["meal_count"], status["item_count"])
    assert list(nutrition) == [
        "guidance_version",
        "date",
        "timezone",
        "scope",
        "availability",
        "unavailable_reason",
        "meal_count",
        "item_count",
        "training_context",
        "nutrients",
        "actions",
    ]


def test_json_with_nutrition_is_deterministic_and_ascii(home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _foods(capsys)
    _log(capsys, ("shake", "1", "count"), ("mystery", "1", "count"))
    _target(capsys, "kcal", "--exact", "2000")

    first = _ok(capsys, "recommend", "--date", DAY, "--json")
    second = _ok(capsys, "recommend", "--date", DAY, "--json")

    assert first == second
    assert first.isascii()


_WAL_SIDECARS = ("-wal", "-shm")


def _home_state(root: Path) -> dict[str, str]:
    # SQLite itself may create empty WAL side files when any mode=ro connection (the analytics
    # reader included) opens a WAL database; they hold no data and are checked separately.
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file() and not path.name.endswith(_WAL_SIDECARS)
    }


def test_recommend_with_nutrition_never_writes(home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _foods(capsys)
    _log(capsys, ("shake", "1", "count"))
    _target(capsys, "protein", "--exact", "100")
    before = _home_state(home)
    targets_mtime = (home / "config" / "nutrition_targets.json").stat().st_mtime_ns

    _ok(capsys, "recommend", "--date", DAY)
    _ok(capsys, "recommend", "--date", DAY, "--json")

    assert _home_state(home) == before  # the database file, targets file and every other file
    wal = home / "db" / "muscle50.sqlite3-wal"
    assert not wal.exists() or wal.stat().st_size == 0  # nothing was written through the WAL either
    assert (home / "config" / "nutrition_targets.json").stat().st_mtime_ns == targets_mtime


def test_unreadable_targets_leave_the_training_plan_intact(home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    baseline = _training_only(_recommend_json(capsys))
    targets = home / "config" / "nutrition_targets.json"
    targets.parent.mkdir()
    targets.write_text("{not json", encoding="utf-8")

    section = _nutrition_section(_ok(capsys, "recommend", "--date", DAY))
    document = _recommend_json(capsys)

    assert section[1].startswith("  unavailable: nutrition target file ")
    assert section[1].endswith("The training plan above does not depend on nutrition.")
    nutrition = document["nutrition"]
    assert (nutrition["availability"], nutrition["nutrients"], nutrition["actions"]) == ("unavailable", None, [])
    assert nutrition["unavailable_reason"].startswith("nutrition target file ")
    assert _training_only(document) == baseline
    assert targets.read_text(encoding="utf-8") == "{not json"


@pytest.mark.parametrize("damage", ["directory", "not_utf8"])
def test_an_unopenable_targets_file_is_unavailable_not_a_crash(
    home: Path, capsys: pytest.CaptureFixture[str], damage: str
) -> None:
    baseline = _training_only(_recommend_json(capsys))
    targets = home / "config" / "nutrition_targets.json"
    targets.parent.mkdir()
    if damage == "directory":
        targets.mkdir()  # reading it raises an OSError (PermissionError on Windows)
    else:
        targets.write_bytes(b"\xff\xfe{}")  # e.g. saved as UTF-16 by an editor

    document = _recommend_json(capsys)

    nutrition = document["nutrition"]
    assert (nutrition["availability"], nutrition["nutrients"], nutrition["actions"]) == ("unavailable", None, [])
    assert nutrition["unavailable_reason"]
    assert _training_only(document) == baseline
    assert "unavailable: " in _ok(capsys, "recommend", "--date", DAY)


def test_nutrition_never_changes_the_training_recommendation(home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    database = home / "db" / "muscle50.sqlite3"
    DailyRecoveryRepository(database).migrate()
    capture = RecoveryCapture(
        capture_id=f"capture-{DAY}",
        requested_date=DAY,
        manifest_relative_path=f"recovery/{DAY}/manifest.json",
        artifacts=(RawArtifact("sleep", f"recovery/{DAY}/sleep.json", "application/json", "0" * 64, 2),),
    )
    DailyRecoveryRepository(database).save(recovery(DAY, training_readiness_level="POOR"), capture)
    baseline = _training_only(_recommend_json(capsys))
    assert baseline["strength"]["adjustment_level"] == "reduce"

    _foods(capsys)
    _log(capsys, ("shake", "1", "count"))
    _target(capsys, "protein", "--exact", "100")
    _target(capsys, "kcal", "--exact", "2000")
    _target(capsys, "carbs", "--exact", "250")
    document = _recommend_json(capsys)

    # Recovery still reduces the session and the plan is byte-for-byte the same; nutrition only adds advice.
    assert _training_only(document) == baseline
    nutrition = document["nutrition"]
    assert nutrition["training_context"]["fuel_relevant"] is False  # reduced session, easy next swim
    assert [item["code"] for item in nutrition["actions"]] == ["protein_below_target", "energy_below_target"]
    assert "fuel" not in nutrition["actions"][1]["message"]
