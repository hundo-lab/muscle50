"""`muscle50 goal set|show|unset` (AC1): exact output, refusals that write nothing, no database."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

import muscle50.cli as cli
from muscle50.cli import main
from muscle50.infrastructure.garmin.client import PythonGarminConnector

TODAY = date(2026, 10, 26)
CUT_ARGS = (
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
CUT_LINES = [
    "Training goal (config\\training_goal.json, user setting):",
    "  mode: cut",
    "  target body fat: 18 % by 2027-02-28",
    "  skeletal muscle mass floor: 41 kg",
    "  weekly loss target: 0.3-0.5 %/week (evidence range 0.5-1.0 %/week [MAINT-05])",
    "  effects: progression keeps load and reps (maintain_load [MAINT-02]); goal lines in recommend/daily;",
    "  cut references in nutrition status. Nutrition targets and the training plan are not changed.",
]
CUT_DOCUMENT = {
    "goal_version": 1,
    "goal": {
        "mode": "cut",
        "target_body_fat_percent": "18",
        "target_weight_kg": None,
        "target_date": "2027-02-28",
        "min_skeletal_muscle_mass_kg": "41",
        "weekly_loss_percent": {"minimum": "0.3", "maximum": "0.5"},
    },
}


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


def test_show_without_a_goal(home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert _run(capsys, "goal", "show") == (
        0,
        "No training goal set. recommend and daily use the default rules (gain).\n",
        "",
    )
    assert _run(capsys, "goal", "show", "--json") == (0, '{\n  "goal_version": 1,\n  "goal": null\n}\n', "")
    assert not home.exists()  # a read creates nothing


def test_set_then_show_text_and_json(home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, out, err = _run(capsys, *CUT_ARGS)
    assert (code, err) == (0, "")
    assert out.split("\n") == ["Training goal set.", *CUT_LINES, ""]

    shown = _run(capsys, "goal", "show")
    assert shown == (0, "\n".join(CUT_LINES) + "\n", "")
    assert _run(capsys, "goal", "show") == shown  # deterministic
    code, document, _err = _run(capsys, "goal", "show", "--json")
    assert document == json.dumps(CUT_DOCUMENT, indent=2) + "\n"
    assert out.isascii() and document.isascii()
    # Only the settings file is created: no database, no Garmin auth, no RAW directories.
    assert sorted(path.relative_to(home).as_posix() for path in home.rglob("*")) == [
        "config",
        "config/training_goal.json",
    ]


def test_set_json_prints_the_stored_goal(capsys: pytest.CaptureFixture[str]) -> None:
    code, out, _err = _run(capsys, *CUT_ARGS, "--json")
    assert (code, out) == (0, json.dumps(CUT_DOCUMENT, indent=2) + "\n")


@pytest.mark.parametrize(
    ("argv", "lines"),
    [
        (
            ("--mode", "gain"),
            [
                "  mode: gain",
                "  target: not set",
                "  skeletal muscle mass floor: not set",
                "  effects: progression unchanged (the default gain rules); goal lines in recommend/daily.",
                "  Nutrition targets and the training plan are not changed.",
            ],
        ),
        (
            ("--mode", "maintain", "--target-weight", "75.5", "--by", "2027-01-01"),
            [
                "  mode: maintain",
                "  target weight: 75.5 kg by 2027-01-01",
                "  skeletal muscle mass floor: not set",
                "  effects: progression unchanged (the default gain rules); goal lines in recommend/daily.",
                "  Nutrition targets and the training plan are not changed.",
            ],
        ),
        (
            ("--mode", "cut", "--target-body-fat", "20"),
            [
                "  mode: cut",
                "  target body fat: 20 %",
                "  skeletal muscle mass floor: not set",
                "  weekly loss target: not set (evidence range 0.5-1.0 %/week [MAINT-05])",
                "  effects: progression keeps load and reps (maintain_load [MAINT-02]); goal lines in recommend/daily;",
                "  cut references in nutrition status. Nutrition targets and the training plan are not changed.",
            ],
        ),
    ],
)
def test_other_goals(capsys: pytest.CaptureFixture[str], argv: tuple[str, ...], lines: list[str]) -> None:
    code, out, _err = _run(capsys, "goal", "set", *argv)
    assert code == 0
    assert out.split("\n")[2:-1] == lines


def test_set_replaces_the_whole_goal(home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _run(capsys, *CUT_ARGS)
    _run(capsys, "goal", "set", "--mode", "maintain")
    document = json.loads(_goal_file(home).read_text(encoding="utf-8"))
    assert document["goal"] == {
        "mode": "maintain",
        "target_body_fat_percent": None,
        "target_weight_kg": None,
        "target_date": None,
        "min_skeletal_muscle_mass_kg": None,
        "weekly_loss_percent": None,
    }


REFUSALS = [
    (("--mode", "cut", "--target-body-fat", "2"), "--target-body-fat은 3~60 사이여야 합니다."),
    (("--mode", "cut", "--target-body-fat", "61"), "--target-body-fat은 3~60 사이여야 합니다."),
    (("--mode", "cut", "--target-body-fat", "x18"), "--target-body-fat는 0 이상의 숫자여야 합니다(예: 18, 0.5)."),
    (("--mode", "cut", "--target-body-fat", "-5"), "--target-body-fat는 0 이상의 숫자여야 합니다(예: 18, 0.5)."),
    (
        ("--mode", "cut", "--target-body-fat", "18", "--target-weight", "70"),
        "--target-body-fat와 --target-weight는 함께 쓸 수 없습니다(목표는 하나만).",
    ),
    (("--mode", "cut", "--by", "2027-02-28"), "--by에는 목표(--target-body-fat 또는 --target-weight)가 필요합니다."),
    (("--mode", "cut", "--target-body-fat", "18", "--by", "2026-10-26"), "--by는 오늘 이후 날짜여야 합니다."),
    (("--mode", "cut", "--target-body-fat", "18", "--by", "2027-2-28"), "--by는 YYYY-MM-DD 형식이어야 합니다."),
    (("--mode", "gain", "--weekly-loss", "0.3", "0.5"), "--weekly-loss는 --mode cut에서만 쓸 수 있습니다."),
    (("--mode", "cut", "--weekly-loss", "0.5", "0.3"), "--weekly-loss는 MIN <= MAX여야 합니다."),
    (("--mode", "cut", "--weekly-loss", "0.01", "0.5"), "--weekly-loss은 0.05~2.0 사이여야 합니다."),
    (("--mode", "cut", "--min-smm", "9"), "--min-smm은 10~100 사이여야 합니다."),
    (("--mode", "cut", "--target-weight", "251"), "--target-weight은 30~250 사이여야 합니다."),
]


@pytest.mark.parametrize(("argv", "message"), REFUSALS)
@pytest.mark.parametrize("existing", [False, True])
def test_refusals_exit_1_and_write_nothing(
    home: Path, capsys: pytest.CaptureFixture[str], argv: tuple[str, ...], message: str, existing: bool
) -> None:
    if existing:
        _run(capsys, *CUT_ARGS)
    before = _goal_file(home).read_bytes() if existing else None

    code, out, err = _run(capsys, "goal", "set", *argv)

    assert (code, out) == (1, "")
    assert err == f"오류: {message} 아무것도 바꾸지 않았습니다.\n"
    if existing:
        assert _goal_file(home).read_bytes() == before
    else:
        assert not home.exists()


@pytest.mark.parametrize(
    "argv",
    [
        ("goal", "set"),
        ("goal", "set", "--mode", "bulk"),
        ("goal", "set", "--mode", "cut", "--weekly-loss", "0.3"),
        ("goal",),
        ("goal", "show", "--date", "2026-10-26"),
    ],
)
def test_argparse_errors_exit_2(home: Path, argv: tuple[str, ...]) -> None:
    with pytest.raises(SystemExit) as error:
        main(list(argv))
    assert error.value.code == 2
    assert not home.exists()


def test_unset_is_idempotent(home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _run(capsys, *CUT_ARGS)
    assert _run(capsys, "goal", "unset") == (
        0,
        "Training goal removed. recommend and daily use the default rules (gain).\n",
        "",
    )
    assert not _goal_file(home).exists()
    assert _run(capsys, "goal", "unset") == (
        0,
        "No training goal set. recommend and daily use the default rules (gain). Nothing changed.\n",
        "",
    )
    code, out, _err = _run(capsys, "goal", "unset", "--json")
    assert json.loads(out) == {"goal_version": 1, "goal": None, "removed": False}


def test_show_refuses_an_invalid_file_without_echoing_it(home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = _goal_file(home)
    path.parent.mkdir(parents=True)
    path.write_text('{"schema_version": 1, "goal": {"mode": "secret-value"}}', encoding="utf-8")
    code, out, err = _run(capsys, "goal", "show")
    assert (code, out) == (1, "")
    assert err.startswith("오류: training goal file ") and err.endswith(
        "is not valid (goal must list exactly "
        "mode, target_body_fat_percent, "
        "target_weight_kg, target_date, "
        "min_skeletal_muscle_mass_kg, "
        "weekly_loss_percent)\n"
    )
    assert "secret-value" not in err
    # `goal set` replaces an invalid file (the way out of it).
    assert _run(capsys, "goal", "set", "--mode", "gain")[0] == 0
    assert _run(capsys, "goal", "show")[0] == 0
