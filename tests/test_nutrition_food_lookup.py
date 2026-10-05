"""`--item <food>`: a catalog food ID, or a food's exact name or alias (Nutrition Food Name Lookup v1).

Runs over temporary MUSCLE50_HOME copies / temporary SQLite databases only. Every food and every
nutrition value is synthetic. The central guarantees: a name or alias records exactly what the
resolved food ID records (rows, text and JSON); a token that could mean two foods is refused with
nothing written; a token that matches nothing is refused with the existing unknown-food text, at
the existing point in the flow; and nothing is ever matched fuzzily or partially.
"""

from __future__ import annotations

import json
import shutil
import sqlite3
from collections.abc import Callable
from datetime import date, datetime, timedelta, timezone, tzinfo
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

import muscle50.cli as cli
from muscle50.application.food_lookup import ResolveFoodReference
from muscle50.application.nutrition_logging import AddFood, NewFood, NutritionLoggingError
from muscle50.cli import main
from muscle50.domain.nutrition import (
    Accuracy,
    FoodNutritionProfile,
    NutritionFact,
    NutritionProvenance,
    NutritionSourceType,
    NutritionValue,
    QuantityUnit,
)
from muscle50.infrastructure.garmin.client import PythonGarminConnector
from muscle50.infrastructure.sqlite.nutrition_repository import SqliteFoodNutritionRepository

KST = timezone(timedelta(hours=9))
DAY = "2026-10-02"
MEAL = "2026-10-02-breakfast-1"
LUNCH = "2026-10-02-lunch-1"
CREATED_AT = datetime(2026, 10, 1, 8, 0, tzinfo=KST)

