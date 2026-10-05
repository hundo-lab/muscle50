"""`muscle50 nutrition meal void/edit/merge`: correcting a whole logged meal.

Runs over a temporary MUSCLE50_HOME / temporary SQLite database only. All nutrition values are
synthetic test numbers. The central guarantees: nothing stored is updated or deleted (every
correction is an appended row), the meal ID never changes, item snapshots are never recalculated,
a voided meal drops out of day/status/recommend at once but stays visible in `meal show`, a merge
keeps the day's exact totals, and a refused correction writes nothing at all.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable
from datetime import date, datetime, timedelta, timezone, tzinfo
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from analytics_builders import activity, strength_set

import muscle50.cli as cli
from muscle50.application.meal_corrections import MergeMeals, copy_item_for_merge
from muscle50.cli import main
from muscle50.domain.activity import ActivityType, NormalizedActivity
from muscle50.domain.meal_history import MealRevision
from muscle50.domain.nutrition import (
    Accuracy,
    MealType,
    NutritionFact,
    NutritionProvenance,
    NutritionSourceType,
    NutritionValue,
    QuantityUnit,
)
from muscle50.infrastructure.garmin.client import PythonGarminConnector
from muscle50.infrastructure.raw_store import RawArtifact
from muscle50.infrastructure.sqlite.database import ActivityRepository
from muscle50.infrastructure.sqlite.nutrition_reader import SqliteNutritionReader
from muscle50.infrastructure.sqlite.nutrition_repository import SqliteMealRepository

KST = timezone(timedelta(hours=9))
MIGRATION = 9
DAY = "2026-10-02"
OTHER_DAY = "2026-10-01"
BREAKFAST = "2026-10-02-breakfast-1"
BREAKFAST_2 = "2026-10-02-breakfast-2"
LUNCH = "2026-10-02-lunch-1"
DINNER = "2026-10-02-dinner-1"
SNACK = "2026-10-02-snack-1"
VOIDED_AT = datetime(2026, 10, 2, 21, 0, tzinfo=KST)
EDITED_AT = datetime(2026, 10, 2, 22, 0, tzinfo=KST)
MERGED_AT = datetime(2026, 10, 2, 22, 5, tzinfo=KST)

CHICKEN = (
    ["--id", "chicken-breast", "--name", "닭가슴살", "--per", "100", "g"]
    + ["--kcal", "100", "--protein", "20", "--carbs", "0", "--fat", "2"]
    + ["--source", "user_provided", "--accuracy", "exact"]
)
CHICKEN_V2 = (
    ["chicken-breast", "--per", "100", "g"]
    + ["--kcal", "120", "--protein", "18", "--carbs", "2", "--fat", "4"]
    + ["--source", "food_database", "--accuracy", "estimated"]
)
# Fat is unknown on the label: the day's fat total stays incomplete before and after a merge.
RICE = (
    ["--id", "hetbahn-white-210", "--name", "햇반", "--per", "210", "g"]
    + ["--kcal", "315", "--protein", "5", "--carbs", "70", "--fat", "unknown"]
    + ["--source", "nutrition_label", "--accuracy", "exact"]
)
BANANA = (
    ["--id", "banana-medium", "--name", "바나나", "--per", "1", "count"]
    + ["--kcal", "90", "--protein", "1", "--carbs", "23", "--fat", "0"]
    + ["--source", "food_database", "--accuracy", "exact"]
)
# An estimated fact: the day's totals are marked estimated before and after a merge.
BAR = (
    ["--id", "energy-bar", "--name", "에너지바", "--per", "1", "count"]
    + ["--kcal", "200", "--protein", "5", "--carbs", "30", "--fat", "7"]
    + ["--source", "food_database", "--accuracy", "estimated"]
)
CHICKEN_ITEM = ("--item", "chicken-breast", "200", "g")
RICE_ITEM = ("--item", "hetbahn-white-210", "210", "g")
BANANA_ITEM = ("--item", "banana-medium", "1", "count")
BAR_ITEM = ("--item", "energy-bar", "1", "count")
FOOD_NAMES = ("닭가슴살", "햇반", "바나나", "에너지바")
TABLES = (
    "nutrition_meals",
    "nutrition_meal_items",
    "nutrition_facts",
    "nutrition_meal_item_removals",
    "nutrition_food_profiles",
    "nutrition_meal_revisions",
    "nutrition_meal_voids",
    "nutrition_meal_merged_items",
)
HISTORY_KEYS = ["voided", "voided_at", "void_reason", "merged_into", "merged_from", "revisions"]
NOT_COUNTED = "Not counted in nutrition day, status, recommend or daily."
# The use-case guard (`active_meal`), not the repository's fallback message.
VOIDED = (
    f"meal {SNACK} was voided at 2026-10-02 21:00 (UTC+09:00); a voided meal cannot be changed. Nothing was changed."
)


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
    monkeypatch.setattr(cli, "_today", lambda: date(2026, 10, 2))
    return root


@pytest.fixture(autouse=True)
def clock(monkeypatch: pytest.MonkeyPatch) -> list[datetime]:
    """The time `void`/`edit`/`merge` record; a test sets ``clock[0]`` before a correction."""
    now = [VOIDED_AT]
    monkeypatch.setattr(cli, "_now", lambda: now[0])
    return now


@pytest.fixture
def database(home: Path) -> Path:
    return home / "db" / "muscle50.sqlite3"


def _run(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, str, str]:
    code = main(list(argv))
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def _ok(capsys: pytest.CaptureFixture[str], *argv: str) -> str:
    code, out, err = _run(capsys, *argv)
    assert code == 0, err
    return out


def _json(capsys: pytest.CaptureFixture[str], *argv: str) -> Any:
    return json.loads(_ok(capsys, *argv, "--json"))


def _refused(capsys: pytest.CaptureFixture[str], *argv: str) -> str:
    code, out, err = _run(capsys, *argv)
    assert (code, out) == (1, ""), err
    assert err.startswith("오류: ")
    return err


def _foods(capsys: pytest.CaptureFixture[str]) -> None:
    for food in (CHICKEN, RICE, BANANA, BAR):
        _ok(capsys, "nutrition", "food", "add", *food)


def _log(capsys: pytest.CaptureFixture[str], meal: str, *items: str, day: str = DAY) -> str:
    document = json.loads(_ok(capsys, "nutrition", "log", "--date", day, "--meal", meal, *items, "--json"))
    meal_id: str = document["meal_id"]
    return meal_id


def _show(capsys: pytest.CaptureFixture[str], meal_id: str) -> Any:
    return _json(capsys, "nutrition", "meal", "show", meal_id)


def _day(capsys: pytest.CaptureFixture[str], day: str = DAY) -> Any:
    return _json(capsys, "nutrition", "day", "--date", day)


def _day_ids(capsys: pytest.CaptureFixture[str], day: str = DAY) -> list[str]:
    return [meal["meal_id"] for meal in _day(capsys, day)["meals"]]


def _items(capsys: pytest.CaptureFixture[str], meal_id: str) -> dict[int, Any]:
    return {item["sequence"]: item for item in _show(capsys, meal_id)["items"]}


def _selected_facts(item: dict[str, Any]) -> set[str]:
    return {nutrient["fact_id"] for nutrient in item["nutrients"].values() if nutrient is not None}


def _tables(database: Path) -> dict[str, list[tuple[Any, ...]]]:
    """Every nutrition row, so a refused correction can be checked for "nothing changed" exactly."""
    connection = sqlite3.connect(database)
    try:
        return {table: connection.execute(f"SELECT * FROM {table} ORDER BY 1, 2").fetchall() for table in TABLES}
    finally:
        connection.close()


def _views(capsys: pytest.CaptureFixture[str], *meal_ids: str, day: str = DAY) -> tuple[str, ...]:
    """Every read view of the meals and their day, text and JSON, byte for byte."""
    commands = [("nutrition", "meal", "show", meal_id) for meal_id in meal_ids]
    commands += [("nutrition", "day", "--date", day), ("nutrition", "status", "--date", day)]
    return tuple(_ok(capsys, *command, *flags) for command in commands for flags in ((), ("--json",)))


def _targets(capsys: pytest.CaptureFixture[str]) -> None:
    _ok(capsys, "nutrition", "target", "set", "kcal", "--exact", "2400")
    _ok(capsys, "nutrition", "target", "set", "protein", "--range", "150", "170")
    _ok(capsys, "nutrition", "target", "set", "carbs", "--exact", "300")
    _ok(capsys, "nutrition", "target", "set", "fat", "--exact", "60")


def _bench(database: Path, source_id: str, day: str) -> None:
    sets = tuple(strength_set(index, reps=10, weight_kg=50.0) for index in range(1, 4))
    item: NormalizedActivity = activity(source_id, f"{day}T12:00:00", ActivityType.STRENGTH, strength_sets=sets)
    artifact = RawArtifact("activity", f"raw/{source_id}/activity.json", "application/json", "0" * 64, 2)
    ActivityRepository(database).save(item, (artifact,))


def _training_history(database: Path) -> None:
    """Two strength sessions, so `recommend` evaluates a plan and shows its nutrition section."""
    ActivityRepository(database).migrate()
    _bench(database, "9001", "2026-09-26")
    _bench(database, "9002", "2026-09-29")


def _recommend(capsys: pytest.CaptureFixture[str], day: str = DAY) -> dict[str, Any]:
    document: dict[str, Any] = json.loads(_ok(capsys, "recommend", "--date", day, "--json"))
    return document


def _nutrition(capsys: pytest.CaptureFixture[str], day: str = DAY) -> dict[str, Any]:
    nutrition: dict[str, Any] = _recommend(capsys, day)["nutrition"]
    # Without this the "meal is gone" checks below could pass for the wrong reason.
    assert nutrition["availability"] == "evaluated"
    return nutrition


def _amounts(nutrients: dict[str, Any]) -> dict[str, Any]:
    """Per-nutrient status without the item references (a merge renumbers the items by design)."""
    return {name: {k: v for k, v in entry.items() if k != "missing_items"} for name, entry in nutrients.items()}


def _execute(database: Path, statement: str, *, foreign_keys: bool = False) -> None:
    connection = sqlite3.connect(database)
    try:
        if foreign_keys:
            connection.execute("PRAGMA foreign_keys = ON")
        connection.execute(statement)
        connection.commit()
    finally:
        connection.close()


def _without_names(text: str, *extra: str) -> str:
    for name in (*FOOD_NAMES, *extra):
        text = text.replace(name, "")
    return text


# --- void -------------------------------------------------------------------------------------------


def _void_setup(capsys: pytest.CaptureFixture[str], database: Path) -> None:
    _training_history(database)
    _foods(capsys)
    _targets(capsys)
    _log(capsys, "breakfast", *CHICKEN_ITEM)
    _log(capsys, "snack", *BANANA_ITEM)
    _log(capsys, "lunch", *RICE_ITEM, day=OTHER_DAY)


def test_void_takes_the_meal_out_of_day_status_and_recommend(
    capsys: pytest.CaptureFixture[str], database: Path
) -> None:
    _void_setup(capsys, database)
    assert _day_ids(capsys) == [BREAKFAST, SNACK]
    assert _json(capsys, "nutrition", "status", "--date", DAY)["nutrients"]["calories_kcal"]["consumed"] == "290"
    before = _nutrition(capsys)
    assert (before["meal_count"], before["nutrients"]["calories_kcal"]["consumed"]) == (2, "290")
    breakfast_views = (
        _ok(capsys, "nutrition", "meal", "show", BREAKFAST),
        _ok(capsys, "nutrition", "meal", "show", BREAKFAST, "--json"),
    )
    other_day = (
        _ok(capsys, "nutrition", "day", "--date", OTHER_DAY),
        _ok(capsys, "nutrition", "day", "--date", OTHER_DAY, "--json"),
    )
    training_before = {key: value for key, value in _recommend(capsys).items() if key != "nutrition"}

    out = _ok(capsys, "nutrition", "meal", "void", SNACK, "--reason", "double entry")

    assert out.splitlines() == [
        f"Voided meal {SNACK}. It no longer counts in nutrition day, status, recommend or daily.",
        "",
        f"[snack] {SNACK} ({DAY}, time not recorded)",
        "  1. 바나나 (banana-medium) 1 count: kcal 90 | P 1 g | C 23 g | F 0 g",
        "     source: food_database/exact",
        "     facts: food:banana-medium:1",
        "  Meal total: kcal 90 | P 1 g | C 23 g | F 0 g",
        f"  Voided 2026-10-02 21:00 (UTC+09:00); reason: double entry. {NOT_COUNTED}",
        "",
        f"Whole day: muscle50 nutrition day --date {DAY}",
    ]
    day = _day(capsys)
    assert [meal["meal_id"] for meal in day["meals"]] == [BREAKFAST]
    assert day["total"]["totals"]["calories_kcal"] == "200"
    day_text = _ok(capsys, "nutrition", "day", "--date", DAY)
    assert SNACK not in day_text
    assert "Consumed (1 meal, 1 item):" in day_text
    status = _json(capsys, "nutrition", "status", "--date", DAY)
    assert (status["meal_count"], status["nutrients"]["calories_kcal"]["consumed"]) == (1, "200")
    assert "Logged: 1 meal, 1 item" in _ok(capsys, "nutrition", "status", "--date", DAY)
    after = _nutrition(capsys)
    assert (after["meal_count"], after["nutrients"]["calories_kcal"]["consumed"]) == (1, "200")
    assert {key: value for key, value in _recommend(capsys).items() if key != "nutrition"} == training_before
    # Other meals and other days print exactly what they printed before.
    assert (
        _ok(capsys, "nutrition", "meal", "show", BREAKFAST),
        _ok(capsys, "nutrition", "meal", "show", BREAKFAST, "--json"),
    ) == breakfast_views
    assert (
        _ok(capsys, "nutrition", "day", "--date", OTHER_DAY),
        _ok(capsys, "nutrition", "day", "--date", OTHER_DAY, "--json"),
    ) == other_day
    # The meal stays stored: nothing was deleted, one void row was appended.
    tables = _tables(database)
    assert [row[0] for row in tables["nutrition_meals"]] == ["2026-10-01-lunch-1", BREAKFAST, SNACK]
    assert tables["nutrition_meal_voids"] == [(SNACK, VOIDED_AT.isoformat(), "double entry", None)]


def test_void_json_is_the_meal_show_document_with_the_history_keys(capsys: pytest.CaptureFixture[str]) -> None:
    _foods(capsys)
    logged = _log(capsys, "snack", *BANANA_ITEM)
    log_document = _show(capsys, logged)

    printed = _ok(capsys, "nutrition", "meal", "void", SNACK, "--reason", "  double entry  ", "--json")

    assert printed == _ok(capsys, "nutrition", "meal", "show", SNACK, "--json")
    document = json.loads(printed)
    assert printed == json.dumps(document, indent=2) + "\n"
    assert list(document) == [*log_document, *HISTORY_KEYS]
    assert {key: document[key] for key in log_document} == log_document
    assert {key: document[key] for key in HISTORY_KEYS} == {
        "voided": True,
        "voided_at": "2026-10-02T21:00:00+09:00",
        # Stored stripped.
        "void_reason": "double entry",
        "merged_into": None,
        "merged_from": [],
        "revisions": [],
    }


def test_void_without_a_reason_and_a_blank_reason_is_refused(
    capsys: pytest.CaptureFixture[str], database: Path
) -> None:
    _foods(capsys)
    _log(capsys, "snack", *BANANA_ITEM)
    rows = _tables(database)
    views = _views(capsys, SNACK)

    err = _refused(capsys, "nutrition", "meal", "void", SNACK, "--reason", "   ")

    assert "--reason must not be blank. Nothing was changed." in err
    assert _tables(database) == rows
    assert _views(capsys, SNACK) == views

    document = _json(capsys, "nutrition", "meal", "void", SNACK)
    assert (document["voided"], document["void_reason"]) == (True, None)
    assert (
        f"  Voided 2026-10-02 21:00 (UTC+09:00); no reason given. {NOT_COUNTED}"
        in _ok(capsys, "nutrition", "meal", "show", SNACK).splitlines()
    )


def test_meal_show_of_a_voided_meal(capsys: pytest.CaptureFixture[str]) -> None:
    _foods(capsys)
    _log(capsys, "snack", *BANANA_ITEM)
    _ok(capsys, "nutrition", "meal", "void", SNACK, "--reason", "logged twice")

    assert _ok(capsys, "nutrition", "meal", "show", SNACK).splitlines() == [
        f"[snack] {SNACK} ({DAY}, time not recorded)",
        "  1. 바나나 (banana-medium) 1 count: kcal 90 | P 1 g | C 23 g | F 0 g",
        "     source: food_database/exact",
        "     facts: food:banana-medium:1",
        "  Meal total: kcal 90 | P 1 g | C 23 g | F 0 g",
        f"  Voided 2026-10-02 21:00 (UTC+09:00); reason: logged twice. {NOT_COUNTED}",
    ]


def test_after_a_void_the_meal_can_be_logged_again_without_additional(capsys: pytest.CaptureFixture[str]) -> None:
    _foods(capsys)
    _log(capsys, "snack", *BANANA_ITEM)
    assert "pass --additional" in _refused(capsys, "nutrition", "log", "--meal", "snack", *BAR_ITEM)
    _ok(capsys, "nutrition", "meal", "void", SNACK)

    logged = _log(capsys, "snack", *BAR_ITEM)

    # The voided ID stays taken, so the new meal gets the next number.
    assert logged == "2026-10-02-snack-2"
    assert _day_ids(capsys) == [logged]


# --- edit -------------------------------------------------------------------------------------------


def test_edit_moves_a_meal_to_another_date_and_keeps_its_id_and_items(
    capsys: pytest.CaptureFixture[str], clock: list[datetime], database: Path
) -> None:
    _foods(capsys)
    _log(capsys, "dinner", *CHICKEN_ITEM)
    before = _show(capsys, DINNER)
    assert _day_ids(capsys) == [DINNER]
    clock[0] = EDITED_AT

    out = _ok(capsys, "nutrition", "meal", "edit", DINNER, "--date", OTHER_DAY, "--time", "21:30")

    assert out.splitlines() == [
        f"Edited meal {DINNER}: date {DAY} -> {OTHER_DAY}; time not recorded -> 21:30. The meal ID does not change.",
        "",
        f"[dinner] {DINNER} ({OTHER_DAY} 21:30)",
        "  1. 닭가슴살 (chicken-breast) 200 g: kcal 200 | P 40 g | C 0 g | F 4 g",
        "     source: user_provided/exact",
        "     facts: food:chicken-breast:1",
        "  Meal total: kcal 200 | P 40 g | C 0 g | F 4 g",
        f"  Edited 2026-10-02 22:00 (UTC+09:00): date {DAY} -> {OTHER_DAY}; time not recorded -> 21:30",
        "  The meal ID keeps the date and type it was logged with; the date and type above are current.",
        "",
        f"Whole day: muscle50 nutrition day --date {OTHER_DAY}",
    ]
    assert _day_ids(capsys) == []
    moved = _day(capsys, OTHER_DAY)
    (meal,) = moved["meals"]
    assert (meal["meal_id"], meal["eaten_at"], meal["time_recorded"]) == (DINNER, "2026-10-01T21:30:00+09:00", True)
    # `day` never carries the history keys; the snapshot items are untouched.
    assert list(meal) == list(before)
    assert meal["items"] == before["items"]
    assert meal["original_text"] == before["original_text"]
    shown = _show(capsys, DINNER)
    assert shown["revisions"] == [
        {
            "revision": 1,
            "revised_at": "2026-10-02T22:00:00+09:00",
            "before": {"meal_type": "dinner", "eaten_at": "2026-10-02T00:00:00+09:00", "time_recorded": False},
            "after": {"meal_type": "dinner", "eaten_at": "2026-10-01T21:30:00+09:00", "time_recorded": True},
        }
    ]
    assert (shown["voided"], shown["merged_from"]) == (False, [])
    # The meal row itself is never rewritten.
    (meal_row,) = _tables(database)["nutrition_meals"]
    assert meal_row[1] == "2026-10-02T00:00:00+09:00"
    # The read-only reader (recommend/daily) places it by its effective date too.
    reader = SqliteNutritionReader(database)
    assert reader.list_eaten_between(datetime(2026, 10, 2, tzinfo=KST), datetime(2026, 10, 3, tzinfo=KST)) == ()
    (read,) = reader.list_eaten_between(datetime(2026, 10, 1, tzinfo=KST), datetime(2026, 10, 2, tzinfo=KST))
    assert (read.meal_id, read.eaten_at) == (DINNER, datetime(2026, 10, 1, 21, 30, tzinfo=KST))
    # The `nutrition log` double-entry guard follows the moved meal.
    assert "pass --additional" in _refused(
        capsys, "nutrition", "log", "--date", OTHER_DAY, "--meal", "dinner", *BANANA_ITEM
    )
    assert _log(capsys, "dinner", *BANANA_ITEM) == "2026-10-02-dinner-2"


def test_edit_type_time_and_date_alone(capsys: pytest.CaptureFixture[str], clock: list[datetime]) -> None:
    _foods(capsys)
    _ok(capsys, "nutrition", "log", "--date", DAY, "--meal", "lunch", "--time", "12:15", *RICE_ITEM)
    logged_at = _show(capsys, LUNCH)["eaten_at"]

    clock[0] = EDITED_AT
    out = _ok(capsys, "nutrition", "meal", "edit", LUNCH, "--meal", "dinner")
    assert out.splitlines()[0] == f"Edited meal {LUNCH}: type lunch -> dinner. The meal ID does not change."
    shown = _show(capsys, LUNCH)
    # A type-only edit keeps the stored time byte for byte.
    assert (shown["meal_type"], shown["eaten_at"]) == ("dinner", logged_at)

    clock[0] = EDITED_AT + timedelta(minutes=1)
    out = _ok(capsys, "nutrition", "meal", "edit", LUNCH, "--time", "19:05")
    assert out.splitlines()[0] == f"Edited meal {LUNCH}: time 12:15 -> 19:05. The meal ID does not change."

    clock[0] = EDITED_AT + timedelta(minutes=2)
    out = _ok(capsys, "nutrition", "meal", "edit", LUNCH, "--date", OTHER_DAY)
    assert out.splitlines()[0] == f"Edited meal {LUNCH}: date {DAY} -> {OTHER_DAY}. The meal ID does not change."
    # A date-only edit keeps the wall time.
    assert _show(capsys, LUNCH)["eaten_at"] == "2026-10-01T19:05:00+09:00"

    clock[0] = EDITED_AT + timedelta(minutes=3)
    out = _ok(capsys, "nutrition", "meal", "edit", LUNCH, "--no-time")
    assert out.splitlines()[0] == f"Edited meal {LUNCH}: time 19:05 -> not recorded. The meal ID does not change."

    shown = _show(capsys, LUNCH)
    assert (shown["meal_type"], shown["eaten_at"], shown["time_recorded"]) == (
        "dinner",
        "2026-10-01T00:00:00+09:00",
        False,
    )
    revisions = shown["revisions"]
    assert [revision["revision"] for revision in revisions] == [1, 2, 3, 4]
    # Each revision's "before" is the previous revision's "after" (revision 1: the logged meal).
    assert revisions[0]["before"] == {"meal_type": "lunch", "eaten_at": logged_at, "time_recorded": True}
    for previous, current in zip(revisions, revisions[1:], strict=False):
        assert current["before"] == previous["after"]
    text = _ok(capsys, "nutrition", "meal", "show", LUNCH).splitlines()
    assert text[0] == f"[dinner] {LUNCH} ({OTHER_DAY}, time not recorded)"
    assert text[-5:] == [
        "  Edited 2026-10-02 22:00 (UTC+09:00): type lunch -> dinner",
        "  Edited 2026-10-02 22:01 (UTC+09:00): time 12:15 -> 19:05",
        f"  Edited 2026-10-02 22:02 (UTC+09:00): date {DAY} -> {OTHER_DAY}",
        "  Edited 2026-10-02 22:03 (UTC+09:00): time 19:05 -> not recorded",
        "  The meal ID keeps the date and type it was logged with; the date and type above are current.",
    ]
    assert _day_ids(capsys, OTHER_DAY) == [LUNCH]
    assert _day_ids(capsys) == []


@pytest.mark.parametrize(
    ("argv", "message"),
    [
        ((), "give at least one of --date, --meal, --time or --no-time. Nothing was changed."),
        (
            ("--date", DAY, "--meal", "dinner"),
            f"meal {DINNER} is already dinner on {DAY} (time not recorded); nothing to change. Nothing was changed.",
        ),
        (("--no-time",), "nothing to change. Nothing was changed."),
        (("--time", "00:00"), "nothing to change. Nothing was changed."),
        (("--date", "2026-10-32"), "--date는 YYYY-MM-DD 형식이어야 합니다."),
        (("--time", "7:30"), "--time must be HH:MM (24-hour), got '7:30'"),
        (("--time", "25:00"), "--time must be HH:MM"),
    ],
)
def test_edit_refusals_change_nothing(
    capsys: pytest.CaptureFixture[str], database: Path, argv: tuple[str, ...], message: str
) -> None:
    _foods(capsys)
    _log(capsys, "dinner", *CHICKEN_ITEM)
    rows = _tables(database)
    views = _views(capsys, DINNER)

    err = _refused(capsys, "nutrition", "meal", "edit", DINNER, *argv)

    assert message in err
    assert _tables(database) == rows
    assert _views(capsys, DINNER) == views


def test_edit_to_the_current_time_is_refused(capsys: pytest.CaptureFixture[str], database: Path) -> None:
    _foods(capsys)
    _ok(capsys, "nutrition", "log", "--date", DAY, "--meal", "dinner", "--time", "19:00", *CHICKEN_ITEM)
    rows = _tables(database)

    err = _refused(capsys, "nutrition", "meal", "edit", DINNER, "--time", "19:00", "--meal", "dinner")

    assert f"meal {DINNER} is already dinner on {DAY} (19:00); nothing to change. Nothing was changed." in err
    assert _tables(database) == rows


def test_edit_argparse_errors(capsys: pytest.CaptureFixture[str], database: Path) -> None:
    _foods(capsys)
    _log(capsys, "dinner", *CHICKEN_ITEM)
    rows = _tables(database)
    for argv in (
        ("edit",),
        ("edit", DINNER, "--time", "19:00", "--no-time"),
        ("edit", DINNER, "--meal", "brunch"),
        ("void",),
        ("merge", BREAKFAST),
    ):
        with pytest.raises(SystemExit) as raised:
            main(["nutrition", "meal", *argv])
        assert raised.value.code == 2
    capsys.readouterr()
    assert _tables(database) == rows


def test_edit_into_an_occupied_slot_needs_additional(capsys: pytest.CaptureFixture[str], database: Path) -> None:
    _foods(capsys)
    _log(capsys, "breakfast", *CHICKEN_ITEM, day=OTHER_DAY)
    _log(capsys, "dinner", *BANANA_ITEM)
    rows = _tables(database)
    views = _views(capsys, DINNER)

    err = _refused(capsys, "nutrition", "meal", "edit", DINNER, "--date", OTHER_DAY, "--meal", "breakfast")

    assert err.rstrip().endswith(
        f"breakfast on {OTHER_DAY} is already recorded (2026-10-01-breakfast-1); pass --additional to move meal "
        f"{DINNER} there anyway. Nothing was changed."
    )
    assert _tables(database) == rows
    assert _views(capsys, DINNER) == views

    _ok(capsys, "nutrition", "meal", "edit", DINNER, "--date", OTHER_DAY, "--meal", "breakfast", "--additional")

    assert _day_ids(capsys, OTHER_DAY) == ["2026-10-01-breakfast-1", DINNER]
    assert _day_ids(capsys) == []


def test_a_time_only_edit_never_trips_the_double_entry_guard(capsys: pytest.CaptureFixture[str]) -> None:
    _foods(capsys)
    _log(capsys, "breakfast", *CHICKEN_ITEM)
    _ok(capsys, "nutrition", "log", "--meal", "breakfast", "--additional", *BANANA_ITEM)

    _ok(capsys, "nutrition", "meal", "edit", BREAKFAST_2, "--time", "10:00")
    _ok(capsys, "nutrition", "meal", "edit", BREAKFAST_2, "--meal", "breakfast", "--time", "10:30")

    assert _show(capsys, BREAKFAST_2)["eaten_at"] == "2026-10-02T10:30:00+09:00"


def test_edit_guard_ignores_voided_meals(capsys: pytest.CaptureFixture[str]) -> None:
    _foods(capsys)
    _log(capsys, "snack", *BANANA_ITEM)
    _log(capsys, "dinner", *CHICKEN_ITEM)
    _ok(capsys, "nutrition", "meal", "void", SNACK)

    _ok(capsys, "nutrition", "meal", "edit", DINNER, "--meal", "snack")

    assert _day_ids(capsys) == [DINNER]
    assert _show(capsys, DINNER)["meal_type"] == "snack"


# --- merge ------------------------------------------------------------------------------------------


def _split_breakfast(capsys: pytest.CaptureFixture[str]) -> None:
    """Breakfast logged in two parts with --additional; fat is incomplete and the bar is estimated."""
    _foods(capsys)
    _ok(capsys, "nutrition", "log", "--date", DAY, "--meal", "breakfast", "--time", "07:30", *CHICKEN_ITEM, *RICE_ITEM)
    _ok(capsys, "nutrition", "log", "--date", DAY, "--meal", "breakfast", "--additional", *BANANA_ITEM, *BAR_ITEM)


def _totals_block(day_text: str) -> list[str]:
    """The day's four nutrient total lines and its "Estimated:" line."""
    lines = day_text.splitlines()
    start = next(index for index, line in enumerate(lines) if line.startswith("Consumed ("))
    return lines[start + 1 : start + 5] + [line for line in lines if line.startswith("Estimated:")]


