"""Telegram presentation: CLI text as monospace HTML messages, and the `telegram check` report.

A reply is sent as ``<pre>`` + HTML-escaped text + ``</pre>`` with ``parse_mode=HTML``, so the
column alignment of the CLI text survives. Telegram allows 4096 characters per message, counted in
UTF-16 code units (an emoji counts 2). A longer reply is cut into consecutive pieces, preferably
at line ends; a single line longer than a message is cut inside the line. Nothing is dropped:
``"".join(split_reply(text)) == text``. The `telegram check` report is ASCII apart from the path.
"""

from __future__ import annotations

import html
from collections.abc import Iterable
from pathlib import Path

from muscle50.application.telegram_bot import TelegramCheck

TELEGRAM_MESSAGE_LIMIT = 4096
_PRE_OPEN = "<pre>"
_PRE_CLOSE = "</pre>"
# Room left for the escaped text of one piece.
PIECE_BUDGET = TELEGRAM_MESSAGE_LIMIT - len(_PRE_OPEN) - len(_PRE_CLOSE)


def utf16_units(text: str) -> int:
    return len(text.encode("utf-16-le")) // 2


def _escaped_units(character: str) -> int:
    return utf16_units(html.escape(character, quote=False))


def split_reply(text: str, budget: int = PIECE_BUDGET) -> list[str]:
    """Consecutive pieces of ``text`` whose escaped size (trailing newline included) fits ``budget``."""
    pieces: list[str] = []
    start = 0
    while start < len(text):
        used = 0
        position = start
        line_end: int | None = None
        has_content = False  # a piece never ends after blank lines only
        while position < len(text):
            character = text[position]
            units = _escaped_units(character)
            if used + units > budget:
                break
            used += units
            position += 1
            if character != "\n":
                has_content = True
            elif has_content:
                line_end = position
        if position == len(text):
            pieces.append(text[start:])
            break
        cut = line_end if line_end is not None else max(position, start + 1)
        pieces.append(text[start:cut])
        start = cut
    return pieces


def telegram_messages(text: str) -> list[str]:
    """``text`` as one or more ``<pre>`` HTML messages, each within the Telegram limit."""
    return [_pre(piece.removesuffix("\n")) for piece in split_reply(text)]


def _pre(text: str) -> str:
    return f"{_PRE_OPEN}{html.escape(text, quote=False)}{_PRE_CLOSE}"


def render_telegram_check(config_path: Path, allowed_chat_ids: Iterable[int], check: TelegramCheck) -> str:
    identity = check.identity
    if check.webhook_set:
        webhook = "set (telegram run cannot poll while a webhook is set; remove it with deleteWebhook)"
    else:
        webhook = "not set"
    handled = check.handled
    if handled is None:
        record = "none"
    elif handled.bot_id != identity.bot_id:
        record = f"belong to bot {handled.bot_id}; run will start with none"
    elif not handled.update_ids:
        record = "none"
    else:
        record = f"{len(handled.update_ids)} (latest {handled.update_ids[-1]})"
    return "\n".join(
        [
            f"Telegram config: {config_path}",
            f"Bot: @{identity.username} (id {identity.bot_id})",
            f"Allowed chats: {', '.join(str(chat_id) for chat_id in sorted(allowed_chat_ids))}",
            f"Webhook: {webhook}",
            f"Handled updates on record: {record}",
            "No messages were read or answered.",
        ]
    )
