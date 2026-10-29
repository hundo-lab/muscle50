"""Strength set timing v1: ACTIVE sets too short for their reps, and the work hidden in the REST before them.

When the watch button is pressed late, the work is recorded as part of the preceding REST and the
ACTIVE set that follows is impossibly short (for example 5 reps in 1.7 s). This module finds those
sets and, where the stored wrist heart-rate series allows, estimates when the work really started.

Everything here is **display only**: no training, rest or nutrition rule consumes these values.
Stored sets and RAW are never changed; every derived value lives only in the output. Missing is
not zero: a set without reps or duration is "unchecked", a missing heart-rate sample is skipped,
and a set that cannot be estimated keeps a reason instead of a number.

Evidence IDs refer to docs/evidence/training-nutrition-evidence.md; ``design`` marks a number the
evidence does not give. All arithmetic is in integer milliseconds so equal input gives equal output.
"""

from __future__ import annotations

import math
import statistics
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from enum import StrEnum
from itertools import pairwise

from muscle50.domain.activity import NormalizedActivity, StrengthSet
from muscle50.domain.exercise_taxonomy import UnmappedReason, classify_strength_set
from muscle50.domain.strength_recommendation import COMPOUND_PATTERNS

SET_TIMING_VERSION = 1

# [design], no evidence: the evidence doc has no tempo or repetition-duration figure. A set faster
# than 1.0 s per rep is shown as "too short for its reps". Revisit after primary-source research on
# repetition duration. Exactly 1.0 s/rep is not suspect.
MIN_MILLISECONDS_PER_REP = 1000
# HR-01 for the form (a rise relative to the preceding low, kept small because wrist PPG under-reads
# in resistance work); [design] for the number 10.
MIN_HEART_RATE_RISE_BPM = 10
# [design], no evidence. Real Garmin smart recording leaves 5-7 s gaps and up to about 12 s.
MAX_HEART_RATE_GAP_MILLISECONDS = 10_000
# HR-03: the upper end of the 0-43 s PPG-vs-ECG offset (not measured in strength work, not fixed);
# [design] for using it as the bound of a calibrated lag, (0, 43 s].
MAX_WRIST_LAG_MILLISECONDS = 43_000
# HR-04 for the method (calibrate the lag from normal sets); [design] for the number 3.
MIN_LAG_CALIBRATION_SETS = 3
# [design], no evidence: "medium" needs at least 5 calibration sets and a lag spread of at most 10 s.
MEDIUM_CONFIDENCE_MIN_CALIBRATION_SETS = 5
MEDIUM_CONFIDENCE_MAX_LAG_SPREAD_MILLISECONDS = 10_000
# HR-02: Garmin wrist HR in strength work has MAPE of roughly 28-82 %, so there is no "high" level.

SUSPECT_EVIDENCE = ("design",)
RISE_EVIDENCE = ("HR-01", "design")
GAP_EVIDENCE = ("design",)
LAG_BOUNDS_EVIDENCE = ("HR-03", "design")
LAG_EVIDENCE = ("HR-04", "HR-03", "design")
CONFIDENCE_EVIDENCE = ("HR-02", "design")
# REST-07 separates compound from accessory rest; [design] for using movement patterns for it.
REST_GROUP_EVIDENCE = ("REST-07", "design")

HEART_RATE_TIMESTAMP_KEY = "directTimestamp"
HEART_RATE_VALUE_KEY = "directHeartRate"

_ACTIVE = "ACTIVE"
_REST = "REST"
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


class NotEstimatedReason(StrEnum):
    """Why a suspect set has no estimate. Checked in this order; the first that applies is reported."""

    NO_PRECEDING_REST = "no_preceding_rest"
    SET_TIME_MISSING = "set_time_missing"
    HEART_RATE_RAW_MISSING = "heart_rate_raw_missing"
    HEART_RATE_RAW_UNREADABLE = "heart_rate_raw_unreadable"
    HEART_RATE_NOT_IN_RAW = "heart_rate_not_in_raw"
    CLOCK_UNVERIFIED = "clock_unverified"
    LAG_UNCALIBRATED = "lag_uncalibrated"
    HEART_RATE_GAP = "heart_rate_gap"
    RISE_UNCLEAR = "rise_unclear"


