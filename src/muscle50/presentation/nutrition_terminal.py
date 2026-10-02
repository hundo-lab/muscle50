"""Terminal and JSON output for Nutrition Logging, targets and daily status.

Text rounds to 0.1 for display only. JSON carries the exact Decimal values as canonical
strings, lists nutrient sets in NutrientField order, and is byte-stable for identical data.
Text stays ASCII apart from user-entered food names (cp949 consoles cannot print dashes/arrows).
"""

from __future__ import annotations

import json
from datetime import time
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Any

from muscle50.application.nutrition_logging import DailyIntake, ItemIntake, MealIntake
from muscle50.application.nutrition_targets import DailyNutritionStatus, NutrientDayStatus
from muscle50.domain.nutrition import (
    FoodNutritionProfile,
    NutrientField,
    NutritionAggregate,
    NutritionFact,
    NutritionValue,
)
from muscle50.domain.nutrition_targets import (
    NutrientTarget,
    NutrientTargetStatus,
    NutritionTargets,
    RangeTarget,
    TargetStatus,
)
from muscle50.infrastructure.decimal_text import decimal_to_text
from muscle50.infrastructure.nutrition_target_store import target_payload

_LABELS = {
    NutrientField.CALORIES_KCAL: "kcal",
    NutrientField.PROTEIN_G: "Protein",
    NutrientField.CARBOHYDRATE_G: "Carbohydrate",
    NutrientField.FAT_G: "Fat",
}
_SHORT = {
    NutrientField.CALORIES_KCAL: "kcal",
    NutrientField.PROTEIN_G: "P",
    NutrientField.CARBOHYDRATE_G: "C",
    NutrientField.FAT_G: "F",
}
_NAMES = {
    NutrientField.CALORIES_KCAL: "kcal",
    NutrientField.PROTEIN_G: "protein",
    NutrientField.CARBOHYDRATE_G: "carbohydrate",
    NutrientField.FAT_G: "fat",
}
_SCOPE_NOTE = "Consumed intake only. Compare with targets: muscle50 nutrition status"


# --- food catalog -------------------------------------------------------------------------


def render_food_list(profiles: tuple[FoodNutritionProfile, ...]) -> str:
    if not profiles:
        return "No foods in the catalog yet. Add one with: muscle50 nutrition food add --help"
    lines = [f"Foods ({len(profiles)}):"]
    for profile in profiles:
        lines.append(f"  {profile.profile_id}  {profile.name}")
        for fact in _active_facts(profile):
            lines.append(f"    {_fact_line(fact)}")
    return "\n".join(lines)


def render_food(profile: FoodNutritionProfile) -> str:
    lines = [f"Food {profile.profile_id}: {profile.name}"]
    if profile.aliases:
        lines.append(f"  aliases: {', '.join(profile.aliases)}")
    active = {fact.fact_id for fact in _active_facts(profile)}
    for fact in profile.facts:
        state = "active" if fact.fact_id in active else "superseded"
        lines.append(f"  fact {fact.fact_id} ({state})")
        lines.append(f"    {_fact_line(fact)}")
        lines.append(f"    reference: {fact.provenance.source_reference}")
        lines.append(f"    recorded: {fact.provenance.created_at.isoformat()}")
    return "\n".join(lines)


def render_food_list_json(profiles: tuple[FoodNutritionProfile, ...]) -> str:
    return _dumps({"foods": [_food_payload(profile) for profile in profiles]})


def render_food_json(profile: FoodNutritionProfile) -> str:
    return _dumps(_food_payload(profile))


# --- meals and days -----------------------------------------------------------------------


def render_logged_meal(intake: MealIntake) -> str:
    day = intake.meal.eaten_at.date().isoformat()
    lines = [f"Recorded meal {intake.meal.meal_id}.", ""]
    lines.extend(_meal_lines(intake))
    lines.extend(["", f"Whole day: muscle50 nutrition day --date {day}"])
    return "\n".join(lines)


def render_logged_meal_json(intake: MealIntake) -> str:
    return _dumps(_meal_payload(intake))


