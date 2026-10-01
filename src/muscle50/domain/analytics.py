"""Deterministic rolling training snapshot built only from canonical data.

This module aggregates; it does not score, recommend, repair, or estimate. Rules:

- Missing is never zero. Every aggregate carries the source activity IDs (or recovery
  dates) that contributed and the ones whose value was missing; an aggregate with no
  contributing values is ``None``.
- Each metric has one explicit aggregation rule (``LOAD_METRIC_AGGREGATION``). Additive
  quantities are summed; bounded per-session scores are never summed or averaged.
- Garmin summary-level values are reported exactly as stored. Swim lap/length detail is
  checked for physical plausibility; implausible detail is excluded only from
  detail-derived values and is always reported as a quality issue, never repaired.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from enum import StrEnum

from muscle50.domain.activity import ActivityType, NormalizedActivity, StrengthSet
from muscle50.domain.activity_load import ACTIVITY_LOAD_METRICS
from muscle50.domain.activity_review import derive_activity_review
from muscle50.domain.exercise_taxonomy import (
    TAXONOMY_VERSION,
    ExerciseClassification,
    LabelOrigin,
    UnmappedReason,
    classify_strength_set,
    label_origin,
)
from muscle50.domain.recovery import DailyRecovery
from muscle50.domain.swimming import derive_lap_metrics, derive_length_metrics

ANALYTICS_VERSION = 1
DEFAULT_LOOKBACK_DAYS = 7
MAX_LOOKBACK_DAYS = 90

# Data-quality bound, not a physiological model: the long-course 50 m freestyle world
# record averages about 2.39 m/s including the dive start. A lap or length faster than
# this is a device segmentation/timing artifact, whatever the swimmer's ability.
MAX_PLAUSIBLE_SWIM_SPEED_MPS = 2.5

# Summary distance and the sum of lap distances are compared with this tolerance to decide
# whether Garmin's summary distance already includes implausible lap distance.
_DISTANCE_MATCH_TOLERANCE_METERS = 0.5


class InvalidSnapshotWindowError(ValueError):
    """Raised when a snapshot window cannot be built from the requested parameters."""


class AggregationRule(StrEnum):
    # Additive quantity over the window (durations, minutes, load points).
    SUM = "sum"
    # Bounded per-session score; the window reports the highest single session.
    MAX = "max"


# Every canonical activity-load metric has exactly one explicit rule. Per-activity values
# are always kept alongside the aggregate, so "per activity" is available for all of them.
# training_load is summed as a plain window total; it is NOT Garmin's exponentially
# weighted acute load. Intensity minutes are raw values; vigorous minutes are not doubled.
LOAD_METRIC_AGGREGATION: Mapping[str, AggregationRule] = {
    "training_load": AggregationRule.SUM,
    "aerobic_training_effect": AggregationRule.MAX,
    "anaerobic_training_effect": AggregationRule.MAX,
    "hr_time_in_zone_1_seconds": AggregationRule.SUM,
    "hr_time_in_zone_2_seconds": AggregationRule.SUM,
    "hr_time_in_zone_3_seconds": AggregationRule.SUM,
    "hr_time_in_zone_4_seconds": AggregationRule.SUM,
    "hr_time_in_zone_5_seconds": AggregationRule.SUM,
    "moderate_intensity_minutes": AggregationRule.SUM,
    "vigorous_intensity_minutes": AggregationRule.SUM,
}


class RecoveryRule(StrEnum):
    # Measured for each day: latest plus mean/min/max over days that have a value.
    DAILY = "daily"
    # Already a rolling or forward-looking state: only the latest value is meaningful.
    STATE = "state"


@dataclass(frozen=True)
class RecoveryFieldSpec:
    field: str
    unit: str | None
    rule: RecoveryRule


RECOVERY_NUMERIC_FIELDS: tuple[RecoveryFieldSpec, ...] = (
    RecoveryFieldSpec("sleep_seconds", "s", RecoveryRule.DAILY),
    RecoveryFieldSpec("deep_sleep_seconds", "s", RecoveryRule.DAILY),
    RecoveryFieldSpec("light_sleep_seconds", "s", RecoveryRule.DAILY),
    RecoveryFieldSpec("rem_sleep_seconds", "s", RecoveryRule.DAILY),
    RecoveryFieldSpec("awake_sleep_seconds", "s", RecoveryRule.DAILY),
    RecoveryFieldSpec("sleep_score", "score", RecoveryRule.DAILY),
    RecoveryFieldSpec("sleep_avg_hrv_ms", "ms", RecoveryRule.DAILY),
    RecoveryFieldSpec("hrv_last_night_avg_ms", "ms", RecoveryRule.DAILY),
    RecoveryFieldSpec("hrv_weekly_avg_ms", "ms", RecoveryRule.STATE),
    RecoveryFieldSpec("resting_heart_rate_bpm", "bpm", RecoveryRule.DAILY),
    RecoveryFieldSpec("body_battery_high", "score", RecoveryRule.DAILY),
    RecoveryFieldSpec("body_battery_low", "score", RecoveryRule.DAILY),
    RecoveryFieldSpec("stress_average", "score", RecoveryRule.DAILY),
    RecoveryFieldSpec("training_readiness_score", "score", RecoveryRule.DAILY),
    RecoveryFieldSpec("recovery_time_minutes", "min", RecoveryRule.STATE),
    RecoveryFieldSpec("respiration_avg_brpm", "brpm", RecoveryRule.DAILY),
)

RECOVERY_CATEGORICAL_FIELDS: tuple[str, ...] = (
    "training_status_key",
    "hrv_status",
    "training_readiness_level",
    "recovery_time_change_phrase",
)


class QualityIssueCode(StrEnum):
    UNDATED_ACTIVITY = "undated_activity"
    NON_NUMERIC_LOAD_METRIC = "non_numeric_load_metric"
    STRENGTH_SET_DETAIL_MISSING = "strength_set_detail_missing"
    STRENGTH_UNCLASSIFIED_EXERCISE = "strength_unclassified_exercise"
    STRENGTH_UNMAPPED_EXERCISE = "strength_unmapped_exercise"
    STRENGTH_NEGATIVE_WEIGHT = "strength_negative_weight"
    STRENGTH_MISSING_REPS = "strength_missing_reps"
    SWIM_DETAIL_MISSING = "swim_detail_missing"
    SWIM_LAP_IMPLAUSIBLE_SPEED = "swim_lap_implausible_speed"
    SWIM_SUMMARY_DISTANCE_INCLUDES_IMPLAUSIBLE_LAPS = "swim_summary_distance_includes_implausible_laps"
    SWIM_LAP_LENGTH_DISTANCE_MISMATCH = "swim_lap_length_distance_mismatch"
    SWIM_LENGTH_IMPLAUSIBLE_SPEED = "swim_length_implausible_speed"


@dataclass(frozen=True)
class QualityIssue:
    code: QualityIssueCode
    source_activity_id: str | None
    detail: str
    lap_sequences: tuple[int, ...] = ()
    set_sequences: tuple[int, ...] = ()


@dataclass(frozen=True)
class SnapshotWindow:
    """Inclusive local calendar-date window ending on ``as_of``."""

    as_of: date
    lookback_days: int
    start: date

    @property
    def dates(self) -> tuple[date, ...]:
        return tuple(self.start + timedelta(days=offset) for offset in range(self.lookback_days))

    def contains(self, day: date) -> bool:
        return self.start <= day <= self.as_of


def snapshot_window(as_of: date, lookback_days: int = DEFAULT_LOOKBACK_DAYS) -> SnapshotWindow:
    if isinstance(lookback_days, bool) or not 1 <= lookback_days <= MAX_LOOKBACK_DAYS:
        raise InvalidSnapshotWindowError(f"lookback days must be between 1 and {MAX_LOOKBACK_DAYS}")
    return SnapshotWindow(as_of=as_of, lookback_days=lookback_days, start=as_of - timedelta(days=lookback_days - 1))


@dataclass(frozen=True)
class SourceValue:
    source_id: str
    value: float


@dataclass(frozen=True)
class MetricAggregate:
    """One window aggregate with full provenance.

    ``values`` lists every contributing (source, value) pair, so per-activity values are
    always recoverable. ``missing_source_ids`` lists sources that had no usable value.
    """

    key: str
    unit: str | None
    rule: AggregationRule
    value: float | None
    values: tuple[SourceValue, ...]
    missing_source_ids: tuple[str, ...]


@dataclass(frozen=True)
class ActivityTypeCount:
    canonical_type: str
    source_type_key: str
    count: int
    source_activity_ids: tuple[str, ...]


@dataclass(frozen=True)
class ActivityOverview:
    activity_count: int
    source_activity_ids: tuple[str, ...]
    training_dates: tuple[date, ...]
    by_type: tuple[ActivityTypeCount, ...]
    elapsed_seconds: MetricAggregate
    load_metrics: tuple[MetricAggregate, ...]


@dataclass(frozen=True)
class VolumeExclusions:
    """ACTIVE sets that could not contribute to volume, by first failing reason."""

    missing_reps: int
    zero_reps: int
    missing_weight: int
    negative_weight: int
    zero_weight: int


@dataclass(frozen=True)
class ExerciseAggregate:
    exercise_key: str | None
    category: str | None
    display_name: str | None
    classified: bool
    active_set_count: int
    reps: int | None
    sets_missing_reps: int
    volume_kg: float | None
    volume_set_count: int
    max_weight_kg: float | None
    source_activity_ids: tuple[str, ...]


@dataclass(frozen=True)
class SetRef:
    source_activity_id: str
    sequence: int


@dataclass(frozen=True)
class LabelOriginCounts:
    """How the Garmin labels behind a count were produced (counts only, never a weight)."""

    confirmed: int
    auto_detected: int
    unspecified: int


@dataclass(frozen=True)
class TaxonomyGroup:
    """ACTIVE sets that share one taxonomy value, with set-level provenance."""

    key: str
    active_set_count: int
    label_origins: LabelOriginCounts
    source_activity_ids: tuple[str, ...]
    sets: tuple[SetRef, ...]


@dataclass(frozen=True)
class TaxonomyExerciseGroup:
    """ACTIVE sets of one original Garmin label, exactly as stored, with its taxonomy.

    Mapped labels carry a movement pattern, primary and secondary muscles, and the mapping
    basis; unmapped labels (UNKNOWN or without a rule) carry ``unmapped_reason`` instead.
    """

    category: str | None
    exercise_name: str | None
    movement_pattern: str | None
    primary_muscle: str | None
    secondary_muscles: tuple[str, ...]
    mapping_basis: str | None
    unmapped_reason: str | None
    active_set_count: int
    label_origins: LabelOriginCounts
    source_activity_ids: tuple[str, ...]
    sets: tuple[SetRef, ...]


@dataclass(frozen=True)
class StrengthTaxonomySummary:
    """ACTIVE sets by exercise taxonomy.

    ``by_exercise`` has one entry per original Garmin label (mapped or not) and sums to
    ``active_set_count``. ``by_movement_pattern`` and ``by_primary_muscle`` count every mapped
    ACTIVE set exactly once, so each sums to ``mapped_active_set_count``; together with
    ``unmapped_active_set_count`` they reconcile to ``active_set_count``.
    ``secondary_muscle_set_exposures`` counts, per muscle, the ACTIVE sets that list it as a
    secondary muscle. Exposures are not sets of their own: they are never added to primary
    totals and do not sum to anything meaningful across muscles.
    """

    taxonomy_version: int
    active_set_count: int
    mapped_active_set_count: int
    unmapped_active_set_count: int
    unknown_active_set_count: int
    unknown_source_activity_ids: tuple[str, ...]
    no_rule_active_set_count: int
    mapped_label_origins: LabelOriginCounts
    by_exercise: tuple[TaxonomyExerciseGroup, ...]
    by_movement_pattern: tuple[TaxonomyGroup, ...]
    by_primary_muscle: tuple[TaxonomyGroup, ...]
    secondary_muscle_set_exposures: tuple[TaxonomyGroup, ...]


@dataclass(frozen=True)
class StrengthSessionSummary:
    source_activity_id: str
    local_date: date
    set_detail_available: bool
    active_set_count: int
    reps: int | None
    sets_missing_reps: int
    volume_kg: float | None
    volume_set_count: int


@dataclass(frozen=True)
class StrengthSummary:
    session_count: int
    source_activity_ids: tuple[str, ...]
    set_row_count: int
    rest_set_count: int
    active_set_count: int
    reps: int | None
    sets_missing_reps: int
    zero_rep_sets: int
    volume_kg: float | None
    volume_set_count: int
    volume_exclusions: VolumeExclusions
    unclassified_active_set_count: int
    exercises: tuple[ExerciseAggregate, ...]
    sessions: tuple[StrengthSessionSummary, ...]
    load_metrics: tuple[MetricAggregate, ...]
    taxonomy: StrengthTaxonomySummary


@dataclass(frozen=True)
class SwimSessionSummary:
    source_activity_id: str
    local_date: date
    # Garmin summary level (activities row / swim_activities), reported as stored.
    summary_distance_meters: float | None
    elapsed_seconds: float | None
    moving_seconds: float | None
    pool_length_meters: float | None
    # Lap/length detail level.
    detail_available: bool
    lap_count: int
    length_count: int
    swimming_length_count: int
    detail_distance_meters: float | None
    implausible_lap_sequences: tuple[int, ...]
    implausible_lap_distance_meters: float
    plausible_detail_distance_meters: float | None
    implausible_length_count: int
    summary_distance_includes_implausible_laps: bool


@dataclass(frozen=True)
class SwimmingSummary:
    session_count: int
    source_activity_ids: tuple[str, ...]
    summary_distance_meters: MetricAggregate
    elapsed_seconds: MetricAggregate
    moving_seconds: MetricAggregate
    pool_lengths_meters: tuple[float, ...]
    detail_distance_meters: MetricAggregate
    plausible_detail_distance_meters: MetricAggregate
    implausible_lap_count: int
    implausible_length_count: int
    sessions: tuple[SwimSessionSummary, ...]
    load_metrics: tuple[MetricAggregate, ...]


@dataclass(frozen=True)
class RecoveryFieldAggregate:
    field: str
    unit: str | None
    rule: RecoveryRule
    latest_value: float | None
    latest_date: date | None
    mean: float | None
    minimum: float | None
    maximum: float | None
    available_dates: tuple[date, ...]
    null_dates: tuple[date, ...]


@dataclass(frozen=True)
class DatedText:
    calendar_date: date
    value: str


@dataclass(frozen=True)
class RecoveryCategoricalField:
    field: str
    latest_value: str | None
    latest_date: date | None
    values: tuple[DatedText, ...]
    null_dates: tuple[date, ...]


@dataclass(frozen=True)
class RecoverySummary:
    requested_day_count: int
    dates_with_row: tuple[date, ...]
    dates_without_row: tuple[date, ...]
    numeric_fields: tuple[RecoveryFieldAggregate, ...]
    categorical_fields: tuple[RecoveryCategoricalField, ...]
    days: tuple[DailyRecovery, ...]


@dataclass(frozen=True)
class TrainingSnapshot:
    analytics_version: int
    window: SnapshotWindow
    activities: ActivityOverview
    strength: StrengthSummary
    swimming: SwimmingSummary
    recovery: RecoverySummary
    quality_issues: tuple[QualityIssue, ...]


def activity_local_date(activity: NormalizedActivity) -> date | None:
    """Garmin's local start date, read from the stored local timestamp without zoneinfo."""
    text = activity.started_at_local
    if not text:
        return None
    try:
        return datetime.fromisoformat(text).date()
    except ValueError:
        return None


