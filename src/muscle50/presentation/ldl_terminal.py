"""Text and JSON for LDL Nutrients v1 (saturated fat, fiber), used by `nutrition_terminal`.

Every function here returns nothing (no line, no key) when there is nothing to show: a fact,
item, meal or day without any saturated fat or fiber value or range, and a status without LDL
targets or data. So every existing output stays byte-identical until such data exists.

Text is ASCII and rounds to 0.1 for display only; JSON carries exact Decimal strings. Unknown is
spelled out ("unknown", "incomplete (known items only: ...)") and never printed as 0. Every
threshold carries its evidence ID (LDL-05, LDL-08, LDL-11) or [design]/[user setting].
"""

from __future__ import annotations

from decimal import ROUND_HALF_EVEN, Decimal
from typing import Any

from muscle50.application.nutrition_logging import DailyIntake, ItemIntake, MealIntake
from muscle50.application.nutrition_targets import DailyNutritionStatus
from muscle50.domain.ldl_nutrients import (
    FAT_KCAL_PER_G,
    LDL05_ESC_GENERAL_PERCENT,
    LDL05_REFERENCE_PERCENT,
    LDL08_REFERENCE_FIBER_G,
    FiberStatus,
    LdlStatus,
    SaturatedFatLimit,
    SaturatedFatStatus,
)
from muscle50.domain.nutrition import (
    CalculatedOptionalNutrient,
    NutrientField,
    NutritionFact,
    OptionalNutrient,
    OptionalNutrientAggregate,
)
from muscle50.domain.nutrition_targets import (
    FiberTarget,
    NutrientTarget,
    NutritionTargets,
    RangeTarget,
    SaturatedFatTarget,
)
from muscle50.infrastructure.decimal_text import decimal_to_text
from muscle50.infrastructure.nutrition_target_store import (
    fiber_target_payload,
    saturated_fat_target_payload,
    target_payload,
)

SAT = OptionalNutrient.SATURATED_FAT_G
FIBER = OptionalNutrient.FIBER_G
LABELS = {SAT: "Saturated fat", FIBER: "Fiber"}
SHORT = {SAT: "sat fat", FIBER: "fiber"}
NAMES = {SAT: "saturated fat", FIBER: "fiber"}


# --- shared helpers ---------------------------------------------------------------------------


def number(value: Decimal) -> str:
    """0.1 display rounding (half-even), trailing zeros dropped; JSON keeps the exact value."""
    text = decimal_to_text(value.quantize(Decimal("0.1"), rounding=ROUND_HALF_EVEN))
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def grams(value: Decimal) -> str:
    # A non-zero amount must not display as 0 g.
    if value > 0 and value.quantize(Decimal("0.1"), rounding=ROUND_HALF_EVEN) == 0:
        return "<0.1 g"
    return f"{number(value)} g"


def decimal_text(value: Decimal | None) -> str | None:
    return decimal_to_text(value) if value is not None else None


def aggregate_value(aggregate: OptionalNutrientAggregate) -> str:
    """Like the four nutrients' `_aggregate_value`: a total, or the known subtotal marked incomplete."""
    if aggregate.item_count == 0:
        return "no items"
    estimated = " (estimated)" if aggregate.estimated else ""
    if aggregate.complete and aggregate.total is not None:
        return f"{grams(aggregate.total)}{estimated}"
    if aggregate.known_subtotal is None:
        return "incomplete (no item has a value)"
    return f"incomplete (known items only: {grams(aggregate.known_subtotal)}{estimated})"


def _has_data(aggregates: tuple[OptionalNutrientAggregate, ...]) -> bool:
    return any(aggregate.has_data for aggregate in aggregates)


def _item_has_value(item: ItemIntake, nutrient: OptionalNutrient) -> bool:
    return any(selection.nutrient is nutrient and selection.value is not None for selection in item.optional)


def missing_item_texts(meals: tuple[MealIntake, ...], nutrient: OptionalNutrient) -> list[str]:
    """`<meal_id> item <n> <name> (<food id>)` for every item without a value, in day order."""
    texts = []
    for meal in meals:
        for item in meal.items:
            if _item_has_value(item, nutrient):
                continue
            food_id = item.item.food_profile_id
            name = f"{item.item.food_name} ({food_id})" if food_id is not None else item.item.food_name
            texts.append(f"{meal.meal.meal_id} item {item.item.sequence} {name}")
    return texts


