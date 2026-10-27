"""Aerobic Guide v1: weekly aerobic minutes, the run-length notice and the cut plateau check.

Pure and deterministic: no I/O, no clock. Everything here is display only; it never changes the
training plan, the progression or the nutrition targets. Evidence IDs come from
docs/evidence/training-nutrition-evidence.md; ``design`` marks a number the evidence does not give.

- Missing is not zero: an activity without stored intensity minutes makes the total a lower bound,
  and its duration is shown apart, never split into moderate and vigorous. No counted activity is
  "none stored", never "0 min". A plateau needs at least two InBody intervals; fewer is
  "insufficient", never "no plateau" (PLAT-02).
- The run-length notice is an observational association (RUNPROG-03), not a warning; there is no
  weekly 10 % rule (RUNPROG-01) and no ACWR (RUNPROG-04).
- The plateau options are unranked (PLAT-06); their order is a fixed display order.
- No measured kg in any result (Training Goal Mode D1): rates, dates, run distances and counts only.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_HALF_EVEN, Decimal

from muscle50.domain.activity import ActivityType, NormalizedActivity
from muscle50.domain.analytics import activity_local_date
from muscle50.domain.body_composition_trend import TrendMetric
from muscle50.domain.training_goal import GoalMode, TrainingGoal

type Points = dict[TrendMetric, dict[date, Decimal]]

# Design (no evidence number): aerobic minutes over D-7..D-1, the window of the weekly sets.
AEROBIC_WINDOW_DAYS = 7
# Design on the EXL-03 / FATEX-01 application memos ("running + swimming"): only these types count.
# Strength is counted apart by the guideline; ``other`` is an unknown type and is never guessed.
AEROBIC_TYPES = (ActivityType.RUNNING, ActivityType.SWIMMING)
# EXL-03: the guideline minimum, >= 150 min/week moderate (or 75 vigorous).
GUIDELINE_MINIMUM_MINUTES = 150
# FATEX-02: the end of the studied dose range (55-300 min/week), shown as a reference mark.
STUDIED_RANGE_END_MINUTES = 300
# Design: runs dated D-7..D are checked (a run from the last days is "recent").
RUN_CHECK_WINDOW_DAYS = 7
# RUNPROG-03: one run more than 10 % longer than the longest run in the previous 30 days.
RUN_PREVIOUS_DAYS = 30
RUN_LONGER_THRESHOLD_PERCENT = 10
# The 10 % test as exact integers: distance * 10 > longest * 11 (no binary 1.1).
_RUN_RATIO_NUMERATOR, _RUN_RATIO_DENOMINATOR = 11, 10
# Days of activity history the aerobic guide reads before D (the oldest baseline of the oldest run).
AEROBIC_HISTORY_DAYS = RUN_CHECK_WINDOW_DAYS + RUN_PREVIOUS_DAYS
# PLAT-02: one InBody or one interval never calls a plateau; at least two intervals are needed.
PLATEAU_MIN_INTERVALS = 2
# Design, as goal mode: an interval pairs a weight with the latest weight at least 7 days before it.
PLATEAU_MIN_INTERVAL_DAYS = 7
# PLAT-02: body weight moves about 0.35 % within a week.
WITHIN_WEEK_WEIGHT_NOISE_PERCENT = Decimal("0.35")
# Design (docs/goals.md calorie step) within PRO-04's deficit limit.
EAT_LESS_STEP_KCAL = (100, 150)
# PLAT-05: one maintenance week.
MAINTENANCE_WEEKS = 1

AEROBIC_EVIDENCE = ("EXL-03", "FATEX-02", "design")
RUN_LENGTH_EVIDENCE = ("RUNPROG-03",)
PLATEAU_EVIDENCE = ("design", "PLAT-01", "PLAT-02")
NOISE_EVIDENCE = ("PLAT-02",)
CHOICE_EVIDENCE = ("PLAT-06", "FATEX-07")

_TENTH = Decimal("0.1")
_WHOLE = Decimal(1)


@dataclass(frozen=True)
class ActivityAerobicMinutes:
    source_activity_id: str
    local_date: date
    activity_type: str
    moderate_minutes: float | None
    vigorous_minutes: float | None
    duration_minutes: int | None
    """Moving time, else elapsed time, in whole minutes (HALF_EVEN); None without either."""


@dataclass(frozen=True)
class AerobicMinutes:
    from_date: date
    to_date: date
    activity_types: tuple[str, ...]
    moderate_minutes: float | None
    """Sum of the stored moderate minutes; None when no counted activity stored any."""
    vigorous_minutes: float | None
    total_minutes: float | None
    """Sum of the stored values of both metrics (a lower bound when ``status`` says so)."""
    status: str
    """``known``, ``lower_bound`` (some metric missing), ``unknown`` (none stored) or ``none_stored``."""
    activities: tuple[ActivityAerobicMinutes, ...]
    without_intensity_count: int
    """Activities with neither intensity metric: not counted, their duration is shown apart."""
    without_intensity_duration_minutes: int | None
    without_duration_count: int
    """Of those, the activities without a duration either."""
    partial_intensity_count: int
    """Activities with only one of the two metrics stored (the stored one is counted)."""
    evidence: tuple[str, ...] = AEROBIC_EVIDENCE


@dataclass(frozen=True)
class RunLengthCheck:
    source_activity_id: str
    local_date: date
    distance_meters: float | None
    longest_previous_meters: float | None
    longest_previous_activity_id: str | None
    longest_previous_date: date | None
    previous_without_distance: int
    """Earlier runs in the 30 days without a distance: the longest may be longer than shown."""
    increase_percent: Decimal | None
    """Against the longest previous run, at 0.1 (HALF_EVEN); negative when shorter."""
    status: str
    """``longer_than_threshold``, ``within``, ``no_previous_run`` or ``no_distance``."""
    baseline_lower_bound: bool


@dataclass(frozen=True)
class RunLengthReport:
    from_date: date
    to_date: date
    runs: tuple[RunLengthCheck, ...]
    previous_days: int = RUN_PREVIOUS_DAYS
    threshold_percent: int = RUN_LONGER_THRESHOLD_PERCENT
    evidence: tuple[str, ...] = RUN_LENGTH_EVIDENCE


@dataclass(frozen=True)
class PlateauInterval:
    from_date: date
    to_date: date
    days: int
    percent_per_week: Decimal
    """Unrounded; negative is a loss (the goal-mode weight rate formula)."""


@dataclass(frozen=True)
class PlateauOption:
    code: str
    evidence: tuple[str, ...]


@dataclass(frozen=True)
class PlateauCheck:
    status: str
    """``met``, ``not_met``, ``insufficient_measurements``, ``unknown`` or ``not_set``."""
    weeks: int | None
    below_loss_percent: Decimal | None
    """The user's --weekly-loss MIN; a loss below it in every interval is a plateau."""
    intervals: tuple[PlateauInterval, ...]
    """Newest first."""
    span_days: int | None
    latest_measurement_date: date | None
    days_since_latest_measurement: int | None
    reason: str | None
    options: tuple[PlateauOption, ...]
    """Only when ``met``; a fixed display order, not a ranking (PLAT-06)."""
    weights_used: int = 0
    evidence: tuple[str, ...] = PLATEAU_EVIDENCE