def test_merge_moves_the_items_voids_the_source_and_keeps_the_day_totals(
    capsys: pytest.CaptureFixture[str], clock: list[datetime], database: Path
) -> None:
    _training_history(database)
    _split_breakfast(capsys)
    _targets(capsys)
    source_items = _items(capsys, BREAKFAST_2)
    day_text = _ok(capsys, "nutrition", "day", "--date", DAY)
    day_total = _day(capsys)["total"]
    status_amounts = _amounts(_json(capsys, "nutrition", "status", "--date", DAY)["nutrients"])
    recommend_amounts = _amounts(_nutrition(capsys)["nutrients"])
    totals_block = _totals_block(day_text)
    assert totals_block == [
        "  kcal          805 (estimated)",
        "  Protein       51 g (estimated)",
        "  Carbohydrate  123 g (estimated)",
        "  Fat           incomplete (known items only: 11 g (estimated))",
        "Estimated: kcal, protein, carbohydrate, fat include values from facts marked estimated.",
    ]
    clock[0] = MERGED_AT

    out = _ok(capsys, "nutrition", "meal", "merge", BREAKFAST, BREAKFAST_2)

    assert out.splitlines() == [
        f"Merged meal {BREAKFAST_2} into {BREAKFAST} as items 3, 4; meal {BREAKFAST_2} is voided.",
        "",
        f"[breakfast] {BREAKFAST} ({DAY} 07:30)",
        "  1. 닭가슴살 (chicken-breast) 200 g: kcal 200 | P 40 g | C 0 g | F 4 g",
        "     source: user_provided/exact",
        "     facts: food:chicken-breast:1",
        "  2. 햇반 (hetbahn-white-210) 210 g: kcal 315 | P 5 g | C 70 g | F missing",
        "     source: nutrition_label/exact",
        "     facts: food:hetbahn-white-210:1",
        "     missing: fat",
        "  3. 바나나 (banana-medium) 1 count: kcal 90 | P 1 g | C 23 g | F 0 g",
        "     source: food_database/exact",
        "     facts: food:banana-medium:1",
        "  4. 에너지바 (energy-bar) 1 count: kcal 200 | P 5 g | C 30 g | F 7 g",
        "     source: food_database/estimated",
        "     facts: food:energy-bar:1",
        "  Meal total: kcal 805 (estimated) | P 51 g (estimated) | C 123 g (estimated) | "
        "F incomplete (known items only: 11 g (estimated))",
        f"  Merged 2026-10-02 22:05 (UTC+09:00) from meal {BREAKFAST_2}: items 3, 4 (its items 1, 2)",
        "",
        f"Whole day: muscle50 nutrition day --date {DAY}",
    ]
    # AC4: the day's totals are byte-identical (text block and JSON total object).
    after_text = _ok(capsys, "nutrition", "day", "--date", DAY)
    assert _totals_block(after_text) == totals_block
    assert "Consumed (1 meal, 4 items):" in after_text
    assert json.dumps(_day(capsys)["total"]) == json.dumps(day_total)
    assert _amounts(_json(capsys, "nutrition", "status", "--date", DAY)["nutrients"]) == status_amounts
    assert _amounts(_nutrition(capsys)["nutrients"]) == recommend_amounts
    assert _day_ids(capsys) == [BREAKFAST]
    # The copies carry the source items' values and catalog fact versions unchanged.
    items = _items(capsys, BREAKFAST)
    assert sorted(items) == [1, 2, 3, 4]
    for copy, original in ((items[3], source_items[1]), (items[4], source_items[2])):
        assert {k: v for k, v in copy.items() if k not in ("sequence", "nutrients", "facts")} == {
            k: v for k, v in original.items() if k not in ("sequence", "nutrients", "facts")
        }
        assert {name: entry["value"] for name, entry in copy["nutrients"].items() if entry} == {
            name: entry["value"] for name, entry in original["nutrients"].items() if entry
        }
        assert [
            {k: v for k, v in fact.items() if k not in ("fact_id", "supersedes_fact_id")} for fact in copy["facts"]
        ] == [
            {k: v for k, v in fact.items() if k not in ("fact_id", "supersedes_fact_id")} for fact in original["facts"]
        ]
    assert _selected_facts(items[3]) == {f"{BREAKFAST}:3:food:banana-medium:1"}
    assert _selected_facts(items[4]) == {f"{BREAKFAST}:4:food:energy-bar:1"}
    # The source is voided with a link to the target; its own items stay stored for audit.
    source = _show(capsys, BREAKFAST_2)
    assert (source["voided"], source["voided_at"], source["void_reason"], source["merged_into"]) == (
        True,
        "2026-10-02T22:05:00+09:00",
        None,
        BREAKFAST,
    )
    assert source["items"] == list(source_items.values())
    assert _ok(capsys, "nutrition", "meal", "show", BREAKFAST_2).splitlines()[-1] == (
        f"  Voided 2026-10-02 22:05 (UTC+09:00); merged into meal {BREAKFAST}. {NOT_COUNTED}"
    )
    target = _show(capsys, BREAKFAST)
    assert target["merged_from"] == [
        {
            "meal_id": BREAKFAST_2,
            "merged_at": "2026-10-02T22:05:00+09:00",
            "items": [{"sequence": 3, "source_sequence": 1}, {"sequence": 4, "source_sequence": 2}],
        }
    ]
    assert (target["voided"], target["revisions"]) == (False, [])
    tables = _tables(database)
    assert tables["nutrition_meal_merged_items"] == [(BREAKFAST, 3, BREAKFAST_2, 1), (BREAKFAST, 4, BREAKFAST_2, 2)]
    assert tables["nutrition_meal_voids"] == [(BREAKFAST_2, MERGED_AT.isoformat(), None, BREAKFAST)]


