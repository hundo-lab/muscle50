"""LDL Nutrients v1 domain: optional amounts, per-nutrient selection, aggregation and status rules.

All values are synthetic test numbers, not real food data or the user's targets.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from muscle50.domain.ldl_nutrients import (
    LdlStatus,
    evaluate_fiber,
    evaluate_saturated_fat,
    meal_note,
    saturated_fat_limit,
)
from muscle50.domain.nutrition import (
    Accuracy,
    MealItem,
    NutrientField,
    NutritionFact,
    NutritionProvenance,
    NutritionRange,
    NutritionSourceType,
    NutritionValue,
    OptionalNutrient,
    OptionalNutrientAggregate,
    OptionalNutrientAmount,
    QuantityUnit,
    aggregate_optional,
    is_general_estimate_fact,
    select_preferred_fact,
)
from muscle50.domain.nutrition_targets import (
    ExactTarget,
    FiberTarget,
    LdlTargets,
    NutritionTargetError,
    NutritionTargets,
    RangeTarget,
    SaturatedFatTarget,
)

KST = timezone(timedelta(hours=9))
SAT = OptionalNutrient.SATURATED_FAT_G
FIBER = OptionalNutrient.FIBER_G
T0 = datetime(2026, 11, 1, 8, 0, tzinfo=KST)


def _provenance(accuracy: Accuracy = Accuracy.EXACT, *, minutes: int = 0) -> NutritionProvenance:
    source = NutritionSourceType.NUTRITION_LABEL if accuracy is Accuracy.EXACT else NutritionSourceType.USER_PROVIDED
    return NutritionProvenance(source, accuracy, "synthetic", T0 + timedelta(minutes=minutes))


def _fact(
    fact_id: str = "f1",
    *,
    fat: str | None = "10",
    optional: tuple[OptionalNutrientAmount, ...] = (),
    accuracy: Accuracy = Accuracy.EXACT,
    supersedes: str | None = None,
    minutes: int = 0,
) -> NutritionFact:
    return NutritionFact(
        fact_id=fact_id,
        values=NutritionValue(calories_kcal=Decimal(100), fat_g=Decimal(fat) if fat is not None else None),
        basis_quantity=Decimal(100),
        basis_unit=QuantityUnit.GRAM,
        provenance=_provenance(accuracy, minutes=minutes),
        supersedes_fact_id=supersedes,
        optional=optional,
    )


def _amount(nutrient: OptionalNutrient, value: str) -> OptionalNutrientAmount:
    return OptionalNutrientAmount(nutrient, Decimal(value))


def _item(sequence: int, *facts: NutritionFact, grams: str = "100") -> MealItem:
    return MealItem(
        meal_id="m1",
        sequence=sequence,
        food_name=f"Syn{sequence}",
        quantity=Decimal(grams),
        quantity_unit=QuantityUnit.GRAM,
        food_profile_id=f"syn-{sequence}",
        nutrition_facts=facts,
    )


def _aggregate(
    total: str | None, known: str | None = None, *, complete: bool = True, items: int = 2
) -> OptionalNutrientAggregate:
    known_text = known if known is not None else total
    return OptionalNutrientAggregate(
        nutrient=SAT,
        total=Decimal(total) if total is not None else None,
        known_subtotal=Decimal(known_text) if known_text is not None else None,
        complete=complete,
        estimated=False,
        has_data=True,
        item_count=items,
        missing_items=(),
    )


# --- amounts and facts ----------------------------------------------------------------------


def test_optional_amounts_are_kept_in_canonical_order() -> None:
    fact = _fact(optional=(_amount(FIBER, "4"), _amount(SAT, "2")))
    assert [amount.nutrient for amount in fact.optional] == [SAT, FIBER]
    assert fact == _fact(optional=(_amount(SAT, "2"), _amount(FIBER, "4")))


@pytest.mark.parametrize(
    ("build", "message"),
    [
        (lambda: OptionalNutrientAmount(SAT), "needs a value or a range"),
        (lambda: OptionalNutrientAmount(SAT, Decimal(-1)), "non-negative"),
        (lambda: OptionalNutrientAmount(SAT, None, Decimal(2), None), "requires both minimum and maximum"),
        (lambda: OptionalNutrientAmount(SAT, None, Decimal(3), Decimal(2)), "minimum cannot exceed maximum"),
        (lambda: OptionalNutrientAmount(SAT, Decimal(5), Decimal(1), Decimal(2)), "within its estimate range"),
        (lambda: _fact(optional=(_amount(SAT, "1"), _amount(SAT, "2"))), "at most once"),
        (lambda: _fact(fat="3", optional=(_amount(SAT, "3.1"),)), "cannot be more than total fat"),
        (
            lambda: _fact(optional=(OptionalNutrientAmount(SAT, None, Decimal(1), Decimal(2)),)),
            "exact nutrition facts cannot carry an estimate range",
        ),
    ],
)
def test_invalid_optional_amounts_are_refused(build: object, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        build()  # type: ignore[operator]


def test_saturated_fat_equal_to_fat_or_with_unknown_fat_is_accepted() -> None:
    assert _fact(fat="3", optional=(_amount(SAT, "3"),)).optional_amount(SAT) == _amount(SAT, "3")
    assert _fact(fat=None, optional=(_amount(SAT, "30"),)).optional_amount(SAT) is not None


def test_saturated_fat_range_above_the_fat_range_is_refused() -> None:
    def estimate(sat_min: str) -> NutritionFact:
        return NutritionFact(
            fact_id="e1",
            values=NutritionValue(),
            basis_quantity=Decimal(1),
            basis_unit=QuantityUnit.SERVING,
            provenance=NutritionProvenance(NutritionSourceType.LANGUAGE_ESTIMATE, Accuracy.ESTIMATED, "synthetic", T0),
            value_range=NutritionRange(NutritionValue(fat_g=Decimal(50)), NutritionValue(fat_g=Decimal(70))),
            optional=(OptionalNutrientAmount(SAT, None, Decimal(sat_min), Decimal(80)),),
        )

    assert is_general_estimate_fact(estimate("70"))
    with pytest.raises(ValueError, match="cannot be more than total fat"):
        estimate("71")


def test_a_fact_with_only_optional_nutrients_is_refused() -> None:
    with pytest.raises(ValueError, match="at least one value or range"):
        NutritionFact(
            fact_id="f1",
            values=NutritionValue(),
            basis_quantity=Decimal(100),
            basis_unit=QuantityUnit.GRAM,
            provenance=_provenance(),
            optional=(_amount(FIBER, "4"),),
        )


def test_a_general_estimate_with_an_optional_point_value_is_not_a_general_estimate() -> None:
    fact = NutritionFact(
        fact_id="e1",
        values=NutritionValue(),
        basis_quantity=Decimal(1),
        basis_unit=QuantityUnit.SERVING,
        provenance=NutritionProvenance(NutritionSourceType.LANGUAGE_ESTIMATE, Accuracy.ESTIMATED, "synthetic", T0),
        value_range=NutritionRange(
            NutritionValue(calories_kcal=Decimal(800)), NutritionValue(calories_kcal=Decimal(900))
        ),
        optional=(OptionalNutrientAmount(FIBER, Decimal(3)),),
    )
    assert not is_general_estimate_fact(fact)


# --- per-nutrient supersession and item amounts --------------------------------------------------


def test_supersession_is_decided_per_optional_nutrient() -> None:
    old = _fact("f1", optional=(_amount(SAT, "2"), _amount(FIBER, "1")))
    # The new version knows only saturated fat: fiber keeps the old fact, saturated fat moves to the new one.
    new = _fact("f2", optional=(_amount(SAT, "3"),), supersedes="f1", minutes=1)
    facts = (old, new)
    assert select_preferred_fact(facts, QuantityUnit.GRAM, SAT) is new
    assert select_preferred_fact(facts, QuantityUnit.GRAM, FIBER) is old
    assert select_preferred_fact(facts, QuantityUnit.GRAM, NutrientField.FAT_G) is new
    item = _item(1, old, new, grams="50")
    assert [(c.nutrient, c.fact_id, c.value) for c in item.calculated_optional()] == [
        (SAT, "f2", Decimal("1.5")),
        (FIBER, "f1", Decimal("0.5")),
    ]


def test_an_item_without_optional_facts_has_no_optional_amounts() -> None:
    assert _item(1, _fact()).calculated_optional() == ()


# --- aggregation ------------------------------------------------------------------------------


def test_aggregate_is_complete_only_when_every_item_has_a_value() -> None:
    full = _item(1, _fact("a", optional=(_amount(SAT, "4"), _amount(FIBER, "2"))))
    partial = _item(2, _fact("b", optional=(_amount(SAT, "1"),)))
    sat, fiber = aggregate_optional((full, partial))
    assert (sat.complete, sat.total, sat.known_subtotal, sat.missing_items) == (True, Decimal(5), Decimal(5), ())
    assert (fiber.complete, fiber.total, fiber.known_subtotal) == (False, None, Decimal(2))
    assert [(ref.meal_id, ref.sequence) for ref in fiber.missing_items] == [("m1", 2)]
    assert sat.has_data and fiber.has_data


def test_items_without_any_value_are_unknown_not_zero() -> None:
    sat, fiber = aggregate_optional((_item(1, _fact()),))
    assert (sat.total, sat.known_subtotal, sat.complete, sat.has_data) == (None, None, False, False)
    assert len(fiber.missing_items) == 1
    empty_sat, _ = aggregate_optional(())
    assert (empty_sat.complete, empty_sat.item_count, empty_sat.total) == (False, 0, None)


def test_an_estimate_range_alone_keeps_the_total_incomplete() -> None:
    estimate = NutritionFact(
        fact_id="m1:2:estimate",
        values=NutritionValue(),
        basis_quantity=Decimal(1),
        basis_unit=QuantityUnit.SERVING,
        provenance=NutritionProvenance(NutritionSourceType.LANGUAGE_ESTIMATE, Accuracy.ESTIMATED, "synthetic", T0),
        value_range=NutritionRange(NutritionValue(fat_g=Decimal(50)), NutritionValue(fat_g=Decimal(70))),
        optional=(OptionalNutrientAmount(SAT, None, Decimal(15), Decimal(25)),),
    )
    general = MealItem("m1", 2, "일반식", None, None, "general-meal", None, (estimate,))
    catalog = _item(1, _fact(optional=(_amount(SAT, "4"),)))
    assert [(c.minimum, c.maximum) for c in general.calculated_optional()] == [(Decimal(15), Decimal(25))]
    sat, _ = aggregate_optional((catalog, general))
    assert (sat.complete, sat.total, sat.known_subtotal, sat.estimated) == (False, None, Decimal(4), True)
    assert [ref.sequence for ref in sat.missing_items] == [2]


# --- targets ----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "build",
    [
        lambda: SaturatedFatTarget(Decimal(0)),
        lambda: SaturatedFatTarget(Decimal(-1)),
        lambda: SaturatedFatTarget(Decimal(100)),
        lambda: SaturatedFatTarget(Decimal(7), Decimal(0)),
        lambda: FiberTarget(Decimal(0)),
        lambda: FiberTarget(Decimal(-25)),
    ],
)
def test_invalid_ldl_targets_are_refused(build: object) -> None:
    with pytest.raises(NutritionTargetError):
        build()  # type: ignore[operator]


def test_ldl_targets_are_kept_when_another_target_changes() -> None:
    ldl = LdlTargets(SaturatedFatTarget(Decimal(7)), FiberTarget(Decimal(25)))
    targets = NutritionTargets().with_ldl(ldl).with_target(NutrientField.CALORIES_KCAL, ExactTarget(Decimal(2400)))
    assert targets.ldl == ldl
    assert NutritionTargets().ldl.is_set is False


# --- saturated fat status (AC7) -----------------------------------------------------------------

# 1800 kcal x 7 % / 9 = 14 g exactly, so "= L" is testable.
KCAL_1800 = ExactTarget(Decimal(1800))
SEVEN = SaturatedFatTarget(Decimal(7))


@pytest.mark.parametrize(
    ("aggregate", "status", "remaining", "excess"),
    [
        (_aggregate("13.9"), LdlStatus.WITHIN_LIMIT, Decimal("0.1"), None),
        (_aggregate("14"), LdlStatus.ABOVE_LIMIT, None, Decimal(0)),
        (_aggregate("15"), LdlStatus.ABOVE_LIMIT, None, Decimal(1)),
        (_aggregate(None, "14", complete=False), LdlStatus.ABOVE_LIMIT, None, None),
        (_aggregate(None, "13.9", complete=False), LdlStatus.INDETERMINATE, None, None),
        (_aggregate(None, None, complete=False), LdlStatus.INDETERMINATE, None, None),
        (_aggregate(None, None, complete=False, items=0), LdlStatus.NO_INTAKE_LOGGED, None, None),
    ],
)
def test_saturated_fat_status(
    aggregate: OptionalNutrientAggregate, status: LdlStatus, remaining: Decimal | None, excess: Decimal | None
) -> None:
    result = evaluate_saturated_fat(SEVEN, KCAL_1800, aggregate)
    assert (result.status, result.remaining_to_limit, result.excess) == (status, remaining, excess)
    assert result.limit is not None and result.limit.low == result.limit.high == Decimal(14)


def test_saturated_fat_without_a_target_or_kcal_target() -> None:
    aggregate = _aggregate("10")
    assert evaluate_saturated_fat(None, KCAL_1800, aggregate).status is LdlStatus.NO_TARGET
    no_kcal = evaluate_saturated_fat(SEVEN, None, aggregate)
    assert (no_kcal.status, no_kcal.limit) == (LdlStatus.NO_KCAL_TARGET, None)
    # no_kcal_target comes before no_intake_logged.
    assert evaluate_saturated_fat(SEVEN, None, _aggregate(None, None, items=0)).status is LdlStatus.NO_KCAL_TARGET


def test_saturated_fat_with_a_kcal_range_draws_only_conclusions_true_at_both_ends() -> None:
    kcal = RangeTarget(Decimal(1800), Decimal(2700))  # limits 14 g and 21 g
    assert evaluate_saturated_fat(SEVEN, kcal, _aggregate("13")).status is LdlStatus.WITHIN_LIMIT
    assert evaluate_saturated_fat(SEVEN, kcal, _aggregate("14")).status is LdlStatus.BETWEEN_LIMITS
    assert evaluate_saturated_fat(SEVEN, kcal, _aggregate("20.9")).status is LdlStatus.BETWEEN_LIMITS
    assert evaluate_saturated_fat(SEVEN, kcal, _aggregate("21")).status is LdlStatus.ABOVE_LIMIT
    assert evaluate_saturated_fat(SEVEN, kcal, _aggregate(None, "20", complete=False)).status is LdlStatus.INDETERMINATE
    limit = saturated_fat_limit(SEVEN, kcal)
    assert (limit.low, limit.high) == (Decimal(14), Decimal(21))


def test_non_terminating_limit_is_decided_exactly() -> None:
    kcal = ExactTarget(Decimal(2400))  # 18.666... g
    limit = saturated_fat_limit(SEVEN, kcal)
    assert str(limit.high) == "18.66666666666666666666666667"
    assert evaluate_saturated_fat(SEVEN, kcal, _aggregate("18.6666666666666666666666666")).status is (
        LdlStatus.WITHIN_LIMIT
    )
    assert evaluate_saturated_fat(SEVEN, kcal, _aggregate("18.67")).status is LdlStatus.ABOVE_LIMIT


def test_logged_energy_share_is_info_only() -> None:
    result = evaluate_saturated_fat(SEVEN, KCAL_1800, _aggregate("10"), logged_kcal=Decimal(1500))
    assert result.logged_energy_percent == Decimal(6)
    assert result.status is LdlStatus.WITHIN_LIMIT
    incomplete = evaluate_saturated_fat(SEVEN, KCAL_1800, _aggregate("10"), logged_kcal=None)
    assert incomplete.logged_energy_percent is None
    assert (
        evaluate_saturated_fat(SEVEN, KCAL_1800, _aggregate("10"), logged_kcal=Decimal(0)).logged_energy_percent is None
    )


# --- fiber status (AC8) ------------------------------------------------------------------------

TWENTY_FIVE = FiberTarget(Decimal(25))


@pytest.mark.parametrize(
    ("aggregate", "status", "remaining"),
    [
        (_aggregate("25"), LdlStatus.TARGET_REACHED, None),
        (_aggregate("17.5"), LdlStatus.BELOW_TARGET, Decimal("7.5")),
        (_aggregate(None, "25", complete=False), LdlStatus.TARGET_REACHED, None),
        (_aggregate(None, "24.9", complete=False), LdlStatus.INDETERMINATE, None),
        (_aggregate(None, None, complete=False, items=0), LdlStatus.NO_INTAKE_LOGGED, None),
    ],
)
def test_fiber_status(aggregate: OptionalNutrientAggregate, status: LdlStatus, remaining: Decimal | None) -> None:
    result = evaluate_fiber(TWENTY_FIVE, aggregate)
    assert (result.status, result.remaining) == (status, remaining)


def test_fiber_without_a_target() -> None:
    assert evaluate_fiber(None, _aggregate("30")).status is LdlStatus.NO_TARGET


# --- meal note (AC10) ---------------------------------------------------------------------------


def test_meal_note_fires_at_the_setting() -> None:
    target = SaturatedFatTarget(Decimal(7), Decimal(50))
    note = meal_note("m1", target, KCAL_1800, _aggregate("7"))  # 7 g = 50 % of 14 g
    assert note is not None
    assert (note.saturated_fat_g, note.share_of_day_limit, note.threshold_percent) == (
        Decimal(7),
        Decimal("0.5"),
        Decimal(50),
    )
    assert meal_note("m1", target, KCAL_1800, _aggregate("6.99")) is None


def test_meal_note_share_comes_from_exact_components() -> None:
    note = meal_note("m1", SaturatedFatTarget(Decimal(7), Decimal(50)), ExactTarget(Decimal(2400)), _aggregate("13"))
    assert note is not None
    assert str(note.share_of_day_limit) == "0.6964285714285714285714285714"


def test_meal_note_needs_setting_kcal_target_and_complete_meal() -> None:
    with_setting = SaturatedFatTarget(Decimal(7), Decimal(50))
    assert meal_note("m1", SEVEN, KCAL_1800, _aggregate("13")) is None
    assert meal_note("m1", with_setting, None, _aggregate("13")) is None
    assert meal_note("m1", with_setting, KCAL_1800, _aggregate(None, "13", complete=False)) is None


def test_meal_note_with_a_kcal_range_uses_the_high_end_limit() -> None:
    target = SaturatedFatTarget(Decimal(7), Decimal(50))
    kcal = RangeTarget(Decimal(1800), Decimal(2700))  # 14 g and 21 g; 50 % of 21 g = 10.5 g
    assert meal_note("m1", target, kcal, _aggregate("10")) is None
    assert meal_note("m1", target, kcal, _aggregate("10.5")) is not None
