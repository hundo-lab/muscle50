"""Build a rolling training snapshot from already-stored canonical data (no Garmin calls)."""

from __future__ import annotations

from datetime import date
from typing import Protocol

from muscle50.domain.analytics import (
    DEFAULT_LOOKBACK_DAYS,
    TrainingSnapshot,
    build_training_snapshot,
    snapshot_window,
)
from muscle50.infrastructure.sqlite.analytics_reader import TrainingData


class TrainingDataReader(Protocol):
    def load(self, start: date, end: date) -> TrainingData: ...


class BuildTrainingSnapshot:
    def __init__(self, reader: TrainingDataReader):
        self._reader = reader

    def execute(self, as_of: date, lookback_days: int = DEFAULT_LOOKBACK_DAYS) -> TrainingSnapshot:
        # Validate the window before touching the database.
        window = snapshot_window(as_of, lookback_days)
        data = self._reader.load(window.start, window.as_of)
        return build_training_snapshot(
            as_of,
            lookback_days,
            data.activities,
            data.recoveries,
            undated_source_activity_ids=data.undated_source_activity_ids,
        )