def test_merge_json_is_the_target_meal_show_document(capsys: pytest.CaptureFixture[str]) -> None:
    _split_breakfast(capsys)

    printed = _ok(capsys, "nutrition", "meal", "merge", BREAKFAST, BREAKFAST_2, "--json")

    assert printed == _ok(capsys, "nutrition", "meal", "show", BREAKFAST, "--json")
    document = json.loads(printed)
    assert printed == json.dumps(document, indent=2) + "\n"
    assert list(document)[-6:] == HISTORY_KEYS
    assert [item["sequence"] for item in document["items"]] == [1, 2, 3, 4]


def test_merge_copies_only_active_items_and_never_reuses_item_numbers(
    capsys: pytest.CaptureFixture[str], database: Path
) -> None:
    _foods(capsys)
    _log(capsys, "breakfast", *CHICKEN_ITEM, *RICE_ITEM)
    _ok(capsys, "nutrition", "meal", "remove-item", BREAKFAST, "--item-number", "2")
    _ok(capsys, "nutrition", "log", "--meal", "breakfast", "--additional", *BANANA_ITEM, *RICE_ITEM, *BAR_ITEM)
    _ok(capsys, "nutrition", "meal", "remove-item", BREAKFAST_2, "--item-number", "2")
    kcal = _day(capsys)["total"]["totals"]["calories_kcal"]

    out = _ok(capsys, "nutrition", "meal", "merge", BREAKFAST, BREAKFAST_2)

    assert (
        out.splitlines()[0]
        == f"Merged meal {BREAKFAST_2} into {BREAKFAST} as items 3, 4; meal {BREAKFAST_2} is voided."
    )
    items = _items(capsys, BREAKFAST)
    assert {sequence: item["food_id"] for sequence, item in items.items()} == {
        1: "chicken-breast",
        3: "banana-medium",
        4: "energy-bar",
    }
    assert _day(capsys)["total"]["totals"]["calories_kcal"] == kcal
    assert f"from meal {BREAKFAST_2}: items 3, 4 (its items 1, 3)" in out
    assert _tables(database)["nutrition_meal_merged_items"] == [
        (BREAKFAST, 3, BREAKFAST_2, 1),
        (BREAKFAST, 4, BREAKFAST_2, 3),
    ]


