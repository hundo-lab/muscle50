"""`muscle50 nutrition repeat <meal_id>`: log a new meal with the same foods and amounts as a logged one.

Runs over a temporary MUSCLE50_HOME / temporary SQLite database only. All nutrition values are
synthetic test numbers. The central guarantees: only the source's active items are repeated, only
their food ID, quantity and unit are reused (the new meal snapshots the catalog facts as they are
now, through `LogMeal`), unknown nutrients stay unknown, the source meal is never changed, the
duplicate-meal guard is unchanged, and a refused repeat writes nothing at all.
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
from muscle50.application.nutrition_logging import RepeatMeal
from muscle50.cli import main
from muscle50.domain.activity import ActivityType, NormalizedActivity
from muscle50.domain.nutrition import Meal, MealItem, MealType, QuantityUnit
from muscle50.infrastructure.garmin.client import PythonGarminConnector
from muscle50.infrastructure.raw_store import RawArtifact
from muscle50.infrastructure.sqlite.database import ActivityRepository
from muscle50.infrastructure.sqlite.nutrition_repository import SqliteFoodNutritionRepository, SqliteMealRepository

KST = timezone(timedelta(hours=9))
SOURCE_DAY = "2026-10-02"
TODAY = "2026-10-03"
SOURCE = "2026-10-02-breakfast-1"
NEW = "2026-10-03-breakfast-1"

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
# Fat is unknown on the label: it must stay missing in every repeated meal, never become 0.
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
SOURCE_ITEMS = (
    ("--item", "chicken-breast", "200", "g"),
    ("--item", "hetbahn-white-210", "210", "g"),
    ("--item", "banana-medium", "1", "count"),
)
ENTRY_TEXT = "chicken-breast 200 g; hetbahn-white-210 210 g; banana-medium 1 count"
TABLES = (
    "nutrition_meals",
    "nutrition_meal_items",
    "nutrition_facts",
    "nutrition_meal_item_removals",
    "nutrition_food_profiles",
)
NEW_MEAL_LINES = [
    f"[breakfast] {NEW} ({TODAY}, time not recorded)",
    "  1. 닭가슴살 (chicken-breast) 200 g: kcal 200 | P 40 g | C 0 g | F 4 g",
    "     source: user_provided/exact",
    "  2. 햇반 (hetbahn-white-210) 210 g: kcal 315 | P 5 g | C 70 g | F missing",
    "     source: nutrition_label/exact",
    "     missing: fat",
    "  3. 바나나 (banana-medium) 1 count: kcal 90 | P 1 g | C 23 g | F 0 g",
    "     source: food_database/exact",
    "  Meal total: kcal 605 | P 46 g | C 93 g | F incomplete (known items only: 4 g)",
]


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
    monkeypatch.setattr(cli, "_today", lambda: date(2026, 10, 3))
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


def _source(capsys: pytest.CaptureFixture[str]) -> str:
    """Catalog plus yesterday's timed breakfast of chicken, rice (fat unknown) and banana; returns the log text."""
    for food in (CHICKEN, RICE, BANANA):
        _ok(capsys, "nutrition", "food", "add", *food)
    items = [token for item in SOURCE_ITEMS for token in item]
    return _ok(capsys, "nutrition", "log", "--date", SOURCE_DAY, "--time", "07:30", "--meal", "breakfast", *items)


def _repeat(capsys: pytest.CaptureFixture[str], *argv: str) -> str:
    return _ok(capsys, "nutrition", "repeat", SOURCE, *argv)


def _show(capsys: pytest.CaptureFixture[str], meal_id: str) -> Any:
    return _json(capsys, "nutrition", "meal", "show", meal_id)


def _selected_facts(item: dict[str, Any]) -> set[str]:
    return {nutrient["fact_id"] for nutrient in item["nutrients"].values() if nutrient is not None}


def _tables(database: Path) -> dict[str, list[tuple[Any, ...]]]:
    connection = sqlite3.connect(database)
    try:
        return {table: connection.execute(f"SELECT * FROM {table} ORDER BY 1, 2").fetchall() for table in TABLES}
    finally:
        connection.close()