CHICKEN = (
    ["--id", "chicken-breast", "--name", "닭가슴살", "--alias", "Chicken Breast", "--per", "100", "g"]
    + ["--kcal", "110", "--protein", "18", "--carbs", "1", "--fat", "3"]
    + ["--source", "user_provided", "--accuracy", "exact"]
)
EGG = (
    ["--id", "egg", "--name", "계란", "--per", "1", "count"]
    + ["--kcal", "70", "--protein", "6", "--carbs", "0.5", "--fat", "5"]
    + ["--source", "nutrition_label", "--accuracy", "exact"]
)
RICE = (
    ["--id", "hetbahn-white-210", "--name", "현미 햇반", "--per", "1", "pack"]
    + ["--kcal", "300", "--protein", "6", "--carbs", "65", "--fat", "2"]
    + ["--source", "nutrition_label", "--accuracy", "exact"]
)
BANANA = (
    ["--id", "banana", "--name", "바나나", "--alias", "banana", "--per", "1", "piece"]
    + ["--kcal", "90", "--protein", "1", "--carbs", "23", "--fat", "0"]
    + ["--source", "food_database", "--accuracy", "exact"]
)
# Accepted by `food add` today: its name `egg` is compared with names/aliases only, never with IDs.
QUAIL_EGG = (
    ["--id", "quail-egg", "--name", "egg", "--per", "1", "count"]
    + ["--kcal", "15", "--protein", "1", "--carbs", "0", "--fat", "1"]
    + ["--source", "nutrition_label", "--accuracy", "exact"]
)
TABLES = (
    "nutrition_meals",
    "nutrition_meal_items",
    "nutrition_facts",
    "nutrition_food_profiles",
    "nutrition_food_profile_aliases",
)
UNKNOWN_FOOD = "no food with id {token!r} (see `muscle50 nutrition food list`)"
E1_EGG = (
    "{label} 'egg' is ambiguous: it is the ID of food egg and a name/alias of food quail-egg. "
    "No food is chosen automatically. Nothing was changed."
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


def _run(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, str, str]:
    code = main(list(argv))
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def _ok(capsys: pytest.CaptureFixture[str], *argv: str) -> str:
    code, out, err = _run(capsys, *argv)
    assert code == 0, err
    return out


def _refused(capsys: pytest.CaptureFixture[str], *argv: str) -> str:
    code, out, err = _run(capsys, *argv)
    assert (code, out) == (1, ""), err
    return err


def _database(root: Path) -> Path:
    return root / "db" / "muscle50.sqlite3"


def _tables(root: Path) -> dict[str, list[tuple[Any, ...]]]:
    """Every nutrition row, so outcomes can be compared exactly.

    `nutrition_meal_item_removals.removed_at` is left out: `meal replace-item` takes it from the
    real clock, so two otherwise identical runs differ there. No view prints it.
    """
    connection = sqlite3.connect(_database(root))
    try:
        rows = {table: connection.execute(f"SELECT * FROM {table} ORDER BY 1, 2").fetchall() for table in TABLES}
        rows["nutrition_meal_item_removals"] = connection.execute(
            "SELECT meal_id, item_sequence, replaced_by_item_sequence FROM nutrition_meal_item_removals ORDER BY 1, 2"
        ).fetchall()
        return rows
    finally:
        connection.close()


def _views(capsys: pytest.CaptureFixture[str], meal_id: str) -> tuple[str, ...]:
    """Every read view of the meal and its day, text and JSON, byte for byte."""
    return tuple(
        _ok(capsys, *command, *flags)
        for command in (
            ("nutrition", "meal", "show", meal_id),
            ("nutrition", "day", "--date", DAY),
            ("nutrition", "status", "--date", DAY),
        )
        for flags in ((), ("--json",))
    )


def _catalog(capsys: pytest.CaptureFixture[str]) -> None:
    """Synthetic catalog plus a breakfast (egg, by ID) that add-item/replace-item can edit."""
    for food in (CHICKEN, EGG, RICE, BANANA):
        _ok(capsys, "nutrition", "food", "add", *food)
    _ok(capsys, "nutrition", "log", "--date", DAY, "--meal", "breakfast", "--item", "egg", "2", "count")


def _collision(capsys: pytest.CaptureFixture[str]) -> None:
    _catalog(capsys)
    _ok(capsys, "nutrition", "food", "add", *QUAIL_EGG)


def _copy(monkeypatch: pytest.MonkeyPatch, source: Path, name: str) -> Path:
    """A byte copy of `source` (catalog facts keep their created_at), made the active home."""
    target = source.parent / name
    shutil.copytree(source, target)
    monkeypatch.setenv("MUSCLE50_HOME", str(target))
    return target


def _log(food: str, quantity: str, unit: str) -> tuple[str, ...]:
    return ("nutrition", "log", "--date", DAY, "--meal", "lunch", "--item", food, quantity, unit)


def _add_item(food: str, quantity: str, unit: str) -> tuple[str, ...]:
    return ("nutrition", "meal", "add-item", MEAL, "--item", food, quantity, unit)


def _replace_item(food: str, quantity: str, unit: str) -> tuple[str, ...]:
    return ("nutrition", "meal", "replace-item", MEAL, "--item-number", "1", "--item", food, quantity, unit)


COMMANDS: dict[str, tuple[Callable[[str, str, str], tuple[str, ...]], str, str]] = {
    # command -> (argv builder, meal it writes, label of its one --item)
    "log": (_log, LUNCH, "--item 1"),
    "add-item": (_add_item, MEAL, "--item 1"),
    "replace-item": (_replace_item, MEAL, "--item"),
}


# --- AC1: a name or alias records exactly what the food ID records ----------------------------------


@pytest.mark.parametrize("command", list(COMMANDS))
@pytest.mark.parametrize(
    ("food_id", "token", "quantity", "unit"),
    [
        pytest.param("chicken-breast", "닭가슴살", "150", "g", id="name"),
        pytest.param("chicken-breast", "Chicken Breast", "150", "g", id="alias"),
        pytest.param("chicken-breast", "cHICKEN bREAST", "150", "g", id="alias-other-ascii-case"),
        pytest.param("chicken-breast", "  닭가슴살 ", "150", "g", id="name-with-surrounding-whitespace"),
        pytest.param("hetbahn-white-210", "현미 햇반", "1", "pack", id="name-with-a-space-as-one-argument"),
    ],
)
def test_name_or_alias_records_exactly_what_the_food_id_records(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    home: Path,
    command: str,
    food_id: str,
    token: str,
    quantity: str,
    unit: str,
) -> None:
    _catalog(capsys)
    build, meal_id, _ = COMMANDS[command]

    for flags in ((), ("--json",)):
        suffix = "json" if flags else "text"
        by_id = _copy(monkeypatch, home, f"by-id-{suffix}")
        id_out = _ok(capsys, *build(food_id, quantity, unit), *flags)
        id_views = _views(capsys, meal_id)
        by_name = _copy(monkeypatch, home, f"by-name-{suffix}")
        name_out = _ok(capsys, *build(token, quantity, unit), *flags)
        name_views = _views(capsys, meal_id)

        assert name_out == id_out
        assert f"({food_id})" in name_out or f'"food_id": "{food_id}"' in name_out
        assert _tables(by_name) == _tables(by_id)
        assert name_views == id_views

    if command == "log":
        # The stored original_text names the resolved food ID, not what was typed.
        stored = {row[0]: row[4] for row in _tables(by_name)["nutrition_meals"]}
        assert stored[LUNCH] == f"structured entry lunch {DAY}: {food_id} {quantity} {unit}"


def test_name_input_json_is_deterministic_and_text_is_ascii_apart_from_names(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch, home: Path
) -> None:
    _catalog(capsys)
    argv = (*_log("닭가슴살", "150", "g"), "--item", "현미 햇반", "1", "pack", "--json")

    _copy(monkeypatch, home, "first")
    first = _ok(capsys, *argv)
    _copy(monkeypatch, home, "second")
    second = _ok(capsys, *argv)

    assert first == second
    assert first == json.dumps(json.loads(first), indent=2) + "\n"
    document = json.loads(first)
    assert [item["food_id"] for item in document["items"]] == ["chicken-breast", "hetbahn-white-210"]

    _copy(monkeypatch, home, "text")
    text = _ok(capsys, *argv[:-1])
    assert text.replace("닭가슴살", "").replace("현미 햇반", "").isascii()


def test_a_food_whose_id_is_also_its_own_alias_is_not_ambiguous(capsys: pytest.CaptureFixture[str]) -> None:
    _catalog(capsys)

    out = _ok(capsys, *_log("banana", "1", "piece"))
    assert "바나나 (banana) 1 piece" in out
    second = _ok(capsys, "nutrition", "log", "--date", DAY, "--meal", "snack", "--item", "바나나", "1", "piece")
    assert "바나나 (banana) 1 piece" in second


# --- AC2: a token that names two different foods is refused -----------------------------------------


@pytest.mark.parametrize("command", list(COMMANDS))
def test_id_that_is_another_foods_name_is_refused_and_nothing_changes(
    capsys: pytest.CaptureFixture[str], home: Path, command: str
) -> None:
    _collision(capsys)
    build, meal_id, label = COMMANDS[command]
    before = (_tables(home), _views(capsys, MEAL))

    assert _refused(capsys, *build("egg", "1", "count")) == "오류: " + E1_EGG.format(label=label) + "\n"
    assert (_tables(home), _views(capsys, MEAL)) == before
    # The other food stays reachable by its own ID, and egg by its name.
    _ok(capsys, *build("quail-egg", "1", "count"))
    _ok(capsys, "nutrition", "log", "--date", DAY, "--meal", "dinner", "--item", "계란", "1", "count")


def test_a_name_or_alias_shared_by_two_foods_is_refused_and_nothing_changes(
    capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    """Two foods with one alias cannot be made through `food add`; data written outside the CLI can."""
    _catalog(capsys)
    repository = SqliteFoodNutritionRepository(_database(home))
    repository.save(_profile("tofu-a", "두부 A", ("tofu",)))
    repository.save(_profile("tofu-b", "두부 B", ("TOFU",)))
    before = _tables(home)

    assert _refused(capsys, *_log("Tofu", "1", "count")) == (
        "오류: --item 1 'Tofu' is ambiguous: it is a name/alias of foods tofu-a, tofu-b. "
        "No food is chosen automatically; use one of these food IDs. Nothing was changed.\n"
    )
    assert _tables(home) == before
    assert "두부 A (tofu-a) 1 count" in _ok(capsys, *_log("tofu-a", "1", "count"))


@pytest.mark.parametrize(
    "argv",
    [
        pytest.param(("nutrition", "log", "--date", DAY, "--meal", "lunch"), id="log"),
        pytest.param(("nutrition", "meal", "add-item", MEAL), id="add-item"),
    ],
)
def test_one_ambiguous_item_among_several_writes_nothing(
    capsys: pytest.CaptureFixture[str], home: Path, argv: tuple[str, ...]
) -> None:
    _collision(capsys)
    before = (_tables(home), _views(capsys, MEAL))

    err = _refused(capsys, *argv, "--item", "banana", "1", "piece", "--item", "egg", "1", "count")

    assert err == "오류: " + E1_EGG.format(label="--item 2") + "\n"
    assert (_tables(home), _views(capsys, MEAL)) == before


# --- AC3: no match is the existing unknown-food refusal ---------------------------------------------


@pytest.mark.parametrize(
    "token",
    [
        pytest.param("닭가슴", id="partial-name"),
        pytest.param("Chicken", id="partial-alias"),
        pytest.param("없는음식", id="unknown-name"),
        pytest.param(" ", id="whitespace-only"),
        pytest.param("Chicken-Breast", id="id-in-other-case"),
        pytest.param(" chicken-breast", id="padded-id"),
    ],
)
@pytest.mark.parametrize("command", list(COMMANDS))
def test_a_token_that_matches_no_food_is_refused_with_the_existing_text(
    capsys: pytest.CaptureFixture[str], home: Path, command: str, token: str
) -> None:
    _catalog(capsys)
    build, _, label = COMMANDS[command]
    before = (_tables(home), _views(capsys, MEAL))

    err = _refused(capsys, *build(token, "1", "g"))

    unknown = UNKNOWN_FOOD.format(token=token)
    expected = f"item 1: {unknown}" if command == "log" else f"{label}: {unknown}. Nothing was changed."
    assert err == f"오류: {expected}\n"
    assert (_tables(home), _views(capsys, MEAL)) == before


# --- Existing refusals keep their text and their order -----------------------------------------------


@pytest.mark.parametrize(
    "argv",
    [
        pytest.param(("log", "--date", DAY, "--meal", "lunch", "--item", "{food}", "abc", "g"), id="log-quantity"),
        pytest.param(("log", "--date", DAY, "--meal", "lunch", "--item", "{food}", "1", "spoon"), id="log-unit"),
        pytest.param(
            ("log", "--date", DAY, "--meal", "lunch", "--time", "25:00", "--item", "{food}", "1", "g"), id="log-time"
        ),
        pytest.param(("log", "--date", DAY, "--meal", "breakfast", "--item", "{food}", "1", "g"), id="log-duplicate"),
        pytest.param(("meal", "add-item", MEAL, "--item", "{food}", "0", "g"), id="add-item-quantity"),
        pytest.param(("meal", "add-item", "2026-10-02-dinner-9", "--item", "{food}", "1", "g"), id="add-item-no-meal"),
        pytest.param(
            ("meal", "replace-item", "2026-10-02-dinner-9", "--item-number", "1", "--item", "{food}", "1", "g"),
            id="replace-item-no-meal",
        ),
        pytest.param(
            ("meal", "replace-item", MEAL, "--item-number", "9", "--item", "{food}", "1", "g"),
            id="replace-item-no-such-item",
        ),
    ],
)
def test_earlier_refusals_come_before_the_food_lookup(
    capsys: pytest.CaptureFixture[str], home: Path, argv: tuple[str, ...]
) -> None:
    """An unknown name gets exactly the refusal a valid food ID gets when something else is wrong first."""
    _catalog(capsys)
    before = _tables(home)

    with_id = _refused(capsys, "nutrition", *(part.format(food="chicken-breast") for part in argv))
    with_unknown_name = _refused(capsys, "nutrition", *(part.format(food="닭가슴") for part in argv))

    assert with_unknown_name == with_id
    assert "no food with id" not in with_unknown_name
    assert _tables(home) == before


@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        pytest.param(
            ("log", "--date", DAY, "--meal", "lunch", "--time", "25:00", "--item", "egg", "1", "count"),
            "--time",
            id="log-time",
        ),
        pytest.param(
            ("log", "--date", DAY, "--meal", "lunch", "--item", "egg", "1", "count", "--item", "banana", "x", "piece"),
            "--item 2 quantity",
            id="log-later-item-quantity",
        ),
        pytest.param(
            ("meal", "add-item", MEAL, "--item", "egg", "1", "count", "--item", "banana", "1", "spoon"),
            "--item 2",
            id="add-item-later-item-unit",
        ),
    ],
)
def test_every_item_and_time_is_parsed_before_any_lookup(
    capsys: pytest.CaptureFixture[str], home: Path, argv: tuple[str, ...], expected: str
) -> None:
    """A format error anywhere is reported before an ambiguous food, as it was before any lookup existed."""
    _collision(capsys)
    before = _tables(home)

    err = _refused(capsys, "nutrition", *argv)

    assert expected in err
    assert "ambiguous" not in err
    assert _tables(home) == before