def build_training_snapshot(
    as_of: date,
    lookback_days: int,
    activities: Sequence[NormalizedActivity],
    recoveries: Sequence[DailyRecovery],
    *,
    undated_source_activity_ids: Sequence[str] = (),
) -> TrainingSnapshot:
    window = snapshot_window(as_of, lookback_days)
    issues: list[QualityIssue] = []

    dated: list[tuple[date, NormalizedActivity]] = []
    undated_ids = set(undated_source_activity_ids)
    for activity in activities:
        local_date = activity_local_date(activity)
        if local_date is None:
            undated_ids.add(activity.source_activity_id)
        elif window.contains(local_date):
            dated.append((local_date, activity))
    # Stable order independent of the caller; float sums below also use math.fsum.
    dated.sort(key=lambda item: (item[0], item[1].started_at_local or "", item[1].source_activity_id))
    issues.extend(
        QualityIssue(
            QualityIssueCode.UNDATED_ACTIVITY,
            source_id,
            "no local start time; excluded from every window",
        )
        for source_id in sorted(undated_ids)
    )

    load_values = {activity.source_activity_id: _load_metric_values(activity, issues) for _day, activity in dated}

    overview = _activity_overview(dated, load_values)
    strength = _strength_summary(
        [(day, activity) for day, activity in dated if activity.canonical_type is ActivityType.STRENGTH],
        load_values,
        issues,
    )
    swimming = _swimming_summary(
        [(day, activity) for day, activity in dated if activity.canonical_type is ActivityType.SWIMMING],
        load_values,
        issues,
    )
    recovery = _recovery_summary(window, recoveries)

    return TrainingSnapshot(
        analytics_version=ANALYTICS_VERSION,
        window=window,
        activities=overview,
        strength=strength,
        swimming=swimming,
        recovery=recovery,
        quality_issues=tuple(issues),
    )


