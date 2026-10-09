"""Nutrition General Meal v1: `--general [--general-note TEXT]` records a meal whose menu and numbers are unknown.

Runs over a temporary MUSCLE50_HOME / temporary SQLite database only, with synthetic foods and values.
The central guarantees: a general item has no quantity, unit or facts, so every total it is part of is
incomplete and never 0; it points to the reserved `general-meal` profile, which is created in the same
transaction as the item and is not a catalog food; and nothing changes for meals without one.
"""

from __future__ import annotations

import json
import re
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
    GeneralMealEntry,
    LogMeal,
    MealEntryItem,
)
from muscle50.cli import main
from muscle50.domain.activity import ActivityType
from muscle50.domain.nutrition import (
    GENERAL_MEAL_FOOD_ID,
    GENERAL_MEAL_NAME,
    Accuracy,
    FoodNutritionProfile,
    Meal,
    MealItem,
    MealType,
    NutritionFact,
    NutritionProvenance,
    NutritionSourceType,
    NutritionValue,
    QuantityUnit,
    is_reserved_food_reference,
    normalize_general_meal_note,
)
from muscle50.infrastructure.garmin.client import PythonGarminConnector
from muscle50.infrastructure.raw_store import RawArtifact
from muscle50.infrastructure.sqlite.database import ActivityRepository
from muscle50.infrastructure.sqlite.nutrition_repository import SqliteFoodNutritionRepository, SqliteMealRepository

KST = timezone(timedelta(hours=9))
DAY = "2026-10-08"
NOW = datetime(2026, 10, 8, 21, 0, tzinfo=KST)
LUNCH = "2026-10-08-lunch-1"
DINNER = "2026-10-08-dinner-1"

CHICKEN = (
    ["--id", "chicken-breast", "--name", "닭가슴살", "--per", "100", "g"]
    + ["--kcal", "110", "--protein", "23", "--carbs", "0", "--fat", "1.5"]
    + ["--source", "nutrition_label", "--accuracy", "exact"]
)
CHICKEN_ITEM = ("--item", "chicken-breast", "100", "g")
UNKNOWN_TOTALS = " | ".join(f"{label} incomplete (no item has a value)" for label in ("kcal", "P", "C", "F"))
ALL_MISSING = ["calories_kcal", "protein_g", "carbohydrate_g", "fat_g"]
LEGACY_ITEM_KEYS = ["sequence", "food_id", "food_name", "quantity", "unit", "nutrients", "missing_fields", "facts"]
E3 = "is the general meal, not a catalog food; record it with --general (no quantity or unit). Nothing was changed."
E2 = (
    "'general-meal' is the general meal (일반식), not a catalog food: it has no nutrition facts and none can be "
    "added. Nothing was changed."
)
E6 = (
    "food 'general-meal' in the catalog is not the general meal (it has nutrition facts, aliases or another name); "
    "general meals cannot be recorded. Nothing was changed."
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
    monkeypatch.setattr(cli, "_today", lambda: date(2026, 10, 8))
    monkeypatch.setattr(cli, "_now", lambda: NOW)
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


def _refused(capsys: pytest.CaptureFixture[str], *argv: str) -> str:
    """Exit 1 with nothing on stdout; returns the error text after `오류: `."""
    code, out, err = _run(capsys, *argv)
    assert (code, out) == (1, ""), err
    assert err.startswith("오류: ") and err.endswith("\n")
    return err.removeprefix("오류: ").removesuffix("\n")


def _usage_error(capsys: pytest.CaptureFixture[str], *argv: str) -> str:
    with pytest.raises(SystemExit) as raised:
        main(list(argv))
    assert raised.value.code == 2
    return capsys.readouterr().err


def _chicken(capsys: pytest.CaptureFixture[str]) -> None:
    _ok(capsys, "nutrition", "food", "add", *CHICKEN)


def _log(capsys: pytest.CaptureFixture[str], meal: str, *entries: str, day: str = DAY) -> str:
    return _ok(capsys, "nutrition", "log", "--date", day, "--meal", meal, *entries)


def _tables(database: Path) -> dict[str, list[tuple[Any, ...]]]:
    connection = sqlite3.connect(database)
    try:
        names = [
            row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name")
        ]
        return {name: sorted(connection.execute(f"SELECT * FROM {name}").fetchall(), key=repr) for name in names}
    finally:
        connection.close()


def _rows(database: Path, table: str) -> list[tuple[Any, ...]]:
    return _tables(database)[table]


def _execute(database: Path, statement: str) -> None:
    connection = sqlite3.connect(database)
    try:
        connection.execute(statement)
        connection.commit()
    finally:
        connection.close()


def _values(document: Any) -> list[Any]:
    """Every scalar in a JSON document."""
    if isinstance(document, dict):
        return [value for item in document.values() for value in _values(item)]
    if isinstance(document, list):
        return [value for item in document for value in _values(item)]
    return [document]


def _general_item(sequence: int, note: str | None) -> dict[str, Any]:
    return {
        "sequence": sequence,
        "food_id": "general-meal",
        "food_name": "일반식",
        "quantity": None,
        "unit": None,
        "nutrients": {"calories_kcal": None, "protein_g": None, "carbohydrate_g": None, "fat_g": None},
        "missing_fields": ALL_MISSING,
        "facts": [],
        "general_meal": True,
        "note": note,
    }


# --- domain ------------------------------------------------------------------------------------------


def test_is_general_requires_the_reserved_profile_and_no_amount_or_facts() -> None:
    general = MealItem("m", 1, GENERAL_MEAL_NAME, None, None, food_profile_id=GENERAL_MEAL_FOOD_ID)
    assert general.is_general
    assert MealItem("m", 1, GENERAL_MEAL_NAME, None, None, serving_description="x").is_general is False
    assert MealItem("m", 1, "바나나", None, None, food_profile_id="banana-medium").is_general is False
    with_amount = MealItem("m", 1, GENERAL_MEAL_NAME, Decimal(1), QuantityUnit.SERVING, GENERAL_MEAL_FOOD_ID)
    assert with_amount.is_general is False
    fact = _fact("m:1:x", QuantityUnit.SERVING)
    with_fact = MealItem("m", 1, GENERAL_MEAL_NAME, None, None, GENERAL_MEAL_FOOD_ID, nutrition_facts=(fact,))
    assert with_fact.is_general is False
    assert general.calculated_nutrition() is None


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (None, None),
        ("", None),
        ("   ", None),
        ("  구내식당 ", "구내식당"),
        ("제육  볶음", "제육  볶음"),
        ("x" * 100, "x" * 100),
    ],
)
def test_note_is_stripped_and_empty_means_none(text: str | None, expected: str | None) -> None:
    assert normalize_general_meal_note(text) == expected


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("x" * 101, "must be at most 100 characters (got 101)"),
        (" " + "가" * 120 + " ", "must be at most 100 characters (got 120)"),
        ("a\nb", "must be a single line of text"),
        ("a\tb", "must be a single line of text"),
        ("a\x00b", "must be a single line of text"),
    ],
)
def test_note_limits(text: str, message: str) -> None:
    with pytest.raises(ValueError, match=f"^{re.escape(message)}$"):
        normalize_general_meal_note(text)


