"""Telegram LLM v2.3: which meal and item a correction is about, a partly changed estimate, and the context blocks.

Pure and deterministic: no I/O and no clock. The LLM only extracts words (a food or memo text, a meal type, an
ordinal such as `아침 1식`, and `last_recorded` / `open_proposal`); the bot decides here. A target that is not exactly
one meal or item is never guessed: the caller shows the candidates and writes nothing.

"The last recorded meal" is not a time window. It is the chat's last two meals recorded successfully (confirm,
plain or edit history lines, meals still active); exactly one of the two matching the words is the target.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from muscle50.domain.llm_today_totals import NUTRIENT_NAMES, amount_text
from muscle50.domain.nutrition import GENERAL_MEAL_FOOD_ID, Meal, MealItem, MealType, NutrientField, QuantityUnit
from muscle50.domain.telegram_llm import MENU_PROPOSAL_TTL_S, NutrientRanges, Proposal, ProposalKind, ProposalState
from muscle50.domain.telegram_llm_prompt import MEAL_NAMES

RECENT_MEALS = 2
"""How many of the chat's latest recorded meals are offered as "the last recorded" (the user's decision)."""
MEMO_MATCH_MIN = 2
"""A memo is searched for a text only when the text has at least this many characters after normalizing."""
RECORDING_KINDS = frozenset({"confirm", "plain", "edit"})
"""History kinds whose `result.meal_id(s)` are meals the bot recorded or corrected."""
_MEAL_NUMBER = re.compile(r"-([0-9]+)$")


# --- the chat's last recorded meals ---


def recent_meal_ids(entries: Iterable[dict[str, Any]], *, chat_id: int) -> tuple[str, ...]:
    """Meal IDs of this chat's successful confirm/plain/edit history lines, newest first and without repeats.

    ``entries`` are in file (oldest first) order. A multi-meal line lists its meals in the order they were recorded,
    so the last of them is the newest. An edit repeats the meal it corrected, which moves it to the front.
    """
    found: list[str] = []
    for entry in reversed(list(entries)):
        if entry.get("chat_id") != chat_id or entry.get("kind") not in RECORDING_KINDS:
            continue
        result = entry.get("result")
        if not isinstance(result, dict) or result.get("exit_code") != 0:
            continue
        ids = result.get("meal_ids") or ([result["meal_id"]] if result.get("meal_id") else [])
        for meal_id in reversed([item for item in ids if isinstance(item, str)]):
            if meal_id not in found:
                found.append(meal_id)
    return tuple(found)


# --- the meal ---


def meal_number(meal_id: str) -> int:
    """The recording order inside a day and meal type (`2026-10-14-breakfast-10` is 10, after `-2`)."""
    match = _MEAL_NUMBER.search(meal_id)
    return int(match.group(1)) if match else 0


def pick_meals(day_meals: Sequence[Meal], meal_type: MealType | None, ordinal: int | None) -> tuple[Meal, ...]:
    """The active meals of a day narrowed by the meal type and the ordinal (`아침 1식` = the 1st active breakfast).

    The ordinal counts the meals of that type that are still active, in recording order (the number in the ID, not
    its text order); a voided first breakfast makes `1` the second one. An ordinal without a meal type narrows nothing
    (the caller must not resolve it). An ordinal past the last meal gives no meal.
    """
    meals = [meal for meal in day_meals if meal_type is None or meal.meal_type is meal_type]
    if ordinal is None or meal_type is None:
        return tuple(meals)
    ordered = sorted(meals, key=lambda meal: meal_number(meal.meal_id))
    return (ordered[ordinal - 1],) if 1 <= ordinal <= len(ordered) else ()


# --- the item ---


@dataclass(frozen=True)
class ItemRef:
    meal: Meal
    item: MealItem


def normalize_memo(text: str | None) -> str:
    """NFKC, case-folded, with whitespace and punctuation removed (two memos match when these are equal)."""
    if not text:
        return ""
    folded = unicodedata.normalize("NFKC", text).casefold()
    return "".join(
        character
        for character in folded
        if not character.isspace() and not unicodedata.category(character).startswith(("P", "Z", "C"))
    )


def item_memo(item: MealItem) -> str | None:
    """A general item's memo (None for a catalog item or a general item without one)."""
    return item.serving_description if item.is_general else None


def match_items(meals: Sequence[Meal], *, food_id: str | None, text: str | None) -> tuple[ItemRef, ...]:
    """The items a correction's words point at, in meal and item order.

    The union of the catalog items whose food ID is ``food_id`` (the exact catalog lookup of the words) and the
    general items whose normalized memo equals the normalized ``text``. When no memo is equal, the general items
    whose memo contains the text count instead (the text needs `MEMO_MATCH_MIN` characters). Nothing is guessed:
    the caller acts only on exactly one match.
    """
    wanted = normalize_memo(text)
    pairs = [ItemRef(meal, item) for meal in meals for item in meal.items]
    by_food = [
        ref for ref in pairs if food_id is not None and ref.item.food_profile_id == food_id and not ref.item.is_general
    ]
    general = [ref for ref in pairs if ref.item.is_general and normalize_memo(item_memo(ref.item))]
    exact = [ref for ref in general if wanted and normalize_memo(item_memo(ref.item)) == wanted]
    if not exact and len(wanted) >= MEMO_MATCH_MIN:
        exact = [ref for ref in general if wanted in normalize_memo(item_memo(ref.item))]
    chosen = {id(ref) for ref in (*by_food, *exact)}
    return tuple(ref for ref in pairs if id(ref) in chosen)


