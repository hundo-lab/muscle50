"""Goal-mode rules and display items (Training Goal Mode and Evidence-Linked Rules v1).

Pure and deterministic: no I/O, no clock. Every rule carries the evidence it rests on, as IDs from
docs/evidence/training-nutrition-evidence.md, or ``design`` for a number the evidence does not give.

- Cut progression (MAINT-02, MAINT-06; optional PROG-03): a final ``increase_load`` or
  ``add_reps`` becomes ``maintain_load`` at the last recorded work load and reps; the gain-mode
  target stays as an optional target. Set counts, exercises and the focus never change.
- Everything else is display only: it never changes the plan.
- Missing is not zero: one InBody point, no weight, a night without sleep data or a start time
  without a zone gives ``unknown``, never 0 and never "short".
- Body-composition values are used for rates and flags only; the report holds no measured kg
  (user decision D1, 2026-10-26), apart from the user's own entered floor and target.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_EVEN, Decimal

from muscle50.domain.activity import ActivityType, NormalizedActivity
from muscle50.domain.analytics import activity_local_date
from muscle50.domain.body_composition_trend import (
    InvalidStoredMeasurementError,
    StoredBodyComposition,
    TrendMetric,
    metric_points,
)
from muscle50.domain.exercise_taxonomy import EXERCISE_RULES, MuscleGroup, UnmappedReason, classify_strength_set
from muscle50.domain.recovery import DailyRecovery
from muscle50.domain.strength_recommendation import (
    REGION_MUSCLES,
    REGION_SESSION_MIN_SETS,
    ProgressionAction,
    Region,
    StrengthRecommendation,
    kg_text,
    strength_history,
)
from muscle50.domain.training_goal import GoalMode, SleepThresholdSetting, TrainingGoal, WeeklyRateRange

GOAL_MODE_VERSION = 1
# VOL-04: ACSM 2026, hypertrophy improves with >= 10 sets per muscle per week (VOL-01's 5/10 bands
# are not established, so VOL-01 is not the source of this number).
WEEKLY_SETS_THRESHOLD = 10
# VOL-02: an indirect (secondary-muscle) set counts as half a set ("fractional" counting).
SECONDARY_SET_WEIGHT = 0.5
# Design choice inside the evidence range 2-6 h (CONC-03 Petre 2 h, CONC-04 Schumann 3 h, Robineau 6 h).
RUN_LEGS_GAP_HOURS = 3
# SLEEP-05: the only number the evidence gives is the health target of >= 7 h per night.
SHORT_NIGHT_HOURS = 7
SLEEP_WINDOW_DAYS = 7
# Design: the weight rate compares the latest weight with the latest earlier weight at least this many
# days before it (InBody is measured every 2-4 weeks; a shorter interval is mostly day-to-day noise).
MIN_RATE_INTERVAL_DAYS = 7
WEEKLY_SETS_WINDOW_DAYS = 7
RUN_LEGS_WINDOW_DAYS = 7
# MAINT-05: 0.5-1 % of body weight per week is the recommended loss; > 1 %/week may not favour muscle.
EVIDENCE_LOSS_RANGE = WeeklyRateRange(Decimal("0.5"), Decimal("1.0"))
# PRO-05: 2.3-3.1 g protein per kg fat-free mass per day during a deficit (Helms 2014).
PROTEIN_G_PER_KG_FAT_FREE_MASS = (Decimal("2.3"), Decimal("3.1"))
# PRO-04: keep the energy deficit at or under about 500 kcal/day.
DEFICIT_LIMIT_KCAL = 500
HUNDREDTH = Decimal("0.01")

PROGRESSION_EVIDENCE = ("MAINT-02", "MAINT-06", "PROG-03")
WEEKLY_SETS_EVIDENCE = ("VOL-04", "VOL-02")
WEIGHT_CHANGE_EVIDENCE = ("MAINT-05", "design")
DESIGN_EVIDENCE = ("design",)
RUN_LEGS_EVIDENCE = ("CONC-03", "CONC-04", "design")
RUN_LEGS_ADVICE_EVIDENCE = ("CONC-05",)
SLEEP_EVIDENCE = ("SLEEP-05",)
SLEEP_RULES_EVIDENCE = ("design", "SLEEP-05")

LEG_MUSCLES = frozenset(REGION_MUSCLES[Region.LEGS])
# Muscles a taxonomy rule trains as primary or secondary; any other muscle can never have a counted set.
COUNTABLE_MUSCLES = frozenset(
    {rule.primary_muscle for rule in EXERCISE_RULES}
    | {muscle for rule in EXERCISE_RULES for muscle in rule.secondary_muscles}
)


@dataclass(frozen=True)
class CutProgressionChange:
    """One exercise whose progression the cut goal turned into ``maintain_load``."""

    label: str
    load_kg: float | None
    target_reps: int | None
    optional_action: ProgressionAction
    """The gain-mode target, kept as optional: ``increase_load`` or ``add_reps``."""
    optional_load_kg: float | None
    optional_load_increase_from_kg: float | None
    optional_load_step: str | None
    optional_target_reps: int | None
    evidence: tuple[str, ...] = PROGRESSION_EVIDENCE


@dataclass(frozen=True)
class MuscleWeeklySets:
    muscle: str
    direct_sets: int
    """Sets with this primary muscle (counted 1)."""
    indirect_sets: int
    """Sets listing this muscle as secondary (counted 0.5, VOL-02)."""
    fractional_sets: float
    below_threshold: bool | None
    """None when no taxonomy rule trains the muscle (not countable; unknown, not 0)."""
    countable: bool


@dataclass(frozen=True)
class WeeklySets:
    from_date: date
    to_date: date
    muscles: tuple[MuscleWeeklySets, ...]
    unknown_sets: int
    no_rule_sets: int
    threshold: int = WEEKLY_SETS_THRESHOLD
    secondary_weight: float = SECONDARY_SET_WEIGHT
    evidence: tuple[str, ...] = WEEKLY_SETS_EVIDENCE

    @property
    def lower_bound(self) -> bool:
        """UNKNOWN or rule-less sets were left out, so every count may be too low."""
        return self.unknown_sets + self.no_rule_sets > 0


@dataclass(frozen=True)
class WeightChange:
    status: str
    """``known`` or ``unknown``."""
    from_date: date | None
    to_date: date | None
    days: int | None
    percent_per_week: Decimal | None
    """Unrounded; negative is a loss. Displayed at 0.01 (HALF_EVEN)."""
    flags: tuple[str, ...]
    """Cut only: ``faster_than_evidence``, ``outside_user_target``, ``gaining``."""
    latest_measurement_date: date | None
    days_since_latest_measurement: int | None
    evidence_range: WeeklyRateRange | None
    """MAINT-05's 0.5-1.0 %/week loss, cut only."""
    reason: str | None = None
    evidence: tuple[str, ...] = WEIGHT_CHANGE_EVIDENCE