def missing_item_payloads(meals: tuple[MealIntake, ...], nutrient: OptionalNutrient) -> list[dict[str, Any]]:
    return [
        {
            "meal_id": meal.meal.meal_id,
            "sequence": item.item.sequence,
            "food_id": item.item.food_profile_id,
            "food_name": item.item.food_name,
        }
        for meal in meals
        for item in meal.items
        if not _item_has_value(item, nutrient)
    ]


# --- facts (food list/show) ----------------------------------------------------------------------


def fact_lines(fact: NutritionFact, indent: str) -> list[str]:
    """`LDL per 40 g: sat fat 0.5 g | fiber unknown`, only for a fact with saturated fat or fiber."""
    if not fact.optional:
        return []
    parts = []
    for nutrient in OptionalNutrient:
        amount = fact.optional_amount(nutrient)
        if amount is None:
            parts.append(f"{SHORT[nutrient]} unknown")
        elif amount.value is not None:
            parts.append(f"{SHORT[nutrient]} {grams(amount.value)}")
        elif amount.minimum is not None and amount.maximum is not None:
            parts.append(f"{SHORT[nutrient]} estimated {number(amount.minimum)}-{grams(amount.maximum)}")
    basis = f"{decimal_to_text(fact.basis_quantity)} {fact.basis_unit.value}"
    return [f"{indent}LDL per {basis}: {' | '.join(parts)}"]


def fact_payload(fact: NutritionFact) -> dict[str, Any]:
    """The trailing `ldl_nutrients` key of a fact entry; empty (no key) for a fact without them."""
    if not fact.optional:
        return {}
    entries: dict[str, Any] = {}
    for nutrient in OptionalNutrient:
        amount = fact.optional_amount(nutrient)
        entries[nutrient.value] = (
            None
            if amount is None
            else {
                "value": decimal_text(amount.value),
                "minimum": decimal_text(amount.minimum),
                "maximum": decimal_text(amount.maximum),
            }
        )
    return {"ldl_nutrients": entries}


# --- items, meals and days ------------------------------------------------------------------------


def _selection_text(selection: CalculatedOptionalNutrient | None, nutrient: OptionalNutrient) -> str:
    if selection is None:
        return f"{SHORT[nutrient]} unknown"
    if selection.value is not None:
        return f"{SHORT[nutrient]} {grams(selection.value)}"
    if selection.minimum is not None and selection.maximum is not None:
        return f"{SHORT[nutrient]} estimated {number(selection.minimum)}-{grams(selection.maximum)}"
    return f"{SHORT[nutrient]} unknown"


def item_lines(item: ItemIntake) -> list[str]:
    """`     LDL: sat fat 0.5 g | fiber unknown`, only for an item with saturated fat or fiber."""
    if not item.optional:
        return []
    selections = {selection.nutrient: selection for selection in item.optional}
    parts = [_selection_text(selections.get(nutrient), nutrient) for nutrient in OptionalNutrient]
    return [f"     LDL: {' | '.join(parts)}"]


def meal_lines(intake: MealIntake) -> list[str]:
    """`  LDL nutrients: sat fat 13 g | fiber incomplete (...)`, only for a meal with such data."""
    aggregates = intake.summary.optional
    if not _has_data(aggregates):
        return []
    parts = [f"{SHORT[aggregate.nutrient]} {aggregate_value(aggregate)}" for aggregate in aggregates]
    return [f"  LDL nutrients: {' | '.join(parts)}"]


def day_lines(intake: DailyIntake) -> list[str]:
    """The block at the end of `nutrition day`, only for a day with saturated fat or fiber data."""
    aggregates = intake.summary.optional
    if not intake.meals or not _has_data(aggregates):
        return []
    lines = ["", "LDL-related nutrients (consumed; compare: muscle50 nutrition status):"]
    lines.extend(f"  {LABELS[aggregate.nutrient]:<13} {aggregate_value(aggregate)}" for aggregate in aggregates)
    lines.extend(unknown_lines(intake.meals))
    return lines


def unknown_lines(meals: tuple[MealIntake, ...]) -> list[str]:
    lines = []
    for nutrient in OptionalNutrient:
        missing = missing_item_texts(meals, nutrient)
        if missing:
            lines.append(f"  Unknown, not 0: {NAMES[nutrient]}: {'; '.join(missing)}")
    return lines