# --- nutrition repeat does not look anything up -------------------------------------------------------


def test_repeat_is_unchanged_by_a_later_name_collision(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch, home: Path
) -> None:
    _catalog(capsys)
    repeat = ("nutrition", "repeat", MEAL, "--date", "2026-10-03")

    for flags in ((), ("--json",)):
        suffix = "json" if flags else "text"
        _copy(monkeypatch, home, f"control-{suffix}")
        control = _ok(capsys, *repeat, *flags)
        _copy(monkeypatch, home, f"collision-{suffix}")
        _ok(capsys, "nutrition", "food", "add", *QUAIL_EGG)
        assert _ok(capsys, *repeat, *flags) == control
        assert "egg" in control


# --- ResolveFoodReference ------------------------------------------------------------------------------


def _profile(food_id: str, name: str, aliases: tuple[str, ...]) -> FoodNutritionProfile:
    return FoodNutritionProfile(
        profile_id=food_id,
        name=name,
        aliases=aliases,
        facts=(
            NutritionFact(
                fact_id=f"food:{food_id}:1",
                values=NutritionValue(calories_kcal=Decimal("50")),
                basis_quantity=Decimal("1"),
                basis_unit=QuantityUnit.COUNT,
                provenance=NutritionProvenance(
                    source_type=NutritionSourceType.USER_PROVIDED,
                    accuracy=Accuracy.EXACT,
                    source_reference="synthetic",
                    created_at=CREATED_AT,
                ),
            ),
        ),
    )