def test_merge_keeps_the_source_snapshot_after_a_newer_catalog_fact(capsys: pytest.CaptureFixture[str]) -> None:
    _foods(capsys)
    _log(capsys, "breakfast", *BANANA_ITEM)
    _ok(capsys, "nutrition", "log", "--meal", "breakfast", "--additional", *CHICKEN_ITEM)
    _ok(capsys, "nutrition", "food", "fact", "add", *CHICKEN_V2)
    source_item = _items(capsys, BREAKFAST_2)[1]

    out = _ok(capsys, "nutrition", "meal", "merge", BREAKFAST, BREAKFAST_2)

    assert out.splitlines()[0].endswith("as item 2; meal 2026-10-02-breakfast-2 is voided.")
    assert f"from meal {BREAKFAST_2}: item 2 (its item 1)" in out
    copy = _items(capsys, BREAKFAST)[2]
    # Not re-snapshotted: version 1 is still the selected fact, version 2 is not part of the copy.
    assert _selected_facts(copy) == {f"{BREAKFAST}:2:food:chicken-breast:1"}
    assert [fact["fact_id"] for fact in copy["facts"]] == [f"{BREAKFAST}:2:food:chicken-breast:1"]
    assert copy["nutrients"]["calories_kcal"]["value"] == source_item["nutrients"]["calories_kcal"]["value"] == "200"