@pytest.mark.parametrize(
    ("text", "reserved"),
    [
        ("일반식", True),
        (" 일반식 ", True),
        ("general-meal", True),
        ("GENERAL-MEAL", True),
        ("General-Meal ", True),
        ("일반", False),
        ("일반식 도시락", False),
        ("general", False),
        ("general_meal", False),
    ],
)
def test_reserved_food_references(text: str, reserved: bool) -> None:
    assert is_reserved_food_reference(text) is reserved


# --- AC1: log --general --------------------------------------------------------------------------------


def test_ac1_log_general_prints_unknown_nutrition_and_stores_one_general_item(
    capsys: pytest.CaptureFixture[str], database: Path
) -> None:
    out = _log(capsys, "lunch", "--general")

    assert out.split("\n") == [
        f"Recorded meal {LUNCH}.",
        "",
        f"[lunch] {LUNCH} (2026-10-08, time not recorded)",
        "  1. 일반식 (general meal): nutrition unknown",
        "     source: no nutrition facts",
        "     missing: kcal, protein, carbohydrate, fat",
        f"  Meal total: {UNKNOWN_TOTALS}",
        "",
        f"Whole day: muscle50 nutrition day --date {DAY}",
        "",
    ]
    tables = _tables(database)
    assert tables["nutrition_meal_items"] == [(LUNCH, 1, "일반식", "general-meal", None, None, None)]
    assert tables["nutrition_facts"] == []
    assert tables["nutrition_food_profiles"] == [("general-meal", "일반식")]
    assert tables["nutrition_food_profile_aliases"] == []
    assert tables["nutrition_meals"][0][4] == f"structured entry lunch {DAY}: general meal"


def test_ac1_json_is_the_meal_document_with_two_keys_appended_to_the_general_item(
    capsys: pytest.CaptureFixture[str],
) -> None:
    printed = _ok(capsys, "nutrition", "log", "--date", DAY, "--meal", "lunch", "--general", "--json")
    document = json.loads(printed)

    assert printed == json.dumps(document, indent=2) + "\n"
    assert list(document) == ["meal_id", "meal_type", "eaten_at", "time_recorded", "original_text", "items", "total"]
    assert document["items"] == [_general_item(1, None)]
    assert list(document["items"][0]) == [*LEGACY_ITEM_KEYS, "general_meal", "note"]
    assert document["total"] == {
        "complete": False,
        "item_count": 1,
        "totals": dict.fromkeys(ALL_MISSING),
        "known_subtotals": dict.fromkeys(ALL_MISSING),
        "incomplete_fields": ALL_MISSING,
        "estimated_fields": [],
        "estimate_range": None,
        "uncalculated_items": [{"meal_id": LUNCH, "sequence": 1}],
    }
    # Deterministic, and `meal show --json` is the same document.
    assert _ok(capsys, "nutrition", "meal", "show", LUNCH, "--json") == printed
    assert _ok(capsys, "nutrition", "meal", "show", LUNCH, "--json") == printed


def test_text_is_ascii_apart_from_the_label_and_the_memo(capsys: pytest.CaptureFixture[str]) -> None:
    _chicken(capsys)
    out = _log(capsys, "dinner", "--general", "--general-note", "구내식당", *CHICKEN_ITEM)
    shown = _ok(capsys, "nutrition", "meal", "show", DINNER)
    day = _ok(capsys, "nutrition", "day", "--date", DAY)
    for text in (out, shown, day):
        assert text.replace("일반식", "").replace("구내식당", "").replace("닭가슴살", "").isascii()


