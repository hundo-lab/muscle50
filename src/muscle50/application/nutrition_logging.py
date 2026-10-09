"""Nutrition Logging MVP: a personal food catalog, structured meal entry and daily intake.

Every nutrient comes from a fact the user supplied for a catalog food. Logging a meal
snapshots the food's fact history for the logged unit onto the meal item (provenance and
supersession copied verbatim), so a later catalog correction never rewrites a historical meal. Units are
never converted: a food declared per 100 g cannot be logged in packs. Missing nutrients stay
missing; totals are reported only when every item contributes the nutrient.

No targets, remaining amounts or recommendations live here; this is intake only.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, tzinfo
from decimal import Decimal
from typing import Literal

from muscle50.application.nutrition import FoodNutritionRepository, MealReader, MealRepository
from muscle50.domain.meal_history import MealHistory, timestamp_text
from muscle50.domain.nutrition import (
    GENERAL_MEAL_FOOD_ID,
    GENERAL_MEAL_NAME,
    Accuracy,
    CalculatedNutrition,
    DailyNutritionSummary,
    FoodNutritionProfile,
    Meal,
    MealItem,
    MealNutritionSummary,
    MealType,
    NutrientField,
    NutritionFact,
    NutritionProvenance,
    NutritionSourceType,
    NutritionValue,
    QuantityUnit,
    aggregate_day,
    aggregate_meal,
    is_reserved_food_reference,
    normalize_general_meal_note,
    select_preferred_fact,
)

# Letters (including Hangul), digits, "_", "." and "-": no whitespace, so an ID is one CLI token.
FOOD_ID_PATTERN = re.compile(r"\w[\w.-]*\Z")

# Only sources where a person supplied the numbers. Visual/language estimates belong to a
# future parser and are deliberately not offered by the catalog.
CATALOG_SOURCE_TYPES: tuple[NutritionSourceType, ...] = (
    NutritionSourceType.NUTRITION_LABEL,
    NutritionSourceType.USER_PROVIDED,
    NutritionSourceType.KNOWN_PRODUCT,
    NutritionSourceType.FOOD_DATABASE,
)

MEAL_TYPE_ORDER: dict[MealType, int] = {meal_type: index for index, meal_type in enumerate(MealType)}

# Nutrient names as the CLI flags spell them.
_FLAG_NAMES: dict[NutrientField, str] = {
    NutrientField.CALORIES_KCAL: "kcal",
    NutrientField.PROTEIN_G: "protein",
    NutrientField.CARBOHYDRATE_G: "carbs",
    NutrientField.FAT_G: "fat",
}


class NutritionLoggingError(ValueError):
    """A request that cannot be recorded or answered without guessing."""


@dataclass(frozen=True)
class NewFood:
    food_id: str
    name: str
    basis_quantity: Decimal
    basis_unit: QuantityUnit
    values: NutritionValue
    source_type: NutritionSourceType
    accuracy: Accuracy
    source_reference: str
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True)
class NewFoodFact:
    """A new nutrition fact version for an existing food (same fields as `NewFood`'s fact)."""

    food_id: str
    basis_quantity: Decimal
    basis_unit: QuantityUnit
    values: NutritionValue
    source_type: NutritionSourceType
    accuracy: Accuracy
    source_reference: str


@dataclass(frozen=True)
class AddedFoodFact:
    profile: FoodNutritionProfile
    fact: NutritionFact
    superseded_fact_id: str


@dataclass(frozen=True)
class MealEntryItem:
    food_id: str
    quantity: Decimal
    unit: QuantityUnit


@dataclass(frozen=True)
class GeneralMealEntry:
    """A general meal (`--general`): eaten, but its menu and nutrition are unknown; the note is only a memo."""

    note: str | None = None


MealEntry = MealEntryItem | GeneralMealEntry


@dataclass(frozen=True)
class ItemIntake:
    item: MealItem
    calculated: CalculatedNutrition | None
    # Nutrients this item cannot supply a value for, in NutrientField order.
    missing_fields: tuple[NutrientField, ...]


@dataclass(frozen=True)
class MealIntake:
    meal: Meal
    summary: MealNutritionSummary
    items: tuple[ItemIntake, ...]
    # Attached only by `nutrition meal show/void/edit/merge`; None everywhere else.
    history: MealHistory | None = None


@dataclass(frozen=True)
class FactVersionChange:
    """A repeated item whose values come from other catalog fact versions than the source item's."""

    source_sequence: int
    new_sequence: int
    food_id: str
    food_name: str
    source_versions: tuple[str, ...]
    new_versions: tuple[str, ...]


@dataclass(frozen=True)
class RepeatedMeal:
    source_meal_id: str
    intake: MealIntake
    # In item order; empty when every item uses the same catalog fact versions as its source.
    fact_changes: tuple[FactVersionChange, ...]


@dataclass(frozen=True)
class DailyIntake:
    day: date
    timezone_name: str
    meals: tuple[MealIntake, ...]
    summary: DailyNutritionSummary


class AddFood:
    def __init__(self, repository: FoodNutritionRepository, clock: Callable[[], datetime]) -> None:
        self._repository = repository
        self._clock = clock

    def execute(self, food: NewFood) -> FoodNutritionProfile:
        if FOOD_ID_PATTERN.fullmatch(food.food_id) is None:
            raise NutritionLoggingError(
                f"food id {food.food_id!r} must be one token of letters, digits, '_', '.' or '-'"
            )
        name = food.name.strip()
        if not name:
            raise NutritionLoggingError("food name must not be blank")
        _check_catalog_fact(food.source_type, food.values)
        aliases = tuple(alias.strip() for alias in food.aliases)
        # The general meal's ID and name are reserved, whether or not its profile row exists yet.
        if is_reserved_food_reference(food.food_id):
            raise NutritionLoggingError(
                f"food id {food.food_id!r} is reserved for the general meal "
                "(record one with nutrition log --general); nothing was changed"
            )
        for label in (name, *aliases):
            if is_reserved_food_reference(label):
                raise NutritionLoggingError(
                    f"name or alias {label!r} is reserved for the general meal "
                    "(record one with nutrition log --general); nothing was changed"
                )
        if self._repository.get(food.food_id) is not None:
            raise NutritionLoggingError(f"food id {food.food_id!r} already exists; nothing was changed")
        for label in (name, *aliases):
            clashes = self._repository.search(label)
            if clashes:
                owner = ", ".join(profile.profile_id for profile in clashes)
                raise NutritionLoggingError(
                    f"name or alias {label!r} is already used by food {owner}; nothing was changed"
                )
        try:
            profile = FoodNutritionProfile(
                profile_id=food.food_id,
                name=name,
                aliases=aliases,
                facts=(
                    NutritionFact(
                        fact_id=f"food:{food.food_id}:1",
                        values=food.values,
                        basis_quantity=food.basis_quantity,
                        basis_unit=food.basis_unit,
                        provenance=NutritionProvenance(
                            source_type=food.source_type,
                            accuracy=food.accuracy,
                            source_reference=food.source_reference,
                            created_at=self._clock(),
                        ),
                    ),
                ),
            )
            self._repository.save(profile)
        except ValueError as exc:
            raise NutritionLoggingError(str(exc)) from exc
        return profile


class AddFoodFact:
    """Append a new nutrition fact version to an existing food; nothing stored is changed.

    The new fact supersedes the food's current fact in the same unit, so it becomes the one
    used for every nutrient from now on. Older facts stay in the history, and meals already
    logged keep the facts snapshotted when they were logged.
    """

    def __init__(self, repository: FoodNutritionRepository, clock: Callable[[], datetime]) -> None:
        self._repository = repository
        self._clock = clock

    def execute(self, new: NewFoodFact) -> AddedFoodFact:
        _check_catalog_fact(new.source_type, new.values)
        _refuse_general_meal_food(new.food_id)
        profile = self._repository.get(new.food_id)
        if profile is None:
            raise NutritionLoggingError(
                f"no food with id {new.food_id!r}; add it first with `muscle50 nutrition food add`. "
                "Nothing was changed."
            )
        unit = new.basis_unit
        if not any(fact.basis_unit is unit for fact in profile.facts):
            units = ", ".join(sorted({fact.basis_unit.value for fact in profile.facts}))
            raise NutritionLoggingError(
                f"food {profile.profile_id!r} has nutrition per {units}, not per {unit.value}; a new fact "
                "version must use the same unit as the fact it replaces. Nothing was changed."
            )
        superseded = {fact.supersedes_fact_id for fact in profile.facts if fact.supersedes_fact_id is not None}
        current = [fact for fact in profile.facts if fact.basis_unit is unit and fact.fact_id not in superseded]
        if len(current) != 1:
            current_ids = ", ".join(fact.fact_id for fact in current)
            raise NutritionLoggingError(
                f"food {profile.profile_id!r} has {len(current)} current facts per {unit.value} ({current_ids}); "
                "cannot tell which one the new version replaces. Nothing was changed."
            )
        previous = current[0]
        # Supersession is decided per nutrient: a nutrient left unknown here would keep the old
        # fact in use for it, so the new version would not be the active fact.
        dropped = [
            nutrient
            for nutrient in NutrientField
            if new.values.get(nutrient) is None and select_preferred_fact(profile.facts, unit, nutrient) is not None
        ]
        if dropped:
            names = ", ".join(_FLAG_NAMES[nutrient] for nutrient in dropped)
            raise NutritionLoggingError(
                f"the current fact {previous.fact_id} has a value for {names}; a new version must give a number "
                "for it too (unknown cannot replace a known value). Nothing was changed."
            )
        if (
            previous.value_range is None
            and previous.values == new.values
            and previous.basis_quantity == new.basis_quantity
            and previous.provenance.source_type is new.source_type
            and previous.provenance.accuracy is new.accuracy
            and previous.provenance.source_reference == new.source_reference
        ):
            raise NutritionLoggingError(
                f"the new fact is the same as the current fact {previous.fact_id}; nothing was changed"
            )
        ids = {fact.fact_id for fact in profile.facts}
        number = len(profile.facts) + 1
        while f"food:{profile.profile_id}:{number}" in ids:
            number += 1
        try:
            fact = NutritionFact(
                fact_id=f"food:{profile.profile_id}:{number}",
                values=new.values,
                basis_quantity=new.basis_quantity,
                basis_unit=unit,
                provenance=NutritionProvenance(
                    source_type=new.source_type,
                    accuracy=new.accuracy,
                    source_reference=new.source_reference,
                    created_at=self._clock(),
                ),
                supersedes_fact_id=previous.fact_id,
            )
            history = (*profile.facts, fact)
            for nutrient in NutrientField:
                selected = select_preferred_fact(history, unit, nutrient)
                expected = fact.fact_id if new.values.get(nutrient) is not None else None
                if (selected.fact_id if selected is not None else None) != expected:
                    raise NutritionLoggingError(
                        f"the new fact would not be the active fact for {_FLAG_NAMES[nutrient]} "
                        f"(the history of {profile.profile_id!r} would select "
                        f"{selected.fact_id if selected is not None else 'nothing'}). Nothing was changed."
                    )
            stored = self._repository.append_nutrition_fact(profile.profile_id, fact)
        except NutritionLoggingError:
            raise
        except ValueError as exc:
            raise NutritionLoggingError(str(exc)) from exc
        return AddedFoodFact(stored, fact, previous.fact_id)


class ListFoods:
    def __init__(self, repository: FoodNutritionRepository) -> None:
        self._repository = repository

    def execute(self) -> tuple[FoodNutritionProfile, ...]:
        # The general meal's system profile is not a food you can log with --item.
        return tuple(profile for profile in self._repository.list_all() if not is_general_meal_profile(profile))


class ShowFood:
    def __init__(self, repository: FoodNutritionRepository) -> None:
        self._repository = repository

    def execute(self, food_id: str) -> FoodNutritionProfile:
        _refuse_general_meal_food(food_id)
        profile = self._repository.get(food_id)
        if profile is None:
            raise NutritionLoggingError(f"no food with id {food_id!r}")
        return profile


class LogMeal:
    def __init__(self, meals: MealRepository, foods: FoodNutritionRepository) -> None:
        self._meals = meals
        self._foods = foods

    def execute(
        self,
        day: date,
        meal_type: MealType,
        items: tuple[MealEntry, ...],
        *,
        timezone: tzinfo,
        eaten_time: time | None = None,
        additional: bool = False,
        repeated_from: str | None = None,
    ) -> MealIntake:
        if not items:
            raise NutritionLoggingError("a meal needs at least one item")
        existing = tuple(
            meal
            for meal in self._meals.list_eaten_between(*local_day_bounds(day, timezone))
            if meal.meal_type is meal_type
        )
        if existing and not additional:
            ids = ", ".join(meal.meal_id for meal in existing)
            raise NutritionLoggingError(
                f"{meal_type.value} on {day.isoformat()} is already recorded ({ids}); "
                "pass --additional to record another one. Nothing was changed."
            )
        meal_id = self._next_meal_id(day, meal_type)
        meal_items = tuple(
            entry_item(self._foods, meal_id, sequence, entry, label=f"item {sequence}")
            for sequence, entry in enumerate(items, start=1)
        )
        # Without --time the meal is dated, not timed: it is stored at local 00:00 of the day.
        eaten_at = datetime.combine(day, eaten_time or time(0), tzinfo=timezone)
        original_text = _structured_text(meal_type, day, eaten_time, items)
        if repeated_from is not None:
            original_text = f"repeated from {repeated_from}; {original_text}"
        try:
            meal = Meal(
                meal_id=meal_id,
                eaten_at=eaten_at,
                meal_type=meal_type,
                original_text=original_text,
                items=meal_items,
            )
            self._meals.save(meal)
        except ValueError as exc:
            raise NutritionLoggingError(str(exc)) from exc
        stored = self._meals.get(meal_id)
        if stored is None:
            raise RuntimeError(f"meal {meal_id!r} was not found after saving")
        return meal_intake(stored)

    def _next_meal_id(self, day: date, meal_type: MealType) -> str:
        number = 1
        while self._meals.get(f"{day.isoformat()}-{meal_type.value}-{number}") is not None:
            number += 1
        return f"{day.isoformat()}-{meal_type.value}-{number}"


class RepeatMeal:
    """Log a new meal with the same foods, quantities and units as an already logged meal.

    Only the source's active items are repeated (removed items are skipped, replacement items
    included), and only their food ID, quantity and unit are reused (a general meal item is
    repeated as a general meal with the same memo): the new meal is logged by
    `LogMeal`, so every item snapshots the catalog facts as they are now (a newer fact version
    is used, never the source's snapshot), and the duplicate-meal guard applies unchanged. The
    source meal is only read.
    """

    def __init__(self, meals: MealRepository, foods: FoodNutritionRepository) -> None:
        self._meals = meals
        self._foods = foods

    def execute(
        self,
        source_meal_id: str,
        day: date,
        *,
        timezone: tzinfo,
        meal_type: MealType | None = None,
        eaten_time: time | None = None,
        additional: bool = False,
    ) -> RepeatedMeal:
        source = active_meal(self._meals, source_meal_id, action="repeated")
        entries: list[MealEntry] = []
        for item in source.items:
            if item.is_general:
                # A general meal is repeated as a general meal, memo included; it has no amount or facts.
                entries.append(GeneralMealEntry(item.serving_description))
                continue
            if item.food_profile_id is None or item.quantity is None or item.quantity_unit is None:
                raise NutritionLoggingError(
                    f"item {item.sequence} of meal {source.meal_id} ({item.food_name}) has no catalog food and "
                    "quantity to repeat. Nothing was changed."
                )
            entries.append(MealEntryItem(item.food_profile_id, item.quantity, item.quantity_unit))
        intake = LogMeal(self._meals, self._foods).execute(
            day,
            meal_type or source.meal_type,
            tuple(entries),
            timezone=timezone,
            eaten_time=eaten_time,
            additional=additional,
            repeated_from=source.meal_id,
        )
        changes = []
        # LogMeal numbers the items 1..n in entry order, so they pair with the source items in order.
        for old, new in zip(meal_intake(source).items, intake.items, strict=True):
            old_versions, new_versions = catalog_fact_versions(old), catalog_fact_versions(new)
            if old_versions != new_versions:
                changes.append(
                    FactVersionChange(
                        old.item.sequence,
                        new.item.sequence,
                        new.item.food_profile_id or "",
                        new.item.food_name,
                        old_versions,
                        new_versions,
                    )
                )
        return RepeatedMeal(source.meal_id, intake, tuple(changes))


class ShowMeal:
    def __init__(self, meals: MealRepository) -> None:
        self._meals = meals

    def execute(self, meal_id: str) -> MealIntake:
        return meal_intake(_existing_meal(self._meals, meal_id), self._meals.history(meal_id))


class AddMealItems:
    """Add catalog foods (or general meals) to a logged meal; the meal ID and its other items are unchanged.

    Each new item snapshots the food's facts exactly as `LogMeal` does, at the time it is added:
    an item added after a new fact version uses that version, while items already in the meal
    keep their own snapshots. All items are added in one transaction, or none is.
    """

    def __init__(self, meals: MealRepository, foods: FoodNutritionRepository) -> None:
        self._meals = meals
        self._foods = foods

    def execute(self, meal_id: str, items: tuple[MealEntry, ...]) -> MealIntake:
        if not items:
            raise NutritionLoggingError("give at least one --item to add. Nothing was changed.")
        active_meal(self._meals, meal_id)
        first = self._meals.next_item_sequence(meal_id)
        try:
            new_items = tuple(
                entry_item(self._foods, meal_id, first + index - 1, entry, label=_entry_label(entry, index))
                for index, entry in enumerate(items, start=1)
            )
            meal = self._meals.add_items(meal_id, new_items)
        except ValueError as exc:
            raise _nothing_changed(exc) from exc
        return meal_intake(meal)


class RemoveMealItem:
    """Remove one item from a logged meal; it stays stored for audit but no longer counts anywhere.

    The meal's last item cannot be removed: like `LogMeal`, a meal always has at least one item.
    """

    def __init__(self, meals: MealRepository, clock: Callable[[], datetime]) -> None:
        self._meals = meals
        self._clock = clock

    def execute(self, meal_id: str, item_number: int) -> MealIntake:
        meal = active_meal(self._meals, meal_id)
        _require_item(meal, item_number)
        if len(meal.items) == 1:
            raise NutritionLoggingError(
                f"item {item_number} is the only item of meal {meal_id}; a meal cannot be left empty. "
                "Use `muscle50 nutrition meal replace-item` to change it. Nothing was changed."
            )
        try:
            stored = self._meals.remove_item(meal_id, item_number, self._clock())
        except ValueError as exc:
            raise _nothing_changed(exc) from exc
        return meal_intake(stored)


class ReplaceMealItem:
    """Replace one item of a logged meal with a new catalog item (or a general meal), atomically.

    The new item gets the next item number (numbers are never reused) and a fresh fact snapshot;
    the old item is removed in the same transaction, so either both happen or nothing does.
    """

    def __init__(self, meals: MealRepository, foods: FoodNutritionRepository, clock: Callable[[], datetime]) -> None:
        self._meals = meals
        self._foods = foods
        self._clock = clock

    def execute(self, meal_id: str, item_number: int, entry: MealEntry) -> MealIntake:
        meal = active_meal(self._meals, meal_id)
        _require_item(meal, item_number)
        try:
            new_item = entry_item(
                self._foods,
                meal_id,
                self._meals.next_item_sequence(meal_id),
                entry,
                label="--item" if isinstance(entry, MealEntryItem) else "--general",
            )
            stored = self._meals.replace_item(meal_id, item_number, new_item, self._clock())
        except ValueError as exc:
            raise _nothing_changed(exc) from exc
        return meal_intake(stored)


def entry_item(
    foods: FoodNutritionRepository, meal_id: str, sequence: int, entry: MealEntry, *, label: str
) -> MealItem:
    """The meal item for one entry: a catalog food snapshot, or a general meal item."""
    if isinstance(entry, GeneralMealEntry):
        return general_meal_item(meal_id, sequence, entry.note, label=label)
    return snapshot_item(foods, meal_id, sequence, entry, label=label)


def general_meal_item(meal_id: str, sequence: int, note: str | None, *, label: str) -> MealItem:
    """A general meal item: the reserved profile, no quantity, no unit, no facts; the memo is kept as text.

    The repository creates the reserved profile row in the same transaction as the item.
    """
    try:
        memo = normalize_general_meal_note(note)
    except ValueError as exc:
        raise NutritionLoggingError(f"{label}: --general-note {exc}. Nothing was changed.") from exc
    return MealItem(
        meal_id=meal_id,
        sequence=sequence,
        food_name=GENERAL_MEAL_NAME,
        quantity=None,
        quantity_unit=None,
        food_profile_id=GENERAL_MEAL_FOOD_ID,
        serving_description=memo,
    )


def is_general_meal_profile(profile: FoodNutritionProfile) -> bool:
    """The general meal's system profile exactly as the repository creates it (no facts, no aliases)."""
    return (
        profile.profile_id == GENERAL_MEAL_FOOD_ID
        and profile.name == GENERAL_MEAL_NAME
        and not profile.facts
        and not profile.aliases
    )


def general_meal_item_refusal(label: str, reference: str) -> str:
    """An `--item` that names the general meal, which is recorded with --general instead."""
    return (
        f"{label} {reference!r} is the general meal, not a catalog food; record it with --general "
        "(no quantity or unit). Nothing was changed."
    )


def snapshot_item(
    foods: FoodNutritionRepository, meal_id: str, sequence: int, entry: MealEntryItem, *, label: str
) -> MealItem:
    """A meal item for `entry` carrying a snapshot of the food's current fact history in its unit."""
    if is_reserved_food_reference(entry.food_id):
        raise NutritionLoggingError(general_meal_item_refusal(label, entry.food_id))
    profile = foods.get(entry.food_id)
    if profile is None:
        raise NutritionLoggingError(f"{label}: no food with id {entry.food_id!r} (see `muscle50 nutrition food list`)")
    if all(profile.preferred_fact(entry.unit, nutrient) is None for nutrient in NutrientField):
        units = sorted({fact.basis_unit.value for fact in profile.facts})
        raise NutritionLoggingError(
            f"{label}: food {profile.profile_id!r} has nutrition per {', '.join(units) or 'nothing'}, "
            f"not per {entry.unit.value}; units are never converted. Nothing was changed."
        )

    # Copy the whole same-unit fact history, not only today's winners: supersession is decided
    # per nutrient, so the item must keep the links to select exactly what the catalog selects.
    # Numbers and provenance are verbatim; each copy's ID names its catalog fact. Supersession
    # never crosses units, so every link target is part of this copy.
    def snapshot_id(fact_id: str) -> str:
        return f"{meal_id}:{sequence}:{fact_id}"

    snapshots = tuple(
        NutritionFact(
            fact_id=snapshot_id(fact.fact_id),
            values=fact.values,
            basis_quantity=fact.basis_quantity,
            basis_unit=fact.basis_unit,
            provenance=fact.provenance,
            value_range=fact.value_range,
            supersedes_fact_id=snapshot_id(fact.supersedes_fact_id) if fact.supersedes_fact_id else None,
        )
        for fact in profile.facts
        if fact.basis_unit is entry.unit
    )
    try:
        return MealItem(
            meal_id=meal_id,
            sequence=sequence,
            food_name=profile.name,
            food_profile_id=profile.profile_id,
            quantity=entry.quantity,
            quantity_unit=entry.unit,
            nutrition_facts=snapshots,
        )
    except ValueError as exc:
        raise NutritionLoggingError(f"{label}: {exc}") from exc


class ShowDailyIntake:
    def __init__(self, meals: MealReader) -> None:
        self._meals = meals

    def execute(self, day: date, timezone: tzinfo, *, timezone_name: str) -> DailyIntake:
        meals = self._meals.list_eaten_between(*local_day_bounds(day, timezone))
        summary = aggregate_day(meals, day, timezone, timezone_name=timezone_name)
        selected = {meal.meal_id for meal in summary.meals}
        ordered = sorted(
            (meal for meal in meals if meal.meal_id in selected),
            key=lambda meal: (meal.eaten_at, MEAL_TYPE_ORDER[meal.meal_type], meal.meal_id),
        )
        return DailyIntake(day, timezone_name, tuple(meal_intake(meal) for meal in ordered), summary)


def meal_intake(meal: Meal, history: MealHistory | None = None) -> MealIntake:
    return MealIntake(meal, aggregate_meal(meal), tuple(_item_intake(item) for item in meal.items), history)


def catalog_fact_versions(item: ItemIntake) -> tuple[str, ...]:
    """The catalog facts the item's selected values were snapshotted from, in nutrient order.

    Snapshot fact IDs are "<meal_id>:<item>:<catalog fact ID>", so the catalog version is the rest.
    """
    prefix = f"{item.item.meal_id}:{item.item.sequence}:"
    selected = [selection.fact_id for selection in item.calculated.nutrients] if item.calculated is not None else []
    versions: list[str] = []
    for fact_id in selected:
        version = fact_id.removeprefix(prefix)
        if version not in versions:
            versions.append(version)
    return tuple(versions)


def local_day_bounds(day: date, timezone: tzinfo) -> tuple[datetime, datetime]:
    start = datetime.combine(day, time(0), tzinfo=timezone)
    end = datetime.combine(day + timedelta(days=1), time(0), tzinfo=timezone)
    return start, end


def offset_name(timezone: tzinfo, day: date) -> str:
    """'+09:00' style name from the UTC offset (tzname() can be a localized string on Windows)."""
    offset = datetime.combine(day, time(12), tzinfo=timezone).utcoffset() or timedelta(0)
    minutes = int(offset.total_seconds()) // 60
    sign = "-" if minutes < 0 else "+"
    hours, rest = divmod(abs(minutes), 60)
    return f"{sign}{hours:02d}:{rest:02d}"


def _refuse_general_meal_food(food_id: str) -> None:
    if food_id == GENERAL_MEAL_FOOD_ID:
        raise NutritionLoggingError(
            f"{GENERAL_MEAL_FOOD_ID!r} is the general meal ({GENERAL_MEAL_NAME}), not a catalog food: it has no "
            "nutrition facts and none can be added. Nothing was changed."
        )


def _entry_label(entry: MealEntry, index: int) -> str:
    return f"--item {index}" if isinstance(entry, MealEntryItem) else f"item {index}"


def _check_catalog_fact(source_type: NutritionSourceType, values: NutritionValue) -> None:
    if source_type not in CATALOG_SOURCE_TYPES:
        raise NutritionLoggingError(f"source {source_type.value!r} cannot be entered into the food catalog")
    if not values.has_any_value:
        raise NutritionLoggingError("at least one of kcal/protein/carbohydrate/fat must be a number")


def _existing_meal(meals: MealRepository, meal_id: str) -> Meal:
    meal = meals.get(meal_id)
    if meal is None:
        raise NutritionLoggingError(
            f"no meal with id {meal_id!r} (meal IDs are listed by `muscle50 nutrition day`). Nothing was changed."
        )
    return meal


def active_meal(meals: MealRepository, meal_id: str, *, action: Literal["changed", "repeated"] = "changed") -> Meal:
    """The logged meal ``meal_id``, refused when it was voided: a voided meal can only be shown."""
    meal = _existing_meal(meals, meal_id)
    history = meals.history(meal_id)
    void = history.void if history is not None else None
    if void is None:
        return meal
    when = timestamp_text(void.voided_at)
    if void.merged_into is not None:
        hint = f"use {void.merged_into}" if action == "changed" else f"repeat {void.merged_into} instead"
        raise NutritionLoggingError(
            f"meal {meal_id} was merged into {void.merged_into} at {when}; a voided meal cannot be {action} "
            f"({hint}). Nothing was changed."
        )
    raise NutritionLoggingError(
        f"meal {meal_id} was voided at {when}; a voided meal cannot be {action}. Nothing was changed."
    )


def _require_item(meal: Meal, item_number: int) -> None:
    numbers = [item.sequence for item in meal.items]
    if item_number not in numbers:
        listed = ", ".join(str(number) for number in numbers)
        raise NutritionLoggingError(
            f"meal {meal.meal_id} has no item {item_number} (its items are {listed}). Nothing was changed."
        )


def _nothing_changed(exc: ValueError) -> NutritionLoggingError:
    message = str(exc)
    return NutritionLoggingError(
        message if message.endswith("Nothing was changed.") else f"{message}. Nothing was changed."
    )


def _item_intake(item: MealItem) -> ItemIntake:
    calculated = item.calculated_nutrition()
    missing = tuple(
        nutrient
        for nutrient in NutrientField
        if calculated is None or (selection := calculated.get(nutrient)) is None or selection.value is None
    )
    return ItemIntake(item, calculated, missing)


def _structured_text(meal_type: MealType, day: date, eaten_time: time | None, items: tuple[MealEntry, ...]) -> str:
    when = day.isoformat() + (f" {eaten_time.strftime('%H:%M')}" if eaten_time is not None else "")
    entries = "; ".join(_entry_text(item) for item in items)
    return f"structured entry {meal_type.value} {when}: {entries}"


def _entry_text(item: MealEntry) -> str:
    if isinstance(item, GeneralMealEntry):
        note = normalize_general_meal_note(item.note)
        return "general meal" if note is None else f"general meal (note: {note})"
    return f"{item.food_id} {item.quantity} {item.unit.value}"