def _new_food(food_id: str, name: str, *aliases: str) -> NewFood:
    return NewFood(
        food_id=food_id,
        name=name,
        basis_quantity=Decimal("1"),
        basis_unit=QuantityUnit.COUNT,
        values=NutritionValue(calories_kcal=Decimal("50")),
        source_type=NutritionSourceType.USER_PROVIDED,
        accuracy=Accuracy.EXACT,
        source_reference="synthetic",
        aliases=aliases,
    )


@pytest.fixture
def foods(tmp_path: Path) -> SqliteFoodNutritionRepository:
    repository = SqliteFoodNutritionRepository(tmp_path / "lookup.sqlite3")
    repository.migrate()
    add = AddFood(repository, clock=lambda: CREATED_AT)
    add.execute(_new_food("chicken-breast", "닭가슴살", "Chicken Breast"))
    add.execute(_new_food("banana", "바나나", "banana"))
    add.execute(_new_food("egg", "계란"))
    return repository


@pytest.mark.parametrize(
    ("reference", "expected"),
    [
        pytest.param("chicken-breast", "chicken-breast", id="id"),
        pytest.param("닭가슴살", "chicken-breast", id="name"),
        pytest.param("Chicken Breast", "chicken-breast", id="alias"),
        pytest.param("CHICKEN BREAST", "chicken-breast", id="ascii-case-folded"),
        pytest.param(" \t닭가슴살 \n", "chicken-breast", id="stripped"),
        pytest.param("banana", "banana", id="own-alias-equals-own-id"),
        pytest.param("계란", "egg", id="name-of-food-with-ascii-id"),
        pytest.param("닭가슴", None, id="partial-is-no-match"),
        pytest.param("Chicken-Breast", None, id="id-is-case-sensitive"),
        pytest.param(" egg", None, id="padded-id-is-no-id"),
        pytest.param("", None, id="empty"),
        pytest.param("   ", None, id="whitespace-only"),
    ],
)
def test_resolve_food_reference(foods: SqliteFoodNutritionRepository, reference: str, expected: str | None) -> None:
    assert ResolveFoodReference(foods).execute(reference, label="--item 1") == expected