class TimingMethod(StrEnum):
    HEART_RATE = "heart_rate"
    NONE = "none"


class Confidence(StrEnum):
    MEDIUM = "medium"
    LOW = "low"


class HeartRateStatus(StrEnum):
    AVAILABLE = "available"
    RAW_MISSING = "raw_missing"
    RAW_UNREADABLE = "raw_unreadable"
    NOT_IN_RAW = "not_in_raw"


class LagStatus(StrEnum):
    CALIBRATED = "calibrated"
    UNCALIBRATED = "uncalibrated"


_STATUS_REASONS = {
    HeartRateStatus.RAW_MISSING: NotEstimatedReason.HEART_RATE_RAW_MISSING,
    HeartRateStatus.RAW_UNREADABLE: NotEstimatedReason.HEART_RATE_RAW_UNREADABLE,
    HeartRateStatus.NOT_IN_RAW: NotEstimatedReason.HEART_RATE_NOT_IN_RAW,
}


@dataclass(frozen=True)
class HeartRateSample:
    at_ms: int
    """Epoch milliseconds (UTC), as Garmin's ``directTimestamp``."""
    bpm: float


@dataclass(frozen=True)
class HeartRateLoad:
    """The stored heart-rate series of one activity. Samples are never printed (health values)."""

    status: HeartRateStatus
    samples: tuple[HeartRateSample, ...]
    artifact_relative_path: str | None


@dataclass(frozen=True)
class LagCalibration:
    status: LagStatus
    median_ms: int | None
    min_ms: int | None
    max_ms: int | None
    set_sequences: tuple[int, ...]
    """Sequences of the normal sets whose lag was measured (also when too few to calibrate)."""


@dataclass(frozen=True)
class SuspectSet:
    source_activity_id: str
    local_date: date
    sequence: int
    exercise_category: str | None
    exercise_name: str | None
    label_set_number: int
    """The k-th ACTIVE set with this Garmin label in the activity."""
    reps: int
    recorded_seconds: float
    preceding_rest_sequence: int | None
    recorded_rest_seconds: float | None
    method: TimingMethod
    not_estimated_reason: NotEstimatedReason | None
    heart_rate_onset_at_ms: int | None
    estimated_start_at_ms: int | None
    estimated_work_ms: int | None
    estimated_work_range_ms: tuple[int, int] | None
    estimated_rest_ms: int | None
    estimated_rest_range_ms: tuple[int, int] | None
    confidence: Confidence | None


@dataclass(frozen=True)
class RestGroup:
    median_seconds: float | None
    """None (unavailable) when the group has no rest, never 0."""
    rest_count: int
    estimated_rest_count: int


@dataclass(frozen=True)
class RestBetweenSets:
    overall: RestGroup
    compound: RestGroup
    isolation: RestGroup
    unclassified: RestGroup
    excluded_not_estimated: int
    excluded_missing_duration: int
    excluded_label_change_or_unknown: int
    excluded_unchecked: int


@dataclass(frozen=True)
class SessionSetTiming:
    source_activity_id: str
    local_date: date
    suspect_set_sequences: tuple[int, ...]
    heart_rate: HeartRateLoad | None
    """None when no suspect set had a preceding REST, so the series was never read."""
    lag: LagCalibration | None
    """None when the series is not available or the set clock does not match it."""


@dataclass(frozen=True)
class StrengthSetTimingSummary:
    version: int
    active_set_count: int
    checked_set_count: int
    unchecked_set_count: int
    suspect_set_count: int
    estimated_set_count: int
    not_estimated_set_count: int
    sessions: tuple[SessionSetTiming, ...]
    """Only sessions with at least one suspect set."""
    suspect_sets: tuple[SuspectSet, ...]
    rest_between_sets: RestBetweenSets