@dataclass(frozen=True)
class SmmFloor:
    status: str
    """``below``, ``at_or_above``, ``unknown`` or ``not_set``."""
    floor_kg: Decimal | None
    measurement_date: date | None
    evidence: tuple[str, ...] = DESIGN_EVIDENCE


@dataclass(frozen=True)
class GoalProgressRate:
    status: str
    """``known``, ``reached``, ``deadline_passed``, ``unknown`` or ``not_set``."""
    required_percent_per_week: Decimal | None
    actual_percent_per_week: Decimal | None
    measurement_date: date | None
    assumption: str | None
    """``fat_free_mass_constant`` for a body-fat target (design)."""
    reason: str | None = None
    evidence: tuple[str, ...] = DESIGN_EVIDENCE


@dataclass(frozen=True)
class RunLegsPair:
    local_date: date
    run_activity_id: str
    strength_activity_id: str
    run_local_time: str | None
    strength_local_time: str | None
    gap_minutes: int | None
    """None when a start time has no zone or cannot be read (gap unknown, never flagged)."""
    order: str
    """``run_first``, ``legs_first``, ``same_start`` or ``unknown``."""
    under_threshold: bool | None
    advice: str | None
    """``lift_first`` when the run came first and the gap is under the threshold."""
    advice_evidence: tuple[str, ...]


@dataclass(frozen=True)
class RunLegsReport:
    from_date: date
    to_date: date
    pairs: tuple[RunLegsPair, ...]
    gap_threshold_hours: int = RUN_LEGS_GAP_HOURS
    evidence: tuple[str, ...] = RUN_LEGS_EVIDENCE


