"""Pure normalization of Garmin pool-swimming splits."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from muscle50.domain.activity import ActivityType
from muscle50.domain.normalization import NormalizationError, activity_id_from, canonical_type, source_type_from
from muscle50.domain.swimming import (
    GarminSource,
    NormalizedSwimActivity,
    SwimDistance,
    SwimLap,
    SwimLength,
)


class SwimNormalizationError(NormalizationError):
    """Raised when a Garmin swim payload cannot be normalized without data loss."""


def normalize_garmin_swim(
    summary: Mapping[str, Any],
    activity: Mapping[str, Any],
    splits: Mapping[str, Any] | None,
) -> NormalizedSwimActivity:
    """Normalize the split hierarchy while preserving every Garmin source object."""

    source = dict(summary)
    source.update(activity)
    source_activity_id = activity_id_from(source)
    source_type_key = source_type_from(source)
    if canonical_type(source_type_key) is not ActivityType.SWIMMING:
        raise SwimNormalizationError(f"activity type is not swimming: {source_type_key}")

    source_pool_length = _number(source, "poolLength")
    source_pool_unit = _pool_unit(source)
    pool_length_meters = _distance_in_meters(source_pool_length, source_pool_unit)

    laps: list[SwimLap] = []
    length_sequence = 0
    if splits is not None:
        _validate_split_activity_id(source_activity_id, splits)
        raw_laps = _object_sequence(splits, "lapDTOs", "splits.lapDTOs")
        for lap_sequence, raw_lap in enumerate(raw_laps):
            raw_lengths = _object_sequence(
                raw_lap,
                "lengthDTOs",
                f"splits.lapDTOs[{lap_sequence}].lengthDTOs",
            )
            lengths: list[SwimLength] = []
            for sequence_in_lap, raw_length in enumerate(raw_lengths):
                path = f"splits.lapDTOs[{lap_sequence}].lengthDTOs[{sequence_in_lap}]"
                lengths.append(
                    _normalize_length(
                        raw_length,
                        path=path,
                        sequence=length_sequence,
                        sequence_in_lap=sequence_in_lap,
                    )
                )
                length_sequence += 1
            laps.append(
                _normalize_lap(
                    raw_lap,
                    path=f"splits.lapDTOs[{lap_sequence}]",
                    sequence=lap_sequence,
                    lengths=tuple(lengths),
                )
            )

    return NormalizedSwimActivity(
        source_activity_id=source_activity_id,
        source_type_key=source_type_key,
        pool_length_meters=pool_length_meters,
        source_pool_length=source_pool_length,
        source_pool_length_unit=source_pool_unit,
        source_active_length_count=_first_integer(source, "numberOfActiveLengths", "activeLengths"),
        splits_available=splits is not None,
        laps=tuple(laps),
        source=_snapshot("summary+activity", source),
    )


def _normalize_lap(
    raw: Mapping[str, Any],
    *,
    path: str,
    sequence: int,
    lengths: tuple[SwimLength, ...],
) -> SwimLap:
    return SwimLap(
        sequence=sequence,
        source_lap_index=_integer(raw, "lapIndex"),
        source_message_index=_integer(raw, "messageIndex"),
        start_time_utc=_utc_datetime(raw.get("startTimeGMT")),
        intensity_type=_text_key(raw.get("intensityType")),
        stroke_type=_first_text_key(raw, "swimStroke", "strokeType"),
        distance=SwimDistance(garmin_meters=_number(raw, "distance")),
        duration_seconds=_number(raw, "duration"),
        moving_seconds=_number(raw, "movingDuration"),
        elapsed_seconds=_number(raw, "elapsedDuration"),
        rest_duration_seconds=_number(raw, "restDuration"),
        average_speed_mps=_number(raw, "averageSpeed"),
        active_length_count=_first_integer(raw, "numberOfActiveLengths", "numActiveLengths"),
        total_length_count=_first_integer(raw, "numberOfLengths", "numLengths"),
        stroke_count=_first_integer(
            raw,
            "strokeCount",
            "strokes",
            "totalStrokes",
            "totalNumberOfStrokes",
        ),
        swolf=_first_number(raw, "avgSwolf", "averageSwolf", "averageSWOLF", "swolf"),
        average_hr_bpm=_number(raw, "averageHR"),
        max_hr_bpm=_number(raw, "maxHR"),
        lengths=lengths,
        source=_snapshot(path, raw),
    )


def _normalize_length(
    raw: Mapping[str, Any],
    *,
    path: str,
    sequence: int,
    sequence_in_lap: int,
) -> SwimLength:
    return SwimLength(
        sequence=sequence,
        sequence_in_lap=sequence_in_lap,
        source_message_index=_integer(raw, "messageIndex"),
        start_time_utc=_utc_datetime(raw.get("startTimeGMT")),
        length_type=_text_key(raw.get("lengthType")),
        stroke_type=_first_text_key(raw, "swimStroke", "strokeType"),
        distance=SwimDistance(garmin_meters=_number(raw, "distance")),
        duration_seconds=_number(raw, "duration"),
        moving_seconds=_number(raw, "movingDuration"),
        elapsed_seconds=_number(raw, "elapsedDuration"),
        rest_duration_seconds=_number(raw, "restDuration"),
        average_speed_mps=_number(raw, "averageSpeed"),
        stroke_count=_first_integer(
            raw,
            "strokeCount",
            "strokes",
            "totalStrokes",
            "totalNumberOfStrokes",
        ),
        swolf=_first_number(raw, "avgSwolf", "averageSwolf", "averageSWOLF", "swolf"),
        average_hr_bpm=_number(raw, "averageHR"),
        max_hr_bpm=_number(raw, "maxHR"),
        source=_snapshot(path, raw),
    )


def _validate_split_activity_id(source_activity_id: str, splits: Mapping[str, Any]) -> None:
    if "activityId" not in splits:
        return
    try:
        split_activity_id = activity_id_from(splits)
    except ValueError as exc:
        raise SwimNormalizationError("splits.activityId is invalid") from exc
    if split_activity_id != source_activity_id:
        raise SwimNormalizationError(f"activityId mismatch: activity={source_activity_id}, splits={split_activity_id}")


def _object_sequence(source: Mapping[str, Any], key: str, path: str) -> tuple[Mapping[str, Any], ...]:
    value = source.get(key)
    if value is None:
        return ()
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise SwimNormalizationError(f"{path} must be an array")
    items: list[Mapping[str, Any]] = []
    for index, item in enumerate(value):
        if not isinstance(item, Mapping):
            raise SwimNormalizationError(f"{path}[{index}] must be an object")
        items.append(item)
    return tuple(items)


def _pool_unit(source: Mapping[str, Any]) -> str | None:
    value = source.get("poolLengthUnit")
    if value is None:
        value = source.get("unitOfPoolLength")
    return _text_key(value)


def _distance_in_meters(value: float | None, unit: str | None) -> float | None:
    if value is None:
        return None
    if unit in {"meter", "meters", "metre", "metres", "m"}:
        return value
    if unit in {"yard", "yards", "yd"}:
        return value * 0.9144
    return None


def _number(source: Mapping[str, Any], key: str) -> float | None:
    return _as_float(source.get(key))


def _first_number(source: Mapping[str, Any], *keys: str) -> float | None:
    for key in keys:
        value = _number(source, key)
        if value is not None:
            return value
    return None


def _integer(source: Mapping[str, Any], key: str) -> int | None:
    value = source.get(key)
    if isinstance(value, bool) or value is None:
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return int(numeric) if numeric.is_integer() else None


def _first_integer(source: Mapping[str, Any], *keys: str) -> int | None:
    for key in keys:
        value = _integer(source, key)
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


def _first_text_key(source: Mapping[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = _text_key(source.get(key))
        if value is not None:
            return value
    return None


def _text_key(value: Any) -> str | None:
    if isinstance(value, Mapping):
        value = value.get("typeKey", value.get("key", value.get("unitKey")))
    return value.strip().lower() if isinstance(value, str) and value.strip() else None


def _utc_datetime(value: Any) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.isoformat()


def _snapshot(path: str, source: Mapping[str, Any]) -> GarminSource:
    try:
        fields_json = json.dumps(source, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise SwimNormalizationError(f"{path} is not valid Garmin JSON") from exc
    return GarminSource(path=path, fields_json=fields_json)
