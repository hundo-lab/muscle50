"""`telegram\\history\\YYYY-MM.jsonl`: the append-only log of every free-text, photo and proposal exchange.

One JSON line per exchange (`json.dumps(..., ensure_ascii=True)`, fixed key order), appended and fsynced;
never rewritten or deleted by muscle50. The month is the entry's own local date (`at`). Reading is
read-only and creates nothing; an unreadable line is an error, never skipped silently.
"""

from __future__ import annotations

import json
import os
from datetime import date
from pathlib import Path
from typing import Any

from muscle50.domain.telegram_llm import check_history_entry


class HistoryReadError(RuntimeError):
    """A history file or line cannot be read (the message names the file and line, never its text)."""


class JsonlHistoryLog:
    def __init__(self, directory: Path) -> None:
        self._directory = directory

    def append(self, entry: dict[str, Any]) -> None:
        line = json.dumps(check_history_entry(entry), ensure_ascii=True) + "\n"
        path = self._directory / f"{entry['at'][:7]}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="ascii", newline="\n") as handle:
            handle.write(line)
            handle.flush()
            os.fsync(handle.fileno())

    def read(self, *, last: int | None = None, day: date | None = None) -> tuple[dict[str, Any], ...]:
        """Entries in file order: the newest ``last`` ones, or the ones whose local date is ``day``."""
        if not self._directory.is_dir():
            return ()
        files = sorted(path for path in self._directory.glob("*.jsonl") if path.is_file())
        if day is not None:
            files = [path for path in files if path.stem == day.isoformat()[:7]]
        entries: list[dict[str, Any]] = []
        for path in files:
            entries.extend(_read_file(path))
        if day is not None:
            return tuple(entry for entry in entries if entry["at"][:10] == day.isoformat())
        return tuple(entries[-last:]) if last is not None else tuple(entries)

    def exists(self) -> bool:
        return self._directory.is_dir() and any(self._directory.glob("*.jsonl"))


def _read_file(path: Path) -> list[dict[str, Any]]:
    try:
        text = path.read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise HistoryReadError(f"대화 기록 파일을 읽을 수 없습니다: {path} ({type(exc).__name__})") from None
    entries = []
    for number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            entries.append(check_history_entry(json.loads(line)))
        except ValueError:
            raise HistoryReadError(f"대화 기록 파일의 {number}번째 줄을 읽을 수 없습니다: {path}") from None
    return entries
