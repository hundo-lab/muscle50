"""Deterministic strength recommendation for one requested date.

Rules (details and thresholds in docs/training-recommendation.md):

- Exercise identity is the stored Garmin ``(category, name)`` label, exactly as stored.
  Labels are never renamed or merged; progression compares a label only with itself.
- Only labels from the user's own recent history are recommended, most familiar first.
  UNKNOWN and rule-less labels are never recommended and never guessed.
- Progression is double progression on the label's most recent comparable session: add
  reps at the same load inside the goal rep range, and add load only after at least two
  work sets reached the top of the range. Recovery or performance signals can only hold
  or reduce, never force an increase.
- Every decision carries the evidence it used; missing data is reported, never zeroed.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from enum import StrEnum

from muscle50.domain.activity import ActivityType, NormalizedActivity
from muscle50.domain.analytics import LabelOriginCounts, activity_local_date
from muscle50.domain.exercise_taxonomy import (
    EXERCISE_RULES,
    ExerciseRule,
    LabelOrigin,
    MovementPattern,
    MuscleGroup,
    UnmappedReason,
    classify_exercise,
    classify_strength_set,
    label_origin,
)
from muscle50.domain.recovery_assessment import AdjustmentLevel, RecoveryAssessment, stronger
from muscle50.domain.training_goals import RepRange, TrainingGoals

HISTORY_DAYS = 28
RECENT_DAYS = 7
UNKNOWN_NOTICE_DAYS = 14
# A region "had a session" on a day with at least this many primary-muscle sets.
REGION_SESSION_MIN_SETS = 3
# A region trained with at least this many sets yesterday is rested today (about 48 h).
REGION_RECENT_WORK_MIN_SETS = 6
# A region without a meaningful session for this many days is neglected (the 1/week goal floor).
NEGLECTED_AFTER_DAYS = 7
# The shortest personal interval used for "due" (about 48 h of rest).
MIN_PERSONAL_INTERVAL_DAYS = 2.0
# Under recovery "reduce", regions trained within this many days yield to more rested ones.
REDUCE_REST_DAYS = 2
LOAD_INCREMENT_KG = 2.5
# After a load increase the rep target restarts this far below the top of the range.
REPS_BELOW_TOP_AFTER_LOAD_INCREASE = 4
# The session may exceed the minutes goal by this much before the second accessory is dropped.
SESSION_MINUTES_TOLERANCE = 5
KEY_SETS = 3
ACCESSORY_SETS = 3
ISOLATION_SETS = 3
MAX_ACCESSORIES = 2
SECOND_ACCESSORY_MIN_SESSIONS = 2
MIN_SETS_PER_EXERCISE = 2
MINUTES_PER_WORKING_SET = 3
WARM_UP_MINUTES = 5
STAGNATION_SESSIONS = 3
# Work loads of one label spreading wider than this ratio suggest mixed equipment.
LOAD_SPREAD_RATIO = 1.5
# Best reps at the same work load dropping by this many counts as a performance regression.
REP_REGRESSION = 2

_EPSILON = 1e-6


class Region(StrEnum):
    PUSH = "push"
    PULL = "pull"
    LEGS = "legs"


# Region order is only a final tie-break.
REGION_MUSCLES: Mapping[Region, tuple[MuscleGroup, ...]] = {
    Region.LEGS: (MuscleGroup.QUADRICEPS, MuscleGroup.HAMSTRINGS, MuscleGroup.GLUTES),
    Region.PULL: (
        MuscleGroup.LATS,
        MuscleGroup.UPPER_BACK,
        MuscleGroup.POSTERIOR_DELTOID,
        MuscleGroup.BICEPS,
        MuscleGroup.FOREARMS,
    ),
    Region.PUSH: (
        MuscleGroup.CHEST,
        MuscleGroup.ANTERIOR_DELTOID,
        MuscleGroup.LATERAL_DELTOID,
        MuscleGroup.TRICEPS,
    ),
}
_REGION_OF_MUSCLE = {muscle: region for region, muscles in REGION_MUSCLES.items() for muscle in muscles}


class StrengthFocus(StrEnum):
    """A focus the user may request. ``shoulders`` spans the push and pull regions."""

    PUSH = "push"
    PULL = "pull"
    LEGS = "legs"
    SHOULDERS = "shoulders"


class FocusSource(StrEnum):
    AUTO = "auto"
    USER = "user"


# A requested focus selects exercises by primary muscle only; secondary exposure never qualifies.
FOCUS_MUSCLES: Mapping[StrengthFocus, tuple[MuscleGroup, ...]] = {
    StrengthFocus.PUSH: REGION_MUSCLES[Region.PUSH],
    StrengthFocus.PULL: REGION_MUSCLES[Region.PULL],
    StrengthFocus.LEGS: REGION_MUSCLES[Region.LEGS],
    StrengthFocus.SHOULDERS: (
        MuscleGroup.ANTERIOR_DELTOID,
        MuscleGroup.LATERAL_DELTOID,
        MuscleGroup.POSTERIOR_DELTOID,
    ),
}
# Muscles some taxonomy rule uses as primary; any other focus muscle can never have sets.
_RULE_PRIMARY_MUSCLES = frozenset(rule.primary_muscle.value for rule in EXERCISE_RULES)

COMPOUND_PATTERNS = frozenset(
    {
        MovementPattern.HORIZONTAL_PUSH,
        MovementPattern.VERTICAL_PUSH,
        MovementPattern.HORIZONTAL_PULL,
        MovementPattern.VERTICAL_PULL,
        MovementPattern.SQUAT,
        MovementPattern.HINGE,
        MovementPattern.LUNGE,
    }
)

# Muscles that swimming loads heavily (shoulders, lats, upper back, triceps).
SWIM_OVERLAP_MUSCLES = frozenset(
    {
        MuscleGroup.ANTERIOR_DELTOID,
        MuscleGroup.LATERAL_DELTOID,
        MuscleGroup.POSTERIOR_DELTOID,
        MuscleGroup.LATS,
        MuscleGroup.UPPER_BACK,
        MuscleGroup.TRICEPS,
    }
)
# After a hard swim these primary muscles get one set fewer, and overhead pressing is not
# chosen as the key exercise.
SWIM_SET_REDUCTION_MUSCLES = frozenset({MuscleGroup.ANTERIOR_DELTOID, MuscleGroup.LATERAL_DELTOID, MuscleGroup.LATS})
SWIM_AVOIDED_KEY_PATTERNS = frozenset({MovementPattern.VERTICAL_PUSH})
# Butterfly distance (plausible laps) that counts as a hard shoulder swim on its own
# (account-calibrated: 4 of 21 swims in 2026-07..09 reach it).
SWIM_BUTTERFLY_OVERLAP_METERS = 200.0

# Labels whose stored weight may be added load or machine assistance (Garmin does not say).
AMBIGUOUS_LOAD_LABELS = frozenset({("PULL_UP", None), ("PUSH_UP", None), ("TRICEPS_EXTENSION", "BENCH_DIP")})


class ExerciseRole(StrEnum):
    KEY = "key"
    ACCESSORY = "accessory"
    ISOLATION = "isolation"


class ProgressionAction(StrEnum):
    INCREASE_LOAD = "increase_load"
    ADD_REPS = "add_reps"
    MAINTAIN = "maintain"
    ESTABLISH_BASELINE = "establish_baseline"


@dataclass(frozen=True, order=True)
class ExerciseLabel:
    """A stored Garmin label, exactly as stored (``name`` None = category only)."""

    category: str
    name: str | None

    @property
    def text(self) -> str:
        return f"{self.category}/{self.name or '-'}"


@dataclass(frozen=True)
class PerformedSet:
    sequence: int
    reps: int | None
    weight_kg: float | None


@dataclass(frozen=True)
class ExerciseOccurrence:
    """All ACTIVE sets of one label within one activity, in set order."""

    source_activity_id: str
    local_date: date
    sets: tuple[PerformedSet, ...]
    label_origins: LabelOriginCounts


@dataclass(frozen=True)
class WorkSetSummary:
    """The comparable part of one occurrence.

    ``work_load_kg`` is the heaviest positive load lifted for at least the rep-range minimum
    (or simply the heaviest, flagged ``below_range``, if no set reached it). ``work_set_reps``
    are the reps of every set at that load. Without any positive load the summary is
    ``load_recorded = False`` and ``work_set_reps`` covers all sets with reps.
    """

    source_activity_id: str
    local_date: date
    usable_set_count: int
    load_recorded: bool
    work_load_kg: float | None
    work_set_reps: tuple[int, ...]
    below_range: bool

    @property
    def best_reps(self) -> int | None:
        return max(self.work_set_reps) if self.work_set_reps else None


@dataclass(frozen=True)
class ProgressionTarget:
    action: ProgressionAction
    load_kg: float | None
    target_reps: int | None
    rep_range: RepRange
    basis: tuple[str, ...]
    caveats: tuple[str, ...]
    load_confidence: str
    """``normal``, ``low`` (load history inconsistent or ambiguous), or ``none`` (no load target)."""
    stagnant: bool
    regression: bool
    recent: tuple[WorkSetSummary, ...]


@dataclass(frozen=True)
class PlannedExercise:
    role: ExerciseRole
    category: str
    exercise_name: str | None
    label: str
    movement_pattern: str
    primary_muscle: str
    secondary_muscles: tuple[str, ...]
    sessions_last_28_days: int
    active_sets_last_28_days: int
    last_performed: date
    sets: int
    progression: ProgressionTarget
    adjustments: tuple[str, ...]


@dataclass(frozen=True)
class AlternativeExercise:
    replaces_label: str
    category: str
    exercise_name: str | None
    label: str
    sessions_last_28_days: int
    reason: str


@dataclass(frozen=True)
class MuscleStatus:
    """Primary-muscle detail behind a region (mapped ACTIVE sets only; swims never count)."""

    muscle: str
    sets_last_7_days: int
    sets_last_28_days: int
    last_trained_date: date | None


@dataclass(frozen=True)
class RegionStatus:
    region: str
    muscles: tuple[str, ...]
    sets_last_7_days: int
    sessions_last_7_days: int
    sessions_last_28_days: int
    weekly_average_sets_28_days: float
    last_trained_date: date | None
    days_since_last_trained: int | None
    sets_previous_day: int
    personal_interval_days: float
    """The region's own average days between sessions over 28 days, clamped to 2-7 days."""
    due_ratio: float | None
    """Days since the last session / personal interval (>= 1: at or past its usual time)."""
    neglected: bool
    """No meaningful strength session for at least 7 days (the 1/week goal floor)."""
    recently_trained_under_reduce: bool
    eligible: bool
    swim_demoted: bool
    muscle_detail: tuple[MuscleStatus, ...]
    notes: tuple[str, ...]


