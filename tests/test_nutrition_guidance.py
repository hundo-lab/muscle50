"""Nutrition guidance policy over real Nutrition Targets statuses and real training recommendations.

Statuses come from ``evaluate_targets`` (the Nutrition Targets code itself), never hand-built, so
these tests also pin that the policy reads the status as-is. All values and targets are synthetic.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest
from analytics_builders import activity, strength_set

from muscle50.domain.activity import ActivityType, NormalizedActivity
from muscle50.domain.nutrition import NutrientField, NutritionAggregate, NutritionValue
from muscle50.domain.nutrition_guidance import (
    NutritionAvailability,
    NutritionGuidance,
    build_nutrition_guidance,
    training_fuel_context,
    unavailable_guidance,
)
from muscle50.domain.nutrition_targets import (
    ExactTarget,
    NutrientTarget,
    NutritionTargets,
    RangeTarget,
    TargetStatus,
    evaluate_targets,
)
from muscle50.domain.training_recommendation import TrainingRecommendation, build_training_recommendation

AS_OF = date(2026, 3, 16)
P, KCAL, C, F = (
    NutrientField.PROTEIN_G,
    NutrientField.CALORIES_KCAL,
    NutrientField.CARBOHYDRATE_G,
    NutrientField.FAT_G,
)


def _bench(source_id: str, day: str) -> NormalizedActivity:
    sets = tuple(strength_set(index, reps=10, weight_kg=50.0) for index in range(1, 4))
    return activity(source_id, f"{day}T12:00:00", ActivityType.STRENGTH, strength_sets=sets)


@pytest.fixture(scope="module")
def strength_day() -> TrainingRecommendation:
    activities = [_bench("1", "2026-03-10"), _bench("2", "2026-03-13")]
    recommendation = build_training_recommendation(AS_OF, activities, [])
    assert recommendation.strength.exercises and recommendation.strength.adjustment_level == "normal"
    return recommendation


@pytest.fixture(scope="module")
def rest_day() -> TrainingRecommendation:
    recommendation = build_training_recommendation(AS_OF, [], [])
    assert not recommendation.strength.exercises
    assert recommendation.swimming.goal.session_type == "return_easy"
    return recommendation


def _with_swim(training: TrainingRecommendation, session_type: str) -> TrainingRecommendation:
    swimming = training.swimming
    return replace(training, swimming=replace(swimming, goal=replace(swimming.goal, session_type=session_type)))


def _with_level(training: TrainingRecommendation, level: str) -> TrainingRecommendation:
    return replace(training, strength=replace(training.strength, adjustment_level=level))


def _aggregate(
    totals: dict[NutrientField, str],
    *,
    known: dict[NutrientField, str] | None = None,
    incomplete: frozenset[NutrientField] = frozenset(),
    estimated: frozenset[NutrientField] = frozenset(),
    items: int = 2,
) -> NutritionAggregate:
    def value(source: dict[NutrientField, str]) -> NutritionValue:
        return NutritionValue(**{nutrient.value: Decimal(text) for nutrient, text in source.items()})

    return NutritionAggregate(
        totals=value({nutrient: text for nutrient, text in totals.items() if nutrient not in incomplete}),
        known_subtotals=value(known if known is not None else totals),
        value_range=None,
        incomplete_fields=incomplete,
        estimated_fields=estimated,
        item_count=items,
        uncalculated_items=(),
    )


def _guidance(
    training: TrainingRecommendation,
    targets: Mapping[NutrientField, NutrientTarget],
    aggregate: NutritionAggregate,
) -> tuple[dict[NutrientField, TargetStatus], NutritionGuidance]:
    statuses = evaluate_targets(NutritionTargets(**{nutrient.value: t for nutrient, t in targets.items()}), aggregate)
    guidance = build_nutrition_guidance(statuses, training)
    return {status.nutrient: status.status for status in statuses}, guidance


def _codes(guidance: NutritionGuidance) -> list[str]:
    return [action.code for action in guidance.actions]


def test_protein_below_exact_target_gets_a_protein_action(rest_day: TrainingRecommendation) -> None:
    statuses, guidance = _guidance(rest_day, {P: ExactTarget(Decimal("100"))}, _aggregate({P: "40"}))

    assert statuses[P] is TargetStatus.BELOW_TARGET
    assert guidance.availability is NutritionAvailability.EVALUATED
    assert _codes(guidance) == ["protein_below_target"]
    message = guidance.actions[0].message
    assert "below the configured target" in message
    assert not any(char.isdigit() for char in message)  # amounts live only in the status, never invented


def test_protein_below_range_names_the_range_minimum(rest_day: TrainingRecommendation) -> None:
    statuses, guidance = _guidance(rest_day, {P: RangeTarget(Decimal("90"), Decimal("110"))}, _aggregate({P: "40"}))

    assert statuses[P] is TargetStatus.BELOW_RANGE
    assert _codes(guidance) == ["protein_below_target"]
    assert "range minimum" in guidance.actions[0].message


def test_protein_within_range_needs_no_action(strength_day: TrainingRecommendation) -> None:
    statuses, guidance = _guidance(strength_day, {P: RangeTarget(Decimal("90"), Decimal("110"))}, _aggregate({P: "95"}))

    assert statuses[P] is TargetStatus.WITHIN_RANGE
    assert guidance.availability is NutritionAvailability.EVALUATED
    assert _codes(guidance) == []


def test_calories_below_target_on_a_strength_day_mentions_fueling_but_keeps_the_plan(
    strength_day: TrainingRecommendation,
) -> None:
    statuses, guidance = _guidance(strength_day, {KCAL: ExactTarget(Decimal("2000"))}, _aggregate({KCAL: "900"}))

    assert statuses[KCAL] is TargetStatus.BELOW_TARGET
    assert _codes(guidance) == ["energy_below_target"]
    message = guidance.actions[0].message
    assert "today's planned strength session" in message and "fuel" in message
    assert "does not change the training plan" in message


def test_calories_below_target_on_a_rest_day_has_no_training_fuel_message(rest_day: TrainingRecommendation) -> None:
    _statuses, guidance = _guidance(rest_day, {KCAL: ExactTarget(Decimal("2000"))}, _aggregate({KCAL: "900"}))

    assert _codes(guidance) == ["energy_below_target"]
    message = guidance.actions[0].message
    assert "fuel" not in message and "session" not in message


@pytest.mark.parametrize(
    ("context", "expected"),
    [
        ("strength", ["carbohydrate_below_target_for_training"]),
        ("rest", []),
        ("reduced_strength_easy_swim", []),
        ("pace_swim_only", ["carbohydrate_below_target_for_training"]),
        ("distance_swim_only", ["carbohydrate_below_target_for_training"]),
        ("recovery_swim_only", []),
    ],
)
def test_carbohydrate_below_target_is_an_action_only_with_training_work_ahead(
    strength_day: TrainingRecommendation, rest_day: TrainingRecommendation, context: str, expected: list[str]
) -> None:
    training = {
        "strength": strength_day,
        "rest": rest_day,
        "reduced_strength_easy_swim": _with_level(strength_day, "reduce"),
        "pace_swim_only": _with_swim(rest_day, "pace_intervals"),
        "distance_swim_only": _with_swim(rest_day, "distance_progression"),
        "recovery_swim_only": _with_swim(rest_day, "recovery_technique"),
    }[context]
    statuses, guidance = _guidance(training, {C: RangeTarget(Decimal("200"), Decimal("260"))}, _aggregate({C: "80"}))

    assert statuses[C] is TargetStatus.BELOW_RANGE  # the status itself is never hidden
    assert _codes(guidance) == expected
    if expected and context != "strength":
        assert "the next swim" in guidance.actions[0].message


def test_training_context_is_explicit(strength_day: TrainingRecommendation, rest_day: TrainingRecommendation) -> None:
    strength = training_fuel_context(strength_day)
    assert (strength.strength_session_planned, strength.strength_adjustment_level, strength.fuel_relevant) == (
        True,
        "normal",
        True,
    )
    assert training_fuel_context(_with_level(strength_day, "hold")).fuel_relevant is True
    reduced = training_fuel_context(_with_level(strength_day, "reduce"))
    assert (reduced.fuel_relevant, reduced.description) == (
        False,
        "a reduced strength session and an easy next swim (return_easy)",
    )
    rest = training_fuel_context(rest_day)
    assert (rest.strength_session_planned, rest.next_swim_session_type, rest.fuel_relevant) == (
        False,
        "return_easy",
        False,
    )


@pytest.mark.parametrize(
    ("target", "consumed", "expected"),
    [
        (ExactTarget(Decimal("100")), "130", TargetStatus.ABOVE_TARGET),
        (RangeTarget(Decimal("90"), Decimal("110")), "130", TargetStatus.ABOVE_RANGE),
        (ExactTarget(Decimal("100")), "100", TargetStatus.TARGET_REACHED),
    ],
)
def test_above_or_reached_targets_get_no_compensating_action(
    strength_day: TrainingRecommendation, target: NutrientTarget, consumed: str, expected: TargetStatus
) -> None:
    targets = {KCAL: target, P: target, C: target, F: target}
    statuses, guidance = _guidance(strength_day, targets, _aggregate(dict.fromkeys(targets, consumed)))

    assert set(statuses.values()) == {expected}
    assert _codes(guidance) == []


def test_unset_target_creates_no_action_even_when_intake_is_low(strength_day: TrainingRecommendation) -> None:
    statuses, guidance = _guidance(strength_day, {P: ExactTarget(Decimal("100"))}, _aggregate({P: "40", KCAL: "1"}))

    assert statuses[KCAL] is TargetStatus.NO_TARGET and statuses[C] is TargetStatus.NO_TARGET
    assert _codes(guidance) == ["protein_below_target"]


def test_no_targets_configured_is_its_own_state(strength_day: TrainingRecommendation) -> None:
    statuses, guidance = _guidance(strength_day, {}, _aggregate({P: "1", KCAL: "1", C: "1"}))

    assert set(statuses.values()) == {TargetStatus.NO_TARGET}
    assert guidance.availability is NutritionAvailability.NO_TARGETS_CONFIGURED
    assert _codes(guidance) == []


def test_missing_nutrient_value_stays_indeterminate_without_action(strength_day: TrainingRecommendation) -> None:
    aggregate = _aggregate({P: "40"}, known={P: "40"}, incomplete=frozenset({P}))
    statuses, guidance = _guidance(strength_day, {P: ExactTarget(Decimal("100"))}, aggregate)

    assert statuses[P] is TargetStatus.INDETERMINATE
    assert _codes(guidance) == []


def test_known_subtotal_equal_to_the_maximum_is_still_indeterminate(strength_day: TrainingRecommendation) -> None:
    aggregate = _aggregate({P: "110"}, known={P: "110"}, incomplete=frozenset({P}))
    statuses, guidance = _guidance(strength_day, {P: RangeTarget(Decimal("90"), Decimal("110"))}, aggregate)

    assert statuses[P] is TargetStatus.INDETERMINATE
    assert _codes(guidance) == []


def test_known_subtotal_above_the_maximum_is_above_without_action(strength_day: TrainingRecommendation) -> None:
    aggregate = _aggregate({P: "111"}, known={P: "111"}, incomplete=frozenset({P}))
    statuses, guidance = _guidance(strength_day, {P: RangeTarget(Decimal("90"), Decimal("110"))}, aggregate)

    assert statuses[P] is TargetStatus.ABOVE_RANGE
    assert _codes(guidance) == []


def test_no_intake_logged_never_becomes_a_deficit(strength_day: TrainingRecommendation) -> None:
    targets = {P: ExactTarget(Decimal("100")), KCAL: ExactTarget(Decimal("2000")), C: ExactTarget(Decimal("250"))}
    aggregate = _aggregate({}, items=0, incomplete=frozenset(NutrientField))

    statuses, guidance = _guidance(strength_day, targets, aggregate)

    assert {statuses[P], statuses[KCAL], statuses[C]} == {TargetStatus.NO_INTAKE_LOGGED}
    assert guidance.availability is NutritionAvailability.NO_INTAKE_LOGGED
    assert _codes(guidance) == []


def test_estimated_totals_stay_marked_as_estimates(rest_day: TrainingRecommendation) -> None:
    aggregate = _aggregate({P: "40"}, estimated=frozenset({P}))
    _statuses, guidance = _guidance(rest_day, {P: ExactTarget(Decimal("100"))}, aggregate)

    assert "includes estimated values" in guidance.actions[0].message


def test_actions_are_ordered_protein_energy_carbohydrate(strength_day: TrainingRecommendation) -> None:
    targets = {
        KCAL: ExactTarget(Decimal("2000")),
        P: ExactTarget(Decimal("100")),
        C: ExactTarget(Decimal("250")),
        F: ExactTarget(Decimal("70")),
    }
    _statuses, guidance = _guidance(strength_day, targets, _aggregate({KCAL: "1", P: "1", C: "1", F: "1"}))

    # Fat below target is reported by status only: v1 has no fat action.
    assert _codes(guidance) == ["protein_below_target", "energy_below_target", "carbohydrate_below_target_for_training"]


@pytest.mark.parametrize("scale", ["0.5", "1", "100000"])
def test_actions_depend_on_the_status_not_on_any_built_in_amount(
    strength_day: TrainingRecommendation, scale: str
) -> None:
    target = Decimal(scale)
    _statuses, below = _guidance(strength_day, {P: ExactTarget(target)}, _aggregate({P: str(target / 2)}))
    _statuses, met = _guidance(strength_day, {P: ExactTarget(target)}, _aggregate({P: str(target)}))

    assert _codes(below) == ["protein_below_target"]
    assert _codes(met) == []


def test_unavailable_guidance_has_no_actions(strength_day: TrainingRecommendation) -> None:
    guidance = unavailable_guidance(strength_day)

    assert guidance.availability is NutritionAvailability.UNAVAILABLE
    assert guidance.actions == ()
    assert guidance.training_context.fuel_relevant is True
