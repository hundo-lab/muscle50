"""Telegram LLM v2.2: meal grouping, the catalog list sent to the LLM and the estimate reference text.

Pure and deterministic. The LLM names a meal on each item; the bot groups the items into meals, drops items
that are only a meal word, shows the LLM the foods it may link by ID, and writes the provenance text of an
estimate (never a URL or page text).
"""

from __future__ import annotations

import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from muscle50.domain.nutrition import (
    GENERAL_MEAL_FOOD_ID,
    FoodNutritionProfile,
    MealType,
    NutrientField,
    QuantityUnit,
)

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


def estimate_reference(base: str, source: str | None, assumption: str | None, *, check_needed: bool = False) -> str:
    """The `--general-estimate-ref` text, at most `GENERAL_ESTIMATE_REFERENCE_MAX_LENGTH` characters.

    ``base; 값 확인 필요; 출처: <source>; 가정: <assumption>``. The check marker is kept ahead of the note;
    the note (source and assumption) is cut first, and dropped when fewer than `NOTE_MIN_CHARS` characters of
    it would remain. Never a URL: the parser refuses those in ``source`` and ``assumption``.
    """
    limit = ESTIMATE_REFERENCE_MAX
    marker = f"; {CHECK_NEEDED_NOTE}" if check_needed else ""
    head = base[: limit - len(marker)].rstrip() + marker
    parts = []
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