def render_daily_intake(intake: DailyIntake) -> str:
    lines = [f"Nutrition intake {intake.day.isoformat()} (UTC{intake.timezone_name})", _SCOPE_NOTE]
    if not intake.meals:
        lines.extend(["", "No meals recorded for this day."])
        return "\n".join(lines)
    for meal in intake.meals:
        lines.append("")
        lines.extend(_meal_lines(meal))
    nutrition = intake.summary.nutrition
    meal_word = "meal" if len(intake.meals) == 1 else "meals"
    item_word = "item" if nutrition.item_count == 1 else "items"
    lines.extend(["", f"Consumed ({len(intake.meals)} {meal_word}, {nutrition.item_count} {item_word}):"])
    for nutrient in NutrientField:
        lines.append(f"  {_LABELS[nutrient]:<13} {_aggregate_value(nutrition, nutrient)}")
    if nutrition.incomplete_fields:
        lines.append("Incomplete: these totals are not precise because an item has no value for them:")
        for nutrient in _ordered(nutrition.incomplete_fields):
            sources = [
                f"{meal.meal.meal_id} item {item.item.sequence} {_item_name(item)}"
                for meal in intake.meals
                for item in meal.items
                if nutrient in item.missing_fields
            ]
            lines.append(f"  {_NAMES[nutrient]}: {'; '.join(sources)}")
    if nutrition.estimated_fields:
        names = ", ".join(_NAMES[nutrient] for nutrient in _ordered(nutrition.estimated_fields))
        lines.append(f"Estimated: {names} include values from facts marked estimated.")
    return "\n".join(lines)


def render_daily_intake_json(intake: DailyIntake) -> str:
    return _dumps(
        {
            "date": intake.day.isoformat(),
            "timezone": intake.timezone_name,
            "scope": "intake_only",
            "meals": [_meal_payload(meal) for meal in intake.meals],
            "total": _aggregate_payload(intake.summary.nutrition),
        }
    )


def _meal_lines(intake: MealIntake) -> list[str]:
    meal = intake.meal
    local = meal.eaten_at
    when = (
        f"{local.date().isoformat()} {local.strftime('%H:%M')}"
        if _time_recorded(intake)
        else f"{local.date().isoformat()}, time not recorded"
    )
    lines = [f"[{meal.meal_type.value}] {meal.meal_id} ({when})"]
    for item in intake.items:
        lines.append(f"  {item.item.sequence}. {_item_name(item)} {_quantity(item)}: {_item_values(item)}")
        lines.append(f"     source: {_item_sources(item)}")
        if item.missing_fields:
            lines.append(f"     missing: {', '.join(_NAMES[nutrient] for nutrient in item.missing_fields)}")
    nutrition = intake.summary.nutrition
    totals = " | ".join(f"{_SHORT[nutrient]} {_aggregate_value(nutrition, nutrient)}" for nutrient in NutrientField)
    lines.append(f"  Meal total: {totals}")
    return lines


def _item_values(item: ItemIntake) -> str:
    parts = []
    for nutrient in NutrientField:
        selection = item.calculated.get(nutrient) if item.calculated is not None else None
        if selection is None or selection.value is None:
            parts.append(f"{_SHORT[nutrient]} missing")
            continue
        # Exact/estimated is shown once per item on its "source:" line.
        parts.append(f"{_SHORT[nutrient]} {_amount(selection.value, nutrient)}")
    return " | ".join(parts)


def _item_sources(item: ItemIntake) -> str:
    labels: list[str] = []
    for fact in item.item.nutrition_facts:
        label = f"{fact.provenance.source_type.value}/{fact.provenance.accuracy.value}"
        if label not in labels:
            labels.append(label)
    return ", ".join(labels) if labels else "no nutrition facts"


def _aggregate_value(nutrition: NutritionAggregate, nutrient: NutrientField) -> str:
    if nutrition.item_count == 0:
        return "no items"
    total = nutrition.totals.get(nutrient)
    estimated = " (estimated)" if nutrient in nutrition.estimated_fields else ""
    if total is not None:
        return f"{_amount(total, nutrient)}{estimated}"
    known = nutrition.known_subtotals.get(nutrient)
    if known is None:
        return "incomplete (no item has a value)"
    return f"incomplete (known items only: {_amount(known, nutrient)}{estimated})"


