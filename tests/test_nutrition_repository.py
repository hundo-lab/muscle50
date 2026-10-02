from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from muscle50.domain.nutrition import (
    Accuracy,
    FoodNutritionProfile,
    Meal,
    MealItem,
    MealType,
    NutrientField,
    NutritionFact,
    NutritionProvenance,
    NutritionRange,
    NutritionSourceType,
    NutritionValue,
    QuantityUnit,
)
from muscle50.infrastructure.sqlite.nutrition_repository import SqliteFoodNutritionRepository, SqliteMealRepository

_DEFAULT_CREATED_AT = datetime.fromisoformat("2026-02-03T08:16:00+09:00")


def _provenance(
    source_type: NutritionSourceType = NutritionSourceType.NUTRITION_LABEL,
    accuracy: Accuracy = Accuracy.EXACT,
    *,
    created_at: datetime = _DEFAULT_CREATED_AT,
    source_reference: str = "synthetic-label://recovery-bar-v1",
    confidence: str | None = "1",
    parser_version: str | None = "synthetic-parser-v1",
    model_version: str | None = "synthetic-model-v1",
) -> NutritionProvenance:
    return NutritionProvenance(
        source_type=source_type,
        accuracy=accuracy,
        source_reference=source_reference,
        created_at=created_at,
        confidence=Decimal(confidence) if confidence is not None else None,
        parser_version=parser_version,
        model_version=model_version,
    )


def _fact(
    fact_id: str = "fact-1",
    *,
    calories_kcal: str = "123.4",
    protein_g: str = "20.5",
    carbohydrate_g: str = "8.25",
    fat_g: str = "1.75",
    basis_quantity: str = "1",
    basis_unit: QuantityUnit = QuantityUnit.PACK,
    provenance: NutritionProvenance | None = None,
    value_range: NutritionRange | None = None,
    supersedes_fact_id: str | None = None,
) -> NutritionFact:
    return NutritionFact(
        fact_id=fact_id,
        values=NutritionValue(
            calories_kcal=Decimal(calories_kcal),
            protein_g=Decimal(protein_g),
            carbohydrate_g=Decimal(carbohydrate_g),
            fat_g=Decimal(fat_g),
        ),
        basis_quantity=Decimal(basis_quantity),
        basis_unit=basis_unit,
        provenance=provenance if provenance is not None else _provenance(),
        value_range=value_range,
        supersedes_fact_id=supersedes_fact_id,
    )


def _meal_repo(tmp_path: Path) -> SqliteMealRepository:
    repository = SqliteMealRepository(tmp_path / "nutrition.db")
    repository.migrate()
    # _simple_meal's item references this profile_id; the schema enforces the foreign key.
    food_repository = SqliteFoodNutritionRepository(tmp_path / "nutrition.db")
    food_repository.migrate()
    food_repository.save(
        FoodNutritionProfile(profile_id="profile-synthetic-recovery-bar", name="Recovery Bar", facts=())
    )
    return repository


def _food_repo(tmp_path: Path) -> SqliteFoodNutritionRepository:
    repository = SqliteFoodNutritionRepository(tmp_path / "nutrition.db")
    repository.migrate()
    return repository


def _simple_meal(meal_id: str = "meal-1", *, facts: tuple[NutritionFact, ...] = ()) -> Meal:
    return Meal(
        meal_id=meal_id,
        eaten_at=datetime.fromisoformat("2026-02-03T08:15:00+09:00"),
        meal_type=MealType.BREAKFAST,
        original_text="two recovery bars and one mystery side",
        parser_version="synthetic-parser-v1",
        model_version="synthetic-model-v1",
        notes="test meal",
        items=(
            MealItem(
                meal_id=meal_id,
                sequence=1,
                food_name="Synthetic Recovery Bar",
                food_profile_id="profile-synthetic-recovery-bar",
                quantity=Decimal("2"),
                quantity_unit=QuantityUnit.PACK,
                serving_description="2 packs",
                nutrition_facts=facts,
            ),
            MealItem(
                meal_id=meal_id,
                sequence=2,
                food_name="Synthetic Mystery Side",
                quantity=None,
                quantity_unit=None,
                serving_description="one unspecified portion",
            ),
        ),
    )