@dataclass(frozen=True)
class ShortSleepReport:
    from_date: date
    to_date: date
    nights_under: int
    nights_with_data: int
    nights_without_data: int
    rules: SleepThresholdSetting
    threshold_hours: int = SHORT_NIGHT_HOURS
    evidence: tuple[str, ...] = SLEEP_EVIDENCE


@dataclass(frozen=True)
class GoalModeReport:
    goal: TrainingGoal
    progression: tuple[CutProgressionChange, ...]
    weekly_sets: WeeklySets
    weight_change: WeightChange
    smm_floor: SmmFloor
    goal_progress: GoalProgressRate
    run_legs: RunLegsReport
    sleep: ShortSleepReport


@dataclass(frozen=True)
class CutNutritionReference:
    """PRO-05 protein range from fat-free mass, and the PRO-04 deficit limit (text only)."""

    status: str
    """``known`` or ``unknown``."""
    protein_min_g: Decimal | None
    protein_max_g: Decimal | None
    measurement_date: date | None
    reason: str | None = None


# --- cut progression -------------------------------------------------------------------------


def apply_cut_progression(
    strength: StrengthRecommendation,
) -> tuple[StrengthRecommendation, tuple[CutProgressionChange, ...]]:
    """Keep the last load and reps instead of increasing them; only progression targets change.

    Applies after every other rule: a regression, recovery or rest-rule ``maintain`` and
    ``establish_baseline`` are already final, and a label without a recorded load (bodyweight
    ``add_reps``) keeps its rep target because there is no load to keep.
    """
    changes: list[CutProgressionChange] = []
    exercises = []
    for exercise in strength.exercises:
        progression = exercise.progression
        last = progression.recent[-1] if progression.recent else None
        if (
            progression.action not in (ProgressionAction.INCREASE_LOAD, ProgressionAction.ADD_REPS)
            or last is None
            or not last.load_recorded
            or last.work_load_kg is None
        ):
            exercises.append(exercise)
            continue
        best = last.best_reps
        reps = min(best, progression.rep_range.maximum) if best is not None else None
        kept = f"{kg_text(last.work_load_kg)} x {reps if reps is not None else '-'}"
        maintained = replace(
            progression,
            action=ProgressionAction.MAINTAIN_LOAD,
            load_kg=last.work_load_kg,
            target_reps=reps,
            load_increase_from_kg=None,
            load_step=None,
            basis=(
                *progression.basis,
                f"cut goal (user setting): keep {kept} instead of {progression.action.value}; that target is "
                "optional [MAINT-02, MAINT-06; optional PROG-03]",
            ),
        )
        exercises.append(replace(exercise, progression=maintained))
        changes.append(
            CutProgressionChange(
                label=exercise.label,
                load_kg=last.work_load_kg,
                target_reps=reps,
                optional_action=progression.action,
                optional_load_kg=progression.load_kg,
                optional_load_increase_from_kg=progression.load_increase_from_kg,
                optional_load_step=progression.load_step,
                optional_target_reps=progression.target_reps,
            )
        )
    return replace(strength, exercises=tuple(exercises)), tuple(changes)


# --- weekly sets per muscle (display only) -----------------------------------------------------


def weekly_muscle_sets(as_of: date, activities: Sequence[NormalizedActivity]) -> WeeklySets:
    """Fractional sets per muscle over D-7..D-1, the window of the plan's ``sets_last_7_days``."""
    start, end = as_of - timedelta(days=WEEKLY_SETS_WINDOW_DAYS), as_of - timedelta(days=1)
    direct: Counter[MuscleGroup] = Counter()
    indirect: Counter[MuscleGroup] = Counter()
    unknown = no_rule = 0
    for _day, activity in strength_history(activities, start, end):
        for strength_set in activity.strength_sets:
            if strength_set.set_type != "ACTIVE":
                continue
            classification = classify_strength_set(strength_set)
            if classification.unmapped_reason is UnmappedReason.UNKNOWN_SOURCE_LABEL:
                unknown += 1
            elif classification.unmapped_reason is UnmappedReason.NO_RULE:
                no_rule += 1
            rule = classification.rule
            if rule is None:
                continue
            direct[rule.primary_muscle] += 1
            for muscle in rule.secondary_muscles:
                indirect[muscle] += 1
    muscles = []
    for region_muscles in REGION_MUSCLES.values():
        for muscle in region_muscles:
            countable = muscle in COUNTABLE_MUSCLES
            fractional = direct[muscle] + SECONDARY_SET_WEIGHT * indirect[muscle]
            muscles.append(
                MuscleWeeklySets(
                    muscle=muscle.value,
                    direct_sets=direct[muscle],
                    indirect_sets=indirect[muscle],
                    fractional_sets=fractional,
                    below_threshold=fractional < WEEKLY_SETS_THRESHOLD if countable else None,
                    countable=countable,
                )
            )
    return WeeklySets(start, end, tuple(muscles), unknown, no_rule)