def _fact_line(fact: NutritionFact) -> str:
    values = " | ".join(
        f"{_SHORT[nutrient]} "
        + (_amount(value, nutrient) if (value := fact.values.get(nutrient)) is not None else "unknown")
        for nutrient in NutrientField
    )
    provenance = fact.provenance
    return (
        f"per {decimal_to_text(fact.basis_quantity)} {fact.basis_unit.value}: {values}  "
        f"[{provenance.source_type.value}/{provenance.accuracy.value}]"
    )


def _amount(value: Decimal, nutrient: NutrientField) -> str:
    rounded = value.quantize(Decimal("0.1"), rounding=ROUND_HALF_EVEN)
    text = decimal_to_text(rounded)
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text if nutrient is NutrientField.CALORIES_KCAL else f"{text} g"


def _item_name(item: ItemIntake) -> str:
    food_id = item.item.food_profile_id
    return f"{item.item.food_name} ({food_id})" if food_id is not None else item.item.food_name


def _quantity(item: ItemIntake) -> str:
    quantity, unit = item.item.quantity, item.item.quantity_unit
    if quantity is None or unit is None:
        return "(no quantity)"
    return f"{decimal_to_text(quantity)} {unit.value}"


def _time_recorded(intake: MealIntake) -> bool:
    # LogMeal stores meals entered without --time at local 00:00.
    return intake.meal.eaten_at.timetz().replace(tzinfo=None) != time(0)


def _active_facts(profile: FoodNutritionProfile) -> tuple[NutritionFact, ...]:
    superseded = {fact.supersedes_fact_id for fact in profile.facts if fact.supersedes_fact_id is not None}
    return tuple(fact for fact in profile.facts if fact.fact_id not in superseded)


def _ordered(fields: frozenset[NutrientField]) -> list[NutrientField]:
    return [nutrient for nutrient in NutrientField if nutrient in fields]


# --- targets and daily status --------------------------------------------------------------


def render_targets(targets: NutritionTargets) -> str:
    lines = ["Daily nutrition targets (the same targets apply to every date):"]
    for nutrient in NutrientField:
        lines.append(f"  {_LABELS[nutrient]:<13} {_target_text(targets.get(nutrient), nutrient)}")
    if all(targets.get(nutrient) is None for nutrient in NutrientField):
        lines.append("No targets set. See: muscle50 nutrition target set --help")
    return "\n".join(lines)


def render_targets_json(targets: NutritionTargets) -> str:
    return _dumps({"targets": _targets_payload(targets)})


def render_nutrition_status(status: DailyNutritionStatus) -> str:
    intake = status.intake
    nutrition = intake.summary.nutrition
    lines = [
        f"Nutrition status {intake.day.isoformat()} (UTC{intake.timezone_name})",
        "Logged intake compared with the currently configured daily targets.",
        "",
    ]
    if intake.meals:
        meal_word = "meal" if len(intake.meals) == 1 else "meals"
        item_word = "item" if nutrition.item_count == 1 else "items"
        lines.append(f"Logged: {len(intake.meals)} {meal_word}, {nutrition.item_count} {item_word}")
    else:
        lines.append("No meals recorded for this day.")
    for day_status in status.nutrients:
        nutrient = day_status.status.nutrient
        target = day_status.status.target
        consumed = _aggregate_value(nutrition, nutrient)
        if target is None:
            lines.append(f"  {_LABELS[nutrient]:<13} {consumed}; no target")
        else:
            lines.append(
                f"  {_LABELS[nutrient]:<13} {consumed}; target {_target_text(target, nutrient)}: "
                f"{_status_text(day_status.status)}"
            )
    incomplete = [day_status for day_status in status.nutrients if day_status.missing_items]
    if incomplete:
        lines.append("Incomplete: no exact total or remaining amount, because an item has no value for:")
        for day_status in incomplete:
            sources = [
                f"{item.meal_id} item {item.sequence} "
                + (f"{item.food_name} ({item.food_id})" if item.food_id is not None else item.food_name)
                for item in day_status.missing_items
            ]
            lines.append(f"  {_NAMES[day_status.status.nutrient]}: {'; '.join(sources)}")
    if nutrition.estimated_fields:
        names = ", ".join(_NAMES[nutrient] for nutrient in _ordered(nutrition.estimated_fields))
        lines.append(f"Estimated: {names} include values from facts marked estimated.")
    if all(status.targets.get(nutrient) is None for nutrient in NutrientField):
        lines.append("No targets set. See: muscle50 nutrition target set --help")
    return "\n".join(lines)