@dataclass(frozen=True)
class SwimOverlap:
    """A swim whose fatigue overlaps today's strength (previous day or same day)."""

    source_activity_id: str
    local_date: date
    same_day: bool
    distance_meters: float | None
    high_intensity: bool
    butterfly_meters: float
    reasons: tuple[str, ...]

    @property
    def strong(self) -> bool:
        return self.high_intensity or self.butterfly_meters >= SWIM_BUTTERFLY_OVERLAP_METERS


@dataclass(frozen=True)
class UnknownExerciseNotice:
    source_activity_id: str
    local_date: date
    unknown_set_count: int
    set_sequences: tuple[int, ...]
    action: str


@dataclass(frozen=True)
class StrengthRecommendation:
    focus: str | None
    focus_source: str
    """``auto`` (chosen by the region ranking) or ``user`` (requested; never switched)."""
    auto_focus: str | None
    """What the region ranking would choose; evidence only when the focus was requested."""
    focus_muscles: tuple[str, ...]
    reasons: tuple[str, ...]
    regions: tuple[RegionStatus, ...]
    exercises: tuple[PlannedExercise, ...]
    alternative: AlternativeExercise | None
    working_sets: int
    estimated_minutes: int
    session_minutes_goal: int
    adjustment_level: str
    adjustments: tuple[str, ...]
    swim_overlaps: tuple[SwimOverlap, ...]
    avoided_muscles: tuple[str, ...]
    unknown_active_sets_last_7_days: int
    unknown_active_sets_last_28_days: int
    unknown_notices: tuple[UnknownExerciseNotice, ...]