def item_payload(item: ItemIntake) -> dict[str, Any]:
    """The trailing `ldl_nutrients` key of an item; empty (no key) for an item without them."""
    if not item.optional:
        return {}
    selections = {selection.nutrient: selection for selection in item.optional}
    entries: dict[str, Any] = {}
    for nutrient in OptionalNutrient:
        selection = selections.get(nutrient)
        entries[nutrient.value] = (
            None
            if selection is None
            else {
                "value": decimal_text(selection.value),
                "minimum": decimal_text(selection.minimum),
                "maximum": decimal_text(selection.maximum),
                "fact_id": selection.fact_id,
                "source_type": selection.provenance.source_type.value,
                "accuracy": selection.provenance.accuracy.value,
            }
        )
    return {"ldl_nutrients": entries}


def aggregate_payload(aggregate: OptionalNutrientAggregate, meals: tuple[MealIntake, ...]) -> dict[str, Any]:
    return {
        "complete": aggregate.complete,
        "estimated": aggregate.estimated,
        "consumed": decimal_text(aggregate.total if aggregate.complete else None),
        "known_subtotal": decimal_text(aggregate.known_subtotal),
        "missing_items": missing_item_payloads(meals, aggregate.nutrient),
    }


def meal_payload(intake: MealIntake) -> dict[str, Any]:
    """The trailing `ldl_nutrients` key of a meal; empty (no key) for a meal without such data."""
    aggregates = intake.summary.optional
    if not _has_data(aggregates):
        return {}
    return {
        "ldl_nutrients": {aggregate.nutrient.value: aggregate_payload(aggregate, (intake,)) for aggregate in aggregates}
    }


def day_payload(intake: DailyIntake) -> dict[str, Any]:
    """The trailing `ldl_nutrients` key of `nutrition day --json`; empty for a day without such data."""
    aggregates = intake.summary.optional
    if not intake.meals or not _has_data(aggregates):
        return {}
    return {
        "ldl_nutrients": {
            aggregate.nutrient.value: aggregate_payload(aggregate, intake.meals) for aggregate in aggregates
        }
    }


# --- targets ---------------------------------------------------------------------------------------

_LDL05 = "LDL-05"
_LDL08 = "LDL-08"
_LDL11 = "LDL-11"
_SAT_REFERENCE = f"[user setting; {_LDL05} reference < {decimal_to_text(LDL05_REFERENCE_PERCENT)} %]"
_FIBER_REFERENCE = f"[user setting; {_LDL08} reference >= {decimal_to_text(LDL08_REFERENCE_FIBER_G)} g]"
_ESC_GENERAL_LINE = (
    f"    {_LDL05} also gives < {decimal_to_text(LDL05_ESC_GENERAL_PERCENT)} % for the general population (ESC) "
    f"[{_LDL05}]"
)
_FIBER_ADVICE = (
    ("fiber_foods", f"    foods with fiber: oats, mixed grains, legumes [{_LDL08}; advice only]", _LDL08),
    ("ldl_diet_pattern", f"    LDL diet pattern also uses soy/tofu protein and nuts [{_LDL11}; advice only]", _LDL11),
)


def target_lines(targets: NutritionTargets) -> list[str]:
    """`target show/set` lines after the four nutrients, only while an LDL target is set."""
    if not targets.ldl.is_set:
        return []
    saturated, fiber = targets.ldl.saturated_fat_g, targets.ldl.fiber_g
    if saturated is None:
        sat_text = "not set"
    else:
        sat_text = f"< {decimal_to_text(saturated.max_energy_percent)} % of energy {_SAT_REFERENCE}"
        if saturated.meal_note_percent is not None:
            sat_text += (
                f"; meal note at {decimal_to_text(saturated.meal_note_percent)} % of the day limit [user setting]"
            )
    fiber_text = "not set" if fiber is None else f">= {decimal_to_text(fiber.minimum)} g/day {_FIBER_REFERENCE}"
    lines = [f"  {LABELS[SAT]:<13} {sat_text}", f"  {LABELS[FIBER]:<13} {fiber_text}"]
    if saturated is not None and saturated.max_energy_percent == LDL05_ESC_GENERAL_PERCENT:
        lines.append(_ESC_GENERAL_LINE)
    return lines