def test_meal_round_trips_with_items_and_facts_without_decimal_loss(tmp_path: Path) -> None:
    repository = _meal_repo(tmp_path)
    meal = _simple_meal(facts=(_fact(),))

    repository.save(meal)
    loaded = repository.get("meal-1")

    assert loaded is not None
    assert loaded.meal_id == meal.meal_id
    assert loaded.eaten_at == meal.eaten_at
    assert loaded.eaten_at.utcoffset() == meal.eaten_at.utcoffset()
    assert loaded.notes == meal.notes
    assert loaded.parser_version == meal.parser_version
    assert loaded.model_version == meal.model_version
    assert len(loaded.items) == 2
    assert loaded.items[0].food_profile_id == "profile-synthetic-recovery-bar"

    fact = loaded.items[0].nutrition_facts[0]
    assert fact.values.carbohydrate_g == Decimal("8.25")
    assert fact.values.calories_kcal == Decimal("123.4")
    assert fact.values.protein_g == Decimal("20.5")
    assert fact.values.fat_g == Decimal("1.75")
    assert fact.provenance.confidence == Decimal("1")
    assert fact.provenance.parser_version == "synthetic-parser-v1"
    assert fact.provenance.model_version == "synthetic-model-v1"
    assert fact.provenance.created_at == meal.items[0].nutrition_facts[0].provenance.created_at
    assert fact.value_range is None


def test_nutrition_fact_value_range_round_trips_exactly_per_nutrient(tmp_path: Path) -> None:
    repository = _meal_repo(tmp_path)
    # Every min/max is distinct across nutrients so a pairwise column transposition in the
    # 8 min_*/max_* insert positions would be detectable rather than silently swapping bounds.
    full_range = NutritionRange(
        minimum=NutritionValue(
            calories_kcal=Decimal("120"), protein_g=Decimal("20"), carbohydrate_g=Decimal("8"), fat_g=Decimal("1.5")
        ),
        maximum=NutritionValue(
            calories_kcal=Decimal("130"), protein_g=Decimal("21"), carbohydrate_g=Decimal("8.5"), fat_g=Decimal("2")
        ),
    )
    estimated = _fact(
        provenance=_provenance(
            source_type=NutritionSourceType.VISUAL_ESTIMATE,
            accuracy=Accuracy.ESTIMATED,
            source_reference="synthetic-vision://estimate-1",
        ),
        value_range=full_range,
    )
    meal = _simple_meal(facts=(estimated,))

    repository.save(meal)
    loaded = repository.get("meal-1")

    assert loaded is not None
    fact = loaded.items[0].nutrition_facts[0]
    assert fact.value_range is not None
    assert fact.value_range.minimum.calories_kcal == Decimal("120")
    assert fact.value_range.maximum.calories_kcal == Decimal("130")
    assert fact.value_range.minimum.protein_g == Decimal("20")
    assert fact.value_range.maximum.protein_g == Decimal("21")
    assert fact.value_range.minimum.carbohydrate_g == Decimal("8")
    assert fact.value_range.maximum.carbohydrate_g == Decimal("8.5")
    assert fact.value_range.minimum.fat_g == Decimal("1.5")
    assert fact.value_range.maximum.fat_g == Decimal("2")


def test_nutrition_fact_partial_value_range_omits_nutrients_without_bounds(tmp_path: Path) -> None:
    repository = _meal_repo(tmp_path)
    partial_range = NutritionRange(
        minimum=NutritionValue(calories_kcal=Decimal("120"), protein_g=Decimal("20")),
        maximum=NutritionValue(calories_kcal=Decimal("130"), protein_g=Decimal("21")),
    )
    estimated = _fact(
        provenance=_provenance(
            source_type=NutritionSourceType.VISUAL_ESTIMATE,
            accuracy=Accuracy.ESTIMATED,
            source_reference="synthetic-vision://estimate-2",
        ),
        value_range=partial_range,
    )
    meal = _simple_meal(facts=(estimated,))

    repository.save(meal)
    loaded = repository.get("meal-1")

    assert loaded is not None
    fact = loaded.items[0].nutrition_facts[0]
    assert fact.value_range is not None
    assert fact.value_range.bounds(NutrientField.CALORIES_KCAL) == (Decimal("120"), Decimal("130"))
    assert fact.value_range.bounds(NutrientField.PROTEIN_G) == (Decimal("20"), Decimal("21"))
    assert fact.value_range.bounds(NutrientField.CARBOHYDRATE_G) is None
    assert fact.value_range.bounds(NutrientField.FAT_G) is None


