"""InBody body-composition trend over stored measurements (InBody Body Composition Trend v1).

Pure and deterministic: no I/O, no clock. Rules (docs/inbody-trend.md):

- A measurement's local date and clock time are the date and time written in its stored
  ``measured_at`` string, i.e. the local time where it was measured. Nothing is converted to this
  computer's zone, and no zone is guessed for a stored time without an offset.
- Order is (local date, stored clock time, UTC instant or "" when the stored time has no offset,
  stored id). The UTC instant is only a tiebreak; it is never displayed.
- Stored floats are rounded to 0.1 with ROUND_HALF_EVEN on their shortest repr, the same 0.1 rule
  the InBody canonical fingerprint uses. Changes are rounded value minus rounded value.
- A missing value stays ``None``; it is never 0. Every metric is its own series.
- Each metric gets at most one point per local date. When the rows of one date disagree (after
  rounding), that date and metric are a conflict and are left out of the trend; no value is chosen.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from decimal import ROUND_HALF_EVEN, Decimal
from enum import StrEnum

from muscle50.domain.training_goals import TrainingGoals

TENTH = Decimal("0.1")
PER_DAYS = 28
"""``per_28_days`` is computed only when the first and last dates are at least this many days apart."""


class TrendMetric(StrEnum):
    WEIGHT_KG = "weight_kg"
    SKELETAL_MUSCLE_MASS_KG = "skeletal_muscle_mass_kg"
    BODY_FAT_MASS_KG = "body_fat_mass_kg"
    BODY_FAT_PERCENT = "body_fat_percent"


METRICS = tuple(TrendMetric)


class InvalidTrendRangeError(ValueError):
    """Raised when ``--from`` is after ``--to``."""


class InvalidStoredMeasurementError(ValueError):
    """Raised when a stored row cannot be read without guessing (the normalizer prevents both cases)."""


@dataclass(frozen=True)
class StoredBodyComposition:
    """The trend columns of one stored ``body_composition_measurements`` row."""

    row_id: int
    measured_at: str
    weight_kg: float | None
    skeletal_muscle_mass_kg: float | None
    body_fat_mass_kg: float | None
    body_fat_percent: float | None

    def value(self, metric: TrendMetric) -> float | None:
        value: float | None = getattr(self, metric.value)
        return value


@dataclass(frozen=True)
class TrendMeasurement:
    measured_at: str
    """The stored string, unchanged."""
    local_date: date
    local_time: time
    """The clock time written in the stored string (no zone conversion)."""
    values: tuple[Decimal | None, ...]
    """Rounded values in ``METRICS`` order; ``None`` when missing."""

    def value(self, metric: TrendMetric) -> Decimal | None:
        return self.values[METRICS.index(metric)]


@dataclass(frozen=True)
class MetricConflict:
    local_date: date
    metric: TrendMetric
    values: tuple[Decimal, ...]
    """Rounded values of the rows that have this metric on this date, in list order."""


@dataclass(frozen=True)
class IntervalChange:
    from_date: date
    to_date: date
    days: int
    changes: tuple[Decimal | None, ...]
    """In ``METRICS`` order; ``None`` unless both dates have a point for that metric."""

    def change(self, metric: TrendMetric) -> Decimal | None:
        return self.changes[METRICS.index(metric)]


@dataclass(frozen=True)
class OverallChange:
    metric: TrendMetric
    from_date: date | None
    to_date: date | None
    days: int | None
    change: Decimal | None
    per_28_days: Decimal | None


@dataclass(frozen=True)
class GoalProgress:
    target: Decimal
    remaining: Decimal | None
    """``None`` when reached or unknown."""
    reached: bool | None
    """``None`` when there is no usable skeletal muscle mass point (unknown, not false)."""


@dataclass(frozen=True)
class SkeletalMuscleGoal:
    latest: Decimal | None
    latest_date: date | None
    milestone: GoalProgress
    long_term: GoalProgress


@dataclass(frozen=True)
class BodyCompositionTrend:
    from_date: date | None
    to_date: date | None
    reference_date: date
    measurements: tuple[TrendMeasurement, ...]
    intervals: tuple[IntervalChange, ...]
    overall: tuple[OverallChange, ...]
    """One entry per metric, in ``METRICS`` order."""
    goal: SkeletalMuscleGoal
    conflicts: tuple[MetricConflict, ...]
    last_measurement_date: date | None
    days_since_last_measurement: int | None

    @property
    def dates(self) -> tuple[date, ...]:
        """Distinct local dates of the listed measurements, ascending."""
        return tuple(sorted({item.local_date for item in self.measurements}))


def round_tenth(value: float) -> Decimal:
    """Round a stored float to 0.1 (HALF_EVEN on its shortest repr, as ``_canonical_number`` does)."""
    if not math.isfinite(value):
        raise InvalidStoredMeasurementError(f"stored InBody value is not finite: {value!r}")
    return _tenth(Decimal(repr(value)))


def validate_trend_range(from_date: date | None, to_date: date | None) -> None:
    if from_date is not None and to_date is not None and from_date > to_date:
        raise InvalidTrendRangeError("--from은 --to보다 이후일 수 없습니다.")


def build_body_composition_trend(
    rows: Sequence[StoredBodyComposition],
    *,
    from_date: date | None,
    to_date: date | None,
    reference_date: date,
    goals: TrainingGoals,
) -> BodyCompositionTrend:
    validate_trend_range(from_date, to_date)
    keyed = [_measurement(row) for row in rows]
    in_range = [
        item
        for item in keyed
        if (from_date is None or item[1].local_date >= from_date) and (to_date is None or item[1].local_date <= to_date)
    ]
    in_range.sort(key=lambda item: item[0])
    measurements = tuple(item[1] for item in in_range)
    dates = tuple(sorted({item.local_date for item in measurements}))

    points: dict[TrendMetric, dict[date, Decimal]] = {metric: {} for metric in METRICS}
    conflicts: list[MetricConflict] = []
    for day in dates:
        same_day = [item for item in measurements if item.local_date == day]
        for metric in METRICS:
            values = tuple(value for item in same_day if (value := item.value(metric)) is not None)
            if not values:
                continue
            if len(set(values)) == 1:
                points[metric][day] = values[0]
            else:
                conflicts.append(MetricConflict(day, metric, values))

    intervals = tuple(
        IntervalChange(
            earlier,
            later,
            (later - earlier).days,
            tuple(_difference(points[metric].get(earlier), points[metric].get(later)) for metric in METRICS),
        )
        for earlier, later in zip(dates, dates[1:], strict=False)
    )
    overall = tuple(_overall(metric, points[metric]) for metric in METRICS)
    last_date = dates[-1] if dates else None
    return BodyCompositionTrend(
        from_date=from_date,
        to_date=to_date,
        reference_date=reference_date,
        measurements=measurements,
        intervals=intervals,
        overall=overall,
        goal=_goal(points[TrendMetric.SKELETAL_MUSCLE_MASS_KG], goals),
        conflicts=tuple(conflicts),
        last_measurement_date=last_date,
        days_since_last_measurement=(reference_date - last_date).days if last_date is not None else None,
    )


type _SortKey = tuple[date, time, str, int]


def _measurement(row: StoredBodyComposition) -> tuple[_SortKey, TrendMeasurement]:
    try:
        parsed = datetime.fromisoformat(row.measured_at)
    except ValueError as exc:
        raise InvalidStoredMeasurementError(
            f"stored InBody measurement {row.row_id} has an unreadable measured_at: {row.measured_at!r}"
        ) from exc
    values: list[Decimal | None] = []
    for metric in METRICS:
        value = row.value(metric)
        if value is None:
            values.append(None)
            continue
        if not math.isfinite(value):
            raise InvalidStoredMeasurementError(
                f"stored InBody measurement {row.row_id} has a non-finite {metric.value}: {value!r}"
            )
        values.append(round_tenth(value))
    local_date, local_time = parsed.date(), parsed.time()
    # The UTC instant only breaks ties between rows with the same stored date and clock time; a stored
    # time without an offset gets "" (no zone is guessed for it). Fixed width, so it sorts as text.
    instant = parsed.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f") if parsed.tzinfo is not None else ""
    key = (local_date, local_time, instant, row.row_id)
    return key, TrendMeasurement(row.measured_at, local_date, local_time, tuple(values))


def _tenth(value: Decimal) -> Decimal:
    result = value.quantize(TENTH, rounding=ROUND_HALF_EVEN)
    return result.copy_abs() if result == 0 else result


def _difference(earlier: Decimal | None, later: Decimal | None) -> Decimal | None:
    if earlier is None or later is None:
        return None
    return _tenth(later - earlier)


def _overall(metric: TrendMetric, points: dict[date, Decimal]) -> OverallChange:
    if not points:
        return OverallChange(metric, None, None, None, None, None)
    first, last = min(points), max(points)
    if first == last:
        return OverallChange(metric, first, last, 0, None, None)
    days = (last - first).days
    change = _tenth(points[last] - points[first])
    per_28_days = _tenth(change * PER_DAYS / days) if days >= PER_DAYS else None
    return OverallChange(metric, first, last, days, change, per_28_days)


def _goal(points: dict[date, Decimal], goals: TrainingGoals) -> SkeletalMuscleGoal:
    latest_date = max(points) if points else None
    latest = points[latest_date] if latest_date is not None else None
    return SkeletalMuscleGoal(
        latest=latest,
        latest_date=latest_date,
        milestone=_progress(round_tenth(goals.skeletal_muscle_mass_milestone_kg), latest),
        long_term=_progress(round_tenth(goals.skeletal_muscle_mass_long_term_kg), latest),
    )


def _progress(target: Decimal, latest: Decimal | None) -> GoalProgress:
    if latest is None:
        return GoalProgress(target, None, None)
    if latest >= target:
        return GoalProgress(target, None, True)
    return GoalProgress(target, _tenth(target - latest), False)