def _saturated_target_payload(target: SaturatedFatTarget | None) -> dict[str, Any] | None:
    if target is None:
        return None
    notes = (
        [{"id": _LDL05, "code": "esc_general_population", "value": decimal_to_text(LDL05_ESC_GENERAL_PERCENT)}]
        if target.max_energy_percent == LDL05_ESC_GENERAL_PERCENT
        else []
    )
    return {
        **saturated_fat_target_payload(target),
        "source": "user_setting",
        "reference": {"id": _LDL05, "value": decimal_to_text(LDL05_REFERENCE_PERCENT)},
        "reference_notes": notes,
    }


def _fiber_target_payload(target: FiberTarget | None) -> dict[str, Any] | None:
    if target is None:
        return None
    return {
        **fiber_target_payload(target),
        "source": "user_setting",
        "reference": {"id": _LDL08, "value": decimal_to_text(LDL08_REFERENCE_FIBER_G)},
    }


# --- daily status ----------------------------------------------------------------------------------


def shows_status(status: DailyNutritionStatus) -> bool:
    """D5: the block appears when an LDL target is set or the day has saturated fat / fiber data."""
    return status.ldl is not None and (status.targets.ldl.is_set or status.ldl.has_data)


def status_lines(status: DailyNutritionStatus) -> list[str]:
    ldl = status.ldl
    if ldl is None or not shows_status(status):
        return []
    lines = ["", "LDL-related nutrients (your targets; advice only, not a diagnosis):"]
    lines.extend(_saturated_fat_lines(ldl.saturated_fat))
    lines.extend(_fiber_lines(ldl.fiber))
    lines.extend(unknown_lines(status.intake.meals))
    limit = ldl.saturated_fat.limit
    for note in ldl.meal_notes:
        day_limit = f" {grams(limit.high)}" if limit is not None else ""
        lines.append(
            f"  Meal note: {note.meal_id} saturated fat {grams(note.saturated_fat_g)} = "
            f"{number(note.share_of_day_limit * _HUNDRED)} % of the day limit{day_limit}, at or above your setting "
            f"{decimal_to_text(note.threshold_percent)} % [user setting; advice only]"
        )
    return lines


_HUNDRED = Decimal(100)
_CONTINUATION = " " * 16


def _kcal_text(target: NutrientTarget) -> str:
    if isinstance(target, RangeTarget):
        return f"{decimal_to_text(target.minimum)}-{decimal_to_text(target.maximum)} (range)"
    return decimal_to_text(target.minimum)


def _limit_text(limit: SaturatedFatLimit) -> str:
    if limit.low == limit.high:
        return grams(limit.high)
    return f"{number(limit.low)}-{grams(limit.high)}"


def _saturated_fat_lines(sat: SaturatedFatStatus) -> list[str]:
    head = f"  {LABELS[SAT]:<13} {aggregate_value(sat.aggregate)}"
    target = sat.target
    if target is None:
        return [f"{head}; no target"]
    lines = [f"{head}; limit < {decimal_to_text(target.max_energy_percent)} % of energy {_SAT_REFERENCE}"]
    if target.max_energy_percent == LDL05_ESC_GENERAL_PERCENT:
        lines.append(_ESC_GENERAL_LINE)
    limit = sat.limit
    if sat.status is LdlStatus.NO_KCAL_TARGET or limit is None:
        lines.append(
            f"{_CONTINUATION}= no gram limit without a kcal target (muscle50 nutrition target set kcal ...): not judged"
        )
        return lines
    lines.append(
        f"{_CONTINUATION}= under {_limit_text(limit)} at your kcal target {_kcal_text(limit.kcal_target)} "
        f"[design: {decimal_to_text(FAT_KCAL_PER_G)} kcal/g]: {_saturated_fat_status_text(sat, limit)}"
    )
    if sat.logged_energy_percent is not None:
        lines.append(
            f"    logged energy share: {number(sat.logged_energy_percent)} % (info only, not used for the status) "
            f"[{_LDL05}; design: {decimal_to_text(FAT_KCAL_PER_G)} kcal/g]"
        )
    return lines


