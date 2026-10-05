"""Recommend today's training from already-stored canonical data (read-only, no Garmin calls)."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date

from muscle50.application.training_snapshot import TrainingDataReader
from muscle50.domain.exercise_taxonomy import MuscleGroup
from muscle50.domain.strength_recommendation import StrengthFocus
from muscle50.domain.training_goals import DEFAULT_TRAINING_GOALS, TrainingGoals
from muscle50.domain.training_recommendation import (
    TrainingRecommendation,
    build_training_recommendation,
    history_start,
)


class BuildTrainingRecommendation:
    def __init__(self, reader: TrainingDataReader, goals: TrainingGoals = DEFAULT_TRAINING_GOALS):
        self._reader = reader
        self._goals = goals

    def execute(
        self,
        as_of: date,
        avoid_muscles: Iterable[MuscleGroup] = (),
        requested_focus: StrengthFocus | None = None,
    ) -> TrainingRecommendation:
        data = self._reader.load(history_start(as_of), as_of)
        return build_training_recommendation(
            as_of,
            data.activities,
            data.recoveries,
            goals=self._goals,
            avoid_muscles=avoid_muscles,
            undated_source_activity_ids=data.undated_source_activity_ids,
            requested_focus=requested_focus,
            sync_coverage=data.sync_coverage,
        )