def kg_text(value: float) -> str:
    """Format a load without a "-0" artefact (Garmin can store -0.0)."""
    return f"{value + 0.0:g} kg"


def strength_history(
    activities: Sequence[NormalizedActivity], start: date, end: date
) -> list[tuple[date, NormalizedActivity]]:
    dated = []
    for activity in activities:
        day = activity_local_date(activity)
        if activity.canonical_type is ActivityType.STRENGTH and day is not None and start <= day <= end:
            dated.append((day, activity))
    dated.sort(key=lambda item: (item[0], item[1].started_at_local or "", item[1].source_activity_id))
    return dated


def exercise_occurrences(
    history: Sequence[tuple[date, NormalizedActivity]],
) -> dict[ExerciseLabel, list[ExerciseOccurrence]]:
    """Occurrences of every mapped label, chronological. Unmapped labels are left out."""
    result: dict[ExerciseLabel, list[ExerciseOccurrence]] = {}
    for day, activity in history:
        per_label: dict[ExerciseLabel, tuple[list[PerformedSet], Counter[LabelOrigin]]] = {}
        for strength_set in activity.strength_sets:
            if strength_set.set_type != "ACTIVE":
                continue
            classification = classify_strength_set(strength_set)
            if classification.rule is None or classification.source_category is None:
                continue
            label = ExerciseLabel(classification.source_category, classification.source_name)
            sets, origins = per_label.setdefault(label, ([], Counter()))
            sets.append(PerformedSet(strength_set.sequence, strength_set.reps, strength_set.normalized_weight_kg))
            origins[label_origin(strength_set.source_exercise_probability)] += 1
        for label, (sets, origins) in per_label.items():
            result.setdefault(label, []).append(
                ExerciseOccurrence(
                    activity.source_activity_id,
                    day,
                    tuple(sets),
                    LabelOriginCounts(
                        confirmed=origins[LabelOrigin.CONFIRMED],
                        auto_detected=origins[LabelOrigin.AUTO_DETECTED],
                        unspecified=origins[LabelOrigin.UNSPECIFIED],
                    ),
                )
            )
    return result


def summarize_occurrence(occurrence: ExerciseOccurrence, rep_range: RepRange) -> WorkSetSummary:
    usable: list[tuple[int, float]] = []
    for item in occurrence.sets:
        # Reps 0/None and the negative "no weight" sentinel are not comparable performance.
        if item.reps is None or item.reps <= 0 or item.weight_kg is None or item.weight_kg < 0:
            continue
        usable.append((item.reps, item.weight_kg + 0.0))
    loaded = [(reps, weight) for reps, weight in usable if weight > 0]
    if not loaded:
        return WorkSetSummary(
            occurrence.source_activity_id,
            occurrence.local_date,
            len(usable),
            False,
            None,
            tuple(reps for reps, _weight in usable),
            False,
        )
    in_range = [(reps, weight) for reps, weight in loaded if reps >= rep_range.minimum]
    work_load = max(weight for _reps, weight in (in_range or loaded))
    return WorkSetSummary(
        occurrence.source_activity_id,
        occurrence.local_date,
        len(usable),
        True,
        work_load,
        tuple(reps for reps, weight in loaded if abs(weight - work_load) < _EPSILON),
        not in_range,
    )


def plan_progression(
    label: ExerciseLabel,
    occurrences: Sequence[ExerciseOccurrence],
    rep_range: RepRange,
    level: AdjustmentLevel,
) -> ProgressionTarget:
    summaries = [summarize_occurrence(item, rep_range) for item in occurrences]
    usable = [item for item in summaries if item.usable_set_count]
    recent = tuple(usable[-4:])
    if not usable:
        return ProgressionTarget(
            ProgressionAction.ESTABLISH_BASELINE,
            None,
            rep_range.minimum,
            rep_range,
            ("no recent set of this label has both reps and a recorded load",),
            (),
            "none",
            False,
            False,
            recent,
        )

    last = usable[-1]
    basis = [f"last session {last.local_date.isoformat()} ({last.source_activity_id}): {_work_text(last)}"]
    caveats: list[str] = []
    best = last.best_reps or 0
    target_reps: int | None

    if not last.load_recorded:
        action = ProgressionAction.ADD_REPS if best < rep_range.maximum else ProgressionAction.MAINTAIN
        target_reps = min(best + 1, rep_range.maximum)
        load: float | None = None
        caveats.append("no external load recorded (0 kg or missing); rep target only")
        basis.append(f"best set {best} reps; target {target_reps} reps")
    else:
        work_load = last.work_load_kg or 0.0
        top_hits = sum(1 for reps in last.work_set_reps if reps >= rep_range.maximum)
        load = work_load
        if top_hits >= 2:
            action = ProgressionAction.INCREASE_LOAD
            load = work_load + LOAD_INCREMENT_KG
            target_reps = max(rep_range.minimum, rep_range.maximum - REPS_BELOW_TOP_AFTER_LOAD_INCREASE)
            basis.append(
                f"{top_hits} work sets reached the top of {rep_range.minimum}-{rep_range.maximum} reps at "
                f"{kg_text(work_load)}; add {kg_text(LOAD_INCREMENT_KG)} (or the next available step)"
            )
        elif last.below_range:
            action = ProgressionAction.ADD_REPS
            target_reps = rep_range.minimum
            basis.append(f"no set reached {rep_range.minimum} reps; stay at {kg_text(work_load)} until it does")
        elif best >= rep_range.maximum:
            action = ProgressionAction.ADD_REPS
            target_reps = rep_range.maximum
            basis.append(
                f"one work set reached {rep_range.maximum} reps at {kg_text(work_load)}; "
                "repeat it on at least 2 work sets before adding load"
            )
        else:
            action = ProgressionAction.ADD_REPS
            target_reps = best + 1
            basis.append(f"same load, one more rep than the best work set ({best} -> {target_reps})")

    comparable = _previous_at_same_load(usable)
    regression = comparable is not None and (last.best_reps or 0) <= (comparable.best_reps or 0) - REP_REGRESSION
    if (
        regression
        and comparable is not None
        and action in (ProgressionAction.INCREASE_LOAD, ProgressionAction.ADD_REPS)
    ):
        action, load, target_reps = _maintain(last, rep_range)
        basis.append(
            f"reps at {kg_text(last.work_load_kg or 0.0)} dropped from {comparable.best_reps} "
            f"({comparable.local_date.isoformat()}) to {last.best_reps}; repeat instead of progressing"
        )
    if level is not AdjustmentLevel.NORMAL and action in (ProgressionAction.INCREASE_LOAD, ProgressionAction.ADD_REPS):
        action, load, target_reps = _maintain(last, rep_range)
        basis.append(f"recovery {level.value}: no load or rep increase; repeat the last work sets")

    trend = _trend_text(usable)
    if trend:
        basis.append(trend)
    stagnant = _stagnant(usable)
    if stagnant:
        basis.append(
            f"stagnant: same work load and no rep gain over the last {STAGNATION_SESSIONS} sessions of this label"
        )

    load_confidence = "none" if load is None else "normal"
    loads = [item.work_load_kg for item in usable if item.work_load_kg is not None]
    if load is not None and len(loads) >= 2 and max(loads) > min(loads) * LOAD_SPREAD_RATIO:
        load_confidence = "low"
        caveats.append(
            f"work loads ranged {kg_text(min(loads))}-{kg_text(max(loads))} over {len(loads)} sessions; "
            "this Garmin label may cover different equipment, so treat the load as approximate"
        )
    if load is not None and (label.category, label.name) in AMBIGUOUS_LOAD_LABELS:
        load_confidence = "low"
        caveats.append("stored weight may be added load or machine assistance; Garmin does not say which")
    last_origins = occurrences[-1].label_origins
    if last_origins.auto_detected and not last_origins.confirmed:
        caveats.append("label auto-detected by the watch (not confirmed in Garmin Connect)")

    return ProgressionTarget(
        action,
        load,
        target_reps,
        rep_range,
        tuple(basis),
        tuple(caveats),
        load_confidence,
        stagnant,
        regression,
        recent,
    )


