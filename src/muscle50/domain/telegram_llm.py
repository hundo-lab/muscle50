"""Telegram LLM v2: what the LLM may answer, how the bot checks it, and the bot's own fixed texts.

Pure and deterministic: no I/O and no clock (dates and times are passed in). The LLM only extracts
and phrases; every answer is validated here against fixed bounds (`LlmOutputError` is a `bad_output`),
dates are computed by the bot from a date *expression*, and nothing is written before the user
confirms a proposal with `/ok_<token>`.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, replace
from datetime import date, time, timedelta
from decimal import ROUND_HALF_EVEN, Decimal
from enum import StrEnum
from typing import Any

from muscle50.domain.nutrition import (
    GENERAL_MEAL_NOTE_MAX_LENGTH,
    MealType,
    NutrientField,
    NutritionSourceType,
    QuantityUnit,
    normalize_general_meal_note,
)


class LlmOutputError(ValueError):
    """The LLM's JSON broke the schema or a bound; treated as `bad_output` (never repaired)."""


class Intent(StrEnum):
    MEAL_LOG = "meal_log"
    QUESTION = "question"
    MENU = "menu"
    MENU_SUGGEST = "menu_suggest"
    MEAL_EDIT = "meal_edit"
    CHAT = "chat"
    UNCLEAR = "unclear"


class PhotoKind(StrEnum):
    MEAL_PHOTO = "meal_photo"
    MENU_CAPTURE = "menu_capture"
    UNCLEAR = "unclear"
    NONE = "none"


class DateExpression(StrEnum):
    NONE = "none"
    TODAY = "today"
    YESTERDAY = "yesterday"
    OTHER = "other"


class Tense(StrEnum):
    EATEN = "eaten"
    PLANNED = "planned"
    NONE = "none"


class Topic(StrEnum):
    TRAINING = "training"
    NUTRITION = "nutrition"
    BODY = "body"


class ItemKind(StrEnum):
    CATALOG = "catalog"
    GENERAL = "general"


class EditAction(StrEnum):
    CHANGE_QUANTITY = "change_quantity"
    REPLACE_FOOD = "replace_food"
    REMOVE_ITEM = "remove_item"
    ADD_ITEM = "add_item"
    VOID_MEAL = "void_meal"
    CHANGE_MEAL_TYPE = "change_meal_type"
    CHANGE_ESTIMATE = "change_estimate"
    """Change the estimated nutrients and/or the memo of a general item."""


class Refers(StrEnum):
    """What a message is about when it answers an earlier one (null: a message of its own)."""

    OPEN_PROPOSAL = "open_proposal"
    """It corrects the proposal that is still open: the corrected `meal_log` replaces it."""
    LAST_RECORDED = "last_recorded"
    """It corrects a meal that was just recorded: a `meal_edit`."""


class SuggestCategory(StrEnum):
    EATING_OUT = "eating_out"
    DELIVERY = "delivery"
    CONVENIENCE_STORE = "convenience_store"
    HOME = "home"


# --- bounds -----------------------------------------------------------------------------------------

KCAL_LIMIT = Decimal(3000)
GRAM_LIMIT = Decimal(300)
QUANTITY_LIMIT = Decimal(10000)
MAX_ITEMS = 20
MAX_MENU_ITEMS = 15
MAX_TOPICS = 3
MAX_SUGGESTIONS = 3
FOOD_TEXT_MAX = 60
MEMO_TEXT_MAX = 60
REPLY_MAX = 300
SUMMARY_MAX = 300
ANSWER_MAX = 600
LEAD_MAX = 150
NAME_MAX = 40
CORNER_MAX = 40
DESCRIPTION_MAX = 80
NOTE_MAX = 80
SOURCE_MAX = 30
ASSUMPTION_MAX = 80
FOOD_ID_MAX = 60
MAX_PORTIONS = 4
PORTION_NAME_MAX = 20
PORTION_GRAM_LIMIT = Decimal(3000)
ORDINAL_MAX = 9

