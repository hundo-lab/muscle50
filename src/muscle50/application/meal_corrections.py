"""Whole-meal corrections: void a logged meal, change its date/type/time, merge two meals.

Nothing stored is rewritten. Each correction is appended (a void, a revision, copied items plus
the source's void), so the meal as it was logged stays recoverable, and the meal ID never
changes even when its date or type does. Nutrition values are never recalculated: a merge copies
the source items' snapshot facts verbatim, and refuses outright when the copy would change the
day's exact totals. A refused correction writes nothing.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import date, datetime, time, tzinfo
from enum import StrEnum

from muscle50.application.nutrition import MealRepository
from muscle50.application.nutrition_logging import (
    MealIntake,
    NutritionLoggingError,
    active_meal,
    local_day_bounds,
    meal_intake,
)
from muscle50.domain.meal_history import MealRevision, recorded_time, timestamp_text
from muscle50.domain.nutrition import Meal, MealItem, MealType, NutrientField, NutritionAggregate, aggregate_day

_NUTRIENT_NAMES: dict[NutrientField, str] = {
    NutrientField.CALORIES_KCAL: "kcal",
    NutrientField.PROTEIN_G: "protein",
    NutrientField.CARBOHYDRATE_G: "carbohydrate",
    NutrientField.FAT_G: "fat",
}


class CorrectionKind(StrEnum):
    VOID = "void"
    EDIT = "edit"
    MERGE = "merge"


@dataclass(frozen=True)
class MealCorrection:
    kind: CorrectionKind
    # The corrected meal (for a merge, the target), with its history attached.
    intake: MealIntake
    source_meal_id: str | None = None


class VoidMeal:
    """Take a logged meal out of every day total; it stays stored and visible in `meal show`."""

    def __init__(self, meals: MealRepository, clock: Callable[[], datetime]) -> None:
        self._meals = meals
        self._clock = clock

    def execute(self, meal_id: str, *, reason: str | None = None) -> MealCorrection:
        if reason is not None and not reason.strip():
            raise NutritionLoggingError("--reason must not be blank. Nothing was changed.")
        history = self._meals.history(meal_id)
        if history is not None and history.void is not None:
            raise NutritionLoggingError(
                f"meal {meal_id} is already voided (at {timestamp_text(history.void.voided_at)}). Nothing was changed."
            )
        active_meal(self._meals, meal_id)
        try:
            self._meals.void_meal(meal_id, self._clock(), reason.strip() if reason is not None else None)
        except ValueError as exc:
            raise _refused(exc) from exc
        return MealCorrection(CorrectionKind.VOID, _corrected(self._meals, meal_id))


class EditMeal:
    """Change a logged meal's date, type and/or time; the meal ID and its items stay as they are."""

    def __init__(self, meals: MealRepository, clock: Callable[[], datetime]) -> None:
        self._meals = meals
        self._clock = clock

    def execute(
        self,
        meal_id: str,
        *,
        timezone_for: Callable[[date], tzinfo],
        day: date | None = None,
        meal_type: MealType | None = None,
        eaten_time: time | None = None,
        clear_time: bool = False,
        additional: bool = False,
    ) -> MealCorrection:
        if day is None and meal_type is None and eaten_time is None and not clear_time:
            raise NutritionLoggingError(
                "give at least one of --date, --meal, --time or --no-time. Nothing was changed."
            )
        if eaten_time is not None and clear_time:
            raise NutritionLoggingError("--time and --no-time cannot be used together. Nothing was changed.")
        meal = active_meal(self._meals, meal_id)
        history = self._meals.history(meal_id)
        if history is None:
            raise RuntimeError(f"meal {meal_id!r} has no history although it exists")
        current_date, current_type = meal.eaten_at.date(), meal.meal_type
        current_time = meal.eaten_at.timetz().replace(tzinfo=None)
        new_date = day if day is not None else current_date
        new_type = meal_type if meal_type is not None else current_type
        new_time = time(0) if clear_time else eaten_time if eaten_time is not None else current_time
        if (new_date, new_type, new_time) == (current_date, current_type, current_time):
            raise NutritionLoggingError(
                f"meal {meal_id} is already {current_type.value} on {current_date.isoformat()} "
                f"({_time_text(meal.eaten_at)}); nothing to change. Nothing was changed."
            )
        # A type-only edit keeps the stored time exactly, offset included.
        if new_date == current_date and new_time == current_time:
            eaten_at = meal.eaten_at
        else:
            eaten_at = datetime.combine(new_date, new_time, tzinfo=timezone_for(new_date))
        if (new_date, new_type) != (current_date, current_type):
            # The same double-entry guard as `nutrition log`, for the slot the meal moves into.
            existing = tuple(
                other
                for other in self._meals.list_eaten_between(*local_day_bounds(new_date, timezone_for(new_date)))
                if other.meal_type is new_type and other.meal_id != meal_id
            )
            if existing and not additional:
                ids = ", ".join(other.meal_id for other in existing)
                raise NutritionLoggingError(
                    f"{new_type.value} on {new_date.isoformat()} is already recorded ({ids}); "
                    f"pass --additional to move meal {meal_id} there anyway. Nothing was changed."
                )
        number = history.revisions[-1].revision + 1 if history.revisions else 1
        try:
            revision = MealRevision(number, self._clock(), new_type, eaten_at)
            self._meals.revise_meal(meal_id, revision)
        except ValueError as exc:
            raise _refused(exc) from exc
        return MealCorrection(CorrectionKind.EDIT, _corrected(self._meals, meal_id))


