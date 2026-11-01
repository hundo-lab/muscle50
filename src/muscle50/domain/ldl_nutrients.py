"""LDL Nutrients v1: the day's saturated fat and fiber against the limits the user set.

Advice only, never a diagnosis: no lab value, no risk class and no warning grade exist here, and
nothing changes a target, the menu order or the training plan. Every threshold is a user setting;
the evidence reference values are only shown next to it:

- saturated fat ``< 7 %`` of energy: LDL-05 (KSoLA and ESC hypercholesterolaemia). ESC's general
  population figure ``< 10 %`` is also LDL-05 and is only named when the user picks 10.
- fiber ``>= 25 g/day``: LDL-08 (KSoLA; the lower end of ESC 25-40 g, so 40 is not a ceiling).
- grams from energy: 9 kcal per g of fat. ``[design: 9 kcal/g]``: it is not an evidence row; the
  LDL-05 note uses it in its own example (2,400 kcal -> 18.7 g).

The gram limit uses the user's kcal target (D2-A), so it exists on incomplete days. A kcal range
gives two limits (D3): only conclusions true at both ends are drawn. All comparisons are exact
Decimal cross-multiplications (no division, no rounding), so "= limit" is decided exactly; the limit
itself is a non-terminating number in general and is computed only for display.

Missing is not zero: an incomplete total is a lower bound, so it can prove "above the limit" or
"fiber reached", and nothing else.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Context, Decimal, localcontext
from enum import StrEnum

from muscle50.domain.nutrition import NUTRITION_DECIMAL_PRECISION, OptionalNutrientAggregate
from muscle50.domain.nutrition_targets import FiberTarget, NutrientTarget, SaturatedFatTarget

_CONTEXT = Context(prec=NUTRITION_DECIMAL_PRECISION, rounding=ROUND_HALF_EVEN)

FAT_KCAL_PER_G = Decimal(9)  # [design: 9 kcal/g]; the same factor as ATWATER_FAT in telegram_llm_check
LDL05_REFERENCE_PERCENT = Decimal(7)  # [LDL-05] KSoLA / ESC hypercholesterolaemia: < 7 % of energy
LDL05_ESC_GENERAL_PERCENT = Decimal(10)  # [LDL-05] ESC general population: < 10 % of energy
LDL08_REFERENCE_FIBER_G = Decimal(25)  # [LDL-08] KSoLA: >= 25 g/day
_PERCENT = Decimal(100)


class LdlStatus(StrEnum):
    NO_TARGET = "no_target"
    # Saturated fat only: the limit is a share of the kcal target, and there is none.
    NO_KCAL_TARGET = "no_kcal_target"
    NO_INTAKE_LOGGED = "no_intake_logged"
    # Some item has no value and the known items prove nothing.
    INDETERMINATE = "indeterminate"
    WITHIN_LIMIT = "within_limit"
    ABOVE_LIMIT = "above_limit"
    # A complete total at or above the limit of the kcal range's low end, below that of its high end.
    BETWEEN_LIMITS = "between_limits"
    BELOW_TARGET = "below_target"
    TARGET_REACHED = "target_reached"


@dataclass(frozen=True)
class SaturatedFatLimit:
    """The gram limits at both ends of the kcal target (equal for an exact kcal target)."""

    percent: Decimal
    kcal_target: NutrientTarget
    low: Decimal
    high: Decimal


@dataclass(frozen=True)
class SaturatedFatStatus:
    target: SaturatedFatTarget | None
    limit: SaturatedFatLimit | None
    aggregate: OptionalNutrientAggregate
    status: LdlStatus
    # Complete totals only: headroom below the (low end) limit, and the amount at or over the (high end) limit.
    remaining_to_limit: Decimal | None
    excess: Decimal | None
    # Info only, never used for the status: share of the logged energy, when kcal and saturated fat are complete.
    logged_energy_percent: Decimal | None


@dataclass(frozen=True)
class FiberStatus:
    target: FiberTarget | None
    aggregate: OptionalNutrientAggregate
    status: LdlStatus
    remaining: Decimal | None


@dataclass(frozen=True)
class MealNote:
    """[user setting; advice only] One meal's complete saturated fat reaches the setting's share of the day limit."""

    meal_id: str
    saturated_fat_g: Decimal
    share_of_day_limit: Decimal
    threshold_percent: Decimal


def saturated_fat_limit(target: SaturatedFatTarget, kcal_target: NutrientTarget) -> SaturatedFatLimit:
    """``kcal x P / 100 / 9`` at both ends of the kcal target, for display (decisions cross-multiply)."""
    return SaturatedFatLimit(
        target.max_energy_percent,
        kcal_target,
        _grams(kcal_target.minimum, target.max_energy_percent),
        _grams(kcal_target.maximum, target.max_energy_percent),
    )


def evaluate_saturated_fat(
    target: SaturatedFatTarget | None,
    kcal_target: NutrientTarget | None,
    aggregate: OptionalNutrientAggregate,
    *,
    logged_kcal: Decimal | None = None,
) -> SaturatedFatStatus:
    """``logged_kcal`` is the day's complete kcal total (None when incomplete); it feeds the info line only."""
    if target is None:
        return SaturatedFatStatus(None, None, aggregate, LdlStatus.NO_TARGET, None, None, None)
    if kcal_target is None:
        return SaturatedFatStatus(target, None, aggregate, LdlStatus.NO_KCAL_TARGET, None, None, None)
    limit = saturated_fat_limit(target, kcal_target)
    if aggregate.item_count == 0:
        return SaturatedFatStatus(target, limit, aggregate, LdlStatus.NO_INTAKE_LOGGED, None, None, None)
    percent = target.max_energy_percent
    low_kcal, high_kcal = kcal_target.minimum, kcal_target.maximum
    if not aggregate.complete or aggregate.total is None:
        known = aggregate.known_subtotal
        # The limit is "under L", so reaching it is already above; the known items are a lower bound.
        if known is not None and _reaches(known, high_kcal, percent):
            return SaturatedFatStatus(target, limit, aggregate, LdlStatus.ABOVE_LIMIT, None, None, None)
        return SaturatedFatStatus(target, limit, aggregate, LdlStatus.INDETERMINATE, None, None, None)
    consumed = aggregate.total
    share = _energy_percent(consumed, logged_kcal)
    if _reaches(consumed, high_kcal, percent):
        return SaturatedFatStatus(
            target, limit, aggregate, LdlStatus.ABOVE_LIMIT, None, _gap(consumed, limit.high), share
        )
    if not _reaches(consumed, low_kcal, percent):
        return SaturatedFatStatus(
            target, limit, aggregate, LdlStatus.WITHIN_LIMIT, _gap(limit.low, consumed), None, share
        )
    return SaturatedFatStatus(target, limit, aggregate, LdlStatus.BETWEEN_LIMITS, None, None, share)