_ESTIMATE_FIELDS: tuple[tuple[NutrientField, str, Decimal], ...] = (
    (NutrientField.CALORIES_KCAL, "kcal", KCAL_LIMIT),
    (NutrientField.PROTEIN_G, "protein", GRAM_LIMIT),
    (NutrientField.CARBOHYDRATE_G, "carbs", GRAM_LIMIT),
    (NutrientField.FAT_G, "fat", GRAM_LIMIT),
)

_REQUIRED_ESTIMATES = frozenset({"kcal", "protein"})
"""Every meal item carries a kcal and a protein range (catalog items too, as the fallback)."""

NutrientRanges = tuple[tuple[NutrientField, Decimal, Decimal], ...]
"""(nutrient, minimum, maximum) in NutrientField order; nutrients not estimated are left out."""


# --- validated LLM output ----------------------------------------------------------------------------


@dataclass(frozen=True)
class Portion:
    """The weight the LLM assumed for one component of a dish whose amount the user did not state."""

    name: str
    g_min: Decimal
    g_max: Decimal


@dataclass(frozen=True)
class InterpretItem:
    kind: ItemKind
    food_text: str
    quantity: Decimal | None
    unit: QuantityUnit | None
    quantity_estimated: bool
    memo: str | None
    estimate: NutrientRanges
    meal_type: MealType | None = None
    """The meal the user named for this food (the top-level `meal_type` is the default)."""
    food_id: str | None = None
    """The catalog ID the LLM suggests; the bot checks it and the user confirms."""
    source: str | None = None
    """A site name (never a URL) when a web search was used."""
    assumption: str | None = None
    from_label: bool = False
    """The values are printed on a nutrition label (photo or the user's words): single values are allowed."""
    portions: tuple[Portion, ...] = ()
    """Assumed grams per component (empty when the user stated the amount or the item is a catalog item)."""
    menu_ref: int | None = None
    """The number of the recently shown menu item the user says they ate (the bot checks it)."""


@dataclass(frozen=True)
class MenuItem:
    slot: MealType | None
    corner: str | None
    name: str
    printed_kcal: Decimal | None
    printed_protein_g: Decimal | None
    estimate: NutrientRanges


@dataclass(frozen=True)
class EditRequest:
    action: EditAction | None
    target_food_text: str | None
    new_food_text: str | None
    new_quantity: Decimal | None
    new_unit: QuantityUnit | None
    new_meal_type: MealType | None
    new_memo: str | None = None
    """`change_estimate`: the item's new memo (null: unchanged)."""
    estimate: NutrientRanges = ()
    """`change_estimate`: only the nutrients that change; the others keep their stored range."""
    from_label: bool = False
    """The new estimate is read from a label: single values are allowed."""
    ordinal: int | None = None
    """"아침 1식" is breakfast with ordinal 1: the Nth active meal of that type that day."""


@dataclass(frozen=True)
class Interpretation:
    intent: Intent
    photo_kind: PhotoKind
    meal_type: MealType | None
    date_expression: DateExpression
    tense: Tense
    items: tuple[InterpretItem, ...]
    question_topics: tuple[Topic, ...]
    slots_visible: tuple[MealType, ...]
    menu_items: tuple[MenuItem, ...]
    edit: EditRequest
    reply: str | None
    memory_summary: str
    document: dict[str, Any]
    """The validated JSON as received (kept in the history)."""
    refers_to: Refers | None = None


@dataclass(frozen=True)
class Answer:
    answer: str
    memory_summary: str
    document: dict[str, Any]


@dataclass(frozen=True)
class Suggestion:
    name: str
    category: SuggestCategory
    description: str
    estimate: NutrientRanges
    note: str


@dataclass(frozen=True)
class SuggestResult:
    lead: str
    suggestions: tuple[Suggestion, ...]
    memory_summary: str
    document: dict[str, Any]


