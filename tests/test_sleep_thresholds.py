"""Sleep thresholds as a user setting (AC7): defaults identical, custom values fire, CLI set/show/reset."""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import pytest
import sync_coverage_builders as builders
from analytics_builders import recovery

import muscle50.cli as cli
from muscle50.cli import main
from muscle50.domain.recovery import DailyRecovery
from muscle50.domain.recovery_assessment import (
    DEFAULT_SLEEP_THRESHOLDS,
    AdjustmentLevel,
    SleepThresholds,
    assess_recovery,
)
from muscle50.infrastructure.garmin.client import PythonGarminConnector

D = date(2026, 3, 16)


@pytest.fixture(autouse=True)
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "home"
    monkeypatch.setenv("MUSCLE50_HOME", str(root))
    monkeypatch.setattr(
        PythonGarminConnector, "authenticate", lambda *args, **kwargs: pytest.fail("must not use Garmin")
    )
    monkeypatch.setattr(cli, "_local_timezone", lambda day: builders.KST)
    monkeypatch.setattr(cli, "_today", lambda: builders.DAILY_TODAY)
    return root


def _run(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, str, str]:
    code = main(list(argv))
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def _rows(*sleep: int | None, score: int = 80) -> list[DailyRecovery]:
    return [
        recovery((D - timedelta(days=offset)).isoformat(), sleep_seconds=value, sleep_score=score)
        for offset, value in enumerate(sleep)
    ]


@pytest.mark.parametrize(
    "rows",
    [
        _rows(4 * 3600 - 1),
        _rows(5 * 3600 - 1),
        _rows(5 * 3600),
        _rows(None, 3 * 3600, 3 * 3600),
        _rows(None, 4 * 3600 + 1, 4 * 3600 + 1),
        _rows(27000, score=49),
        [],
    ],
)
def test_defaults_are_exactly_the_previous_behaviour(rows: list[DailyRecovery]) -> None:
    assert assess_recovery(D, rows) == assess_recovery(D, rows, DEFAULT_SLEEP_THRESHOLDS)
    assert SleepThresholds(18000, 14400, 50) == DEFAULT_SLEEP_THRESHOLDS


def test_a_custom_hold_threshold_fires_and_names_its_value() -> None:
    rows = _rows(5 * 3600 + 1800)  # 5.5 h: not short by default
    assert assess_recovery(D, rows).level is AdjustmentLevel.NORMAL
    custom = assess_recovery(D, rows, SleepThresholds(6 * 3600, 4 * 3600, 50))
    assert custom.level is AdjustmentLevel.HOLD
    (fired,) = custom.fired
    assert fired.rule == "sleep_seconds < 21600s"
    # The lookback uses the same thresholds.
    lookback = assess_recovery(
        D, _rows(None, 5 * 3600 + 1800, 5 * 3600 + 1800), SleepThresholds(6 * 3600, 4 * 3600, 50)
    )
    assert lookback.carried


SHOW_DEFAULT = [
    "Sleep thresholds of the training recovery rules (default):",
    "  hold below: 5 h of sleep (18000 s)",
    "  reduce below: 4 h of sleep (14400 s)",
    "  hold below sleep score: 50",
    "  These are design choices, not evidence [design; SLEEP-05: the evidence gives only the health",
    "  target of 7 h or more per night]. recommend and daily show nights under 7 h only with a goal set.",
]