def _saturated_fat_status_text(sat: SaturatedFatStatus, limit: SaturatedFatLimit) -> str:
    kind = sat.status
    if kind is LdlStatus.NO_INTAKE_LOGGED:
        return "no meals logged"
    if kind is LdlStatus.INDETERMINATE:
        return "cannot tell yet (incomplete)"
    if kind is LdlStatus.WITHIN_LIMIT and sat.remaining_to_limit is not None:
        return f"within limit, {grams(sat.remaining_to_limit)} below it"
    if kind is LdlStatus.ABOVE_LIMIT:
        if sat.excess is None:
            return "above limit (the known items alone reach it)"
        return f"at or above limit, {grams(sat.excess)} over"
    if kind is LdlStatus.BETWEEN_LIMITS:
        return (
            f"between the limits of your kcal range ({_limit_text(limit)}): depends on where in your kcal range you end"
        )
    return kind.value


def _fiber_lines(fiber: FiberStatus) -> list[str]:
    head = f"  {LABELS[FIBER]:<13} {aggregate_value(fiber.aggregate)}"
    target = fiber.target
    if target is None:
        return [f"{head}; no target"]
    kind = fiber.status
    if kind is LdlStatus.NO_INTAKE_LOGGED:
        text = "no meals logged"
    elif kind is LdlStatus.INDETERMINATE:
        text = "cannot tell yet (incomplete)"
    elif kind is LdlStatus.BELOW_TARGET and fiber.remaining is not None:
        text = f"below target, {grams(fiber.remaining)} to go"
    elif kind is LdlStatus.TARGET_REACHED:
        text = "target reached" if fiber.aggregate.complete else "target reached (the known items alone reach it)"
    else:
        text = kind.value
    lines = [f"{head}; target >= {decimal_to_text(target.minimum)} g/day {_FIBER_REFERENCE}: {text}"]
    if _fiber_advice(fiber):
        lines.extend(line for _code, line, _evidence in _FIBER_ADVICE)
    return lines


def _fiber_advice(fiber: FiberStatus) -> bool:
    return fiber.target is not None and fiber.status in (LdlStatus.BELOW_TARGET, LdlStatus.INDETERMINATE)


def status_payload(status: DailyNutritionStatus) -> dict[str, Any]:
    """The trailing `ldl_nutrients` key of `nutrition status --json`; empty when the block is not shown."""
    ldl = status.ldl
    if ldl is None or not shows_status(status):
        return {}
    meals = status.intake.meals
    sat, fiber = ldl.saturated_fat, ldl.fiber
    limit = sat.limit
    return {
        "ldl_nutrients": {
            "advice_only": True,
            "saturated_fat_g": {
                "target": _saturated_target_payload(sat.target),
                "limit_g": None
                if limit is None
                else {"low": decimal_to_text(limit.low), "high": decimal_to_text(limit.high)},
                "limit_basis": None
                if sat.target is None
                else {
                    "calories_kcal_target": target_payload(status.targets.get(NutrientField.CALORIES_KCAL)),
                    "kcal_per_g": decimal_to_text(FAT_KCAL_PER_G),
                    "evidence": ["design"],
                },
                "status": sat.status.value,
                "complete": sat.aggregate.complete,
                "estimated": sat.aggregate.estimated,
                "consumed": decimal_text(sat.aggregate.total if sat.aggregate.complete else None),
                "known_subtotal": decimal_text(sat.aggregate.known_subtotal),
                "remaining_to_limit": decimal_text(sat.remaining_to_limit),
                "excess": decimal_text(sat.excess),
                "logged_energy_percent": decimal_text(sat.logged_energy_percent),
                "missing_items": missing_item_payloads(meals, SAT),
            },
            "fiber_g": {
                "target": _fiber_target_payload(fiber.target),
                "status": fiber.status.value,
                "complete": fiber.aggregate.complete,
                "estimated": fiber.aggregate.estimated,
                "consumed": decimal_text(fiber.aggregate.total if fiber.aggregate.complete else None),
                "known_subtotal": decimal_text(fiber.aggregate.known_subtotal),
                "remaining": decimal_text(fiber.remaining),
                "missing_items": missing_item_payloads(meals, FIBER),
                "advice": [{"code": code, "evidence": [evidence]} for code, _line, evidence in _FIBER_ADVICE]
                if _fiber_advice(fiber)
                else [],
            },
            "meal_notes": [
                {
                    "meal_id": note.meal_id,
                    "code": "high_saturated_fat",
                    "saturated_fat_g": decimal_to_text(note.saturated_fat_g),
                    "share_of_day_limit": decimal_to_text(note.share_of_day_limit),
                    "threshold": {"kind": "user_setting", "percent": decimal_to_text(note.threshold_percent)},
                }
                for note in ldl.meal_notes
            ],
        }
    }
