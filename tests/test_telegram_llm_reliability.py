"""Telegram LLM v2.4 pure logic (docs/specs/telegram-llm-reliability.md): the menu time-to-live text, the photo
caption rule, the photo memory text, the short summaries and the schema. No I/O."""

from __future__ import annotations

from muscle50.domain.telegram_llm import MENU_PROPOSAL_TTL_S, PROPOSAL_TTL_S
from muscle50.domain.telegram_llm_corrections import MENU_WINDOW_S
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
