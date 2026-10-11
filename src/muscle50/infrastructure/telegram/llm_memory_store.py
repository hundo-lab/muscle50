"""`config\\telegram_llm_memory.json`: per-chat conversation memory (a short summary and the last turns).

Owned by `telegram run`; written atomically. It holds message text, so it is never logged. A damaged
file raises `LlmMemoryError`: the bot then logs it, calls the LLM without memory and does not write
the file (so nothing is overwritten); `/forget` rewrites it for that chat.
"""

from __future__ import annotations

import json
import os
import uuid
from contextlib import suppress
from pathlib import Path
from typing import Any

from muscle50.domain.telegram_llm import EMPTY_MEMORY, ChatMemory, ChatTurn

SCHEMA_VERSION = 1


class LlmMemoryError(RuntimeError):
    """The memory file cannot be read or written (the message names the file, never its content)."""


class JsonLlmMemoryStore:
    def __init__(self, path: Path) -> None:
        self._path = path

    def get(self, chat_id: int) -> ChatMemory:
        return self._load().get(chat_id, EMPTY_MEMORY)

    def put(self, chat_id: int, memory: ChatMemory) -> None:
        chats = self._load()
        chats[chat_id] = memory
        self._save(chats)

    def clear(self, chat_id: int) -> None:
        try:
            chats = self._load()
        except LlmMemoryError:
            chats = {}  # /forget on a damaged file: start again with an empty memory
        chats.pop(chat_id, None)
        self._save(chats)

    def _load(self) -> dict[int, ChatMemory]:
        try:
            raw = self._path.read_bytes()
        except FileNotFoundError:
            return {}
        except OSError as exc:
            raise LlmMemoryError(f"cannot read {self._path.name} ({type(exc).__name__})") from None
        try:
            document = json.loads(raw.decode("utf-8"))
            if not isinstance(document, dict) or document.get("schema_version") != SCHEMA_VERSION:
                raise ValueError("schema")
            return {int(chat): _memory(entry) for chat, entry in document["chats"].items()}
        except (KeyError, TypeError, ValueError) as exc:
            raise LlmMemoryError(f"{self._path.name} is damaged ({type(exc).__name__})") from None

    def _save(self, chats: dict[int, ChatMemory]) -> None:
        document = {
            "schema_version": SCHEMA_VERSION,
            "chats": {str(chat): _document(chats[chat]) for chat in sorted(chats)},
        }
        temporary = self._path.with_name(f".{self._path.name}.{uuid.uuid4().hex}.tmp")
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with temporary.open("w", encoding="utf-8", newline="\n") as handle:
                handle.write(json.dumps(document, indent=2, ensure_ascii=True) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self._path)
        except OSError as exc:
            raise LlmMemoryError(f"cannot write {self._path.name} ({type(exc).__name__})") from None
        finally:
            with suppress(FileNotFoundError):
                temporary.unlink()


def _memory(entry: Any) -> ChatMemory:
    summary = entry["summary"]
    if summary is not None and not isinstance(summary, str):
        raise TypeError("summary")
    turns = tuple(ChatTurn(int(turn["at"]), str(turn["user"]), str(turn["bot"])) for turn in entry["turns"])
    return ChatMemory(summary, turns)


def _document(memory: ChatMemory) -> dict[str, Any]:
    return {
        "summary": memory.summary,
        "turns": [{"at": turn.at_unix, "user": turn.user, "bot": turn.bot} for turn in memory.turns],
    }