def set_duration_ms(strength_set: StrengthSet) -> int | None:
    if strength_set.duration_seconds is None or not math.isfinite(strength_set.duration_seconds):
        return None
    return round(strength_set.duration_seconds * 1000)


def is_checked(strength_set: StrengthSet) -> bool:
    """An ACTIVE set with at least one rep and a duration. REST rows are never checked."""
    return (
        strength_set.set_type == _ACTIVE
        and strength_set.reps is not None
        and strength_set.reps >= 1
        and set_duration_ms(strength_set) is not None
    )


def is_suspect(strength_set: StrengthSet) -> bool:
    """A checked set shorter than MIN_MILLISECONDS_PER_REP per rep (integer comparison)."""
    if not is_checked(strength_set):
        return False
    duration = set_duration_ms(strength_set)
    assert duration is not None and strength_set.reps is not None
    return duration < strength_set.reps * MIN_MILLISECONDS_PER_REP


def suspect_sequences(activity: NormalizedActivity) -> tuple[int, ...]:
    return tuple(item.sequence for item in _ordered_sets(activity) if is_suspect(item))


def needs_heart_rate(activity: NormalizedActivity) -> bool:
    """True when at least one suspect set has a preceding REST, so the series is worth reading."""
    ordered = _ordered_sets(activity)
    return any(is_suspect(current) and previous.set_type == _REST for previous, current in pairwise(ordered))


def parse_set_start_ms(text: str | None) -> int | None:
    """Garmin's set ``startTime`` as epoch ms; a naive value is UTC (no zoneinfo)."""
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return (parsed - _EPOCH) // timedelta(milliseconds=1)


def utc_text(at_ms: int) -> str:
    """Fixed ISO format (millisecond precision) for an epoch-ms instant."""
    return (_EPOCH + timedelta(milliseconds=at_ms)).isoformat(timespec="milliseconds")


def parse_direct_heart_rate(details: object) -> tuple[HeartRateStatus, tuple[HeartRateSample, ...]]:
    """The ``directHeartRate`` series of a Garmin ``details.json``, found by descriptor key.

    Garmin permutes ``metricsIndex`` between calls, so columns are never read by position. A null or
    non-numeric cell is skipped (missing, not 0). A timestamp with two different values makes the
    whole series unreadable rather than picking one.
    """
    if not isinstance(details, Mapping):
        return HeartRateStatus.RAW_UNREADABLE, ()
    descriptors = details.get("metricDescriptors")
    if descriptors is None:
        return HeartRateStatus.NOT_IN_RAW, ()
    if not isinstance(descriptors, list):
        return HeartRateStatus.RAW_UNREADABLE, ()
    columns: dict[str, int] = {}
    for descriptor in descriptors:
        if not isinstance(descriptor, Mapping):
            return HeartRateStatus.RAW_UNREADABLE, ()
        key = descriptor.get("key")
        if key not in (HEART_RATE_TIMESTAMP_KEY, HEART_RATE_VALUE_KEY):
            continue
        index = descriptor.get("metricsIndex")
        if not isinstance(index, int) or isinstance(index, bool) or index < 0:
            return HeartRateStatus.RAW_UNREADABLE, ()
        if columns.setdefault(key, index) != index:
            return HeartRateStatus.RAW_UNREADABLE, ()
    if HEART_RATE_TIMESTAMP_KEY not in columns or HEART_RATE_VALUE_KEY not in columns:
        return HeartRateStatus.NOT_IN_RAW, ()
    rows = details.get("activityDetailMetrics")
    if rows is None:
        rows = []
    if not isinstance(rows, list):
        return HeartRateStatus.RAW_UNREADABLE, ()
    values: dict[int, float] = {}
    for row in rows:
        metrics = row.get("metrics") if isinstance(row, Mapping) else None
        if not isinstance(metrics, list):
            return HeartRateStatus.RAW_UNREADABLE, ()
        timestamp = _number_cell(metrics, columns[HEART_RATE_TIMESTAMP_KEY])
        bpm = _number_cell(metrics, columns[HEART_RATE_VALUE_KEY])
        if timestamp is None or bpm is None:
            continue
        at_ms = round(timestamp)
        if values.setdefault(at_ms, bpm) != bpm:
            return HeartRateStatus.RAW_UNREADABLE, ()
    if not values:
        return HeartRateStatus.NOT_IN_RAW, ()
    return HeartRateStatus.AVAILABLE, tuple(HeartRateSample(at, values[at]) for at in sorted(values))