def test_merge_of_different_meal_types_keeps_the_target_type_and_time(capsys: pytest.CaptureFixture[str]) -> None:
    _foods(capsys)
    _ok(capsys, "nutrition", "log", "--meal", "breakfast", "--time", "07:30", *CHICKEN_ITEM)
    _log(capsys, "snack", *BANANA_ITEM)

    _ok(capsys, "nutrition", "meal", "merge", BREAKFAST, SNACK)

    shown = _show(capsys, BREAKFAST)
    assert (shown["meal_type"], shown["eaten_at"]) == ("breakfast", "2026-10-02T07:30:00+09:00")
    assert _day_ids(capsys) == [BREAKFAST]


def test_merge_refusals_change_nothing(capsys: pytest.CaptureFixture[str], database: Path) -> None:
    _foods(capsys)
    _log(capsys, "breakfast", *CHICKEN_ITEM)
    _log(capsys, "lunch", *RICE_ITEM)
    _log(capsys, "dinner", *BANANA_ITEM, day=OTHER_DAY)
    _log(capsys, "snack", *BAR_ITEM)
    _ok(capsys, "nutrition", "meal", "void", SNACK)
    rows = _tables(database)
    views = _views(capsys, BREAKFAST, LUNCH)

    cases = [
        ((BREAKFAST, BREAKFAST), f"cannot merge meal {BREAKFAST} into itself. Nothing was changed."),
        (("2026-10-02-lunch-9", BREAKFAST), "no meal with id '2026-10-02-lunch-9'"),
        ((BREAKFAST, "2026-10-02-lunch-9"), "no meal with id '2026-10-02-lunch-9'"),
        ((BREAKFAST, SNACK), f"meal {SNACK} was voided at 2026-10-02 21:00 (UTC+09:00)"),
        ((SNACK, BREAKFAST), f"meal {SNACK} was voided at 2026-10-02 21:00 (UTC+09:00)"),
        (
            (BREAKFAST, "2026-10-01-dinner-1"),
            f"meal 2026-10-01-dinner-1 is on {OTHER_DAY} but meal {BREAKFAST} is on {DAY}; only meals of the same "
            "date can be merged (move one first with muscle50 nutrition meal edit). Nothing was changed.",
        ),
    ]
    for (target, source), message in cases:
        err = _refused(capsys, "nutrition", "meal", "merge", target, source)
        assert message in err
        assert err.rstrip().endswith("Nothing was changed.")

    assert _tables(database) == rows
    assert _views(capsys, BREAKFAST, LUNCH) == views