def _maintain(last: WorkSetSummary, rep_range: RepRange) -> tuple[ProgressionAction, float | None, int | None]:
    best = last.best_reps
    return ProgressionAction.MAINTAIN, last.work_load_kg, min(best, rep_range.maximum) if best is not None else None


def _work_text(summary: WorkSetSummary) -> str:
    reps = "/".join(str(reps) for reps in summary.work_set_reps)
    if not summary.load_recorded:
        return f"reps {reps} without recorded load"
    suffix = " (below rep range)" if summary.below_range else ""
    return f"work load {kg_text(summary.work_load_kg or 0.0)} x {reps} reps{suffix}"


def _previous_at_same_load(usable: Sequence[WorkSetSummary]) -> WorkSetSummary | None:
    """The latest earlier session with the same work load (the only comparable performance).

    A lower work load alone is not a regression: under one Garmin label it may be different
    equipment or a deliberate choice, so loads are only compared with themselves.
    """
    last = usable[-1]
    if not last.load_recorded:
        return None
    for item in reversed(usable[:-1]):
        if item.load_recorded and abs((item.work_load_kg or 0.0) - (last.work_load_kg or 0.0)) < _EPSILON:
            return item
    return None


def _stagnant(usable: Sequence[WorkSetSummary]) -> bool:
    window = [item for item in usable if item.load_recorded][-STAGNATION_SESSIONS:]
    if len(window) < STAGNATION_SESSIONS:
        return False
    first_load = window[0].work_load_kg or 0.0
    if any(abs((item.work_load_kg or 0.0) - first_load) >= _EPSILON for item in window):
        return False
    return (window[-1].best_reps or 0) <= (window[0].best_reps or 0)


def _trend_text(usable: Sequence[WorkSetSummary]) -> str | None:
    loaded = [item for item in usable if item.load_recorded]
    if len(loaded) < 2:
        return None
    points = ", ".join(
        f"{item.local_date.strftime('%m-%d')} {kg_text(item.work_load_kg or 0.0)}x{item.best_reps}" for item in loaded
    )
    return f"{len(loaded)}-session trend (work load x best reps): {points}"


def _region_sets_by_day(
    history: Sequence[tuple[date, NormalizedActivity]],
) -> tuple[dict[Region, Counter[date]], dict[MuscleGroup, Counter[date]], Counter[date]]:
    region_sets: dict[Region, Counter[date]] = {region: Counter() for region in REGION_MUSCLES}
    muscle_sets: dict[MuscleGroup, Counter[date]] = {muscle: Counter() for muscle in MuscleGroup}
    unknown_sets: Counter[date] = Counter()
    for day, activity in history:
        for strength_set in activity.strength_sets:
            if strength_set.set_type != "ACTIVE":
                continue
            classification = classify_strength_set(strength_set)
            if classification.unmapped_reason is UnmappedReason.UNKNOWN_SOURCE_LABEL:
                unknown_sets[day] += 1
            rule = classification.rule
            if rule is None:
                continue
            muscle_sets[rule.primary_muscle][day] += 1
            if rule.primary_muscle in _REGION_OF_MUSCLE:
                region_sets[_REGION_OF_MUSCLE[rule.primary_muscle]][day] += 1
    return region_sets, muscle_sets, unknown_sets