def find_rise_onset(
    samples: Sequence[HeartRateSample],
    search_start: int,
    search_end: int,
    rise_end: int,
) -> int | NotEstimatedReason:
    """The latest low point in [search_start, search_end] that is followed by a clear rise.

    ``samples`` must be sorted by time. Returns the low point's timestamp, or why there is none:
    the series must cover [search_start, rise_end] without a gap longer than
    MAX_HEART_RATE_GAP_MILLISECONDS; a low point at the first sample means heart rate was already
    rising (HR-05, for example from the previous set); the rise after it must reach
    MIN_HEART_RATE_RISE_BPM by ``rise_end``.
    """
    window = [sample for sample in samples if search_start <= sample.at_ms <= rise_end]
    if (
        not window
        or window[0].at_ms - search_start > MAX_HEART_RATE_GAP_MILLISECONDS
        or rise_end - window[-1].at_ms > MAX_HEART_RATE_GAP_MILLISECONDS
        or any(later.at_ms - earlier.at_ms > MAX_HEART_RATE_GAP_MILLISECONDS for earlier, later in pairwise(window))
    ):
        return NotEstimatedReason.HEART_RATE_GAP
    search = [sample for sample in window if sample.at_ms <= search_end]
    if not search:
        return NotEstimatedReason.HEART_RATE_GAP
    # Lowest value; on a tie the latest sample wins.
    trough = min(search, key=lambda sample: (sample.bpm, -sample.at_ms))
    if trough.at_ms == search[0].at_ms:
        return NotEstimatedReason.RISE_UNCLEAR
    peak = max((sample.bpm for sample in window if sample.at_ms > trough.at_ms), default=None)
    if peak is None or peak - trough.bpm < MIN_HEART_RATE_RISE_BPM:
        return NotEstimatedReason.RISE_UNCLEAR
    return trough.at_ms


def calibrate_lag(activity: NormalizedActivity, samples: Sequence[HeartRateSample]) -> LagCalibration:
    """Wrist lag measured on this activity's normal sets (HR-04): ACTIVE start to heart-rate low point.

    Per activity, so it does not depend on the snapshot window. A normal set is a checked,
    non-suspect ACTIVE set right after a REST, with a parseable start.
    """
    lags: list[int] = []
    sequences: list[int] = []
    for previous, current in pairwise(_ordered_sets(activity)):
        if previous.set_type != _REST or not is_checked(current) or is_suspect(current):
            continue
        start = parse_set_start_ms(current.started_at)
        duration = set_duration_ms(current)
        if start is None or duration is None:
            continue
        end = start + duration
        onset = find_rise_onset(
            samples, start, min(start + MAX_WRIST_LAG_MILLISECONDS, end), end + MAX_WRIST_LAG_MILLISECONDS
        )
        if isinstance(onset, NotEstimatedReason):
            continue
        lag = onset - start
        if 0 < lag <= MAX_WRIST_LAG_MILLISECONDS:
            lags.append(lag)
            sequences.append(current.sequence)
    if len(lags) < MIN_LAG_CALIBRATION_SETS:
        return LagCalibration(LagStatus.UNCALIBRATED, None, None, None, tuple(sequences))
    return LagCalibration(LagStatus.CALIBRATED, statistics.median_low(lags), min(lags), max(lags), tuple(sequences))


