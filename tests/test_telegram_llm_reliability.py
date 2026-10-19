"""Telegram LLM v2.4 pure logic (docs/specs/telegram-llm-reliability.md): the menu time-to-live text, the photo
caption rule, the photo memory text, the short summaries and the schema. No I/O."""

from __future__ import annotations

import json
from dataclasses import replace
from importlib.resources import files

import pytest
from test_telegram_llm_domain import interpretation

from muscle50.domain.telegram_llm import (
    MENU_PROPOSAL_TTL_S,
    PROPOSAL_TTL_S,
    Intent,
    Interpretation,
    MenuItem,
    PhotoKind,
    parse_interpretation,
)
from muscle50.domain.telegram_llm_corrections import MENU_WINDOW_S
from muscle50.domain.telegram_llm_photo import (
    album_partial_line,
    caption_is_clearly_eaten,
    photo_memory_text,
    photo_outcome_words,
)
from muscle50.domain.telegram_llm_prompt import PROPOSAL_EXPIRED_TEXT, menu_expired_text

# --- AC6: the menu time-to-live ---


def test_the_menu_window_and_the_menu_ttl_are_one_constant() -> None:
    assert MENU_WINDOW_S == MENU_PROPOSAL_TTL_S == 4 * 3600
    assert PROPOSAL_TTL_S == 3600


def test_menu_expired_text_names_the_stored_lifetime() -> None:
    assert menu_expired_text(4 * 3600) == (
        "이 메뉴 제안은 유효 시간(4시간)이 지났습니다. 메뉴 사진을 다시 보내거나 다시 물어봐 주세요."
    )
    assert "(60분)" in menu_expired_text(3600)
    assert "(90분)" in menu_expired_text(5400)
    assert "(3시간)" in menu_expired_text(3 * 3600)
    assert menu_expired_text(3600) != PROPOSAL_EXPIRED_TEXT


# --- AC8: the interpret schema and the Intent enum agree ---


def test_the_interpret_schema_intents_equal_the_intent_enum() -> None:
    text = files("muscle50").joinpath("schemas", "telegram_llm_interpret_v1.schema.json").read_text("utf-8")
    schema = json.loads(text)
    assert set(schema["properties"]["intent"]["enum"]) == {intent.value for intent in Intent}
    assert "sync_request" in schema["properties"]["intent"]["enum"]
    assert len(schema["required"]) == 12  # the root keys are unchanged: only the intent enum grew


# --- AC2: when a failed photo read may offer a plain general meal ---

CAPTION_CASES = [
    (None, False),
    ("", False),
    ("점심", False),
    ("점심 먹었어", True),
    ("먹음", True),
    ("이거 먹은 거야", True),
    ("드셨나요", True),
    ("I ate lunch", True),
    ("ATE", True),
    ("ate", True),
    ("plate", False),
    ("chocolate", False),
    ("a plate of rice", False),
    ("가나다ate", True),  # not an ASCII letter before it: a whole word as far as the rule can tell
    ("ate2", True),
    ("점심 메뉴 먹었어", False),
    ("menu ate", False),
    ("MENU 먹음", False),
    ("ＡＴＥ", True),  # full-width letters fold with NFKC
    ("메뉴", False),
]


@pytest.mark.parametrize(("caption", "expected"), CAPTION_CASES)
def test_caption_is_clearly_eaten(caption: str | None, expected: bool) -> None:
    assert caption_is_clearly_eaten(caption) is expected


# --- AC3: what the memory keeps about a photo ---


def _read(kind: PhotoKind, items: list[str | None] | None = None, menu: int = 0) -> Interpretation:
    document = interpretation(
        photo_kind=kind.value,
        items=[
            {
                **interpretation()["items"][0],
                "food_text": name or "x",
                "memo": name if name and name.startswith("메모") else None,
            }
            for name in (items or [])
        ],
    )
    parsed = parse_interpretation(document)
    return replace(parsed, menu_items=tuple(parsed.menu_items) + tuple(_menu_item(n) for n in range(menu)))


def _menu_item(number: int) -> MenuItem:
    return MenuItem(None, None, f"메뉴{number}", None, None, ())


def test_photo_outcome_words() -> None:
    assert photo_outcome_words(None) == "해석 못함"
    assert photo_outcome_words(_read(PhotoKind.UNCLEAR)) == "사진 종류 불명"
    assert photo_outcome_words(_read(PhotoKind.NONE)) == "사진 종류 불명"
    assert photo_outcome_words(_read(PhotoKind.MENU_CAPTURE, menu=5)) == "메뉴 캡처로 읽음: 항목 5개"
    assert photo_outcome_words(_read(PhotoKind.MEAL_PHOTO, ["제육볶음 정식", "햇반"])) == (
        "식사 사진으로 읽음: 제육볶음 정식, 햇반"
    )
    assert photo_outcome_words(_read(PhotoKind.MEAL_PHOTO, ["가", "나", "다", "라", "마"])) == (
        "식사 사진으로 읽음: 가, 나, 다 외 2개"
    )
    assert photo_outcome_words(_read(PhotoKind.MEAL_PHOTO, ["가", "나", "다"])) == "식사 사진으로 읽음: 가, 나, 다"
    assert photo_outcome_words(_read(PhotoKind.MEAL_PHOTO)) == "식사 사진으로 읽음"


def test_a_long_item_name_is_clipped_to_twenty_characters() -> None:
    long_name = "가" * 30
    assert photo_outcome_words(_read(PhotoKind.MEAL_PHOTO, [long_name])) == "식사 사진으로 읽음: " + "가" * 20


def test_photo_memory_text() -> None:
    assert photo_memory_text(2, "점심", "메뉴 캡처로 읽음: 항목 5개") == "[사진 2장] 점심 → 메뉴 캡처로 읽음: 항목 5개"
    assert photo_memory_text(1, None, "해석 못함") == "[사진 1장] → 해석 못함"
    assert photo_memory_text(1, "  ", "사진 종류 불명") == "[사진 1장] → 사진 종류 불명"
    assert photo_memory_text(1, "a  b\nc", "x") == "[사진 1장] a b c → x"


def test_photo_memory_text_survives_the_memory_clip() -> None:
    text = photo_memory_text(4, "캡" * 200, "결" * 300)
    assert len(text) <= 300 and text.startswith("[사진 4장] " + "캡" * 60 + " → ") and text.endswith("결" * 160)


def test_album_partial_line() -> None:
    assert album_partial_line(5, 4) == "사진 5장 중 4장만 읽었습니다"
    assert album_partial_line(2, 2) is None
    assert album_partial_line(1, 1) is None