# --- AC3: mixed with a catalog food ----------------------------------------------------------------------


def test_ac3_mixed_meal_keeps_known_values_as_a_lower_bound(capsys: pytest.CaptureFixture[str]) -> None:
    _chicken(capsys)
    out = _log(capsys, "dinner", "--general", "--general-note", "구내식당", *CHICKEN_ITEM)

    assert out.split("\n") == [
        f"Recorded meal {DINNER}.",
        "",
        f"[dinner] {DINNER} (2026-10-08, time not recorded)",
        "  1. 일반식 (general meal; note: 구내식당): nutrition unknown",
        "     source: no nutrition facts",
        "     missing: kcal, protein, carbohydrate, fat",
        "  2. 닭가슴살 (chicken-breast) 100 g: kcal 110 | P 23 g | C 0 g | F 1.5 g",
        "     source: nutrition_label/exact",
        "  Meal total: kcal incomplete (known items only: 110) | P incomplete (known items only: 23 g) | "
        "C incomplete (known items only: 0 g) | F incomplete (known items only: 1.5 g)",
        "",
        f"Whole day: muscle50 nutrition day --date {DAY}",
        "",
    ]
    total = _json(capsys, "nutrition", "meal", "show", DINNER)["total"]
    assert total["totals"] == dict.fromkeys(ALL_MISSING)
    assert total["known_subtotals"] == {
        "calories_kcal": "110",
        "protein_g": "23",
        "carbohydrate_g": "0",
        "fat_g": "1.5",
    }
    assert (total["complete"], total["incomplete_fields"]) == (False, ALL_MISSING)
    assert total["uncalculated_items"] == [{"meal_id": DINNER, "sequence": 1}]
    status = _json(capsys, "nutrition", "status", "--date", DAY)
    for nutrient in ALL_MISSING:
        entry = status["nutrients"][nutrient]
        assert (entry["complete"], entry["consumed"]) == (False, None)
        assert entry["missing_items"] == [
            {"meal_id": DINNER, "sequence": 1, "food_id": "general-meal", "food_name": "일반식"}
        ]
    assert status["nutrients"]["protein_g"]["known_subtotal"] == "23"


# --- AC2: a day with only general meals --------------------------------------------------------------------


def test_ac2_general_only_day_is_incomplete_everywhere_and_never_zero(capsys: pytest.CaptureFixture[str]) -> None:
    _ok(capsys, "nutrition", "target", "set", "kcal", "--range", "2200", "2500")
    _ok(capsys, "nutrition", "target", "set", "protein", "--exact", "120")
    _log(capsys, "lunch", "--general", "--general-note", "구내식당")
    _log(capsys, "dinner", "--general")

    day_text = _ok(capsys, "nutrition", "day", "--date", DAY).split("\n")
    assert day_text[day_text.index("Consumed (2 meals, 2 items):") + 1 :][:4] == [
        "  kcal          incomplete (no item has a value)",
        "  Protein       incomplete (no item has a value)",
        "  Carbohydrate  incomplete (no item has a value)",
        "  Fat           incomplete (no item has a value)",
    ]
    assert f"  kcal: {LUNCH} item 1 일반식 (general-meal); {DINNER} item 1 일반식 (general-meal)" in day_text
    status_text = _ok(capsys, "nutrition", "status", "--date", DAY).split("\n")
    assert status_text[3:8] == [
        "Logged: 2 meals, 2 items",
        "  kcal          incomplete (no item has a value); target 2200-2500 (range): "
        "cannot tell yet (incomplete); remaining unknown",
        "  Protein       incomplete (no item has a value); target 120 g (exact): "
        "cannot tell yet (incomplete); remaining unknown",
        "  Carbohydrate  incomplete (no item has a value); no target",
        "  Fat           incomplete (no item has a value); no target",
    ]

    day = _json(capsys, "nutrition", "day", "--date", DAY)
    assert day["total"]["totals"] == dict.fromkeys(ALL_MISSING)
    assert day["total"]["known_subtotals"] == dict.fromkeys(ALL_MISSING)
    assert day["total"]["complete"] is False
    status = _json(capsys, "nutrition", "status", "--date", DAY)
    for nutrient in ("calories_kcal", "protein_g"):
        entry = status["nutrients"][nutrient]
        assert (entry["status"], entry["complete"], entry["consumed"], entry["remaining"]) == (
            "indeterminate",
            False,
            None,
            None,
        )
    # Missing is not zero: no value anywhere in the documents is a zero amount.
    for document in (day, status):
        assert "0" not in [value for value in _values(document) if isinstance(value, str)]


def _bench(database: Path, source_id: str, day: str) -> None:
    sets = tuple(strength_set(index, reps=10, weight_kg=50.0) for index in range(1, 4))
    item = activity(source_id, f"{day}T12:00:00", ActivityType.STRENGTH, strength_sets=sets)
    artifact = RawArtifact("activity", f"raw/{source_id}/activity.json", "application/json", "0" * 64, 2)
    ActivityRepository(database).save(item, (artifact,))