# --- weekly aerobic minutes --------------------------------------------------------------------


def weekly_aerobic_minutes(as_of: date, activities: Sequence[NormalizedActivity]) -> AerobicMinutes:
    """Stored Garmin intensity minutes of runs and swims dated D-7..D-1 (vigorous not doubled)."""
    start, end = as_of - timedelta(days=AEROBIC_WINDOW_DAYS), as_of - timedelta(days=1)
    items: list[tuple[ActivityAerobicMinutes, float | None]] = []
    for activity in activities:
        day = activity_local_date(activity)
        if day is None or not start <= day <= end or activity.canonical_type not in AEROBIC_TYPES:
            continue
        seconds = _duration_seconds(activity)
        items.append(
            (
                ActivityAerobicMinutes(
                    source_activity_id=activity.source_activity_id,
                    local_date=day,
                    activity_type=activity.canonical_type.value,
                    moderate_minutes=_metric(activity, "moderate_intensity_minutes"),
                    vigorous_minutes=_metric(activity, "vigorous_intensity_minutes"),
                    duration_minutes=_whole_minutes(seconds) if seconds is not None else None,
                ),
                seconds,
            )
        )
    items.sort(key=lambda item: (item[0].local_date, item[0].source_activity_id))
    listed = tuple(item for item, _seconds in items)
    types = tuple(kind.value for kind in AEROBIC_TYPES)
    if not listed:
        return AerobicMinutes(start, end, types, None, None, None, "none_stored", (), 0, None, 0, 0)
    without = [
        (item, seconds) for item, seconds in items if item.moderate_minutes is None and item.vigorous_minutes is None
    ]
    partial = sum(1 for item in listed if (item.moderate_minutes is None) != (item.vigorous_minutes is None))
    durations = [seconds for _item, seconds in without if seconds is not None]
    without_duration = len(without) - len(durations)
    without_minutes = _whole_minutes(math.fsum(durations)) if durations else None
    if len(without) == len(listed):
        return AerobicMinutes(
            start, end, types, None, None, None, "unknown", listed, len(without), without_minutes, without_duration, 0
        )
    moderate = _stored_sum(item.moderate_minutes for item in listed)
    vigorous = _stored_sum(item.vigorous_minutes for item in listed)
    status = "lower_bound" if without or partial else "known"
    return AerobicMinutes(
        start,
        end,
        types,
        moderate,
        vigorous,
        math.fsum(value for value in (moderate, vigorous) if value is not None),
        status,
        listed,
        len(without),
        without_minutes,
        without_duration,
        partial,
    )


