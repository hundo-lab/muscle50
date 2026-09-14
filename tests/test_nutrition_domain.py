from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal, localcontext

import pytest

from muscle50.domain.nutrition import (
    Accuracy,
    Meal,
    MealItem,
    MealItemReference,
    MealType,
    NutrientField,
    NutritionFact,
    NutritionProvenance,
    NutritionRange,
    NutritionSourceType,
    NutritionValue,
    QuantityUnit,
    aggregate_day,
    aggregate_meal,
)

CREATED_AT = datetime(2026, 2, 3, 0, 0, tzinfo=UTC)


def _provenance(
    source_type: NutritionSourceType,
    accuracy: Accuracy,
    *,
    confidence: str | None = None,
    minute: int = 0,
) -> NutritionProvenance:
    return NutritionProvenance(
        source_type=source_type,
        accuracy=accuracy,
        confidence=Decimal(confidence) if confidence is not None else None,
        source_reference=f"synthetic://{source_type.value}",
        parser_version="fixture-parser-v1" if accuracy is Accuracy.ESTIMATED else None,
        model_version="fixture-model-v1" if accuracy is Accuracy.ESTIMATED else None,
        created_at=CREATED_AT + timedelta(minutes=minute),
    )


def _fact(
    fact_id: str,
    values: NutritionValue,
    *,
    source_type: NutritionSourceType = NutritionSourceType.NUTRITION_LABEL,
    accuracy: Accuracy = Accuracy.EXACT,
    basis_quantity: str = "1",
    basis_unit: QuantityUnit = QuantityUnit.PACK,
    value_range: NutritionRange | None = None,
    supersedes: str | None = None,
    minute: int = 0,
) -> NutritionFact:
    return NutritionFact(
        fact_id=fact_id,
        values=values,
        basis_quantity=Decimal(basis_quantity),
        basis_unit=basis_unit,
        provenance=_provenance(source_type, accuracy, confidence="0.8", minute=minute),
        value_range=value_range,
        supersedes_fact_id=supersedes,
    )


def _item(
    sequence: int,
    facts: tuple[NutritionFact, ...],
    *,
    meal_id: str = "meal-synthetic",
    quantity: str | None = "1",
    unit: QuantityUnit | None = QuantityUnit.PACK,
) -> MealItem:
    return MealItem(
        meal_id=meal_id,
        sequence=sequence,
        food_name=f"Synthetic Food {sequence}",
        quantity=Decimal(quantity) if quantity is not None else None,
        quantity_unit=unit,
        serving_description=f"synthetic serving {sequence}",
        nutrition_facts=facts,
    )


def _meal(*items: MealItem, meal_id: str = "meal-synthetic", eaten_at: datetime | None = None) -> Meal:
    return Meal(
        meal_id=meal_id,
        eaten_at=eaten_at or datetime(2026, 2, 3, 8, 0, tzinfo=timezone(timedelta(hours=9))),
        meal_type=MealType.BREAKFAST,
        original_text="Synthetic meal fixture",
        items=items,
    )


def test_label_values_scale_with_decimal_arithmetic_for_lifestyle_units() -> None:
    fact = _fact(
        "label",
        NutritionValue(Decimal("123.4"), Decimal("20.5"), Decimal("8.25"), Decimal("1.75")),
    )

    calculated = fact.calculate(Decimal("2"), QuantityUnit.PACK)

    assert calculated.values == NutritionValue(
        calories_kcal=Decimal("246.8"),
        protein_g=Decimal("41.0"),
        carbohydrate_g=Decimal("16.50"),
        fat_g=Decimal("3.50"),
    )
    calories = calculated.get(NutrientField.CALORIES_KCAL)
    assert calories is not None
    assert calories.provenance.accuracy is Accuracy.EXACT