def test_ac2_recommend_gives_no_nutrition_action_once_a_general_meal_is_logged(
    capsys: pytest.CaptureFixture[str], database: Path
) -> None:
    ActivityRepository(database).migrate()
    _bench(database, "9001", "2026-10-02")
    _bench(database, "9002", "2026-10-05")
    _chicken(capsys)
    _ok(capsys, "nutrition", "target", "set", "kcal", "--range", "2200", "2500")
    _ok(capsys, "nutrition", "target", "set", "protein", "--exact", "120")
    _log(capsys, "lunch", *CHICKEN_ITEM)
    # Control: the catalog meal alone is far below both targets, so there are actions.
    assert _json(capsys, "recommend", "--date", DAY)["nutrition"]["actions"] != []

    _ok(capsys, "nutrition", "meal", "add-item", LUNCH, "--general")
    before = _tables(database)
    recommendation = _json(capsys, "recommend", "--date", DAY)

    nutrition = recommendation["nutrition"]
    assert nutrition["actions"] == []
    assert nutrition["availability"] != "no_intake_logged"
    assert nutrition["nutrients"]["protein_g"]["status"] == "indeterminate"
    assert nutrition["nutrients"]["protein_g"]["known_subtotal"] == "23"
    # The reader is read-only: recommend writes nothing (no profile row, nothing else).
    assert _tables(database) == before


# --- AC4: the memo --------------------------------------------------------------------------------------


def test_ac4_note_is_stripped_stored_shown_and_does_not_change_totals(
    capsys: pytest.CaptureFixture[str], database: Path
) -> None:
    _log(capsys, "lunch", "--general", "--general-note", "  구내식당  ")
    _log(capsys, "dinner", "--general", "--general-note", "   ")

    items = _rows(database, "nutrition_meal_items")
    assert items == [
        (DINNER, 1, "일반식", "general-meal", None, None, None),
        (LUNCH, 1, "일반식", "general-meal", None, None, "구내식당"),
    ]
    shown = _ok(capsys, "nutrition", "meal", "show", LUNCH).split("\n")
    assert shown[:5] == [
        f"[lunch] {LUNCH} (2026-10-08, time not recorded)",
        "  1. 일반식 (general meal; note: 구내식당): nutrition unknown",
        "     source: no nutrition facts",
        "     facts: none selected",
        "     missing: kcal, protein, carbohydrate, fat",
    ]
    with_note = _json(capsys, "nutrition", "meal", "show", LUNCH)
    without_note = _json(capsys, "nutrition", "meal", "show", DINNER)
    assert with_note["items"] == [_general_item(1, "구내식당")]
    assert without_note["items"] == [_general_item(1, None)]
    assert with_note["original_text"] == f"structured entry lunch {DAY}: general meal (note: 구내식당)"
    assert {**with_note["total"], "uncalculated_items": []} == {**without_note["total"], "uncalculated_items": []}


@pytest.mark.parametrize(
    ("entries", "message"),
    [
        (("--general", "--general-note", "x" * 101), "item 1: --general-note must be at most 100 characters (got 101)"),
        (("--general", "--general-note", "a\nb"), "item 1: --general-note must be a single line of text"),
        (("--general", "--general-note", "a\tb"), "item 1: --general-note must be a single line of text"),
        (
            (*CHICKEN_ITEM, "--general", "--general-note", "가" * 101),
            "item 2: --general-note must be at most 100 characters (got 101)",
        ),
    ],
)
def test_ac4_bad_notes_are_refused_and_nothing_is_written(
    capsys: pytest.CaptureFixture[str], database: Path, entries: tuple[str, ...], message: str
) -> None:
    _chicken(capsys)
    _log(capsys, "breakfast", "--general")
    rows = _tables(database)

    error = _refused(capsys, "nutrition", "log", "--date", DAY, "--meal", "lunch", *entries)
    assert error == f"{message}. Nothing was changed."
    assert _refused(capsys, "nutrition", "meal", "add-item", f"{DAY}-breakfast-1", *entries) == error
    assert _tables(database) == rows


def test_ac4_bad_note_on_replace_item_is_refused(capsys: pytest.CaptureFixture[str], database: Path) -> None:
    _log(capsys, "lunch", "--general")
    rows = _tables(database)
    error = _refused(
        capsys, "nutrition", "meal", "replace-item", LUNCH, "--item-number", "1", "--general", "--general-note", "a\nb"
    )
    assert error == "--general-note must be a single line of text. Nothing was changed."
    assert _tables(database) == rows


# --- entry order and argparse errors --------------------------------------------------------------------


def test_items_keep_the_command_line_order_of_item_and_general(
    capsys: pytest.CaptureFixture[str], database: Path
) -> None:
    _chicken(capsys)
    _log(
        capsys, "lunch", *CHICKEN_ITEM, "--general", "--general-note", "x", "--general", "--item", "닭가슴살", "50", "g"
    )

    document = _json(capsys, "nutrition", "meal", "show", LUNCH)
    assert [(item["sequence"], item["food_id"], item.get("note", "-")) for item in document["items"]] == [
        (1, "chicken-breast", "-"),
        (2, "general-meal", "x"),
        (3, "general-meal", None),
        (4, "chicken-breast", "-"),
    ]
    assert document["original_text"] == (
        f"structured entry lunch {DAY}: chicken-breast 100 g; general meal (note: x); general meal; chicken-breast 50 g"
    )
    assert document["total"]["known_subtotals"]["calories_kcal"] == "165"
    assert document["total"]["totals"]["calories_kcal"] is None


