"""Daily nutrition targets and how logged intake compares with them.

A target is set explicitly per nutrient: an exact value, an inclusive range, or nothing
(unset). Unset is not zero, and zero is not a valid target. Targets are never calculated
here. The comparison reads a Nutrition Core aggregate as it is; it never re-aggregates
meals and never treats a missing nutrient value as zero.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import ROUND_HALF_EVEN, Context, Decimal, localcontext
from enum import StrEnum

from muscle50.domain.nutrition import NUTRITION_DECIMAL_PRECISION, NutrientField, NutritionAggregate

_CONTEXT = Context(prec=NUTRITION_DECIMAL_PRECISION, rounding=ROUND_HALF_EVEN)


class NutritionTargetError(ValueError):
    """A target that cannot be stored or read without guessing."""


class TargetKind(StrEnum):
    EXACT = "exact"
    RANGE = "range"
    UNSET = "unset"


@dataclass(frozen=True)
class ExactTarget:
    value: Decimal

    def __post_init__(self) -> None:
        _require_positive(self.value, "target")

    @property
    def kind(self) -> TargetKind:
        return TargetKind.EXACT

    @property
    def minimum(self) -> Decimal:
        return self.value

    @property
    def maximum(self) -> Decimal:
        return self.value


@dataclass(frozen=True)
class RangeTarget:
    """An inclusive range; ``minimum == maximum`` is allowed."""

    minimum: Decimal
    maximum: Decimal

    def __post_init__(self) -> None:
        _require_positive(self.minimum, "range minimum")
        _require_positive(self.maximum, "range maximum")
        if self.minimum > self.maximum:
            raise NutritionTargetError("range minimum cannot exceed range maximum")

    @property
    def kind(self) -> TargetKind:
        return TargetKind.RANGE


NutrientTarget = ExactTarget | RangeTarget


@dataclass(frozen=True)
class NutritionTargets:
    """Daily targets; ``None`` means no target is set for that nutrient."""

    calories_kcal: NutrientTarget | None = None
    protein_g: NutrientTarget | None = None
    carbohydrate_g: NutrientTarget | None = None
    fat_g: NutrientTarget | None = None

    def __post_init__(self) -> None:
        for nutrient in NutrientField:
            target = self.get(nutrient)
            if target is not None and not isinstance(target, ExactTarget | RangeTarget):
                raise NutritionTargetError(f"{nutrient.value} target must be exact, range or unset")

    def get(self, nutrient: NutrientField) -> NutrientTarget | None:
        target: NutrientTarget | None = getattr(self, nutrient.value)
        return target

    def with_target(self, nutrient: NutrientField, target: NutrientTarget | None) -> NutritionTargets:
        return replace(self, **{nutrient.value: target})


class TargetStatus(StrEnum):
    NO_TARGET = "no_target"
    # The day has no logged items: Nutrition Core reports that as incomplete, not as zero.
    NO_INTAKE_LOGGED = "no_intake_logged"
    # Some logged item has no value for the nutrient and the known items prove nothing.
    INDETERMINATE = "indeterminate"
    BELOW_TARGET = "below_target"
    TARGET_REACHED = "target_reached"
    ABOVE_TARGET = "above_target"
    BELOW_RANGE = "below_range"
    WITHIN_RANGE = "within_range"
    ABOVE_RANGE = "above_range"


@dataclass(frozen=True)
class NutrientTargetStatus:
    nutrient: NutrientField
    target: NutrientTarget | None
    # Day total; None unless every logged item supplies the nutrient.
    consumed: Decimal | None
    # Sum over the items that do supply it (Nutrition Core's known subtotal).
    known_subtotal: Decimal | None
    complete: bool
    estimated: bool
    status: TargetStatus
    # Non-negative gaps, None when they cannot be known exactly:
    # remaining to the exact value or the range minimum, headroom to the range maximum,
    # and the amount above the exact value or the range maximum.
    remaining: Decimal | None
    remaining_to_maximum: Decimal | None
    excess: Decimal | None


def evaluate_nutrient(
    nutrient: NutrientField, target: NutrientTarget | None, nutrition: NutritionAggregate
) -> NutrientTargetStatus:
    consumed = nutrition.totals.get(nutrient)
    known = nutrition.known_subtotals.get(nutrient)
    complete = nutrition.item_count > 0 and nutrient not in nutrition.incomplete_fields and consumed is not None
    status = _status(target, nutrition.item_count, consumed if complete else None, known)
    remaining: Decimal | None = None
    to_maximum: Decimal | None = None
    excess: Decimal | None = None
    if target is not None and complete and consumed is not None:
        remaining = _gap(target.minimum, consumed)
        excess = _gap(consumed, target.maximum)
        if isinstance(target, RangeTarget):
            to_maximum = _gap(target.maximum, consumed)
    return NutrientTargetStatus(
        nutrient=nutrient,
        target=target,
        consumed=consumed if complete else None,
        known_subtotal=known,
        complete=complete,
        estimated=nutrient in nutrition.estimated_fields,
        status=status,
        remaining=remaining,
        remaining_to_maximum=to_maximum,
        excess=excess,
    )


def evaluate_targets(targets: NutritionTargets, nutrition: NutritionAggregate) -> tuple[NutrientTargetStatus, ...]:
    return tuple(evaluate_nutrient(nutrient, targets.get(nutrient), nutrition) for nutrient in NutrientField)


def _status(
    target: NutrientTarget | None, item_count: int, consumed: Decimal | None, known: Decimal | None
) -> TargetStatus:
    if target is None:
        return TargetStatus.NO_TARGET
    exact = isinstance(target, ExactTarget)
    if item_count == 0:
        return TargetStatus.NO_INTAKE_LOGGED
    if consumed is None:
        # Nutrient values are validated non-negative, so the missing items can only add to
        # the known subtotal: it is a lower bound of the real total. That proves "above" when
        # the known items alone exceed the upper bound, and nothing else.
        if known is not None and known > target.maximum:
            return TargetStatus.ABOVE_TARGET if exact else TargetStatus.ABOVE_RANGE
        return TargetStatus.INDETERMINATE
    if consumed < target.minimum:
        return TargetStatus.BELOW_TARGET if exact else TargetStatus.BELOW_RANGE
    if consumed > target.maximum:
        return TargetStatus.ABOVE_TARGET if exact else TargetStatus.ABOVE_RANGE
    return TargetStatus.TARGET_REACHED if exact else TargetStatus.WITHIN_RANGE


def _gap(upper: Decimal, lower: Decimal) -> Decimal:
    """``upper - lower`` when positive, otherwise zero."""
    with localcontext(_CONTEXT):
        difference = upper - lower
    return difference if difference > 0 else Decimal(0)


def _require_positive(value: Decimal, what: str) -> None:
    if not isinstance(value, Decimal) or not value.is_finite() or value <= 0:
        raise NutritionTargetError(f"{what} must be a finite number greater than 0")
