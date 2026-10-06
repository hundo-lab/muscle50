"""Telegram reply formatting: HTML `<pre>` with escaping, split within 4096 UTF-16 units, nothing lost."""

from __future__ import annotations

import html
import urllib.request
from pathlib import Path

import pytest

from muscle50.application.telegram_bot import BotIdentity, HandledUpdates, TelegramCheck
from muscle50.presentation.telegram_format import (
    PIECE_BUDGET,
    TELEGRAM_MESSAGE_LIMIT,
    render_telegram_check,
    split_reply,
    telegram_messages,
    utf16_units,
)


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(urllib.request, "urlopen", lambda *args, **kwargs: pytest.fail("no network in tests"))


def _body(message: str) -> str:
    assert message.startswith("<pre>") and message.endswith("</pre>")
    return html.unescape(message[len("<pre>") : -len("</pre>")])


def test_short_text_is_one_pre_message_with_html_escaped() -> None:
    text = "a < b & c > d\n  \"quoted\" 'single'\n닭가슴살 (chicken-breast) 150 g"
    assert telegram_messages(text) == [
        "<pre>a &lt; b &amp; c &gt; d\n  \"quoted\" 'single'\n닭가슴살 (chicken-breast) 150 g</pre>"
    ]


def test_budget_leaves_room_for_the_pre_tags() -> None:
    assert PIECE_BUDGET == TELEGRAM_MESSAGE_LIMIT - 11


def test_exact_boundary_is_one_message_and_one_more_unit_splits_at_the_line_end() -> None:
    first = "x" * 2000
    fits = first + "\n" + "y" * (PIECE_BUDGET - 2001)
    assert utf16_units(fits) == PIECE_BUDGET
    assert split_reply(fits) == [fits]
    over = fits + "y"
    assert split_reply(over) == [first + "\n", "y" * (PIECE_BUDGET - 2000)]
    assert [_body(message) for message in telegram_messages(over)] == [first, "y" * (PIECE_BUDGET - 2000)]


def test_escaping_counts_toward_the_limit() -> None:
    line = "<" * 1100  # 4400 units once escaped
    pieces = split_reply(line)
    assert "".join(pieces) == line
    assert [len(piece) for piece in pieces] == [PIECE_BUDGET // 4, 1100 - PIECE_BUDGET // 4]
    for message in telegram_messages(line):
        assert utf16_units(message) <= TELEGRAM_MESSAGE_LIMIT


def test_an_over_long_single_line_is_hard_split_without_loss() -> None:
    line = "z" * (PIECE_BUDGET * 2 + 7)
    pieces = split_reply(line)
    assert pieces == ["z" * PIECE_BUDGET, "z" * PIECE_BUDGET, "z" * 7]


def test_emoji_count_two_units() -> None:
    line = "\U0001f357" * 2100  # 4200 UTF-16 units
    pieces = split_reply(line)
    assert "".join(pieces) == line
    assert [utf16_units(piece) for piece in pieces] == [PIECE_BUDGET - 1, 4200 - (PIECE_BUDGET - 1)]


def test_long_mixed_text_round_trips_and_every_message_fits() -> None:
    lines = [f"{index:05d} 닭가슴살 <{index}> & \U0001f357 " + "-" * (index % 70) for index in range(800)]
    text = "\n".join(lines)
    pieces = split_reply(text)
    assert len(pieces) > 1
    assert "".join(pieces) == text
    messages = telegram_messages(text)
    assert len(messages) == len(pieces)
    for piece, message in zip(pieces, messages, strict=True):
        assert utf16_units(message) <= TELEGRAM_MESSAGE_LIMIT
        assert _body(message) == piece.removesuffix("\n")
    # Every cut is at a line end here, so joining the message bodies with newlines restores the text.
    assert "\n".join(_body(message) for message in messages) == text


def test_a_piece_never_consists_of_blank_lines_only() -> None:
    text = "a" * (PIECE_BUDGET - 1) + "\n\n\n" + "b" * 10
    pieces = split_reply(text)
    assert "".join(pieces) == text
    assert all(piece.strip("\n") for piece in pieces)


IDENTITY = BotIdentity(1234567890, "muscle50_example_bot")
CONFIG = Path("C:/synthetic/home/config/telegram.json")


def test_check_report_without_state() -> None:
    check = TelegramCheck(IDENTITY, False, None)
    assert render_telegram_check(CONFIG, frozenset({222, 111}), check).split("\n") == [
        f"Telegram config: {CONFIG}",
        "Bot: @muscle50_example_bot (id 1234567890)",
        "Allowed chats: 111, 222",
        "Webhook: not set",
        "Handled updates on record: none",
        "No messages were read or answered.",
    ]


def test_check_report_with_state_webhook_and_foreign_state() -> None:
    own = TelegramCheck(IDENTITY, True, HandledUpdates(1234567890, (5490, 5501)))
    lines = render_telegram_check(CONFIG, frozenset({111}), own).split("\n")
    assert lines[3] == "Webhook: set (telegram run cannot poll while a webhook is set; remove it with deleteWebhook)"
    assert lines[4] == "Handled updates on record: 2 (latest 5501)"
    foreign = TelegramCheck(IDENTITY, False, HandledUpdates(999, (1,)))
    assert render_telegram_check(CONFIG, frozenset({111}), foreign).split("\n")[4] == (
        "Handled updates on record: belong to bot 999; run will start with none"
    )