NOTE_ORDER = "argument --general-note: must directly follow the --general it describes"
NO_ENTRY = "one of the arguments --item --general is required"


@pytest.mark.parametrize(
    ("argv", "message"),
    [
        (("log", "--meal", "lunch", "--general-note", "x", "--general"), NOTE_ORDER),
        (("log", "--meal", "lunch", "--general", "--general-note", "a", "--general-note", "b"), NOTE_ORDER),
        (("log", "--meal", "lunch", *CHICKEN_ITEM, "--general-note", "a"), NOTE_ORDER),
        (("log", "--meal", "lunch"), NO_ENTRY),
        (("log", "--meal", "lunch", "--general", "구내식당"), "unrecognized arguments: 구내식당"),
        (("meal", "add-item", LUNCH), NO_ENTRY),
        (("meal", "add-item", LUNCH, "--general-note", "x"), NOTE_ORDER),
        (("meal", "replace-item", LUNCH, "--item-number", "1"), NO_ENTRY),
        (
            ("meal", "replace-item", LUNCH, "--item-number", "1", "--general", *CHICKEN_ITEM),
            "argument --item: not allowed with argument --general",
        ),
        (
            ("meal", "replace-item", LUNCH, "--item-number", "1", *CHICKEN_ITEM, "--general-note", "x"),
            "argument --general-note: requires --general",
        ),
    ],
)
def test_malformed_entries_are_argparse_errors_and_write_nothing(
    capsys: pytest.CaptureFixture[str], database: Path, argv: tuple[str, ...], message: str
) -> None:
    _chicken(capsys)
    _log(capsys, "lunch", *CHICKEN_ITEM)
    rows = _tables(database)

    err = _usage_error(capsys, "nutrition", *argv)

    assert err.rstrip("\n").endswith(f"error: {message}")
    if not message.startswith("unrecognized"):  # argparse reports unknown extras at the top level
        assert f"usage: muscle50 nutrition {argv[0]}" in err
    assert _tables(database) == rows


def test_a_usage_error_runs_nothing_not_even_the_migration(capsys: pytest.CaptureFixture[str], home: Path) -> None:
    _usage_error(capsys, "nutrition", "log", "--meal", "lunch")
    _usage_error(capsys, "nutrition", "meal", "replace-item", LUNCH, "--item-number", "1", "--general-note", "x")
    assert not home.exists()


# --- AC5: corrections work on general items ---------------------------------------------------------------


def test_ac5_add_remove_and_replace_items(capsys: pytest.CaptureFixture[str], database: Path) -> None:
    _chicken(capsys)
    _log(capsys, "lunch", *CHICKEN_ITEM)

    added = _ok(capsys, "nutrition", "meal", "add-item", LUNCH, "--general", "--general", "--general-note", "배달")
    assert added.split("\n")[0] == f"Added items 2, 3 to meal {LUNCH}."
    assert "  2. 일반식 (general meal): nutrition unknown" in added
    assert "  3. 일반식 (general meal; note: 배달): nutrition unknown" in added

    removed = _ok(capsys, "nutrition", "meal", "remove-item", LUNCH, "--item-number", "2")
    assert removed.split("\n")[0] == f"Removed item 2 from meal {LUNCH}."

    # general -> catalog, then catalog -> general with a memo.
    replaced = _ok(capsys, "nutrition", "meal", "replace-item", LUNCH, "--item-number", "3", *CHICKEN_ITEM)
    assert replaced.split("\n")[0] == f"Replaced item 3 of meal {LUNCH} with item 4."
    replaced = _ok(
        capsys, "nutrition", "meal", "replace-item", LUNCH, "--item-number", "1", "--general", "--general-note", "제육"
    )
    assert replaced.split("\n")[0] == f"Replaced item 1 of meal {LUNCH} with item 5."

    document = _json(capsys, "nutrition", "meal", "show", LUNCH)
    assert [(item["sequence"], item["food_id"]) for item in document["items"]] == [
        (4, "chicken-breast"),
        (5, "general-meal"),
    ]
    assert document["items"][1] == _general_item(5, "제육")
    assert document["total"]["known_subtotals"]["protein_g"] == "23"
    assert document["total"]["totals"]["protein_g"] is None
    # Item rows are only ever inserted; the general items stay stored for audit.
    assert [row[:4] for row in _rows(database, "nutrition_meal_items")] == [
        (LUNCH, 1, "닭가슴살", "chicken-breast"),
        (LUNCH, 2, "일반식", "general-meal"),
        (LUNCH, 3, "일반식", "general-meal"),
        (LUNCH, 4, "닭가슴살", "chicken-breast"),
        (LUNCH, 5, "일반식", "general-meal"),
    ]
    assert _rows(database, "nutrition_food_profiles") == [("chicken-breast", "닭가슴살"), ("general-meal", "일반식")]


def test_ac5_the_only_general_item_cannot_be_removed(capsys: pytest.CaptureFixture[str], database: Path) -> None:
    _log(capsys, "lunch", "--general")
    rows = _tables(database)
    error = _refused(capsys, "nutrition", "meal", "remove-item", LUNCH, "--item-number", "1")
    assert error.startswith(f"item 1 is the only item of meal {LUNCH}; a meal cannot be left empty.")
    assert _tables(database) == rows