def evaluate_fiber(target: FiberTarget | None, aggregate: OptionalNutrientAggregate) -> FiberStatus:
    if target is None:
        return FiberStatus(None, aggregate, LdlStatus.NO_TARGET, None)
    if aggregate.item_count == 0:
        return FiberStatus(target, aggregate, LdlStatus.NO_INTAKE_LOGGED, None)
    if not aggregate.complete or aggregate.total is None:
        known = aggregate.known_subtotal
        # Missing items can only add fiber, so a known subtotal at the floor proves it is reached.
        if known is not None and known >= target.minimum:
            return FiberStatus(target, aggregate, LdlStatus.TARGET_REACHED, None)
        return FiberStatus(target, aggregate, LdlStatus.INDETERMINATE, None)
    consumed = aggregate.total
    if consumed >= target.minimum:
        return FiberStatus(target, aggregate, LdlStatus.TARGET_REACHED, None)
    return FiberStatus(target, aggregate, LdlStatus.BELOW_TARGET, _gap(target.minimum, consumed))


def meal_note(
    meal_id: str,
    target: SaturatedFatTarget | None,
    kcal_target: NutrientTarget | None,
    meal_aggregate: OptionalNutrientAggregate,
) -> MealNote | None:
    """The meal note, or None: it needs the user's meal-note setting, a kcal target, and the meal's
    saturated fat complete (every item has a value). With a kcal range it is judged against the
    high-end limit, so it holds at either end."""
    if target is None or target.meal_note_percent is None or kcal_target is None:
        return None
    if not meal_aggregate.complete or meal_aggregate.total is None:
        return None
    grams = meal_aggregate.total
    high_kcal = kcal_target.maximum
    percent = target.max_energy_percent
    with localcontext(_CONTEXT):
        # share = grams / L_high = grams x 9 x 100 / (kcal x P), from the exact components.
        share = grams * FAT_KCAL_PER_G * _PERCENT / (high_kcal * percent)
        fires = grams * FAT_KCAL_PER_G * _PERCENT * _PERCENT >= target.meal_note_percent * high_kcal * percent
    if not fires:
        return None
    return MealNote(meal_id, grams, share, target.meal_note_percent)


def _reaches(grams: Decimal, kcal: Decimal, percent: Decimal) -> bool:
    """``grams >= kcal x percent / 100 / 9``, as ``grams x 9 x 100 >= kcal x percent`` (exact)."""
    with localcontext(_CONTEXT):
        return grams * FAT_KCAL_PER_G * _PERCENT >= kcal * percent


def _grams(kcal: Decimal, percent: Decimal) -> Decimal:
    with localcontext(_CONTEXT):
        return kcal * percent / _PERCENT / FAT_KCAL_PER_G


def _energy_percent(grams: Decimal, logged_kcal: Decimal | None) -> Decimal | None:
    if logged_kcal is None or logged_kcal <= 0:
        return None
    with localcontext(_CONTEXT):
        return grams * FAT_KCAL_PER_G * _PERCENT / logged_kcal


def _gap(upper: Decimal, lower: Decimal) -> Decimal:
    """``upper - lower`` when positive, otherwise zero."""
    with localcontext(_CONTEXT):
        difference = upper - lower
    return difference if difference > 0 else Decimal(0)