def parse_interpretation(document: Any) -> Interpretation:
    root = _object(document, "interpretation", 12)
    items = _array(root["items"], "items", MAX_ITEMS)
    topics = _array(root["question_topics"], "question_topics", MAX_TOPICS)
    menu = _object(root["menu"], "menu", 2)
    menu_items = _array(menu["items"], "menu.items", MAX_MENU_ITEMS)
    slots = _array(menu["slots_visible"], "menu.slots_visible", 3)
    edit = _object(root["edit"], "edit", 10)
    parsed_items = tuple(_item(item, index) for index, item in enumerate(items, start=1))
    default_meal = _optional_enum(MealType, root["meal_type"], "meal_type")
    if default_meal is None and len({item.meal_type is None for item in parsed_items}) > 1:
        raise LlmOutputError("items must all name a meal or none of them may (no meal_type to fall back on)")
    intent = _enum(Intent, root["intent"], "intent")
    refers_to = _optional_enum(Refers, root["refers_to"], "refers_to")
    parsed_edit = _edit(edit)
    _cross_check(intent, refers_to, parsed_edit)
    return Interpretation(
        intent=intent,
        refers_to=refers_to,
        photo_kind=_enum(PhotoKind, root["photo_kind"], "photo_kind"),
        meal_type=default_meal,
        date_expression=_enum(DateExpression, root["date_expression"], "date_expression"),
        tense=_enum(Tense, root["tense"], "tense"),
        items=parsed_items,
        question_topics=tuple(dict.fromkeys(_enum(Topic, topic, "question_topics") for topic in topics)),
        slots_visible=tuple(dict.fromkeys(_slot(slot) for slot in slots)),
        menu_items=tuple(_menu_item(item, index) for index, item in enumerate(menu_items, start=1)),
        edit=parsed_edit,
        reply=_optional_text(root["reply"], "reply", REPLY_MAX, multiline=True),
        memory_summary=_text(root["memory_summary"], "memory_summary", SUMMARY_MAX, multiline=True, blank=True),
        document=root,
    )


def parse_answer(document: Any) -> Answer:
    root = _object(document, "answer", 2)
    return Answer(
        answer=_text(root["answer"], "answer", ANSWER_MAX, multiline=True),
        memory_summary=_text(root["memory_summary"], "memory_summary", SUMMARY_MAX, multiline=True, blank=True),
        document=root,
    )


def parse_suggestions(document: Any) -> SuggestResult:
    root = _object(document, "suggest", 3)
    raw = _array(root["suggestions"], "suggestions", MAX_SUGGESTIONS)
    if not raw:
        raise LlmOutputError("suggestions must not be empty")
    suggestions = []
    for index, item in enumerate(raw, start=1):
        entry = _object(item, f"suggestions[{index}]", 5)
        suggestions.append(
            Suggestion(
                name=_text(entry["name"], f"suggestions[{index}].name", NAME_MAX),
                category=_enum(SuggestCategory, entry["category"], f"suggestions[{index}].category"),
                description=_text(
                    entry["description"], f"suggestions[{index}].description", DESCRIPTION_MAX, blank=True
                ),
                estimate=_estimate(entry["estimate"], f"suggestions[{index}].estimate"),
                note=_text(entry["note"], f"suggestions[{index}].note", NOTE_MAX, blank=True),
            )
        )
    return SuggestResult(
        lead=_text(root["lead"], "lead", LEAD_MAX, blank=True),
        suggestions=tuple(suggestions),
        memory_summary=_text(root["memory_summary"], "memory_summary", SUMMARY_MAX, multiline=True, blank=True),
        document=root,
    )


def _edit(entry: dict[str, Any]) -> EditRequest:
    action = _optional_enum(EditAction, entry["action"], "edit.action")
    new_memo = _optional_text(entry["new_memo"], "edit.new_memo", MEMO_TEXT_MAX)
    estimate = _estimate(entry["estimate"], "edit.estimate")
    from_label = entry["from_label"]
    if type(from_label) is not bool:
        raise LlmOutputError("edit.from_label must be a boolean")
    return EditRequest(
        action=action,
        target_food_text=_optional_text(entry["target_food_text"], "edit.target_food_text", FOOD_TEXT_MAX),
        new_food_text=_optional_text(entry["new_food_text"], "edit.new_food_text", FOOD_TEXT_MAX),
        new_quantity=_quantity(entry["new_quantity"], "edit.new_quantity"),
        new_unit=_optional_enum(QuantityUnit, entry["new_unit"], "edit.new_unit"),
        new_meal_type=_optional_enum(MealType, entry["new_meal_type"], "edit.new_meal_type"),
        new_memo=new_memo,
        estimate=estimate,
        from_label=from_label,
        ordinal=_ordinal(entry["target_meal_ordinal"]),
    )


