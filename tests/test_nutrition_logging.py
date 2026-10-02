"""Nutrition Logging MVP use cases over an isolated temporary SQLite database.

All nutrition values here are synthetic test numbers, not real food data.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, date, datetime, time, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from muscle50.application.nutrition_logging import (
    AddFood,
    DailyIntake,
    ListFoods,
    LogMeal,
    MealEntryItem,
    NewFood,
    NutritionLoggingError,
    ShowDailyIntake,
    ShowFood,
    offset_name,
)
from muscle50.domain.nutrition import (
    Accuracy,
    MealType,
    NutrientField,
    NutritionFact,
    NutritionProvenance,
    NutritionSourceType,
    NutritionValue,
    QuantityUnit,
)
from muscle50.infrastructure.sqlite.nutrition_repository import SqliteFoodNutritionRepository, SqliteMealRepository

KST = timezone(timedelta(hours=9))
DAY = date(2026, 10, 2)
CREATED_AT = datetime(2026, 10, 1, 21, 0, tzinfo=KST)


@pytest.fixture
def database(tmp_path: Path) -> Path:
    path = tmp_path / "db" / "muscle50.sqlite3"
    SqliteFoodNutritionRepository(path).migrate()
    return path


@pytest.fixture
def foods(database: Path) -> SqliteFoodNutritionRepository:
    return SqliteFoodNutritionRepository(database)


@pytest.fixture
def meals(database: Path) -> SqliteMealRepository:
    return SqliteMealRepository(database)


def _values(kcal: str | None, protein: str | None, carbs: str | None, fat: str | None) -> NutritionValue:
    def number(text: str | None) -> Decimal | None:
        return Decimal(text) if text is not None else None

    return NutritionValue(number(kcal), number(protein), number(carbs), number(fat))


def _food(
    food_id: str,
    name: str,
    quantity: str,
    unit: QuantityUnit,
    values: NutritionValue,
    *,
    source: NutritionSourceType = NutritionSourceType.NUTRITION_LABEL,
    accuracy: Accuracy = Accuracy.EXACT,
    aliases: tuple[str, ...] = (),
) -> NewFood:
    return NewFood(food_id, name, Decimal(quantity), unit, values, source, accuracy, f"synthetic:{food_id}", aliases)


def _add(foods: SqliteFoodNutritionRepository, food: NewFood) -> None:
    AddFood(foods, clock=lambda: CREATED_AT).execute(food)


def _catalog(foods: SqliteFoodNutritionRepository) -> None:
    """Synthetic breakfast catalog: gram, count, pack and piece based foods."""
    _add(foods, _food("chicken-breast", "닭가슴살", "100", QuantityUnit.GRAM, _values("110", "18", "1", "3")))
    _add(
        foods,
        _food(
            "egg",
            "계란",
            "1",
            QuantityUnit.COUNT,
            _values("70", "6", "0.5", "5"),
            source=NutritionSourceType.USER_PROVIDED,
            accuracy=Accuracy.ESTIMATED,
        ),
    )
    _add(foods, _food("hetbahn", "햇반", "1", QuantityUnit.PACK, _values("300", "5", "68", "1")))
    _add(
        foods,
        _food(
            "banana",
            "바나나",
            "1",
            QuantityUnit.PIECE,
            _values("90", "1", "23", "0.3"),
            source=NutritionSourceType.USER_PROVIDED,
        ),
    )


def _log(
    meals: SqliteMealRepository,
    foods: SqliteFoodNutritionRepository,
    meal_type: MealType,
    *items: tuple[str, str, QuantityUnit],
    day: date = DAY,
    eaten_time: time | None = None,
    additional: bool = False,
) -> str:
    entries = tuple(MealEntryItem(food_id, Decimal(quantity), unit) for food_id, quantity, unit in items)
    intake = LogMeal(meals, foods).execute(
        day, meal_type, entries, timezone=KST, eaten_time=eaten_time, additional=additional
    )
    return intake.meal.meal_id


def _day(meals: SqliteMealRepository, day: date = DAY) -> DailyIntake:
    return ShowDailyIntake(meals).execute(day, KST, timezone_name="+09:00")


def _row_counts(database: Path) -> tuple[int, ...]:
    connection = sqlite3.connect(database)
    try:
        return tuple(
            connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in ("nutrition_food_profiles", "nutrition_meals", "nutrition_meal_items", "nutrition_facts")
        )
    finally:
        connection.close()


# --- food catalog -------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("unit", "quantity"),
    [(QuantityUnit.GRAM, "100"), (QuantityUnit.COUNT, "1"), (QuantityUnit.PACK, "1"), (QuantityUnit.PIECE, "1")],
)
def test_add_food_round_trips_unit_values_source_and_accuracy(
    foods: SqliteFoodNutritionRepository, unit: QuantityUnit, quantity: str
) -> None:
    _add(
        foods,
        _food(
            "food-1",
            "한글 음식",
            quantity,
            unit,
            _values("123.45", "18", "0", "2.5"),
            source=NutritionSourceType.KNOWN_PRODUCT,
            accuracy=Accuracy.ESTIMATED,
            aliases=("별칭",),
        ),
    )

    profile = SqliteFoodNutritionRepository(foods._database_path).get("food-1")  # fresh instance: real reload

    assert profile is not None
    assert profile.name == "한글 음식"
    assert profile.aliases == ("별칭",)
    (fact,) = profile.facts
    assert fact.fact_id == "food:food-1:1"
    assert fact.basis_quantity == Decimal(quantity)
    assert fact.basis_unit is unit
    assert fact.values == _values("123.45", "18", "0", "2.5")
    assert fact.provenance.source_type is NutritionSourceType.KNOWN_PRODUCT
    assert fact.provenance.accuracy is Accuracy.ESTIMATED
    assert fact.provenance.source_reference == "synthetic:food-1"
    assert fact.provenance.created_at == CREATED_AT


def test_unknown_nutrient_is_stored_as_missing_and_zero_stays_zero(foods: SqliteFoodNutritionRepository) -> None:
    _add(foods, _food("rice", "쌀밥", "1", QuantityUnit.PACK, _values("300", "0", "68", None)))

    profile = ShowFood(foods).execute("rice")

    assert profile.facts[0].values.protein_g == Decimal("0")
    assert profile.facts[0].values.fat_g is None


def test_food_without_any_nutrient_value_is_rejected(database: Path, foods: SqliteFoodNutritionRepository) -> None:
    with pytest.raises(NutritionLoggingError, match="at least one"):
        _add(foods, _food("empty", "빈 음식", "1", QuantityUnit.PIECE, _values(None, None, None, None)))
    assert _row_counts(database) == (0, 0, 0, 0)


def test_estimate_sources_cannot_enter_the_catalog(foods: SqliteFoodNutritionRepository) -> None:
    with pytest.raises(NutritionLoggingError, match="language_estimate"):
        _add(
            foods,
            _food(
                "guess",
                "추정",
                "1",
                QuantityUnit.PIECE,
                _values("100", "1", "1", "1"),
                source=NutritionSourceType.LANGUAGE_ESTIMATE,
                accuracy=Accuracy.ESTIMATED,
            ),
        )


@pytest.mark.parametrize("food_id", ["", "two words", "a=b", "-leading"])
def test_food_id_must_be_one_safe_token(foods: SqliteFoodNutritionRepository, food_id: str) -> None:
    with pytest.raises(NutritionLoggingError, match="food id"):
        _add(foods, _food(food_id, "이름", "1", QuantityUnit.PIECE, _values("1", "1", "1", "1")))


def test_korean_food_id_is_allowed(foods: SqliteFoodNutritionRepository) -> None:
    _add(foods, _food("닭가슴살", "닭가슴살", "100", QuantityUnit.GRAM, _values("110", "18", "1", "3")))
    assert ShowFood(foods).execute("닭가슴살").name == "닭가슴살"


def test_duplicate_food_id_is_rejected_and_original_is_unchanged(
    database: Path, foods: SqliteFoodNutritionRepository
) -> None:
    _add(foods, _food("banana", "바나나", "1", QuantityUnit.PIECE, _values("90", "1", "23", "0.3")))

    with pytest.raises(NutritionLoggingError, match="already exists"):
        _add(foods, _food("banana", "다른 바나나", "1", QuantityUnit.PIECE, _values("1", "1", "1", "1")))

    assert ShowFood(foods).execute("banana").facts[0].values.calories_kcal == Decimal("90")
    assert _row_counts(database) == (1, 0, 0, 1)


@pytest.mark.parametrize(("name", "aliases"), [("바나나", ()), ("BANANA-X", ("Banana",)), ("새 이름", ("바나나",))])
def test_duplicate_name_or_alias_is_rejected(
    foods: SqliteFoodNutritionRepository, name: str, aliases: tuple[str, ...]
) -> None:
    _add(
        foods, _food("banana", "바나나", "1", QuantityUnit.PIECE, _values("90", "1", "23", "0.3"), aliases=("banana",))
    )

    with pytest.raises(NutritionLoggingError, match="already used by food banana"):
        _add(foods, _food("banana-2", name, "1", QuantityUnit.PIECE, _values("1", "1", "1", "1"), aliases=aliases))


def test_list_foods_is_ordered_by_id(foods: SqliteFoodNutritionRepository) -> None:
    _catalog(foods)
    assert [profile.profile_id for profile in ListFoods(foods).execute()] == [
        "banana",
        "chicken-breast",
        "egg",
        "hetbahn",
    ]


def test_show_unknown_food_fails_clearly(foods: SqliteFoodNutritionRepository) -> None:
    with pytest.raises(NutritionLoggingError, match="no food with id 'nope'"):
        ShowFood(foods).execute("nope")


# --- scaling ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("food_id", "quantity", "unit", "expected"),
    [
        ("chicken-breast", "200", QuantityUnit.GRAM, ("220", "36", "2", "6")),
        ("chicken-breast", "150.5", QuantityUnit.GRAM, ("165.55", "27.09", "1.505", "4.515")),
        ("egg", "2", QuantityUnit.COUNT, ("140", "12", "1.0", "10")),
        ("hetbahn", "1", QuantityUnit.PACK, ("300", "5", "68", "1")),
        ("hetbahn", "0.5", QuantityUnit.PACK, ("150", "2.5", "34", "0.5")),
        ("banana", "1.5", QuantityUnit.PIECE, ("135", "1.5", "34.5", "0.45")),
    ],
)
def test_logged_quantity_scales_facts_exactly(
    foods: SqliteFoodNutritionRepository,
    meals: SqliteMealRepository,
    food_id: str,
    quantity: str,
    unit: QuantityUnit,
    expected: tuple[str, str, str, str],
) -> None:
    _catalog(foods)
    _log(meals, foods, MealType.SNACK, (food_id, quantity, unit))

    (item,) = _day(meals).meals[0].items

    assert item.calculated is not None
    assert item.calculated.values == _values(*expected)
    assert item.missing_fields == ()


def test_snapshot_matches_the_profiles_preferred_fact_calculation(
    foods: SqliteFoodNutritionRepository, meals: SqliteMealRepository
) -> None:
    _catalog(foods)
    _log(meals, foods, MealType.LUNCH, ("chicken-breast", "200", QuantityUnit.GRAM))
    profile = ShowFood(foods).execute("chicken-breast")

    (item,) = _day(meals).meals[0].items

    assert item.calculated is not None
    for nutrient in NutrientField:
        fact = profile.preferred_fact(QuantityUnit.GRAM, nutrient)
        assert fact is not None
        expected = fact.calculate(Decimal("200"), QuantityUnit.GRAM).get(nutrient)
        selected = item.calculated.get(nutrient)
        assert selected is not None and expected is not None
        assert selected.value == expected.value
        assert selected.provenance == fact.provenance
    (snapshot,) = item.item.nutrition_facts
    assert snapshot.fact_id == "2026-10-02-lunch-1:1:food:chicken-breast:1"
    assert snapshot.supersedes_fact_id is None


@pytest.mark.parametrize(
    ("food_id", "unit"),
    [
        ("hetbahn", QuantityUnit.GRAM),  # 210 g is not converted to packs
        ("egg", QuantityUnit.GRAM),  # no hidden "1 egg = N g"
        ("chicken-breast", QuantityUnit.PIECE),
        ("banana", QuantityUnit.COUNT),  # piece and count are different units
    ],
)
def test_incompatible_unit_is_rejected_and_nothing_is_saved(
    database: Path,
    foods: SqliteFoodNutritionRepository,
    meals: SqliteMealRepository,
    food_id: str,
    unit: QuantityUnit,
) -> None:
    _catalog(foods)
    before = _row_counts(database)

    with pytest.raises(NutritionLoggingError, match="units are never converted"):
        _log(meals, foods, MealType.BREAKFAST, ("chicken-breast", "100", QuantityUnit.GRAM), (food_id, "210", unit))

    assert _row_counts(database) == before


def test_unknown_food_is_rejected_and_nothing_is_saved(
    database: Path, foods: SqliteFoodNutritionRepository, meals: SqliteMealRepository
) -> None:
    _catalog(foods)
    before = _row_counts(database)

    with pytest.raises(NutritionLoggingError, match="item 2: no food with id 'mystery'"):
        _log(meals, foods, MealType.DINNER, ("egg", "1", QuantityUnit.COUNT), ("mystery", "1", QuantityUnit.PIECE))

    assert _row_counts(database) == before


# --- meals --------------------------------------------------------------------------------


def test_breakfast_acceptance_scenario_persists_items_and_totals(
    database: Path, foods: SqliteFoodNutritionRepository, meals: SqliteMealRepository
) -> None:
    _catalog(foods)
    meal_id = _log(
        meals,
        foods,
        MealType.BREAKFAST,
        ("chicken-breast", "200", QuantityUnit.GRAM),
        ("egg", "2", QuantityUnit.COUNT),
        ("hetbahn", "1", QuantityUnit.PACK),
        ("banana", "1", QuantityUnit.PIECE),
    )

    reloaded = ShowDailyIntake(SqliteMealRepository(database)).execute(DAY, KST, timezone_name="+09:00")

    assert meal_id == "2026-10-02-breakfast-1"
    (breakfast,) = reloaded.meals
    assert [
        (item.item.food_name, item.item.food_profile_id, item.item.quantity, item.item.quantity_unit)
        for item in breakfast.items
    ] == [
        ("닭가슴살", "chicken-breast", Decimal("200"), QuantityUnit.GRAM),
        ("계란", "egg", Decimal("2"), QuantityUnit.COUNT),
        ("햇반", "hetbahn", Decimal("1"), QuantityUnit.PACK),
        ("바나나", "banana", Decimal("1"), QuantityUnit.PIECE),
    ]
    assert breakfast.summary.nutrition.totals == _values("750", "54", "94.0", "17.3")
    assert breakfast.summary.nutrition.incomplete_fields == frozenset()
    assert reloaded.summary.nutrition.totals == _values("750", "54", "94.0", "17.3")
    assert reloaded.summary.nutrition.estimated_fields == frozenset(NutrientField)  # the egg fact is estimated


def test_multiple_meals_on_one_day_are_ordered_and_summed(
    foods: SqliteFoodNutritionRepository, meals: SqliteMealRepository
) -> None:
    _catalog(foods)
    _log(meals, foods, MealType.DINNER, ("chicken-breast", "100", QuantityUnit.GRAM))
    _log(meals, foods, MealType.LUNCH, ("hetbahn", "1", QuantityUnit.PACK))
    _log(meals, foods, MealType.BREAKFAST, ("banana", "1", QuantityUnit.PIECE))
    _log(meals, foods, MealType.SNACK, ("egg", "1", QuantityUnit.COUNT), eaten_time=time(15, 30))

    intake = _day(meals)

    # Untimed meals sort by meal type (not alphabetically: lunch before dinner), timed ones by time.
    assert [meal.meal.meal_type for meal in intake.meals] == [
        MealType.BREAKFAST,
        MealType.LUNCH,
        MealType.DINNER,
        MealType.SNACK,
    ]
    assert intake.summary.nutrition.item_count == 4
    assert intake.summary.nutrition.totals == _values("570", "30", "92.5", "9.3")


def test_day_selection_uses_local_date_boundaries(
    foods: SqliteFoodNutritionRepository, meals: SqliteMealRepository
) -> None:
    _catalog(foods)
    _log(meals, foods, MealType.SNACK, ("banana", "1", QuantityUnit.PIECE), eaten_time=time(23, 59))
    _log(meals, foods, MealType.SNACK, ("egg", "1", QuantityUnit.COUNT), day=DAY + timedelta(days=1))
    _log(
        meals,
        foods,
        MealType.SNACK,
        ("egg", "1", QuantityUnit.COUNT),
        day=DAY - timedelta(days=1),
        eaten_time=time(23, 59),
    )

    intake = _day(meals)

    assert [meal.meal.meal_id for meal in intake.meals] == ["2026-10-02-snack-1"]
    assert intake.meals[0].meal.eaten_at == datetime(2026, 10, 2, 23, 59, tzinfo=KST)


def test_meal_without_time_is_stored_at_local_midnight(
    foods: SqliteFoodNutritionRepository, meals: SqliteMealRepository
) -> None:
    _catalog(foods)
    _log(meals, foods, MealType.BREAKFAST, ("egg", "1", QuantityUnit.COUNT))

    meal = _day(meals).meals[0].meal

    assert meal.eaten_at == datetime(2026, 10, 2, tzinfo=KST)
    assert meal.parser_version is None
    assert meal.original_text == "structured entry breakfast 2026-10-02: egg 1 count"


def test_second_meal_of_the_same_type_needs_additional(
    database: Path, foods: SqliteFoodNutritionRepository, meals: SqliteMealRepository
) -> None:
    _catalog(foods)
    _log(meals, foods, MealType.SNACK, ("egg", "1", QuantityUnit.COUNT))
    before = _row_counts(database)

    with pytest.raises(NutritionLoggingError, match=r"already recorded \(2026-10-02-snack-1\)"):
        _log(meals, foods, MealType.SNACK, ("egg", "1", QuantityUnit.COUNT))
    assert _row_counts(database) == before

    assert _log(meals, foods, MealType.SNACK, ("banana", "1", QuantityUnit.PIECE), additional=True) == (
        "2026-10-02-snack-2"
    )
    assert len(_day(meals).meals) == 2


def test_meal_without_items_is_rejected(foods: SqliteFoodNutritionRepository, meals: SqliteMealRepository) -> None:
    with pytest.raises(NutritionLoggingError, match="at least one item"):
        _log(meals, foods, MealType.LUNCH)


def test_later_catalog_correction_does_not_rewrite_a_logged_meal(
    foods: SqliteFoodNutritionRepository, meals: SqliteMealRepository
) -> None:
    _catalog(foods)
    _log(meals, foods, MealType.BREAKFAST, ("chicken-breast", "200", QuantityUnit.GRAM))
    foods.append_nutrition_fact(
        "chicken-breast",
        NutritionFact(
            fact_id="food:chicken-breast:2",
            values=_values("120", "20", "0", "2"),
            basis_quantity=Decimal("100"),
            basis_unit=QuantityUnit.GRAM,
            provenance=NutritionProvenance(
                NutritionSourceType.NUTRITION_LABEL, Accuracy.EXACT, "synthetic:corrected", CREATED_AT
            ),
            supersedes_fact_id="food:chicken-breast:1",
        ),
    )
    _log(meals, foods, MealType.LUNCH, ("chicken-breast", "200", QuantityUnit.GRAM))

    breakfast, lunch = _day(meals).meals

    assert breakfast.summary.nutrition.totals.protein_g == Decimal("36")
    assert lunch.summary.nutrition.totals.protein_g == Decimal("40")
    assert lunch.items[0].item.nutrition_facts[0].fact_id == "2026-10-02-lunch-1:1:food:chicken-breast:2"


# --- aggregation and missing data ---------------------------------------------------------


def test_missing_nutrient_makes_meal_and_day_incomplete_without_zero_filling(
    foods: SqliteFoodNutritionRepository, meals: SqliteMealRepository
) -> None:
    _catalog(foods)
    _add(foods, _food("rice", "쌀밥", "1", QuantityUnit.PACK, _values("300", "5", "68", None)))
    _log(meals, foods, MealType.LUNCH, ("rice", "1", QuantityUnit.PACK), ("chicken-breast", "100", QuantityUnit.GRAM))
    _log(meals, foods, MealType.DINNER, ("egg", "1", QuantityUnit.COUNT))

    intake = _day(meals)
    lunch, dinner = intake.meals

    rice, chicken = lunch.items
    assert rice.missing_fields == (NutrientField.FAT_G,)
    assert rice.calculated is not None and rice.calculated.get(NutrientField.FAT_G) is None
    assert chicken.missing_fields == ()
    assert lunch.summary.nutrition.totals == _values("410", "23", "69", None)
    assert lunch.summary.nutrition.known_subtotals.fat_g == Decimal("3")
    assert lunch.summary.nutrition.incomplete_fields == frozenset({NutrientField.FAT_G})
    assert dinner.summary.nutrition.incomplete_fields == frozenset()
    assert intake.summary.nutrition.totals.fat_g is None
    assert intake.summary.nutrition.known_subtotals.fat_g == Decimal("8")
    assert intake.summary.nutrition.totals.calories_kcal == Decimal("480")


def test_decimal_totals_are_exact(foods: SqliteFoodNutritionRepository, meals: SqliteMealRepository) -> None:
    _add(foods, _food("drop", "한 방울", "1", QuantityUnit.PIECE, _values("0.1", "0.1", "0.1", "0.1")))
    _log(meals, foods, MealType.SNACK, ("drop", "1", QuantityUnit.PIECE), ("drop", "1", QuantityUnit.PIECE))
    _log(meals, foods, MealType.OTHER, ("drop", "1", QuantityUnit.PIECE))

    totals = _day(meals).summary.nutrition.totals

    assert totals.calories_kcal == Decimal("0.3")  # binary floats would give 0.30000000000000004


def test_day_without_meals_has_no_totals(meals: SqliteMealRepository) -> None:
    intake = _day(meals)

    assert intake.meals == ()
    assert intake.summary.nutrition.item_count == 0
    assert intake.summary.nutrition.totals == NutritionValue()


def test_offset_name_is_built_from_the_utc_offset() -> None:
    assert offset_name(KST, DAY) == "+09:00"
    assert offset_name(timezone(timedelta(hours=-3, minutes=-30)), DAY) == "-03:30"
    assert offset_name(UTC, DAY) == "+00:00"
