"""`nutrition meal replace-item MEAL --item-number N --general [--general-note TEXT] --general-estimate SPEC
[--general-estimate-ref TEXT]` (Telegram LLM v2.3): a general item is corrected by replacing it, so the estimate and the
memo of the new item come from the same SPEC grammar as `nutrition log --general-estimate`. The old item and its
estimate fact stay stored (append-only; a removal row hides the old item). Temporary MUSCLE50_HOME, synthetic values."""

from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timedelta, timezone, tzinfo
from pathlib import Path
from typing import Any

import pytest

import muscle50.cli as cli
from muscle50.cli import main
from muscle50.infrastructure.garmin.client import PythonGarminConnector

KST = timezone(timedelta(hours=9))
DAY = "2026-10-14"
NOW = datetime(2026, 10, 14, 9, 0, tzinfo=KST)
MEAL = "2026-10-14-breakfast-1"
CHICKEN = (
    ["--id", "chicken-breast", "--name", "닭가슴살", "--per", "100", "g"]
    + ["--kcal", "110", "--protein", "23", "--carbs", "0", "--fat", "1.5"]
    + ["--source", "nutrition_label", "--accuracy", "exact"]
)
OLD_SPEC = "language_estimate:kcal=180-200,protein=5-6"
NEW_SPEC = "visual_estimate:kcal=185-185,protein=5-5,carbs=37-37,fat=2-2"
REPLACE = ("nutrition", "meal", "replace-item", MEAL, "--item-number", "1", "--general")


@pytest.fixture(autouse=True)
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "home"
    monkeypatch.setenv("MUSCLE50_HOME", str(root))
    monkeypatch.setattr(
        PythonGarminConnector, "authenticate", lambda *args, **kwargs: pytest.fail("nutrition must not use Garmin")
    )

    def fixed_timezone(day: date) -> tzinfo:
        return KST

    monkeypatch.setattr(cli, "_local_timezone", fixed_timezone)
    monkeypatch.setattr(cli, "_today", lambda: date(2026, 10, 14))
    monkeypatch.setattr(cli, "_now", lambda: NOW)
    return root


def run(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, str, str]:
    code = main(list(argv))
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def ok(capsys: pytest.CaptureFixture[str], *argv: str) -> str:
    code, out, err = run(capsys, *argv)
    assert code == 0, err
    return out


def usage_error(capsys: pytest.CaptureFixture[str], *argv: str) -> str:
    with pytest.raises(SystemExit) as raised:
        main(list(argv))
    assert raised.value.code == 2
    return capsys.readouterr().err


def refused(capsys: pytest.CaptureFixture[str], *argv: str) -> str:
    code, out, err = run(capsys, *argv)
    assert (code, out) == (1, ""), err
    assert err.startswith("오류: ")
    return err.removeprefix("오류: ").removesuffix("\n")


def tables(home: Path) -> dict[str, list[tuple[Any, ...]]]:
    database = home / "db" / "muscle50.sqlite3"
    if not database.exists():
        return {}
    connection = sqlite3.connect(database)
    try:
        names = [
            row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name")
        ]
        return {name: sorted(connection.execute(f"SELECT * FROM {name}").fetchall(), key=repr) for name in names}
    finally:
        connection.close()


def logged(capsys: pytest.CaptureFixture[str]) -> None:
    """Breakfast with one estimated general item (the item to correct)."""
    ok(
        capsys,
        *("nutrition", "log", "--date", DAY, "--meal", "breakfast"),
        *("--general", "--general-note=삼각김밥", f"--general-estimate={OLD_SPEC}", "--general-estimate-ref=old ref"),
    )


# --- the happy path ------------------------------------------------------------------------------------------------


