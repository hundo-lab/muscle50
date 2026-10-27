"""`goal set --plateau-weeks N` and the goal file schema 2 (Aerobic Guide v1, D2).

A goal without the setting keeps writing schema 1 byte for byte; schema 2 is written only when the
setting is given, and each schema is read with its own exact key set.
"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

import muscle50.cli as cli
from muscle50.cli import main
from muscle50.domain.training_goal import (
    GoalMode,
    GoalSettingsError,
    TrainingGoal,
    TrainingGoalError,
    WeeklyRateRange,
    validate_goal,
)
from muscle50.infrastructure.garmin.client import PythonGarminConnector
from muscle50.infrastructure.training_goal_store import JsonSleepThresholdRepository, JsonTrainingGoalRepository

TODAY = date(2026, 10, 27)
CUT = (
    "goal",
    "set",
    "--mode",
    "cut",
    "--target-body-fat",
    "18",
    "--by",
    "2027-02-28",
    "--min-smm",
    "41",
    "--weekly-loss",
    "0.3",
    "0.5",
)
V1_GOAL: dict[str, Any] = {
    "mode": "cut",
    "target_body_fat_percent": "18",
    "target_weight_kg": None,
    "target_date": "2027-02-28",
    "min_skeletal_muscle_mass_kg": "41",
    "weekly_loss_percent": {"minimum": "0.3", "maximum": "0.5"},
}
V2_GOAL: dict[str, Any] = {**V1_GOAL, "plateau_weeks": 3}
PLATEAU_LINES = [
    "Training goal (config\\training_goal.json, user setting):",
    "  mode: cut",
    "  target body fat: 18 % by 2027-02-28",
    "  skeletal muscle mass floor: 41 kg",
    "  weekly loss target: 0.3-0.5 %/week (evidence range 0.5-1.0 %/week [MAINT-05])",
    "  plateau check: 3 weeks below 0.3 %/week loss, at least 2 InBody intervals (user setting [design]; "
    "no evidence-based definition [PLAT-01])",
    "  effects: progression keeps load and reps (maintain_load [MAINT-02]); goal lines in recommend/daily;",
    "  cut references in nutrition status. Nutrition targets and the training plan are not changed.",
]


@pytest.fixture(autouse=True)
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "home"
    monkeypatch.setenv("MUSCLE50_HOME", str(root))
    monkeypatch.setattr(
        PythonGarminConnector, "authenticate", lambda *args, **kwargs: pytest.fail("goal must not use Garmin")
    )
    monkeypatch.setattr(cli, "_today", lambda: TODAY)
    return root


def _run(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, str, str]:
    code = main(list(argv))
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def _goal_file(home: Path) -> Path:
    return home / "config" / "training_goal.json"


def _bytes(document: dict[str, Any]) -> bytes:
    return (json.dumps(document, indent=2) + "\n").encode("ascii")


def test_set_with_plateau_weeks_writes_schema_2_and_shows_the_setting(
    home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, out, err = _run(capsys, *CUT, "--plateau-weeks", "3")
    assert (code, err) == (0, "")
    assert out == "Training goal set.\n" + "\n".join(PLATEAU_LINES) + "\n"
    assert out.isascii()
    assert _goal_file(home).read_bytes() == _bytes({"schema_version": 2, "goal": V2_GOAL})
    assert _run(capsys, "goal", "show") == (0, "\n".join(PLATEAU_LINES) + "\n", "")
    expected_json = json.dumps({"goal_version": 1, "goal": V2_GOAL}, indent=2) + "\n"
    assert _run(capsys, "goal", "show", "--json") == (0, expected_json, "")
    assert _run(capsys, *CUT, "--plateau-weeks", "3", "--json") == (0, expected_json, "")


def test_set_without_plateau_weeks_writes_exactly_schema_1(home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _run(capsys, *CUT, "--plateau-weeks", "3")
    assert _run(capsys, *CUT)[0] == 0  # the whole document is replaced (D7): the setting is dropped
    assert _goal_file(home).read_bytes() == _bytes({"schema_version": 1, "goal": V1_GOAL})
    code, out, _err = _run(capsys, "goal", "show")
    assert code == 0 and "plateau" not in out


@pytest.mark.parametrize(
    ("argv", "message"),
    [
        (
            ("goal", "set", "--mode", "gain", "--plateau-weeks", "3"),
            "--plateau-weeks는 --mode cut과 --weekly-loss가 있어야 합니다.",
        ),
        (
            ("goal", "set", "--mode", "maintain", "--plateau-weeks", "3"),
            "--plateau-weeks는 --mode cut과 --weekly-loss가 있어야 합니다.",
        ),
        (
            ("goal", "set", "--mode", "cut", "--target-body-fat", "18", "--plateau-weeks", "3"),
            "--plateau-weeks는 --mode cut과 --weekly-loss가 있어야 합니다.",
        ),
        ((*CUT, "--plateau-weeks", "1"), "--plateau-weeks는 2~26 사이의 정수여야 합니다."),
        ((*CUT, "--plateau-weeks", "27"), "--plateau-weeks는 2~26 사이의 정수여야 합니다."),
        ((*CUT, "--plateau-weeks", "-4"), "--plateau-weeks는 2~26 사이의 정수여야 합니다."),
    ],
)
@pytest.mark.parametrize("existing", [False, True])
def test_refusals_exit_1_and_write_nothing(
    home: Path, capsys: pytest.CaptureFixture[str], argv: tuple[str, ...], message: str, existing: bool
) -> None:
    if existing:
        assert _run(capsys, *CUT)[0] == 0
        before = _goal_file(home).read_bytes()
    code, out, err = _run(capsys, *argv)
    assert (code, out) == (1, "")
    assert err == f"오류: {message} 아무것도 바꾸지 않았습니다.\n"
    if existing:
        assert _goal_file(home).read_bytes() == before
    else:
        assert not home.exists()


def test_a_non_integer_is_an_argparse_error(home: Path) -> None:
    with pytest.raises(SystemExit) as error:
        main([*CUT, "--plateau-weeks", "x"])
    assert error.value.code == 2
    assert not home.exists()


# --- the store -----------------------------------------------------------------------------------

SECRET = 19


def test_the_store_reads_schema_1_and_schema_2(tmp_path: Path) -> None:
    path = tmp_path / "goal.json"
    path.write_bytes(_bytes({"schema_version": 1, "goal": V1_GOAL}))
    v1 = JsonTrainingGoalRepository(path).load()
    assert v1 is not None and v1.plateau_weeks is None
    path.write_bytes(_bytes({"schema_version": 2, "goal": V2_GOAL}))
    v2 = JsonTrainingGoalRepository(path).load()
    assert v2 is not None and v2.plateau_weeks == 3
    JsonTrainingGoalRepository(path).save(v2)
    assert path.read_bytes() == _bytes({"schema_version": 2, "goal": V2_GOAL})


def _v2_with(**changes: Any) -> dict[str, Any]:
    return {"schema_version": 2, "goal": {**V2_GOAL, **changes}}


@pytest.mark.parametrize(
    ("document", "key"),
    [
        ({"schema_version": 2, "goal": V1_GOAL}, "goal must list exactly"),  # v2 without the key
        ({"schema_version": 1, "goal": {**V1_GOAL, "plateau_weeks": SECRET}}, "goal must list exactly"),
        (_v2_with(plateau_weeks=None), "(plateau_weeks)"),
        (_v2_with(plateau_weeks=True), "(plateau_weeks)"),
        (_v2_with(plateau_weeks=str(SECRET)), "(plateau_weeks)"),
        (_v2_with(plateau_weeks=float(SECRET)), "(plateau_weeks)"),
        (_v2_with(plateau_weeks=SECRET * 100), "(plateau_weeks)"),
        (_v2_with(plateau_weeks=SECRET, weekly_loss_percent=None), "(plateau_weeks)"),
        (_v2_with(plateau_weeks=SECRET, mode="gain", weekly_loss_percent=None), "(plateau_weeks)"),
        ({"schema_version": 3, "goal": V2_GOAL}, "(schema_version)"),
    ],
)
def test_invalid_plateau_files_name_the_key_but_never_the_value(tmp_path: Path, document: object, key: str) -> None:
    path = tmp_path / "goal.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    before = path.read_bytes()
    with pytest.raises(GoalSettingsError) as error:
        JsonTrainingGoalRepository(path).load()
    message = str(error.value)
    assert key in message
    assert str(SECRET) not in message
    assert path.read_bytes() == before


def test_the_sleep_file_stays_schema_1_only(tmp_path: Path) -> None:
    path = tmp_path / "sleep.json"
    body = {"hold_below_seconds": 18000, "reduce_below_seconds": 14400, "hold_below_score": 50}
    path.write_text(json.dumps({"schema_version": 2, "sleep_thresholds": body}), encoding="utf-8")
    with pytest.raises(GoalSettingsError, match=r"\(schema_version\)"):
        JsonSleepThresholdRepository(path).load()


def test_a_goal_value_object_with_a_bool_is_refused() -> None:
    goal = TrainingGoal(
        GoalMode.CUT, weekly_loss_percent=WeeklyRateRange(Decimal("0.3"), Decimal("0.5")), plateau_weeks=True
    )
    with pytest.raises(TrainingGoalError) as error:
        validate_goal(goal)
    assert error.value.key == "plateau_weeks"
