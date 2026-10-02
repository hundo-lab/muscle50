"""Attach the day's nutrition status to an already-built training recommendation.

The training recommendation is built first and is never changed here. The nutrition status is
exactly ``ShowDailyNutritionStatus`` for the same date (same meals, aggregation and target
comparison as ``muscle50 nutrition status``); ``build_nutrition_guidance`` only decides which
statuses are worth an action. Nutrition is an extra signal: if it cannot be read, the result
says so and the training recommendation stands on its own.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, tzinfo
from typing import Protocol

from muscle50.application.nutrition_logging import offset_name
from muscle50.application.nutrition_targets import DailyNutritionStatus
from muscle50.domain.nutrition_guidance import NutritionGuidance, build_nutrition_guidance, unavailable_guidance
from muscle50.domain.nutrition_targets import NutritionTargetError
from muscle50.domain.training_recommendation import TrainingRecommendation
from muscle50.infrastructure.sqlite.nutrition_reader import NutritionReadError

# Expected ways for nutrition to be unreadable; anything else is a bug and propagates.
_UNAVAILABLE_ERRORS = (NutritionReadError, NutritionTargetError, sqlite3.Error)


class DailyNutritionStatusSource(Protocol):
    def execute(self, day: date, timezone: tzinfo, *, timezone_name: str) -> DailyNutritionStatus: ...


@dataclass(frozen=True)
class NutritionContext:
    day: date
    timezone_name: str
    # None only when nutrition could not be read (availability "unavailable").
    status: DailyNutritionStatus | None
    guidance: NutritionGuidance
    unavailable_reason: str | None = None


class BuildNutritionContext:
    def __init__(self, status: DailyNutritionStatusSource, timezone_for: Callable[[date], tzinfo]) -> None:
        self._status = status
        self._timezone_for = timezone_for

    def execute(self, as_of: date, training: TrainingRecommendation) -> NutritionContext:
        zone = self._timezone_for(as_of)
        name = offset_name(zone, as_of)
        try:
            status = self._status.execute(as_of, zone, timezone_name=name)
        except _UNAVAILABLE_ERRORS as exc:
            return NutritionContext(as_of, name, None, unavailable_guidance(training), str(exc))
        guidance = build_nutrition_guidance(tuple(day_status.status for day_status in status.nutrients), training)
        return NutritionContext(as_of, name, status, guidance)