def test_save_persists_facts_supplied_in_reverse_supersession_order(tmp_path: Path) -> None:
    repository = _meal_repo(tmp_path)
    original = _fact("fact-1")
    correction = _fact(
        "fact-2",
        calories_kcal="130",
        provenance=_provenance(
            source_type=NutritionSourceType.USER_PROVIDED,
            created_at=datetime.fromisoformat("2026-02-03T09:00:00+09:00"),
            source_reference="user://correction",
        ),
        supersedes_fact_id="fact-1",
    )
    # The domain does not require supersedes_fact_id targets to appear earlier in the
    # tuple; the append-only trigger does require the referenced row to already exist,
    # so the repository must resolve this ordering itself.
    meal = _simple_meal(facts=(correction, original))

    repository.save(meal)
    loaded = repository.get("meal-1")

    assert loaded is not None
    assert {fact.fact_id for fact in loaded.items[0].nutrition_facts} == {"fact-1", "fact-2"}
    preferred = loaded.items[0].preferred_fact()
    assert preferred is not None
    assert preferred.fact_id == "fact-2"


def test_meal_item_without_quantity_or_unit_round_trips(tmp_path: Path) -> None:
    repository = _meal_repo(tmp_path)
    meal = _simple_meal()

    repository.save(meal)
    loaded = repository.get("meal-1")

    assert loaded is not None
    side = loaded.items[1]
    assert side.quantity is None
    assert side.quantity_unit is None
    assert side.food_profile_id is None
    assert side.nutrition_facts == ()


def test_append_nutrition_fact_supersession_wins_selection_and_keeps_history(tmp_path: Path) -> None:
    repository = _meal_repo(tmp_path)
    meal = _simple_meal(facts=(_fact("fact-1"),))
    repository.save(meal)

    correction = _fact(
        "fact-2",
        calories_kcal="130",
        protein_g="21",
        carbohydrate_g="9",
        fat_g="2",
        provenance=_provenance(
            source_type=NutritionSourceType.USER_PROVIDED,
            created_at=datetime.fromisoformat("2026-02-03T09:00:00+09:00"),
            source_reference="user://correction",
        ),
        supersedes_fact_id="fact-1",
    )

    updated = repository.append_nutrition_fact("meal-1", 1, correction)

    facts = updated.items[0].nutrition_facts
    assert {fact.fact_id for fact in facts} == {"fact-1", "fact-2"}
    preferred = updated.items[0].preferred_fact()
    assert preferred is not None
    assert preferred.fact_id == "fact-2"

    reloaded = repository.get("meal-1")
    assert reloaded is not None
    assert {fact.fact_id for fact in reloaded.items[0].nutrition_facts} == {"fact-1", "fact-2"}


def test_append_nutrition_fact_rejects_supersession_with_different_basis_unit(tmp_path: Path) -> None:
    repository = _meal_repo(tmp_path)
    repository.save(_simple_meal(facts=(_fact("fact-1"),)))

    wrong_unit = _fact("fact-2", basis_unit=QuantityUnit.GRAM, supersedes_fact_id="fact-1")

    with pytest.raises(sqlite3.IntegrityError, match="same owner and basis unit"):
        repository.append_nutrition_fact("meal-1", 1, wrong_unit)

    reloaded = repository.get("meal-1")
    assert reloaded is not None
    assert [fact.fact_id for fact in reloaded.items[0].nutrition_facts] == ["fact-1"]


def test_append_nutrition_fact_rejects_cross_owner_supersession(tmp_path: Path) -> None:
    database_path = tmp_path / "nutrition.db"
    meal_repository = _meal_repo(tmp_path)
    meal_repository.save(_simple_meal(facts=(_fact("meal-fact"),)))
    food_repository = SqliteFoodNutritionRepository(database_path)
    food_repository.migrate()
    food_repository.save(FoodNutritionProfile(profile_id="profile-other", name="Other Product", facts=()))
    cross_owner = _fact("profile-fact", supersedes_fact_id="meal-fact")

    with pytest.raises(sqlite3.IntegrityError, match="same owner and basis unit"):
        food_repository.append_nutrition_fact("profile-other", cross_owner)

    profile = food_repository.get("profile-other")
    assert profile is not None
    assert profile.facts == ()


def test_nutrition_facts_table_is_append_only(tmp_path: Path) -> None:
    repository = _meal_repo(tmp_path)
    meal = _simple_meal(facts=(_fact(),))
    repository.save(meal)

    connection = sqlite3.connect(tmp_path / "nutrition.db")
    try:
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            connection.execute("UPDATE nutrition_facts SET calories_kcal = '999' WHERE fact_id = 'fact-1'")
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            connection.execute("DELETE FROM nutrition_facts WHERE fact_id = 'fact-1'")
    finally:
        connection.close()