def test_merge_that_would_change_the_exact_day_totals_is_refused(
    capsys: pytest.CaptureFixture[str], database: Path
) -> None:
    """1/3 + 1/3 + 1000 and 1/3 + 1000 + 1/3 round differently at 28 digits."""
    for food_id, basis, kcal in (("third", "3", "1"), ("big", "1", "1000")):
        _ok(
            capsys,
            "nutrition",
            "food",
            "add",
            *("--id", food_id, "--name", food_id, "--per", basis, "count", "--kcal", kcal),
            *("--protein", "unknown", "--carbs", "unknown", "--fat", "unknown"),
            *("--source", "user_provided", "--accuracy", "exact"),
        )
    _ok(capsys, "nutrition", "log", "--meal", "snack", "--time", "07:00", "--item", "third", "1", "count")
    _ok(
        capsys,
        "nutrition",
        "log",
        "--meal",
        "breakfast",
        "--time",
        "08:00",
        *("--item", "third", "1", "count", "--item", "big", "1", "count"),
    )
    assert _day(capsys)["total"]["totals"]["calories_kcal"] == "1000.666666666666666666666667"
    rows = _tables(database)
    views = _views(capsys, BREAKFAST, SNACK)

    err = _refused(capsys, "nutrition", "meal", "merge", BREAKFAST, SNACK)

    assert err.rstrip().endswith(
        f"merging {SNACK} into {BREAKFAST} would change the exact day totals for kcal (item order changes how "
        "non-terminating values add up); the meals were left separate. Nothing was changed."
    )
    assert _tables(database) == rows
    assert _views(capsys, BREAKFAST, SNACK) == views


