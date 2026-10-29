"""Text lines and the JSON payload of strength set timing (display only).

ASCII only. Heart-rate values (bpm) are health data and never appear here; only the rule
thresholds, sample counts, timestamps and the derived durations do. The payload is built by hand
with a fixed key order, never with ``dataclasses.asdict`` (which would dump every sample).
"""

from __future__ import annotations

from typing import Any

from muscle50.domain.strength_set_timing import (
    CONFIDENCE_EVIDENCE,
    GAP_EVIDENCE,
    LAG_BOUNDS_EVIDENCE,
    LAG_EVIDENCE,
    MAX_HEART_RATE_GAP_MILLISECONDS,
    MAX_WRIST_LAG_MILLISECONDS,
    MEDIUM_CONFIDENCE_MAX_LAG_SPREAD_MILLISECONDS,
    MEDIUM_CONFIDENCE_MIN_CALIBRATION_SETS,
    MIN_HEART_RATE_RISE_BPM,
    MIN_LAG_CALIBRATION_SETS,
    MIN_MILLISECONDS_PER_REP,
    REST_GROUP_EVIDENCE,
    RISE_EVIDENCE,
    SUSPECT_EVIDENCE,
    LagCalibration,
    RestBetweenSets,
    RestGroup,
    SessionSetTiming,
    StrengthSetTimingSummary,
    SuspectSet,
    utc_text,
)


def set_timing_lines(summary: StrengthSetTimingSummary) -> list[str]:
    lags = {session.source_activity_id: session.lag for session in summary.sessions}
    lines = [
        f"  Set timing [design; display only, used by no rule]: {summary.active_set_count} ACTIVE sets, "
        f"{summary.checked_set_count} checked, {summary.suspect_set_count} too short for their reps "
        f"(< {MIN_MILLISECONDS_PER_REP / 1000:.1f} s/rep); {summary.estimated_set_count} estimated from heart rate, "
        f"{summary.not_estimated_set_count} not estimated"
    ]
    lines.extend(_suspect_line(item, lags.get(item.source_activity_id)) for item in summary.suspect_sets)
    lines.append(_rest_line(summary.rest_between_sets))
    return lines


def set_timing_payload(summary: StrengthSetTimingSummary) -> dict[str, Any]:
    return {
        "set_timing_version": summary.version,
        "display_only": True,
        "rules": {
            "min_seconds_per_rep": MIN_MILLISECONDS_PER_REP / 1000,
            "min_heart_rate_rise_bpm": MIN_HEART_RATE_RISE_BPM,
            "max_heart_rate_gap_seconds": MAX_HEART_RATE_GAP_MILLISECONDS / 1000,
            "wrist_lag_bounds_seconds": [0.0, MAX_WRIST_LAG_MILLISECONDS / 1000],
            "min_lag_calibration_sets": MIN_LAG_CALIBRATION_SETS,
            "medium_confidence_min_calibration_sets": MEDIUM_CONFIDENCE_MIN_CALIBRATION_SETS,
            "medium_confidence_max_lag_spread_seconds": MEDIUM_CONFIDENCE_MAX_LAG_SPREAD_MILLISECONDS / 1000,
        },
        "evidence": {
            "min_seconds_per_rep": list(SUSPECT_EVIDENCE),
            "min_heart_rate_rise_bpm": list(RISE_EVIDENCE),
            "max_heart_rate_gap_seconds": list(GAP_EVIDENCE),
            "wrist_lag_bounds_seconds": list(LAG_BOUNDS_EVIDENCE),
            "lag_calibration": list(LAG_EVIDENCE),
            "confidence": list(CONFIDENCE_EVIDENCE),
            "rest_groups": list(REST_GROUP_EVIDENCE),
        },
        "active_set_count": summary.active_set_count,
        "checked_set_count": summary.checked_set_count,
        "unchecked_set_count": summary.unchecked_set_count,
        "suspect_set_count": summary.suspect_set_count,
        "estimated_set_count": summary.estimated_set_count,
        "not_estimated_set_count": summary.not_estimated_set_count,
        "sessions": [_session_payload(session) for session in summary.sessions],
        "suspect_sets": [_suspect_payload(item) for item in summary.suspect_sets],
        "rest_between_sets": _rest_payload(summary.rest_between_sets),
    }


def _suspect_line(item: SuspectSet, lag: LagCalibration | None) -> str:
    label = f"{item.exercise_category or 'no category'}/{item.exercise_name or '-'}"
    text = (
        f"    {item.local_date.isoformat()} {item.source_activity_id} seq {item.sequence} {label} "
        f"#{item.label_set_number}: {item.reps} reps in {item.recorded_seconds:.1f} s"
    )
    if item.preceding_rest_sequence is not None:
        rest = "unavailable" if item.recorded_rest_seconds is None else f"{item.recorded_rest_seconds:.1f} s"
        text += f" after REST {rest}"
    if (
        item.estimated_work_ms is None
        or item.estimated_work_range_ms is None
        or item.estimated_rest_ms is None
        or item.estimated_rest_range_ms is None
        or item.confidence is None
        or lag is None
        or lag.median_ms is None
    ):
        return f"{text} -> not estimated ({item.not_estimated_reason})"
    work_low, work_high = item.estimated_work_range_ms
    rest_low, rest_high = item.estimated_rest_range_ms
    return (
        f"{text} -> estimated work {_seconds(item.estimated_work_ms)} ({_bare(work_low)}-{_bare(work_high)}) / "
        f"rest {_seconds(item.estimated_rest_ms)} ({_bare(rest_low)}-{_bare(rest_high)}) "
        f"({item.method}, {item.confidence}; wrist lag {_seconds(lag.median_ms)} from {len(lag.set_sequences)} sets "
        "[HR-04])"
    )