def test_the_estimate_and_the_memo_of_a_general_item_are_replaced(
    capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    logged(capsys)
    out = ok(
        capsys,
        *REPLACE,
        "--general-note",
        "깻잎닭갈비 삼각김밥 1개",
        f"--general-estimate={NEW_SPEC}",
        "--general-estimate-ref=라벨 사진",
    )
    assert out.split("\n")[:5] == [
        f"Replaced item 1 of meal {MEAL} with item 2.",
        "",
        f"[breakfast] {MEAL} (2026-10-14, time not recorded)",
        "  2. 일반식 (general meal; note: 깻잎닭갈비 삼각김밥 1개): "
        "estimated kcal 185-185 | P 5-5 g | C 37-37 g | F 2-2 g",
        "     source: visual_estimate/estimated",
    ]
    shown = json.loads(ok(capsys, "nutrition", "meal", "show", MEAL, "--json"))
    (entry,) = shown["items"]  # the replaced item is hidden
    assert entry["sequence"] == 2 and entry["note"] == "깻잎닭갈비 삼각김밥 1개"
    assert entry["facts"][0]["source_reference"] == "라벨 사진"
    kcal = entry["nutrients"]["calories_kcal"]
    assert (kcal["minimum"], kcal["maximum"], kcal["value"]) == ("185", "185", None)
    day = ok(capsys, "nutrition", "day", "--date", DAY)
    assert "kcal 185-185" in day and "180-200" not in day  # the day shows the new value


def test_the_old_item_and_its_estimate_stay_stored_for_audit(capsys: pytest.CaptureFixture[str], home: Path) -> None:
    logged(capsys)
    before = tables(home)
    ok(capsys, *REPLACE, f"--general-estimate={NEW_SPEC}")
    after = tables(home)
    assert after["nutrition_meal_items"][0] in before["nutrition_meal_items"]
    old_fact = before["nutrition_facts"][0]
    assert old_fact in after["nutrition_facts"] and len(after["nutrition_facts"]) == 2
    assert after["nutrition_meal_item_removals"] and len(after["nutrition_meal_item_removals"]) == 1
    # nothing else in the history changed
    for name in ("nutrition_meals", "nutrition_food_profiles"):
        assert after[name] == before[name]


def test_the_default_reference_is_that_of_log_general_estimate(capsys: pytest.CaptureFixture[str], home: Path) -> None:
    logged(capsys)
    ok(capsys, *REPLACE, f"--general-estimate={NEW_SPEC}")
    shown = json.loads(ok(capsys, "nutrition", "meal", "show", MEAL, "--json"))
    twin = ok(
        capsys,
        *("nutrition", "log", "--date", "2026-10-13", "--meal", "dinner"),
        *("--general", f"--general-estimate={NEW_SPEC}"),
    )
    assert twin.startswith("Recorded meal 2026-10-13-dinner-1.")
    other = json.loads(ok(capsys, "nutrition", "meal", "show", "2026-10-13-dinner-1", "--json"))
    assert shown["items"][0]["facts"][0]["source_reference"] == other["items"][0]["facts"][0]["source_reference"]


def test_the_rows_equal_those_of_log_general_estimate_on_a_twin_home(
    capsys: pytest.CaptureFixture[str], home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    logged(capsys)
    ok(capsys, *REPLACE, "--general-note=삼각김밥 1개", f"--general-estimate={NEW_SPEC}", "--general-estimate-ref=ref")
    replaced = tables(home)
    twin = tmp_path / "twin"
    monkeypatch.setenv("MUSCLE50_HOME", str(twin))
    ok(
        capsys,
        *("nutrition", "log", "--date", DAY, "--meal", "breakfast"),
        *("--general", "--general-note=삼각김밥 1개", f"--general-estimate={NEW_SPEC}", "--general-estimate-ref=ref"),
    )
    direct = tables(twin)
    # the same estimate fact except its item position (the replaced item is item 2 of its meal)
    assert replaced["nutrition_facts"][1][3:] == direct["nutrition_facts"][0][3:]


def test_json_is_the_meal_show_document_and_runs_are_deterministic(
    capsys: pytest.CaptureFixture[str], home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    logged(capsys)
    first = ok(capsys, *REPLACE, f"--general-estimate={NEW_SPEC}", "--json")
    shown = ok(capsys, "nutrition", "meal", "show", MEAL, "--json")
    assert first == shown  # the same document `meal show --json` prints
    monkeypatch.setenv("MUSCLE50_HOME", str(tmp_path / "twin"))
    logged(capsys)
    assert ok(capsys, *REPLACE, f"--general-estimate={NEW_SPEC}", "--json") == first


# --- refusals ----------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("argv", "message"),
    [
        (
            ("--item", "chicken-breast", "100", "g", f"--general-estimate={NEW_SPEC}"),
            "argument --general-estimate: requires --general",
        ),
        (
            ("--general", "--general-estimate-ref=x"),
            "argument --general-estimate-ref: requires --general-estimate",
        ),
        (
            ("--item", "chicken-breast", "100", "g", "--general-estimate-ref=x"),
            "argument --general-estimate-ref: requires --general-estimate",
        ),
    ],
)
def test_misused_options_are_usage_errors_and_write_nothing(
    capsys: pytest.CaptureFixture[str], home: Path, argv: tuple[str, ...], message: str
) -> None:
    ok(capsys, "nutrition", "food", "add", *CHICKEN)
    logged(capsys)
    rows = tables(home)
    base = ("nutrition", "meal", "replace-item", MEAL, "--item-number", "1")
    err = usage_error(capsys, *base, *argv)
    assert err.rstrip("\n").endswith(f"error: {message}")
    assert "usage: muscle50 nutrition meal replace-item" in err
    assert tables(home) == rows


@pytest.mark.parametrize(
    ("spec", "message"),
    [
        ("visual_estimate:kcal=300-200", "min"),
        ("visual_estimate:kcal=x-200", "kcal"),
        ("web_estimate:kcal=100-200", "--general-estimate source must be visual_estimate or language_estimate"),
        ("visual_estimate", "--general-estimate"),
    ],
)
def test_a_bad_estimate_is_refused_with_nothing_changed(
    capsys: pytest.CaptureFixture[str], home: Path, spec: str, message: str
) -> None:
    logged(capsys)
    rows = tables(home)
    error = refused(capsys, *REPLACE, f"--general-estimate={spec}")
    assert message in error and error.endswith("Nothing was changed.")
    assert tables(home) == rows


def test_a_voided_meal_and_an_unknown_item_number_are_refused_as_before(
    capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    logged(capsys)
    rows = tables(home)
    missing = ("nutrition", "meal", "replace-item", MEAL, "--item-number", "9", "--general")
    error = refused(capsys, *missing, f"--general-estimate={NEW_SPEC}")
    assert "item 9" in error
    assert tables(home) == rows
    ok(capsys, "nutrition", "meal", "void", MEAL)
    rows = tables(home)
    assert "voided" in refused(capsys, *REPLACE, f"--general-estimate={NEW_SPEC}")
    assert tables(home) == rows


# --- unchanged neighbours ---------------------------------------------------------------------------------------------


def test_replace_item_without_the_new_options_is_unchanged(capsys: pytest.CaptureFixture[str], home: Path) -> None:
    logged(capsys)
    out = ok(capsys, *REPLACE, "--general-note", "제육")
    assert out.split("\n")[:4] == [
        f"Replaced item 1 of meal {MEAL} with item 2.",
        "",
        f"[breakfast] {MEAL} (2026-10-14, time not recorded)",
        "  2. 일반식 (general meal; note: 제육): nutrition unknown",
    ]


def test_the_help_lists_the_two_options(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        main(["nutrition", "meal", "replace-item", "--help"])
    help_text = capsys.readouterr().out
    assert "--general-estimate SPEC" in help_text and "--general-estimate-ref TEXT" in help_text
    assert "just before it" not in help_text  # these are plain options of replace-item, not positional
