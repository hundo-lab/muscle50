"""Nutrition guidance v1: which daily nutrition statuses deserve an action next to a training plan.

This is a rule layer over two finished results and never recomputes either of them:

- the per-nutrient ``NutrientTargetStatus`` from Nutrition Targets (Nutrition Core totals compared
  with the configured targets; this module does no arithmetic on nutrient values), and
- the ``TrainingRecommendation`` for the same date, which is built first and never sees
  nutrition. Nutrition therefore cannot change, cancel or shorten the training plan.

Only a ``below_*`` status on a complete total produces an action. ``no_target``,
``no_intake_logged`` and ``indeterminate`` never do (unknown is not zero, an unset target is not a
target), and ``above_*``/met states are reported as status only: no compensating advice. There
is no shortfall threshold and no gram or timing prescription; amounts appear only in the
status itself. Nothing here is medical or diagnostic.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from muscle50.domain.nutrition import NutrientField
from muscle50.domain.nutrition_targets import NutrientTargetStatus, TargetStatus
from muscle50.domain.recovery_assessment import AdjustmentLevel
from muscle50.domain.swim_recommendation import SwimSessionType
from muscle50.domain.training_recommendation import TrainingRecommendation

NUTRITION_GUIDANCE_VERSION = 1

# Next-swim goals that are real training work rather than easy/recovery swimming.
FUEL_SWIM_SESSION_TYPES = frozenset({SwimSessionType.DISTANCE_PROGRESSION, SwimSessionType.PACE_INTERVALS})

_BELOW = frozenset({TargetStatus.BELOW_TARGET, TargetStatus.BELOW_RANGE})


class NutritionAvailability(StrEnum):
    EVALUATED = "evaluated"
    """At least one target is configured and at least one item is logged for the date."""
    NO_TARGETS_CONFIGURED = "no_targets_configured"
    NO_INTAKE_LOGGED = "no_intake_logged"
    """Targets exist but no meal is logged: not "ate nothing", so no status is used."""
    UNAVAILABLE = "unavailable"
    """Nutrition data or targets could not be read; the training plan is unaffected."""


@dataclass(frozen=True)
class TrainingFuelContext:
    """The training-plan facts that decide whether energy/carbohydrate is framed as fuel."""

    strength_session_planned: bool
    strength_adjustment_level: str
    next_swim_session_type: str
    fuel_relevant: bool
    description: str


@dataclass(frozen=True)
class NutritionAction:
    code: str
    nutrient: NutrientField
    message: str


@dataclass(frozen=True)
class NutritionGuidance:
    guidance_version: int
    availability: NutritionAvailability
    training_context: TrainingFuelContext
    actions: tuple[NutritionAction, ...]


def training_fuel_context(training: TrainingRecommendation) -> TrainingFuelContext:
    strength = training.strength
    planned = bool(strength.exercises)
    level = strength.adjustment_level
    swim_type = training.swimming.goal.session_type
    strength_fuel = planned and level != AdjustmentLevel.REDUCE.value
    swim_fuel = swim_type in FUEL_SWIM_SESSION_TYPES
    parts = []
    if strength_fuel:
        parts.append("today's planned strength session")
    if swim_fuel:
        parts.append(f"the next swim ({swim_type})")
    if parts:
        description = " and ".join(parts)
    elif planned:
        description = f"a reduced strength session and an easy next swim ({swim_type})"
    else:
        description = f"no strength session planned and an easy next swim ({swim_type})"
    return TrainingFuelContext(planned, level, swim_type, strength_fuel or swim_fuel, description)


def unavailable_guidance(training: TrainingRecommendation) -> NutritionGuidance:
    return NutritionGuidance(
        NUTRITION_GUIDANCE_VERSION, NutritionAvailability.UNAVAILABLE, training_fuel_context(training), ()
    )


def build_nutrition_guidance(
    statuses: Sequence[NutrientTargetStatus], training: TrainingRecommendation
) -> NutritionGuidance:
    context = training_fuel_context(training)
    if all(status.target is None for status in statuses):
        availability = NutritionAvailability.NO_TARGETS_CONFIGURED
    elif any(status.status is TargetStatus.NO_INTAKE_LOGGED for status in statuses):
        # Nutrition Targets' own "no logged items" verdict; not re-derived from counts here.
        availability = NutritionAvailability.NO_INTAKE_LOGGED
    else:
        availability = NutritionAvailability.EVALUATED
    actions: tuple[NutritionAction, ...] = ()
    if availability is NutritionAvailability.EVALUATED:
        by_nutrient = {status.nutrient: status for status in statuses}
        actions = tuple(
            action
            for nutrient in (NutrientField.PROTEIN_G, NutrientField.CALORIES_KCAL, NutrientField.CARBOHYDRATE_G)
            if (status := by_nutrient.get(nutrient)) is not None and (action := _action(status, context)) is not None
        )
    return NutritionGuidance(NUTRITION_GUIDANCE_VERSION, availability, context, actions)


def _action(status: NutrientTargetStatus, context: TrainingFuelContext) -> NutritionAction | None:
    # A below status exists only for a complete total (Nutrition Targets never reports
    # below_* from a known subtotal), so these actions never rest on unknown values.
    if status.status not in _BELOW or not status.complete:
        return None
    bound = "target" if status.status is TargetStatus.BELOW_TARGET else "range minimum"
    estimated = " (the logged total includes estimated values)" if status.estimated else ""
    nutrient = status.nutrient
    if nutrient is NutrientField.PROTEIN_G:
        return NutritionAction(
            "protein_below_target",
            nutrient,
            f"logged protein is below the configured {bound}{estimated}; if meals remain today, "
            "include a protein source in them",
        )
    if nutrient is NutrientField.CALORIES_KCAL:
        if context.fuel_relevant:
            message = (
                f"logged energy is below the configured {bound}{estimated} with {context.description} ahead; "
                "eat enough to fuel it. This does not change the training plan"
            )
        else:
            message = (
                f"logged energy is below the configured {bound}{estimated}; if meals remain today, aim to reach it"
            )
        return NutritionAction("energy_below_target", nutrient, message)
    if nutrient is NutrientField.CARBOHYDRATE_G and context.fuel_relevant:
        return NutritionAction(
            "carbohydrate_below_target_for_training",
            nutrient,
            f"logged carbohydrate is below the configured {bound}{estimated} with {context.description} ahead; "
            "carbohydrate is the main fuel for that work",
        )
    return None