def _rows_of(database: Path, meal_id: str) -> dict[str, list[tuple[Any, ...]]]:
    """Every stored row that belongs to one meal (meal, items, item facts, removals)."""
    tables = _tables(database)
    return {
        "meal": [row for row in tables["nutrition_meals"] if row[0] == meal_id],
        "items": [row for row in tables["nutrition_meal_items"] if row[0] == meal_id],
        "facts": [row for row in tables["nutrition_facts"] if row[1] == meal_id],
        "removals": [row for row in tables["nutrition_meal_item_removals"] if row[0] == meal_id],
    }


def _views(capsys: pytest.CaptureFixture[str], meal_id: str, day: str) -> tuple[str, ...]:
    """Every read view of a meal and its day, text and JSON, byte for byte."""
    return tuple(
        _ok(capsys, *command, *flags)
        for command in (
            ("nutrition", "meal", "show", meal_id),
            ("nutrition", "day", "--date", day),
            ("nutrition", "status", "--date", day),
        )
        for flags in ((), ("--json",))
    )


def _execute(database: Path, statement: str) -> None:
    connection = sqlite3.connect(database)
    try:
        connection.execute(statement)
        connection.commit()
    finally:
        connection.close()


# --- 1. same foods/amounts/units, new meal, source byte-identical -------------------------------


def test_1_repeat_logs_the_same_items_as_a_new_meal_and_leaves_the_source_byte_identical(
    capsys: pytest.CaptureFixture[str], database: Path
) -> None:
    _source(capsys)
    source_rows = _rows_of(database, SOURCE)
    source_views = _views(capsys, SOURCE, SOURCE_DAY)

    out = _repeat(capsys)

    assert out.splitlines() == [
        f"Recorded meal {NEW} (repeated from {SOURCE}).",
        "",
        *NEW_MEAL_LINES,
        "",
        f"Whole day: muscle50 nutrition day --date {TODAY}",
    ]
    assert "Nutrition facts changed" not in out
    new = _show(capsys, NEW)
    source = _show(capsys, SOURCE)
    assert [(item["food_id"], item["quantity"], item["unit"]) for item in new["items"]] == [
        (item["food_id"], item["quantity"], item["unit"]) for item in source["items"]
    ]
    assert [item["sequence"] for item in new["items"]] == [1, 2, 3]
    assert new["meal_type"] == "breakfast"
    assert (new["eaten_at"], new["time_recorded"]) == (f"{TODAY}T00:00:00+09:00", False)
    assert new["original_text"] == f"repeated from {SOURCE}; structured entry breakfast {TODAY}: {ENTRY_TEXT}"
    assert new["total"]["totals"] == source["total"]["totals"]
    # The new meal owns its own snapshots of the catalog facts, not copies of the source's snapshots.
    assert [_selected_facts(item) for item in new["items"]] == [
        {f"{NEW}:1:food:chicken-breast:1"},
        {f"{NEW}:2:food:hetbahn-white-210:1"},
        {f"{NEW}:3:food:banana-medium:1"},
    ]
    assert _rows_of(database, SOURCE) == source_rows
    assert _views(capsys, SOURCE, SOURCE_DAY) == source_views
    assert [meal["meal_id"] for meal in _json(capsys, "nutrition", "day")["meals"]] == [NEW]


# --- 2. removed items are skipped, replacement items included ------------------------------------


def test_2_only_the_source_active_items_are_repeated(capsys: pytest.CaptureFixture[str], database: Path) -> None:
    _source(capsys)
    _ok(capsys, "nutrition", "meal", "remove-item", SOURCE, "--item-number", "2")
    two_bananas = ("--item", "banana-medium", "2", "count")
    _ok(capsys, "nutrition", "meal", "replace-item", SOURCE, "--item-number", "3", *two_bananas)
    assert [item["sequence"] for item in _show(capsys, SOURCE)["items"]] == [1, 4]
    source_rows = _rows_of(database, SOURCE)

    _repeat(capsys)

    new = _show(capsys, NEW)
    assert [(item["sequence"], item["food_id"], item["quantity"], item["unit"]) for item in new["items"]] == [
        (1, "chicken-breast", "200", "g"),
        (2, "banana-medium", "2", "count"),
    ]
    assert new["total"]["totals"] == {"calories_kcal": "380", "protein_g": "42", "carbohydrate_g": "46", "fat_g": "4"}
    assert new["original_text"] == (
        f"repeated from {SOURCE}; structured entry breakfast {TODAY}: chicken-breast 200 g; banana-medium 2 count"
    )
    # Nothing about the source's removals is carried over: the new meal has no removed items.
    assert _rows_of(database, NEW)["removals"] == []
    assert _rows_of(database, SOURCE) == source_rows