def render_nutrition_status_json(status: DailyNutritionStatus) -> str:
    intake = status.intake
    return _dumps(
        {
            "date": intake.day.isoformat(),
            "timezone": intake.timezone_name,
            "scope": "intake_vs_current_targets",
            "meal_count": len(intake.meals),
            "item_count": intake.summary.nutrition.item_count,
            "nutrients": {
                day_status.status.nutrient.value: _nutrient_status_payload(day_status)
                for day_status in status.nutrients
            },
        }
    )


def _target_text(target: NutrientTarget | None, nutrient: NutrientField) -> str:
    # Targets are user-entered, so they are shown exactly rather than rounded.
    unit = "" if nutrient is NutrientField.CALORIES_KCAL else " g"
    if target is None:
        return "not set"
    if isinstance(target, RangeTarget):
        return f"{decimal_to_text(target.minimum)}-{decimal_to_text(target.maximum)}{unit} (range)"
    return f"{decimal_to_text(target.value)}{unit} (exact)"


def _status_text(status: NutrientTargetStatus) -> str:
    nutrient = status.nutrient

    def amount(value: Decimal | None) -> str:
        if value is None:
            return "unknown"
        # A non-zero gap must not display as 0 ("below target, 0 g to go").
        if 0 < value < Decimal("0.05"):
            return "<0.1" if nutrient is NutrientField.CALORIES_KCAL else "<0.1 g"
        return _amount(value, nutrient)

    kind = status.status
    if kind is TargetStatus.NO_INTAKE_LOGGED:
        return "no meals logged"
    if kind is TargetStatus.INDETERMINATE:
        return "cannot tell yet (incomplete); remaining unknown"
    if kind is TargetStatus.BELOW_TARGET:
        return f"below target, {amount(status.remaining)} to go"
    if kind is TargetStatus.TARGET_REACHED:
        return "target reached"
    if kind is TargetStatus.BELOW_RANGE:
        return f"below range, {amount(status.remaining)} to minimum, {amount(status.remaining_to_maximum)} to maximum"
    if kind is TargetStatus.WITHIN_RANGE:
        return f"within range, {amount(status.remaining_to_maximum)} left to maximum"
    if kind in (TargetStatus.ABOVE_TARGET, TargetStatus.ABOVE_RANGE):
        label = "above target" if kind is TargetStatus.ABOVE_TARGET else "above range"
        if not status.complete:
            return f"{label} (the known items alone exceed it; exact excess unknown)"
        return f"{label} by {amount(status.excess)}"
    return kind.value


# --- JSON payloads ------------------------------------------------------------------------


def _dumps(payload: dict[str, Any]) -> str:
    return json.dumps(payload, indent=2, ensure_ascii=True)


def _decimal(value: Decimal | None) -> str | None:
    return decimal_to_text(value) if value is not None else None


def _values_payload(values: NutritionValue) -> dict[str, str | None]:
    return {nutrient.value: _decimal(values.get(nutrient)) for nutrient in NutrientField}