def test_ac5_void_and_edit(capsys: pytest.CaptureFixture[str]) -> None:
    _log(capsys, "lunch", "--general", "--general-note", "구내식당")

    edited = _ok(capsys, "nutrition", "meal", "edit", LUNCH, "--time", "12:30")
    assert edited.split("\n")[0] == f"Edited meal {LUNCH}: time not recorded -> 12:30. The meal ID does not change."
    assert "  1. 일반식 (general meal; note: 구내식당): nutrition unknown" in edited

    voided = _ok(capsys, "nutrition", "meal", "void", LUNCH, "--reason", "중복")
    assert voided.split("\n")[0].startswith(f"Voided meal {LUNCH}.")
    assert _json(capsys, "nutrition", "day", "--date", DAY)["meals"] == []
    assert _json(capsys, "nutrition", "meal", "show", LUNCH)["items"] == [_general_item(1, "구내식당")]


def test_ac5_merge_copies_the_general_item_and_its_memo(capsys: pytest.CaptureFixture[str], database: Path) -> None:
    _chicken(capsys)
    _log(capsys, "lunch", *CHICKEN_ITEM)
    _ok(
        capsys,
        "nutrition",
        "log",
        "--date",
        DAY,
        "--meal",
        "lunch",
        "--general",
        "--general-note",
        "배달",
        "--additional",
    )
    day_before = _json(capsys, "nutrition", "day", "--date", DAY)["total"]

    merged = _ok(capsys, "nutrition", "meal", "merge", LUNCH, f"{DAY}-lunch-2")

    assert merged.split("\n")[0] == f"Merged meal {DAY}-lunch-2 into {LUNCH} as item 2; meal {DAY}-lunch-2 is voided."
    document = _json(capsys, "nutrition", "meal", "show", LUNCH)
    assert document["items"][1] == _general_item(2, "배달")
    day_after = _json(capsys, "nutrition", "day", "--date", DAY)
    assert [meal["meal_id"] for meal in day_after["meals"]] == [LUNCH]
    assert {key: value for key, value in day_after["total"].items() if key != "uncalculated_items"} == {
        key: value for key, value in day_before.items() if key != "uncalculated_items"
    }
    facts = _rows(database, "nutrition_facts")
    assert [row for row in facts if row[3] == "general-meal" or str(row[0]).startswith(f"{LUNCH}:2:")] == []


def test_ac5_repeat_copies_the_general_item_and_its_memo(capsys: pytest.CaptureFixture[str]) -> None:
    _chicken(capsys)
    _log(capsys, "dinner", "--general", "--general-note", "구내식당", *CHICKEN_ITEM)

    out = _ok(capsys, "nutrition", "repeat", DINNER, "--date", "2026-10-09")

    assert out.split("\n")[:4] == [
        f"Recorded meal 2026-10-09-dinner-1 (repeated from {DINNER}).",
        "",
        "[dinner] 2026-10-09-dinner-1 (2026-10-09, time not recorded)",
        "  1. 일반식 (general meal; note: 구내식당): nutrition unknown",
    ]
    assert "Nutrition facts changed" not in out
    document = _json(capsys, "nutrition", "meal", "show", "2026-10-09-dinner-1")
    assert document["items"][0] == _general_item(1, "구내식당")
    assert document["items"][1]["food_id"] == "chicken-breast"
    assert document["original_text"] == (
        f"repeated from {DINNER}; structured entry dinner 2026-10-09: general meal (note: 구내식당); "
        "chicken-breast 100 g"
    )


# --- AC6: the reserved ID, name and alias -------------------------------------------------------------------


FOOD_FACT = ["--per", "1", "serving", "--kcal", "500", "--protein", "20", "--carbs", "60", "--fat", "15"]
FOOD_FACT += ["--source", "user_provided", "--accuracy", "exact"]
RESERVED_ID = "is reserved for the general meal (record one with nutrition log --general); nothing was changed"


@pytest.mark.parametrize("after_general_meal", [False, True], ids=["fresh", "after-general-meal"])
@pytest.mark.parametrize(
    ("identity", "message"),
    [
        (("--id", "general-meal", "--name", "일반 식사"), f"food id 'general-meal' {RESERVED_ID}"),
        (("--id", "GENERAL-MEAL", "--name", "일반 식사"), f"food id 'GENERAL-MEAL' {RESERVED_ID}"),
        (("--id", "일반식", "--name", "일반 식사"), f"food id '일반식' {RESERVED_ID}"),
        (("--id", "set-meal", "--name", "일반식"), f"name or alias '일반식' {RESERVED_ID}"),
        (("--id", "set-meal", "--name", " 일반식 "), f"name or alias '일반식' {RESERVED_ID}"),
        (("--id", "set-meal", "--name", "General-Meal"), f"name or alias 'General-Meal' {RESERVED_ID}"),
        (("--id", "set-meal", "--name", "정식", "--alias", "일반식"), f"name or alias '일반식' {RESERVED_ID}"),
    ],
)
def test_ac6_food_add_refuses_the_reserved_id_name_and_alias(
    capsys: pytest.CaptureFixture[str],
    database: Path,
    after_general_meal: bool,
    identity: tuple[str, ...],
    message: str,
) -> None:
    _chicken(capsys)
    if after_general_meal:
        _log(capsys, "lunch", "--general")
    rows = _tables(database)

    assert _refused(capsys, "nutrition", "food", "add", *identity, *FOOD_FACT) == message
    assert _tables(database) == rows