# --- 3. unknown nutrients stay unknown --------------------------------------------------------------


def test_3_an_unknown_nutrient_is_never_turned_into_zero(capsys: pytest.CaptureFixture[str], database: Path) -> None:
    _source(capsys)

    out = _repeat(capsys)

    new = _show(capsys, NEW)
    rice = new["items"][1]
    assert rice["food_id"] == "hetbahn-white-210"
    assert rice["nutrients"]["fat_g"] is None
    assert rice["missing_fields"] == ["fat_g"]
    assert new["total"]["totals"]["fat_g"] is None
    assert new["total"]["known_subtotals"]["fat_g"] == "4"
    assert new["total"]["incomplete_fields"] == ["fat_g"]
    assert new["total"]["complete"] is False
    assert "F missing" in out
    assert "F incomplete (known items only: 4 g)" in out
    day = _json(capsys, "nutrition", "day")
    assert day["total"]["totals"]["fat_g"] is None
    assert day["total"]["incomplete_fields"] == ["fat_g"]
    # Stored as NULL, not '0'.
    rice_facts = [row for row in _rows_of(database, NEW)["facts"] if row[2] == 2]
    assert [row[7] for row in rice_facts] == [None]


# --- 4. a fact correction: the repeat uses the current fact, the source keeps its own -------------


def test_4_after_a_fact_correction_the_repeat_uses_the_current_fact_and_says_so(
    capsys: pytest.CaptureFixture[str], database: Path
) -> None:
    _source(capsys)
    _ok(capsys, "nutrition", "food", "fact", "add", *CHICKEN_V2)
    source_rows = _rows_of(database, SOURCE)
    source_views = _views(capsys, SOURCE, SOURCE_DAY)

    out = _repeat(capsys)

    new_chicken = _show(capsys, NEW)["items"][0]
    source_chicken = _show(capsys, SOURCE)["items"][0]
    assert _selected_facts(new_chicken) == {f"{NEW}:1:food:chicken-breast:2"}
    assert _selected_facts(source_chicken) == {f"{SOURCE}:1:food:chicken-breast:1"}
    assert new_chicken["nutrients"]["calories_kcal"]["value"] == "240"
    assert source_chicken["nutrients"]["calories_kcal"]["value"] == "200"
    # Like `nutrition log`, the item carries the food's whole same-unit history.
    assert [fact["fact_id"] for fact in new_chicken["facts"]] == [
        f"{NEW}:1:food:chicken-breast:1",
        f"{NEW}:1:food:chicken-breast:2",
    ]
    lines = out.splitlines()
    note = lines.index("Nutrition facts changed since the source meal; this meal uses the current catalog facts:")
    assert lines[note + 1 : note + 3] == [
        "  item 1 닭가슴살 (chicken-breast) uses food:chicken-breast:2; source item 1 used food:chicken-breast:1",
        "",
    ]
    assert "  1. 닭가슴살 (chicken-breast) 200 g: kcal 240 | P 36 g | C 4 g | F 8 g" in lines
    assert "     source: food_database/estimated" in lines
    assert _rows_of(database, SOURCE) == source_rows
    assert _views(capsys, SOURCE, SOURCE_DAY) == source_views


# --- 5. the duplicate-meal guard is unchanged ---------------------------------------------------------


