"""`muscle50 nutrition meal show/add-item/remove-item/replace-item`: editing a logged meal's items.

Runs over a temporary MUSCLE50_HOME / temporary SQLite database only. All nutrition values are
synthetic test numbers. The central guarantees: the meal ID never changes, a new item snapshots
the food's facts at the time it is added while existing items keep their own snapshots, a removed
item stops counting everywhere at once, and a refused edit changes nothing at all.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timedelta, timezone, tzinfo
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from analytics_builders import activity, strength_set

import muscle50.cli as cli
from muscle50.application.nutrition_logging import (
    AddMealItems,
    MealEntryItem,
    ReplaceMealItem,
)
from muscle50.cli import main
from muscle50.domain.activity import ActivityType, NormalizedActivity
from muscle50.domain.nutrition import (
    Accuracy,
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
from muscle50.infrastructure.sqlite.nutrition_repository import SqliteFoodNutritionRepository, SqliteMealRepository

KST = timezone(timedelta(hours=9))
DAY = "2026-10-02"
MEAL = "2026-10-02-breakfast-1"
EDITED_AT = datetime(2026, 10, 2, 21, 0, tzinfo=KST)

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
CHICKEN_V3 = (
    ["chicken-breast", "--per", "100", "g"]
    + ["--kcal", "130", "--protein", "25", "--carbs", "1", "--fat", "3"]
    + ["--source", "nutrition_label", "--accuracy", "exact"]
)
RICE = (
    ["--id", "hetbahn-white-210", "--name", "햇반", "--per", "210", "g"]
    + ["--kcal", "315", "--protein", "5", "--carbs", "70", "--fat", "1"]
    + ["--source", "nutrition_label", "--accuracy", "exact"]
)
BANANA = (
    ["--id", "banana-medium", "--name", "바나나", "--per", "1", "count"]
    + ["--kcal", "90", "--protein", "1", "--carbs", "23", "--fat", "0"]
    + ["--source", "food_database", "--accuracy", "exact"]
)
RICE_ITEM = ("--item", "hetbahn-white-210", "210", "g")
BANANA_ITEM = ("--item", "banana-medium", "1", "count")
TABLES = (
    "nutrition_meals",
    "nutrition_meal_items",
    "nutrition_facts",
    "nutrition_meal_item_removals",
    "nutrition_food_profiles",
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


def _foods(capsys: pytest.CaptureFixture[str]) -> None:
    for food in (CHICKEN, RICE, BANANA):
        _ok(capsys, "nutrition", "food", "add", *food)


def _breakfast(capsys: pytest.CaptureFixture[str]) -> None:
    """The user's case: breakfast logged with chicken only."""
    _foods(capsys)
    _ok(capsys, "nutrition", "log", "--date", DAY, "--meal", "breakfast", "--item", "chicken-breast", "200", "g")


def _add(capsys: pytest.CaptureFixture[str], *items: str) -> str:
    return _ok(capsys, "nutrition", "meal", "add-item", MEAL, *items)


def _day(capsys: pytest.CaptureFixture[str]) -> Any:
    return _json(capsys, "nutrition", "day", "--date", DAY)


def _show(capsys: pytest.CaptureFixture[str]) -> Any:
    return _json(capsys, "nutrition", "meal", "show", MEAL)


def _items(capsys: pytest.CaptureFixture[str]) -> dict[int, Any]:
    return {item["sequence"]: item for item in _show(capsys)["items"]}


def _selected_facts(item: dict[str, Any]) -> set[str]:
    return {nutrient["fact_id"] for nutrient in item["nutrients"].values() if nutrient is not None}


def _tables(database: Path) -> dict[str, list[tuple[Any, ...]]]:
    """Every nutrition row, so a refused edit can be checked for "nothing changed" exactly."""
    connection = sqlite3.connect(database)
    try:
        return {table: connection.execute(f"SELECT * FROM {table} ORDER BY 1, 2").fetchall() for table in TABLES}
    finally:
        connection.close()


def _views(capsys: pytest.CaptureFixture[str]) -> tuple[str, ...]:
    """Every read view of the meal and its day, text and JSON, byte for byte."""
    return tuple(
        _ok(capsys, *command, *flags)
        for command in (
            ("nutrition", "meal", "show", MEAL),
            ("nutrition", "day", "--date", DAY),
            ("nutrition", "status", "--date", DAY),
        )
        for flags in ((), ("--json",))
    )