def test_ac6_the_all_unknown_refusal_still_comes_first(capsys: pytest.CaptureFixture[str], database: Path) -> None:
    _chicken(capsys)
    rows = _tables(database)
    unknown = ["--per", "1", "serving", "--kcal", "unknown", "--protein", "unknown", "--carbs", "unknown"]
    unknown += ["--fat", "unknown", "--source", "user_provided", "--accuracy", "exact"]
    for identity in (("--id", "set-meal", "--name", "정식"), ("--id", "general-meal", "--name", "일반식")):
        error = _refused(capsys, "nutrition", "food", "add", *identity, *unknown)
        assert error == "at least one of kcal/protein/carbohydrate/fat must be a number"
    assert _tables(database) == rows


@pytest.mark.parametrize("after_general_meal", [False, True], ids=["fresh", "after-general-meal"])
def test_ac6_food_show_and_fact_add_refuse_the_general_meal(
    capsys: pytest.CaptureFixture[str], database: Path, after_general_meal: bool
) -> None:
    _chicken(capsys)
    if after_general_meal:
        _log(capsys, "lunch", "--general")
    rows = _tables(database)

    assert _refused(capsys, "nutrition", "food", "show", "general-meal") == E2
    assert _refused(capsys, "nutrition", "food", "show", "general-meal", "--json") == E2
    assert _refused(capsys, "nutrition", "food", "fact", "add", "general-meal", *FOOD_FACT) == E2
    # Other references keep today's text.
    assert _refused(capsys, "nutrition", "food", "show", "일반식") == "no food with id '일반식'"
    assert _tables(database) == rows


@pytest.mark.parametrize("after_general_meal", [False, True], ids=["fresh", "after-general-meal"])
@pytest.mark.parametrize("reference", ["일반식", "general-meal", "GENERAL-MEAL", " 일반식 "])
def test_ac6_item_naming_the_general_meal_is_refused(
    capsys: pytest.CaptureFixture[str], database: Path, after_general_meal: bool, reference: str
) -> None:
    _chicken(capsys)
    _log(capsys, "breakfast", *CHICKEN_ITEM)
    if after_general_meal:
        _log(capsys, "lunch", "--general")
    rows = _tables(database)
    meal = f"{DAY}-breakfast-1"

    log = _refused(
        capsys,
        "nutrition",
        "log",
        "--date",
        DAY,
        "--meal",
        "dinner",
        *CHICKEN_ITEM,
        "--item",
        reference,
        "1",
        "serving",
    )
    assert log == f"--item 2 {reference!r} {E3}"
    add = _refused(capsys, "nutrition", "meal", "add-item", meal, "--item", reference, "1", "serving")
    assert add == f"--item 1 {reference!r} {E3}"
    replace = _refused(
        capsys, "nutrition", "meal", "replace-item", meal, "--item-number", "1", "--item", reference, "1", "serving"
    )
    assert replace == f"--item {reference!r} {E3}"
    assert _tables(database) == rows


def test_ac6_snapshot_refuses_the_general_meal_even_without_the_cli(database: Path) -> None:
    ActivityRepository(database).migrate()
    meals, foods = SqliteMealRepository(database), SqliteFoodNutritionRepository(database)
    with pytest.raises(ValueError, match=f"^{re.escape(f'item 1 {GENERAL_MEAL_FOOD_ID!r} {E3}')}$"):
        LogMeal(meals, foods).execute(
            date(2026, 10, 8),
            MealType.LUNCH,
            (MealEntryItem("general-meal", Decimal(1), QuantityUnit.SERVING),),
            timezone=KST,
        )


def test_ac6_ac7_food_list_does_not_change_after_a_general_meal(capsys: pytest.CaptureFixture[str]) -> None:
    empty = (_ok(capsys, "nutrition", "food", "list"), _ok(capsys, "nutrition", "food", "list", "--json"))
    _log(capsys, "breakfast", "--general")
    assert (_ok(capsys, "nutrition", "food", "list"), _ok(capsys, "nutrition", "food", "list", "--json")) == empty

    _chicken(capsys)
    with_chicken = (_ok(capsys, "nutrition", "food", "list"), _ok(capsys, "nutrition", "food", "list", "--json"))
    assert "general-meal" not in with_chicken[0] + with_chicken[1]
    _log(capsys, "lunch", "--general")
    assert (_ok(capsys, "nutrition", "food", "list"), _ok(capsys, "nutrition", "food", "list", "--json")) == (
        with_chicken
    )


# --- E6: a user food already holds the reserved ID ------------------------------------------------------


def _fact(fact_id: str, unit: QuantityUnit) -> NutritionFact:
    return NutritionFact(
        fact_id=fact_id,
        values=NutritionValue(calories_kcal=Decimal(500)),
        basis_quantity=Decimal(1),
        basis_unit=unit,
        provenance=NutritionProvenance(
            NutritionSourceType.USER_PROVIDED, Accuracy.EXACT, "synthetic", datetime(2026, 9, 1, tzinfo=KST)
        ),
    )