def _ordinal(value: Any) -> int | None:
    if value is None:
        return None
    if type(value) is not int or not 1 <= value <= ORDINAL_MAX:
        raise LlmOutputError(f"edit.target_meal_ordinal must be an integer from 1 to {ORDINAL_MAX} or null")
    return value


def _cross_check(intent: Intent, refers_to: Refers | None, edit: EditRequest) -> None:
    """Combinations the schema cannot express: they are a format failure (`bad_output`), never repaired."""
    if refers_to is Refers.OPEN_PROPOSAL and intent is not Intent.MEAL_LOG:
        raise LlmOutputError("refers_to open_proposal needs the meal_log intent")
    if refers_to is Refers.LAST_RECORDED and intent is not Intent.MEAL_EDIT:
        raise LlmOutputError("refers_to last_recorded needs the meal_edit intent")
    if edit.action is EditAction.CHANGE_ESTIMATE and not edit.estimate and edit.new_memo is None:
        raise LlmOutputError("change_estimate needs an estimate or a new memo")


def _portions(value: Any, where: str) -> tuple[Portion, ...]:
    portions = []
    for index, raw in enumerate(_array(value, where, MAX_PORTIONS), start=1):
        entry = _object(raw, f"{where}[{index}]", 3)
        low = _bounded(entry["g_min"], f"{where}[{index}].g_min", PORTION_GRAM_LIMIT)
        high = _bounded(entry["g_max"], f"{where}[{index}].g_max", PORTION_GRAM_LIMIT)
        if low is None or high is None:
            raise LlmOutputError(f"{where}[{index}] needs both g_min and g_max")
        if low > high:
            raise LlmOutputError(f"{where}[{index}].g_min is above g_max")
        name = _no_url(_text(entry["name"], f"{where}[{index}].name", PORTION_NAME_MAX), f"{where}[{index}].name")
        assert name is not None
        portions.append(Portion(name, low, high))
    return tuple(portions)


def _menu_ref(value: Any, where: str) -> int | None:
    if value is None:
        return None
    if type(value) is not int:
        raise LlmOutputError(f"{where} must be an integer or null")
    return value


def _item(value: Any, index: int) -> InterpretItem:
    where = f"items[{index}]"
    entry = _object(value, where, 14)
    quantity_estimated = entry["quantity_estimated"]
    if type(quantity_estimated) is not bool:
        raise LlmOutputError(f"{where}.quantity_estimated must be a boolean")
    from_label = entry["from_label"]
    if type(from_label) is not bool:
        raise LlmOutputError(f"{where}.from_label must be a boolean")
    return InterpretItem(
        kind=_enum(ItemKind, entry["kind"], f"{where}.kind"),
        food_text=_text(entry["food_text"], f"{where}.food_text", FOOD_TEXT_MAX),
        quantity=_quantity(entry["quantity"], f"{where}.quantity"),
        unit=_optional_enum(QuantityUnit, entry["unit"], f"{where}.unit"),
        quantity_estimated=quantity_estimated,
        memo=_optional_text(entry["memo"], f"{where}.memo", MEMO_TEXT_MAX),
        estimate=_estimate(entry["estimate"], f"{where}.estimate", required=_REQUIRED_ESTIMATES),
        meal_type=_optional_enum(MealType, entry["meal_type"], f"{where}.meal_type"),
        food_id=_optional_text(entry["food_id"], f"{where}.food_id", FOOD_ID_MAX),
        source=_no_url(_optional_text(entry["source"], f"{where}.source", SOURCE_MAX), f"{where}.source"),
        assumption=_no_url(
            _optional_text(entry["assumption"], f"{where}.assumption", ASSUMPTION_MAX), f"{where}.assumption"
        ),
        from_label=from_label,
        portions=_portions(entry["portions"], f"{where}.portions"),
        menu_ref=_menu_ref(entry["menu_ref"], f"{where}.menu_ref"),
    )


