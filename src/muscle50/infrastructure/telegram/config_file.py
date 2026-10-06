"""`config\\telegram.json`: the bot token and the allowed chat ids, written by the user.

Read strictly, in a fixed order, before any network call. Error messages name the file and what
is wrong, but never echo the token, another key or a value.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_TOKEN = re.compile(r"[0-9]+:[A-Za-z0-9_-]+")
_KEYS = frozenset({"bot_token", "allowed_chat_ids"})


class TelegramConfigError(RuntimeError):
    """`config\\telegram.json` is missing or invalid. The message never contains the token."""


@dataclass(frozen=True)
class TelegramConfig:
    bot_token: str = field(repr=False)
    allowed_chat_ids: frozenset[int]


def load_telegram_config(path: Path) -> TelegramConfig:
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        raise TelegramConfigError(
            f'telegram 설정 파일이 없습니다: {path}. docs/telegram-bot.md의 "설정"대로 만드세요.'
        ) from None
    except OSError as exc:
        raise TelegramConfigError(f"telegram 설정 파일을 읽을 수 없습니다: {path} ({exc.strerror})") from None
    try:
        text = raw.decode("utf-8-sig")  # a BOM written by Notepad is accepted
    except UnicodeDecodeError:
        raise TelegramConfigError(f"telegram 설정 파일이 UTF-8이 아닙니다: {path}") from None
    try:
        document: Any = json.loads(text)
    except json.JSONDecodeError as exc:
        # Only the position: the message of a decode error can quote the file content.
        raise TelegramConfigError(
            f"telegram 설정 파일이 올바른 JSON이 아닙니다: {path} (line {exc.lineno}, column {exc.colno})"
        ) from None
    if not isinstance(document, dict) or set(document) != _KEYS:
        raise TelegramConfigError(f"telegram 설정 파일에는 bot_token과 allowed_chat_ids 두 key만 있어야 합니다: {path}")
    token = document["bot_token"]
    if not isinstance(token, str) or _TOKEN.fullmatch(token) is None:
        raise TelegramConfigError("bot_token은 BotFather가 준 token 문자열(숫자:문자)이어야 합니다.")
    return TelegramConfig(token, _chat_ids(document["allowed_chat_ids"]))


def _chat_ids(value: Any) -> frozenset[int]:
    if not isinstance(value, list):
        raise TelegramConfigError("allowed_chat_ids는 chat id 정수의 목록이어야 합니다.")
    if not value:
        raise TelegramConfigError("allowed_chat_ids가 비어 있습니다. 허용할 chat id를 하나 이상 넣으세요.")
    seen: set[int] = set()
    for index, item in enumerate(value, start=1):
        if type(item) is not int:  # bool is refused too
            raise TelegramConfigError(f"allowed_chat_ids의 {index}번째 값은 따옴표 없는 정수여야 합니다.")
        if item in seen:
            raise TelegramConfigError(f"allowed_chat_ids에 같은 chat id가 두 번 있습니다: {item}")
        seen.add(item)
    return frozenset(seen)
