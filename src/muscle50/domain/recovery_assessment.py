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

Lookback (a partial requested-date row must not erase clearly poor recent mornings):

- It applies only when the requested date's row is missing or has no ``sleep_seconds``
  (the night measurement; a readiness value without it was computed without last night).
- The morning fields of D-1 and D-2 (sleep, sleep score, readiness level, recovery time) are
  checked with the same thresholds. ``hold`` is carried when D-1 fired a reduce-level rule
  or both D-1 and D-2 fired any rule. Carried evidence is never stronger than ``hold``
  because it is not today's measurement. A missing earlier value never fires.
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
# Earlier mornings checked when the requested date has no sleep measurement.
LOOKBACK_DAYS = 2


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
class RecoveryLookback:
    """Earlier mornings checked because the requested date has no sleep measurement."""

    reason: str
    observations: tuple[RecoveryObservation, ...]
    """D-1 and D-2 morning fields (``source_date`` says which day); never part of today's."""
    poor_dates: tuple[date, ...]
    carried_level: AdjustmentLevel | None
    """``hold`` when carried into today's level, else None (evidence only)."""
    explanation: str


@dataclass(frozen=True)
class RecoveryAssessment:
    level: AdjustmentLevel
    requested_date_row_available: bool
    previous_date_row_available: bool
    observations: tuple[RecoveryObservation, ...]
    missing_fields: tuple[str, ...]
    lookback: RecoveryLookback | None = None

    @property
    def fired(self) -> tuple[RecoveryObservation, ...]:
        return tuple(item for item in self.observations if item.fired_level is not None)

    @property
    def data_available(self) -> bool:
        return any(item.value is not None for item in self.observations)

    @property
    def carried(self) -> bool:
        return self.lookback is not None and self.lookback.carried_level is not None


def assess_recovery(as_of: date, recoveries: Sequence[DailyRecovery]) -> RecoveryAssessment:
    by_date = {item.calendar_date: item for item in recoveries}
    today = by_date.get(as_of.isoformat())
    previous_day = as_of - timedelta(days=1)
    previous = by_date.get(previous_day.isoformat())

    observations = [
        *_morning_observations(as_of, today, include_hrv=True),
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
    lookback = _lookback(as_of, today, by_date)
    if lookback is not None and lookback.carried_level is not None:
        level = stronger(level, lookback.carried_level)
    return RecoveryAssessment(
        level=level,
        requested_date_row_available=today is not None,
        previous_date_row_available=previous is not None,
        observations=tuple(observations),
        missing_fields=tuple(item.field for item in observations if item.value is None),
        lookback=lookback,
    )


def _morning_observations(day: date, row: DailyRecovery | None, *, include_hrv: bool) -> list[RecoveryObservation]:
    observations = [
        _numeric(
            "sleep_seconds",
            day,
            row.sleep_seconds if row else None,
            ((VERY_SHORT_SLEEP_SECONDS, AdjustmentLevel.REDUCE), (SHORT_SLEEP_SECONDS, AdjustmentLevel.HOLD)),
            below=True,
            unit="s",
        ),
        _numeric(
            "sleep_score",
            day,
            row.sleep_score if row else None,
            ((LOW_SLEEP_SCORE, AdjustmentLevel.HOLD),),
            below=True,
            unit="",
        ),
    ]
    if include_hrv:
        observations.append(
            _categorical("hrv_status", day, row.hrv_status if row else None, {AdjustmentLevel.HOLD: HOLD_HRV_STATUSES})
        )
    observations.extend(
        (
            _categorical(
                "training_readiness_level",
                day,
                row.training_readiness_level if row else None,
                {AdjustmentLevel.REDUCE: REDUCE_READINESS_LEVELS, AdjustmentLevel.HOLD: HOLD_READINESS_LEVELS},
            ),
            # Reported for context only; the level above is Garmin's own banding of this score.
            RecoveryObservation(
                "training_readiness_score",
                day,
                row.training_readiness_score if row else None,
                None,
                None,
            ),
            _numeric(
                "recovery_time_minutes",
                day,
                row.recovery_time_minutes if row else None,
                (
                    (VERY_LONG_RECOVERY_TIME_MINUTES, AdjustmentLevel.REDUCE),
                    (LONG_RECOVERY_TIME_MINUTES, AdjustmentLevel.HOLD),
                ),
                below=False,
                unit="min",
            ),
        )
    )
    return observations


def _lookback(as_of: date, today: DailyRecovery | None, by_date: dict[str, DailyRecovery]) -> RecoveryLookback | None:
    if today is not None and today.sleep_seconds is not None:
        return None
    reason = (
        f"no recovery row for {as_of.isoformat()}"
        if today is None
        else f"no sleep recorded for {as_of.isoformat()} (row is partial)"
    )
    observations: list[RecoveryObservation] = []
    fired_by_day: dict[date, list[RecoveryObservation]] = {}
    for offset in range(1, LOOKBACK_DAYS + 1):
        day = as_of - timedelta(days=offset)
        # HRV status is a rolling weekly status, not one morning's signal; it is not carried.
        day_observations = _morning_observations(day, by_date.get(day.isoformat()), include_hrv=False)
        observations.extend(day_observations)
        fired = [item for item in day_observations if item.fired_level is not None]
        if fired:
            fired_by_day[day] = fired
    previous_day = as_of - timedelta(days=1)
    previous_reduce = any(item.fired_level is AdjustmentLevel.REDUCE for item in fired_by_day.get(previous_day, ()))
    carried = previous_reduce or len(fired_by_day) == LOOKBACK_DAYS
    evidence = "; ".join(
        f"{day.isoformat()}: {', '.join(_fired_text(item) for item in items)}"
        for day, items in sorted(fired_by_day.items(), reverse=True)
    )
    if carried:
        trigger = (
            f"{previous_day.isoformat()} fired a reduce-level rule"
            if previous_reduce
            else f"both of the previous {LOOKBACK_DAYS} mornings were poor"
        )
        explanation = (
            f"{reason}; {trigger} ({evidence}): hold carried forward (capped at hold because it is not "
            "today's measurement)"
        )
    elif fired_by_day:
        explanation = (
            f"{reason}; earlier poor signal ({evidence}) is not enough to carry forward "
            f"(needs a reduce-level rule on {previous_day.isoformat()} or both previous mornings poor)"
        )
    else:
        explanation = f"{reason}; the previous {LOOKBACK_DAYS} mornings fired no rule (missing values never fire)"
    return RecoveryLookback(
        reason=reason,
        observations=tuple(observations),
        poor_dates=tuple(sorted(fired_by_day, reverse=True)),
        carried_level=AdjustmentLevel.HOLD if carried else None,
        explanation=explanation,
    )


def _fired_text(item: RecoveryObservation) -> str:
    if item.field == "sleep_seconds" and isinstance(item.value, (int, float)):
        hours, minutes = divmod(int(item.value) // 60, 60)
        value = f"{hours}h{minutes:02d}m"
    else:
        value = str(item.value)
    return f"{item.field} {value} ({item.rule})"


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