def _stored_sum(values: Iterable[float | None]) -> float | None:
    """The sum of the stored values; None when no activity stored this metric (unknown, never 0)."""
    stored = [value for value in values if value is not None]
    return math.fsum(stored) if stored else None


def _metric(activity: NormalizedActivity, key: str) -> float | None:
    """A stored finite number; an absent or non-numeric metric is unknown (a stored 0 is a real 0)."""
    for metric in activity.metrics:
        if metric.key != key:
            continue
        value = metric.value
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            return None
        return float(value)
    return None


def _duration_seconds(activity: NormalizedActivity) -> float | None:
    for value in (activity.moving_seconds, activity.elapsed_seconds):
        if value is not None and math.isfinite(value) and value >= 0:
            return value
    return None


def _whole_minutes(seconds: float) -> int:
    return int((Decimal(repr(seconds)) / Decimal(60)).quantize(_WHOLE, rounding=ROUND_HALF_EVEN))


# --- run-length notice (RUNPROG-03) ------------------------------------------------------------


def run_length_checks(as_of: date, activities: Sequence[NormalizedActivity]) -> RunLengthReport:
    """Each run dated D-7..D against the longest run dated in the 30 days before its own date."""
    start = as_of - timedelta(days=RUN_CHECK_WINDOW_DAYS)
    runs = sorted(
        (
            (day, activity)
            for activity in activities
            if activity.canonical_type is ActivityType.RUNNING and (day := activity_local_date(activity)) is not None
        ),
        key=lambda item: (item[0], item[1].started_at_local or "", item[1].source_activity_id),
    )
    checks = tuple(_check_run(day, run, runs) for day, run in runs if start <= day <= as_of)
    return RunLengthReport(start, as_of, checks)


def _check_run(day: date, run: NormalizedActivity, runs: Sequence[tuple[date, NormalizedActivity]]) -> RunLengthCheck:
    # Design: only earlier dates are the baseline; other runs on the same date are not compared.
    earliest = day - timedelta(days=RUN_PREVIOUS_DAYS)
    previous = [(other_day, other) for other_day, other in runs if earliest <= other_day < day]
    measured = [(other_day, other) for other_day, other in previous if _distance(other) is not None]
    without = len(previous) - len(measured)
    distance = _distance(run)

    def result(status: str, longest: tuple[date, NormalizedActivity] | None = None) -> RunLengthCheck:
        increase: Decimal | None = None
        if longest is not None and distance is not None:
            base = Decimal(repr(_distance(longest[1])))
            increase = ((Decimal(repr(distance)) / base - 1) * 100).quantize(_TENTH, rounding=ROUND_HALF_EVEN)
        return RunLengthCheck(
            source_activity_id=run.source_activity_id,
            local_date=day,
            distance_meters=distance,
            longest_previous_meters=_distance(longest[1]) if longest is not None else None,
            longest_previous_activity_id=longest[1].source_activity_id if longest is not None else None,
            longest_previous_date=longest[0] if longest is not None else None,
            previous_without_distance=without,
            increase_percent=increase,
            status=status,
            baseline_lower_bound=longest is not None and without > 0,
        )

    if distance is None:
        return result("no_distance")
    if not measured:
        return result("no_previous_run")
    # Ties: the most recent of the longest runs.
    longest = max(measured, key=lambda item: (_distance(item[1]) or 0.0, item[0], item[1].source_activity_id))
    longest_meters = _distance(longest[1])
    assert longest_meters is not None
    longer = Decimal(repr(distance)) * _RUN_RATIO_DENOMINATOR > Decimal(repr(longest_meters)) * _RUN_RATIO_NUMERATOR
    return result("longer_than_threshold" if longer else "within", longest)