def _region_statuses(
    as_of: date,
    region_sets: Mapping[Region, Counter[date]],
    muscle_sets: Mapping[MuscleGroup, Counter[date]],
    goals: TrainingGoals,
    strong_swim: bool,
    level: AdjustmentLevel,
    avoided: frozenset[MuscleGroup],
) -> list[RegionStatus]:
    recent_start = as_of - timedelta(days=RECENT_DAYS)
    previous_day = as_of - timedelta(days=1)
    # The weekly goal bounds the personal interval: a rarely trained region still becomes
    # due within a week, and a daily-trained one is never treated as due sooner than ~48 h.
    longest_interval = 7.0 / goals.region_min_sessions_per_week
    statuses = []
    for region, muscles in REGION_MUSCLES.items():
        by_day = region_sets[region]
        sets_7 = sum(count for day, count in by_day.items() if day >= recent_start)
        trained_days = sorted(day for day, count in by_day.items() if count >= REGION_SESSION_MIN_SETS)
        sessions_7 = sum(1 for day in trained_days if day >= recent_start)
        last = trained_days[-1] if trained_days else None
        days_since = (as_of - last).days if last else None
        if trained_days:
            interval = min(longest_interval, max(MIN_PERSONAL_INTERVAL_DAYS, HISTORY_DAYS / len(trained_days)))
        else:
            interval = longest_interval
        neglected = days_since is None or days_since >= NEGLECTED_AFTER_DAYS
        recent_under_reduce = (
            level is AdjustmentLevel.REDUCE and days_since is not None and days_since <= REDUCE_REST_DAYS
        )
        previous_sets = by_day.get(previous_day, 0)
        notes = []
        eligible = True
        if previous_sets >= REGION_RECENT_WORK_MIN_SETS:
            eligible = False
            notes.append(f"{previous_sets} primary sets yesterday; rest about 48 h")
        if all(muscle in avoided for muscle in muscles):
            eligible = False
            notes.append("all muscles of this region are on the avoid list")
        if neglected:
            notes.append(
                f"no strength session for {NEGLECTED_AFTER_DAYS}+ days (swims never count); "
                f"below the {goals.region_min_sessions_per_week}/week goal"
            )
        swim_demoted = strong_swim and region in (Region.PUSH, Region.PULL)
        if swim_demoted:
            notes.append("hard swim overlap: shoulders/back/triceps deprioritised")
        if recent_under_reduce:
            notes.append(f"recovery reduce: trained in the last {REDUCE_REST_DAYS} days; more rested regions first")
        statuses.append(
            RegionStatus(
                region=region.value,
                muscles=tuple(muscle.value for muscle in muscles),
                sets_last_7_days=sets_7,
                sessions_last_7_days=sessions_7,
                sessions_last_28_days=len(trained_days),
                weekly_average_sets_28_days=round(sum(by_day.values()) * 7 / HISTORY_DAYS, 2),
                last_trained_date=last,
                days_since_last_trained=days_since,
                sets_previous_day=previous_sets,
                personal_interval_days=round(interval, 2),
                due_ratio=round(days_since / interval, 3) if days_since is not None else None,
                neglected=neglected,
                recently_trained_under_reduce=recent_under_reduce,
                eligible=eligible,
                swim_demoted=swim_demoted,
                muscle_detail=tuple(_muscle_status(muscle, muscle_sets[muscle], recent_start) for muscle in muscles),
                notes=tuple(notes),
            )
        )
    return statuses


def _muscle_status(muscle: MuscleGroup, by_day: Counter[date], recent_start: date) -> MuscleStatus:
    return MuscleStatus(
        muscle=muscle.value,
        sets_last_7_days=sum(count for day, count in by_day.items() if day >= recent_start),
        sets_last_28_days=sum(by_day.values()),
        last_trained_date=max(by_day) if by_day else None,
    )


def _region_rank(status: RegionStatus) -> tuple[int, int, int, int, float, float, int]:
    weekly = status.weekly_average_sets_28_days
    volume_ratio = status.sets_last_7_days / weekly if weekly > 0 else 0.0
    return (
        0 if status.eligible else 1,
        # Genuine neglect (no strength session for a week) is protected; swims never count.
        # Selecting the region resets it, so this cannot pick the same region repeatedly.
        0 if status.neglected else 1,
        1 if status.swim_demoted else 0,
        1 if status.recently_trained_under_reduce else 0,
        # Otherwise the region most due against its own usual interval: a region trained
        # yesterday is barely due, whatever a weekly count says.
        -(status.due_ratio if status.due_ratio is not None else math.inf),
        # Then lower 7-day volume relative to the user's own 28-day average (no universal target).
        round(volume_ratio, 6),
        list(REGION_MUSCLES).index(Region(status.region)),
    )


@dataclass(frozen=True)
class _Candidate:
    label: ExerciseLabel
    rule: ExerciseRule
    occurrences: tuple[ExerciseOccurrence, ...]

    @property
    def sessions(self) -> int:
        return len({item.source_activity_id for item in self.occurrences})

    @property
    def active_sets(self) -> int:
        return sum(len(item.sets) for item in self.occurrences)

    @property
    def last_date(self) -> date:
        return self.occurrences[-1].local_date

    @property
    def compound(self) -> bool:
        return self.rule.movement_pattern in COMPOUND_PATTERNS


def _familiarity_key(candidate: _Candidate) -> tuple[int, int, int, str]:
    return (-candidate.sessions, -candidate.active_sets, -candidate.last_date.toordinal(), candidate.label.text)


def _candidates(
    focus_muscles: Iterable[MuscleGroup],
    occurrences: Mapping[ExerciseLabel, list[ExerciseOccurrence]],
    avoided: frozenset[MuscleGroup],
) -> list[_Candidate]:
    muscles = set(focus_muscles)
    result = []
    for label, items in occurrences.items():
        rule = _rule_of(label)
        if rule is None or rule.primary_muscle not in muscles:
            continue
        if rule.primary_muscle in avoided or any(muscle in avoided for muscle in rule.secondary_muscles):
            continue
        result.append(_Candidate(label, rule, tuple(items)))
    return sorted(result, key=_familiarity_key)


def _rule_of(label: ExerciseLabel) -> ExerciseRule | None:
    return classify_exercise(label.category, label.name).rule