def _targets(capsys: pytest.CaptureFixture[str]) -> None:
    _ok(capsys, "nutrition", "target", "set", "kcal", "--exact", "2400")
    _ok(capsys, "nutrition", "target", "set", "protein", "--range", "150", "170")
    _ok(capsys, "nutrition", "target", "set", "carbs", "--exact", "300")


def _status(capsys: pytest.CaptureFixture[str]) -> dict[str, Any]:
    nutrients: dict[str, Any] = _json(capsys, "nutrition", "status", "--date", DAY)["nutrients"]
    return nutrients


def _bench(database: Path, source_id: str, day: str) -> None:
    sets = tuple(strength_set(index, reps=10, weight_kg=50.0) for index in range(1, 4))
    item: NormalizedActivity = activity(source_id, f"{day}T12:00:00", ActivityType.STRENGTH, strength_sets=sets)
    artifact = RawArtifact("activity", f"raw/{source_id}/activity.json", "application/json", "0" * 64, 2)
    ActivityRepository(database).save(item, (artifact,))


def _recommend(capsys: pytest.CaptureFixture[str]) -> dict[str, Any]:
    document: dict[str, Any] = json.loads(_ok(capsys, "recommend", "--date", DAY, "--json"))
    return document


def _training_only(document: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in document.items() if key != "nutrition"}


# --- show -----------------------------------------------------------------------------------


def test_show_prints_the_meal_items_quantities_and_fact_versions(capsys: pytest.CaptureFixture[str]) -> None:
    _breakfast(capsys)

    assert _ok(capsys, "nutrition", "meal", "show", MEAL).splitlines() == [
        f"[breakfast] {MEAL} (2026-10-02, time not recorded)",
        "  1. 닭가슴살 (chicken-breast) 200 g: kcal 200 | P 40 g | C 0 g | F 4 g",
        "     source: user_provided/exact",
        "     facts: food:chicken-breast:1",
        "  Meal total: kcal 200 | P 40 g | C 0 g | F 4 g",
    ]
    shown = _show(capsys)
    assert shown["meal_id"] == MEAL
    assert shown["meal_type"] == "breakfast"
    assert shown["eaten_at"] == "2026-10-02T00:00:00+09:00"
    (item,) = shown["items"]
    assert (item["food_id"], item["quantity"], item["unit"]) == ("chicken-breast", "200", "g")
    assert item["facts"][0]["source_type"] == "user_provided"
    # Same document as `nutrition log --json` prints for the meal.
    assert shown == _day(capsys)["meals"][0]


def test_show_unknown_meal_is_an_error(capsys: pytest.CaptureFixture[str]) -> None:
    _breakfast(capsys)
    code, out, err = _run(capsys, "nutrition", "meal", "show", "2026-10-02-breakfast-9")
    assert (code, out) == (1, "")
    assert "no meal with id '2026-10-02-breakfast-9'" in err


# --- A/B/C: add items to the logged breakfast -----------------------------------------------


def test_a_two_items_added_to_a_one_item_breakfast_keep_one_meal(
    capsys: pytest.CaptureFixture[str], database: Path
) -> None:
    _breakfast(capsys)
    original_text = _show(capsys)["original_text"]
    assert _day(capsys)["total"]["item_count"] == 1

    first = _add(capsys, *RICE_ITEM)
    second = _add(capsys, *BANANA_ITEM)

    assert first.splitlines()[0] == f"Added item 2 to meal {MEAL}."
    assert second.splitlines()[0] == f"Added item 3 to meal {MEAL}."
    day = _day(capsys)
    (meal,) = day["meals"]
    assert meal["meal_id"] == MEAL
    assert [item["food_id"] for item in meal["items"]] == ["chicken-breast", "hetbahn-white-210", "banana-medium"]
    assert [item["sequence"] for item in meal["items"]] == [1, 2, 3]
    assert day["total"]["item_count"] == 3
    assert day["total"]["totals"] == {"calories_kcal": "605", "protein_g": "46", "carbohydrate_g": "93", "fat_g": "5"}
    assert meal["total"]["totals"] == day["total"]["totals"]
    # The log-time record of what was entered is kept as it was.
    assert meal["original_text"] == original_text
    connection = sqlite3.connect(database)
    try:
        assert connection.execute("SELECT COUNT(*) FROM nutrition_meals").fetchone()[0] == 1
    finally:
        connection.close()
    text = _ok(capsys, "nutrition", "day", "--date", DAY)
    assert "Consumed (1 meal, 3 items):" in text


