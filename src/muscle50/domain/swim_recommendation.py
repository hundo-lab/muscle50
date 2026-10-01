"""Deterministic next-swim goal from recent swim history.

Rules (details and thresholds in docs/training-recommendation.md):

- Distances come from the Analytics Engine plausibility rules: a lap the snapshot marks
  implausible is never used, and a Garmin summary distance that includes such laps (for
  example 2026-09-17, 3025 m) is never a baseline. Stored data is never corrected.
- A "continuous swim" is a run of swimming lengths inside one plausible lap that no idle
  length of at least ``CONTINUITY_BREAK_IDLE_SECONDS`` interrupts. Laps without lengths
  count as one unverified segment. Short wall rests that Garmin did not record as idle
  lengths cannot be detected.
- Pace baselines use only freestyle-only segments whose every length has a plausible
  speed and a duration, because the target is a 1500 m swim time.
- High intensity uses only stored signals: HR zone 5 time, anaerobic training effect, and
  butterfly distance. Stored lap ``intensity_type`` is empty and paddle/fin use is not
  recorded, so neither is used.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from enum import StrEnum

from muscle50.domain.activity import ActivityType, NormalizedActivity
from muscle50.domain.analytics import (
    MAX_PLAUSIBLE_SWIM_SPEED_MPS,
    SwimSessionSummary,
    activity_local_date,
    build_training_snapshot,
)
from muscle50.domain.recovery_assessment import AdjustmentLevel
from muscle50.domain.swimming import SwimLap, derive_lap_metrics, derive_length_metrics
from muscle50.domain.training_goals import TrainingGoals

SWIM_HISTORY_DAYS = 28
CONTINUITY_BREAK_IDLE_SECONDS = 10.0
# Account-calibrated (2026-07..09 swims: anaerobic TE 0.6-2.6, zone 5 0-551 s).
HIGH_INTENSITY_ZONE5_SECONDS = 120.0
HIGH_INTENSITY_ANAEROBIC_TE = 2.5
MIN_PACE_SEGMENT_METERS = 200.0
# A swim counts as a distance effort when its longest continuous segment reaches this
# fraction of the progression anchor.
DISTANCE_EFFORT_FRACTION = 0.6
DISTANCE_EFFORT_LOOKBACK_DAYS = 14
DISTANCE_PROGRESSION_STALE_DAYS = 7
DISTANCE_STEP_METERS = 100.0
EASY_CONTINUOUS_FRACTION = 0.8
RECOVERY_SWIM_METERS = 600.0
INTERVAL_REPEAT_METERS = 100.0
INTERVAL_REPEATS = 8
INTERVAL_PACE_STEP_SECONDS = 4.0
WARM_UP_METERS = 200.0
COOL_DOWN_METERS = 100.0
DEFAULT_POOL_METERS = 50.0
# Strength the previous day that makes a hard (interval) swim a poor idea.
HEAVY_UPPER_BODY_SETS = 8
HEAVY_LEG_SETS = 8


class SwimSessionType(StrEnum):
    EASY_CONTINUOUS = "easy_continuous"
    DISTANCE_PROGRESSION = "distance_progression"
    PACE_INTERVALS = "pace_intervals"
    RECOVERY_TECHNIQUE = "recovery_technique"


@dataclass(frozen=True)
class SwimSegment:
    source_activity_id: str
    local_date: date
    lap_sequence: int
    distance_meters: float
    length_seconds: float | None
    strokes: tuple[str, ...]
    verified_from_lengths: bool
    timing_plausible: bool
    """Every length has a duration and a plausible speed; required for any baseline."""

    @property
    def freestyle_only(self) -> bool:
        return self.strokes == ("freestyle",)

    @property
    def pace_seconds_per_100m(self) -> float | None:
        if self.length_seconds is None or self.distance_meters <= 0:
            return None
        return self.length_seconds * 100.0 / self.distance_meters


@dataclass(frozen=True)
class SwimSessionAnalysis:
    source_activity_id: str
    local_date: date
    pool_length_meters: float | None
    summary_distance_meters: float | None
    plausible_detail_distance_meters: float | None
    distance_meters: float | None
    distance_basis: str
    """``plausible_detail`` (lap detail minus implausible laps) or ``summary_only`` (no detail)."""
    summary_includes_implausible_laps: bool
    excluded_lap_sequences: tuple[int, ...]
    longest_segment: SwimSegment | None
    """Longest continuous segment with plausible length timing (the only kind used as a baseline)."""
    longest_implausible_segment: SwimSegment | None
    """A longer segment that was ignored because its length timing is implausible or missing."""
    best_pace_segment: SwimSegment | None
    butterfly_meters: float
    hr_zone_5_seconds: float | None
    anaerobic_training_effect: float | None
    aerobic_training_effect: float | None
    high_intensity: bool
    high_intensity_reasons: tuple[str, ...]


@dataclass(frozen=True)
class SwimBaseline:
    configured_continuous_meters: float
    recent_longest_segment: SwimSegment | None
    recent_best_pace_segment: SwimSegment | None
    progression_anchor_meters: float
    target_continuous_meters: float
    target_pace_seconds_per_100m: tuple[float, float]
    """Fastest and slowest pace that meet the configured 1500 m time range."""


@dataclass(frozen=True)
class SwimGoal:
    session_type: str
    total_meters: float
    main_set: str
    target_continuous_meters: float | None
    target_pace_seconds_per_100m: tuple[float, float] | None
    reasons: tuple[str, ...]
    cautions: tuple[str, ...]


@dataclass(frozen=True)
class SwimRecommendation:
    goal: SwimGoal
    baseline: SwimBaseline
    sessions_last_7_days: int
    goal_sessions_per_week: int
    sessions: tuple[SwimSessionAnalysis, ...]
    excluded_baselines: tuple[str, ...]


# Strength focuses that load the muscles swimming loads (a user-requested shoulders focus
# is one of them even though it is not an automatic region).
_UPPER_BODY_FOCUSES = frozenset({"push", "pull", "shoulders"})


@dataclass(frozen=True)
class StrengthContext:
    """Strength load around the next swim (previous day's sets and today's planned focus)."""

    upper_body_sets_previous_day: int
    leg_sets_previous_day: int
    planned_focus: str | None


def pace_text(seconds_per_100m: float) -> str:
    whole = int(round(seconds_per_100m))
    return f"{whole // 60}:{whole % 60:02d}/100 m"


def analyze_swims(as_of: date, activities: Sequence[NormalizedActivity]) -> tuple[SwimSessionAnalysis, ...]:
    """Swims dated in the 28 days ending on ``as_of`` (inclusive), oldest first."""
    swims = [
        activity
        for activity in activities
        if activity.canonical_type is ActivityType.SWIMMING and activity_local_date(activity) is not None
    ]
    # Reuse the Analytics Engine's implausible-lap and summary-contamination rules.
    snapshot = build_training_snapshot(as_of, SWIM_HISTORY_DAYS, swims, ())
    by_id = {activity.source_activity_id: activity for activity in swims}
    return tuple(_analyze(session, by_id[session.source_activity_id]) for session in snapshot.swimming.sessions)


def _analyze(session: SwimSessionSummary, activity: NormalizedActivity) -> SwimSessionAnalysis:
    excluded = set(session.implausible_lap_sequences)
    segments: list[SwimSegment] = []
    butterfly = 0.0
    swim = activity.swim_detail
    for lap in swim.laps if swim is not None else ():
        if lap.sequence in excluded:
            continue
        lap_segments, lap_butterfly = _lap_segments(session, lap)
        segments.extend(lap_segments)
        butterfly += lap_butterfly

    metrics = {metric.key: metric.value for metric in activity.metrics}
    zone5 = _number(metrics.get("hr_time_in_zone_5_seconds"))
    anaerobic = _number(metrics.get("anaerobic_training_effect"))
    aerobic = _number(metrics.get("aerobic_training_effect"))
    reasons = []
    high_intensity = False
    if zone5 is not None and zone5 >= HIGH_INTENSITY_ZONE5_SECONDS:
        high_intensity = True
        reasons.append(f"HR zone 5 {zone5:.0f} s >= {HIGH_INTENSITY_ZONE5_SECONDS:g} s")
    if anaerobic is not None and anaerobic >= HIGH_INTENSITY_ANAEROBIC_TE:
        high_intensity = True
        reasons.append(f"anaerobic TE {anaerobic:.1f} >= {HIGH_INTENSITY_ANAEROBIC_TE:g}")
    if butterfly > 0:
        reasons.append(f"butterfly {butterfly:g} m")

    pace_candidates = [
        item
        for item in segments
        if item.freestyle_only and item.timing_plausible and item.distance_meters >= MIN_PACE_SEGMENT_METERS
    ]
    longest = max((item for item in segments if item.timing_plausible), key=_segment_length_key, default=None)
    longest_implausible = max(
        (item for item in segments if not item.timing_plausible), key=_segment_length_key, default=None
    )
    if session.detail_available:
        distance, basis = session.plausible_detail_distance_meters, "plausible_detail"
    else:
        distance, basis = session.summary_distance_meters, "summary_only"
    return SwimSessionAnalysis(
        source_activity_id=session.source_activity_id,
        local_date=session.local_date,
        pool_length_meters=session.pool_length_meters,
        summary_distance_meters=session.summary_distance_meters,
        plausible_detail_distance_meters=session.plausible_detail_distance_meters,
        distance_meters=distance,
        distance_basis=basis,
        summary_includes_implausible_laps=session.summary_distance_includes_implausible_laps,
        excluded_lap_sequences=session.implausible_lap_sequences,
        longest_segment=longest,
        longest_implausible_segment=longest_implausible
        if longest_implausible is not None
        and (longest is None or longest_implausible.distance_meters > longest.distance_meters)
        else None,
        best_pace_segment=min(pace_candidates, key=_segment_pace_key, default=None),
        butterfly_meters=butterfly,
        hr_zone_5_seconds=zone5,
        anaerobic_training_effect=anaerobic,
        aerobic_training_effect=aerobic,
        high_intensity=high_intensity,
        high_intensity_reasons=tuple(reasons),
    )


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return None
    return float(value)


def _segment_length_key(segment: SwimSegment) -> tuple[float, int]:
    return (segment.distance_meters, -segment.lap_sequence)


def _segment_pace_key(segment: SwimSegment) -> tuple[float, float, int]:
    return (segment.pace_seconds_per_100m or math.inf, -segment.distance_meters, segment.lap_sequence)


def _lap_segments(session: SwimSessionSummary, lap: SwimLap) -> tuple[list[SwimSegment], float]:
    lap_distance = derive_lap_metrics(lap).effective_distance_meters
    if not lap.lengths:
        if lap_distance is None or lap_distance <= 0:
            return [], 0.0
        stroke = lap.stroke_type or "unknown"
        segment = SwimSegment(
            session.source_activity_id,
            session.local_date,
            lap.sequence,
            lap_distance,
            lap.duration_seconds,
            (stroke,),
            False,
            False,
        )
        return [segment], lap_distance if stroke == "butterfly" else 0.0

    segments: list[SwimSegment] = []
    butterfly = 0.0
    distance = 0.0
    seconds: float | None = 0.0
    strokes: set[str] = set()
    trusted = True

    def close() -> None:
        if distance > 0:
            segments.append(
                SwimSegment(
                    session.source_activity_id,
                    session.local_date,
                    lap.sequence,
                    distance,
                    seconds,
                    tuple(sorted(strokes)),
                    True,
                    trusted and seconds is not None,
                )
            )

    for length in lap.lengths:
        length_distance = derive_length_metrics(length).effective_distance_meters
        duration = length.duration_seconds
        if length_distance is not None and length_distance > 0:
            stroke = length.stroke_type or lap.stroke_type or "unknown"
            distance += length_distance
            seconds = seconds + duration if seconds is not None and duration is not None and duration > 0 else None
            strokes.add(stroke)
            if stroke == "butterfly":
                butterfly += length_distance
            if duration is None or duration <= 0 or length_distance / duration > MAX_PLAUSIBLE_SWIM_SPEED_MPS:
                trusted = False
        elif (duration or 0.0) >= CONTINUITY_BREAK_IDLE_SECONDS:
            close()
            distance, seconds, strokes, trusted = 0.0, 0.0, set(), True
    close()
    return segments, butterfly


def build_swim_recommendation(
    as_of: date,
    sessions: Sequence[SwimSessionAnalysis],
    recovery_level: AdjustmentLevel,
    strength: StrengthContext,
    goals: TrainingGoals,
) -> SwimRecommendation:
    excluded = tuple(
        f"{item.local_date.isoformat()} {item.source_activity_id}: Garmin summary "
        f"{_meters(item.summary_distance_meters)} includes implausible lap(s) "
        f"{', '.join(str(seq) for seq in item.excluded_lap_sequences)}; not a baseline "
        f"(plausible detail {_meters(item.plausible_detail_distance_meters)})"
        for item in sessions
        if item.excluded_lap_sequences
    )
    longest = max(
        (item.longest_segment for item in sessions if item.longest_segment is not None),
        key=lambda segment: (segment.distance_meters, segment.local_date),
        default=None,
    )
    best_pace = min(
        (item.best_pace_segment for item in sessions if item.best_pace_segment is not None),
        key=lambda segment: (segment.pace_seconds_per_100m or math.inf, -segment.local_date.toordinal()),
        default=None,
    )
    anchor = max(goals.continuous_swim_baseline_meters, longest.distance_meters if longest else 0.0)
    pool = next(
        (item.pool_length_meters for item in reversed(sessions) if item.pool_length_meters),
        DEFAULT_POOL_METERS,
    )
    target_continuous = min(goals.continuous_swim_target_meters, _round_to_pool(anchor + DISTANCE_STEP_METERS, pool))
    target = goals.continuous_swim_target_meters
    pace_range = (
        goals.target_1500m_fastest_seconds * 100.0 / target,
        goals.target_1500m_slowest_seconds * 100.0 / target,
    )
    baseline = SwimBaseline(
        configured_continuous_meters=goals.continuous_swim_baseline_meters,
        recent_longest_segment=longest,
        recent_best_pace_segment=best_pace,
        progression_anchor_meters=anchor,
        target_continuous_meters=target_continuous,
        target_pace_seconds_per_100m=pace_range,
    )
    recent_start = as_of - timedelta(days=6)
    sessions_7 = sum(1 for item in sessions if item.local_date >= recent_start)
    goal = _select_goal(as_of, sessions, recovery_level, strength, baseline, pool, goals)
    return SwimRecommendation(goal, baseline, sessions_7, goals.swim_sessions_per_week, tuple(sessions), excluded)


def _select_goal(
    as_of: date,
    sessions: Sequence[SwimSessionAnalysis],
    recovery_level: AdjustmentLevel,
    strength: StrengthContext,
    baseline: SwimBaseline,
    pool: float,
    goals: TrainingGoals,
) -> SwimGoal:
    reasons: list[str] = []
    cautions: list[str] = []
    last = sessions[-1] if sessions else None
    effort_threshold = DISTANCE_EFFORT_FRACTION * baseline.progression_anchor_meters
    efforts = [
        item
        for item in sessions
        if item.longest_segment is not None and item.longest_segment.distance_meters >= effort_threshold
    ]
    last_effort = efforts[-1] if efforts else None
    anchor_source = (
        f"recent longest continuous {_segment_text(baseline.recent_longest_segment)}"
        if baseline.recent_longest_segment
        else f"no continuous segment in the last {SWIM_HISTORY_DAYS} days"
    )
    reasons.append(
        f"progression anchor {_meters(baseline.progression_anchor_meters)} = max(configured baseline "
        f"{_meters(goals.continuous_swim_baseline_meters)}, {anchor_source})"
    )

    if recovery_level is AdjustmentLevel.REDUCE:
        session_type = SwimSessionType.RECOVERY_TECHNIQUE
        reasons.append("recovery reduce today")
    elif last is not None and last.high_intensity and (as_of - last.local_date).days <= 1:
        session_type = SwimSessionType.RECOVERY_TECHNIQUE
        reasons.append(
            f"last swim {last.local_date.isoformat()} was high intensity ({'; '.join(last.high_intensity_reasons)})"
        )
    elif last_effort is None or (as_of - last_effort.local_date).days > DISTANCE_EFFORT_LOOKBACK_DAYS:
        session_type = SwimSessionType.DISTANCE_PROGRESSION
        reasons.append(
            f"no continuous swim of at least {_meters(effort_threshold)} "
            f"in the last {DISTANCE_EFFORT_LOOKBACK_DAYS} days"
        )
    elif last is not None and last is last_effort:
        if baseline.recent_best_pace_segment is not None:
            session_type = SwimSessionType.PACE_INTERVALS
            reasons.append(
                f"last swim {last.local_date.isoformat()} was a distance effort; alternate with pace work "
                "instead of adding distance every session"
            )
        else:
            session_type = SwimSessionType.EASY_CONTINUOUS
            reasons.append("last swim was a distance effort and no trustworthy freestyle pace exists for intervals")
    elif (as_of - last_effort.local_date).days > DISTANCE_PROGRESSION_STALE_DAYS:
        session_type = SwimSessionType.DISTANCE_PROGRESSION
        reasons.append(f"last distance effort was {last_effort.local_date.isoformat()} (over 7 days ago)")
    else:
        session_type = SwimSessionType.EASY_CONTINUOUS
        reasons.append(f"distance effort on {last_effort.local_date.isoformat()} is recent; keep this one easy")

    if (
        session_type is SwimSessionType.PACE_INTERVALS
        and strength.upper_body_sets_previous_day >= HEAVY_UPPER_BODY_SETS
    ):
        session_type = SwimSessionType.EASY_CONTINUOUS
        reasons.append(
            f"{strength.upper_body_sets_previous_day} shoulder/back/triceps sets yesterday: intervals moved to easy"
        )
    if strength.upper_body_sets_previous_day >= HEAVY_UPPER_BODY_SETS or strength.planned_focus in _UPPER_BODY_FOCUSES:
        cautions.append("shoulders/back/triceps share load with strength: no butterfly or paddles today")
    if strength.planned_focus in _UPPER_BODY_FOCUSES:
        cautions.append(
            f"today's strength focus is {strength.planned_focus}: if both happen today, separate them by several hours"
        )
    if strength.leg_sets_previous_day >= HEAVY_LEG_SETS or strength.planned_focus == "legs":
        cautions.append("legs are loaded by strength: keep kick sets and fins easy")
    # Report ignored segments only when they would have counted as a distance effort.
    ignored = [
        item.longest_implausible_segment
        for item in sessions
        if item.longest_implausible_segment is not None
        and item.longest_implausible_segment.distance_meters > effort_threshold
    ]
    for segment in ignored:
        cautions.append(
            f"ignored as baseline: {_segment_text(segment)} has missing or implausible length timing "
            "(possible unrecorded rests or segmentation error)"
        )

    return _goal(session_type, baseline, pool, reasons, cautions)


def _goal(
    session_type: SwimSessionType,
    baseline: SwimBaseline,
    pool: float,
    reasons: list[str],
    cautions: list[str],
) -> SwimGoal:
    fast, slow = baseline.target_pace_seconds_per_100m
    extra = WARM_UP_METERS + COOL_DOWN_METERS
    if session_type is SwimSessionType.RECOVERY_TECHNIQUE:
        return SwimGoal(
            session_type.value,
            RECOVERY_SWIM_METERS,
            f"{_meters(RECOVERY_SWIM_METERS)} easy: mixed strokes and drills, no butterfly, no paddles",
            None,
            None,
            tuple(reasons),
            tuple(cautions),
        )
    if session_type is SwimSessionType.DISTANCE_PROGRESSION:
        target = baseline.target_continuous_meters
        main = f"{_meters(target)} continuous at an even, comfortable pace (no stops)"
        # Capped at the goal distance: the progression is now the goal time, not more distance.
        if target <= baseline.progression_anchor_meters:
            window = f"{_time(fast * target / 100)}-{_time(slow * target / 100)}"
            main = f"{_meters(target)} continuous, timed: aim for {window}"
        return SwimGoal(session_type.value, target + extra, main, target, None, tuple(reasons), tuple(cautions))
    if session_type is SwimSessionType.PACE_INTERVALS:
        reference = baseline.recent_best_pace_segment
        current = reference.pace_seconds_per_100m if reference else None
        if current is None:
            pace = (fast, slow)
        else:
            pace = (max(fast, current - INTERVAL_PACE_STEP_SECONDS), max(fast, current - 1.0))
            reasons.append(f"current freestyle pace {_segment_text(reference)}")
        repeats = INTERVAL_REPEATS
        main = (
            f"{repeats} x {INTERVAL_REPEAT_METERS:g} m freestyle at {pace_text(pace[0])}-{pace_text(pace[1])}, "
            "20-30 s rest"
        )
        reasons.append(f"1500 m goal range {pace_text(fast)}-{pace_text(slow)}")
        total = repeats * INTERVAL_REPEAT_METERS + extra
        return SwimGoal(session_type.value, total, main, None, pace, tuple(reasons), tuple(cautions))
    distance = _round_to_pool(EASY_CONTINUOUS_FRACTION * baseline.progression_anchor_meters, pool)
    return SwimGoal(
        session_type.value,
        distance + extra,
        f"{_meters(distance)} easy continuous with relaxed technique focus",
        distance,
        None,
        tuple(reasons),
        tuple(cautions),
    )


def _round_to_pool(meters: float, pool: float) -> float:
    step = 2 * pool
    return max(step, round(meters / step) * step)


def _meters(value: float | None) -> str:
    return "-" if value is None else f"{value:g} m"


def _time(seconds: float) -> str:
    whole = int(round(seconds))
    return f"{whole // 60}:{whole % 60:02d}"


def _segment_text(segment: SwimSegment | None) -> str:
    if segment is None:
        return "-"
    pace = segment.pace_seconds_per_100m
    pace_part = f", {pace_text(pace)}" if pace is not None else ""
    return (
        f"{_meters(segment.distance_meters)} ({segment.local_date.isoformat()} {segment.source_activity_id} "
        f"lap {segment.lap_sequence}, {'/'.join(segment.strokes)}{pace_part})"
    )
