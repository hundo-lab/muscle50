"""Telegram LLM v2.4: the words around a photo message (pure).

- `caption_is_clearly_eaten`: after a failed photo read, a value-less general meal is offered only when the
  caption says the food was eaten (and does not say it is a menu). Anything else asks for a clearer caption and
  writes nothing.
- `photo_outcome_words` and `photo_memory_text`: what the chat memory keeps about a photo, so the coach does
  not say "there is no photo" a moment later.
- `album_partial_line`: the note when fewer photos were read than were sent.
"""

from __future__ import annotations

import re
import unicodedata

from muscle50.domain.telegram_llm import Interpretation, PhotoKind

EATEN_WORDS = ("먹었", "먹음", "먹은", "드셨")
"""Korean words for "ate": a plain substring test (ambiguity falls to the side that writes nothing)."""
MENU_WORDS = ("메뉴", "menu")
_ATE_WORD = re.compile(r"(?<![a-z])ate(?![a-z])")
"""The ASCII `ate` counts only as a whole word, so `plate` and `chocolate` do not."""

CAPTION_MEMORY_MAX = 60
OUTCOME_MEMORY_MAX = 160
OUTCOME_NAMES_SHOWN = 3
OUTCOME_NAME_MAX = 20

OUTCOME_FAILED = "해석 못함"
OUTCOME_UNCLEAR = "사진 종류 불명"


def caption_is_clearly_eaten(caption: str | None) -> bool:
    """True when the caption says the food was eaten and does not mention a menu."""
    if not caption:
        return False
    text = unicodedata.normalize("NFKC", caption).casefold()
    if any(word in text for word in MENU_WORDS):
        return False
    return any(word in text for word in EATEN_WORDS) or _ATE_WORD.search(text) is not None


def photo_outcome_words(interpretation: Interpretation | None) -> str:
    """How the photo was read, in a few words (no extra LLM call): the memory line after the arrow."""
    if interpretation is None:
        return OUTCOME_FAILED
    kind = interpretation.photo_kind
    if kind is PhotoKind.MEAL_PHOTO:
        names = [_name(item.memo or item.food_text) for item in interpretation.items]
        names = [name for name in names if name]
        if not names:
            return "식사 사진으로 읽음"
        shown = ", ".join(names[:OUTCOME_NAMES_SHOWN])
        rest = len(names) - OUTCOME_NAMES_SHOWN
        return f"식사 사진으로 읽음: {shown}" + (f" 외 {rest}개" if rest > 0 else "")
    if kind is PhotoKind.MENU_CAPTURE:
        return f"메뉴 캡처로 읽음: 항목 {len(interpretation.menu_items)}개"
    return OUTCOME_UNCLEAR


def photo_memory_text(count: int, caption: str | None, outcome: str) -> str:
    """`[사진 2장] 점심 → 메뉴 캡처로 읽음: 항목 5개`. Short enough to survive the memory's own clip."""
    head = f"[사진 {count}장]"
    words = " ".join((caption or "").split())[:CAPTION_MEMORY_MAX]
    return f"{head} {words} → {outcome[:OUTCOME_MEMORY_MAX]}" if words else f"{head} → {outcome[:OUTCOME_MEMORY_MAX]}"


def album_partial_line(sent: int, read: int) -> str | None:
    """`사진 5장 중 4장만 읽었습니다` when fewer photos were read than were sent; None otherwise."""
    return f"사진 {sent}장 중 {read}장만 읽었습니다" if sent > read else None


def _name(text: str) -> str:
    return " ".join(text.split())[:OUTCOME_NAME_MAX]