def estimate_session(
    local_date: date,
    activity: NormalizedActivity,
    heart_rate: HeartRateLoad | None,
) -> tuple[SessionSetTiming, tuple[SuspectSet, ...]]:
    """Every suspect set of one activity, estimated from the REST before it where heart rate allows."""
    ordered = _ordered_sets(activity)
    source_id = activity.source_activity_id
    label_numbers = _label_set_numbers(ordered)

    lag: LagCalibration | None = None
    clock_ok = False
    if heart_rate is not None and heart_rate.status is HeartRateStatus.AVAILABLE and heart_rate.samples:
        clock_ok = _clock_matches(ordered, heart_rate.samples)
        if clock_ok:
            lag = calibrate_lag(activity, heart_rate.samples)

    suspects: list[SuspectSet] = []
    for index, current in enumerate(ordered):
        if not is_suspect(current):
            continue
        previous = ordered[index - 1] if index > 0 else None
        rest = previous if previous is not None and previous.set_type == _REST else None
        reason, estimate = _estimate(current, rest, heart_rate, clock_ok, lag)
        duration = current.duration_seconds
        assert current.reps is not None and duration is not None
        suspects.append(
            SuspectSet(
                source_activity_id=source_id,
                local_date=local_date,
                sequence=current.sequence,
                exercise_category=current.source_exercise_category,
                exercise_name=current.source_exercise_name,
                label_set_number=label_numbers[current.sequence],
                reps=current.reps,
                recorded_seconds=duration,
                preceding_rest_sequence=rest.sequence if rest is not None else None,
                recorded_rest_seconds=rest.duration_seconds if rest is not None else None,
                method=TimingMethod.NONE if estimate is None else TimingMethod.HEART_RATE,
                not_estimated_reason=reason,
                heart_rate_onset_at_ms=estimate.onset_ms if estimate else None,
                estimated_start_at_ms=estimate.start_ms if estimate else None,
                estimated_work_ms=estimate.work_ms if estimate else None,
                estimated_work_range_ms=estimate.work_range_ms if estimate else None,
                estimated_rest_ms=estimate.rest_ms if estimate else None,
                estimated_rest_range_ms=estimate.rest_range_ms if estimate else None,
                confidence=estimate.confidence if estimate else None,
            )
        )
    session = SessionSetTiming(
        source_activity_id=source_id,
        local_date=local_date,
        suspect_set_sequences=tuple(item.sequence for item in suspects),
        heart_rate=heart_rate,
        lag=lag,
    )
    return session, tuple(suspects)


def summarize_set_timing(
    activities: Sequence[tuple[date, NormalizedActivity]],
    heart_rates: Mapping[str, HeartRateLoad],
) -> StrengthSetTimingSummary | None:
    """Set timing for the window's strength sessions; None when no set is too short for its reps.

    ``heart_rates`` holds the series of the activities for which ``needs_heart_rate`` is true; an
    activity that needs one but is absent counts as RAW missing.
    """
    ordered_activities = sorted(
        activities, key=lambda item: (item[0], item[1].started_at_local or "", item[1].source_activity_id)
    )
    counts: Counter[str] = Counter()
    sessions: list[SessionSetTiming] = []
    suspect_sets: list[SuspectSet] = []
    for day, activity in ordered_activities:
        for strength_set in activity.strength_sets:
            if strength_set.set_type != _ACTIVE:
                continue
            counts["active"] += 1
            counts["checked" if is_checked(strength_set) else "unchecked"] += 1
        if not suspect_sequences(activity):
            continue
        heart_rate = heart_rates.get(activity.source_activity_id)
        if heart_rate is None and needs_heart_rate(activity):
            heart_rate = HeartRateLoad(HeartRateStatus.RAW_MISSING, (), None)
        session, suspects = estimate_session(day, activity, heart_rate)
        sessions.append(session)
        suspect_sets.extend(suspects)
    if not suspect_sets:
        return None
    estimated = sum(1 for item in suspect_sets if item.method is TimingMethod.HEART_RATE)
    return StrengthSetTimingSummary(
        version=SET_TIMING_VERSION,
        active_set_count=counts["active"],
        checked_set_count=counts["checked"],
        unchecked_set_count=counts["unchecked"],
        suspect_set_count=len(suspect_sets),
        estimated_set_count=estimated,
        not_estimated_set_count=len(suspect_sets) - estimated,
        sessions=tuple(sessions),
        suspect_sets=tuple(suspect_sets),
        rest_between_sets=rest_between_sets(ordered_activities, suspect_sets),
    )