@pytest.mark.parametrize("table", ["nutrition_meal_voids", "nutrition_meal_merged_items"])
def test_merge_failing_at_any_step_writes_nothing(
    capsys: pytest.CaptureFixture[str], database: Path, table: str
) -> None:
    _split_breakfast(capsys)
    rows = _tables(database)
    views = _views(capsys, BREAKFAST, BREAKFAST_2)
    # The copied items and their facts are written first; then the void, then the mapping rows.
    _execute(
        database,
        f"CREATE TRIGGER fail_step BEFORE INSERT ON {table} "
        "BEGIN SELECT RAISE(ABORT, 'synthetic storage failure'); END",
    )

    with pytest.raises(sqlite3.IntegrityError, match="synthetic storage failure"):
        MergeMeals(SqliteMealRepository(database), clock=lambda: MERGED_AT).execute(
            BREAKFAST, BREAKFAST_2, timezone_for=lambda day: KST
        )

    _execute(database, "DROP TRIGGER fail_step")
    assert _tables(database) == rows
    assert _views(capsys, BREAKFAST, BREAKFAST_2) == views


# --- guards on voided meals (AC5) -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("argv", "message"),
    [
        (("meal", "edit", SNACK, "--meal", "lunch"), VOIDED),
        (("meal", "edit", SNACK, "--date", OTHER_DAY), VOIDED),
        (("meal", "merge", BREAKFAST, SNACK), VOIDED),
        (("meal", "merge", SNACK, BREAKFAST), VOIDED),
        (("meal", "add-item", SNACK, *BANANA_ITEM), VOIDED),
        (("meal", "remove-item", SNACK, "--item-number", "1"), VOIDED),
        (("meal", "replace-item", SNACK, "--item-number", "1", *BAR_ITEM), VOIDED),
        (("meal", "void", SNACK), f"meal {SNACK} is already voided (at 2026-10-02 21:00 (UTC+09:00))."),
        (("repeat", SNACK, "--additional"), VOIDED.replace("changed.", "repeated.", 1)),
    ],
)
def test_a_voided_meal_cannot_be_changed(
    capsys: pytest.CaptureFixture[str], database: Path, argv: tuple[str, ...], message: str
) -> None:
    _foods(capsys)
    _log(capsys, "breakfast", *CHICKEN_ITEM)
    _log(capsys, "snack", *BANANA_ITEM, *RICE_ITEM)
    _ok(capsys, "nutrition", "meal", "void", SNACK)
    rows = _tables(database)
    views = _views(capsys, BREAKFAST, SNACK)

    err = _refused(capsys, "nutrition", *argv)

    assert message in err
    assert f"meal {SNACK} " in err
    assert err.rstrip().endswith("Nothing was changed.")
    assert _tables(database) == rows
    assert _views(capsys, BREAKFAST, SNACK) == views


def test_a_merged_source_names_the_meal_it_was_merged_into(capsys: pytest.CaptureFixture[str]) -> None:
    _split_breakfast(capsys)
    _ok(capsys, "nutrition", "meal", "merge", BREAKFAST, BREAKFAST_2)

    edit = _refused(capsys, "nutrition", "meal", "add-item", BREAKFAST_2, *BANANA_ITEM)
    repeat = _refused(capsys, "nutrition", "repeat", BREAKFAST_2)

    assert edit.rstrip().endswith(
        f"meal {BREAKFAST_2} was merged into {BREAKFAST} at 2026-10-02 21:00 (UTC+09:00); a voided meal cannot be "
        f"changed (use {BREAKFAST}). Nothing was changed."
    )
    assert repeat.rstrip().endswith(
        f"a voided meal cannot be repeated (repeat {BREAKFAST} instead). Nothing was changed."
    )


