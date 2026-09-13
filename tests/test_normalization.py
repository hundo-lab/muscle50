from __future__ import annotations

import json
from pathlib import Path

import pytest

from muscle50.domain.activity import ActivityType
from muscle50.domain.normalization import (
    NormalizationError,
    activity_id_from,
    canonical_type,
    normalize_activity,
    normalize_strength_sets,
)


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("trail_running", ActivityType.RUNNING),
        ("open_water_swimming", ActivityType.SWIMMING),
        ("strength_training", ActivityType.STRENGTH),
        ("cardio_training", ActivityType.OTHER),
        ("future_garmin_type", ActivityType.OTHER),
    ],
)
def test_activity_type_mapping(source: str, expected: ActivityType) -> None:
    assert canonical_type(source) is expected


@pytest.mark.parametrize("value", [None, True, 0, -1, "bad"])
def test_invalid_activity_id_is_rejected(value: object) -> None:
    with pytest.raises(NormalizationError):
        activity_id_from({"activityId": value})


def _synthetic_strength_sets() -> dict[str, object]:
    path = Path(__file__).parent / "fixtures" / "synthetic_strength_sets.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_strength_sets_preserve_source_fields_and_normalize_weight() -> None:
    strength_sets = normalize_strength_sets("222", _synthetic_strength_sets())

    assert len(strength_sets) == 5
    first = strength_sets[0]
    assert first.sequence == 1
    assert first.source_message_index == 0
    assert first.source_exercise_category == "BENCH_PRESS"
    assert first.source_exercise_name == "BARBELL_BENCH_PRESS"
    assert first.source_exercise_key == "BARBELL_BENCH_PRESS"
    assert first.display_exercise_name == "Barbell Bench Press"
    assert first.source_exercise_probability == 98.5
    assert first.source_weight == 60000
    assert first.source_weight_unit == "g"
    assert first.normalized_weight_kg == 60
    assert first.duration_seconds == 35.5
    assert first.started_at == "2026-01-03T06:10:00.0"
    assert first.workout_step_index == 1

    rest = strength_sets[1]
    assert rest.set_type == "REST"
    assert rest.reps is None
    assert rest.source_weight is None
    assert rest.normalized_weight_kg is None
    assert rest.display_exercise_name is None
    assert strength_sets[2].duration_seconds is None


def test_only_explicit_active_sets_contribute_to_totals() -> None:
    activity = normalize_activity(
        {"activityId": 222, "activityType": {"typeKey": "strength_training"}},
        {},
        _synthetic_strength_sets(),
    )
    metrics = {metric.key: metric.value for metric in activity.metrics}

    assert metrics["set_count"] == 3
    assert metrics["rep_count"] == 30
    assert len(activity.strength_sets) == 5


def test_rep_total_is_unknown_when_an_active_set_has_no_repetition_count() -> None:
    exercise_sets = _synthetic_strength_sets()
    sets = exercise_sets["exerciseSets"]
    assert isinstance(sets, list)
    active_set = sets[0]
    assert isinstance(active_set, dict)
    active_set.pop("repetitionCount")

    activity = normalize_activity(
        {"activityId": 222, "activityType": {"typeKey": "strength_training"}},
        {},
        exercise_sets,
    )
    metrics = {metric.key: metric.value for metric in activity.metrics}

    assert metrics["set_count"] == 3
    assert "rep_count" not in metrics


@pytest.mark.parametrize("exercise_sets", [{}, {"activityId": 222}, {"activityId": 222, "exerciseSets": "bad"}])
def test_missing_or_invalid_exercise_set_list_does_not_create_zero_totals(
    exercise_sets: dict[str, object],
) -> None:
    activity = normalize_activity(
        {"activityId": 222, "activityType": {"typeKey": "strength_training"}},
        {},
        exercise_sets,
    )

    assert "set_count" not in {metric.key for metric in activity.metrics}
    assert "rep_count" not in {metric.key for metric in activity.metrics}
    assert activity.strength_sets == ()


def test_explicit_empty_exercise_set_list_creates_known_zero_totals() -> None:
    activity = normalize_activity(
        {"activityId": 222, "activityType": {"typeKey": "strength_training"}},
        {},
        {"activityId": 222, "exerciseSets": []},
    )
    metrics = {metric.key: metric.value for metric in activity.metrics}

    assert metrics == {"set_count": 0, "rep_count": 0}


def test_exercise_set_activity_id_must_match() -> None:
    with pytest.raises(NormalizationError, match="does not match"):
        normalize_strength_sets("999", _synthetic_strength_sets())
