"""How many ACTIVE sets of one stored Garmin activity are UNKNOWN (Telegram `/refresh` before/after).

Read-only. The count uses the recommendation's own predicate (`unknown_active_set_sequences`), so
it matches the `strength.unknown_notices` entry of the same activity whatever its date. Nothing is
guessed: an activity that is not stored is ``None``, and a non-strength activity says so.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Protocol

from muscle50.domain.activity import ActivityType, NormalizedActivity
from muscle50.domain.analytics import activity_local_date
from muscle50.domain.strength_recommendation import unknown_active_set_sequences


@dataclass(frozen=True)
class ActivityUnknownSets:
    source_activity_id: str
    local_date: date | None
    """Garmin's local start date; None when the stored activity has no usable local start time."""
    is_strength: bool
    unknown_set_count: int
    set_sequences: tuple[int, ...]


class StoredActivityReader(Protocol):
    def load_activity(self, source_activity_id: str) -> NormalizedActivity | None: ...


class CountActivityUnknownSets:
    def __init__(self, reader: StoredActivityReader) -> None:
        self._reader = reader

    def execute(self, source_activity_id: str) -> ActivityUnknownSets | None:
        """None when the activity is not stored."""
        activity = self._reader.load_activity(source_activity_id)
        if activity is None:
            return None
        sequences = unknown_active_set_sequences(activity)
        return ActivityUnknownSets(
            source_activity_id=activity.source_activity_id,
            local_date=activity_local_date(activity),
            is_strength=activity.canonical_type is ActivityType.STRENGTH,
            unknown_set_count=len(sequences),
            set_sequences=sequences,
        )
