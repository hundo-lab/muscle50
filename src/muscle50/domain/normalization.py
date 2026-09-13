"""Pure Garmin-to-muscle50 normalization."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from muscle50.domain.activity import ActivityMetric, ActivityType, NormalizedActivity, StrengthSet

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
    has_strength_set_list = exercise_sets is not None and _has_exercise_set_list(exercise_sets)
    strength_sets = (
        normalize_strength_sets(source_id, exercise_sets)
        if activity_type is ActivityType.STRENGTH and exercise_sets is not None and has_strength_set_list
        else ()
    )

    metrics: list[ActivityMetric] = []
    _append_metric(metrics, source, "averageRunningCadenceInStepsPerMinute", "cadence", "spm")
    _append_metric(metrics, source, "averageStrideLength", "stride_length", "cm")
    _append_pool_length(metrics, source)
    _append_metric(metrics, source, "lapCount", "lap_count", "count")
    _append_metric(metrics, source, "avgSwolf", "average_swolf", "score")
    _append_metric(metrics, source, "avgStrokeDistance", "average_stroke_distance", "m")

    if activity_type is ActivityType.STRENGTH and has_strength_set_list:
        metrics.extend(strength_set_metrics(strength_sets))

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
        strength_sets=strength_sets,
    )


def normalize_strength_sets(
    source_activity_id: str,
    exercise_sets: Mapping[str, Any],
) -> tuple[StrengthSet, ...]:
    """Normalize Garmin exerciseSets without modifying or filling missing source values."""
    payload_activity_id = exercise_sets.get("activityId")
    if payload_activity_id is not None and activity_id_from({"activityId": payload_activity_id}) != source_activity_id:
        raise NormalizationError("Garmin exercise sets activityId does not match the activity")

    raw_sets = exercise_sets.get("exerciseSets")
    if not isinstance(raw_sets, Sequence) or isinstance(raw_sets, (str, bytes)):
        return ()

    normalized: list[StrengthSet] = []
    for position, raw_set in enumerate(raw_sets, start=1):
        if not isinstance(raw_set, Mapping):
            continue
        category, name, probability = _primary_exercise(raw_set)
        exercise_key = name or category
        source_weight = _as_float(raw_set.get("weight"))
        # Garmin Connect's exerciseSets endpoint represents weight in grams. The
        # source value and its endpoint-defined unit remain alongside the kg value.
        source_weight_unit = "g" if source_weight is not None else None
        normalized.append(
            StrengthSet(
                sequence=position,
                source_message_index=_as_int(raw_set.get("messageIndex")),
                source_exercise_category=category,
                source_exercise_name=name,
                source_exercise_key=exercise_key,
                display_exercise_name=_display_exercise_name(exercise_key),
                source_exercise_probability=probability,
                set_type=_normalized_set_type(raw_set.get("setType")),
                reps=_as_int(raw_set.get("repetitionCount")),
                source_weight=source_weight,
                source_weight_unit=source_weight_unit,
                normalized_weight_kg=source_weight / 1000 if source_weight is not None else None,
                duration_seconds=_as_float(raw_set.get("duration")),
                started_at=_as_str(raw_set.get("startTime")),
                workout_step_index=_as_int(raw_set.get("wktStepIndex")),
            )
        )
    return tuple(normalized)


def strength_set_metrics(strength_sets: tuple[StrengthSet, ...]) -> tuple[ActivityMetric, ...]:
    workout_sets = [item for item in strength_sets if item.set_type == "ACTIVE"]
    metrics = [ActivityMetric("set_count", len(workout_sets), "count", "exercise_sets")]
    if all(item.reps is not None for item in workout_sets):
        metrics.append(
            ActivityMetric(
                "rep_count",
                sum(item.reps for item in workout_sets if item.reps is not None),
                "count",
                "exercise_sets",
            )
        )
    return tuple(metrics)


def has_exercise_set_list(exercise_sets: Mapping[str, Any]) -> bool:
    """Return whether Garmin explicitly supplied an exerciseSets array."""
    return _has_exercise_set_list(exercise_sets)


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


def _primary_exercise(item: Mapping[str, Any]) -> tuple[str | None, str | None, float | None]:
    exercises = item.get("exercises")
    if not isinstance(exercises, Sequence) or isinstance(exercises, (str, bytes)):
        return None, None, None
    for candidate in exercises:
        if isinstance(candidate, Mapping):
            return (
                _as_str(candidate.get("category")),
                _as_str(candidate.get("name")),
                _as_float(candidate.get("probability")),
            )
    return None, None, None


def _has_exercise_set_list(exercise_sets: Mapping[str, Any]) -> bool:
    raw_sets = exercise_sets.get("exerciseSets")
    return isinstance(raw_sets, Sequence) and not isinstance(raw_sets, (str, bytes))


def _display_exercise_name(source_key: str | None) -> str | None:
    if source_key is None:
        return None
    return " ".join(part.capitalize() for part in source_key.split("_") if part)


def _normalized_set_type(value: Any) -> str | None:
    text = _as_str(value)
    return text.strip().upper() if text is not None and text.strip() else None


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


def _as_int(value: Any) -> int | None:
    numeric = _as_float(value)
    if numeric is None or not numeric.is_integer():
        return None
    return int(numeric)


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