def general_ranges(item: MealItem) -> NutrientRanges:
    """The stored estimate of a general item as ranges (empty when it has none)."""
    fact = item.general_estimate
    if fact is None or fact.value_range is None:
        return ()
    ranges = []
    for nutrient in NutrientField:
        bounds = fact.value_range.bounds(nutrient)
        if bounds is not None:
            ranges.append((nutrient, bounds[0], bounds[1]))
    return tuple(ranges)


def merge_estimate(current: NutrientRanges, changes: NutrientRanges) -> NutrientRanges:
    """The stored ranges with only the named nutrients replaced; the others keep their range (unknown stays unknown)."""
    by_field = {nutrient: (low, high) for nutrient, low, high in current}
    by_field.update({nutrient: (low, high) for nutrient, low, high in changes})
    return tuple((nutrient, *by_field[nutrient]) for nutrient in NutrientField if nutrient in by_field)


# --- text of a range and of the context blocks ---


def ranges_summary(ranges: NutrientRanges) -> str:
    """`kcal 185, 단백질 5 g` (one number when min = max), the way the LLM data and proposals write ranges."""
    parts = []
    for nutrient, low, high in ranges:
        unit = "" if nutrient is NutrientField.CALORIES_KCAL else " g"
        value = amount_text(low) if low == high else f"{amount_text(low)}~{amount_text(high)}"
        parts.append(f"{NUTRIENT_NAMES[nutrient]} {value}{unit}")
    return ", ".join(parts)


def item_summary(item: MealItem) -> str:
    """One item of a recorded meal as the LLM and the candidate lists see it."""
    if item.is_general:
        note = item.serving_description
        return f"일반식 (메모: {note})" if note else "일반식"
    if item.quantity is not None and item.quantity_unit is not None:
        name = f"{item.food_name} ({item.food_profile_id})" if item.food_profile_id else item.food_name
        return f"{name} {amount_text(item.quantity)} {item.quantity_unit.value}"
    return item.food_name


def recent_meals_block(meals: Sequence[Meal]) -> str:
    """`<직전 기록>`: the chat's last recorded meals, newest first, with the item numbers the day view shows."""
    lines: list[str] = []
    for meal in meals:
        lines.append(f"{meal.meal_id} | {MEAL_NAMES[meal.meal_type]}")
        for item in meal.items:
            text = f"{item.sequence}. {item_summary(item)}"
            ranges = general_ranges(item)
            lines.append(f"{text} | {ranges_summary(ranges)}" if ranges else text)
    return "\n".join(lines)


def open_proposal_block(proposal: Proposal) -> str:
    """`<열린 제안>`: the item lines the user was shown for the newest open meal proposal and (v2.5) the earlier
    requests that corrected it, so that the next correction keeps them."""
    if proposal.meal_type is not None:
        where = (
            f"{MEAL_NAMES[proposal.meal_type]} {proposal.day:%m-%d}" if proposal.day else MEAL_NAMES[proposal.meal_type]
        )
    else:
        where = f"{proposal.day:%m-%d} {len(proposal.meals)}끼" if proposal.day else f"{len(proposal.meals)}끼"
    lines = [f"/ok_{proposal.token} | {where}", *proposal.outline]
    if proposal.edit_requests:
        lines.append("앞선 수정 요청(오래된 것부터):")
        lines.extend(f"- {request}" for request in proposal.edit_requests)
    return "\n".join(lines)


# --- a new meal that overlaps a recorded one of the same day and type ---


@dataclass(frozen=True)
class Candidate:
    """One item a proposal would record: a catalog food with an amount, or a general item with a memo."""

    food_id: str | None
    """The catalog food ID; None for a general item."""
    memo: str | None
    ranges: NutrientRanges
    quantity: Decimal | None
    unit: QuantityUnit | None


@dataclass(frozen=True)
class Overlap:
    """A candidate (by position) that an already recorded item of that meal also is."""

    index: int
    meal: Meal
    item: MealItem
    identical: bool
    """The recorded item already has the candidate's values (the amount, or the estimate of the same memo)."""


def _same_food(item: MealItem, candidate: Candidate) -> bool:
    """The same catalog food ID, or the same general memo after normalizing (an empty memo never matches).

    The reserved `general-meal` profile is every general item's food ID, so it never counts as a food match.
    """
    if candidate.food_id is not None:
        return (
            candidate.food_id != GENERAL_MEAL_FOOD_ID
            and not item.is_general
            and item.food_profile_id == candidate.food_id
        )
    memo = normalize_memo(candidate.memo)
    return bool(memo) and item.is_general and normalize_memo(item_memo(item)) == memo