def _no_url(text: str | None, where: str) -> str | None:
    """A page address or body is never stored: a bare site name is fine."""
    if text is not None and ("://" in text or "www." in text.casefold()):
        raise LlmOutputError(f"{where} must not contain a web address")
    return text


def _menu_item(value: Any, index: int) -> MenuItem:
    where = f"menu.items[{index}]"
    entry = _object(value, where, 6)
    return MenuItem(
        slot=_slot(entry["slot"]) if entry["slot"] is not None else None,
        corner=_optional_text(entry["corner"], f"{where}.corner", CORNER_MAX),
        name=_text(entry["name"], f"{where}.name", NAME_MAX),
        printed_kcal=_bounded(entry["printed_kcal"], f"{where}.printed_kcal", KCAL_LIMIT),
        printed_protein_g=_bounded(entry["printed_protein_g"], f"{where}.printed_protein_g", GRAM_LIMIT),
        estimate=_estimate(entry["estimate"], f"{where}.estimate"),
    )


def _slot(value: Any) -> MealType:
    slot = _enum(MealType, value, "slot")
    if slot not in (MealType.BREAKFAST, MealType.LUNCH, MealType.DINNER):
        raise LlmOutputError("slot must be breakfast, lunch or dinner")
    return slot


def _estimate(value: Any, where: str, *, required: frozenset[str] = frozenset()) -> NutrientRanges:
    entry = _object(value, where, 8)
    ranges = []
    for nutrient, name, limit in _ESTIMATE_FIELDS:
        low = _bounded(entry[f"{name}_min"], f"{where}.{name}_min", limit)
        high = _bounded(entry[f"{name}_max"], f"{where}.{name}_max", limit)
        if name in required and (low is None or high is None):
            raise LlmOutputError(f"{where}.{name} needs both min and max")
        if (low is None) != (high is None):
            raise LlmOutputError(f"{where}.{name} needs both min and max or neither")
        if low is not None and high is not None:
            if low > high:
                raise LlmOutputError(f"{where}.{name}_min is above {name}_max")
            ranges.append((nutrient, low, high))
    return tuple(ranges)


def _object(value: Any, where: str, size: int) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise LlmOutputError(f"{where} must be an object")
    if len(value) != size:
        raise LlmOutputError(f"{where} must have exactly the schema keys")
    return value


def _array(value: Any, where: str, limit: int) -> list[Any]:
    if not isinstance(value, list):
        raise LlmOutputError(f"{where} must be an array")
    if len(value) > limit:
        raise LlmOutputError(f"{where} has more than {limit} entries")
    return value


def _enum[E: StrEnum](kind: type[E], value: Any, where: str) -> E:
    if not isinstance(value, str):
        raise LlmOutputError(f"{where} must be a string")
    try:
        return kind(value)
    except ValueError:
        raise LlmOutputError(f"{where} has an unknown value") from None


def _optional_enum[E: StrEnum](kind: type[E], value: Any, where: str) -> E | None:
    return None if value is None else _enum(kind, value, where)


def _text(value: Any, where: str, limit: int, *, multiline: bool = False, blank: bool = False) -> str:
    if not isinstance(value, str):
        raise LlmOutputError(f"{where} must be a string")
    text = value.strip()
    if not text and not blank:
        raise LlmOutputError(f"{where} must not be blank")
    if len(text) > limit:
        raise LlmOutputError(f"{where} is longer than {limit} characters")
    allowed = {"\n"} if multiline else set()
    if any(unicodedata.category(character) == "Cc" and character not in allowed for character in text):
        raise LlmOutputError(f"{where} contains control characters")
    return text


def _optional_text(value: Any, where: str, limit: int, *, multiline: bool = False) -> str | None:
    if value is None:
        return None
    text = _text(value, where, limit, multiline=multiline, blank=True)
    return text or None


