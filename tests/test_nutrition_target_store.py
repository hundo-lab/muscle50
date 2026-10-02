"""Target persistence and the daily status use case over a temporary home (synthetic values only)."""

from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from muscle50.application.nutrition_logging import AddFood, LogMeal, MealEntryItem, NewFood
from muscle50.application.nutrition_targets import (
    MissingItem,
    SetNutritionTarget,
    ShowDailyNutritionStatus,
    ShowNutritionTargets,
)
from muscle50.domain.nutrition import (
    Accuracy,
    MealType,
    NutrientField,
    NutritionSourceType,
    NutritionValue,
    QuantityUnit,
)
from muscle50.domain.nutrition_targets import (
    ExactTarget,
    NutritionTargetError,
    NutritionTargets,
    RangeTarget,
    TargetStatus,
)
from muscle50.infrastructure.nutrition_target_store import JsonNutritionTargetRepository
from muscle50.infrastructure.sqlite.nutrition_repository import SqliteFoodNutritionRepository, SqliteMealRepository

KST = timezone(timedelta(hours=9))
DAY = date(2026, 10, 2)
PROTEIN_RANGE = RangeTarget(Decimal(170), Decimal(180))
FAT_EXACT = ExactTarget(Decimal("80.5"))


@pytest.fixture
def path(tmp_path: Path) -> Path:
    return tmp_path / "home" / "config" / "nutrition_targets.json"


@pytest.fixture
def store(path: Path) -> JsonNutritionTargetRepository:
    return JsonNutritionTargetRepository(path)


def _valid_document() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "targets": {
            "calories_kcal": {"kind": "unset"},
            "protein_g": {"kind": "range", "minimum": "170", "maximum": "180"},
            "carbohydrate_g": {"kind": "unset"},
            "fat_g": {"kind": "exact", "value": "80.5"},
        },
    }