def _select_slots(
    candidates: Sequence[_Candidate], avoided_key_patterns: frozenset[MovementPattern]
) -> tuple[list[tuple[ExerciseRole, _Candidate]], list[str]]:
    notes: list[str] = []
    compounds = [item for item in candidates if item.compound]
    isolations = [item for item in candidates if not item.compound]
    key = next((item for item in compounds if item.rule.movement_pattern not in avoided_key_patterns), None)
    skipped = [item for item in compounds if item.rule.movement_pattern in avoided_key_patterns]
    if skipped and (key is None or _familiarity_key(skipped[0]) < _familiarity_key(key)):
        notes.append(f"{skipped[0].label.text} not used as key exercise after a hard swim (overhead pressing)")
    if key is None and isolations:
        key = isolations[0]
    if key is None:
        return [], notes
    plan: list[tuple[ExerciseRole, _Candidate]] = [(ExerciseRole.KEY, key)]
    remaining = [
        item for item in compounds if item is not key and item.rule.movement_pattern not in avoided_key_patterns
    ]
    # First accessory: prefer a movement pattern different from the key exercise.
    remaining.sort(key=lambda item: (item.rule.movement_pattern == key.rule.movement_pattern, _familiarity_key(item)))
    if remaining:
        plan.append((ExerciseRole.ACCESSORY, remaining.pop(0)))
    # Second accessory: the most familiar remaining compound, only if it is a regular one.
    remaining.sort(key=_familiarity_key)
    second = next((item for item in remaining if item.sessions >= SECOND_ACCESSORY_MIN_SESSIONS), None)
    if second is not None and MAX_ACCESSORIES >= 2:
        plan.append((ExerciseRole.ACCESSORY, second))
    # Isolation: prefer a primary muscle the compounds do not already target, then familiarity.
    covered = {candidate.rule.primary_muscle for _role, candidate in plan}
    options = sorted(
        (item for item in isolations if item is not key),
        key=lambda item: (item.rule.primary_muscle in covered, _familiarity_key(item)),
    )
    if options:
        plan.append((ExerciseRole.ISOLATION, options[0]))
    return plan, notes


def _auto_selection(
    ranked: Sequence[RegionStatus],
    occurrences: Mapping[ExerciseLabel, list[ExerciseOccurrence]],
    avoided: frozenset[MuscleGroup],
    avoided_patterns: frozenset[MovementPattern],
) -> tuple[RegionStatus | None, list[tuple[ExerciseRole, _Candidate]], list[str], list[str]]:
    """The automatic focus: the first ranked region that has a familiar mapped exercise."""
    skipped: list[str] = []
    for status in ranked:
        candidates = _candidates(REGION_MUSCLES[Region(status.region)], occurrences, avoided)
        plan, notes = _select_slots(candidates, avoided_patterns)
        if plan:
            return status, plan, notes, skipped
        skipped.append(f"{status.region}: no familiar mapped exercise in the last {HISTORY_DAYS} days; skipped")
    return None, [], [], skipped


