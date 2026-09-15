from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from muscle50.domain.swim_normalization import SwimNormalizationError, normalize_garmin_swim
from muscle50.domain.swimming import derive_lap_metrics, derive_length_metrics


@pytest.fixture
def pool_swim() -> dict[str, Any]:
    fixture_path = Path(__file__).parent / "fixtures" / "garmin_pool_swim.json"
    data: object = json.loads(fixture_path.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def test_normalizes_activity_lap_length_hierarchy_without_using_source_indices_as_sequence(
    pool_swim: dict[str, Any],
) -> None:
    swim = normalize_garmin_swim(pool_swim["summary"], pool_swim["activity"], pool_swim["splits"])

    assert swim.source_activity_id == "900001"
    assert swim.pool_length_meters == 25
    assert swim.source_pool_length == 25
    assert swim.source_pool_length_unit == "meter"
    assert swim.source_active_length_count == 6
    assert swim.splits_available is True
    assert [lap.sequence for lap in swim.laps] == [0, 1, 2]
    assert [lap.source_lap_index for lap in swim.laps] == [7, 11, 15]
    assert [length.sequence for lap in swim.laps for length in lap.lengths] == [0, 1, 2, 3, 4]
    assert [length.source_message_index for length in swim.laps[0].lengths] == [101, 102, 103]


def test_preserves_swim_metrics_mixed_strokes_drill_and_idle_rest(pool_swim: dict[str, Any]) -> None:
    swim = normalize_garmin_swim(pool_swim["summary"], pool_swim["activity"], pool_swim["splits"])

    first_lap = swim.laps[0]
    first_length = first_lap.lengths[0]
    idle_length = first_lap.lengths[2]
    assert first_lap.distance.garmin_meters == 50
    assert first_lap.distance.corrected_meters is None
    assert first_lap.duration_seconds == 55
    assert first_lap.elapsed_seconds == 70
    assert first_lap.stroke_type == "freestyle"
    assert first_lap.stroke_count == 29
    assert first_lap.swolf == 42.5
    assert first_lap.average_hr_bpm == 128
    assert first_lap.max_hr_bpm == 140
    assert first_lap.active_length_count == 2
    assert first_lap.total_length_count == 3
    assert first_length.stroke_count == 14
    assert first_length.swolf == 41
    assert idle_length.length_type == "idle"
    assert idle_length.stroke_type is None
    assert derive_length_metrics(idle_length).rest_duration_seconds == 15

    assert swim.laps[1].stroke_type == "mixed"
    assert [length.stroke_type for length in swim.laps[1].lengths] == ["backstroke", "breaststroke"]
    assert swim.laps[2].stroke_type == "drill"
    assert swim.laps[2].active_length_count == 2
    assert swim.laps[2].lengths == ()


def test_derived_metrics_are_separate_from_garmin_normalization(pool_swim: dict[str, Any]) -> None:
    swim = normalize_garmin_swim(pool_swim["summary"], pool_swim["activity"], pool_swim["splits"])

    first_lap = swim.laps[0]
    derived = derive_lap_metrics(first_lap)
    assert derived.effective_distance_meters == 50
    assert derived.pace_seconds_per_100_meters == pytest.approx(110)
    assert derived.rest_duration_seconds == 15
    assert first_lap.rest_duration_seconds is None


def test_corrected_distance_changes_effective_distance_without_overwriting_garmin_distance(
    pool_swim: dict[str, Any],
) -> None:
    swim = normalize_garmin_swim(pool_swim["summary"], pool_swim["activity"], pool_swim["splits"])
    garmin_lap = swim.laps[0]
    corrected_lap = replace(
        garmin_lap,
        distance=replace(garmin_lap.distance, corrected_meters=75),
    )

    derived = derive_lap_metrics(corrected_lap)

    assert garmin_lap.distance.garmin_meters == 50
    assert corrected_lap.distance.garmin_meters == 50
    assert derived.effective_distance_meters == 75
    assert derived.pace_seconds_per_100_meters == pytest.approx(55 * 100 / 75)


def test_preserves_complete_garmin_source_fields(pool_swim: dict[str, Any]) -> None:
    swim = normalize_garmin_swim(pool_swim["summary"], pool_swim["activity"], pool_swim["splits"])

    source_fields = json.loads(swim.laps[0].source.fields_json)
    assert swim.laps[0].source.path == "splits.lapDTOs[0]"
    assert source_fields["garminFutureField"] == "preserve-me"
    assert source_fields["lengthDTOs"][0]["messageIndex"] == 101


@pytest.mark.parametrize(
    ("pool_length", "unit", "expected_meters"),
    [(25, "meter", 25), (50, "meter", 50), (25, "yard", 22.86), (25, "unknown", None)],
)
def test_pool_length_conversion_requires_a_known_source_unit(
    pool_length: int,
    unit: str,
    expected_meters: float | None,
) -> None:
    summary = {
        "activityId": 1,
        "activityType": {"typeKey": "lap_swimming"},
        "poolLength": pool_length,
        "poolLengthUnit": {"unitKey": unit},
    }

    swim = normalize_garmin_swim(summary, {}, {"activityId": 1, "lapDTOs": []})

    assert swim.pool_length_meters == expected_meters
    assert swim.source_pool_length == pool_length
    assert swim.source_pool_length_unit == unit


def test_missing_optional_values_are_not_invented() -> None:
    summary = {"activityId": 2, "activityTypeKey": "lap_swimming"}
    splits = {"activityId": 2, "lapDTOs": [{"lengthDTOs": [{"lengthType": "ACTIVE"}]}]}

    swim = normalize_garmin_swim(summary, {}, splits)

    lap = swim.laps[0]
    length = lap.lengths[0]
    assert swim.pool_length_meters is None
    assert lap.distance.garmin_meters is None
    assert lap.distance.corrected_meters is None
    assert lap.stroke_type is None
    assert lap.swolf is None
    assert length.distance.garmin_meters is None
    assert length.stroke_count is None
    assert length.average_hr_bpm is None
    assert derive_length_metrics(length).pace_seconds_per_100_meters is None


@pytest.mark.parametrize("duration", [0, -1])
def test_zero_or_negative_duration_does_not_produce_a_derived_pace(duration: int) -> None:
    summary = {"activityId": 20, "activityTypeKey": "lap_swimming"}
    splits = {
        "activityId": 20,
        "lapDTOs": [{"distance": 25, "duration": duration, "lengthDTOs": []}],
    }

    swim = normalize_garmin_swim(summary, {}, splits)

    assert swim.laps[0].duration_seconds == duration
    assert derive_lap_metrics(swim.laps[0]).pace_seconds_per_100_meters is None


def test_missing_optional_splits_is_distinct_from_an_empty_split_response() -> None:
    summary = {"activityId": 3, "activityTypeKey": "lap_swimming"}

    missing = normalize_garmin_swim(summary, {}, None)
    empty = normalize_garmin_swim(summary, {}, {"activityId": 3, "lapDTOs": []})

    assert missing.splits_available is False
    assert empty.splits_available is True
    assert missing.laps == empty.laps == ()


def test_rejects_mismatched_activity_ids_and_malformed_hierarchy() -> None:
    summary = {"activityId": 4, "activityTypeKey": "lap_swimming"}

    with pytest.raises(SwimNormalizationError, match="activityId mismatch"):
        normalize_garmin_swim(summary, {}, {"activityId": 5, "lapDTOs": []})
    with pytest.raises(SwimNormalizationError, match="splits.lapDTOs must be an array"):
        normalize_garmin_swim(summary, {}, {"activityId": 4, "lapDTOs": {}})
    with pytest.raises(SwimNormalizationError, match=r"lengthDTOs\[0\] must be an object"):
        normalize_garmin_swim(summary, {}, {"activityId": 4, "lapDTOs": [{"lengthDTOs": [1]}]})


def test_rejects_non_swimming_activity() -> None:
    with pytest.raises(SwimNormalizationError, match="activity type is not swimming"):
        normalize_garmin_swim(
            {"activityId": 5, "activityTypeKey": "running"},
            {},
            {"activityId": 5, "lapDTOs": []},
        )
