"""Recommend today's training from already-stored canonical data (read-only, no Garmin calls)."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date

from muscle50.application.inbody_trend import BodyCompositionReader
from muscle50.application.training_snapshot import TrainingDataReader
from muscle50.domain.activity import NormalizedActivity
from muscle50.domain.aerobic_guide import aerobic_history_start
from muscle50.domain.body_composition_trend import StoredBodyComposition
from muscle50.domain.exercise_taxonomy import MuscleGroup
from muscle50.domain.strength_recommendation import StrengthFocus
from muscle50.domain.training_goal import DEFAULT_SLEEP_SETTING, SleepThresholdSetting, TrainingGoal
from muscle50.domain.training_goals import DEFAULT_TRAINING_GOALS, TrainingGoals
from muscle50.domain.training_recommendation import (
    TrainingRecommendation,
    build_training_recommendation,
    history_start,
)
from muscle50.infrastructure.sqlite.body_composition_reader import BodyCompositionReadError


class BuildTrainingRecommendation:
    def __init__(
        self,
        reader: TrainingDataReader,
        goals: TrainingGoals = DEFAULT_TRAINING_GOALS,
        *,
        goal: TrainingGoal | None = None,
        sleep: SleepThresholdSetting = DEFAULT_SLEEP_SETTING,
        body_composition: BodyCompositionReader | None = None,
    ):
        """``goal`` and ``sleep`` are the user settings; InBody is read only when a goal is set."""
        self._reader = reader
        self._goals = goals
        self._goal = goal
        self._sleep = sleep
        self._body_composition = body_composition

    def execute(
        self,
        as_of: date,
        avoid_muscles: Iterable[MuscleGroup] = (),
        requested_focus: StrengthFocus | None = None,
    ) -> TrainingRecommendation:
        data = self._reader.load(history_start(as_of), as_of)
        rows: tuple[StoredBodyComposition, ...] | None = ()
        error: str | None = None
        aerobic: tuple[NormalizedActivity, ...] | None = None
        if self._goal is not None:
            rows, error = self._measurements()
            # The aerobic guide needs 37 days (a run's 30-day baseline); a separate read keeps the
            # plan inputs above exactly as they were.
            aerobic = self._reader.load(aerobic_history_start(as_of), as_of).activities
        return build_training_recommendation(
            as_of,
            data.activities,
            data.recoveries,
            goals=self._goals,
            avoid_muscles=avoid_muscles,
            undated_source_activity_ids=data.undated_source_activity_ids,
            requested_focus=requested_focus,
            sync_coverage=data.sync_coverage,
            goal=self._goal,
            body_composition=rows,
            body_composition_error=error,
            sleep=self._sleep,
            aerobic_activities=aerobic,
        )

    def _measurements(self) -> tuple[tuple[StoredBodyComposition, ...] | None, str | None]:
        # InBody only feeds goal-mode display lines: unreadable InBody data makes them "unknown",
        # it never fails the recommendation.
        if self._body_composition is None:
            return None, "no InBody reader"
        try:
            return self._body_composition.load_measurements(), None
        except BodyCompositionReadError as exc:
            return None, str(exc)
