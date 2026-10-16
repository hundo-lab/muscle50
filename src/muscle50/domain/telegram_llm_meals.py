"""Telegram LLM v2.2: meal grouping, the catalog list sent to the LLM and the estimate reference text.

Pure and deterministic. The LLM names a meal on each item; the bot groups the items into meals, drops items
that are only a meal word, shows the LLM the foods it may link by ID, and writes the provenance text of an
estimate (never a URL or page text).
"""

from __future__ import annotations

import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

from muscle50.domain.nutrition import (
    GENERAL_MEAL_FOOD_ID,
    FoodNutritionProfile,
    MealType,
    NutrientField,
    QuantityUnit,
)
from muscle50.domain.telegram_llm import NutrientRanges, Portion

MEAL_WORDS = frozenset(
    {
        "아침",
        "점심",
        "저녁",
        "간식",
        "야식",
        "아침식사",
        "점심식사",
        "저녁식사",
        "breakfast",
        "lunch",
        "dinner",
        "snack",
    }
)
CATALOG_MAX_FOODS = 120
CATALOG_MAX_CHARS = 6000
CATALOG_NAME_MAX = 40
CATALOG_ALIASES_MAX = 3
CATALOG_MATCH_MIN = 2
CATALOG_HEADER = "형식: ID | 이름 | 별칭 | 등록 단위"
ESTIMATE_REFERENCE_MAX = 100
"""The `--general-estimate-ref` limit (a test pins it to `GENERAL_ESTIMATE_REFERENCE_MAX_LENGTH`)."""
NOTE_MIN_CHARS = 10
"""An estimate reference note is kept only when at least this many characters of it fit."""
CHECK_NEEDED_NOTE = "값 확인 필요"
LABEL_NOTE = "라벨"
DISH_WORD_MIN_CHARS = 2

_MEAL_ORDER = (MealType.BREAKFAST, MealType.LUNCH, MealType.DINNER, MealType.SNACK, MealType.OTHER)
_PUNCTUATION = ".,!?~:;/\\\"'()[]{}-_"


# --- meals -----------------------------------------------------------------------------------------------


class HasMealType(Protocol):
    @property
    def meal_type(self) -> MealType | None: ...


@dataclass(frozen=True)
class MealGroup[T: HasMealType]:
    meal_type: MealType | None
    """None: the message named no meal (the bot picks the slot from the time)."""
    items: tuple[T, ...]


def is_meal_word(text: str) -> bool:
    """True when ``text`` is only a meal word (아침, 점심식사, lunch, ...), whatever its spacing or punctuation."""
    normalized = unicodedata.normalize("NFKC", text).casefold()
    squeezed = "".join(
        character for character in normalized if not character.isspace() and character not in _PUNCTUATION
    )
    return squeezed in MEAL_WORDS


def group_meals[T: HasMealType](items: Sequence[T], default: MealType | None) -> tuple[MealGroup[T], ...]:
    """The items grouped by meal: an item's own `meal_type`, else ``default``. Items of one meal are merged
    (so the proposal has one `nutrition log` per meal) and groups are ordered breakfast to other, then the
    group with no meal."""
    by_meal: dict[MealType | None, list[T]] = {}
    for item in items:
        by_meal.setdefault(item.meal_type or default, []).append(item)
    ordered: list[MealType | None] = [meal for meal in _MEAL_ORDER if meal in by_meal]
    if None in by_meal:
        ordered.append(None)
    return tuple(MealGroup(meal, tuple(by_meal[meal])) for meal in ordered)


# --- catalog list ----------------------------------------------------------------------------------------


@dataclass(frozen=True)
class CatalogPrompt:
    text: str
    shown: int
    total: int


def registered_units(profile: FoodNutritionProfile) -> tuple[QuantityUnit, ...]:
    """The units with a registered value for some nutrient (the test `nutrition log --item` applies)."""
    return tuple(
        unit
        for unit in QuantityUnit
        if any(profile.preferred_fact(unit, nutrient) is not None for nutrient in NutrientField)
    )


