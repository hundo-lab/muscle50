"""Transparent recovery rules for a training recommendation.

No composite score: each rule reads one stored Garmin field, compares it with a named
threshold, and either fires (``hold`` or ``reduce``) or not. The strongest fired rule sets
the adjustment level. A missing value never fires a rule; missing data means "no
adjustment possible", never "poor recovery".

Which row is used for which field matters because Garmin day-level values keep changing
through the day (and backfilled rows were captured after the fact):

- Row for the requested date: sleep and HRV status describe the night ending that morning;
  training readiness and its recovery time come from Garmin's morning readiness entry
  (``AFTER_WAKEUP_RESET``, see ``recovery_normalization``).
- Row for the previous date: training status, an end-of-day value.
- Body battery, stress, and resting HR are not used: their stored value can describe the
  state after the requested day's training.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from enum import StrEnum

from muscle50.domain.recovery import DailyRecovery

# Thresholds (account-calibrated against 2026-09 data; see docs/training-recommendation.md).
SHORT_SLEEP_SECONDS = 5 * 3600
VERY_SHORT_SLEEP_SECONDS = 4 * 3600
LOW_SLEEP_SCORE = 50
LONG_RECOVERY_TIME_MINUTES = 12 * 60
VERY_LONG_RECOVERY_TIME_MINUTES = 24 * 60
HOLD_HRV_STATUSES = frozenset({"LOW", "UNBALANCED", "POOR"})
HOLD_READINESS_LEVELS = frozenset({"LOW"})
REDUCE_READINESS_LEVELS = frozenset({"POOR"})
HOLD_TRAINING_STATUSES = frozenset({"STRAINED", "OVERREACHING", "UNPRODUCTIVE"})


class AdjustmentLevel(StrEnum):
    NORMAL = "normal"
    """Progression rules apply as usual."""
    HOLD = "hold"
    """No load increase and no added reps: repeat the last comparable performance."""
    REDUCE = "reduce"
    """As hold, plus one set fewer per exercise."""


_LEVEL_ORDER = {AdjustmentLevel.NORMAL: 0, AdjustmentLevel.HOLD: 1, AdjustmentLevel.REDUCE: 2}


def stronger(first: AdjustmentLevel, second: AdjustmentLevel) -> AdjustmentLevel:
    return first if _LEVEL_ORDER[first] >= _LEVEL_ORDER[second] else second


@dataclass(frozen=True)
class RecoveryObservation:
    """One stored field as read for the assessment; ``value`` is None when missing."""

    field: str
    source_date: date
    value: float | str | None
    fired_level: AdjustmentLevel | None
    rule: str | None


@dataclass(frozen=True)
class RecoveryAssessment:
    level: AdjustmentLevel
    requested_date_row_available: bool
    previous_date_row_available: bool
    observations: tuple[RecoveryObservation, ...]
    missing_fields: tuple[str, ...]

    @property
    def fired(self) -> tuple[RecoveryObservation, ...]:
        return tuple(item for item in self.observations if item.fired_level is not None)

    @property
    def data_available(self) -> bool:
        return any(item.value is not None for item in self.observations)


def assess_recovery(as_of: date, recoveries: Sequence[DailyRecovery]) -> RecoveryAssessment:
    by_date = {item.calendar_date: item for item in recoveries}
    today = by_date.get(as_of.isoformat())
    previous_day = as_of - timedelta(days=1)
    previous = by_date.get(previous_day.isoformat())

    observations = [
        _numeric(
            "sleep_seconds",
            as_of,
            today.sleep_seconds if today else None,
            ((VERY_SHORT_SLEEP_SECONDS, AdjustmentLevel.REDUCE), (SHORT_SLEEP_SECONDS, AdjustmentLevel.HOLD)),
            below=True,
            unit="s",
        ),
        _numeric(
            "sleep_score",
            as_of,
            today.sleep_score if today else None,
            ((LOW_SLEEP_SCORE, AdjustmentLevel.HOLD),),
            below=True,
            unit="",
        ),
        _categorical(
            "hrv_status",
            as_of,
            today.hrv_status if today else None,
            {AdjustmentLevel.HOLD: HOLD_HRV_STATUSES},
        ),
        _categorical(
            "training_readiness_level",
            as_of,
            today.training_readiness_level if today else None,
            {AdjustmentLevel.REDUCE: REDUCE_READINESS_LEVELS, AdjustmentLevel.HOLD: HOLD_READINESS_LEVELS},
        ),
        # Reported for context only; the level above is Garmin's own banding of this score.
        RecoveryObservation(
            "training_readiness_score",
            as_of,
            today.training_readiness_score if today else None,
            None,
            None,
        ),
        _numeric(
            "recovery_time_minutes",
            as_of,
            today.recovery_time_minutes if today else None,
            (
                (VERY_LONG_RECOVERY_TIME_MINUTES, AdjustmentLevel.REDUCE),
                (LONG_RECOVERY_TIME_MINUTES, AdjustmentLevel.HOLD),
            ),
            below=False,
            unit="min",
        ),
        _categorical(
            "training_status_key",
            previous_day,
            previous.training_status_key if previous else None,
            {AdjustmentLevel.HOLD: HOLD_TRAINING_STATUSES},
        ),
    ]
    level = AdjustmentLevel.NORMAL
    for item in observations:
        if item.fired_level is not None:
            level = stronger(level, item.fired_level)
    return RecoveryAssessment(
        level=level,
        requested_date_row_available=today is not None,
        previous_date_row_available=previous is not None,
        observations=tuple(observations),
        missing_fields=tuple(item.field for item in observations if item.value is None),
    )


def _numeric(
    field: str,
    source_date: date,
    value: float | None,
    thresholds: Sequence[tuple[float, AdjustmentLevel]],
    *,
    below: bool,
    unit: str,
) -> RecoveryObservation:
    if value is None:
        return RecoveryObservation(field, source_date, None, None, None)
    # Thresholds are ordered strongest first; the first one crossed fires.
    for threshold, level in thresholds:
        crossed = value < threshold if below else value >= threshold
        if crossed:
            comparison = "<" if below else ">="
            return RecoveryObservation(field, source_date, value, level, f"{field} {comparison} {threshold:g}{unit}")
    return RecoveryObservation(field, source_date, value, None, None)


def _categorical(
    field: str,
    source_date: date,
    value: str | None,
    rules: dict[AdjustmentLevel, frozenset[str]],
) -> RecoveryObservation:
    if value is None:
        return RecoveryObservation(field, source_date, None, None, None)
    for level, values in rules.items():
        if value.strip().upper() in values:
            return RecoveryObservation(field, source_date, value, level, f"{field} in {sorted(values)}")
    return RecoveryObservation(field, source_date, value, None, None)
