"""Pure Garmin-to-muscle50 normalization."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from muscle50.domain.activity import ActivityMetric, ActivityType, NormalizedActivity

_TYPE_MAP: dict[str, ActivityType] = {
    "running": ActivityType.RUNNING,
    "trail_running": ActivityType.RUNNING,
    "treadmill_running": ActivityType.RUNNING,
    "indoor_running": ActivityType.RUNNING,
    "lap_swimming": ActivityType.SWIMMING,
    "open_water_swimming": ActivityType.SWIMMING,
    "swimming": ActivityType.SWIMMING,
    "strength_training": ActivityType.STRENGTH,
    "cycling": ActivityType.CYCLING,
    "road_biking": ActivityType.CYCLING,
    "indoor_cycling": ActivityType.CYCLING,
    "walking": ActivityType.WALKING,
}


class NormalizationError(ValueError):
    """Raised when Garmin data lacks a stable activity identity."""


def activity_id_from(raw: Mapping[str, Any]) -> str:
    value = raw.get("activityId")
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise NormalizationError("Garmin activityId must be a positive integer")
    try:
        numeric = int(value)
    except (TypeError, ValueError) as exc:
        raise NormalizationError("Garmin activityId must be a positive integer") from exc
    if numeric <= 0:
        raise NormalizationError("Garmin activityId must be a positive integer")
    return str(numeric)


def source_type_from(raw: Mapping[str, Any]) -> str:
    activity_type = raw.get("activityType")
    if isinstance(activity_type, Mapping):
        key = activity_type.get("typeKey")
        if isinstance(key, str) and key.strip():
            return key.strip().lower()
    key = raw.get("activityTypeKey")
    return key.strip().lower() if isinstance(key, str) and key.strip() else "unknown"


def canonical_type(source_type_key: str) -> ActivityType:
    return _TYPE_MAP.get(source_type_key, ActivityType.OTHER)


def normalize_activity(
    summary: Mapping[str, Any],
    activity: Mapping[str, Any],
    exercise_sets: Mapping[str, Any] | None = None,
) -> NormalizedActivity:
    source = dict(summary)
    source.update(activity)
    source_id = activity_id_from(source)
    source_type = source_type_from(source)
    activity_type = canonical_type(source_type)

    metrics: list[ActivityMetric] = []
    _append_metric(metrics, source, "averageRunningCadenceInStepsPerMinute", "cadence", "spm")
    _append_metric(metrics, source, "averageStrideLength", "stride_length", "cm")
    _append_pool_length(metrics, source)
    _append_metric(metrics, source, "lapCount", "lap_count", "count")
    _append_metric(metrics, source, "avgSwolf", "average_swolf", "score")
    _append_metric(metrics, source, "avgStrokeDistance", "average_stroke_distance", "m")

    if activity_type is ActivityType.STRENGTH and exercise_sets:
        set_list = exercise_sets.get("exerciseSets")
        if isinstance(set_list, Sequence) and not isinstance(set_list, (str, bytes)):
            # Older payloads may omit setType; retain those as active for backward
            # compatibility. Explicit REST/other rows are never workout sets.
            workout_sets = [item for item in set_list if isinstance(item, Mapping) and _is_active_strength_set(item)]
            reps = sum(_as_float(item.get("repetitionCount")) or 0 for item in workout_sets)
            metrics.extend(
                [
                    ActivityMetric("set_count", len(workout_sets), "count", "exercise_sets"),
                    ActivityMetric("rep_count", int(reps), "count", "exercise_sets"),
                ]
            )

    return NormalizedActivity(
        source_activity_id=source_id,
        source_type_key=source_type,
        canonical_type=activity_type,
        name=_as_str(source.get("activityName")),
        started_at_utc=_normalize_datetime(source.get("startTimeGMT"), assume_utc=True),
        started_at_local=_normalize_datetime(source.get("startTimeLocal"), assume_utc=False),
        timezone_name=_timezone_name(source),
        elapsed_seconds=_first_number(source, "elapsedDuration", "duration"),
        moving_seconds=_first_number(source, "movingDuration", "duration"),
        distance_meters=_as_float(source.get("distance")),
        calories_kcal=_as_float(source.get("calories")),
        average_hr_bpm=_as_float(source.get("averageHR")),
        max_hr_bpm=_as_float(source.get("maxHR")),
        elevation_gain_meters=_as_float(source.get("elevationGain")),
        metrics=tuple(metrics),
    )


def _timezone_name(source: Mapping[str, Any]) -> str | None:
    timezone = source.get("timeZoneUnitDTO")
    if isinstance(timezone, Mapping):
        return _as_str(timezone.get("unitKey"))
    return _as_str(source.get("timeZoneId"))


def _append_metric(
    target: list[ActivityMetric],
    source: Mapping[str, Any],
    source_key: str,
    metric_key: str,
    unit: str | None,
) -> None:
    value = _as_float(source.get(source_key))
    if value is not None:
        target.append(ActivityMetric(metric_key, value, unit, source_key))


def _append_pool_length(target: list[ActivityMetric], source: Mapping[str, Any]) -> None:
    value = _as_float(source.get("poolLength"))
    if value is None:
        return
    unit_value = source.get("poolLengthUnit")
    if isinstance(unit_value, Mapping):
        unit_value = unit_value.get("unitKey")
    unit_key = unit_value.strip().lower() if isinstance(unit_value, str) else None
    if unit_key in {"meter", "meters", "metre", "metres", "m"}:
        normalized_value, normalized_unit = value, "m"
    elif unit_key in {"yard", "yards", "yd"}:
        normalized_value, normalized_unit = value * 0.9144, "m"
    else:
        # Preserve the numeric source value but never claim a unit we cannot prove.
        normalized_value, normalized_unit = value, None
    target.append(ActivityMetric("pool_length", normalized_value, normalized_unit, "poolLength"))


def _is_active_strength_set(item: Mapping[str, Any]) -> bool:
    set_type = item.get("setType")
    return set_type is None or (isinstance(set_type, str) and set_type.strip().upper() == "ACTIVE")


def _first_number(source: Mapping[str, Any], *keys: str) -> float | None:
    for key in keys:
        value = _as_float(source.get(key))
        if value is not None:
            return value
    return None


def _as_float(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_str(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _normalize_datetime(value: Any, *, assume_utc: bool) -> str | None:
    text = _as_str(value)
    if text is None:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if assume_utc and parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.isoformat()