def aggregate(
    key: str,
    unit: str | None,
    rule: AggregationRule,
    pairs: Iterable[tuple[str, float | None]],
) -> MetricAggregate:
    items = tuple(pairs)
    present = tuple(SourceValue(source_id, value) for source_id, value in items if value is not None)
    missing = tuple(source_id for source_id, value in items if value is None)
    value: float | None
    if not present:
        value = None
    elif rule is AggregationRule.SUM:
        # fsum is exactly rounded, so the result does not depend on summation order.
        value = math.fsum(item.value for item in present)
    else:
        value = max(item.value for item in present)
    return MetricAggregate(key, unit, rule, value, present, missing)


def _load_metric_values(activity: NormalizedActivity, issues: list[QualityIssue]) -> dict[str, float | None]:
    by_key = {metric.key: metric.value for metric in activity.metrics}
    values: dict[str, float | None] = {}
    for spec in ACTIVITY_LOAD_METRICS:
        raw = by_key.get(spec.metric_key)
        if raw is None:
            values[spec.metric_key] = None
        elif isinstance(raw, bool) or not isinstance(raw, (int, float)) or not math.isfinite(raw):
            values[spec.metric_key] = None
            issues.append(
                QualityIssue(
                    QualityIssueCode.NON_NUMERIC_LOAD_METRIC,
                    activity.source_activity_id,
                    f"{spec.metric_key} is not a finite number; treated as missing",
                )
            )
        else:
            values[spec.metric_key] = float(raw)
    return values


