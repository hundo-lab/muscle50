"""The training snapshot plus strength set timing, computed on read from stored sets and RAW (no Garmin calls).

Nothing is stored: the estimates are recomputed from the canonical sets and the stored
``details.json`` every time, and they are display only.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Protocol

from muscle50.application.training_snapshot import TrainingDataReader, snapshot_from_data
from muscle50.domain.activity import NormalizedActivity
from muscle50.domain.analytics import DEFAULT_LOOKBACK_DAYS, TrainingSnapshot, activity_local_date, snapshot_window
from muscle50.domain.strength_set_timing import (
    HeartRateLoad,
    StrengthSetTimingSummary,
    needs_heart_rate,
    summarize_set_timing,
)


class HeartRateSource(Protocol):
    def load(self, source_activity_id: str) -> HeartRateLoad: ...


@dataclass(frozen=True)
class SnapshotWithSetTiming:
    snapshot: TrainingSnapshot
    set_timing: StrengthSetTimingSummary | None
    """None when the window has no set that is too short for its reps."""


class BuildSnapshotWithSetTiming:
    def __init__(self, reader: TrainingDataReader, heart_rate: HeartRateSource) -> None:
        self._reader = reader
        self._heart_rate = heart_rate

    def execute(self, as_of: date, lookback_days: int = DEFAULT_LOOKBACK_DAYS) -> SnapshotWithSetTiming:
        # Validate the window before touching the database.
        window = snapshot_window(as_of, lookback_days)
        data = self._reader.load(window.start, window.as_of)
        snapshot = snapshot_from_data(as_of, lookback_days, data)
        strength_ids = set(snapshot.strength.source_activity_ids)
        sessions: list[tuple[date, NormalizedActivity]] = []
        for activity in data.activities:
            day = activity_local_date(activity)
            if day is not None and activity.source_activity_id in strength_ids:
                sessions.append((day, activity))
        sessions.sort(key=lambda item: (item[0], item[1].started_at_local or "", item[1].source_activity_id))
        # The series is read only for activities with a suspect set right after a REST.
        heart_rates = {
            activity.source_activity_id: self._heart_rate.load(activity.source_activity_id)
            for _day, activity in sessions
            if needs_heart_rate(activity)
        }
        return SnapshotWithSetTiming(snapshot, summarize_set_timing(sessions, heart_rates))