def llm_decimal(value: Any, where: str) -> Decimal:
    """A JSON number as an exact Decimal rounded to 0.1 (half-even, trailing zeros dropped)."""
    if type(value) not in (int, float):
        raise LlmOutputError(f"{where} must be a number")
    number = Decimal(str(value))
    if not number.is_finite():
        raise LlmOutputError(f"{where} must be finite")
    rounded = number.quantize(Decimal("0.1"), rounding=ROUND_HALF_EVEN)
    return rounded.to_integral_value() if rounded == rounded.to_integral_value() else rounded.normalize()


def _bounded(value: Any, where: str, limit: Decimal) -> Decimal | None:
    if value is None:
        return None
    number = llm_decimal(value, where)
    if number < 0 or number > limit:
        raise LlmOutputError(f"{where} is outside 0-{limit}")
    return number


def _quantity(value: Any, where: str) -> Decimal | None:
    if value is None:
        return None
    number = llm_decimal(value, where)
    if number <= 0 or number > QUANTITY_LIMIT:
        raise LlmOutputError(f"{where} must be above 0 and at most {QUANTITY_LIMIT}")
    return number


# --- dates, meal slots and memos ---------------------------------------------------------------------


def resolve_date_expression(expression: DateExpression, today: date) -> date | None:
    """The bot's date for an expression (the LLM never computes dates); None for `other`."""
    if expression in (DateExpression.NONE, DateExpression.TODAY):
        return today
    if expression is DateExpression.YESTERDAY:
        return today - timedelta(days=1)
    return None


def meal_slot_for(local_time: time) -> MealType:
    """[00:00, 10:00) breakfast, [10:00, 15:00) lunch, [15:00, 24:00) dinner (this computer's local time)."""
    if local_time < time(10):
        return MealType.BREAKFAST
    if local_time < time(15):
        return MealType.LUNCH
    return MealType.DINNER


def clean_memo(text: str | None) -> str | None:
    """A general meal memo from LLM text: control characters become spaces, whitespace collapses, at most
    100 characters (`normalize_general_meal_note` accepts the result)."""
    if text is None:
        return None
    spaced = "".join(" " if unicodedata.category(character) == "Cc" else character for character in text)
    collapsed = " ".join(spaced.split())[:GENERAL_MEAL_NOTE_MAX_LENGTH].strip()
    return normalize_general_meal_note(collapsed)


def estimate_source(photo: bool) -> NutritionSourceType:
    return NutritionSourceType.VISUAL_ESTIMATE if photo else NutritionSourceType.LANGUAGE_ESTIMATE


# --- commands the LLM layer owns (only when the feature is on) ---------------------------------------

PROPOSAL_TOKEN = re.compile(r"[0-9a-f]{4}")
_PROPOSAL_COMMAND = re.compile(r"/(ok|plain|no)_([0-9a-f]{4})")
_EAT_COMMAND = re.compile(r"/eat_([0-9a-f]{4})_([1-9][0-9]?)")
LLM_COMMANDS = frozenset({"llm", "memory", "forget", "history"})


@dataclass(frozen=True)
class ProposalCommand:
    action: str
    """`ok`, `plain`, `no` or `eat`."""
    token: str
    number: int | None = None
    """`/eat_<token>_<n>`: the menu number."""


@dataclass(frozen=True)
class LlmCommand:
    name: str
    """`llm`, `memory`, `forget` or `history`."""
    argument: str
    """The rest of the message, stripped (may be empty)."""


def parse_llm_command(text: str, *, bot_username: str) -> ProposalCommand | LlmCommand | None:
    """A command of the LLM layer, or None (the v1 parser then handles the message unchanged)."""
    parts = text.split(maxsplit=1)
    if not parts:
        return None
    head, rest = parts[0], parts[1].strip() if len(parts) > 1 else ""
    name, at, suffix = head.partition("@")
    if at and suffix.lower() != bot_username.lower():
        return None
    match = _PROPOSAL_COMMAND.fullmatch(name)
    if match is not None and not rest:
        return ProposalCommand(match.group(1), match.group(2))
    eat = _EAT_COMMAND.fullmatch(name)
    if eat is not None and not rest:
        return ProposalCommand("eat", eat.group(1), int(eat.group(2)))
    if name.startswith("/") and name[1:] in LLM_COMMANDS:
        return LlmCommand(name[1:], rest)
    return None