def _load_aggregates(
    activities: Sequence[tuple[date, NormalizedActivity]],
    load_values: Mapping[str, Mapping[str, float | None]],
) -> tuple[MetricAggregate, ...]:
    return tuple(
        aggregate(
            spec.metric_key,
            spec.unit,
            LOAD_METRIC_AGGREGATION[spec.metric_key],
            (
                (activity.source_activity_id, load_values[activity.source_activity_id][spec.metric_key])
                for _day, activity in activities
            ),
        )
        for spec in ACTIVITY_LOAD_METRICS
    )


def _activity_overview(
    activities: Sequence[tuple[date, NormalizedActivity]],
    load_values: Mapping[str, Mapping[str, float | None]],
) -> ActivityOverview:
    by_type: dict[tuple[str, str], list[str]] = {}
    for _day, activity in activities:
        by_type.setdefault((activity.canonical_type.value, activity.source_type_key), []).append(
            activity.source_activity_id
        )
    return ActivityOverview(
        activity_count=len(activities),
        source_activity_ids=tuple(activity.source_activity_id for _day, activity in activities),
        training_dates=tuple(sorted({day for day, _activity in activities})),
        by_type=tuple(
            ActivityTypeCount(canonical, source_type, len(ids), tuple(ids))
            for (canonical, source_type), ids in sorted(by_type.items())
        ),
        elapsed_seconds=aggregate(
            "elapsed_seconds",
            "s",
            AggregationRule.SUM,
            ((activity.source_activity_id, activity.elapsed_seconds) for _day, activity in activities),
        ),
        load_metrics=_load_aggregates(activities, load_values),
    )


@dataclass
class _SetTotals:
    active_set_count: int = 0
    reps_total: int = 0
    reps_count: int = 0
    sets_missing_reps: int = 0
    zero_rep_sets: int = 0
    volume_terms: list[float] = field(default_factory=list)
    max_weight_kg: float | None = None

    def add(self, strength_set: StrengthSet) -> str | None:
        """Add one ACTIVE set; return the volume exclusion reason, if any."""
        self.active_set_count += 1
        reps = strength_set.reps
        weight = strength_set.normalized_weight_kg
        if reps is None:
            self.sets_missing_reps += 1
        else:
            self.reps_total += reps
            self.reps_count += 1
            if reps == 0:
                self.zero_rep_sets += 1
        if weight is not None and weight > 0 and (self.max_weight_kg is None or weight > self.max_weight_kg):
            self.max_weight_kg = weight
        reason = _volume_exclusion_reason(strength_set)
        if reason is None and reps is not None and weight is not None:
            self.volume_terms.append(weight * reps)
        return reason

    @property
    def reps(self) -> int | None:
        return self.reps_total if self.reps_count else None

    @property
    def volume_kg(self) -> float | None:
        return math.fsum(self.volume_terms) if self.volume_terms else None

    @property
    def volume_set_count(self) -> int:
        return len(self.volume_terms)