def test_unknown_nutrients_propagate_in_direct_arithmetic() -> None:
    left = NutritionValue(calories_kcal=Decimal("100"), protein_g=None)
    right = NutritionValue(calories_kcal=Decimal("50"), protein_g=Decimal("10"))

    result = left.plus(right)

    assert result.calories_kcal == Decimal("150")
    assert result.protein_g is None


def test_source_priority_prefers_label_over_user_product_database_and_estimates() -> None:
    values = NutritionValue(calories_kcal=Decimal("1"))
    facts = tuple(
        _fact(
            source.value,
            values,
            source_type=source,
            accuracy=Accuracy.ESTIMATED
            if source in {NutritionSourceType.VISUAL_ESTIMATE, NutritionSourceType.LANGUAGE_ESTIMATE}
            else Accuracy.EXACT,
        )
        for source in NutritionSourceType
    )

    selected = _item(1, facts).preferred_fact()

    assert selected is not None
    assert selected.provenance.source_type is NutritionSourceType.NUTRITION_LABEL


def test_superseding_fact_replaces_old_fact_without_removing_history() -> None:
    old = _fact("old-label", NutritionValue(calories_kcal=Decimal("100")))
    corrected = _fact(
        "corrected-label",
        NutritionValue(calories_kcal=Decimal("110")),
        supersedes="old-label",
        minute=1,
    )
    item = _item(1, (old, corrected))

    selected = item.preferred_fact()

    assert len(item.nutrition_facts) == 2
    assert selected is corrected


def test_partial_correction_supersedes_only_fields_it_provides() -> None:
    old = _fact(
        "old-label",
        NutritionValue(calories_kcal=Decimal("100"), protein_g=Decimal("20")),
    )
    corrected = _fact(
        "corrected-label",
        NutritionValue(calories_kcal=Decimal("110")),
        supersedes="old-label",
        minute=1,
    )
    calculated = _item(1, (old, corrected)).calculated_nutrition()

    assert calculated is not None
    calories = calculated.get(NutrientField.CALORIES_KCAL)
    protein = calculated.get(NutrientField.PROTEIN_G)
    assert calories is not None and calories.fact_id == "corrected-label"
    assert protein is not None and protein.fact_id == "old-label"


def test_cyclic_supersession_history_is_rejected() -> None:
    first = _fact("first", NutritionValue(calories_kcal=Decimal("100")), supersedes="second")
    second = _fact("second", NutritionValue(calories_kcal=Decimal("110")), supersedes="first")

    with pytest.raises(ValueError, match="cycle"):
        _item(1, (first, second))


def test_units_are_not_implicitly_converted() -> None:
    per_pack = _fact("per-pack", NutritionValue(calories_kcal=Decimal("100")))
    item = _item(1, (per_pack,), quantity="100", unit=QuantityUnit.GRAM)

    assert item.calculated_nutrition() is None
    with pytest.raises(ValueError, match="cannot convert"):
        per_pack.calculate(Decimal("100"), QuantityUnit.GRAM)


@pytest.mark.parametrize("unit", list(QuantityUnit))
def test_all_supported_units_scale_when_fact_basis_matches(unit: QuantityUnit) -> None:
    fact = _fact(
        f"per-{unit.value}",
        NutritionValue(calories_kcal=Decimal("10")),
        basis_unit=unit,
    )

    calculated = fact.calculate(Decimal("2"), unit)

    assert calculated.values.calories_kcal == Decimal("20")


def test_superseding_fact_must_keep_the_same_basis_unit() -> None:
    per_pack = _fact("per-pack", NutritionValue(calories_kcal=Decimal("100")))
    per_gram = _fact(
        "per-gram",
        NutritionValue(calories_kcal=Decimal("1")),
        basis_unit=QuantityUnit.GRAM,
        supersedes="per-pack",
    )

    with pytest.raises(ValueError, match="same basis unit"):
        _item(1, (per_pack, per_gram))