def test_cascaded_delete_is_blocked_and_preserves_fact_history(tmp_path: Path) -> None:
    repository = _meal_repo(tmp_path)
    meal = _simple_meal(facts=(_fact(),))
    repository.save(meal)

    connection = sqlite3.connect(tmp_path / "nutrition.db")
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        # nutrition_meals -> nutrition_meal_items cascades, but nutrition_meal_items ->
        # nutrition_facts is ON DELETE RESTRICT, so the cascade must abort the whole delete.
        with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY constraint failed"):
            connection.execute("DELETE FROM nutrition_meals WHERE meal_id = 'meal-1'")
        with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY constraint failed"):
            connection.execute("DELETE FROM nutrition_meal_items WHERE meal_id = 'meal-1' AND item_sequence = 1")
        connection.rollback()
    finally:
        connection.close()

    reloaded = repository.get("meal-1")
    assert reloaded is not None
    assert {fact.fact_id for fact in reloaded.items[0].nutrition_facts} == {"fact-1"}


def test_load_meal_orders_facts_chronologically_across_differing_utc_offsets(tmp_path: Path) -> None:
    repository = _meal_repo(tmp_path)
    # f1 is truly earlier (03:00Z) than f2 (04:00Z), but f2's raw ISO text sorts before f1's
    # raw ISO text ("...T04:00:00+00:00" < "...T12:00:00+09:00"), so ORDER BY created_at as
    # SQL text would (and did) return them reversed.
    f1 = _fact(
        "f1",
        provenance=_provenance(created_at=datetime.fromisoformat("2026-03-01T12:00:00+09:00")),
    )
    f2 = _fact(
        "f2",
        calories_kcal="200",
        provenance=_provenance(
            created_at=datetime.fromisoformat("2026-03-01T04:00:00+00:00"),
            source_reference="synthetic-label://recovery-bar-v2",
        ),
    )
    meal = _simple_meal(facts=(f1, f2))
    repository.save(meal)

    loaded = repository.get("meal-1")

    assert loaded is not None
    assert [fact.fact_id for fact in loaded.items[0].nutrition_facts] == ["f1", "f2"]


def test_get_unknown_meal_id_returns_none(tmp_path: Path) -> None:
    repository = _meal_repo(tmp_path)

    assert repository.get("does-not-exist") is None


def test_save_rejects_resaving_an_existing_meal_id(tmp_path: Path) -> None:
    repository = _meal_repo(tmp_path)
    meal = _simple_meal()
    repository.save(meal)

    with pytest.raises(ValueError, match="already exists"):
        repository.save(meal)


def test_list_eaten_between_is_correct_across_differing_utc_offsets(tmp_path: Path) -> None:
    repository = _meal_repo(tmp_path)

    # Naive-string-comparison trap 1 (ordering inversion): meal_a's raw ISO text starts with
    # hour "23" and meal_b's with hour "10", so raw lexicographic order puts meal_b first.
    # In true UTC time meal_a (14:00Z) precedes meal_b (15:00Z).
    meal_a = Meal(
        meal_id="meal-a",
        eaten_at=datetime.fromisoformat("2026-02-03T23:00:00+09:00"),  # 2026-02-03T14:00:00 UTC
        meal_type=MealType.SNACK,
        original_text="meal a",
    )
    meal_b = Meal(
        meal_id="meal-b",
        eaten_at=datetime.fromisoformat("2026-02-03T10:00:00-05:00"),  # 2026-02-03T15:00:00 UTC
        meal_type=MealType.SNACK,
        original_text="meal b",
    )
    # Naive-string-comparison trap 2 (membership drop): meal_c's raw offset text sorts past
    # the window's raw upper bound even though it is truly inside the UTC window.
    meal_c = Meal(
        meal_id="meal-c",
        eaten_at=datetime.fromisoformat("2026-02-04T02:00:00+09:00"),  # 2026-02-03T17:00:00 UTC
        meal_type=MealType.SNACK,
        original_text="meal c",
    )
    outside = Meal(
        meal_id="meal-outside",
        eaten_at=datetime.fromisoformat("2026-02-05T00:00:00+00:00"),
        meal_type=MealType.SNACK,
        original_text="meal outside",
    )

    for meal in (meal_a, meal_b, meal_c, outside):
        repository.save(meal)

    results = repository.list_eaten_between(
        datetime.fromisoformat("2026-02-03T00:00:00+00:00"),
        datetime.fromisoformat("2026-02-04T00:00:00+00:00"),
    )

    assert [meal.meal_id for meal in results] == ["meal-a", "meal-b", "meal-c"]