# --- proposals and state --------------------------------------------------------------------------------

PROPOSAL_TTL_S = 60 * 60
PROPOSAL_PRUNE_AFTER_S = 24 * 60 * 60
MAX_PROPOSALS = 50


class ProposalKind(StrEnum):
    MEAL = "meal"
    MENU = "menu"
    EDIT = "edit"


class ProposalState(StrEnum):
    OPEN = "open"
    USED = "used"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class MenuChoice:
    memo: str
    ranges: NutrientRanges
    printed: bool
    """The values are the menu's printed numbers (min = max), still stored as an estimate."""


@dataclass(frozen=True)
class MealCommand:
    """One meal of a multi-meal proposal: the `nutrition log` argv `/ok_` and `/plain_` run for it."""

    meal_type: MealType
    argv_ok: tuple[str, ...]
    argv_plain: tuple[str, ...] = ()
    """Empty when no item of this meal has an estimate (`/plain_` then runs `argv_ok`)."""


@dataclass(frozen=True)
class Proposal:
    token: str
    chat_id: int
    kind: ProposalKind
    created_unix: int
    expires_unix: int
    state: ProposalState
    argv_ok: tuple[str, ...] = ()
    argv_plain: tuple[str, ...] = ()
    """Empty when no item has an estimate (then `/plain_` is not offered)."""
    choices: tuple[MenuChoice, ...] = ()
    meal_type: MealType | None = None
    day: date | None = None
    source: NutritionSourceType | None = None
    reference: str | None = None
    meal_id: str | None = None
    """An edit's meal (for `확인: /show <id>`)."""
    label: str = ""
    """How the menu was made (`메뉴 캡처 추정`, `메뉴 제안 추정`), shown in the `/eat_` proposal."""
    meals: tuple[MealCommand, ...] = ()
    """A multi-meal proposal (two or more meals): one command per meal, run in order; `argv_ok` stays empty."""

    @property
    def plain_available(self) -> bool:
        """`/plain_` is offered when the proposal (or any of its meals) has an estimate to leave out."""
        return bool(self.argv_plain) or any(meal.argv_plain for meal in self.meals)

    def with_state(self, state: ProposalState) -> Proposal:
        return replace(self, state=state)


@dataclass(frozen=True)
class LlmState:
    provider_override: str | None
    proposals: tuple[Proposal, ...]


EMPTY_STATE = LlmState(None, ())


def prune_proposals(proposals: tuple[Proposal, ...], now_unix: int) -> tuple[Proposal, ...]:
    """Drop proposals 24 h after they expired, then keep the newest `MAX_PROPOSALS`."""
    kept = [proposal for proposal in proposals if proposal.expires_unix + PROPOSAL_PRUNE_AFTER_S > now_unix]
    return tuple(kept[-MAX_PROPOSALS:])


# --- conversation memory ---------------------------------------------------------------------------------

MEMORY_TURNS = 8
MEMORY_TEXT_MAX = 300
MEMORY_TTL_S = 24 * 60 * 60


@dataclass(frozen=True)
class ChatTurn:
    at_unix: int
    user: str
    bot: str


@dataclass(frozen=True)
class ChatMemory:
    summary: str | None
    turns: tuple[ChatTurn, ...]


EMPTY_MEMORY = ChatMemory(None, ())


def remember(memory: ChatMemory, *, user: str, bot: str, summary: str | None, now_unix: int) -> ChatMemory:
    turns = (*active_memory(memory, now_unix).turns, ChatTurn(now_unix, _clip(user), _clip(bot)))
    new_summary = _clip(summary) if summary is not None and summary.strip() else memory.summary
    return ChatMemory(new_summary, turns[-MEMORY_TURNS:])


def active_memory(memory: ChatMemory, now_unix: int) -> ChatMemory:
    return ChatMemory(memory.summary, tuple(turn for turn in memory.turns if turn.at_unix + MEMORY_TTL_S > now_unix))