def test_field_level_source_priority_fills_macros_without_overriding_label_calories() -> None:
    label = _fact("label", NutritionValue(calories_kcal=Decimal("100")))
    database = _fact(
        "database",
        NutritionValue(
            calories_kcal=Decimal("120"),
            protein_g=Decimal("20"),
            carbohydrate_g=Decimal("5"),
            fat_g=Decimal("2"),
        ),
        source_type=NutritionSourceType.FOOD_DATABASE,
        accuracy=Accuracy.ESTIMATED,
    )

    calculated = _item(1, (database, label)).calculated_nutrition()

    assert calculated is not None
    assert calculated.values == NutritionValue(Decimal("100"), Decimal("20"), Decimal("5"), Decimal("2"))
    calories = calculated.get(NutrientField.CALORIES_KCAL)
    protein = calculated.get(NutrientField.PROTEIN_G)
    assert calories is not None and calories.fact_id == "label"
    assert protein is not None and protein.fact_id == "database"

    aggregate = aggregate_meal(_meal(_item(1, (database, label)))).nutrition
    assert aggregate.totals == calculated.values
    assert aggregate.estimated_fields == frozenset(
        {NutrientField.PROTEIN_G, NutrientField.CARBOHYDRATE_G, NutrientField.FAT_G}
    )


def test_calculation_is_independent_of_ambient_decimal_context() -> None:
    fact = _fact(
        "per-three",
        NutritionValue(calories_kcal=Decimal("1")),
        basis_quantity="3",
    )
    with localcontext() as context:
        context.prec = 6
        low_precision = fact.calculate(Decimal("1"), QuantityUnit.PACK).values.calories_kcal
    with localcontext() as context:
        context.prec = 50
        high_precision = fact.calculate(Decimal("1"), QuantityUnit.PACK).values.calories_kcal

    assert low_precision == high_precision == Decimal("0.3333333333333333333333333333")


def test_aggregation_is_independent_of_ambient_decimal_context() -> None:
    large = _fact("large", NutritionValue(calories_kcal=Decimal("123456")))
    small = _fact("small", NutritionValue(calories_kcal=Decimal("0.1")))
    meal = _meal(_item(1, (large,)), _item(2, (small,)))

    with localcontext() as context:
        context.prec = 6
        low_precision = aggregate_meal(meal).nutrition.totals.calories_kcal
    with localcontext() as context:
        context.prec = 50
        high_precision = aggregate_meal(meal).nutrition.totals.calories_kcal

    assert low_precision == high_precision == Decimal("123456.1")


def test_meal_aggregation_preserves_estimate_range_and_flags() -> None:
    exact = _fact(
        "exact",
        NutritionValue(Decimal("200"), Decimal("40"), Decimal("10"), Decimal("4")),
    )
    estimated = _fact(
        "estimated",
        NutritionValue(Decimal("75"), Decimal("5"), Decimal("15"), Decimal("2")),
        source_type=NutritionSourceType.LANGUAGE_ESTIMATE,
        accuracy=Accuracy.ESTIMATED,
        basis_unit=QuantityUnit.PIECE,
        value_range=NutritionRange(
            NutritionValue(Decimal("60"), Decimal("4"), Decimal("12"), Decimal("1")),
            NutritionValue(Decimal("90"), Decimal("6"), Decimal("18"), Decimal("3")),
        ),
    )
    meal = _meal(
        _item(1, (exact,)),
        _item(2, (estimated,), quantity="2", unit=QuantityUnit.PIECE),
    )

    result = aggregate_meal(meal).nutrition

    assert result.totals == NutritionValue(Decimal("350"), Decimal("50"), Decimal("40"), Decimal("8"))
    assert result.known_subtotals == result.totals
    assert result.value_range == NutritionRange(
        NutritionValue(Decimal("320"), Decimal("48"), Decimal("34"), Decimal("6")),
        NutritionValue(Decimal("380"), Decimal("52"), Decimal("46"), Decimal("10")),
    )
    assert result.incomplete_fields == frozenset()
    assert result.estimated_fields == frozenset(NutrientField)