def test_list_eaten_between_rejects_naive_datetimes(tmp_path: Path) -> None:
    repository = _meal_repo(tmp_path)

    with pytest.raises(ValueError, match="timezone-aware"):
        repository.list_eaten_between(datetime(2026, 2, 3), datetime(2026, 2, 4, tzinfo=UTC))


def test_load_profile_orders_facts_chronologically_across_differing_utc_offsets(tmp_path: Path) -> None:
    repository = _food_repo(tmp_path)
    # Same trap as the meal-item path: fact "a" is truly earlier (03:00Z) than fact "b"
    # (04:00Z), but "b"'s raw ISO text sorts first, so ORDER BY created_at as SQL text
    # would (and did) return them reversed. This load path previously had no test.
    fact_a = _fact(
        "a",
        provenance=_provenance(created_at=datetime.fromisoformat("2026-03-01T12:00:00+09:00")),
    )
    fact_b = _fact(
        "b",
        calories_kcal="200",
        provenance=_provenance(
            created_at=datetime.fromisoformat("2026-03-01T04:00:00+00:00"),
            source_reference="synthetic-label://recovery-bar-v2",
        ),
    )
    profile = FoodNutritionProfile(profile_id="profile-1", name="Recovery Bar", facts=(fact_a, fact_b))
    repository.save(profile)

    loaded = repository.get("profile-1")

    assert loaded is not None
    assert [fact.fact_id for fact in loaded.facts] == ["a", "b"]


def test_food_profile_round_trips_with_aliases_search_and_appended_facts(tmp_path: Path) -> None:
    repository = _food_repo(tmp_path)
    profile = FoodNutritionProfile(
        profile_id="profile-1",
        name="Recovery Bar",
        facts=(_fact(),),
        aliases=("recovery bar mini", "rb"),
    )

    repository.save(profile)
    loaded = repository.get("profile-1")

    assert loaded is not None
    assert loaded.name == "Recovery Bar"
    assert set(loaded.aliases) == {"recovery bar mini", "rb"}
    assert loaded.facts[0].values.carbohydrate_g == Decimal("8.25")

    assert [found.profile_id for found in repository.search("recovery bar")] == ["profile-1"]
    assert [found.profile_id for found in repository.search("RB")] == ["profile-1"]
    assert repository.search("unrelated food") == ()

    correction = _fact(
        "fact-2",
        calories_kcal="140",
        provenance=_provenance(
            source_type=NutritionSourceType.USER_PROVIDED,
            created_at=datetime.fromisoformat("2026-02-03T09:00:00+09:00"),
            source_reference="user://correction",
        ),
        supersedes_fact_id="fact-1",
    )
    updated = repository.append_nutrition_fact("profile-1", correction)

    assert {fact.fact_id for fact in updated.facts} == {"fact-1", "fact-2"}
    preferred = updated.preferred_fact(QuantityUnit.PACK)
    assert preferred is not None
    assert preferred.fact_id == "fact-2"


def test_food_profile_get_unknown_id_returns_none(tmp_path: Path) -> None:
    repository = _food_repo(tmp_path)

    assert repository.get("does-not-exist") is None


def test_save_rejects_resaving_an_existing_profile_id(tmp_path: Path) -> None:
    repository = _food_repo(tmp_path)
    profile = FoodNutritionProfile(profile_id="profile-1", name="Recovery Bar", facts=())
    repository.save(profile)

    with pytest.raises(ValueError, match="already exists"):
        repository.save(profile)


def test_search_matches_profile_with_no_aliases_by_name(tmp_path: Path) -> None:
    repository = _food_repo(tmp_path)
    profile = FoodNutritionProfile(profile_id="profile-no-aliases", name="Plain Rice", facts=())
    repository.save(profile)

    assert [found.profile_id for found in repository.search("plain rice")] == ["profile-no-aliases"]


def test_list_all_returns_every_profile_ordered_by_id_with_facts(tmp_path: Path) -> None:
    repository = _food_repo(tmp_path)
    assert repository.list_all() == ()
    repository.save(FoodNutritionProfile(profile_id="b-food", name="바나나", facts=(_fact("fact-b"),)))
    repository.save(FoodNutritionProfile(profile_id="a-food", name="Apple", facts=(), aliases=("사과",)))

    profiles = repository.list_all()

    assert [profile.profile_id for profile in profiles] == ["a-food", "b-food"]
    assert profiles[0].aliases == ("사과",)
    assert profiles[1].facts == (_fact("fact-b"),)
