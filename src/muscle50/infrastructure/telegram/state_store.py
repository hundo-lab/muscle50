"""`config\\telegram_state.json`: the update ids `telegram run` has already handled.

Owned by `telegram run`, which creates it when it handles its first allowed message. Versioned,
written atomically (temp file, fsync, `os.replace`, like the nutrition targets file), and read
strictly: a damaged file is an error, never "nothing handled yet". It holds no DB data.
"""

from __future__ import annotations

import json
import os
import uuid
from contextlib import suppress
from pathlib import Path
from typing import Any

from muscle50.application.telegram_bot import MAX_HANDLED_UPDATES, HandledUpdates, TelegramStateError

SCHEMA_VERSION = 1
_KEYS = frozenset({"schema_version", "bot_id", "handled_update_ids"})


class JsonHandledUpdateStore:
    def __init__(self, path: Path) -> None:
        self._path = path

    def load(self) -> HandledUpdates | None:
        try:
            raw = self._path.read_bytes()
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise TelegramStateError(f"telegram 상태 파일을 읽을 수 없습니다: {self._path} ({exc.strerror})") from None
        try:
            return _handled_from_document(json.loads(raw.decode("utf-8")))
        except UnicodeDecodeError:
            reason = "not UTF-8"
        except json.JSONDecodeError as exc:
            reason = f"not valid JSON: line {exc.lineno}, column {exc.colno}"
        except ValueError as exc:
            reason = str(exc)
        raise TelegramStateError(
            f"telegram 상태 파일이 올바르지 않습니다: {self._path} ({reason}). telegram run이 만드는 파일입니다. "
            "지우고 다시 시작해도 됩니다(bot 시작 전에 보낸 메시지는 실행하지 않습니다)."
        )

    def save(self, handled: HandledUpdates) -> None:
        content = json.dumps(state_document(handled), indent=2, ensure_ascii=True) + "\n"
        temporary = self._path.with_name(f".{self._path.name}.{uuid.uuid4().hex}.tmp")
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with temporary.open("w", encoding="utf-8", newline="\n") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self._path)
        except OSError as exc:
            raise TelegramStateError(
                f"telegram 상태 파일을 쓸 수 없습니다: {self._path} ({exc.strerror}). 명령은 실행하지 않았습니다."
            ) from None
        finally:
            with suppress(FileNotFoundError):
                temporary.unlink()


def state_document(handled: HandledUpdates) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "bot_id": handled.bot_id,
        "handled_update_ids": list(handled.update_ids),
    }


def _handled_from_document(document: Any) -> HandledUpdates:
    if not isinstance(document, dict) or set(document) != _KEYS:
        raise ValueError("expected exactly the keys schema_version, bot_id and handled_update_ids")
    version = document["schema_version"]
    if type(version) is not int or version != SCHEMA_VERSION:
        raise ValueError(f"unsupported schema_version {version!r}")
    bot_id = document["bot_id"]
    if type(bot_id) is not int:
        raise ValueError("bot_id must be an integer")
    ids = document["handled_update_ids"]
    if (
        not isinstance(ids, list)
        or len(ids) > MAX_HANDLED_UPDATES
        or any(type(item) is not int for item in ids)
        or len(set(ids)) != len(ids)
    ):
        raise ValueError(f"handled_update_ids must be a list of at most {MAX_HANDLED_UPDATES} distinct integers")
    return HandledUpdates(bot_id, tuple(ids))