def _distance(activity: NormalizedActivity) -> float | None:
    """A stored positive finite distance; none, zero or non-finite is "no distance" (never judged)."""
    value = activity.distance_meters
    if value is None or not math.isfinite(value) or value <= 0:
        return None
    return value


# --- plateau check (cut only) ------------------------------------------------------------------


def plateau_check(
    goal: TrainingGoal, points: Points | None, as_of: date, unavailable: str | None
) -> PlateauCheck | None:
    """Cut only. ``met`` when every InBody interval over the last N weeks lost less than the MIN.

    Walking back from the latest weight, each weight is paired with the latest weight at least 7
    days before it (the goal-mode ``weight_change`` pairing, so the newest interval is the same).
    The walk stops once the intervals span N weeks and there are at least two of them.
    """
    if goal.mode is not GoalMode.CUT:
        return None
    weeks, rate = goal.plateau_weeks, goal.weekly_loss_percent
    if weeks is None or rate is None:
        return PlateauCheck(
            "not_set",
            None,
            None,
            (),
            None,
            None,
            None,
            "goal set --plateau-weeks N was not given (there is no evidence-based plateau definition)",
            (),
        )
    below = rate.minimum
    if points is None:
        return PlateauCheck("unknown", weeks, below, (), None, None, None, unavailable or "InBody data unavailable", ())
    weights = points[TrendMetric.WEIGHT_KG]
    latest = max(weights) if weights else None
    since = (as_of - latest).days if latest is not None else None
    intervals: list[PlateauInterval] = []
    current = latest
    while current is not None:
        earlier = [day for day in weights if day <= current - timedelta(days=PLATEAU_MIN_INTERVAL_DAYS)]
        if not earlier:
            break
        previous = max(earlier)
        days = (current - previous).days
        change = (weights[current] - weights[previous]) / weights[previous] * Decimal(7) / Decimal(days) * Decimal(100)
        intervals.append(PlateauInterval(previous, current, days, change))
        if _enough(intervals, weeks):
            break
        current = previous
    span = (intervals[0].to_date - intervals[-1].from_date).days if intervals else None
    used = len(intervals) + 1 if intervals else (1 if latest is not None else 0)
    if not _enough(intervals, weeks):
        reason = (
            f"{used} {_plural(used, 'weight', 'weights')} cover {len(intervals)} "
            f"{_plural(len(intervals), 'interval', 'intervals')}; the check needs {weeks} weeks and at least "
            f"{PLATEAU_MIN_INTERVALS} intervals"
        )
        return PlateauCheck(
            "insufficient_measurements", weeks, below, tuple(intervals), span, latest, since, reason, (), used
        )
    met = all(-interval.percent_per_week < below for interval in intervals)
    return PlateauCheck(
        "met" if met else "not_met",
        weeks,
        below,
        tuple(intervals),
        span,
        latest,
        since,
        None,
        plateau_options() if met else (),
        used,
    )


def _enough(intervals: Sequence[PlateauInterval], weeks: int) -> bool:
    if len(intervals) < PLATEAU_MIN_INTERVALS:
        return False
    return (intervals[0].to_date - intervals[-1].from_date).days >= weeks * 7


def plateau_options() -> tuple[PlateauOption, ...]:
    """The four options in a fixed display order; no option is ranked above another (PLAT-06)."""
    return (
        PlateauOption("check_meal_logging", ("PLAT-04",)),
        PlateauOption("eat_less", ("design", "PRO-04")),
        PlateauOption("keep_intake_add_activity", ("FATEX-05", "FATEX-04", "RUNPROG-03", "CONC-04")),
        PlateauOption("maintenance_week", ("PLAT-05",)),
    )


def aerobic_history_start(as_of: date) -> date:
    """The first date the aerobic guide reads: the 30-day baseline of a run dated D-7."""
    return as_of - timedelta(days=AEROBIC_HISTORY_DAYS)


def _plural(count: int, one: str, many: str) -> str:
    return one if count == 1 else many