def test_a_several_items_in_one_command_are_added_together(capsys: pytest.CaptureFixture[str]) -> None:
    _breakfast(capsys)

    out = _add(capsys, *RICE_ITEM, *BANANA_ITEM)

    assert out.splitlines()[0] == f"Added items 2, 3 to meal {MEAL}."
    assert out.splitlines()[-1] == f"Whole day: muscle50 nutrition day --date {DAY}"
    assert sorted(_items(capsys)) == [1, 2, 3]
    assert _day(capsys)["total"]["totals"]["calories_kcal"] == "605"


def test_b_add_item_updates_nutrition_status(capsys: pytest.CaptureFixture[str]) -> None:
    _breakfast(capsys)
    _targets(capsys)
    before = _status(capsys)
    assert (before["calories_kcal"]["consumed"], before["calories_kcal"]["remaining"]) == ("200", "2200")
    assert before["carbohydrate_g"]["consumed"] == "0"

    _add(capsys, *RICE_ITEM, *BANANA_ITEM)

    after = _status(capsys)
    assert (after["calories_kcal"]["consumed"], after["calories_kcal"]["remaining"]) == ("605", "1795")
    assert after["protein_g"]["consumed"] == "46"
    assert (after["carbohydrate_g"]["consumed"], after["carbohydrate_g"]["remaining"]) == ("93", "207")


def test_c_add_item_updates_the_recommendation_nutrition_but_not_the_training_plan(
    capsys: pytest.CaptureFixture[str], database: Path
) -> None:
    ActivityRepository(database).migrate()
    _bench(database, "9001", "2026-09-26")
    _bench(database, "9002", "2026-09-29")
    _breakfast(capsys)
    _targets(capsys)
    before = _recommend(capsys)
    assert before["nutrition"]["nutrients"]["calories_kcal"]["consumed"] == "200"

    _add(capsys, *RICE_ITEM, *BANANA_ITEM)

    after = _recommend(capsys)
    assert after["nutrition"]["nutrients"]["calories_kcal"]["consumed"] == "605"
    assert after["nutrition"]["nutrients"]["carbohydrate_g"]["consumed"] == "93"
    assert _training_only(after) == _training_only(before)
    text = _ok(capsys, "recommend", "--date", DAY)
    assert "  kcal          605; target 2400 (exact): below target, 1795 to go" in text


# --- D: fact version snapshots ----------------------------------------------------------------


def test_d_existing_item_keeps_its_fact_and_a_new_item_snapshots_the_current_one(
    capsys: pytest.CaptureFixture[str],
) -> None:
    _breakfast(capsys)
    _ok(capsys, "nutrition", "food", "fact", "add", *CHICKEN_V2)
    item_1_before = _items(capsys)[1]

    _add(capsys, "--item", "chicken-breast", "100", "g")

    items = _items(capsys)
    assert items[1] == item_1_before
    assert _selected_facts(items[1]) == {f"{MEAL}:1:food:chicken-breast:1"}
    assert _selected_facts(items[2]) == {f"{MEAL}:2:food:chicken-breast:2"}
    assert items[1]["nutrients"]["calories_kcal"]["value"] == "200"
    assert items[2]["nutrients"]["calories_kcal"]["value"] == "120"
    # The new item carries the whole same-unit history (v1 and v2), as `nutrition log` does.
    assert [fact["fact_id"] for fact in items[2]["facts"]] == [
        f"{MEAL}:2:food:chicken-breast:1",
        f"{MEAL}:2:food:chicken-breast:2",
    ]
    text = _ok(capsys, "nutrition", "meal", "show", MEAL)
    assert "     facts: food:chicken-breast:1\n" in text
    assert "     facts: food:chicken-breast:2\n" in text

    # A later catalog version changes neither item.
    _ok(capsys, "nutrition", "food", "fact", "add", *CHICKEN_V3)
    assert _items(capsys) == items
    _add(capsys, "--item", "chicken-breast", "100", "g")
    assert _selected_facts(_items(capsys)[3]) == {f"{MEAL}:3:food:chicken-breast:3"}
    assert {sequence: item for sequence, item in _items(capsys).items() if sequence < 3} == items


