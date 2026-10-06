"""Show the InBody body-composition trend from already-stored measurements (read-only, no provider calls)."""

from __future__ import annotations

from datetime import date
from typing import Protocol

from muscle50.domain.body_composition_trend import (
    BodyCompositionTrend,
    StoredBodyComposition,
    build_body_composition_trend,
    validate_trend_range,
)
from muscle50.domain.training_goals import DEFAULT_TRAINING_GOALS, TrainingGoals


class BodyCompositionReader(Protocol):
    def load_measurements(self) -> tuple[StoredBodyComposition, ...]:
        """Every stored InBody measurement, in stored-id order."""
        ...


class ShowBodyCompositionTrend:
    def __init__(self, reader: BodyCompositionReader, goals: TrainingGoals = DEFAULT_TRAINING_GOALS):
        self._reader = reader
        self._goals = goals

    def execute(self, from_date: date | None, to_date: date | None, *, today: date) -> BodyCompositionTrend:
        """The trend for an inclusive local-date range; the reference date is ``to_date`` or ``today``."""
        # Validate the range before touching the database.
        validate_trend_range(from_date, to_date)
        rows = self._reader.load_measurements()
        return build_body_composition_trend(
            rows,
            from_date=from_date,
            to_date=to_date,
            reference_date=to_date if to_date is not None else today,
            goals=self._goals,
        )