def _write(path: Path, document: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(document if isinstance(document, str) else json.dumps(document), encoding="utf-8")


# --- persistence --------------------------------------------------------------------------


def test_missing_file_means_no_targets_and_reading_never_creates_it(
    store: JsonNutritionTargetRepository, path: Path
) -> None:
    assert store.load() == NutritionTargets()
    assert ShowNutritionTargets(store).execute() == NutritionTargets()
    assert not path.parent.exists()


def test_targets_round_trip_exactly(store: JsonNutritionTargetRepository) -> None:
    targets = NutritionTargets(protein_g=PROTEIN_RANGE, fat_g=FAT_EXACT)

    store.save(targets)

    assert store.load() == targets
    assert store.load().get(NutrientField.FAT_G) == ExactTarget(Decimal("80.5"))


def test_saved_file_is_versioned_deterministic_lf_and_uses_decimal_strings(
    store: JsonNutritionTargetRepository, path: Path
) -> None:
    store.save(NutritionTargets(protein_g=PROTEIN_RANGE, fat_g=FAT_EXACT))
    first = path.read_bytes()
    store.save(NutritionTargets(fat_g=FAT_EXACT).with_target(NutrientField.PROTEIN_G, PROTEIN_RANGE))

    assert path.read_bytes() == first
    assert b"\r\n" not in first
    assert json.loads(first) == _valid_document()
    assert list(path.parent.iterdir()) == [path]  # no temporary file left behind


def test_set_target_changes_one_nutrient_and_keeps_the_others(store: JsonNutritionTargetRepository) -> None:
    use_case = SetNutritionTarget(store)

    use_case.execute(NutrientField.PROTEIN_G, PROTEIN_RANGE)
    use_case.execute(NutrientField.FAT_G, FAT_EXACT)
    stored = use_case.execute(NutrientField.PROTEIN_G, ExactTarget(Decimal(175)))

    assert stored == NutritionTargets(protein_g=ExactTarget(Decimal(175)), fat_g=FAT_EXACT)
    assert use_case.execute(NutrientField.FAT_G, None) == NutritionTargets(protein_g=ExactTarget(Decimal(175)))
    assert store.load() == NutritionTargets(protein_g=ExactTarget(Decimal(175)))


def test_valid_hand_written_file_is_accepted(store: JsonNutritionTargetRepository, path: Path) -> None:
    _write(path, _valid_document())

    assert store.load() == NutritionTargets(protein_g=PROTEIN_RANGE, fat_g=FAT_EXACT)


def _broken(change: Any) -> dict[str, Any]:
    document = _valid_document()
    change(document)
    return document


@pytest.mark.parametrize(
    "document",
    [
        "{not json",
        "[]",
        _broken(lambda d: d.update(schema_version=2)),
        _broken(lambda d: d.update(schema_version="1")),
        _broken(lambda d: d.update(schema_version=True)),
        _broken(lambda d: d.update(extra=1)),
        _broken(lambda d: d.pop("schema_version")),
        _broken(lambda d: d["targets"].pop("fat_g")),
        _broken(lambda d: d["targets"].update(fiber_g={"kind": "unset"})),
        _broken(lambda d: d["targets"].update(fat_g=None)),
        _broken(lambda d: d["targets"].update(fat_g={"kind": "exact", "value": 80.5})),
        _broken(lambda d: d["targets"].update(fat_g={"kind": "exact", "value": 80})),
        _broken(lambda d: d["targets"].update(fat_g={"kind": "exact", "value": "0"})),
        _broken(lambda d: d["targets"].update(fat_g={"kind": "exact", "value": "-5"})),
        _broken(lambda d: d["targets"].update(fat_g={"kind": "exact", "value": "NaN"})),
        _broken(lambda d: d["targets"].update(fat_g={"kind": "exact", "value": "1e3"})),
        _broken(lambda d: d["targets"].update(fat_g={"kind": "exact", "value": "80", "maximum": "90"})),
        _broken(lambda d: d["targets"].update(fat_g={"kind": "between", "value": "80"})),
        _broken(lambda d: d["targets"].update(fat_g={"kind": "unset", "value": "80"})),
        _broken(lambda d: d["targets"].update(protein_g={"kind": "range", "minimum": "180", "maximum": "170"})),
        _broken(lambda d: d["targets"].update(protein_g={"kind": "range", "minimum": "170"})),
    ],
)
def test_malformed_file_is_an_error_not_an_empty_target_set(
    store: JsonNutritionTargetRepository, path: Path, document: Any
) -> None:
    _write(path, document)

    with pytest.raises(NutritionTargetError, match="nutrition target file"):
        store.load()


def test_set_target_refuses_to_overwrite_a_malformed_file(store: JsonNutritionTargetRepository, path: Path) -> None:
    _write(path, "{not json")

    with pytest.raises(NutritionTargetError):
        SetNutritionTarget(store).execute(NutrientField.FAT_G, FAT_EXACT)
    assert path.read_text(encoding="utf-8") == "{not json"


# --- daily status over logged meals -------------------------------------------------------


@pytest.fixture
def database(tmp_path: Path) -> Path:
    database = tmp_path / "db" / "muscle50.sqlite3"
    SqliteFoodNutritionRepository(database).migrate()
    foods = SqliteFoodNutritionRepository(database)
    add = AddFood(foods, clock=lambda: datetime(2026, 10, 1, 21, tzinfo=KST))
    for food_id, unit, values in (
        ("chicken", QuantityUnit.GRAM, NutritionValue(Decimal(110), Decimal(18), Decimal(1), Decimal(3))),
        ("rice", QuantityUnit.PACK, NutritionValue(Decimal(300), Decimal(5), Decimal(68), None)),
    ):
        add.execute(
            NewFood(
                food_id,
                food_id,
                Decimal(100) if unit is QuantityUnit.GRAM else Decimal(1),
                unit,
                values,
                NutritionSourceType.NUTRITION_LABEL,
                Accuracy.EXACT,
                "synthetic",
            )
        )
    meals = SqliteMealRepository(database)
    LogMeal(meals, foods).execute(
        DAY, MealType.BREAKFAST, (MealEntryItem("chicken", Decimal(200), QuantityUnit.GRAM),), timezone=KST
    )
    LogMeal(meals, foods).execute(
        DAY,
        MealType.LUNCH,
        (
            MealEntryItem("chicken", Decimal("150.5"), QuantityUnit.GRAM),
            MealEntryItem("rice", Decimal(1), QuantityUnit.PACK),
        ),
        timezone=KST,
    )
    return database


def _table_digest(database: Path) -> list[Any]:
    connection = sqlite3.connect(database)
    try:
        return [
            connection.execute(f"SELECT * FROM {table} ORDER BY 1, 2").fetchall()
            for table in ("nutrition_meals", "nutrition_meal_items", "nutrition_facts", "nutrition_food_profiles")
        ]
    finally:
        connection.close()


def test_status_compares_logged_meals_with_stored_targets(database: Path, store: JsonNutritionTargetRepository) -> None:
    store.save(NutritionTargets(protein_g=PROTEIN_RANGE, fat_g=FAT_EXACT, calories_kcal=ExactTarget(Decimal(2400))))

    status = ShowDailyNutritionStatus(SqliteMealRepository(database), store).execute(DAY, KST, timezone_name="+09:00")

    assert [meal.meal.meal_id for meal in status.intake.meals] == ["2026-10-02-breakfast-1", "2026-10-02-lunch-1"]
    by_nutrient = {entry.status.nutrient: entry for entry in status.nutrients}
    protein = by_nutrient[NutrientField.PROTEIN_G].status
    # 200 g + 150.5 g at 18 g/100 g, plus 5 g from rice.
    assert protein.consumed == Decimal("68.090")
    assert protein.status is TargetStatus.BELOW_RANGE
    assert protein.remaining == Decimal("101.910")
    fat = by_nutrient[NutrientField.FAT_G]
    assert fat.status.status is TargetStatus.INDETERMINATE
    assert fat.status.known_subtotal == Decimal("10.515")
    assert fat.missing_items == (MissingItem("2026-10-02-lunch-1", 2, "rice", "rice"),)
    assert by_nutrient[NutrientField.PROTEIN_G].missing_items == ()
    assert by_nutrient[NutrientField.CARBOHYDRATE_G].status.status is TargetStatus.NO_TARGET


def test_changing_targets_never_rewrites_logged_meals(database: Path, store: JsonNutritionTargetRepository) -> None:
    before = _table_digest(database)
    use_case = ShowDailyNutritionStatus(SqliteMealRepository(database), store)
    first = use_case.execute(DAY, KST, timezone_name="+09:00")

    SetNutritionTarget(store).execute(NutrientField.PROTEIN_G, PROTEIN_RANGE)
    SetNutritionTarget(store).execute(NutrientField.PROTEIN_G, ExactTarget(Decimal(60)))
    second = use_case.execute(DAY, KST, timezone_name="+09:00")

    assert _table_digest(database) == before
    assert first.intake == second.intake
    protein = next(entry.status for entry in second.nutrients if entry.status.nutrient is NutrientField.PROTEIN_G)
    assert protein.status is TargetStatus.ABOVE_TARGET
    assert protein.excess == Decimal("8.090")


def test_status_for_a_day_without_meals(database: Path, store: JsonNutritionTargetRepository) -> None:
    store.save(NutritionTargets(protein_g=PROTEIN_RANGE))

    status = ShowDailyNutritionStatus(SqliteMealRepository(database), store).execute(
        date(2026, 10, 3), KST, timezone_name="+09:00"
    )

    assert status.intake.meals == ()
    statuses = {entry.status.nutrient: entry.status.status for entry in status.nutrients}
    assert statuses[NutrientField.PROTEIN_G] is TargetStatus.NO_INTAKE_LOGGED
    assert statuses[NutrientField.FAT_G] is TargetStatus.NO_TARGET