# --- E: remove an item --------------------------------------------------------------------------


def test_e_remove_item_drops_only_that_item_everywhere(capsys: pytest.CaptureFixture[str], database: Path) -> None:
    ActivityRepository(database).migrate()
    _bench(database, "9001", "2026-09-26")
    _bench(database, "9002", "2026-09-29")
    _breakfast(capsys)
    _targets(capsys)
    _add(capsys, *RICE_ITEM, *BANANA_ITEM)
    items_before = _items(capsys)
    recommendation_before = _recommend(capsys)

    out = _ok(capsys, "nutrition", "meal", "remove-item", MEAL, "--item-number", "2")

    assert out.splitlines()[0] == f"Removed item 2 from meal {MEAL}."
    items = _items(capsys)
    assert sorted(items) == [1, 3]
    assert items[1] == items_before[1]
    assert items[3] == items_before[3]
    day = _day(capsys)
    assert [meal["meal_id"] for meal in day["meals"]] == [MEAL]
    assert day["total"]["item_count"] == 2
    assert day["total"]["totals"] == {"calories_kcal": "290", "protein_g": "41", "carbohydrate_g": "23", "fat_g": "4"}
    assert _status(capsys)["calories_kcal"]["consumed"] == "290"
    recommendation = _recommend(capsys)
    assert recommendation["nutrition"]["nutrients"]["calories_kcal"]["consumed"] == "290"
    assert _training_only(recommendation) == _training_only(recommendation_before)
    assert "hetbahn" not in _ok(capsys, "nutrition", "day", "--date", DAY)
    # Kept for audit, never deleted: the item row, its facts and the removal record.
    tables = _tables(database)
    assert [row[1] for row in tables["nutrition_meal_items"]] == [1, 2, 3]
    assert sum(1 for row in tables["nutrition_facts"] if row[1] == MEAL and row[2] == 2) == 1
    ((meal_id, sequence, removed_at, replaced_by),) = tables["nutrition_meal_item_removals"]
    assert (meal_id, sequence, replaced_by) == (MEAL, 2, None)
    assert datetime.fromisoformat(removed_at).tzinfo is not None


def test_e_item_numbers_are_never_reused_after_a_removal(capsys: pytest.CaptureFixture[str]) -> None:
    _breakfast(capsys)
    _add(capsys, *RICE_ITEM, *BANANA_ITEM)
    _ok(capsys, "nutrition", "meal", "remove-item", MEAL, "--item-number", "3")

    out = _add(capsys, *BANANA_ITEM)

    assert out.splitlines()[0] == f"Added item 4 to meal {MEAL}."
    assert sorted(_items(capsys)) == [1, 2, 4]
    assert _selected_facts(_items(capsys)[4]) == {f"{MEAL}:4:food:banana-medium:1"}


def test_e_removing_the_last_item_is_refused(capsys: pytest.CaptureFixture[str], database: Path) -> None:
    _breakfast(capsys)
    rows = _tables(database)
    views = _views(capsys)

    code, out, err = _run(capsys, "nutrition", "meal", "remove-item", MEAL, "--item-number", "1")

    assert (code, out) == (1, "")
    assert "only item of meal" in err
    assert "replace-item" in err
    assert "Nothing was changed." in err
    assert _tables(database) == rows
    assert _views(capsys) == views


def test_e_repository_refuses_to_empty_a_meal_inside_its_transaction(
    capsys: pytest.CaptureFixture[str], database: Path
) -> None:
    """The use case checks first; the repository re-checks under its write lock."""
    _breakfast(capsys)
    _add(capsys, *BANANA_ITEM)
    repository = SqliteMealRepository(database)
    repository.remove_item(MEAL, 1, EDITED_AT)
    rows = _tables(database)

    with pytest.raises(ValueError, match="cannot be left empty"):
        repository.remove_item(MEAL, 2, EDITED_AT)

    assert _tables(database) == rows


# --- F: refused edits change nothing ------------------------------------------------------------