@pytest.mark.parametrize(
    "profile",
    [
        FoodNutritionProfile("general-meal", "일반식", (_fact("food:general-meal:1", QuantityUnit.SERVING),)),
        FoodNutritionProfile("general-meal", "정식", ()),
        FoodNutritionProfile("general-meal", "일반식", (), aliases=("백반",)),
    ],
    ids=["with-a-fact", "another-name", "with-an-alias"],
)
def test_e6_a_user_food_with_the_reserved_id_blocks_general_meals(
    capsys: pytest.CaptureFixture[str], database: Path, profile: FoodNutritionProfile
) -> None:
    _chicken(capsys)
    _log(capsys, "breakfast", *CHICKEN_ITEM)
    SqliteFoodNutritionRepository(database).save(profile)
    rows = _tables(database)

    assert _refused(capsys, "nutrition", "log", "--date", DAY, "--meal", "lunch", "--general") == E6
    assert _refused(capsys, "nutrition", "meal", "add-item", f"{DAY}-breakfast-1", "--general") == E6
    assert _tables(database) == rows


# --- one transaction -------------------------------------------------------------------------------------


def test_a_failed_meal_write_leaves_no_meal_and_no_profile_row(database: Path) -> None:
    ActivityRepository(database).migrate()
    _execute(
        database,
        "CREATE TRIGGER fail_step BEFORE INSERT ON nutrition_meal_items "
        "BEGIN SELECT RAISE(ABORT, 'synthetic storage failure'); END",
    )
    meals, foods = SqliteMealRepository(database), SqliteFoodNutritionRepository(database)

    with pytest.raises(sqlite3.IntegrityError, match="synthetic storage failure"):
        LogMeal(meals, foods).execute(date(2026, 10, 8), MealType.LUNCH, (GeneralMealEntry("구내식당"),), timezone=KST)

    _execute(database, "DROP TRIGGER fail_step")
    tables = _tables(database)
    assert tables["nutrition_meals"] == []
    assert tables["nutrition_food_profiles"] == []


def test_a_failed_add_item_leaves_no_profile_row(capsys: pytest.CaptureFixture[str], database: Path) -> None:
    _chicken(capsys)
    _log(capsys, "lunch", *CHICKEN_ITEM)
    rows = _tables(database)
    # The second new item fails after the general item (and its profile row) were inserted.
    _execute(
        database,
        "CREATE TRIGGER fail_step BEFORE INSERT ON nutrition_meal_items WHEN NEW.item_sequence = 3 "
        "BEGIN SELECT RAISE(ABORT, 'synthetic storage failure'); END",
    )
    entries = (GeneralMealEntry(), MealEntryItem("chicken-breast", Decimal(50), QuantityUnit.GRAM))

    with pytest.raises(sqlite3.IntegrityError, match="synthetic storage failure"):
        AddMealItems(SqliteMealRepository(database), SqliteFoodNutritionRepository(database)).execute(LUNCH, entries)

    _execute(database, "DROP TRIGGER fail_step")
    assert _tables(database) == rows


# --- AC7: nothing changes without a general meal -----------------------------------------------------------


def test_ac7_items_without_a_quantity_that_are_not_general_render_as_before(
    capsys: pytest.CaptureFixture[str], database: Path
) -> None:
    _chicken(capsys)
    meal_id = "2026-10-08-other-1"
    SqliteMealRepository(database).save(
        Meal(
            meal_id=meal_id,
            eaten_at=datetime(2026, 10, 8, 12, 0, tzinfo=KST),
            meal_type=MealType.OTHER,
            original_text="synthetic parser entry",
            items=(
                MealItem(meal_id, 1, "수제 샐러드", None, None, serving_description="one unspecified portion"),
                MealItem(meal_id, 2, "닭가슴살", None, None, "chicken-breast", serving_description="a memo"),
            ),
        )
    )

    shown = _ok(capsys, "nutrition", "meal", "show", meal_id)
    assert shown.split("\n")[1:3] == [
        "  1. 수제 샐러드 (no quantity): kcal missing | P missing | C missing | F missing",
        "     source: no nutrition facts",
    ]
    assert "  2. 닭가슴살 (chicken-breast) (no quantity): kcal missing | P missing | C missing | F missing" in shown
    document = _json(capsys, "nutrition", "meal", "show", meal_id)
    day = _ok(capsys, "nutrition", "day", "--date", DAY) + _ok(capsys, "nutrition", "day", "--date", DAY, "--json")
    for text in (shown, json.dumps(document), day):
        assert "general" not in text
        assert "unspecified portion" not in text and "a memo" not in text
    assert [list(item) for item in document["items"]] == [LEGACY_ITEM_KEYS, LEGACY_ITEM_KEYS]
    assert _rows(database, "nutrition_food_profiles") == [("chicken-breast", "닭가슴살")]


def test_ac7_catalog_only_meals_keep_their_documents(capsys: pytest.CaptureFixture[str], database: Path) -> None:
    _chicken(capsys)
    printed = _ok(capsys, "nutrition", "log", "--date", DAY, "--meal", "lunch", *CHICKEN_ITEM, "--json")
    document = json.loads(printed)
    assert [list(item) for item in document["items"]] == [LEGACY_ITEM_KEYS]
    assert document["original_text"] == f"structured entry lunch {DAY}: chicken-breast 100 g"
    assert "general" not in printed + _ok(capsys, "nutrition", "meal", "show", LUNCH)
    # The reserved profile is created only by a general meal.
    assert _rows(database, "nutrition_food_profiles") == [("chicken-breast", "닭가슴살")]