# --- InBody rates and flags (display only) -----------------------------------------------------

type Points = dict[TrendMetric, dict[date, Decimal]]


def weight_change(goal: TrainingGoal, points: Points | None, as_of: date, unavailable: str | None) -> WeightChange:
    cut = goal.mode is GoalMode.CUT
    evidence_range = EVIDENCE_LOSS_RANGE if cut else None
    latest = max((day for series in points.values() for day in series), default=None) if points else None
    since = (as_of - latest).days if latest is not None else None

    def unknown(reason: str) -> WeightChange:
        return WeightChange("unknown", None, None, None, None, (), latest, since, evidence_range, reason)

    if points is None:
        return unknown(unavailable or "InBody data unavailable")
    weights = points[TrendMetric.WEIGHT_KG]
    if not weights:
        return unknown(f"no InBody weight on or before {as_of.isoformat()}")
    to_date = max(weights)
    earlier = [day for day in weights if day <= to_date - timedelta(days=MIN_RATE_INTERVAL_DAYS)]
    if not earlier:
        return unknown(
            f"no InBody weight at least {MIN_RATE_INTERVAL_DAYS} days before the latest ({to_date.isoformat()})"
        )
    from_date = max(earlier)
    days = (to_date - from_date).days
    rate = (weights[to_date] - weights[from_date]) / weights[from_date] * Decimal(7) / Decimal(days) * Decimal(100)
    flags: list[str] = []
    if cut:
        loss = -rate
        if loss > EVIDENCE_LOSS_RANGE.maximum:
            flags.append("faster_than_evidence")
        target = goal.weekly_loss_percent
        if target is not None and not target.minimum <= loss <= target.maximum:
            flags.append("outside_user_target")
        if rate > 0:
            flags.append("gaining")
    return WeightChange("known", from_date, to_date, days, rate, tuple(flags), latest, since, evidence_range)


def smm_floor(goal: TrainingGoal, points: Points | None) -> SmmFloor:
    floor = goal.min_skeletal_muscle_mass_kg
    if floor is None:
        return SmmFloor("not_set", None, None)
    series = points[TrendMetric.SKELETAL_MUSCLE_MASS_KG] if points is not None else {}
    if not series:
        return SmmFloor("unknown", floor, None)
    day = max(series)
    return SmmFloor("below" if series[day] < floor else "at_or_above", floor, day)


def goal_progress(goal: TrainingGoal, points: Points | None, as_of: date, actual: Decimal | None) -> GoalProgressRate:
    """The weekly rate the deadline needs (design: fat-free mass assumed constant for a body-fat target)."""
    body_fat = goal.target_body_fat_percent
    assumption = "fat_free_mass_constant" if body_fat is not None else None

    def result(
        status: str, required: Decimal | None = None, day: date | None = None, reason: str | None = None
    ) -> GoalProgressRate:
        return GoalProgressRate(status, required, actual, day, assumption, reason)

    if (body_fat is None and goal.target_weight_kg is None) or goal.target_date is None:
        return result(
            "not_set", reason="needs a target and a deadline (goal set --target-body-fat/--target-weight --by)"
        )
    if goal.target_date <= as_of:
        return result("deadline_passed", reason=f"the deadline {goal.target_date.isoformat()} has passed")
    if points is None:
        return result("unknown", reason="InBody data unavailable")
    weights = points[TrendMetric.WEIGHT_KG]
    if body_fat is not None:
        fat = points[TrendMetric.BODY_FAT_MASS_KG]
        both = sorted(set(weights) & set(fat))
        if not both:
            return result("unknown", reason="no InBody date with both weight and body fat mass")
        day = both[-1]
        fat_free = weights[day] - fat[day]
        if fat_free <= 0:
            return result("unknown", day=day, reason="the stored body fat mass is not below the weight")
        target_weight = fat_free / (1 - body_fat / 100)
    else:
        if not weights:
            return result("unknown", reason="no InBody weight")
        day = max(weights)
        assert goal.target_weight_kg is not None
        target_weight = goal.target_weight_kg
    current = weights[day]
    if (goal.mode is GoalMode.CUT and target_weight >= current) or (
        goal.mode is GoalMode.GAIN and target_weight <= current
    ):
        return result("reached", day=day)
    weeks = Decimal((goal.target_date - as_of).days) / Decimal(7)
    required = (target_weight / current - 1) / weeks * Decimal(100)
    return result("known", required, day)


