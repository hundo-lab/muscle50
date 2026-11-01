"""LDL Nutrients v1 storage: migration 011, append-only rows, snapshots, merge, old databases.

All values are synthetic test numbers. Every database lives under pytest's tmp_path.
"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime, time, timedelta, timezone, tzinfo
from decimal import Decimal
from pathlib import Path

import pytest

import muscle50.cli as cli
from muscle50.application.meal_corrections import MergeMeals
from muscle50.application.nutrition_logging import (
    AddFood,
    AddFoodFact,
    LogMeal,
    MealEntryItem,
    NewFood,
    NewFoodFact,
    NutritionLoggingError,
    RepeatMeal,
)
from muscle50.cli import main
from muscle50.domain.nutrition import (
    Accuracy,
    MealType,
    NutritionSourceType,
    NutritionValue,
    OptionalNutrient,
    OptionalNutrientAmount,
    QuantityUnit,
    aggregate_optional,
)
from muscle50.infrastructure.garmin.client import PythonGarminConnector
from muscle50.infrastructure.sqlite.database import ActivityRepository
from muscle50.infrastructure.sqlite.nutrition_reader import SqliteNutritionReader
from muscle50.infrastructure.sqlite.nutrition_repository import SqliteFoodNutritionRepository, SqliteMealRepository

KST = timezone(timedelta(hours=9))
DAY = date(2026, 11, 5)
CLOCK = datetime(2026, 11, 1, 9, 0, tzinfo=KST)
SAT = OptionalNutrient.SATURATED_FAT_G
FIBER = OptionalNutrient.FIBER_G
_OPTIONAL_OBJECTS = (
    "nutrition_fact_optional_nutrients",
    "nutrition_fact_optional_nutrients_prevent_update",
    "nutrition_fact_optional_nutrients_prevent_delete",
    "nutrition_fact_optional_nutrients_exact_has_no_range",
)


@pytest.fixture
def database(tmp_path: Path) -> Path:
    path = tmp_path / "muscle50.sqlite3"
    ActivityRepository(path).migrate()
    return path


def _food(
    food_id: str,
    *,
    fat: str = "3",
    optional: tuple[OptionalNutrientAmount, ...] = (),
    per: str = "40",
    kcal: str = "150",
) -> NewFood:
    return NewFood(
        food_id=food_id,
        name=food_id.title(),
        basis_quantity=Decimal(per),
        basis_unit=QuantityUnit.GRAM,
        values=NutritionValue(Decimal(kcal), Decimal(5), Decimal(27), Decimal(fat)),
        source_type=NutritionSourceType.NUTRITION_LABEL,
        accuracy=Accuracy.EXACT,
        source_reference="synthetic label",
        optional=optional,
    )


def _amounts(sat: str | None = None, fiber: str | None = None) -> tuple[OptionalNutrientAmount, ...]:
    amounts = []
    if sat is not None:
        amounts.append(OptionalNutrientAmount(SAT, Decimal(sat)))
    if fiber is not None:
        amounts.append(OptionalNutrientAmount(FIBER, Decimal(fiber)))
    return tuple(amounts)


def _add(database: Path, food: NewFood) -> None:
    AddFood(SqliteFoodNutritionRepository(database), clock=lambda: CLOCK).execute(food)


def _log(database: Path, meal_type: MealType, *entries: MealEntryItem, at: time | None = None) -> str:
    intake = LogMeal(SqliteMealRepository(database), SqliteFoodNutritionRepository(database)).execute(
        DAY, meal_type, entries, timezone=KST, eaten_time=at
    )
    return intake.meal.meal_id


def _rows(database: Path) -> dict[str, list[tuple[object, ...]]]:
    with sqlite3.connect(database) as connection:
        tables = [
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            )
        ]
        return {table: sorted(connection.execute(f"SELECT * FROM {table}").fetchall(), key=repr) for table in tables}


def _to_pre_011(database: Path) -> None:
    """The same database as it was before migration 11: no table, no triggers, no marker."""
    with sqlite3.connect(database) as connection:
        for name in _OPTIONAL_OBJECTS[1:]:
            connection.execute(f"DROP TRIGGER {name}")
        connection.execute("DROP TABLE nutrition_fact_optional_nutrients")
        connection.execute("DELETE FROM schema_migrations WHERE version = 11")


# --- migration ---------------------------------------------------------------------------------


def test_migration_011_over_a_010_database_adds_only_its_objects(database: Path) -> None:
    _add(database, _food("syn-oats"))
    _log(database, MealType.BREAKFAST, MealEntryItem("syn-oats", Decimal(80), QuantityUnit.GRAM))
    _to_pre_011(database)
    before = _rows(database)
    with sqlite3.connect(database) as connection:
        objects_before = set(connection.execute("SELECT type, name FROM sqlite_master").fetchall())

    ActivityRepository(database).migrate()

    after = _rows(database)
    with sqlite3.connect(database) as connection:
        objects_after = set(connection.execute("SELECT type, name FROM sqlite_master").fetchall())
        versions = [row[0] for row in connection.execute("SELECT version FROM schema_migrations ORDER BY version")]
    assert {name for _type, name in objects_after - objects_before} == {
        *_OPTIONAL_OBJECTS,
        "sqlite_autoindex_nutrition_fact_optional_nutrients_1",
    }
    assert after.pop("nutrition_fact_optional_nutrients") == []
    schema_rows = after.pop("schema_migrations")
    assert [row[0] for row in schema_rows if row[0] == 11] == [11]
    before.pop("schema_migrations")
    assert after == before
    assert versions == list(range(1, 12))


def test_optional_rows_are_append_only_and_exact_facts_take_no_range(database: Path) -> None:
    _add(database, _food("syn-oats", optional=_amounts(sat="0.5", fiber="4")))
    with sqlite3.connect(database) as connection:
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            connection.execute("UPDATE nutrition_fact_optional_nutrients SET value = '0'")
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            connection.execute("DELETE FROM nutrition_fact_optional_nutrients")
        with pytest.raises(sqlite3.IntegrityError, match="exact nutrition facts cannot carry an estimate range"):
            connection.execute(
                "INSERT INTO nutrition_fact_optional_nutrients VALUES ('food:syn-oats:1', 'fiber_g', NULL, '1', '2')"
            )
        with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
            connection.execute(
                "INSERT INTO nutrition_fact_optional_nutrients "
                "VALUES ('food:syn-oats:1', 'cholesterol', '1', NULL, NULL)"
            )
        with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
            connection.execute(
                "INSERT INTO nutrition_fact_optional_nutrients VALUES ('food:syn-oats:1', 'fiber_g', NULL, NULL, NULL)"
            )
        rows = connection.execute("SELECT * FROM nutrition_fact_optional_nutrients ORDER BY nutrient").fetchall()
    assert rows == [
        ("food:syn-oats:1", "fiber_g", "4", None, None),
        ("food:syn-oats:1", "saturated_fat_g", "0.5", None, None),
    ]


# --- repository round trip, snapshot, repeat, merge -------------------------------------------------


def test_repository_round_trip_keeps_optional_amounts(database: Path) -> None:
    _add(database, _food("syn-oats", optional=_amounts(sat="0.5", fiber="4")))
    _add(database, _food("syn-plain"))
    foods = SqliteFoodNutritionRepository(database)
    oats, plain = foods.get("syn-oats"), foods.get("syn-plain")
    assert oats is not None and plain is not None
    assert oats.facts[0].optional == _amounts(sat="0.5", fiber="4")
    assert plain.facts[0].optional == ()


def test_logging_snapshots_optional_amounts_and_later_versions_do_not_change_the_meal(database: Path) -> None:
    _add(database, _food("syn-oats", optional=_amounts(sat="0.5", fiber="4")))
    meal_id = _log(database, MealType.BREAKFAST, MealEntryItem("syn-oats", Decimal(80), QuantityUnit.GRAM))
    AddFoodFact(SqliteFoodNutritionRepository(database), clock=lambda: CLOCK + timedelta(hours=1)).execute(
        NewFoodFact(
            "syn-oats",
            Decimal(40),
            QuantityUnit.GRAM,
            NutritionValue(Decimal(150), Decimal(5), Decimal(27), Decimal(3)),
            NutritionSourceType.NUTRITION_LABEL,
            Accuracy.EXACT,
            "synthetic label v2",
            _amounts(sat="1", fiber="5"),
        )
    )
    meal = SqliteMealRepository(database).get(meal_id)
    assert meal is not None
    assert [(c.nutrient, c.value, c.fact_id) for c in meal.items[0].calculated_optional()] == [
        (SAT, Decimal(1), f"{meal_id}:1:food:syn-oats:1"),
        (FIBER, Decimal(8), f"{meal_id}:1:food:syn-oats:1"),
    ]
    repeated = RepeatMeal(SqliteMealRepository(database), SqliteFoodNutritionRepository(database)).execute(
        meal_id, DAY, timezone=KST, additional=True
    )
    assert [(c.nutrient, c.value) for c in repeated.intake.items[0].optional] == [
        (SAT, Decimal(2)),
        (FIBER, Decimal(10)),
    ]


def test_merge_copies_optional_amounts(database: Path) -> None:
    _add(database, _food("syn-oats", optional=_amounts(sat="0.5", fiber="4")))
    entry = MealEntryItem("syn-oats", Decimal(40), QuantityUnit.GRAM)
    target = _log(database, MealType.BREAKFAST, entry)
    source = LogMeal(SqliteMealRepository(database), SqliteFoodNutritionRepository(database)).execute(
        DAY, MealType.BREAKFAST, (entry,), timezone=KST, additional=True
    )
    merged = MergeMeals(SqliteMealRepository(database), clock=lambda: CLOCK).execute(
        target, source.meal.meal_id, timezone_for=lambda day: KST
    )
    sat, fiber = merged.intake.summary.optional
    assert (sat.total, fiber.total) == (Decimal(1), Decimal(8))


def test_merge_is_refused_when_it_would_change_the_saturated_fat_total(database: Path) -> None:
    # 1 g of a 3 g fact: every four-nutrient value is exactly 1, saturated fat is 1/3 (non-terminating).
    _add(database, _food("syn-third", per="3", kcal="3", fat="3", optional=_amounts(sat="1")))
    _add(database, _food("syn-big", per="1", kcal="1000", fat="1000", optional=_amounts(sat="1000")))
    third = MealEntryItem("syn-third", Decimal(1), QuantityUnit.GRAM)
    target = _log(database, MealType.BREAKFAST, third, at=time(8))
    _log(database, MealType.LUNCH, MealEntryItem("syn-big", Decimal(1), QuantityUnit.GRAM), at=time(9))
    source = LogMeal(SqliteMealRepository(database), SqliteFoodNutritionRepository(database)).execute(
        DAY, MealType.BREAKFAST, (third,), timezone=KST, eaten_time=time(10), additional=True
    )
    before = _rows(database)

    with pytest.raises(NutritionLoggingError, match="exact day totals for saturated fat"):
        MergeMeals(SqliteMealRepository(database), clock=lambda: CLOCK).execute(
            target, source.meal.meal_id, timezone_for=lambda day: KST
        )
    assert _rows(database) == before


# --- failed writes ----------------------------------------------------------------------------------


def test_a_failed_optional_row_rolls_back_the_food_and_its_facts(database: Path) -> None:
    with sqlite3.connect(database) as connection:
        connection.execute(
            "CREATE TRIGGER fail_step BEFORE INSERT ON nutrition_fact_optional_nutrients "
            "BEGIN SELECT RAISE(ABORT, 'synthetic storage failure'); END"
        )
    before = _rows(database)
    with pytest.raises(sqlite3.IntegrityError, match="synthetic storage failure"):
        _add(database, _food("syn-oats", optional=_amounts(sat="0.5")))
    assert _rows(database) == before


# --- read-only readers on a database before migration 11 -----------------------------------------


def test_the_reader_reads_a_pre_011_database_as_unknown(database: Path) -> None:
    _add(database, _food("syn-plain"))
    _log(database, MealType.BREAKFAST, MealEntryItem("syn-plain", Decimal(40), QuantityUnit.GRAM))
    bounds = (
        datetime.combine(DAY, time(0), tzinfo=KST),
        datetime.combine(DAY + timedelta(days=1), time(0), tzinfo=KST),
    )
    migrated = SqliteNutritionReader(database).list_eaten_between(*bounds)
    _to_pre_011(database)
    old = SqliteNutritionReader(database).list_eaten_between(*bounds)
    assert old == migrated
    sat, fiber = aggregate_optional(old[0].items)
    assert (sat.has_data, sat.total, fiber.known_subtotal) == (False, None, None)


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "home"
    monkeypatch.setenv("MUSCLE50_HOME", str(root))
    monkeypatch.setattr(
        PythonGarminConnector, "authenticate", lambda *args, **kwargs: pytest.fail("must not use Garmin")
    )

    def fixed_timezone(day: date) -> tzinfo:
        return KST

    monkeypatch.setattr(cli, "_local_timezone", fixed_timezone)
    monkeypatch.setattr(cli, "_today", lambda: DAY)
    return root


def _out(capsys: pytest.CaptureFixture[str], *argv: str) -> str:
    code = main(list(argv))
    captured = capsys.readouterr()
    assert code == 0, captured.err
    return captured.out


def test_recommend_reads_a_pre_011_database_unchanged(home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _out(
        capsys,
        *("nutrition", "food", "add", "--id", "syn-plain", "--name", "SynPlain", "--per", "40", "g"),
        *("--kcal", "150", "--protein", "5", "--carbs", "27", "--fat", "3"),
        *("--source", "nutrition_label", "--accuracy", "exact"),
    )
    _out(capsys, "nutrition", "target", "set", "kcal", "--exact", "2400")
    _out(capsys, "nutrition", "log", "--meal", "breakfast", "--item", "syn-plain", "80", "g")
    migrated = _out(capsys, "recommend", "--date", DAY.isoformat(), "--json")
    _to_pre_011(home / "db" / "muscle50.sqlite3")
    assert _out(capsys, "recommend", "--date", DAY.isoformat(), "--json") == migrated
    with sqlite3.connect(home / "db" / "muscle50.sqlite3") as connection:
        assert connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone() == (10,)