def test_5_a_duplicate_repeat_is_refused_and_writes_nothing(capsys: pytest.CaptureFixture[str], database: Path) -> None:
    _source(capsys)
    _repeat(capsys)
    rows = _tables(database)
    views = _views(capsys, NEW, TODAY)

    for argv in ((), ("--date", SOURCE_DAY)):
        code, out, err = _run(capsys, "nutrition", "repeat", SOURCE, *argv)
        assert (code, out) == (1, "")
        assert "pass --additional to record another one. Nothing was changed." in err

    assert f"breakfast on {TODAY} is already recorded ({NEW})" in _run(capsys, "nutrition", "repeat", SOURCE)[2]
    assert _tables(database) == rows
    assert _views(capsys, NEW, TODAY) == views

    out = _repeat(capsys, "--additional")

    assert out.splitlines()[0] == f"Recorded meal {TODAY}-breakfast-2 (repeated from {SOURCE})."
    assert [meal["meal_id"] for meal in _json(capsys, "nutrition", "day")["meals"]] == [NEW, f"{TODAY}-breakfast-2"]


# --- 6. date / time / meal overrides --------------------------------------------------------------------


def test_6_date_time_and_meal_type_can_be_overridden(capsys: pytest.CaptureFixture[str]) -> None:
    _source(capsys)

    out = _repeat(capsys, "--date", "2026-10-05", "--time", "12:15", "--meal", "lunch")

    assert out.splitlines()[0] == f"Recorded meal 2026-10-05-lunch-1 (repeated from {SOURCE})."
    assert "[lunch] 2026-10-05-lunch-1 (2026-10-05 12:15)" in out
    new = _show(capsys, "2026-10-05-lunch-1")
    assert (new["meal_type"], new["eaten_at"], new["time_recorded"]) == ("lunch", "2026-10-05T12:15:00+09:00", True)
    assert new["original_text"] == f"repeated from {SOURCE}; structured entry lunch 2026-10-05 12:15: {ENTRY_TEXT}"
    # A different meal type is not a duplicate of the source's breakfast on its own date. Without
    # --time the dinner is stored at 00:00, so it is listed before the 07:30 breakfast.
    _repeat(capsys, "--date", SOURCE_DAY, "--meal", "dinner")
    assert [meal["meal_id"] for meal in _json(capsys, "nutrition", "day", "--date", SOURCE_DAY)["meals"]] == [
        "2026-10-02-dinner-1",
        SOURCE,
    ]


@pytest.mark.parametrize(
    ("argv", "message"),
    [
        (("--time", "25:00"), "--time must be HH:MM"),
        (("--date", "2026-13-01"), "--date"),
    ],
)
def test_6_bad_overrides_are_refused_before_anything_is_written(
    capsys: pytest.CaptureFixture[str], database: Path, argv: tuple[str, ...], message: str
) -> None:
    _source(capsys)
    rows = _tables(database)

    code, out, err = _run(capsys, "nutrition", "repeat", SOURCE, *argv)

    assert (code, out) == (1, "")
    assert message in err
    assert _tables(database) == rows


def test_6_bad_arguments_are_argparse_errors(capsys: pytest.CaptureFixture[str], database: Path) -> None:
    _source(capsys)
    rows = _tables(database)
    for argv in ((), (SOURCE, "--meal", "brunch"), (SOURCE, "--item", "banana-medium", "1", "count")):
        with pytest.raises(SystemExit) as raised:
            main(["nutrition", "repeat", *argv])
        assert raised.value.code == 2
    capsys.readouterr()
    assert _tables(database) == rows


# --- 7. an unusable source is refused atomically ----------------------------------------------------


def _save_source(database: Path, *items: MealItem) -> None:
    """A meal written below the CLI (as a future parser could): items without a catalog food or amount."""
    SqliteMealRepository(database).save(
        Meal(
            meal_id="2026-10-01-other-1",
            eaten_at=datetime(2026, 10, 1, 12, 0, tzinfo=KST),
            meal_type=MealType.OTHER,
            original_text="synthetic parser entry",
            items=items,
        )
    )