def catalog_prompt(profiles: Sequence[FoodNutritionProfile], message: str) -> CatalogPrompt | None:
    """The `[카탈로그]` text: one food per line (ID | name | aliases | registered units). The reserved general meal
    and foods with no registered unit are left out. Over `CATALOG_MAX_FOODS` foods or `CATALOG_MAX_CHARS`
    characters, the foods whose ID, name or alias appears in ``message`` come first, then ID order."""
    eligible = []
    for profile in sorted(profiles, key=lambda item: item.profile_id):
        if profile.profile_id == GENERAL_MEAL_FOOD_ID:
            continue
        units = registered_units(profile)
        if units:
            eligible.append((profile, units))
    if not eligible:
        return None
    wanted = unicodedata.normalize("NFKC", message).casefold()

    def relevant(profile: FoodNutritionProfile) -> bool:
        names = (profile.profile_id, profile.name, *profile.aliases)
        return any(len(name) >= CATALOG_MATCH_MIN and name.casefold() in wanted for name in names)

    ranked = [entry for entry in eligible if relevant(entry[0])] + [
        entry for entry in eligible if not relevant(entry[0])
    ]
    chosen: list[tuple[FoodNutritionProfile, tuple[QuantityUnit, ...]]] = []
    size = len(CATALOG_HEADER)
    for entry in ranked:
        line = _catalog_line(*entry)
        if len(chosen) >= CATALOG_MAX_FOODS or size + 1 + len(line) > CATALOG_MAX_CHARS:
            break
        chosen.append(entry)
        size += 1 + len(line)
    chosen.sort(key=lambda entry: entry[0].profile_id)
    lines = [CATALOG_HEADER, *(_catalog_line(*entry) for entry in chosen)]
    return CatalogPrompt("\n".join(lines), len(chosen), len(eligible))


def _catalog_line(profile: FoodNutritionProfile, units: Sequence[QuantityUnit]) -> str:
    aliases = ", ".join(_clip(alias) for alias in profile.aliases[:CATALOG_ALIASES_MAX]) or "-"
    return f"{profile.profile_id} | {_clip(profile.name)} | {aliases} | {', '.join(unit.value for unit in units)}"


def _clip(text: str) -> str:
    one_line = " ".join(text.replace("|", "/").split())
    return one_line[:CATALOG_NAME_MAX]


# --- estimate provenance ---------------------------------------------------------------------------------


def estimate_reference(
    base: str,
    source: str | None,
    assumption: str | None,
    *,
    check_needed: bool = False,
    label: bool = False,
    portions: Sequence[Portion] = (),
) -> str:
    """The `--general-estimate-ref` text, at most `GENERAL_ESTIMATE_REFERENCE_MAX_LENGTH` characters.

    ``base; 라벨; 값 확인 필요; 양: <portions>; 출처: <source>; 가정: <assumption>``. The label and check markers
    are kept ahead of the note; the note (portions, source and assumption) is cut from its end first, and dropped
    when fewer than `NOTE_MIN_CHARS` characters of it would remain. Never a URL: the parser refuses those in
    ``source``, ``assumption`` and the portion names. Without a label and portions the text is the v2.2 one.
    """
    limit = ESTIMATE_REFERENCE_MAX
    marker = (f"; {LABEL_NOTE}" if label else "") + (f"; {CHECK_NEEDED_NOTE}" if check_needed else "")
    head = base[: limit - len(marker)].rstrip() + marker
    parts = []
    if portions:
        parts.append(f"양: {portions_reference(portions)}")
    if source:
        parts.append(f"출처: {source}")
    if assumption:
        parts.append(f"가정: {assumption}")
    if not parts:
        return head
    room = limit - len(head) - len("; ")
    if room < NOTE_MIN_CHARS:
        return head
    return f"{head}; {'; '.join(parts)[:room].rstrip()}"


def portions_reference(portions: Sequence[Portion]) -> str:
    """`닭 150-200g, 감자 100-150g`: the assumed grams as stored in the estimate reference."""
    return ", ".join(f"{portion.name} {_grams(portion.g_min)}-{_grams(portion.g_max)}g" for portion in portions)


def portions_text(portions: Sequence[Portion]) -> str:
    """`닭 150~200 g, 감자 100~150 g`: the assumed grams as shown in the proposal (one number when min = max)."""
    parts = []
    for portion in portions:
        low, high = _grams(portion.g_min), _grams(portion.g_max)
        amount = low if low == high else f"{low}~{high}"
        parts.append(f"{portion.name} {amount} g")
    return ", ".join(parts)


def _grams(value: Decimal) -> str:
    text = format(value, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


# --- label values and the dish name in the memo ------------------------------------------------------------------


def is_label_estimate(ranges: NutrientRanges, from_label: bool) -> bool:
    """A label value: the LLM says it was read from a label and every given range is a single value (min = max).

    A label with a real range (the model mixed a value with a range) is an ordinary estimate and runs every check.
    """
    return from_label and bool(ranges) and all(low == high for _nutrient, low, high in ranges)


def dish_memo(food_text: str, memo: str | None) -> str:
    """The memo of a general item, always starting from the user's dish name.

    The model sometimes keeps only the description (`닭 및 감자 위주` for `안동찜닭 닭 및 감자 위주`). When the first
    word of ``food_text`` (at least `DISH_WORD_MIN_CHARS` characters) is not in the memo, it is put in front.
    This is a plain containment test, not a semantic check.
    """
    text = memo or food_text
    words = food_text.split()
    word = words[0] if words else ""
    if len(_fold(word)) >= DISH_WORD_MIN_CHARS and _fold(word) not in _fold(text):
        return f"{word} {text}"
    return text


def _fold(text: str) -> str:
    return unicodedata.normalize("NFKC", text).casefold()