def _volume_exclusion_reason(strength_set: StrengthSet) -> str | None:
    # Volume (kg x reps) is only defined when both are known and positive. Zero weight may be
    # bodyweight or unrecorded load; either way the external-load volume is unknown, not zero.
    # Negative weight is Garmin's "no weight" sentinel (for example -1 g) and is invalid.
    reps = strength_set.reps
    weight = strength_set.normalized_weight_kg
    if reps is None:
        return "missing_reps"
    if reps == 0:
        return "zero_reps"
    if weight is None:
        return "missing_weight"
    if weight < 0:
        return "negative_weight"
    if weight == 0:
        return "zero_weight"
    return None


@dataclass
class _GroupTotals:
    sets: list[SetRef] = field(default_factory=list)
    source_ids: list[str] = field(default_factory=list)
    origins: Counter[LabelOrigin] = field(default_factory=Counter)

    def add(self, ref: SetRef, origin: LabelOrigin) -> None:
        self.sets.append(ref)
        if ref.source_activity_id not in self.source_ids:
            self.source_ids.append(ref.source_activity_id)
        self.origins[origin] += 1


def _origin_counts(origins: Counter[LabelOrigin]) -> LabelOriginCounts:
    return LabelOriginCounts(
        confirmed=origins[LabelOrigin.CONFIRMED],
        auto_detected=origins[LabelOrigin.AUTO_DETECTED],
        unspecified=origins[LabelOrigin.UNSPECIFIED],
    )


def _taxonomy_groups(groups: Mapping[str, _GroupTotals]) -> tuple[TaxonomyGroup, ...]:
    items = [
        TaxonomyGroup(
            key=key,
            active_set_count=len(totals.sets),
            label_origins=_origin_counts(totals.origins),
            source_activity_ids=tuple(totals.source_ids),
            sets=tuple(totals.sets),
        )
        for key, totals in groups.items()
    ]
    return tuple(sorted(items, key=lambda item: (-item.active_set_count, item.key)))


@dataclass
class _TaxonomyTotals:
    active_set_count: int = 0
    mapped_origins: Counter[LabelOrigin] = field(default_factory=Counter)
    labels: dict[tuple[str | None, str | None], tuple[ExerciseClassification, _GroupTotals]] = field(
        default_factory=dict
    )
    patterns: dict[str, _GroupTotals] = field(default_factory=dict)
    primary: dict[str, _GroupTotals] = field(default_factory=dict)
    secondary: dict[str, _GroupTotals] = field(default_factory=dict)

    def add(self, ref: SetRef, origin: LabelOrigin, classification: ExerciseClassification) -> None:
        """Add one ACTIVE set once to its label and, if mapped, once to its pattern and primary muscle."""
        self.active_set_count += 1
        label = (classification.source_category, classification.source_name)
        if label not in self.labels:
            self.labels[label] = (classification, _GroupTotals())
        self.labels[label][1].add(ref, origin)
        rule = classification.rule
        if rule is None:
            return
        self.mapped_origins[origin] += 1
        self.patterns.setdefault(rule.movement_pattern.value, _GroupTotals()).add(ref, origin)
        self.primary.setdefault(rule.primary_muscle.value, _GroupTotals()).add(ref, origin)
        for muscle in rule.secondary_muscles:
            self.secondary.setdefault(muscle.value, _GroupTotals()).add(ref, origin)

    def summary(self) -> StrengthTaxonomySummary:
        exercises = [_exercise_group(classification, totals) for classification, totals in self.labels.values()]
        exercises.sort(key=lambda item: (-item.active_set_count, item.category or "", item.exercise_name or ""))
        unknown_ids: list[str] = []
        unknown = no_rule = 0
        for item in exercises:
            if item.unmapped_reason == UnmappedReason.UNKNOWN_SOURCE_LABEL:
                unknown += item.active_set_count
                unknown_ids.extend(item.source_activity_ids)
            elif item.unmapped_reason == UnmappedReason.NO_RULE:
                no_rule += item.active_set_count
        return StrengthTaxonomySummary(
            taxonomy_version=TAXONOMY_VERSION,
            active_set_count=self.active_set_count,
            mapped_active_set_count=self.active_set_count - unknown - no_rule,
            unmapped_active_set_count=unknown + no_rule,
            unknown_active_set_count=unknown,
            unknown_source_activity_ids=tuple(sorted(set(unknown_ids))),
            no_rule_active_set_count=no_rule,
            mapped_label_origins=_origin_counts(self.mapped_origins),
            by_exercise=tuple(exercises),
            by_movement_pattern=_taxonomy_groups(self.patterns),
            by_primary_muscle=_taxonomy_groups(self.primary),
            secondary_muscle_set_exposures=_taxonomy_groups(self.secondary),
        )


def _exercise_group(classification: ExerciseClassification, totals: _GroupTotals) -> TaxonomyExerciseGroup:
    rule = classification.rule
    return TaxonomyExerciseGroup(
        category=classification.source_category,
        exercise_name=classification.source_name,
        movement_pattern=rule.movement_pattern.value if rule else None,
        primary_muscle=rule.primary_muscle.value if rule else None,
        secondary_muscles=tuple(muscle.value for muscle in rule.secondary_muscles) if rule else (),
        mapping_basis=rule.basis.value if rule else None,
        unmapped_reason=classification.unmapped_reason.value if classification.unmapped_reason else None,
        active_set_count=len(totals.sets),
        label_origins=_origin_counts(totals.origins),
        source_activity_ids=tuple(totals.source_ids),
        sets=tuple(totals.sets),
    )