@pytest.mark.parametrize(
    ("argv", "message"),
    [
        (("add-item", "2026-10-02-lunch-1", *BANANA_ITEM), "no meal with id '2026-10-02-lunch-1'"),
        (("add-item", MEAL, "--item", "ghost", "1", "count"), "--item 1: no food with id 'ghost'"),
        (("add-item", MEAL, *BANANA_ITEM, "--item", "ghost", "1", "count"), "--item 2: no food with id 'ghost'"),
        (("add-item", MEAL, "--item", "banana-medium", "100", "g"), "has nutrition per count, not per g"),
        (("add-item", MEAL, "--item", "banana-medium", "1", "cup"), "unit 'cup' is not supported"),
        (("add-item", MEAL, "--item", "banana-medium", "0", "count"), "must be greater than 0"),
        (("add-item", MEAL, "--item", "banana-medium", "-1", "count"), "plain non-negative number"),
        (("add-item", MEAL, "--item", "banana-medium", "abc", "count"), "plain non-negative number"),
        (("remove-item", "2026-10-02-lunch-1", "--item-number", "1"), "no meal with id"),
        (("remove-item", MEAL, "--item-number", "5"), "has no item 5 (its items are 1, 2)"),
        (("remove-item", MEAL, "--item-number", "0"), "has no item 0"),
        (("replace-item", MEAL, "--item-number", "5", *BANANA_ITEM), "has no item 5"),
        (("replace-item", "2026-10-02-lunch-1", "--item-number", "1", *BANANA_ITEM), "no meal with id"),
        (("replace-item", MEAL, "--item-number", "1", "--item", "ghost", "1", "g"), "no food with id 'ghost'"),
        (("replace-item", MEAL, "--item-number", "1", "--item", "banana-medium", "1", "g"), "not per g"),
    ],
)
def test_f_refused_edit_changes_nothing(
    capsys: pytest.CaptureFixture[str], database: Path, argv: tuple[str, ...], message: str
) -> None:
    _breakfast(capsys)
    _add(capsys, *RICE_ITEM)
    rows = _tables(database)
    views = _views(capsys)

    code, out, err = _run(capsys, "nutrition", "meal", *argv)

    assert (code, out) == (1, "")
    assert message in err
    # Malformed quantities/units are refused while the arguments are read, before any lookup.
    if not any(parse_error in message for parse_error in ("is not supported", "greater than 0", "plain non-negative")):
        assert err.rstrip().endswith("Nothing was changed.")
    assert _tables(database) == rows
    assert _views(capsys) == views


def test_f_an_already_removed_item_cannot_be_removed_or_replaced_again(
    capsys: pytest.CaptureFixture[str], database: Path
) -> None:
    _breakfast(capsys)
    _add(capsys, *RICE_ITEM, *BANANA_ITEM)
    _ok(capsys, "nutrition", "meal", "remove-item", MEAL, "--item-number", "2")
    rows = _tables(database)

    for argv in (("remove-item", MEAL, "--item-number", "2"), ("replace-item", MEAL, "--item-number", "2", *RICE_ITEM)):
        code, _out, err = _run(capsys, "nutrition", "meal", *argv)
        assert code == 1
        assert "has no item 2 (its items are 1, 3)" in err

    assert _tables(database) == rows
    with pytest.raises(ValueError, match="no meal item"):
        SqliteMealRepository(database).append_nutrition_fact(MEAL, 2, _fact(f"{MEAL}:2:late"))
    with pytest.raises(ValueError, match="already removed"):
        SqliteMealRepository(database).remove_item(MEAL, 2, EDITED_AT)
    assert _tables(database) == rows


def test_f_missing_or_malformed_arguments_are_argparse_errors(
    capsys: pytest.CaptureFixture[str], database: Path
) -> None:
    _breakfast(capsys)
    rows = _tables(database)
    for argv in (
        ("add-item", MEAL),
        ("remove-item", MEAL),
        ("remove-item", MEAL, "--item-number", "two"),
        ("replace-item", MEAL, "--item-number", "1"),
        ("replace-item", MEAL, *BANANA_ITEM),
    ):
        with pytest.raises(SystemExit) as raised:
            main(["nutrition", "meal", *argv])
        assert raised.value.code == 2
    capsys.readouterr()
    assert _tables(database) == rows