def _rest_line(rest: RestBetweenSets) -> str:
    overall = rest.overall
    return (
        "  Rest between sets (same exercise; recorded, estimated where available) [design]: "
        f"median {_median(overall)} from {overall.rest_count} rests ({overall.estimated_rest_count} estimated), "
        f"compound {_median(rest.compound)} ({rest.compound.rest_count}), "
        f"isolation {_median(rest.isolation)} ({rest.isolation.rest_count}), "
        f"unclassified {_median(rest.unclassified)} ({rest.unclassified.rest_count}); "
        f"excluded: not estimated {rest.excluded_not_estimated}, missing duration {rest.excluded_missing_duration}, "
        f"label change or UNKNOWN {rest.excluded_label_change_or_unknown}, unchecked {rest.excluded_unchecked}"
    )


def _median(group: RestGroup) -> str:
    return "unavailable" if group.median_seconds is None else f"{group.median_seconds:.0f} s"


def _seconds(milliseconds: int) -> str:
    return f"{_bare(milliseconds)} s"


def _bare(milliseconds: int) -> str:
    return f"{milliseconds / 1000:.0f}"


def _session_payload(session: SessionSetTiming) -> dict[str, Any]:
    heart_rate = session.heart_rate
    lag = session.lag
    return {
        "source_activity_id": session.source_activity_id,
        "local_date": session.local_date.isoformat(),
        "suspect_set_sequences": list(session.suspect_set_sequences),
        "heart_rate": None
        if heart_rate is None
        else {
            "status": heart_rate.status.value,
            "artifact_relative_path": heart_rate.artifact_relative_path,
            "sample_count": len(heart_rate.samples),
        },
        "lag": None
        if lag is None
        else {
            "status": lag.status.value,
            "median_seconds": _optional_seconds(lag.median_ms),
            "min_seconds": _optional_seconds(lag.min_ms),
            "max_seconds": _optional_seconds(lag.max_ms),
            "calibration_set_sequences": list(lag.set_sequences),
        },
    }


def _suspect_payload(item: SuspectSet) -> dict[str, Any]:
    return {
        "source_activity_id": item.source_activity_id,
        "local_date": item.local_date.isoformat(),
        "sequence": item.sequence,
        "exercise_category": item.exercise_category,
        "exercise_name": item.exercise_name,
        "label_set_number": item.label_set_number,
        "reps": item.reps,
        "recorded_seconds": item.recorded_seconds,
        "preceding_rest_sequence": item.preceding_rest_sequence,
        "recorded_rest_seconds": item.recorded_rest_seconds,
        "method": item.method.value,
        "not_estimated_reason": None if item.not_estimated_reason is None else item.not_estimated_reason.value,
        "heart_rate_onset_at_utc": None
        if item.heart_rate_onset_at_ms is None
        else utc_text(item.heart_rate_onset_at_ms),
        "estimated_start_at_utc": None if item.estimated_start_at_ms is None else utc_text(item.estimated_start_at_ms),
        "estimated_work_seconds": _optional_seconds(item.estimated_work_ms),
        "estimated_work_range_seconds": _range(item.estimated_work_range_ms),
        "estimated_rest_seconds": _optional_seconds(item.estimated_rest_ms),
        "estimated_rest_range_seconds": _range(item.estimated_rest_range_ms),
        "confidence": None if item.confidence is None else item.confidence.value,
    }


def _rest_payload(rest: RestBetweenSets) -> dict[str, Any]:
    return {
        "overall": _group_payload(rest.overall),
        "compound": _group_payload(rest.compound),
        "isolation": _group_payload(rest.isolation),
        "unclassified": _group_payload(rest.unclassified),
        "excluded_not_estimated": rest.excluded_not_estimated,
        "excluded_missing_duration": rest.excluded_missing_duration,
        "excluded_label_change_or_unknown": rest.excluded_label_change_or_unknown,
        "excluded_unchecked": rest.excluded_unchecked,
    }


def _group_payload(group: RestGroup) -> dict[str, Any]:
    return {
        "median_seconds": group.median_seconds,
        "rest_count": group.rest_count,
        "estimated_rest_count": group.estimated_rest_count,
    }


def _optional_seconds(milliseconds: int | None) -> float | None:
    return None if milliseconds is None else milliseconds / 1000


def _range(milliseconds: tuple[int, int] | None) -> list[float] | None:
    return None if milliseconds is None else [milliseconds[0] / 1000, milliseconds[1] / 1000]