def rest_between_sets(
    activities: Sequence[tuple[date, NormalizedActivity]],
    suspect_sets: Sequence[SuspectSet],
) -> RestBetweenSets:
    """Rest rows between two ACTIVE sets of the same known Garmin label (REST-07 grouping).

    The value is the estimated rest when the following set was estimated, else the recorded REST
    duration when the following set is normal. Every other case is excluded and counted.
    """
    by_set = {(item.source_activity_id, item.sequence): item for item in suspect_sets}
    values: dict[str, list[tuple[int, bool]]] = {"compound": [], "isolation": [], "unclassified": []}
    excluded: Counter[str] = Counter()
    for _day, activity in activities:
        ordered = _ordered_sets(activity)
        for before, rest, after in zip(ordered, ordered[1:], ordered[2:], strict=False):
            if rest.set_type != _REST or before.set_type != _ACTIVE or after.set_type != _ACTIVE:
                continue
            classification = classify_strength_set(after)
            if (
                classification.unmapped_reason is UnmappedReason.UNKNOWN_SOURCE_LABEL
                or classify_strength_set(before).unmapped_reason is UnmappedReason.UNKNOWN_SOURCE_LABEL
                or _label(before) != _label(after)
            ):
                excluded["label_change_or_unknown"] += 1
                continue
            if not is_checked(after):
                excluded["unchecked"] += 1
                continue
            suspect = by_set.get((activity.source_activity_id, after.sequence))
            if suspect is not None:
                if suspect.estimated_rest_ms is None:
                    excluded["not_estimated"] += 1
                    continue
                value, estimated = suspect.estimated_rest_ms, True
            else:
                rest_ms = set_duration_ms(rest)
                if rest_ms is None:
                    excluded["missing_duration"] += 1
                    continue
                value, estimated = rest_ms, False
            if classification.rule is None:
                group = "unclassified"
            elif classification.rule.movement_pattern in COMPOUND_PATTERNS:
                group = "compound"
            else:
                group = "isolation"
            values[group].append((value, estimated))
    overall = [item for group in values.values() for item in group]
    return RestBetweenSets(
        overall=_rest_group(overall),
        compound=_rest_group(values["compound"]),
        isolation=_rest_group(values["isolation"]),
        unclassified=_rest_group(values["unclassified"]),
        excluded_not_estimated=excluded["not_estimated"],
        excluded_missing_duration=excluded["missing_duration"],
        excluded_label_change_or_unknown=excluded["label_change_or_unknown"],
        excluded_unchecked=excluded["unchecked"],
    )


@dataclass(frozen=True)
class _Estimate:
    onset_ms: int
    start_ms: int
    work_ms: int
    work_range_ms: tuple[int, int]
    rest_ms: int
    rest_range_ms: tuple[int, int]
    confidence: Confidence