def test_resolve_refuses_an_id_that_is_also_other_foods_names(foods: SqliteFoodNutritionRepository) -> None:
    AddFood(foods, clock=lambda: CREATED_AT).execute(_new_food("quail-egg", "egg"))
    resolver = ResolveFoodReference(foods)

    with pytest.raises(NutritionLoggingError) as one:
        resolver.execute("egg", label="--item 3")
    assert str(one.value) == E1_EGG.format(label="--item 3")

    foods.save(_profile("duck-egg", "오리알", ("EGG",)))
    with pytest.raises(NutritionLoggingError) as two:
        resolver.execute("egg", label="--item")
    assert str(two.value) == (
        "--item 'egg' is ambiguous: it is the ID of food egg and a name/alias of foods duck-egg, quail-egg. "
        "No food is chosen automatically. Nothing was changed."
    )


def test_resolve_refuses_a_name_shared_by_several_foods(foods: SqliteFoodNutritionRepository) -> None:
    foods.save(_profile("tofu-a", "두부 A", ("tofu",)))
    foods.save(_profile("tofu-b", "두부 B", ("Tofu",)))
    foods.save(_profile("tofu-c", "tofu", ()))

    with pytest.raises(NutritionLoggingError) as refused:
        ResolveFoodReference(foods).execute(" TOFU ", label="--item 2")
    assert str(refused.value) == (
        "--item 2 ' TOFU ' is ambiguous: it is a name/alias of foods tofu-a, tofu-b, tofu-c. "
        "No food is chosen automatically; use one of these food IDs. Nothing was changed."
    )