def memory_block(memory: ChatMemory, now_unix: int) -> str | None:
    """Exactly the `[기억]` block the next prompt gets (and `/memory` shows); None when empty."""
    active = active_memory(memory, now_unix)
    if active.summary is None and not active.turns:
        return None
    lines = ["[기억]", f"요약: {active.summary if active.summary is not None else '없음'}"]
    if active.turns:
        lines.append("최근 대화:")
        for turn in active.turns:
            lines.append(f"- 나: {turn.user}")
            lines.append(f"  bot: {turn.bot}")
    return "\n".join(lines)


def _clip(text: str) -> str:
    return " ".join(text.split())[:MEMORY_TEXT_MAX]


# --- conversation history (append-only JSONL lines, kept as JSON documents) -------------------------------

HISTORY_VERSION = 1
HISTORY_KEYS_V1 = (
    "v",
    "update_id",
    "at",
    "chat_id",
    "kind",
    "text",
    "caption",
    "photo",
    "intent",
    "provider",
    "model",
    "provider_result",
    "llm_output",
    "reply",
    "proposal",
    "result",
)
HISTORY_KEYS_V21 = (*HISTORY_KEYS_V1, "retried", "attempts")
"""Lines written by model routing (v2.1) have these 18 keys and stay valid."""
HISTORY_KEYS = (*HISTORY_KEYS_V21, "web_searches", "recheck")
"""New lines (v2.2) add the web search count and the numeric re-check; lines with 16 or 18 keys stay valid."""
RECHECK_OUTCOMES = frozenset({"fixed", "still_inconsistent", "reask_failed"})
RECHECK_CODES = frozenset(
    {"range_too_wide", "range_is_a_point", "macros_vs_kcal", "macros_exceed_kcal", "assumption_number"}
)
HISTORY_ATTEMPT_KEYS = ("provider", "model", "outcome", "retry")
HISTORY_KINDS = frozenset({"text", "photo", "confirm", "plain", "cancel", "eat", "edit"})


def history_entry(**fields: Any) -> dict[str, Any]:
    """One history line in the fixed key order; every key not given is null."""
    unknown = set(fields) - set(HISTORY_KEYS)
    if unknown:
        raise ValueError(f"unknown history keys: {sorted(unknown)}")
    entry = {key: fields.get(key) for key in HISTORY_KEYS}
    entry["v"] = HISTORY_VERSION
    return entry


def check_history_entry(document: Any) -> dict[str, Any]:
    """A stored line as read back (any of the three key shapes); ValueError when it is not a version-1 entry."""
    if (
        not isinstance(document, dict)
        or tuple(document) not in (HISTORY_KEYS_V1, HISTORY_KEYS_V21, HISTORY_KEYS)
        or document["v"] != HISTORY_VERSION
    ):
        raise ValueError("not a version 1 history entry")
    if document["kind"] not in HISTORY_KINDS or not isinstance(document["at"], str) or len(document["at"]) < 16:
        raise ValueError("not a version 1 history entry")
    if type(document["chat_id"]) is not int:
        raise ValueError("not a version 1 history entry")
    if "retried" in document and not _routing_keys_ok(document["retried"], document["attempts"]):
        raise ValueError("not a version 1 history entry")
    if "recheck" in document and not _search_keys_ok(document["web_searches"], document["recheck"]):
        raise ValueError("not a version 1 history entry")
    return document


def _search_keys_ok(web_searches: Any, recheck: Any) -> bool:
    if web_searches is not None and (type(web_searches) is not int or web_searches < 0):
        return False
    if recheck is None:
        return True
    return (
        isinstance(recheck, dict)
        and tuple(recheck) == ("reasons", "outcome")
        and isinstance(recheck["reasons"], list)
        and all(code in RECHECK_CODES for code in recheck["reasons"])
        and recheck["outcome"] in RECHECK_OUTCOMES
    )


def _routing_keys_ok(retried: Any, attempts: Any) -> bool:
    if retried is not None and type(retried) is not bool:
        return False
    if attempts is None:
        return True
    return isinstance(attempts, list) and all(
        isinstance(item, dict) and tuple(item) == HISTORY_ATTEMPT_KEYS and type(item["retry"]) is bool
        for item in attempts
    )