def _estimate(
    current: StrengthSet,
    rest: StrengthSet | None,
    heart_rate: HeartRateLoad | None,
    clock_ok: bool,
    lag: LagCalibration | None,
) -> tuple[NotEstimatedReason | None, _Estimate | None]:
    if rest is None:
        return NotEstimatedReason.NO_PRECEDING_REST, None
    rest_start = parse_set_start_ms(rest.started_at)
    pressed = parse_set_start_ms(current.started_at)
    duration = set_duration_ms(current)
    if rest_start is None or pressed is None or duration is None:
        return NotEstimatedReason.SET_TIME_MISSING, None
    if heart_rate is None:
        return NotEstimatedReason.HEART_RATE_RAW_MISSING, None
    status_reason = _STATUS_REASONS.get(heart_rate.status)
    if status_reason is not None:
        return status_reason, None
    if not heart_rate.samples:
        return NotEstimatedReason.HEART_RATE_NOT_IN_RAW, None
    if not clock_ok:
        return NotEstimatedReason.CLOCK_UNVERIFIED, None
    if lag is None or lag.median_ms is None or lag.min_ms is None or lag.max_ms is None:
        return NotEstimatedReason.LAG_UNCALIBRATED, None
    shift = lag.median_ms
    # The work ended when the button was pressed (``pressed``); its heart-rate trace is shifted by the lag.
    onset = find_rise_onset(heart_rate.samples, rest_start + shift, pressed + shift, pressed + duration + shift)
    if isinstance(onset, NotEstimatedReason):
        return onset, None
    start = onset - shift  # within [rest_start, pressed] by construction
    start_low = max(rest_start, onset - lag.max_ms)
    start_high = min(pressed, onset - lag.min_ms)
    spread = lag.max_ms - lag.min_ms
    medium = (
        len(lag.set_sequences) >= MEDIUM_CONFIDENCE_MIN_CALIBRATION_SETS
        and spread <= MEDIUM_CONFIDENCE_MAX_LAG_SPREAD_MILLISECONDS
    )
    return None, _Estimate(
        onset_ms=onset,
        start_ms=start,
        work_ms=pressed - start,
        work_range_ms=(pressed - start_high, pressed - start_low),
        rest_ms=start - rest_start,
        rest_range_ms=(start_low - rest_start, start_high - rest_start),
        confidence=Confidence.MEDIUM if medium else Confidence.LOW,
    )


def _clock_matches(ordered: Sequence[StrengthSet], samples: Sequence[HeartRateSample]) -> bool:
    """The first set start lies within the series (plus one gap): catches a misread time zone."""
    first_start = next(
        (start for start in (parse_set_start_ms(item.started_at) for item in ordered) if start is not None), None
    )
    if first_start is None:
        return False
    return (
        samples[0].at_ms - MAX_HEART_RATE_GAP_MILLISECONDS
        <= first_start
        <= samples[-1].at_ms + MAX_HEART_RATE_GAP_MILLISECONDS
    )


def _rest_group(values: Sequence[tuple[int, bool]]) -> RestGroup:
    if not values:
        return RestGroup(None, 0, 0)
    return RestGroup(
        median_seconds=statistics.median(value for value, _estimated in values) / 1000,
        rest_count=len(values),
        estimated_rest_count=sum(1 for _value, estimated in values if estimated),
    )


def _label(strength_set: StrengthSet) -> tuple[str | None, str | None]:
    return strength_set.source_exercise_category, strength_set.source_exercise_name


def _label_set_numbers(ordered: Sequence[StrengthSet]) -> dict[int, int]:
    seen: Counter[tuple[str | None, str | None]] = Counter()
    numbers: dict[int, int] = {}
    for strength_set in ordered:
        if strength_set.set_type != _ACTIVE:
            continue
        seen[_label(strength_set)] += 1
        numbers[strength_set.sequence] = seen[_label(strength_set)]
    return numbers


def _ordered_sets(activity: NormalizedActivity) -> tuple[StrengthSet, ...]:
    return tuple(sorted(activity.strength_sets, key=lambda item: item.sequence))


def _number_cell(metrics: list[object], index: int) -> float | None:
    if index >= len(metrics):
        return None
    value = metrics[index]
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    number = float(value)
    return number if math.isfinite(number) else None