def fat_free_mass(points: Points) -> tuple[date, Decimal] | None:
    """Weight minus body fat mass on the latest date that has both (design; FFM is not a stored column)."""
    weights, fat = points[TrendMetric.WEIGHT_KG], points[TrendMetric.BODY_FAT_MASS_KG]
    both = sorted(set(weights) & set(fat))
    if not both:
        return None
    day = both[-1]
    value = weights[day] - fat[day]
    return (day, value) if value > 0 else None


def cut_nutrition_reference(
    rows: Sequence[StoredBodyComposition] | None, as_of: date, unavailable: str | None = None
) -> CutNutritionReference:
    """PRO-05 protein grams from the latest fat-free mass on or before ``as_of`` (whole grams, HALF_EVEN)."""
    if rows is None:
        return CutNutritionReference("unknown", None, None, None, unavailable or "InBody data unavailable")
    try:
        points = metric_points(rows, to_date=as_of)
    except InvalidStoredMeasurementError:
        return CutNutritionReference("unknown", None, None, None, "a stored InBody measurement cannot be read")
    found = fat_free_mass(points)
    if found is None:
        return CutNutritionReference(
            "unknown", None, None, None, "no InBody date with both weight and body fat mass on or before this date"
        )
    day, mass = found
    low, high = PROTEIN_G_PER_KG_FAT_FREE_MASS
    whole = Decimal(1)
    return CutNutritionReference(
        "known",
        (mass * low).quantize(whole, rounding=ROUND_HALF_EVEN),
        (mass * high).quantize(whole, rounding=ROUND_HALF_EVEN),
        day,
    )


# --- run and legs on the same day (display only) -----------------------------------------------


def run_legs_pairs(as_of: date, activities: Sequence[NormalizedActivity]) -> RunLegsReport:
    """Runs and legs sessions on the same local date in D-7..D, with the gap between their starts."""
    start = as_of - timedelta(days=RUN_LEGS_WINDOW_DAYS)
    runs: dict[date, list[NormalizedActivity]] = {}
    legs: dict[date, list[NormalizedActivity]] = {}
    for activity in activities:
        day = activity_local_date(activity)
        if day is None or not start <= day <= as_of:
            continue
        if activity.canonical_type is ActivityType.RUNNING:
            runs.setdefault(day, []).append(activity)
        elif activity.canonical_type is ActivityType.STRENGTH and _legs_sets(activity) >= REGION_SESSION_MIN_SETS:
            legs.setdefault(day, []).append(activity)
    pairs = [
        _pair(day, run, session)
        for day in sorted(set(runs) & set(legs))
        for run in sorted(runs[day], key=_start_key)
        for session in sorted(legs[day], key=_start_key)
    ]
    return RunLegsReport(start, as_of, tuple(pairs))


def _legs_sets(activity: NormalizedActivity) -> int:
    count = 0
    for strength_set in activity.strength_sets:
        if strength_set.set_type != "ACTIVE":
            continue
        rule = classify_strength_set(strength_set).rule
        if rule is not None and rule.primary_muscle in LEG_MUSCLES:
            count += 1
    return count


def _start_key(activity: NormalizedActivity) -> tuple[str, str]:
    return (activity.started_at_local or "", activity.source_activity_id)


