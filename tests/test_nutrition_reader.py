"""The read-only meal reader returns what the repository returns and never creates anything."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from muscle50.domain.nutrition import (
    Accuracy,
    Meal,
    MealItem,
    MealType,
    NutritionFact,
    NutritionProvenance,
    NutritionSourceType,
    NutritionValue,
    QuantityUnit,
)
from muscle50.infrastructure.sqlite.nutrition_reader import NutritionReadError, SqliteNutritionReader
from muscle50.infrastructure.sqlite.nutrition_repository import SqliteMealRepository

KST = timezone(timedelta(hours=9))
DAY_START = datetime(2026, 3, 16, tzinfo=KST)
DAY_END = DAY_START + timedelta(days=1)


def _meal(meal_id: str, eaten_at: datetime) -> Meal:
    fact = NutritionFact(
        fact_id=f"{meal_id}:1:fact",
        values=NutritionValue(calories_kcal=Decimal("200"), protein_g=Decimal("30"), carbohydrate_g=None),
        basis_quantity=Decimal("1"),
        basis_unit=QuantityUnit.COUNT,
        provenance=NutritionProvenance(
            source_type=NutritionSourceType.NUTRITION_LABEL,
            accuracy=Accuracy.EXACT,
            source_reference="synthetic label",
            created_at=datetime(2026, 3, 1, tzinfo=UTC),
        ),
    )
    item = MealItem(
        meal_id=meal_id,
        sequence=1,
        food_name="SynShake",
        quantity=Decimal("1"),
        quantity_unit=QuantityUnit.COUNT,
        nutrition_facts=(fact,),
    )
    return Meal(
        meal_id=meal_id, eaten_at=eaten_at, meal_type=MealType.BREAKFAST, original_text="synthetic", items=(item,)
    )


def test_reader_lists_the_same_meals_as_the_repository(tmp_path: Path) -> None:
    database = tmp_path / "db" / "muscle50.sqlite3"
    repository = SqliteMealRepository(database)
    repository.migrate()
    repository.save(_meal("inside", DAY_START + timedelta(hours=8)))
    repository.save(_meal("next-day", DAY_END))

    meals = SqliteNutritionReader(database).list_eaten_between(DAY_START, DAY_END)

    assert meals == repository.list_eaten_between(DAY_START, DAY_END)
    assert [meal.meal_id for meal in meals] == ["inside"]


def test_missing_database_is_an_error_and_nothing_is_created(tmp_path: Path) -> None:
    database = tmp_path / "absent" / "muscle50.sqlite3"

    with pytest.raises(NutritionReadError, match="not found"):
        SqliteNutritionReader(database).list_eaten_between(DAY_START, DAY_END)

    assert not database.parent.exists()


def test_database_without_nutrition_tables_is_refused(tmp_path: Path) -> None:
    database = tmp_path / "old.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY)")
        connection.execute("INSERT INTO schema_migrations VALUES (2)")
    connection.close()

    with pytest.raises(NutritionReadError, match="no nutrition tables"):
        SqliteNutritionReader(database).list_eaten_between(DAY_START, DAY_END)


def test_naive_bounds_are_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        SqliteNutritionReader(tmp_path / "x.sqlite3").list_eaten_between(datetime(2026, 3, 16), DAY_END)
