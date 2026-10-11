"""`config\\telegram_llm_coach.md`: the user's optional coach guide, read again for every LLM call.

UTF-8 (a BOM is accepted), at most `COACH_GUIDE_MAX_CHARS` characters. A missing file means no guide;
a file that is too long, not UTF-8 or unreadable is skipped for that call with a reason (never its text).
"""

from __future__ import annotations

from pathlib import Path

COACH_GUIDE_MAX_CHARS = 4000


class CoachGuideFile:
    def __init__(self, path: Path) -> None:
        self._path = path

    def read(self) -> tuple[str | None, str | None]:
        """(guide text, None), (None, None) when there is no file, or (None, reason) when it is skipped."""
        try:
            raw = self._path.read_bytes()
        except FileNotFoundError:
            return None, None
        except OSError as exc:
            return None, f"unreadable: {type(exc).__name__}"
        try:
            text = raw.decode("utf-8-sig").strip()
        except UnicodeDecodeError:
            return None, "not UTF-8"
        if len(text) > COACH_GUIDE_MAX_CHARS:
            return None, f"longer than {COACH_GUIDE_MAX_CHARS} characters"
        return (text or None), None
