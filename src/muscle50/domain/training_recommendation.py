"""Training Recommendation v1: deterministic strength plan and next-swim goal for one date.

This is the rule layer only. It reads canonical activities and recovery rows that were
already loaded (read-only), never writes, never calls Garmin, and never uses an LLM. A later
presentation/LLM layer may rephrase this output but must not change its decisions.

Date semantics for a requested date D (no clock, no zoneinfo; Garmin local dates):

- Strength history is the 28 days before D. A strength activity already stored on D is
  excluded (and reported) so the recommendation describes the state before that session.
- Swims dated D or D-1 are same-day/previous-day overlap inputs for strength. The next-swim
  goal uses swims up to and including D (they happened before the next swim).
- Recovery: see ``recovery_assessment`` for which row each field comes from.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, timedelta

from muscle50.domain.activity import ActivityType, NormalizedActivity
from muscle50.domain.analytics import activity_local_date
from muscle50.domain.exercise_taxonomy import MuscleGroup
from muscle50.domain.recovery import DailyRecovery
from muscle50.domain.recovery_assessment import RecoveryAssessment, assess_recovery
from muscle50.domain.strength_recommendation import (
    HISTORY_DAYS,
    REGION_MUSCLES,
    SWIM_OVERLAP_MUSCLES,
    Region,
    StrengthFocus,
    StrengthRecommendation,
    SwimOverlap,
    build_strength_recommendation,
    primary_muscle_sets_on,
)
from muscle50.domain.swim_recommendation import (
    RETURN_AFTER_GAP_DAYS,
    StrengthContext,
    SwimRecommendation,
    analyze_swims,
    build_swim_recommendation,
)
from muscle50.domain.training_goals import DEFAULT_TRAINING_GOALS, TrainingGoals

RECOMMENDATION_VERSION = 1
# Days of history loaded before the requested date (the requested date is loaded too).
LOOKBACK_DAYS = HISTORY_DAYS
# A gap this long between the newest stored activity and the requested date is reported.
COVERAGE_GAP_DAYS = 2


@dataclass(frozen=True)
class RecommendationNotice:
    code: str
    message: str
    source_activity_id: str | None = None
    local_date: date | None = None


@dataclass(frozen=True)
class DataFreshness:
    """What the stored data covers relative to the requested date.

    The schema records what was stored, not which days were synced, so "no stored activity"
    is never a confirmed rest day.
    """

    latest_activity_date: date | None
    latest_strength_date: date | None
    latest_swim_date: date | None
    latest_recovery_date: date | None
    requested_date_recovery_row: bool
    requested_date_sleep_recorded: bool
    sync_coverage_recorded: bool
    statement: str


@dataclass(frozen=True)
class TrainingRecommendation:
    recommendation_version: int
    as_of: date
    history_start: date
    goals: TrainingGoals
    recovery: RecoveryAssessment
    strength: StrengthRecommendation
    swimming: SwimRecommendation
    excluded_same_day_strength_ids: tuple[str, ...]
    latest_activity_date: date | None
    latest_recovery_date: date | None
    data_freshness: DataFreshness
    notices: tuple[RecommendationNotice, ...]


def history_start(as_of: date) -> date:
    return as_of - timedelta(days=LOOKBACK_DAYS)


def build_training_recommendation(
    as_of: date,
    activities: Sequence[NormalizedActivity],
    recoveries: Sequence[DailyRecovery],
    *,
    goals: TrainingGoals = DEFAULT_TRAINING_GOALS,
    avoid_muscles: Iterable[MuscleGroup] = (),
    undated_source_activity_ids: Sequence[str] = (),
    requested_focus: StrengthFocus | None = None,
) -> TrainingRecommendation:
    start = history_start(as_of)
    previous_day = as_of - timedelta(days=1)
    dated = [
        (day, activity)
        for activity in activities
        if (day := activity_local_date(activity)) is not None and start <= day <= as_of
    ]
    same_day_strength = tuple(
        sorted(
            activity.source_activity_id
            for day, activity in dated
            if day == as_of and activity.canonical_type is ActivityType.STRENGTH
        )
    )
    window_activities = [activity for _day, activity in dated]

    recovery = assess_recovery(as_of, recoveries)
    swim_sessions = analyze_swims(as_of, window_activities)
    overlaps = tuple(
        SwimOverlap(
            source_activity_id=item.source_activity_id,
            local_date=item.local_date,
            same_day=item.local_date == as_of,
            distance_meters=item.distance_meters,
            high_intensity=item.high_intensity,
            butterfly_meters=item.butterfly_meters,
            reasons=item.high_intensity_reasons,
        )
        for item in swim_sessions
        if item.local_date in (previous_day, as_of)
    )
    strength = build_strength_recommendation(
        as_of, window_activities, recovery, overlaps, goals, avoid_muscles, requested_focus
    )

    previous_sets = primary_muscle_sets_on(previous_day, window_activities)
    context = StrengthContext(
        upper_body_sets_previous_day=sum(previous_sets[muscle] for muscle in SWIM_OVERLAP_MUSCLES),
        leg_sets_previous_day=sum(previous_sets[muscle] for muscle in REGION_MUSCLES[Region.LEGS]),
        planned_focus=strength.focus,
    )
    swimming = build_swim_recommendation(as_of, swim_sessions, recovery.level, context, goals)

    latest_activity = max((day for day, _activity in dated), default=None)
    recovery_dates = sorted(
        day for item in recoveries if start <= (day := date.fromisoformat(item.calendar_date)) <= as_of
    )
    latest_recovery = recovery_dates[-1] if recovery_dates else None
    today_row = next((item for item in recoveries if item.calendar_date == as_of.isoformat()), None)
    freshness = DataFreshness(
        latest_activity_date=latest_activity,
        latest_strength_date=_latest(dated, ActivityType.STRENGTH),
        latest_swim_date=_latest(dated, ActivityType.SWIMMING),
        latest_recovery_date=latest_recovery,
        requested_date_recovery_row=today_row is not None,
        requested_date_sleep_recorded=today_row is not None and today_row.sleep_seconds is not None,
        sync_coverage_recorded=False,
        statement=(
            "sync completeness is not recorded: a day without a stored activity is 'no recorded activity', "
            "not a confirmed rest day, and a partial recovery row may still be filled by a later sync"
        ),
    )
    notices = _notices(
        as_of,
        same_day_strength,
        freshness,
        recovery,
        strength,
        swimming,
        undated_source_activity_ids,
    )
    return TrainingRecommendation(
        recommendation_version=RECOMMENDATION_VERSION,
        as_of=as_of,
        history_start=start,
        goals=goals,
        recovery=recovery,
        strength=strength,
        swimming=swimming,
        excluded_same_day_strength_ids=same_day_strength,
        latest_activity_date=latest_activity,
        latest_recovery_date=latest_recovery,
        data_freshness=freshness,
        notices=notices,
    )


def _latest(dated: Sequence[tuple[date, NormalizedActivity]], activity_type: ActivityType) -> date | None:
    return max((day for day, activity in dated if activity.canonical_type is activity_type), default=None)


def _notices(
    as_of: date,
    same_day_strength: Sequence[str],
    freshness: DataFreshness,
    recovery: RecoveryAssessment,
    strength: StrengthRecommendation,
    swimming: SwimRecommendation,
    undated_source_activity_ids: Sequence[str],
) -> tuple[RecommendationNotice, ...]:
    latest_activity = freshness.latest_activity_date
    latest_recovery = freshness.latest_recovery_date
    notices: list[RecommendationNotice] = []
    for source_id in same_day_strength:
        notices.append(
            RecommendationNotice(
                "same_day_strength_excluded",
                "a strength activity is already stored on this date; it is excluded from history so the "
                "recommendation reflects the state before it",
                source_id,
                as_of,
            )
        )
    if latest_activity is None:
        notices.append(
            RecommendationNotice(
                "no_recent_activity",
                f"no Garmin activity stored in the {LOOKBACK_DAYS} days before this date; "
                "this may be missing sync rather than rest",
            )
        )
    elif (as_of - latest_activity).days >= COVERAGE_GAP_DAYS:
        notices.append(
            RecommendationNotice(
                "activity_coverage_gap",
                f"newest stored activity is {latest_activity.isoformat()}; the days after it may be unsynced "
                "rather than rest (sync coverage is not recorded)",
            )
        )
    lookback = f"; {recovery.lookback.explanation}" if recovery.lookback is not None else ""
    if not recovery.requested_date_row_available:
        latest = latest_recovery.isoformat() if latest_recovery else "none in window"
        notices.append(
            RecommendationNotice(
                "recovery_row_missing",
                f"no Garmin recovery row for {as_of.isoformat()} (latest: {latest}); it may not be synced yet. "
                f"Missing is not treated as poor recovery{lookback}",
            )
        )
    else:
        if recovery.missing_fields:
            notices.append(
                RecommendationNotice(
                    "recovery_fields_missing",
                    f"recovery fields missing (not treated as poor): {', '.join(recovery.missing_fields)}",
                )
            )
        if not freshness.requested_date_sleep_recorded:
            readiness = next(
                (item.value for item in recovery.observations if item.field == "training_readiness_level"), None
            )
            readiness_note = (
                f"; its readiness ({readiness}) was stored without a sleep measurement" if readiness is not None else ""
            )
            notices.append(
                RecommendationNotice(
                    "recovery_row_partial",
                    f"the {as_of.isoformat()} recovery row has no sleep; the stored data cannot tell whether the "
                    f"night was not recorded or not synced yet{readiness_note}{lookback}",
                    local_date=as_of,
                )
            )
    if latest_recovery is not None and (as_of - latest_recovery).days >= COVERAGE_GAP_DAYS:
        notices.append(
            RecommendationNotice(
                "recovery_coverage_gap",
                f"newest stored recovery row is {latest_recovery.isoformat()}; recent recovery may be unsynced",
            )
        )
    days_since_swim = swimming.baseline.days_since_last_swim
    if days_since_swim is None or days_since_swim >= RETURN_AFTER_GAP_DAYS:
        since = (
            f"since {freshness.latest_swim_date.isoformat()} ({days_since_swim} days)"
            if freshness.latest_swim_date is not None and days_since_swim is not None
            else f"in the {LOOKBACK_DAYS} days before this date"
        )
        notices.append(
            RecommendationNotice(
                "swim_gap",
                f"no swim stored {since}; a real break and unsynced swims cannot be distinguished",
            )
        )
    for no_rule in strength.no_rule_notices:
        hint = (
            f"its Garmin category suggests {no_rule.category_hint_muscle} "
            f"({no_rule.category_hint_region or 'no region'})"
            if no_rule.category_hint_muscle
            else "its region is unknown (no rule for its Garmin category either)"
        )
        notices.append(
            RecommendationNotice(
                "strength_no_rule_exercise",
                f"{no_rule.label}: {no_rule.set_count} ACTIVE sets (set {_sequences(no_rule.set_sequences)}) have no "
                f"taxonomy rule and are not counted for any muscle; {hint}, so that muscle/region may be "
                "underestimated in focus and volume. Not guessed; a rule must be added after review",
                no_rule.source_activity_id,
                no_rule.local_date,
            )
        )
    for item in strength.unknown_notices:
        notices.append(
            RecommendationNotice(
                "strength_unknown_exercise",
                f"{item.unknown_set_count} ACTIVE sets are UNKNOWN in Garmin (set {_sequences(item.set_sequences)}); "
                f"they are not guessed and are excluded from muscle counts and progression. To fix: {item.action}",
                item.source_activity_id,
                item.local_date,
            )
        )
    for text in swimming.excluded_baselines:
        notices.append(RecommendationNotice("swim_anomaly_excluded", text))
    for session in swimming.sessions:
        if session.distance_basis == "summary_only":
            notices.append(
                RecommendationNotice(
                    "swim_detail_missing",
                    "no lap detail; only the unverified Garmin summary distance is available",
                    session.source_activity_id,
                    session.local_date,
                )
            )
    for source_id in sorted(undated_source_activity_ids):
        notices.append(
            RecommendationNotice("undated_activity", "activity has no local start time; not used", source_id)
        )
    return tuple(notices)


def _sequences(values: Sequence[int]) -> str:
    return ", ".join(str(value) for value in values)