def test_partial_and_uncalculated_items_never_become_zero_or_exact_totals() -> None:
    partial = _fact("partial", NutritionValue(calories_kcal=Decimal("80"), protein_g=None))
    meal = _meal(
        _item(1, (partial,)),
        _item(2, (), quantity=None, unit=None),
    )

    result = aggregate_meal(meal).nutrition

    assert result.totals.calories_kcal is None
    assert result.totals.protein_g is None
    assert result.known_subtotals.calories_kcal == Decimal("80")
    assert result.value_range is None
    assert result.incomplete_fields == frozenset(NutrientField)
    assert result.uncalculated_items == (MealItemReference("meal-synthetic", 2),)


def test_empty_meal_reports_unknown_not_zero() -> None:
    result = aggregate_meal(_meal()).nutrition

    assert result.totals == NutritionValue()
    assert result.known_subtotals == NutritionValue()
    assert result.incomplete_fields == frozenset(NutrientField)
    assert result.item_count == 0


def test_range_without_point_value_is_retained_without_inventing_a_midpoint() -> None:
    ranged = _fact(
        "range-only",
        NutritionValue(),
        source_type=NutritionSourceType.VISUAL_ESTIMATE,
        accuracy=Accuracy.ESTIMATED,
        value_range=NutritionRange(
            NutritionValue(calories_kcal=Decimal("300")),
            NutritionValue(calories_kcal=Decimal("500")),
        ),
    )

    result = aggregate_meal(_meal(_item(1, (ranged,)))).nutrition

    assert result.totals.calories_kcal is None
    assert result.value_range is not None
    assert result.value_range.minimum.calories_kcal == Decimal("300")
    assert NutrientField.CALORIES_KCAL in result.incomplete_fields
    assert NutrientField.CALORIES_KCAL in result.estimated_fields


def test_estimated_point_must_fall_within_its_range() -> None:
    with pytest.raises(ValueError, match="within its estimate range"):
        _fact(
            "bad-range",
            NutritionValue(calories_kcal=Decimal("600")),
            source_type=NutritionSourceType.VISUAL_ESTIMATE,
            accuracy=Accuracy.ESTIMATED,
            value_range=NutritionRange(
                NutritionValue(calories_kcal=Decimal("300")),
                NutritionValue(calories_kcal=Decimal("500")),
            ),
        )


def test_daily_aggregation_uses_explicit_timezone_boundary() -> None:
    fact = _fact("label", NutritionValue(calories_kcal=Decimal("100")))
    first = _meal(
        _item(1, (fact,), meal_id="first"),
        meal_id="first",
        eaten_at=datetime(2026, 2, 2, 23, 30, tzinfo=UTC),
    )
    second = _meal(
        _item(1, (fact,), meal_id="second"),
        meal_id="second",
        eaten_at=datetime(2026, 2, 3, 16, 0, tzinfo=UTC),
    )

    result = aggregate_day(
        (first, second),
        date(2026, 2, 3),
        timezone(timedelta(hours=9)),
        timezone_name="Asia/Seoul",
    )

    assert [meal.meal_id for meal in result.meals] == ["first"]
    assert result.nutrition.totals.calories_kcal == Decimal("100")


@pytest.mark.parametrize(
    "factory",
    [
        lambda: NutritionValue(calories_kcal=Decimal("NaN")),
        lambda: NutritionValue(protein_g=Decimal("-1")),
        lambda: NutritionRange(
            NutritionValue(calories_kcal=Decimal("20")),
            NutritionValue(calories_kcal=Decimal("10")),
        ),
        lambda: NutritionProvenance(
            source_type=NutritionSourceType.LANGUAGE_ESTIMATE,
            accuracy=Accuracy.EXACT,
            source_reference="synthetic://invalid-exact-estimate",
            created_at=CREATED_AT,
        ),
    ],
)
def test_invalid_nutrition_values_are_rejected(factory: Callable[[], object]) -> None:
    with pytest.raises(ValueError):
        factory()