def _strength_summary(
    activities: Sequence[tuple[date, NormalizedActivity]],
    load_values: Mapping[str, Mapping[str, float | None]],
    issues: list[QualityIssue],
) -> StrengthSummary:
    window_totals = _SetTotals()
    exclusions = dict.fromkeys(("missing_reps", "zero_reps", "missing_weight", "negative_weight", "zero_weight"), 0)
    exercises: dict[tuple[str | None, str | None], tuple[_SetTotals, list[str], list[str | None], set[bool]]] = {}
    taxonomy = _TaxonomyTotals()
    sessions: list[StrengthSessionSummary] = []
    set_row_count = rest_set_count = unclassified = 0

    for day, activity in activities:
        source_id = activity.source_activity_id
        if not activity.strength_sets:
            issues.append(
                QualityIssue(
                    QualityIssueCode.STRENGTH_SET_DETAIL_MISSING,
                    source_id,
                    "strength activity has no stored exercise sets; set-level totals exclude it",
                )
            )
        unclassified_sequences = frozenset(
            sequence for reason in derive_activity_review(activity).reasons for sequence in reason.set_sequences
        )
        session_totals = _SetTotals()
        negative_weight_sequences: list[int] = []
        missing_reps_sequences: list[int] = []
        no_rule_sequences: list[int] = []
        for strength_set in activity.strength_sets:
            set_row_count += 1
            if strength_set.set_type == "REST":
                rest_set_count += 1
            if strength_set.set_type != "ACTIVE":
                continue
            reason = window_totals.add(strength_set)
            session_totals.add(strength_set)
            if reason is not None:
                exclusions[reason] += 1
            if strength_set.normalized_weight_kg is not None and strength_set.normalized_weight_kg < 0:
                negative_weight_sequences.append(strength_set.sequence)
            if strength_set.reps is None:
                missing_reps_sequences.append(strength_set.sequence)
            classified = strength_set.sequence not in unclassified_sequences
            if not classified:
                unclassified += 1
            # The taxonomy keys on the stored (category, name) label, never on a renamed exercise.
            classification = classify_strength_set(strength_set)
            if classification.unmapped_reason is UnmappedReason.NO_RULE:
                no_rule_sequences.append(strength_set.sequence)
            taxonomy.add(
                SetRef(source_id, strength_set.sequence),
                label_origin(strength_set.source_exercise_probability),
                classification,
            )
            key = (strength_set.source_exercise_key, strength_set.source_exercise_category)
            if key not in exercises:
                exercises[key] = (_SetTotals(), [], [], set())
            totals, source_ids, display_names, classified_flags = exercises[key]
            totals.add(strength_set)
            if source_id not in source_ids:
                source_ids.append(source_id)
            if strength_set.display_exercise_name not in display_names:
                display_names.append(strength_set.display_exercise_name)
            classified_flags.add(classified)

        if unclassified_sequences:
            issues.append(
                QualityIssue(
                    QualityIssueCode.STRENGTH_UNCLASSIFIED_EXERCISE,
                    source_id,
                    f"{len(unclassified_sequences)} ACTIVE sets have UNKNOWN/missing Garmin exercise classification",
                    set_sequences=tuple(sorted(unclassified_sequences)),
                )
            )
        if no_rule_sequences:
            issues.append(
                QualityIssue(
                    QualityIssueCode.STRENGTH_UNMAPPED_EXERCISE,
                    source_id,
                    f"{len(no_rule_sequences)} ACTIVE sets have a Garmin exercise label without an exercise "
                    "taxonomy rule; reported as unmapped",
                    set_sequences=tuple(no_rule_sequences),
                )
            )
        if negative_weight_sequences:
            issues.append(
                QualityIssue(
                    QualityIssueCode.STRENGTH_NEGATIVE_WEIGHT,
                    source_id,
                    f"{len(negative_weight_sequences)} ACTIVE sets have a negative weight sentinel; "
                    "excluded from volume",
                    set_sequences=tuple(negative_weight_sequences),
                )
            )
        if missing_reps_sequences:
            issues.append(
                QualityIssue(
                    QualityIssueCode.STRENGTH_MISSING_REPS,
                    source_id,
                    f"{len(missing_reps_sequences)} ACTIVE sets have no rep count; excluded from reps and volume",
                    set_sequences=tuple(missing_reps_sequences),
                )
            )
        sessions.append(
            StrengthSessionSummary(
                source_activity_id=source_id,
                local_date=day,
                set_detail_available=bool(activity.strength_sets),
                active_set_count=session_totals.active_set_count,
                reps=session_totals.reps,
                sets_missing_reps=session_totals.sets_missing_reps,
                volume_kg=session_totals.volume_kg,
                volume_set_count=session_totals.volume_set_count,
            )
        )

    exercise_aggregates = [
        ExerciseAggregate(
            exercise_key=key,
            category=category,
            # A key may map to more than one Garmin display name only if the source did;
            # the first-seen display name is kept and the key remains the identity.
            display_name=display_names[0],
            classified=classified_flags == {True},
            active_set_count=totals.active_set_count,
            reps=totals.reps,
            sets_missing_reps=totals.sets_missing_reps,
            volume_kg=totals.volume_kg,
            volume_set_count=totals.volume_set_count,
            max_weight_kg=totals.max_weight_kg,
            source_activity_ids=tuple(source_ids),
        )
        for (key, category), (totals, source_ids, display_names, classified_flags) in exercises.items()
    ]
    exercise_aggregates.sort(key=lambda item: (-item.active_set_count, item.exercise_key or "", item.category or ""))

    return StrengthSummary(
        session_count=len(activities),
        source_activity_ids=tuple(activity.source_activity_id for _day, activity in activities),
        set_row_count=set_row_count,
        rest_set_count=rest_set_count,
        active_set_count=window_totals.active_set_count,
        reps=window_totals.reps,
        sets_missing_reps=window_totals.sets_missing_reps,
        zero_rep_sets=window_totals.zero_rep_sets,
        volume_kg=window_totals.volume_kg,
        volume_set_count=window_totals.volume_set_count,
        volume_exclusions=VolumeExclusions(**exclusions),
        unclassified_active_set_count=unclassified,
        exercises=tuple(exercise_aggregates),
        sessions=tuple(sessions),
        load_metrics=_load_aggregates(activities, load_values),
        taxonomy=taxonomy.summary(),
    )