@pytest.mark.parametrize(
    ("second_item", "message"),
    [
        (
            MealItem("2026-10-01-other-1", 2, "수제 샐러드", Decimal("1"), QuantityUnit.SERVING),
            "item 2 of meal 2026-10-01-other-1 (수제 샐러드) has no catalog food and quantity to repeat.",
        ),
        (
            MealItem("2026-10-01-other-1", 2, "바나나", None, None, food_profile_id="banana-medium"),
            "item 2 of meal 2026-10-01-other-1 (바나나) has no catalog food and quantity to repeat.",
        ),
    ],
)
def test_7_a_source_item_without_food_or_quantity_refuses_the_whole_repeat(
    capsys: pytest.CaptureFixture[str], database: Path, second_item: MealItem, message: str
) -> None:
    _source(capsys)
    # Item 1 alone would be repeatable; item 2 is not, so nothing at all may be written.
    first = MealItem("2026-10-01-other-1", 1, "닭가슴살", Decimal("100"), QuantityUnit.GRAM, "chicken-breast")
    _save_source(database, first, second_item)
    rows = _tables(database)

    code, out, err = _run(capsys, "nutrition", "repeat", "2026-10-01-other-1")

    assert (code, out) == (1, "")
    assert message in err
    assert err.rstrip().endswith("Nothing was changed.")
    assert _tables(database) == rows


def test_7_an_unknown_source_meal_is_refused(capsys: pytest.CaptureFixture[str], database: Path) -> None:
    _source(capsys)
    rows = _tables(database)

    code, out, err = _run(capsys, "nutrition", "repeat", "2026-10-02-lunch-1")

    assert (code, out) == (1, "")
    assert "no meal with id '2026-10-02-lunch-1'" in err
    assert "Nothing was changed." in err
    assert _tables(database) == rows


# --- 8. a storage failure rolls everything back ------------------------------------------------------


@pytest.mark.parametrize(
    "trigger",
    [
        # The last item's facts fail after the meal, two items and their facts were inserted.
        "CREATE TRIGGER fail_step BEFORE INSERT ON nutrition_facts WHEN NEW.fact_id LIKE '2026-10-03-breakfast-1:3:%' "
        "BEGIN SELECT RAISE(ABORT, 'synthetic storage failure'); END",
        # The second item row fails after the meal row and the first item were inserted.
        "CREATE TRIGGER fail_step BEFORE INSERT ON nutrition_meal_items WHEN NEW.item_sequence = 2 "
        "BEGIN SELECT RAISE(ABORT, 'synthetic storage failure'); END",
    ],
)
def test_8_a_storage_failure_while_repeating_writes_nothing(
    capsys: pytest.CaptureFixture[str], database: Path, trigger: str
) -> None:
    _source(capsys)
    rows = _tables(database)
    source_views = _views(capsys, SOURCE, SOURCE_DAY)
    _execute(database, trigger)

    with pytest.raises(sqlite3.IntegrityError, match="synthetic storage failure"):
        RepeatMeal(SqliteMealRepository(database), SqliteFoodNutritionRepository(database)).execute(
            SOURCE, date(2026, 10, 3), timezone=KST
        )

    _execute(database, "DROP TRIGGER fail_step")
    assert _tables(database) == rows
    assert _views(capsys, SOURCE, SOURCE_DAY) == source_views
    assert _json(capsys, "nutrition", "day")["meals"] == []


# --- 9. day / status / recommend pick the repeated meal up; the training plan does not change ------


def _bench(database: Path, source_id: str, day: str) -> None:
    sets = tuple(strength_set(index, reps=10, weight_kg=50.0) for index in range(1, 4))
    item: NormalizedActivity = activity(source_id, f"{day}T12:00:00", ActivityType.STRENGTH, strength_sets=sets)
    artifact = RawArtifact("activity", f"raw/{source_id}/activity.json", "application/json", "0" * 64, 2)
    ActivityRepository(database).save(item, (artifact,))


def _training_only(document: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in document.items() if key != "nutrition"}