def _identical(item: MealItem, candidate: Candidate) -> bool:
    if candidate.food_id is not None:
        return item.quantity == candidate.quantity and item.quantity_unit is candidate.unit
    # A proposal without values never replaces recorded values (that would lose them).
    return not candidate.ranges or general_ranges(item) == candidate.ranges


def find_overlaps(existing: Sequence[Meal], candidates: Sequence[Candidate]) -> tuple[Overlap, ...]:
    """The candidates that are already recorded in one of the ``existing`` meals (same day and meal type).

    Deterministic: a catalog food by ID, a general item by normalized memo. Each candidate is reported once, with
    the first recorded item it equals.
    """
    found = []
    for index, candidate in enumerate(candidates):
        match = next(((meal, item) for meal in existing for item in meal.items if _same_food(item, candidate)), None)
        if match is not None:
            found.append(Overlap(index, match[0], match[1], _identical(match[1], candidate)))
    return tuple(found)


@dataclass(frozen=True)
class FixPlan:
    """What makes the recorded meal equal to the proposal: items to replace and new items to add."""

    meal: Meal
    replacements: tuple[Overlap, ...]
    """Overlapping items whose values differ (one `replace-item` each)."""
    additions: tuple[int, ...]
    """Candidates that overlap nothing (one `add-item` for all of them together)."""

    @property
    def operations(self) -> int:
        return len(self.replacements) + (1 if self.additions else 0)


def plan_fix(overlaps: Sequence[Overlap], candidate_count: int) -> FixPlan | None:
    """The fix for a single-meal proposal whose overlaps all lie in one recorded meal; None otherwise.

    An overlapping item with the same values needs no operation: it is already recorded. `/fix_` is offered only
    when exactly one operation is left (`FixPlan.operations`).
    """
    if len({overlap.meal.meal_id for overlap in overlaps}) != 1:
        return None
    overlapping = {overlap.index for overlap in overlaps}
    return FixPlan(
        overlaps[0].meal,
        tuple(overlap for overlap in overlaps if not overlap.identical),
        tuple(index for index in range(candidate_count) if index not in overlapping),
    )


def overlap_name(item: MealItem) -> str:
    """The recorded food as the overlap notice names it: a general item's memo, a catalog food's name."""
    return (item_memo(item) or item.food_name) if item.is_general else item.food_name


# --- a menu shown in the last hours, picked by name ---

MENU_WINDOW_S = MENU_PROPOSAL_TTL_S
"""A menu capture or suggestion is offered to the LLM for this long after it was made. Since v2.4 it is also the
menu proposal's own time-to-live (`/eat_` works for the same 4 hours). One edge differs by one second: at exactly
this age the menu is still offered by name (`<=`), while `/eat_` is expired (`now >= expires_unix`)."""
MENU_NAME_MIN = 2
"""A menu item and the user's words must be at least this long (after normalizing) to count as the same name."""


def recent_menu(proposals: Iterable[Proposal], *, chat_id: int, now_unix: int) -> Proposal | None:
    """The chat's newest menu proposal that is open or used (not cancelled) and at most `MENU_WINDOW_S` old.

    Its own expiry is ignored: choosing from the menu by words is allowed as long as the menu is recent.
    """
    recent = [
        proposal
        for proposal in proposals
        if proposal.chat_id == chat_id
        and proposal.kind is ProposalKind.MENU
        and proposal.state in (ProposalState.OPEN, ProposalState.USED)
        and 0 <= now_unix - proposal.created_unix <= MENU_WINDOW_S
        and proposal.choices
    ]
    return max(recent, key=lambda proposal: proposal.created_unix, default=None)


def menu_block(proposal: Proposal) -> str:
    """`<최근 메뉴>`: the choices of a recent menu in the order the user saw them (the numbers `menu_ref` uses)."""
    where = MEAL_NAMES[proposal.meal_type] if proposal.meal_type is not None else "끼니 미정"
    head = f"/eat_{proposal.token} {where}" + (f" ({proposal.label})" if proposal.label else "")
    lines = [head]
    for number, choice in enumerate(proposal.choices, start=1):
        text = f"{number}. {choice.memo}"
        if choice.ranges:
            text += f" | {ranges_summary(choice.ranges)}" + (" (메뉴판 표기 포함)" if choice.printed else "")
        lines.append(text)
    return "\n".join(lines)


def menu_name_matches(food_text: str, memo: str) -> bool:
    """The user's words and the menu item's name contain one another (a plain test: a wrong number is caught)."""
    words, name = normalize_memo(food_text), normalize_memo(memo)
    if len(words) < MENU_NAME_MIN or len(name) < MENU_NAME_MIN:
        return False
    return words in name or name in words
