"""The training goal and sleep threshold files: strict read, atomic write, never echo a value."""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from muscle50.domain.recovery_assessment import DEFAULT_SLEEP_THRESHOLDS, SleepThresholds
from muscle50.domain.training_goal import (
    DEFAULT_SLEEP_SETTING,
    GoalMode,
    GoalSettingsError,
    TrainingGoal,
    WeeklyRateRange,
)
from muscle50.infrastructure.training_goal_store import JsonSleepThresholdRepository, JsonTrainingGoalRepository

CUT = TrainingGoal(
    mode=GoalMode.CUT,
    target_body_fat_percent=Decimal("18"),
    target_date=date(2027, 2, 28),
    min_skeletal_muscle_mass_kg=Decimal("41"),
    weekly_loss_percent=WeeklyRateRange(Decimal("0.3"), Decimal("0.5")),
)
GOAL_DOCUMENT: dict[str, Any] = {
    "schema_version": 1,
    "goal": {
        "mode": "cut",
        "target_body_fat_percent": "18",
        "target_weight_kg": None,
        "target_date": "2027-02-28",
        "min_skeletal_muscle_mass_kg": "41",
        "weekly_loss_percent": {"minimum": "0.3", "maximum": "0.5"},
    },
}


def test_missing_file_means_no_goal_and_nothing_is_created(tmp_path: Path) -> None:
    path = tmp_path / "config" / "training_goal.json"
    assert JsonTrainingGoalRepository(path).load() is None
    assert JsonSleepThresholdRepository(tmp_path / "config" / "sleep.json").load() == DEFAULT_SLEEP_SETTING
    assert not (tmp_path / "config").exists()


def test_round_trip_writes_the_exact_document_with_lf(tmp_path: Path) -> None:
    path = tmp_path / "config" / "training_goal.json"
    repository = JsonTrainingGoalRepository(path)
    repository.save(CUT)
    assert repository.load() == CUT
    assert path.read_bytes() == (json.dumps(GOAL_DOCUMENT, indent=2) + "\n").encode("ascii")
    assert [item.name for item in path.parent.iterdir()] == ["training_goal.json"]  # no temporary left


def test_save_replaces_the_whole_document(tmp_path: Path) -> None:
    repository = JsonTrainingGoalRepository(tmp_path / "goal.json")
    repository.save(CUT)
    repository.save(TrainingGoal(GoalMode.GAIN))
    assert repository.load() == TrainingGoal(GoalMode.GAIN)


def test_delete_is_idempotent(tmp_path: Path) -> None:
    repository = JsonTrainingGoalRepository(tmp_path / "goal.json")
    repository.save(CUT)
    assert repository.delete() is True
    assert repository.delete() is False
    assert repository.load() is None


def test_a_passed_deadline_still_loads(tmp_path: Path) -> None:
    # `--by` must be after today only when it is set; a stored goal whose date has passed is valid.
    path = tmp_path / "goal.json"
    document = json.loads(json.dumps(GOAL_DOCUMENT))
    document["goal"]["target_date"] = "2020-01-01"
    path.write_text(json.dumps(document), encoding="utf-8")
    loaded = JsonTrainingGoalRepository(path).load()
    assert loaded is not None and loaded.target_date == date(2020, 1, 1)


SECRET = "73.1234"


def _goal_with(**changes: Any) -> dict[str, Any]:
    document: dict[str, Any] = json.loads(json.dumps(GOAL_DOCUMENT))
    document["goal"].update(changes)
    return document