def _fact_payload(fact: NutritionFact) -> dict[str, Any]:
    provenance = fact.provenance
    return {
        "fact_id": fact.fact_id,
        "basis_quantity": decimal_to_text(fact.basis_quantity),
        "basis_unit": fact.basis_unit.value,
        "values": _values_payload(fact.values),
        "source_type": provenance.source_type.value,
        "accuracy": provenance.accuracy.value,
        "source_reference": provenance.source_reference,
        "confidence": _decimal(provenance.confidence),
        "created_at": provenance.created_at.isoformat(),
        "has_estimate_range": fact.value_range is not None,
        "supersedes_fact_id": fact.supersedes_fact_id,
    }


def _food_payload(profile: FoodNutritionProfile) -> dict[str, Any]:
    active = {fact.fact_id for fact in _active_facts(profile)}
    return {
        "food_id": profile.profile_id,
        "name": profile.name,
        "aliases": list(profile.aliases),
        "facts": [{**_fact_payload(fact), "active": fact.fact_id in active} for fact in profile.facts],
    }


def _item_payload(item: ItemIntake) -> dict[str, Any]:
    nutrients: dict[str, Any] = {}
    for nutrient in NutrientField:
        selection = item.calculated.get(nutrient) if item.calculated is not None else None
        nutrients[nutrient.value] = (
            None
            if selection is None
            else {
                "value": _decimal(selection.value),
                "minimum": _decimal(selection.minimum),
                "maximum": _decimal(selection.maximum),
                "fact_id": selection.fact_id,
                "source_type": selection.provenance.source_type.value,
                "accuracy": selection.provenance.accuracy.value,
            }
        )
    return {
        "sequence": item.item.sequence,
        "food_id": item.item.food_profile_id,
        "food_name": item.item.food_name,
        "quantity": _decimal(item.item.quantity),
        "unit": item.item.quantity_unit.value if item.item.quantity_unit is not None else None,
        "nutrients": nutrients,
        "missing_fields": [nutrient.value for nutrient in item.missing_fields],
        "facts": [_fact_payload(fact) for fact in item.item.nutrition_facts],
    }


def _meal_payload(intake: MealIntake) -> dict[str, Any]:
    meal = intake.meal
    return {
        "meal_id": meal.meal_id,
        "meal_type": meal.meal_type.value,
        "eaten_at": meal.eaten_at.isoformat(),
        "time_recorded": _time_recorded(intake),
        "original_text": meal.original_text,
        "items": [_item_payload(item) for item in intake.items],
        "total": _aggregate_payload(intake.summary.nutrition),
    }


def _aggregate_payload(nutrition: NutritionAggregate) -> dict[str, Any]:
    value_range = nutrition.value_range
    return {
        "complete": nutrition.item_count > 0 and not nutrition.incomplete_fields,
        "item_count": nutrition.item_count,
        "totals": _values_payload(nutrition.totals),
        "known_subtotals": _values_payload(nutrition.known_subtotals),
        "incomplete_fields": [nutrient.value for nutrient in _ordered(nutrition.incomplete_fields)],
        "estimated_fields": [nutrient.value for nutrient in _ordered(nutrition.estimated_fields)],
        "estimate_range": None
        if value_range is None
        else {
            "minimum": _values_payload(value_range.minimum),
            "maximum": _values_payload(value_range.maximum),
        },
        "uncalculated_items": [
            {"meal_id": reference.meal_id, "sequence": reference.sequence} for reference in nutrition.uncalculated_items
        ],
    }


def _targets_payload(targets: NutritionTargets) -> dict[str, Any]:
    return {nutrient.value: target_payload(targets.get(nutrient)) for nutrient in NutrientField}


def _nutrient_status_payload(day_status: NutrientDayStatus) -> dict[str, Any]:
    status = day_status.status
    return {
        "target": target_payload(status.target),
        "status": status.status.value,
        "complete": status.complete,
        "estimated": status.estimated,
        "consumed": _decimal(status.consumed),
        "known_subtotal": _decimal(status.known_subtotal),
        "remaining": _decimal(status.remaining),
        "remaining_to_maximum": _decimal(status.remaining_to_maximum),
        "excess": _decimal(status.excess),
        "missing_items": [
            {"meal_id": item.meal_id, "sequence": item.sequence, "food_id": item.food_id, "food_name": item.food_name}
            for item in day_status.missing_items
        ],
    }