def test_f_storage_failure_while_adding_rolls_back_every_item(
    capsys: pytest.CaptureFixture[str], database: Path
) -> None:
    _breakfast(capsys)
    rows = _tables(database)
    views = _views(capsys)
    # Fail on the second new item's facts, after the first item was already inserted.
    _execute(
        database,
        "CREATE TRIGGER fail_banana BEFORE INSERT ON nutrition_facts WHEN NEW.fact_id LIKE '%banana%' "
        "BEGIN SELECT RAISE(ABORT, 'synthetic storage failure'); END",
    )
    entries = (
        MealEntryItem("hetbahn-white-210", Decimal("210"), QuantityUnit.GRAM),
        MealEntryItem("banana-medium", Decimal("1"), QuantityUnit.COUNT),
    )

    with pytest.raises(sqlite3.IntegrityError, match="synthetic storage failure"):
        AddMealItems(SqliteMealRepository(database), SqliteFoodNutritionRepository(database)).execute(MEAL, entries)

    _execute(database, "DROP TRIGGER fail_banana")
    assert _tables(database) == rows
    assert _views(capsys) == views


# --- G: replace an item ---------------------------------------------------------------------------


def test_g_replace_item_swaps_one_item_in_one_step(capsys: pytest.CaptureFixture[str], database: Path) -> None:
    _breakfast(capsys)
    _add(capsys, *RICE_ITEM)
    item_1 = _items(capsys)[1]

    out = _ok(
        capsys, "nutrition", "meal", "replace-item", MEAL, "--item-number", "2", "--item", RICE_ITEM[1], "105", "g"
    )

    assert out.splitlines()[0] == f"Replaced item 2 of meal {MEAL} with item 3."
    items = _items(capsys)
    assert sorted(items) == [1, 3]
    assert items[1] == item_1
    assert (items[3]["food_id"], items[3]["quantity"], items[3]["unit"]) == ("hetbahn-white-210", "105", "g")
    assert _day(capsys)["total"]["totals"]["calories_kcal"] == "357.5"
    ((meal_id, sequence, _removed_at, replaced_by),) = _tables(database)["nutrition_meal_item_removals"]
    assert (meal_id, sequence, replaced_by) == (MEAL, 2, 3)


def test_g_the_only_item_can_be_replaced(capsys: pytest.CaptureFixture[str]) -> None:
    _breakfast(capsys)
    _ok(capsys, "nutrition", "meal", "replace-item", MEAL, "--item-number", "1", "--item", "chicken-breast", "150", "g")
    items = _items(capsys)
    assert sorted(items) == [2]
    assert items[2]["quantity"] == "150"


@pytest.mark.parametrize(
    "trigger",
    [
        # The new item's facts fail to insert: the item row before them must not survive.
        "CREATE TRIGGER fail_step BEFORE INSERT ON nutrition_facts "
        "BEGIN SELECT RAISE(ABORT, 'synthetic storage failure'); END",
        # The new item and its facts are written, then recording the removal fails.
        "CREATE TRIGGER fail_step BEFORE INSERT ON nutrition_meal_item_removals "
        "BEGIN SELECT RAISE(ABORT, 'synthetic storage failure'); END",
    ],
)
def test_g_replace_failing_at_either_step_keeps_the_old_item_and_writes_nothing(
    capsys: pytest.CaptureFixture[str], database: Path, trigger: str
) -> None:
    _breakfast(capsys)
    _add(capsys, *RICE_ITEM)
    rows = _tables(database)
    views = _views(capsys)
    _execute(database, trigger)

    with pytest.raises(sqlite3.IntegrityError, match="synthetic storage failure"):
        ReplaceMealItem(
            SqliteMealRepository(database), SqliteFoodNutritionRepository(database), clock=lambda: EDITED_AT
        ).execute(MEAL, 2, MealEntryItem("banana-medium", Decimal("1"), QuantityUnit.COUNT))

    _execute(database, "DROP TRIGGER fail_step")
    assert _tables(database) == rows
    assert _views(capsys) == views
    assert sorted(_items(capsys)) == [1, 2]


# --- H: the same add run twice --------------------------------------------------------------------