@pytest.mark.parametrize(
    ("document", "key"),
    [
        (_goal_with(extra=SECRET), "goal must list exactly"),
        (_goal_with(mode=SECRET), "(mode)"),
        (_goal_with(target_body_fat_percent=73.1234), "(target_body_fat_percent)"),
        (_goal_with(target_body_fat_percent=SECRET), "(target_body_fat_percent)"),
        (_goal_with(target_body_fat_percent="-" + SECRET), "(target_body_fat_percent)"),
        (_goal_with(target_weight_kg=SECRET), "(target_weight_kg)"),  # both targets
        (_goal_with(target_date="2027-02-30" + SECRET), "(target_date)"),
        (_goal_with(target_date=20270228), "(target_date)"),
        (_goal_with(min_skeletal_muscle_mass_kg="1" + SECRET), "(min_skeletal_muscle_mass_kg)"),
        (_goal_with(weekly_loss_percent={"minimum": SECRET, "maximum": "0.5"}), "(weekly_loss_percent)"),
        (_goal_with(weekly_loss_percent={"minimum": "0.5", "maximum": "0.3"}), "(weekly_loss_percent)"),
        (_goal_with(mode="gain"), "(weekly_loss_percent)"),  # weekly loss outside cut
        ({"schema_version": 2, "goal": GOAL_DOCUMENT["goal"]}, "(schema_version)"),
        ({"schema_version": 1}, "expected exactly the keys"),
        ([SECRET], "expected exactly the keys"),
    ],
)
def test_invalid_goal_files_name_the_key_but_never_the_value(tmp_path: Path, document: object, key: str) -> None:
    path = tmp_path / "goal.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    before = path.read_bytes()
    with pytest.raises(GoalSettingsError) as error:
        JsonTrainingGoalRepository(path).load()
    message = str(error.value)
    assert key in message
    assert SECRET not in message
    assert error.value.__cause__ is None and error.value.__suppress_context__
    assert path.read_bytes() == before


@pytest.mark.parametrize("content", [b"{not json " + SECRET.encode(), b"\xff\xfe" + SECRET.encode()])
def test_unreadable_goal_files_are_refused(tmp_path: Path, content: bytes) -> None:
    path = tmp_path / "goal.json"
    path.write_bytes(content)
    with pytest.raises(GoalSettingsError) as error:
        JsonTrainingGoalRepository(path).load()
    assert SECRET not in str(error.value)


def test_sleep_thresholds_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "config" / "sleep_thresholds.json"
    repository = JsonSleepThresholdRepository(path)
    custom = SleepThresholds(21600, 14400, 50)
    repository.save(custom)
    loaded = repository.load()
    assert (loaded.thresholds, loaded.source) == (custom, "user_setting")
    assert json.loads(path.read_text(encoding="utf-8")) == {
        "schema_version": 1,
        "sleep_thresholds": {"hold_below_seconds": 21600, "reduce_below_seconds": 14400, "hold_below_score": 50},
    }
    assert repository.delete() is True
    assert repository.load().thresholds == DEFAULT_SLEEP_THRESHOLDS


@pytest.mark.parametrize(
    ("body", "key"),
    [
        ({"hold_below_seconds": 18000.5, "reduce_below_seconds": 14400, "hold_below_score": 50}, "hold_below_seconds"),
        ({"hold_below_seconds": "18000", "reduce_below_seconds": 14400, "hold_below_score": 50}, "hold_below_seconds"),
        ({"hold_below_seconds": 18000, "reduce_below_seconds": 18000, "hold_below_score": 50}, "reduce_below_seconds"),
        ({"hold_below_seconds": 43201, "reduce_below_seconds": 14400, "hold_below_score": 50}, "hold_below_seconds"),
        ({"hold_below_seconds": 18000, "reduce_below_seconds": 14400, "hold_below_score": 101}, "hold_below_score"),
        ({"hold_below_seconds": 18000, "reduce_below_seconds": 14400, "hold_below_score": True}, "hold_below_score"),
        ({"hold_below_seconds": 18000, "reduce_below_seconds": 14400}, "sleep_thresholds must list exactly"),
    ],
)
def test_invalid_sleep_files_name_the_key(tmp_path: Path, body: dict[str, object], key: str) -> None:
    path = tmp_path / "sleep.json"
    path.write_text(json.dumps({"schema_version": 1, "sleep_thresholds": body}), encoding="utf-8")
    with pytest.raises(GoalSettingsError) as error:
        JsonSleepThresholdRepository(path).load()
    assert key in str(error.value)
    assert "18000.5" not in str(error.value)