def build_strength_recommendation(
    as_of: date,
    activities: Sequence[NormalizedActivity],
    recovery: RecoveryAssessment,
    swim_overlaps: Sequence[SwimOverlap],
    goals: TrainingGoals,
    avoid_muscles: Iterable[MuscleGroup] = (),
    requested_focus: StrengthFocus | None = None,
) -> StrengthRecommendation:
    """Recommend today's strength session from history strictly before ``as_of``.

    With ``requested_focus`` the session is built around that focus and never switched;
    recovery, swim overlap, ``avoid_muscles`` and progression rules still apply unchanged.
    """
    avoided = frozenset(avoid_muscles)
    history = strength_history(activities, as_of - timedelta(days=HISTORY_DAYS), as_of - timedelta(days=1))
    occurrences = exercise_occurrences(history)
    region_sets, muscle_sets, unknown_by_day = _region_sets_by_day(history)
    strong_swim = any(item.strong for item in swim_overlaps)
    statuses = _region_statuses(as_of, region_sets, muscle_sets, goals, strong_swim, recovery.level, avoided)
    ranked = sorted(statuses, key=_region_rank)

    reasons: list[str] = []
    adjustments: list[str] = []
    level = recovery.level
    avoided_patterns = SWIM_AVOIDED_KEY_PATTERNS if strong_swim else frozenset()
    # Always computed: the decision without a request, evidence alongside one.
    auto_status, auto_plan, auto_notes, auto_skipped = _auto_selection(ranked, occurrences, avoided, avoided_patterns)

    plan: list[tuple[ExerciseRole, _Candidate]]
    if requested_focus is None:
        if not any(item.eligible for item in statuses):
            level = stronger(level, AdjustmentLevel.REDUCE)
            adjustments.append("every region was trained substantially yesterday: reduced session")
        plan = auto_plan
        adjustments.extend(auto_notes)
        reasons.extend(auto_skipped)
        if auto_status is not None:
            reasons.insert(0, _focus_reason(auto_status, ranked))
        else:
            reasons.append(
                f"no mapped strength history in the last {HISTORY_DAYS} days; no exercise can be recommended"
            )
        focus_name = auto_status.region if auto_status else None
        focus_muscles = auto_status.muscles if auto_status else ()
        focus_source = FocusSource.AUTO
    else:
        requested_muscles = FOCUS_MUSCLES[requested_focus]
        # The same ~48 h rest rule that makes a region ineligible; a request keeps the focus,
        # so it reduces the session instead of switching away from it.
        previous_day = as_of - timedelta(days=1)
        sets_yesterday = sum(muscle_sets[muscle].get(previous_day, 0) for muscle in requested_muscles)
        if sets_yesterday >= REGION_RECENT_WORK_MIN_SETS:
            level = stronger(level, AdjustmentLevel.REDUCE)
            adjustments.append(
                f"requested {requested_focus.value} had {sets_yesterday} primary sets yesterday (about 48 h rest "
                "is usual): reduced session, focus kept"
            )
        plan, notes = _select_slots(_candidates(requested_muscles, occurrences, avoided), avoided_patterns)
        adjustments.extend(notes)
        reasons.append(_requested_focus_reason(requested_focus, statuses, auto_status))
        if not plan:
            reasons.append(
                f"history is limited: no familiar mapped {requested_focus.value} exercise (primary muscle "
                f"{', '.join(muscle.value for muscle in requested_muscles)}) in the last {HISTORY_DAYS} days; "
                "no exercise or load target is recommended and the focus is not switched"
            )
        elif all(candidate.sessions < SECOND_ACCESSORY_MIN_SESSIONS for _role, candidate in plan):
            reasons.append(
                f"history is limited: every planned {requested_focus.value} exercise has only one session in the "
                f"last {HISTORY_DAYS} days, so its targets rest on that single session"
            )
        focus_name = requested_focus.value
        focus_muscles = tuple(muscle.value for muscle in requested_muscles)
        focus_source = FocusSource.USER

    exercises: list[PlannedExercise] = []
    for role, candidate in plan:
        rep_range = goals.compound_rep_range if candidate.compound else goals.isolation_rep_range
        progression = plan_progression(candidate.label, candidate.occurrences, rep_range, level)
        sets = {ExerciseRole.KEY: KEY_SETS, ExerciseRole.ACCESSORY: ACCESSORY_SETS}.get(role, ISOLATION_SETS)
        exercise_adjustments = []
        if level is AdjustmentLevel.REDUCE:
            sets -= 1
            exercise_adjustments.append("recovery reduce: one set fewer")
        if strong_swim and candidate.rule.primary_muscle in SWIM_SET_REDUCTION_MUSCLES:
            sets -= 1
            exercise_adjustments.append("hard swim overlap: one set fewer for shoulders/lats")
        sets = max(sets, MIN_SETS_PER_EXERCISE)
        if candidate.rule.primary_muscle in SWIM_OVERLAP_MUSCLES and swim_overlaps and not strong_swim:
            exercise_adjustments.append("recent swim also loads this muscle; stop 2-3 reps short of failure")
        exercises.append(
            PlannedExercise(
                role=role,
                category=candidate.label.category,
                exercise_name=candidate.label.name,
                label=candidate.label.text,
                movement_pattern=candidate.rule.movement_pattern.value,
                primary_muscle=candidate.rule.primary_muscle.value,
                secondary_muscles=tuple(muscle.value for muscle in candidate.rule.secondary_muscles),
                sessions_last_28_days=candidate.sessions,
                active_sets_last_28_days=candidate.active_sets,
                last_performed=candidate.last_date,
                sets=sets,
                progression=progression,
                adjustments=tuple(exercise_adjustments),
            )
        )

    # Keep the session near the time goal: drop the second accessory first.
    while _minutes(exercises) > goals.strength_session_minutes + SESSION_MINUTES_TOLERANCE and _drop_second_accessory(
        exercises
    ):
        adjustments.append(f"second accessory dropped to stay near {goals.strength_session_minutes} minutes")
    if (
        requested_focus is not None
        and exercises
        and not any(item.role is ExerciseRole.ACCESSORY for item in exercises)
        and _minutes(exercises) + SESSION_MINUTES_TOLERANCE < goals.strength_session_minutes
    ):
        # Reported only: a requested focus is never padded with exercises outside its history.
        familiar = _candidates(FOCUS_MUSCLES[requested_focus], occurrences, avoided)
        usable = sum(1 for item in familiar if item.compound and item.rule.movement_pattern not in avoided_patterns)
        swim_rule = any(item.compound and item.rule.movement_pattern in avoided_patterns for item in familiar)
        reasons.append(
            f"history is limited: {usable} usable familiar compound {requested_focus.value} exercises in the last "
            f"{HISTORY_DAYS} days{' after the hard-swim overhead-press rule' if swim_rule else ''}, so no "
            f"accessory slot was filled; the session is about {_minutes(exercises)} min against the "
            f"{goals.strength_session_minutes}-minute goal and nothing was added to fill it"
        )

    if level is not AdjustmentLevel.NORMAL:
        fired = ", ".join(item.rule or item.field for item in recovery.fired) or "no other region rested"
        adjustments.insert(0, f"recovery {level.value}: {fired}")
    elif not recovery.data_available:
        adjustments.insert(0, "no recovery data for this date: no recovery adjustment (missing is not poor)")
    for overlap in swim_overlaps:
        when = "earlier today" if overlap.same_day else "yesterday"
        detail = "; ".join(overlap.reasons) if overlap.reasons else "no high-intensity signal"
        adjustments.append(f"swim {when} ({overlap.source_activity_id}): shoulders/back/triceps overlap; {detail}")

    recent_start = as_of - timedelta(days=RECENT_DAYS)
    unknown_recent = sum(count for day, count in unknown_by_day.items() if day >= recent_start)
    if unknown_recent:
        reasons.append(
            f"{unknown_recent} UNKNOWN sets in the last 7 days are not attributed to any muscle; "
            "region set counts are lower bounds"
        )
    return StrengthRecommendation(
        focus=focus_name,
        focus_source=focus_source.value,
        auto_focus=auto_status.region if auto_status else None,
        focus_muscles=focus_muscles,
        reasons=tuple(reasons),
        regions=tuple(ranked),
        exercises=tuple(exercises),
        alternative=_alternative(exercises, occurrences, avoided),
        working_sets=sum(item.sets for item in exercises),
        estimated_minutes=_minutes(exercises),
        session_minutes_goal=goals.strength_session_minutes,
        adjustment_level=level.value,
        adjustments=tuple(adjustments),
        swim_overlaps=tuple(swim_overlaps),
        avoided_muscles=tuple(sorted(muscle.value for muscle in avoided)),
        unknown_active_sets_last_7_days=unknown_recent,
        unknown_active_sets_last_28_days=sum(unknown_by_day.values()),
        unknown_notices=_unknown_notices(as_of, history),
    )


def _region_text(status: RegionStatus) -> str:
    if status.last_trained_date is None:
        last = f"no session in {HISTORY_DAYS} days"
    else:
        last = f"last session {status.last_trained_date.isoformat()} ({status.days_since_last_trained} d ago)"
    due = f"{status.due_ratio:g}" if status.due_ratio is not None else "-"
    return (
        f"{last}, usual interval {status.personal_interval_days:g} d "
        f"({status.sessions_last_28_days} sessions/28 d), due {due}, "
        f"{status.sets_last_7_days} sets in 7 d vs own {status.weekly_average_sets_28_days:g}/week"
    )