def _pair(day: date, run: NormalizedActivity, session: NormalizedActivity) -> RunLegsPair:
    run_start, legs_start = _aware(run.started_at_utc), _aware(session.started_at_utc)
    run_local, legs_local = _local(run.started_at_local), _local(session.started_at_local)
    gap: int | None = None
    under: bool | None = None
    if run_start is not None and legs_start is not None:
        delta = abs(legs_start - run_start)
        gap = int(delta.total_seconds() // 60)
        under = delta < timedelta(hours=RUN_LEGS_GAP_HOURS)
        order = "run_first" if run_start < legs_start else "legs_first" if legs_start < run_start else "same_start"
    else:
        order = "unknown"
        if run_local is not None and legs_local is not None:
            order = "run_first" if run_local < legs_local else "legs_first" if legs_local < run_local else "same_start"
    advice = "lift_first" if under and order == "run_first" else None
    return RunLegsPair(
        local_date=day,
        run_activity_id=run.source_activity_id,
        strength_activity_id=session.source_activity_id,
        run_local_time=run_local.strftime("%H:%M") if run_local is not None else None,
        strength_local_time=legs_local.strftime("%H:%M") if legs_local is not None else None,
        gap_minutes=gap,
        order=order,
        under_threshold=under,
        advice=advice,
        advice_evidence=RUN_LEGS_ADVICE_EVIDENCE if advice is not None else (),
    )


def _aware(text: str | None) -> datetime | None:
    """A stored UTC start with an explicit offset; a naive or unreadable time is not guessed."""
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None and parsed.utcoffset() is not None else None


def _local(text: str | None) -> datetime | None:
    if not text:
        return None
    try:
        return datetime.fromisoformat(text).replace(tzinfo=None)
    except ValueError:
        return None


# --- nights under 7 h (display only) -------------------------------------------------------------


def short_sleep_nights(
    as_of: date, recoveries: Sequence[DailyRecovery], setting: SleepThresholdSetting
) -> ShortSleepReport:
    """Nights ending D-6..D under 7 h; a night without a sleep value is counted apart, never as short."""
    by_date = {item.calendar_date: item for item in recoveries}
    start = as_of - timedelta(days=SLEEP_WINDOW_DAYS - 1)
    under = with_data = 0
    for offset in range(SLEEP_WINDOW_DAYS):
        row = by_date.get((start + timedelta(days=offset)).isoformat())
        seconds = row.sleep_seconds if row is not None else None
        if seconds is None:
            continue
        with_data += 1
        if seconds < SHORT_NIGHT_HOURS * 3600:
            under += 1
    return ShortSleepReport(start, as_of, under, with_data, SLEEP_WINDOW_DAYS - with_data, setting)


# --- the report --------------------------------------------------------------------------------


def build_goal_mode_report(
    goal: TrainingGoal,
    as_of: date,
    activities: Sequence[NormalizedActivity],
    recoveries: Sequence[DailyRecovery],
    progression: tuple[CutProgressionChange, ...],
    body_composition: Sequence[StoredBodyComposition] | None,
    body_composition_error: str | None,
    sleep: SleepThresholdSetting,
) -> GoalModeReport:
    """``body_composition`` None means the InBody rows could not be read (``body_composition_error`` says why)."""
    points: Points | None = None
    unavailable = f"InBody data unavailable: {body_composition_error}" if body_composition_error else None
    if body_composition is not None:
        try:
            points = metric_points(body_composition, to_date=as_of)
        except InvalidStoredMeasurementError:
            unavailable = "InBody data unavailable: a stored InBody measurement cannot be read"
    change = weight_change(goal, points, as_of, unavailable)
    return GoalModeReport(
        goal=goal,
        progression=progression,
        weekly_sets=weekly_muscle_sets(as_of, activities),
        weight_change=change,
        smm_floor=smm_floor(goal, points),
        goal_progress=goal_progress(goal, points, as_of, change.percent_per_week),
        run_legs=run_legs_pairs(as_of, activities),
        sleep=short_sleep_nights(as_of, recoveries, sleep),
    )


def percent_text(value: Decimal | None) -> str | None:
    """A rate at 0.01 %/week (HALF_EVEN), without a "-0.00"."""
    if value is None:
        return None
    rounded = value.quantize(HUNDREDTH, rounding=ROUND_HALF_EVEN)
    return format(rounded.copy_abs() if rounded == 0 else rounded, "f")
