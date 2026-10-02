"""Nutrition targets and the target status of a Nutrition Core aggregate (synthetic values only)."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import pytest

from muscle50.domain.nutrition import (
    Accuracy,
    Meal,
    MealItem,
    MealType,
    NutrientField,
    NutritionAggregate,
    NutritionFact,
    NutritionProvenance,
    NutritionSourceType,
    NutritionValue,
    QuantityUnit,
    aggregate_day,
    aggregate_meal,
)
from muscle50.domain.nutrition_targets import (
    ExactTarget,
    NutritionTargetError,
    NutritionTargets,
    RangeTarget,
    TargetKind,
    TargetStatus,
    evaluate_nutrient,
    evaluate_targets,
)

KST = timezone(timedelta(hours=9))
DAY = date(2026, 10, 2)
PROTEIN = NutrientField.PROTEIN_G
FAT = NutrientField.FAT_G


def _item(
    meal_id: str,
    sequence: int,
    *,
    kcal: str | None = "100",
    protein: str | None = "10",
    carbs: str | None = "10",
    fat: str | None = "1",
    accuracy: Accuracy = Accuracy.EXACT,
) -> MealItem:
    def value(text: str | None) -> Decimal | None:
        return Decimal(text) if text is not None else None

    fact = NutritionFact(
        fact_id=f"{meal_id}:{sequence}:fact",
        values=NutritionValue(value(kcal), value(protein), value(carbs), value(fat)),
        basis_quantity=Decimal(1),
        basis_unit=QuantityUnit.COUNT,
        provenance=NutritionProvenance(
            NutritionSourceType.USER_PROVIDED, accuracy, "synthetic", datetime(2026, 10, 1, tzinfo=KST)
        ),
    )
    return MealItem(meal_id, sequence, f"food {sequence}", Decimal(1), QuantityUnit.COUNT, nutrition_facts=(fact,))


def _meal(meal_id: str, *items: dict[str, Any], hour: int = 8) -> Meal:
    return Meal(
        meal_id=meal_id,
        eaten_at=datetime(2026, 10, 2, hour, tzinfo=KST),
        meal_type=MealType.OTHER,
        original_text="synthetic",
        items=tuple(_item(meal_id, sequence, **values) for sequence, values in enumerate(items, start=1)),
    )


def _nutrition(*items: dict[str, Any]) -> NutritionAggregate:
    return aggregate_meal(_meal("m", *items)).nutrition


def _empty_day() -> NutritionAggregate:
    return aggregate_day((), DAY, KST, timezone_name="+09:00").nutrition


# --- target values -----------------------------------------------------------------------


def test_exact_target_keeps_its_decimal_and_reports_equal_bounds() -> None:
    target = ExactTarget(Decimal("80.5"))

    assert target.kind is TargetKind.EXACT
    assert (target.minimum, target.maximum) == (Decimal("80.5"), Decimal("80.5"))


def test_range_target_is_inclusive_and_allows_equal_bounds() -> None:
    assert RangeTarget(Decimal(170), Decimal(180)).kind is TargetKind.RANGE
    assert RangeTarget(Decimal(175), Decimal(175)).minimum == Decimal(175)


@pytest.mark.parametrize("value", [Decimal(0), Decimal("-1"), Decimal("NaN"), Decimal("Infinity"), Decimal("-0")])
def test_exact_target_must_be_finite_and_positive(value: Decimal) -> None:
    with pytest.raises(NutritionTargetError):
        ExactTarget(value)


@pytest.mark.parametrize("value", [80, 80.0, "80", None, True])
def test_target_values_must_be_decimals(value: Any) -> None:
    with pytest.raises(NutritionTargetError):
        ExactTarget(value)
    with pytest.raises(NutritionTargetError):
        RangeTarget(Decimal(1), value)


@pytest.mark.parametrize(
    ("minimum", "maximum"),
    [("180", "170"), ("0", "10"), ("-5", "10"), ("10", "Infinity"), ("NaN", "10")],
)
def test_invalid_ranges_are_rejected(minimum: str, maximum: str) -> None:
    with pytest.raises(NutritionTargetError):
        RangeTarget(Decimal(minimum), Decimal(maximum))


def test_unset_is_the_default_and_distinct_from_any_value() -> None:
    targets = NutritionTargets()

    assert all(targets.get(nutrient) is None for nutrient in NutrientField)
    updated = targets.with_target(FAT, ExactTarget(Decimal(80)))
    assert updated.get(FAT) == ExactTarget(Decimal(80))
    assert targets.get(FAT) is None
    assert updated.with_target(FAT, None) == NutritionTargets()


def test_targets_reject_values_that_are_not_target_objects() -> None:
    with pytest.raises(NutritionTargetError):
        NutritionTargets(fat_g=Decimal(80))  # type: ignore[arg-type]


# --- exact targets -----------------------------------------------------------------------


def test_below_exact_target_reports_the_remaining_amount() -> None:
    result = evaluate_nutrient(FAT, ExactTarget(Decimal(80)), _nutrition({"fat": "30"}, {"fat": "20.5"}))

    assert result.status is TargetStatus.BELOW_TARGET
    assert result.complete is True
    assert result.consumed == Decimal("50.5")
    assert result.remaining == Decimal("29.5")
    assert result.excess == Decimal(0)
    assert result.remaining_to_maximum is None


def test_exact_target_reached_uses_exact_decimal_equality() -> None:
    result = evaluate_nutrient(FAT, ExactTarget(Decimal(80)), _nutrition({"fat": "79.9"}, {"fat": "0.10"}))

    assert result.consumed == Decimal("80.00")
    assert result.status is TargetStatus.TARGET_REACHED
    assert (result.remaining, result.excess) == (Decimal(0), Decimal(0))


def test_above_exact_target_reports_the_excess() -> None:
    result = evaluate_nutrient(FAT, ExactTarget(Decimal(80)), _nutrition({"fat": "80.01"}))

    assert result.status is TargetStatus.ABOVE_TARGET
    assert result.remaining == Decimal(0)
    assert result.excess == Decimal("0.01")


def test_no_tolerance_is_invented_around_an_exact_target() -> None:
    below = evaluate_nutrient(FAT, ExactTarget(Decimal(80)), _nutrition({"fat": "79.999999"}))

    assert below.status is TargetStatus.BELOW_TARGET
    assert below.remaining == Decimal("0.000001")


# --- range targets -----------------------------------------------------------------------


def test_below_range_reports_distance_to_both_bounds() -> None:
    result = evaluate_nutrient(PROTEIN, RangeTarget(Decimal(170), Decimal(180)), _nutrition({"protein": "120"}))

    assert result.status is TargetStatus.BELOW_RANGE
    assert result.remaining == Decimal(50)
    assert result.remaining_to_maximum == Decimal(60)
    assert result.excess == Decimal(0)


@pytest.mark.parametrize(("protein", "headroom"), [("170", "10"), ("175.5", "4.5"), ("180", "0")])
def test_within_range_includes_both_bounds(protein: str, headroom: str) -> None:
    result = evaluate_nutrient(PROTEIN, RangeTarget(Decimal(170), Decimal(180)), _nutrition({"protein": protein}))

    assert result.status is TargetStatus.WITHIN_RANGE
    assert result.remaining == Decimal(0)
    assert result.remaining_to_maximum == Decimal(headroom)
    assert result.excess == Decimal(0)


def test_above_range_reports_the_excess_over_the_maximum() -> None:
    result = evaluate_nutrient(PROTEIN, RangeTarget(Decimal(170), Decimal(180)), _nutrition({"protein": "181.25"}))

    assert result.status is TargetStatus.ABOVE_RANGE
    assert result.remaining == Decimal(0)
    assert result.remaining_to_maximum == Decimal(0)
    assert result.excess == Decimal("1.25")


# --- unset targets and empty days --------------------------------------------------------


def test_unset_target_still_reports_consumed_intake_without_gaps() -> None:
    result = evaluate_nutrient(PROTEIN, None, _nutrition({"protein": "54"}))

    assert result.status is TargetStatus.NO_TARGET
    assert result.target is None
    assert result.consumed == Decimal(54)
    assert result.complete is True
    assert (result.remaining, result.remaining_to_maximum, result.excess) == (None, None, None)


def test_day_without_meals_is_not_treated_as_zero_intake() -> None:
    result = evaluate_nutrient(PROTEIN, RangeTarget(Decimal(170), Decimal(180)), _empty_day())

    assert result.status is TargetStatus.NO_INTAKE_LOGGED
    assert result.complete is False
    assert result.consumed is None
    assert result.known_subtotal is None
    assert (result.remaining, result.remaining_to_maximum, result.excess) == (None, None, None)


def test_day_without_meals_and_without_target_has_no_target_status() -> None:
    assert evaluate_nutrient(PROTEIN, None, _empty_day()).status is TargetStatus.NO_TARGET


# --- multiple meals and precision --------------------------------------------------------


def test_multiple_meals_are_compared_as_one_day_total() -> None:
    meals = (
        _meal("breakfast", {"protein": "40.25"}, {"protein": "12"}, hour=8),
        _meal("lunch", {"protein": "60"}, hour=12),
        _meal("dinner", {"protein": "62.75"}, hour=19),
    )
    nutrition = aggregate_day(meals, DAY, KST, timezone_name="+09:00").nutrition

    result = evaluate_nutrient(PROTEIN, RangeTarget(Decimal(170), Decimal(180)), nutrition)

    assert result.consumed == Decimal("175.00")
    assert result.status is TargetStatus.WITHIN_RANGE
    assert result.remaining_to_maximum == Decimal("5.00")


def test_decimal_arithmetic_has_no_binary_float_drift() -> None:
    # 0.1 + 0.2 != 0.3 in binary floating point; Decimal keeps it exact.
    nutrition = _nutrition({"fat": "0.1"}, {"fat": "0.2"})

    assert evaluate_nutrient(FAT, ExactTarget(Decimal("0.3")), nutrition).status is TargetStatus.TARGET_REACHED
    below = evaluate_nutrient(FAT, ExactTarget(Decimal("0.30000000001")), nutrition)
    assert below.remaining == Decimal("0.00000000001")


def test_estimated_intake_is_flagged() -> None:
    nutrition = _nutrition({"protein": "100", "accuracy": Accuracy.ESTIMATED})

    result = evaluate_nutrient(PROTEIN, ExactTarget(Decimal(150)), nutrition)

    assert result.estimated is True
    assert result.status is TargetStatus.BELOW_TARGET


# --- missing nutrition data --------------------------------------------------------------


def test_incomplete_nutrient_is_not_treated_as_zero() -> None:
    nutrition = _nutrition({"fat": "30"}, {"fat": None})

    result = evaluate_nutrient(FAT, ExactTarget(Decimal(80)), nutrition)

    assert result.complete is False
    assert result.consumed is None
    assert result.known_subtotal == Decimal(30)
    assert result.status is TargetStatus.INDETERMINATE
    assert (result.remaining, result.remaining_to_maximum, result.excess) == (None, None, None)


def test_incomplete_known_subtotal_equal_to_exact_target_is_still_indeterminate() -> None:
    # The missing item can only add fat, so the real total is >= 80: reached or above, unknown which.
    result = evaluate_nutrient(FAT, ExactTarget(Decimal(80)), _nutrition({"fat": "80"}, {"fat": None}))

    assert result.status is TargetStatus.INDETERMINATE


def test_incomplete_known_subtotal_above_exact_target_proves_above_target() -> None:
    result = evaluate_nutrient(FAT, ExactTarget(Decimal(80)), _nutrition({"fat": "80.5"}, {"fat": None}))

    assert result.status is TargetStatus.ABOVE_TARGET
    assert result.complete is False
    assert result.consumed is None
    assert result.known_subtotal == Decimal("80.5")
    # Above is certain, the exact excess is not.
    assert (result.remaining, result.excess) == (None, None)


def test_incomplete_known_subtotal_above_range_maximum_proves_above_range() -> None:
    nutrition = _nutrition({"protein": "185"}, {"protein": None})

    result = evaluate_nutrient(PROTEIN, RangeTarget(Decimal(170), Decimal(180)), nutrition)

    assert result.status is TargetStatus.ABOVE_RANGE
    assert result.complete is False
    assert (result.remaining, result.remaining_to_maximum, result.excess) == (None, None, None)


@pytest.mark.parametrize("known", ["100", "170", "175", "180"])
def test_incomplete_known_subtotal_up_to_range_maximum_proves_nothing(known: str) -> None:
    nutrition = _nutrition({"protein": known}, {"protein": None})

    result = evaluate_nutrient(PROTEIN, RangeTarget(Decimal(170), Decimal(180)), nutrition)

    assert result.status is TargetStatus.INDETERMINATE
    assert result.known_subtotal == Decimal(known)


def test_no_item_with_a_value_is_indeterminate_with_unknown_subtotal() -> None:
    result = evaluate_nutrient(FAT, ExactTarget(Decimal(80)), _nutrition({"fat": None}))

    assert result.status is TargetStatus.INDETERMINATE
    assert result.known_subtotal is None


def test_complete_nutrients_stay_calculable_when_another_is_incomplete() -> None:
    nutrition = _nutrition({"protein": "60", "fat": "10"}, {"protein": "50", "fat": None})
    targets = NutritionTargets(
        protein_g=RangeTarget(Decimal(170), Decimal(180)),
        fat_g=ExactTarget(Decimal(80)),
        calories_kcal=ExactTarget(Decimal(2400)),
    )

    by_nutrient = {result.nutrient: result for result in evaluate_targets(targets, nutrition)}

    assert by_nutrient[FAT].status is TargetStatus.INDETERMINATE
    protein = by_nutrient[PROTEIN]
    assert protein.complete is True
    assert protein.status is TargetStatus.BELOW_RANGE
    assert protein.remaining == Decimal(60)
    kcal = by_nutrient[NutrientField.CALORIES_KCAL]
    assert (kcal.consumed, kcal.remaining, kcal.status) == (Decimal(200), Decimal(2200), TargetStatus.BELOW_TARGET)
    assert by_nutrient[NutrientField.CARBOHYDRATE_G].status is TargetStatus.NO_TARGET


def test_evaluate_targets_lists_every_nutrient_in_field_order() -> None:
    results = evaluate_targets(NutritionTargets(), _nutrition({}))

    assert [result.nutrient for result in results] == list(NutrientField)