def _implausible_speed(distance_meters: float | None, duration_seconds: float | None) -> bool:
    """Distance with no positive duration, or faster than the plausibility bound."""
    if distance_meters is None or distance_meters <= 0:
        return False
    if duration_seconds is None or duration_seconds <= 0:
        return True
    return distance_meters / duration_seconds > MAX_PLAUSIBLE_SWIM_SPEED_MPS


def _swim_session(day: date, activity: NormalizedActivity, issues: list[QualityIssue]) -> SwimSessionSummary:
    source_id = activity.source_activity_id
    swim = activity.swim_detail
    if swim is None or not swim.laps:
        issues.append(
            QualityIssue(
                QualityIssueCode.SWIM_DETAIL_MISSING,
                source_id,
                "no stored lap/length detail; only Garmin summary values are available",
            )
        )
        return SwimSessionSummary(
            source_activity_id=source_id,
            local_date=day,
            summary_distance_meters=activity.distance_meters,
            elapsed_seconds=activity.elapsed_seconds,
            moving_seconds=activity.moving_seconds,
            pool_length_meters=swim.pool_length_meters if swim is not None else None,
            detail_available=False,
            lap_count=0,
            length_count=0,
            swimming_length_count=0,
            detail_distance_meters=None,
            implausible_lap_sequences=(),
            implausible_lap_distance_meters=0.0,
            plausible_detail_distance_meters=None,
            implausible_length_count=0,
            summary_distance_includes_implausible_laps=False,
        )

    lap_distances: list[float] = []
    plausible_distances: list[float] = []
    implausible_laps: list[int] = []
    implausible_lap_distance: list[float] = []
    mismatched_laps: list[int] = []
    implausible_lengths = 0
    length_count = swimming_lengths = 0
    for lap in swim.laps:
        lap_distance = derive_lap_metrics(lap).effective_distance_meters
        if lap_distance is not None:
            lap_distances.append(lap_distance)
        lap_is_implausible = _implausible_speed(lap_distance, lap.duration_seconds)
        if lap_is_implausible and lap_distance is not None:
            implausible_laps.append(lap.sequence)
            implausible_lap_distance.append(lap_distance)
        elif lap_distance is not None:
            plausible_distances.append(lap_distance)

        length_distances: list[float] = []
        for length in lap.lengths:
            length_count += 1
            length_distance = derive_length_metrics(length).effective_distance_meters
            if length_distance is not None and length_distance > 0:
                swimming_lengths += 1
                length_distances.append(length_distance)
            # Lengths inside an implausible lap are already covered by the lap issue.
            if not lap_is_implausible and _implausible_speed(length_distance, length.duration_seconds):
                implausible_lengths += 1
        if lap.lengths and abs(math.fsum(length_distances) - (lap_distance or 0.0)) > _DISTANCE_MATCH_TOLERANCE_METERS:
            mismatched_laps.append(lap.sequence)

    detail_distance = math.fsum(lap_distances) if lap_distances else None
    implausible_distance = math.fsum(implausible_lap_distance)
    summary_includes = (
        bool(implausible_laps)
        and activity.distance_meters is not None
        and detail_distance is not None
        and abs(activity.distance_meters - detail_distance) <= _DISTANCE_MATCH_TOLERANCE_METERS
    )

    if implausible_laps:
        issues.append(
            QualityIssue(
                QualityIssueCode.SWIM_LAP_IMPLAUSIBLE_SPEED,
                source_id,
                f"{len(implausible_laps)} laps carry {implausible_distance:g} m faster than "
                f"{MAX_PLAUSIBLE_SWIM_SPEED_MPS:g} m/s (or with no duration); "
                "excluded from plausible detail distance",
                lap_sequences=tuple(implausible_laps),
            )
        )
    if summary_includes:
        issues.append(
            QualityIssue(
                QualityIssueCode.SWIM_SUMMARY_DISTANCE_INCLUDES_IMPLAUSIBLE_LAPS,
                source_id,
                f"Garmin summary distance {activity.distance_meters:g} m equals the lap total and includes "
                f"{implausible_distance:g} m from implausible laps; reported unchanged",
                lap_sequences=tuple(implausible_laps),
            )
        )
    if mismatched_laps:
        issues.append(
            QualityIssue(
                QualityIssueCode.SWIM_LAP_LENGTH_DISTANCE_MISMATCH,
                source_id,
                f"{len(mismatched_laps)} laps whose distance differs from the sum of their length distances",
                lap_sequences=tuple(mismatched_laps),
            )
        )
    if implausible_lengths:
        issues.append(
            QualityIssue(
                QualityIssueCode.SWIM_LENGTH_IMPLAUSIBLE_SPEED,
                source_id,
                f"{implausible_lengths} lengths inside plausible laps are faster than "
                f"{MAX_PLAUSIBLE_SWIM_SPEED_MPS:g} m/s; counted only, distance unchanged",
            )
        )

    return SwimSessionSummary(
        source_activity_id=source_id,
        local_date=day,
        summary_distance_meters=activity.distance_meters,
        elapsed_seconds=activity.elapsed_seconds,
        moving_seconds=activity.moving_seconds,
        pool_length_meters=swim.pool_length_meters,
        detail_available=True,
        lap_count=len(swim.laps),
        length_count=length_count,
        swimming_length_count=swimming_lengths,
        detail_distance_meters=detail_distance,
        implausible_lap_sequences=tuple(implausible_laps),
        implausible_lap_distance_meters=implausible_distance,
        plausible_detail_distance_meters=math.fsum(plausible_distances) if detail_distance is not None else None,
        implausible_length_count=implausible_lengths,
        summary_distance_includes_implausible_laps=summary_includes,
    )