class MergeMeals:
    """Move the source meal's active items into the target meal and void the source, atomically.

    The items are copied with their snapshot facts unchanged (only the IDs follow the new item
    numbers), so every value stays what was logged. Both meals must be on the same date. The
    merge is refused when it would change the day's exact totals: Decimal sums run in item
    order, and a different order can round a non-terminating value differently.
    """

    def __init__(self, meals: MealRepository, clock: Callable[[], datetime]) -> None:
        self._meals = meals
        self._clock = clock

    def execute(
        self, target_meal_id: str, source_meal_id: str, *, timezone_for: Callable[[date], tzinfo]
    ) -> MealCorrection:
        if target_meal_id == source_meal_id:
            raise NutritionLoggingError(f"cannot merge meal {target_meal_id} into itself. Nothing was changed.")
        target = active_meal(self._meals, target_meal_id)
        source = active_meal(self._meals, source_meal_id)
        target_date, source_date = target.eaten_at.date(), source.eaten_at.date()
        if target_date != source_date:
            raise NutritionLoggingError(
                f"meal {source_meal_id} is on {source_date.isoformat()} but meal {target_meal_id} is on "
                f"{target_date.isoformat()}; only meals of the same date can be merged (move one first with "
                "muscle50 nutrition meal edit). Nothing was changed."
            )
        first = self._meals.next_item_sequence(target_meal_id)
        try:
            copies = tuple(
                copy_item_for_merge(item, target_meal_id, first + index) for index, item in enumerate(source.items)
            )
            merged = replace(target, items=(*target.items, *copies))
        except ValueError as exc:
            raise _refused(exc) from exc
        changed = _changed_day_totals(self._meals, target, source, merged, timezone_for)
        if changed:
            raise NutritionLoggingError(
                f"merging {source_meal_id} into {target_meal_id} would change the exact day totals for "
                f"{', '.join(changed)} (item order changes how non-terminating values add up); the meals were "
                "left separate. Nothing was changed."
            )
        try:
            self._meals.merge_meals(
                target_meal_id,
                source_meal_id,
                copies,
                tuple(item.sequence for item in source.items),
                self._clock(),
            )
        except ValueError as exc:
            raise _refused(exc) from exc
        return MealCorrection(CorrectionKind.MERGE, _corrected(self._meals, target_meal_id), source_meal_id)


def copy_item_for_merge(item: MealItem, meal_id: str, sequence: int) -> MealItem:
    """``item`` as item ``sequence`` of meal ``meal_id``, with its snapshot facts copied verbatim.

    Snapshot fact IDs are "<meal_id>:<item>:<catalog fact ID>"; the copy keeps the catalog part
    under the new meal and item number (supersession links follow), so the copy selects exactly
    the facts the source item selected and `meal show` names the same catalog versions.
    """
    prefix = f"{item.meal_id}:{item.sequence}:"

    def copied_id(fact_id: str) -> str:
        return f"{meal_id}:{sequence}:{fact_id.removeprefix(prefix)}"

    facts = tuple(
        replace(
            fact,
            fact_id=copied_id(fact.fact_id),
            supersedes_fact_id=copied_id(fact.supersedes_fact_id) if fact.supersedes_fact_id is not None else None,
        )
        for fact in item.nutrition_facts
    )
    return replace(item, meal_id=meal_id, sequence=sequence, nutrition_facts=facts)


def _changed_day_totals(
    meals: MealRepository,
    target: Meal,
    source: Meal,
    merged: Meal,
    timezone_for: Callable[[date], tzinfo],
) -> list[str]:
    """Names of the nutrients whose exact day totals the merge would change (empty: none)."""
    day = target.eaten_at.date()
    zone = timezone_for(day)
    day_meals = meals.list_eaten_between(*local_day_bounds(day, zone))
    after_meals = (*(meal for meal in day_meals if meal.meal_id not in (target.meal_id, source.meal_id)), merged)
    before = aggregate_day(day_meals, day, zone, timezone_name="merge check").nutrition
    after = aggregate_day(after_meals, day, zone, timezone_name="merge check").nutrition
    changed = [_NUTRIENT_NAMES[nutrient] for nutrient in NutrientField if _differs(before, after, nutrient)]
    # Item references (meal ID, item number) do change by design; only the amounts must not.
    if not changed and before.item_count != after.item_count:
        changed.append("the item count")
    return changed


def _differs(before: NutritionAggregate, after: NutritionAggregate, nutrient: NutrientField) -> bool:
    def bounds(aggregate: NutritionAggregate) -> object:
        return aggregate.value_range.bounds(nutrient) if aggregate.value_range is not None else None

    return (
        before.totals.get(nutrient) != after.totals.get(nutrient)
        or before.known_subtotals.get(nutrient) != after.known_subtotals.get(nutrient)
        or bounds(before) != bounds(after)
        or (nutrient in before.incomplete_fields) != (nutrient in after.incomplete_fields)
        or (nutrient in before.estimated_fields) != (nutrient in after.estimated_fields)
    )


def _corrected(meals: MealRepository, meal_id: str) -> MealIntake:
    meal = meals.get(meal_id)
    if meal is None:
        raise RuntimeError(f"meal {meal_id!r} was not found after correcting it")
    return meal_intake(meal, meals.history(meal_id))


def _time_text(eaten_at: datetime) -> str:
    wall = recorded_time(eaten_at)
    return wall.strftime("%H:%M") if wall is not None else "time not recorded"


def _refused(exc: ValueError) -> NutritionLoggingError:
    message = str(exc)
    return NutritionLoggingError(
        message if message.endswith("Nothing was changed.") else f"{message}. Nothing was changed."
    )