def test_show_set_reset(home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert _run(capsys, "settings", "sleep", "show") == (0, "\n".join(SHOW_DEFAULT) + "\n", "")
    assert not home.exists()
    code, out, _err = _run(capsys, "settings", "sleep", "set", "--hold-below-hours", "6", "--hold-below-score", "40")
    assert code == 0
    assert out.split("\n")[:5] == [
        "Sleep thresholds set.",
        "Sleep thresholds of the training recovery rules (config\\sleep_thresholds.json, user setting):",
        "  hold below: 6 h of sleep (21600 s)",
        "  reduce below: 4 h of sleep (14400 s)",
        "  hold below sleep score: 40",
    ]
    code, document, _err = _run(capsys, "settings", "sleep", "show", "--json")
    assert json.loads(document) == {
        "sleep_thresholds_version": 1,
        "hold_below_seconds": 21600,
        "reduce_below_seconds": 14400,
        "hold_below_score": 40,
        "source": "user_setting",
        "evidence": ["design", "SLEEP-05"],
    }
    assert document == json.dumps(json.loads(document), indent=2) + "\n"
    # Merging: only the given flag changes.
    _run(capsys, "settings", "sleep", "set", "--reduce-below-hours", "4.25")
    stored = json.loads((home / "config" / "sleep_thresholds.json").read_text(encoding="utf-8"))
    assert stored["sleep_thresholds"] == {
        "hold_below_seconds": 21600,
        "reduce_below_seconds": 15300,
        "hold_below_score": 40,
    }
    assert sorted(path.relative_to(home).as_posix() for path in home.rglob("*")) == [
        "config",
        "config/sleep_thresholds.json",
    ]
    assert _run(capsys, "settings", "sleep", "reset") == (0, "Sleep thresholds reset to the defaults.\n", "")
    assert _run(capsys, "settings", "sleep", "reset") == (
        0,
        "Sleep thresholds were already the defaults. Nothing changed.\n",
        "",
    )
    assert _run(capsys, "settings", "sleep", "show")[1] == "\n".join(SHOW_DEFAULT) + "\n"


@pytest.mark.parametrize(
    ("argv", "message"),
    [
        (
            ("--reduce-below-hours", "5"),
            "--reduce-below-hours는 0보다 크고 hold 기준(--hold-below-hours)보다 작아야 합니다.",
        ),
        (
            ("--hold-below-hours", "3"),
            "--reduce-below-hours는 0보다 크고 hold 기준(--hold-below-hours)보다 작아야 합니다.",
        ),
        (("--hold-below-hours", "12.5"), "--hold-below-hours는 0보다 크고 12 이하여야 합니다."),
        (("--hold-below-hours", "5.0001"), "--hold-below-hours는 정수 초가 되는 시간이어야 합니다(예: 5, 5.5, 5.25)."),
        (("--hold-below-hours", "five"), "--hold-below-hours는 0 이상의 숫자여야 합니다(예: 18, 0.5)."),
        (("--hold-below-score", "0"), "--hold-below-score는 1~100 사이의 정수여야 합니다."),
        (("--hold-below-score", "49.5"), "--hold-below-score는 1~100 사이의 정수여야 합니다."),
        (("--hold-below-score", "101"), "--hold-below-score는 1~100 사이의 정수여야 합니다."),
    ],
)
@pytest.mark.parametrize("existing", [False, True])
def test_refusals_write_nothing(
    home: Path, capsys: pytest.CaptureFixture[str], argv: tuple[str, ...], message: str, existing: bool
) -> None:
    path = home / "config" / "sleep_thresholds.json"
    if existing:
        _run(capsys, "settings", "sleep", "set", "--hold-below-score", "45")
    before = path.read_bytes() if existing else None
    code, out, err = _run(capsys, "settings", "sleep", "set", *argv)
    assert (code, out, err) == (1, "", f"오류: {message} 아무것도 바꾸지 않았습니다.\n")
    if existing:
        assert path.read_bytes() == before
    else:
        assert not home.exists()


def test_set_without_a_flag_is_a_usage_error(home: Path) -> None:
    with pytest.raises(SystemExit) as error:
        main(["settings", "sleep", "set"])
    assert error.value.code == 2
    assert not home.exists()


def test_recommend_uses_the_custom_thresholds(home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    # The golden database's 2026-03-15 night is 7 h; a hold threshold of 7.5 h fires on it in the lookback.
    builders.build_recommend_database(home)
    golden = builders.golden(f"recommend_{builders.RECOMMEND_DATE}.txt")
    _run(capsys, "settings", "sleep", "set", "--hold-below-hours", "7.5")
    code, out, _err = _run(capsys, "recommend", "--date", builders.RECOMMEND_DATE)
    assert code == 0 and out != golden
    assert "    sleep_seconds [2026-03-15]: 07:00:00 -> hold (sleep_seconds < 27000s)" in out.split("\n")
    _run(capsys, "settings", "sleep", "reset")
    assert _run(capsys, "recommend", "--date", builders.RECOMMEND_DATE)[1] == golden
