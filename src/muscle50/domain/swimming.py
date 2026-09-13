"""Normalized and derived swimming domain types."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class GarminSource:
    """Location and lossless JSON snapshot of a Garmin source object."""

    path: str
    fields_json: str


@dataclass(frozen=True)
class SwimDistance:
    """Garmin distance plus an optional, separately supplied correction."""

    garmin_meters: float | None
    corrected_meters: float | None = None


@dataclass(frozen=True)
class SwimLength:
    sequence: int
    sequence_in_lap: int
    source_message_index: int | None
    start_time_utc: str | None
    length_type: str | None
    stroke_type: str | None
    distance: SwimDistance
    duration_seconds: float | None
    moving_seconds: float | None
    elapsed_seconds: float | None
    rest_duration_seconds: float | None
    average_speed_mps: float | None
    stroke_count: int | None
    swolf: float | None
    average_hr_bpm: float | None
    max_hr_bpm: float | None
    source: GarminSource


@dataclass(frozen=True)
class SwimLap:
    sequence: int
    source_lap_index: int | None
    source_message_index: int | None
    start_time_utc: str | None
    intensity_type: str | None
    stroke_type: str | None
    distance: SwimDistance
    duration_seconds: float | None
    moving_seconds: float | None
    elapsed_seconds: float | None
    rest_duration_seconds: float | None
    average_speed_mps: float | None
    active_length_count: int | None
    total_length_count: int | None
    stroke_count: int | None
    swolf: float | None
    average_hr_bpm: float | None
    max_hr_bpm: float | None
    lengths: tuple[SwimLength, ...]
    source: GarminSource


@dataclass(frozen=True)
class NormalizedSwimActivity:
    source_activity_id: str
    source_type_key: str
    pool_length_meters: float | None
    source_pool_length: float | None
    source_pool_length_unit: str | None
    source_active_length_count: int | None
    splits_available: bool
    laps: tuple[SwimLap, ...]
    source: GarminSource
    normalizer_version: int = 1


@dataclass(frozen=True)
class DerivedSwimMetrics:
    """Values computed from normalized fields, never written back as Garmin data."""

    effective_distance_meters: float | None
    pace_seconds_per_100_meters: float | None
    rest_duration_seconds: float | None


def derive_length_metrics(length: SwimLength) -> DerivedSwimMetrics:
    rest_duration = length.rest_duration_seconds
    if rest_duration is None and length.length_type == "idle":
        rest_duration = length.elapsed_seconds
        if rest_duration is None:
            rest_duration = length.duration_seconds
    return _derive_metrics(
        length.distance,
        length.average_speed_mps,
        length.duration_seconds,
        rest_duration,
    )


def derive_lap_metrics(lap: SwimLap) -> DerivedSwimMetrics:
    rest_duration = lap.rest_duration_seconds
    if rest_duration is None:
        idle_rests: list[float] = []
        for length in lap.lengths:
            if length.length_type != "idle":
                continue
            length_rest = derive_length_metrics(length).rest_duration_seconds
            if length_rest is not None:
                idle_rests.append(length_rest)
        if idle_rests:
            rest_duration = sum(idle_rests)
        elif lap.elapsed_seconds is not None and lap.duration_seconds is not None:
            difference = lap.elapsed_seconds - lap.duration_seconds
            if difference >= 0:
                rest_duration = difference
    return _derive_metrics(
        lap.distance,
        lap.average_speed_mps,
        lap.duration_seconds,
        rest_duration,
    )


def _derive_metrics(
    distance: SwimDistance,
    average_speed_mps: float | None,
    duration_seconds: float | None,
    rest_duration_seconds: float | None,
) -> DerivedSwimMetrics:
    effective_distance = distance.corrected_meters
    if effective_distance is None:
        effective_distance = distance.garmin_meters

    pace = None
    if distance.corrected_meters is not None and effective_distance is not None and effective_distance > 0:
        if duration_seconds is not None:
            pace = duration_seconds * 100.0 / effective_distance
    elif average_speed_mps is not None and average_speed_mps > 0:
        pace = 100.0 / average_speed_mps
    elif effective_distance is not None and effective_distance > 0 and duration_seconds is not None:
        pace = duration_seconds * 100.0 / effective_distance

    return DerivedSwimMetrics(
        effective_distance_meters=effective_distance,
        pace_seconds_per_100_meters=pace,
        rest_duration_seconds=rest_duration_seconds,
    )