def test_9_the_repeated_meal_counts_in_day_status_and_recommend_but_not_in_the_training_plan(
    capsys: pytest.CaptureFixture[str], database: Path
) -> None:
    ActivityRepository(database).migrate()
    _bench(database, "9001", "2026-09-27")
    _bench(database, "9002", "2026-09-30")
    _source(capsys)
    _ok(capsys, "nutrition", "target", "set", "kcal", "--exact", "2400")
    _ok(capsys, "nutrition", "target", "set", "protein", "--range", "150", "170")
    _ok(capsys, "nutrition", "target", "set", "carbs", "--exact", "300")
    before = _json(capsys, "recommend", "--date", TODAY)
    assert before["nutrition"]["availability"] == "no_intake_logged"
    source_day = _views(capsys, SOURCE, SOURCE_DAY)

    _repeat(capsys)

    day = _json(capsys, "nutrition", "day")
    assert day["total"]["item_count"] == 3
    assert day["total"]["totals"]["calories_kcal"] == "605"
    status = _json(capsys, "nutrition", "status")["nutrients"]
    assert (status["calories_kcal"]["consumed"], status["calories_kcal"]["remaining"]) == ("605", "1795")
    assert status["protein_g"]["consumed"] == "46"
    assert (status["carbohydrate_g"]["consumed"], status["carbohydrate_g"]["remaining"]) == ("93", "207")
    after = _json(capsys, "recommend", "--date", TODAY)
    assert after["nutrition"]["availability"] == "evaluated"
    assert after["nutrition"]["nutrients"]["calories_kcal"]["consumed"] == "605"
    assert (after["nutrition"]["meal_count"], after["nutrition"]["item_count"]) == (1, 3)
    assert _training_only(after) == _training_only(before)
    text = _ok(capsys, "recommend", "--date", TODAY)
    assert "  kcal          605; target 2400 (exact): below target, 1795 to go" in text
    # The source day is untouched.
    assert _views(capsys, SOURCE, SOURCE_DAY) == source_day


# --- 10. deterministic text and JSON --------------------------------------------------------------------


def test_10_text_and_json_are_deterministic_and_json_is_the_log_document(capsys: pytest.CaptureFixture[str]) -> None:
    _source(capsys)
    log_json = _show(capsys, SOURCE)

    printed = _repeat(capsys, "--json")

    document = json.loads(printed)
    assert printed == json.dumps(document, indent=2) + "\n"
    # Same document as `nutrition log --json` / `meal show --json`, no extra keys.
    assert list(document) == list(log_json)
    assert [list(item) for item in document["items"]] == [list(item) for item in log_json["items"]]
    assert printed == _ok(capsys, "nutrition", "meal", "show", NEW, "--json")
    assert document == _json(capsys, "nutrition", "day")["meals"][0]
    assert _views(capsys, NEW, TODAY) == _views(capsys, NEW, TODAY)

    text = _repeat(capsys, "--date", "2026-10-04")
    assert text == _repeat(capsys, "--date", "2026-10-05").replace("2026-10-05", "2026-10-04")
    for name in ("닭가슴살", "햇반", "바나나"):
        text = text.replace(name, "")
    assert text.isascii()


# --- 11. `nutrition log` itself does not change ------------------------------------------------------------


def test_11_nutrition_log_output_and_stored_meal_are_unchanged(
    capsys: pytest.CaptureFixture[str], database: Path
) -> None:
    out = _source(capsys)

    assert out.splitlines() == [
        f"Recorded meal {SOURCE}.",
        "",
        f"[breakfast] {SOURCE} ({SOURCE_DAY} 07:30)",
        *NEW_MEAL_LINES[1:],
        "",
        f"Whole day: muscle50 nutrition day --date {SOURCE_DAY}",
    ]
    (meal_row,) = _rows_of(database, SOURCE)["meal"]
    # meal_id, eaten_at, utc sort key, type, original_text, parser_version, model_version, notes
    assert meal_row[3:] == (
        "breakfast",
        f"structured entry breakfast {SOURCE_DAY} 07:30: {ENTRY_TEXT}",
        None,
        None,
        None,
    )
    logged = _ok(capsys, "nutrition", "log", "--meal", "lunch", "--item", "banana-medium", "1", "count", "--json")
    document = json.loads(logged)
    assert document["original_text"] == f"structured entry lunch {TODAY}: banana-medium 1 count"
    assert logged == _ok(capsys, "nutrition", "meal", "show", f"{TODAY}-lunch-1", "--json")
    assert "repeated from" not in json.dumps(_tables(database)["nutrition_meals"])