def test_the_repository_refuses_a_voided_meal_inside_its_transaction(
    capsys: pytest.CaptureFixture[str], database: Path
) -> None:
    """The use cases check first; the repository re-checks under its write lock."""
    _foods(capsys)
    _log(capsys, "breakfast", *CHICKEN_ITEM)
    _log(capsys, "snack", *BANANA_ITEM, *RICE_ITEM)
    _ok(capsys, "nutrition", "meal", "void", SNACK)
    repository = SqliteMealRepository(database)
    snack = repository.get(SNACK)
    breakfast = repository.get(BREAKFAST)
    assert snack is not None and breakfast is not None
    rows = _tables(database)

    attempts: list[Callable[[], object]] = [
        lambda: repository.void_meal(SNACK, EDITED_AT, None),
        lambda: repository.revise_meal(SNACK, MealRevision(1, EDITED_AT, MealType.LUNCH, snack.eaten_at)),
        lambda: repository.merge_meals(
            BREAKFAST,
            SNACK,
            tuple(copy_item_for_merge(item, BREAKFAST, 1 + item.sequence) for item in snack.items),
            (1, 2),
            EDITED_AT,
        ),
        lambda: repository.merge_meals(
            SNACK, BREAKFAST, (copy_item_for_merge(breakfast.items[0], SNACK, 3),), (1,), EDITED_AT
        ),
        lambda: repository.add_items(SNACK, (copy_item_for_merge(breakfast.items[0], SNACK, 3),)),
        lambda: repository.remove_item(SNACK, 1, EDITED_AT),
        lambda: repository.replace_item(SNACK, 1, copy_item_for_merge(breakfast.items[0], SNACK, 3), EDITED_AT),
        lambda: repository.append_nutrition_fact(SNACK, 1, _fact(f"{SNACK}:1:late")),
    ]
    for attempt in attempts:
        with pytest.raises(ValueError, match="voided"):
            attempt()

    assert _tables(database) == rows


# --- schema (append-only) and older databases (AC6) -------------------------------------------------


def test_correction_tables_are_append_only(capsys: pytest.CaptureFixture[str], database: Path) -> None:
    _split_breakfast(capsys)
    _log(capsys, "lunch", *RICE_ITEM)
    _ok(capsys, "nutrition", "meal", "edit", LUNCH, "--time", "12:00")
    _ok(capsys, "nutrition", "meal", "merge", BREAKFAST, BREAKFAST_2)
    rows = _tables(database)

    for table in ("nutrition_meal_revisions", "nutrition_meal_voids", "nutrition_meal_merged_items"):
        for statement in (f"UPDATE {table} SET meal_id = meal_id", f"DELETE FROM {table}"):
            with pytest.raises(sqlite3.IntegrityError, match="append-only"):
                _execute(database, statement)
    # A voided meal cannot get a revision, even when written directly.
    with pytest.raises(sqlite3.IntegrityError, match="a voided meal cannot be revised"):
        _execute(
            database,
            "INSERT INTO nutrition_meal_revisions VALUES "
            f"('{BREAKFAST_2}', 1, 'x', '2026-10-02T09:00:00+09:00', '2026-10-02T00:00:00.000000', 'breakfast')",
        )
    # A mapping row needs a voided source meal.
    with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
        _execute(
            database,
            f"INSERT INTO nutrition_meal_merged_items VALUES ('{BREAKFAST}', 1, '{LUNCH}', 1)",
            foreign_keys=True,
        )
    assert _tables(database) == rows


def test_read_only_paths_still_read_a_database_without_migration_9(
    capsys: pytest.CaptureFixture[str], database: Path
) -> None:
    """`recommend` (and `daily`'s nutrition section) never migrate; a database before 9 must read as before."""
    _training_history(database)
    _foods(capsys)
    _targets(capsys)
    _log(capsys, "breakfast", *CHICKEN_ITEM)
    _log(capsys, "snack", *BANANA_ITEM)
    _log(capsys, "dinner", *RICE_ITEM)
    bounds = (datetime(2026, 10, 2, tzinfo=KST), datetime(2026, 10, 3, tzinfo=KST))
    uncorrected = _ok(capsys, "recommend", "--date", DAY, "--json")
    uncorrected_meals = SqliteNutritionReader(database).list_eaten_between(*bounds)
    _ok(capsys, "nutrition", "meal", "void", SNACK)
    _ok(capsys, "nutrition", "meal", "edit", DINNER, "--date", OTHER_DAY)
    assert _ok(capsys, "recommend", "--date", DAY, "--json") != uncorrected

    # Back to a database last written before migration 9 (no correction tables, no marker).
    for table in ("nutrition_meal_merged_items", "nutrition_meal_voids", "nutrition_meal_revisions"):
        _execute(database, f"DROP TABLE {table}")
    _execute(database, f"DELETE FROM schema_migrations WHERE version = {MIGRATION}")

    assert _ok(capsys, "recommend", "--date", DAY, "--json") == uncorrected
    assert SqliteNutritionReader(database).list_eaten_between(*bounds) == uncorrected_meals
    connection = sqlite3.connect(database)
    try:
        names = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        versions = [row[0] for row in connection.execute("SELECT version FROM schema_migrations ORDER BY version")]
    finally:
        connection.close()
    # The read-only paths did not migrate.
    assert "nutrition_meal_voids" not in names
    assert MIGRATION not in versions


# --- determinism and unchanged neighbours ------------------------------------------------------------


def test_text_and_json_are_deterministic_and_ascii(capsys: pytest.CaptureFixture[str], clock: list[datetime]) -> None:
    _split_breakfast(capsys)
    _log(capsys, "snack", *BANANA_ITEM)
    _log(capsys, "dinner", *CHICKEN_ITEM)
    _ok(capsys, "nutrition", "meal", "void", SNACK, "--reason", "중복 기록")
    clock[0] = EDITED_AT
    _ok(capsys, "nutrition", "meal", "edit", DINNER, "--time", "19:00", "--meal", "lunch")
    clock[0] = MERGED_AT
    _ok(capsys, "nutrition", "meal", "merge", BREAKFAST, BREAKFAST_2)

    meals = (BREAKFAST, BREAKFAST_2, SNACK, DINNER)
    views = _views(capsys, *meals)
    assert _views(capsys, *meals) == views
    for meal_id in meals:
        printed = _ok(capsys, "nutrition", "meal", "show", meal_id, "--json")
        assert printed == json.dumps(json.loads(printed), indent=2) + "\n"
        assert printed.isascii()
        assert _without_names(_ok(capsys, "nutrition", "meal", "show", meal_id), "중복 기록").isascii()


def test_an_untouched_meal_keeps_the_log_document(capsys: pytest.CaptureFixture[str]) -> None:
    _foods(capsys)
    logged = _ok(capsys, "nutrition", "log", "--meal", "breakfast", *CHICKEN_ITEM, "--json")
    _log(capsys, "snack", *BANANA_ITEM)
    _ok(capsys, "nutrition", "meal", "void", SNACK)

    shown = _ok(capsys, "nutrition", "meal", "show", BREAKFAST, "--json")

    assert shown == logged
    assert not set(HISTORY_KEYS) & set(json.loads(shown))
    assert _ok(capsys, "nutrition", "meal", "show", BREAKFAST).splitlines()[-1].startswith("  Meal total:")


# --- helpers ---------------------------------------------------------------------------------------


def _fact(fact_id: str) -> NutritionFact:
    return NutritionFact(
        fact_id=fact_id,
        values=NutritionValue(calories_kcal=Decimal("1")),
        basis_quantity=Decimal("1"),
        basis_unit=QuantityUnit.COUNT,
        provenance=NutritionProvenance(
            source_type=NutritionSourceType.USER_PROVIDED,
            accuracy=Accuracy.EXACT,
            source_reference="synthetic",
            created_at=EDITED_AT,
        ),
    )
