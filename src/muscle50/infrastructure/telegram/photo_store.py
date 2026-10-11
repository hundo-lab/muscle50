"""`telegram\\photos\\YYYY-MM\\<sha256>.<ext>`: photos sent to the bot, kept once and never rewritten.

Content-addressed like the RAW snapshots: the same photo twice is one file. muscle50 never deletes
them (the user does). With `"keep_photos": false` nothing is written.
"""

from __future__ import annotations

import hashlib
import os
import uuid
from contextlib import suppress
from datetime import date
from pathlib import Path

from muscle50.infrastructure.llm.argv import image_suffix


class PhotoStore:
    def __init__(self, root: Path, directory: Path) -> None:
        self._root = root
        self._directory = directory

    def keep(self, data: bytes, day: date) -> str:
        """The photo's path relative to MUSCLE50_HOME, with `/` separators."""
        name = hashlib.sha256(data).hexdigest() + image_suffix(data)
        path = self._directory / day.isoformat()[:7] / name
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_name(f".{name}.{uuid.uuid4().hex}.tmp")
            try:
                with temporary.open("wb") as handle:
                    handle.write(data)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary, path)
            finally:
                with suppress(FileNotFoundError):
                    temporary.unlink()
        return path.relative_to(self._root).as_posix()


def photo_digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