def test_h_running_the_same_add_twice_adds_two_items(capsys: pytest.CaptureFixture[str]) -> None:
    """No automatic de-duplication: the second run is a second item, visible in the output."""
    _breakfast(capsys)
    _add(capsys, *BANANA_ITEM)

    out = _add(capsys, *BANANA_ITEM)

    assert out.splitlines()[0] == f"Added item 3 to meal {MEAL}."
    assert "  2. 바나나 (banana-medium) 1 count" in out
    assert "  3. 바나나 (banana-medium) 1 count" in out
    assert _day(capsys)["total"]["totals"]["calories_kcal"] == "380"
    # The mistake is undone with remove-item.
    _ok(capsys, "nutrition", "meal", "remove-item", MEAL, "--item-number", "3")
    assert _day(capsys)["total"]["totals"]["calories_kcal"] == "290"


# --- other meals, read-only reader and determinism -----------------------------------------------


def test_editing_one_meal_leaves_other_meals_byte_identical(capsys: pytest.CaptureFixture[str]) -> None:
    _breakfast(capsys)
    _ok(capsys, "nutrition", "log", "--date", DAY, "--meal", "lunch", *RICE_ITEM)
    lunch = _json(capsys, "nutrition", "meal", "show", "2026-10-02-lunch-1")
    other_day = _ok(capsys, "nutrition", "day", "--date", "2026-10-01", "--json")

    _add(capsys, *BANANA_ITEM)
    _ok(capsys, "nutrition", "meal", "remove-item", MEAL, "--item-number", "1")

    assert _json(capsys, "nutrition", "meal", "show", "2026-10-02-lunch-1") == lunch
    assert _ok(capsys, "nutrition", "day", "--date", "2026-10-01", "--json") == other_day
    assert [meal["meal_id"] for meal in _day(capsys)["meals"]] == [MEAL, "2026-10-02-lunch-1"]


def test_read_only_reader_skips_removed_items(capsys: pytest.CaptureFixture[str], database: Path) -> None:
    _breakfast(capsys)
    _add(capsys, *BANANA_ITEM)
    _ok(capsys, "nutrition", "meal", "remove-item", MEAL, "--item-number", "1")

    (meal,) = SqliteNutritionReader(database).list_eaten_between(
        datetime(2026, 10, 2, tzinfo=KST), datetime(2026, 10, 3, tzinfo=KST)
    )

    assert [item.sequence for item in meal.items] == [2]


def test_read_only_reader_still_reads_a_database_without_migration_8(
    capsys: pytest.CaptureFixture[str], database: Path
) -> None:
    """`recommend` never migrates, so a database last written before Meal Edit must still read."""
    _breakfast(capsys)
    _execute(database, "DROP TABLE nutrition_meal_item_removals")
    _execute(database, "DELETE FROM schema_migrations WHERE version = 8")

    (meal,) = SqliteNutritionReader(database).list_eaten_between(
        datetime(2026, 10, 2, tzinfo=KST), datetime(2026, 10, 3, tzinfo=KST)
    )

    assert meal.meal_id == MEAL
    assert [item.food_profile_id for item in meal.items] == ["chicken-breast"]


def test_removals_are_append_only(capsys: pytest.CaptureFixture[str], database: Path) -> None:
    _breakfast(capsys)
    _add(capsys, *BANANA_ITEM)
    _ok(capsys, "nutrition", "meal", "remove-item", MEAL, "--item-number", "2")
    for statement in (
        "UPDATE nutrition_meal_item_removals SET removed_at = 'x'",
        "DELETE FROM nutrition_meal_item_removals",
    ):
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            _execute(database, statement)
    assert sorted(_items(capsys)) == [1]


def test_text_and_json_are_deterministic(capsys: pytest.CaptureFixture[str]) -> None:
    _breakfast(capsys)
    _add(capsys, *RICE_ITEM, *BANANA_ITEM)
    _ok(
        capsys, "nutrition", "meal", "replace-item", MEAL, "--item-number", "3", "--item", "banana-medium", "2", "count"
    )

    assert _views(capsys) == _views(capsys)
    shown = _ok(capsys, "nutrition", "meal", "show", MEAL, "--json")
    assert shown == json.dumps(json.loads(shown), indent=2) + "\n"


# --- helpers ---------------------------------------------------------------------------------------


def _execute(database: Path, statement: str) -> None:
    connection = sqlite3.connect(database)
    try:
        connection.execute(statement)
        connection.commit()
    finally:
        connection.close()


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