def _swimming_summary(
    activities: Sequence[tuple[date, NormalizedActivity]],
    load_values: Mapping[str, Mapping[str, float | None]],
    issues: list[QualityIssue],
) -> SwimmingSummary:
    sessions = tuple(_swim_session(day, activity, issues) for day, activity in activities)

    def total(key: str, unit: str, values: Iterable[tuple[str, float | None]]) -> MetricAggregate:
        return aggregate(key, unit, AggregationRule.SUM, values)

    return SwimmingSummary(
        session_count=len(sessions),
        source_activity_ids=tuple(item.source_activity_id for item in sessions),
        summary_distance_meters=total(
            "summary_distance_meters", "m", ((s.source_activity_id, s.summary_distance_meters) for s in sessions)
        ),
        elapsed_seconds=total("elapsed_seconds", "s", ((s.source_activity_id, s.elapsed_seconds) for s in sessions)),
        moving_seconds=total("moving_seconds", "s", ((s.source_activity_id, s.moving_seconds) for s in sessions)),
        pool_lengths_meters=tuple(
            sorted({s.pool_length_meters for s in sessions if s.pool_length_meters is not None})
        ),
        detail_distance_meters=total(
            "detail_distance_meters", "m", ((s.source_activity_id, s.detail_distance_meters) for s in sessions)
        ),
        plausible_detail_distance_meters=total(
            "plausible_detail_distance_meters",
            "m",
            ((s.source_activity_id, s.plausible_detail_distance_meters) for s in sessions),
        ),
        implausible_lap_count=sum(len(s.implausible_lap_sequences) for s in sessions),
        implausible_length_count=sum(s.implausible_length_count for s in sessions),
        sessions=sessions,
        load_metrics=_load_aggregates(activities, load_values),
    )


def _recovery_summary(window: SnapshotWindow, recoveries: Sequence[DailyRecovery]) -> RecoverySummary:
    by_date: dict[date, DailyRecovery] = {}
    for recovery in recoveries:
        day = date.fromisoformat(recovery.calendar_date)
        if window.contains(day):
            if day in by_date:
                raise ValueError(f"duplicate recovery row for {recovery.calendar_date}")
            by_date[day] = recovery
    dates_with_row = tuple(sorted(by_date))
    dates_without_row = tuple(day for day in window.dates if day not in by_date)

    numeric: list[RecoveryFieldAggregate] = []
    for spec in RECOVERY_NUMERIC_FIELDS:
        present: list[tuple[date, float]] = []
        null_dates: list[date] = []
        for day in dates_with_row:
            raw = getattr(by_date[day], spec.field)
            if raw is None:
                null_dates.append(day)
            else:
                present.append((day, float(raw)))
        latest = present[-1] if present else None
        daily = spec.rule is RecoveryRule.DAILY and bool(present)
        numeric.append(
            RecoveryFieldAggregate(
                field=spec.field,
                unit=spec.unit,
                rule=spec.rule,
                latest_value=latest[1] if latest else None,
                latest_date=latest[0] if latest else None,
                mean=math.fsum(value for _day, value in present) / len(present) if daily else None,
                minimum=min(value for _day, value in present) if daily else None,
                maximum=max(value for _day, value in present) if daily else None,
                available_dates=tuple(day for day, _value in present),
                null_dates=tuple(null_dates),
            )
        )

    categorical: list[RecoveryCategoricalField] = []
    for field_name in RECOVERY_CATEGORICAL_FIELDS:
        values: list[DatedText] = []
        categorical_nulls: list[date] = []
        for day in dates_with_row:
            text = getattr(by_date[day], field_name)
            if text is None:
                categorical_nulls.append(day)
            else:
                values.append(DatedText(day, text))
        categorical.append(
            RecoveryCategoricalField(
                field=field_name,
                latest_value=values[-1].value if values else None,
                latest_date=values[-1].calendar_date if values else None,
                values=tuple(values),
                null_dates=tuple(categorical_nulls),
            )
        )

    return RecoverySummary(
        requested_day_count=window.lookback_days,
        dates_with_row=dates_with_row,
        dates_without_row=dates_without_row,
        numeric_fields=tuple(numeric),
        categorical_fields=tuple(categorical),
        days=tuple(by_date[day] for day in dates_with_row),
    )