def _decided_by(status: RegionStatus, runner_up: RegionStatus | None) -> str:
    """Name the first ranking criterion on which the focus beat the runner-up."""
    if runner_up is None:
        return "only region with familiar exercises"
    other = runner_up.region
    mine, theirs = _region_rank(status), _region_rank(runner_up)
    if mine[0] != theirs[0]:
        return f"{other} is resting after heavy work yesterday or avoided"
    if mine[1] != theirs[1]:
        return f"no strength session for {NEGLECTED_AFTER_DAYS}+ days (protected; swims never count)"
    if mine[2] != theirs[2]:
        return f"hard swim overlap moves {other} back"
    if mine[3] != theirs[3]:
        return f"recovery reduce: {other} was trained in the last {REDUCE_REST_DAYS} days"
    if mine[4] != theirs[4]:
        return f"more due against its own usual interval than {other}"
    if mine[5] != theirs[5]:
        return f"lower 7-day volume against its own average than {other}"
    return f"tie with {other}; fixed region order"


def _focus_reason(status: RegionStatus, ranked: Sequence[RegionStatus]) -> str:
    later = list(ranked[ranked.index(status) + 1 :])
    runner_up = later[0] if later else None
    return f"{status.region}: {_decided_by(status, runner_up)}; {_region_text(status)}"


def _requested_focus_reason(
    focus: StrengthFocus, statuses: Sequence[RegionStatus], auto_status: RegionStatus | None
) -> str:
    if auto_status is None:
        automatic = "automatic selection found no usable history"
    elif auto_status.region == focus.value:
        automatic = "automatic selection agrees"
    else:
        automatic = f"automatic selection would be {auto_status.region}"
    if focus is StrengthFocus.SHOULDERS:
        # Shoulders spans two regions, so report its own primary muscles.
        details = {item.muscle: item for status in statuses for item in status.muscle_detail}
        detail = "; ".join(_muscle_text(details[muscle.value]) for muscle in FOCUS_MUSCLES[focus])
    else:
        detail = _region_text(next(item for item in statuses if item.region == focus.value))
    return f"{focus.value}: user-selected focus ({automatic}); {detail}"


def _muscle_text(status: MuscleStatus) -> str:
    if status.muscle not in _RULE_PRIMARY_MUSCLES:
        # Structurally always zero, so do not let it read as neglect.
        return f"{status.muscle}: no v1 taxonomy rule uses it as a primary muscle (never counted)"
    last = status.last_trained_date.isoformat() if status.last_trained_date else f"none in {HISTORY_DAYS} d"
    return (
        f"{status.muscle} {status.sets_last_7_days} primary sets in 7 d, "
        f"{status.sets_last_28_days} in 28 d (last {last})"
    )


def _minutes(exercises: Sequence[PlannedExercise]) -> int:
    return WARM_UP_MINUTES + MINUTES_PER_WORKING_SET * sum(item.sets for item in exercises) if exercises else 0


def _drop_second_accessory(exercises: list[PlannedExercise]) -> bool:
    accessories = [index for index, item in enumerate(exercises) if item.role is ExerciseRole.ACCESSORY]
    if len(accessories) < 2:
        return False
    del exercises[accessories[-1]]
    return True


def _alternative(
    exercises: Sequence[PlannedExercise],
    occurrences: Mapping[ExerciseLabel, list[ExerciseOccurrence]],
    avoided: frozenset[MuscleGroup],
) -> AlternativeExercise | None:
    """At most one optional variation, only for a stagnant exercise, only from history."""
    planned = {item.label for item in exercises}
    for exercise in exercises:
        if not exercise.progression.stagnant:
            continue
        options = []
        for label, items in occurrences.items():
            rule = _rule_of(label)
            if rule is None or label.text in planned:
                continue
            if rule.primary_muscle in avoided or any(muscle in avoided for muscle in rule.secondary_muscles):
                continue
            same_pattern = rule.movement_pattern.value == exercise.movement_pattern
            same_primary = rule.primary_muscle.value == exercise.primary_muscle
            if same_pattern or same_primary:
                options.append(
                    (0 if same_pattern else 1, _familiarity_key(_Candidate(label, rule, tuple(items))), label, items)
                )
        if options:
            _rank, _key, label, items = min(options)
            return AlternativeExercise(
                replaces_label=exercise.label,
                category=label.category,
                exercise_name=label.name,
                label=label.text,
                sessions_last_28_days=len({item.source_activity_id for item in items}),
                reason=f"optional: {exercise.label} has stagnated; this familiar variation trains the same "
                f"{'movement pattern' if _rank == 0 else 'primary muscle'}",
            )
    return None


def _unknown_notices(
    as_of: date, history: Sequence[tuple[date, NormalizedActivity]]
) -> tuple[UnknownExerciseNotice, ...]:
    start = as_of - timedelta(days=UNKNOWN_NOTICE_DAYS)
    notices = []
    for day, activity in history:
        if day < start:
            continue
        sequences = tuple(
            item.sequence
            for item in activity.strength_sets
            if item.set_type == "ACTIVE"
            and classify_strength_set(item).unmapped_reason is UnmappedReason.UNKNOWN_SOURCE_LABEL
        )
        if sequences:
            notices.append(
                UnknownExerciseNotice(
                    source_activity_id=activity.source_activity_id,
                    local_date=day,
                    unknown_set_count=len(sequences),
                    set_sequences=sequences,
                    action=(
                        "set the exercise in Garmin Connect, then run: "
                        f"muscle50 garmin refresh {activity.source_activity_id}"
                    ),
                )
            )
    return tuple(sorted(notices, key=lambda item: (item.local_date, item.source_activity_id), reverse=True))


def primary_muscle_sets_on(day: date, activities: Sequence[NormalizedActivity]) -> Counter[MuscleGroup]:
    """Mapped ACTIVE sets per primary muscle for strength activities dated ``day``."""
    counts: Counter[MuscleGroup] = Counter()
    for _day, activity in strength_history(activities, day, day):
        for strength_set in activity.strength_sets:
            rule = classify_strength_set(strength_set).rule if strength_set.set_type == "ACTIVE" else None
            if rule is not None:
                counts[rule.primary_muscle] += 1
    return counts
