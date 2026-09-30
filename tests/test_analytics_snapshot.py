from __future__ import annotations

import dataclasses
import json
import random
from collections.abc import Sequence
from datetime import date
from typing import Any

import pytest
from analytics_builders import (
    activity,
    lap,
    length,
    load_metrics,
    recovery,
    strength_set,
    swim_detail,
    uniform_lap,
)

from muscle50.domain.activity import ActivityMetric, ActivityType, NormalizedActivity
from muscle50.domain.activity_load import ACTIVITY_LOAD_METRIC_KEYS
from muscle50.domain.analytics import (
    LOAD_METRIC_AGGREGATION,
    MAX_LOOKBACK_DAYS,
    AggregationRule,
    InvalidSnapshotWindowError,
    MetricAggregate,
    QualityIssueCode,
    RecoveryRule,
    TrainingSnapshot,
    build_training_snapshot,
    snapshot_window,
)
from muscle50.domain.recovery import DailyRecovery
from muscle50.presentation.terminal import render_training_snapshot, render_training_snapshot_json

AS_OF = date(2026, 3, 14)


def _snapshot(
    activities: Sequence[NormalizedActivity] = (),
    recoveries: Sequence[DailyRecovery] = (),
    days: int = 7,
    **kwargs: Any,
) -> TrainingSnapshot:
    return build_training_snapshot(AS_OF, days, activities, recoveries, **kwargs)


def _metric(aggregates: tuple[MetricAggregate, ...], key: str) -> MetricAggregate:
    return next(item for item in aggregates if item.key == key)


def _codes(snapshot: TrainingSnapshot) -> list[QualityIssueCode]:
    return [issue.code for issue in snapshot.quality_issues]


# Window


def test_window_is_inclusive_and_ends_on_as_of() -> None:
    window = snapshot_window(AS_OF, 7)

    assert window.start == date(2026, 3, 8)
    assert window.dates[0] == date(2026, 3, 8)
    assert window.dates[-1] == AS_OF
    assert len(window.dates) == 7


@pytest.mark.parametrize("days", [0, -1, MAX_LOOKBACK_DAYS + 1, True])
def test_window_rejects_out_of_range_lookback(days: int) -> None:
    with pytest.raises(InvalidSnapshotWindowError):
        snapshot_window(AS_OF, days)


def test_activities_are_selected_by_garmin_local_date_including_boundaries() -> None:
    snapshot = _snapshot(
        [
            activity("before", "2026-03-07T23:59:59"),
            activity("first", "2026-03-08T00:00:00"),
            activity("last", "2026-03-14T23:59:59"),
            activity("after", "2026-03-15T00:00:00"),
        ]
    )

    assert snapshot.activities.source_activity_ids == ("first", "last")
    assert snapshot.activities.training_dates == (date(2026, 3, 8), date(2026, 3, 14))


def test_undated_activities_are_reported_not_silently_dropped() -> None:
    snapshot = _snapshot([activity("undated", None)], undated_source_activity_ids=["other-undated"])

    assert snapshot.activities.activity_count == 0
    undated = [issue for issue in snapshot.quality_issues if issue.code is QualityIssueCode.UNDATED_ACTIVITY]
    assert [issue.source_activity_id for issue in undated] == ["other-undated", "undated"]


# Load metric semantics


def test_every_canonical_load_metric_has_exactly_one_explicit_rule() -> None:
    assert set(LOAD_METRIC_AGGREGATION) == ACTIVITY_LOAD_METRIC_KEYS
    assert LOAD_METRIC_AGGREGATION["aerobic_training_effect"] is AggregationRule.MAX
    assert LOAD_METRIC_AGGREGATION["anaerobic_training_effect"] is AggregationRule.MAX
    summed = {key for key, rule in LOAD_METRIC_AGGREGATION.items() if rule is AggregationRule.SUM}
    assert summed == ACTIVITY_LOAD_METRIC_KEYS - {"aerobic_training_effect", "anaerobic_training_effect"}


def test_additive_metrics_are_summed_and_training_effect_is_maxed_with_provenance() -> None:
    snapshot = _snapshot(
        [
            activity("a", "2026-03-10T08:00:00", metrics=load_metrics(training_load=40.0, aerobic_training_effect=2.5)),
            activity("b", "2026-03-11T08:00:00", metrics=load_metrics(training_load=60.5, aerobic_training_effect=3.9)),
        ]
    )
    load = snapshot.activities.load_metrics

    training_load = _metric(load, "training_load")
    assert training_load.rule is AggregationRule.SUM
    assert training_load.value == 100.5
    assert [(item.source_id, item.value) for item in training_load.values] == [("a", 40.0), ("b", 60.5)]
    aerobic = _metric(load, "aerobic_training_effect")
    assert aerobic.rule is AggregationRule.MAX
    assert aerobic.value == 3.9
    assert _metric(load, "hr_time_in_zone_3_seconds").value == 2.0
    assert _metric(load, "vigorous_intensity_minutes").value == 2.0  # raw, never doubled


def test_missing_metric_is_listed_as_missing_and_never_counted_as_zero() -> None:
    snapshot = _snapshot(
        [
            activity("has", "2026-03-10T08:00:00", metrics=load_metrics(training_load=30.0)),
            activity("lacks", "2026-03-11T08:00:00", metrics=load_metrics(training_load=None)),
            activity("none", "2026-03-12T08:00:00", metrics=()),
        ]
    )

    training_load = _metric(snapshot.activities.load_metrics, "training_load")
    assert training_load.value == 30.0
    assert training_load.missing_source_ids == ("lacks", "none")


def test_aggregate_with_no_values_is_none_not_zero() -> None:
    snapshot = _snapshot([activity("none", "2026-03-12T08:00:00", metrics=())])

    assert all(item.value is None for item in snapshot.activities.load_metrics)
    assert _snapshot().activities.elapsed_seconds.value is None


def test_non_numeric_load_metric_is_missing_and_reported() -> None:
    metrics = (*load_metrics(training_load=None), ActivityMetric("training_load", "high", "score", "x"))
    snapshot = _snapshot([activity("text", "2026-03-12T08:00:00", metrics=metrics)])

    assert _metric(snapshot.activities.load_metrics, "training_load").missing_source_ids == ("text",)
    assert QualityIssueCode.NON_NUMERIC_LOAD_METRIC in _codes(snapshot)


def test_activity_counts_by_type() -> None:
    snapshot = _snapshot(
        [
            activity("s1", "2026-03-10T08:00:00", ActivityType.STRENGTH),
            activity("s2", "2026-03-10T18:00:00", ActivityType.STRENGTH),
            activity("r1", "2026-03-11T08:00:00", ActivityType.RUNNING),
        ]
    )

    counts = {(item.canonical_type, item.source_type_key): item.count for item in snapshot.activities.by_type}
    assert counts == {("running", "running"): 1, ("strength", "strength_training"): 2}
    assert snapshot.activities.training_dates == (date(2026, 3, 10), date(2026, 3, 11))


def test_snapshot_is_independent_of_input_order() -> None:
    items = [
        activity(
            f"id{index}",
            f"2026-03-{8 + index % 7:02d}T0{index % 10}:00:00",
            metrics=load_metrics(training_load=0.1),
        )
        for index in range(20)
    ]
    shuffled = list(items)
    random.Random(7).shuffle(shuffled)

    first = render_training_snapshot_json(_snapshot(items))
    second = render_training_snapshot_json(_snapshot(shuffled))

    assert first == second


# Strength


def test_strength_totals_count_only_active_sets_and_keep_missing_reps_out() -> None:
    sets = (
        strength_set(1, reps=10, weight_kg=60.0),
        strength_set(2, set_type="REST", category=None, reps=None, weight_kg=None),
        strength_set(3, reps=8, weight_kg=70.0),
        strength_set(4, reps=None, weight_kg=70.0),
        strength_set(5, reps=0, weight_kg=70.0),
    )
    snapshot = _snapshot([activity("s", "2026-03-10T08:00:00", ActivityType.STRENGTH, strength_sets=sets)])
    strength = snapshot.strength

    assert strength.session_count == 1
    assert strength.set_row_count == 5
    assert strength.rest_set_count == 1
    assert strength.active_set_count == 4
    assert strength.reps == 18
    assert strength.sets_missing_reps == 1
    assert strength.zero_rep_sets == 1
    assert strength.volume_kg == 60.0 * 10 + 70.0 * 8
    assert strength.volume_set_count == 2
    missing_reps = [issue for issue in snapshot.quality_issues if issue.code is QualityIssueCode.STRENGTH_MISSING_REPS]
    assert missing_reps[0].set_sequences == (4,)


def test_volume_excludes_unknown_zero_and_sentinel_weights_by_reason() -> None:
    sets = (
        strength_set(1, reps=10, weight_kg=None),
        strength_set(2, reps=10, weight_kg=-0.001),
        strength_set(3, reps=10, weight_kg=0.0),
        strength_set(4, reps=None, weight_kg=50.0),
        strength_set(5, reps=0, weight_kg=50.0),
    )
    snapshot = _snapshot([activity("s", "2026-03-10T08:00:00", ActivityType.STRENGTH, strength_sets=sets)])
    strength = snapshot.strength

    assert strength.volume_kg is None
    assert strength.volume_set_count == 0
    excluded = strength.volume_exclusions
    assert (
        excluded.missing_weight,
        excluded.negative_weight,
        excluded.zero_weight,
        excluded.missing_reps,
        excluded.zero_reps,
    ) == (1, 1, 1, 1, 1)
    negative = [issue for issue in snapshot.quality_issues if issue.code is QualityIssueCode.STRENGTH_NEGATIVE_WEIGHT]
    assert negative[0].set_sequences == (2,)


def test_exercise_aggregation_keeps_unclassified_sets_separate_and_flagged() -> None:
    sets = (
        strength_set(1, category="BENCH_PRESS", reps=10, weight_kg=60.0),
        strength_set(2, category="BENCH_PRESS", reps=8, weight_kg=70.0),
        strength_set(3, category="CURL", name="DUMBBELL_HAMMER_CURL", reps=12, weight_kg=12.5),
        strength_set(4, category="UNKNOWN", reps=10, weight_kg=20.0),
        strength_set(5, category=None, reps=10, weight_kg=20.0),
    )
    snapshot = _snapshot(
        [
            activity("s1", "2026-03-10T08:00:00", ActivityType.STRENGTH, strength_sets=sets[:3]),
            activity("s2", "2026-03-12T08:00:00", ActivityType.STRENGTH, strength_sets=sets),
        ]
    )
    exercises = {item.exercise_key: item for item in snapshot.strength.exercises}

    bench = exercises["BENCH_PRESS"]
    assert bench.active_set_count == 4
    assert bench.reps == 36
    assert bench.volume_kg == 2 * (600.0 + 560.0)
    assert bench.max_weight_kg == 70.0
    assert bench.source_activity_ids == ("s1", "s2")
    assert bench.classified
    hammer = exercises["DUMBBELL_HAMMER_CURL"]
    assert hammer.category == "CURL"
    assert hammer.active_set_count == 2
    assert not exercises["UNKNOWN"].classified
    assert not exercises[None].classified
    assert snapshot.strength.unclassified_active_set_count == 2
    unclassified = [
        issue for issue in snapshot.quality_issues if issue.code is QualityIssueCode.STRENGTH_UNCLASSIFIED_EXERCISE
    ]
    assert [(issue.source_activity_id, issue.set_sequences) for issue in unclassified] == [("s2", (4, 5))]


def test_strength_activity_without_set_detail_is_reported() -> None:
    snapshot = _snapshot([activity("s", "2026-03-10T08:00:00", ActivityType.STRENGTH)])

    assert snapshot.strength.session_count == 1
    assert snapshot.strength.active_set_count == 0
    assert snapshot.strength.reps is None
    assert snapshot.strength.sessions[0].set_detail_available is False
    assert QualityIssueCode.STRENGTH_SET_DETAIL_MISSING in _codes(snapshot)


# Swimming


def _phantom_swim(source_id: str = "swim") -> NormalizedActivity:
    laps = (
        uniform_lap(0, 4, 25.0, 30.0),  # 100 m, plausible
        lap(1, 500.0, 1.5, tuple(length(index, 25.0, 0.075) for index in range(20))),  # phantom lap
        uniform_lap(2, 8, 25.0, 25.0),  # 200 m, plausible
    )
    return activity(
        source_id,
        "2026-03-12T08:00:00",
        ActivityType.SWIMMING,
        distance_meters=800.0,
        elapsed_seconds=1800.0,
        moving_seconds=400.0,
        swim_detail=swim_detail(source_id, laps),
    )


def test_phantom_lap_is_excluded_from_detail_distance_but_summary_is_reported_unchanged() -> None:
    snapshot = _snapshot([_phantom_swim()])
    swimming = snapshot.swimming
    session = swimming.sessions[0]

    assert session.summary_distance_meters == 800.0
    assert session.detail_distance_meters == 800.0
    assert session.implausible_lap_sequences == (1,)
    assert session.implausible_lap_distance_meters == 500.0
    assert session.plausible_detail_distance_meters == 300.0
    assert session.summary_distance_includes_implausible_laps
    assert session.implausible_length_count == 0  # lengths in the phantom lap belong to the lap issue
    assert swimming.summary_distance_meters.value == 800.0
    assert swimming.plausible_detail_distance_meters.value == 300.0
    codes = _codes(snapshot)
    assert QualityIssueCode.SWIM_LAP_IMPLAUSIBLE_SPEED in codes
    assert QualityIssueCode.SWIM_SUMMARY_DISTANCE_INCLUDES_IMPLAUSIBLE_LAPS in codes


def test_summary_level_load_metrics_are_not_affected_by_malformed_detail() -> None:
    snapshot = _snapshot([_phantom_swim()])

    assert _metric(snapshot.swimming.load_metrics, "training_load").value == 1.0
    assert snapshot.swimming.elapsed_seconds.value == 1800.0
    assert snapshot.swimming.moving_seconds.value == 400.0


def test_summary_that_does_not_match_lap_total_is_not_claimed_to_include_phantom_laps() -> None:
    snapshot = _snapshot([dataclasses.replace(_phantom_swim(), distance_meters=300.0)])

    session = snapshot.swimming.sessions[0]
    assert session.plausible_detail_distance_meters == 300.0
    assert not session.summary_distance_includes_implausible_laps
    assert QualityIssueCode.SWIM_SUMMARY_DISTANCE_INCLUDES_IMPLAUSIBLE_LAPS not in _codes(snapshot)


def test_fast_length_inside_plausible_lap_is_counted_but_distance_is_kept() -> None:
    lengths = (length(0, 25.0, 20.0), length(1, 25.0, 5.0), length(2, 25.0, 20.0), length(3, 25.0, 20.0))
    laps = (lap(0, 100.0, 65.0, lengths),)
    snapshot = _snapshot(
        [
            activity(
                "swim",
                "2026-03-12T08:00:00",
                ActivityType.SWIMMING,
                distance_meters=100.0,
                swim_detail=swim_detail("swim", laps),
            )
        ]
    )
    session = snapshot.swimming.sessions[0]

    assert session.implausible_length_count == 1
    assert session.implausible_lap_sequences == ()
    assert session.plausible_detail_distance_meters == 100.0
    assert QualityIssueCode.SWIM_LENGTH_IMPLAUSIBLE_SPEED in _codes(snapshot)


def test_lap_distance_that_disagrees_with_its_lengths_is_reported() -> None:
    laps = (lap(0, 75.0, 60.0, (length(0, 25.0, 30.0), length(1, 25.0, 30.0))),)
    snapshot = _snapshot(
        [activity("swim", "2026-03-12T08:00:00", ActivityType.SWIMMING, swim_detail=swim_detail("swim", laps))]
    )

    mismatch = [
        issue for issue in snapshot.quality_issues if issue.code is QualityIssueCode.SWIM_LAP_LENGTH_DISTANCE_MISMATCH
    ]
    assert mismatch[0].lap_sequences == (0,)


def test_idle_lengths_without_distance_are_not_swimming_lengths() -> None:
    laps = (uniform_lap(0, 2, 50.0, 40.0), lap(1, 0.0, 30.0, (length(0, None, 0.5),)))
    snapshot = _snapshot(
        [
            activity(
                "swim",
                "2026-03-12T08:00:00",
                ActivityType.SWIMMING,
                distance_meters=100.0,
                swim_detail=swim_detail("swim", laps, pool=50.0),
            )
        ]
    )
    session = snapshot.swimming.sessions[0]

    assert session.length_count == 3
    assert session.swimming_length_count == 2
    assert session.implausible_length_count == 0
    assert snapshot.swimming.pool_lengths_meters == (50.0,)
    assert snapshot.quality_issues == ()


def test_swim_without_detail_keeps_summary_values_and_reports_missing_detail() -> None:
    snapshot = _snapshot(
        [activity("swim", "2026-03-12T08:00:00", ActivityType.SWIMMING, distance_meters=1000.0)]
    )
    swimming = snapshot.swimming

    assert swimming.summary_distance_meters.value == 1000.0
    assert swimming.detail_distance_meters.value is None
    assert swimming.detail_distance_meters.missing_source_ids == ("swim",)
    assert QualityIssueCode.SWIM_DETAIL_MISSING in _codes(snapshot)


# Recovery


def test_recovery_separates_missing_rows_from_null_fields() -> None:
    snapshot = _snapshot(
        recoveries=[
            recovery("2026-03-08", sleep_seconds=20000, sleep_score=70),
            recovery("2026-03-10", sleep_seconds=None, sleep_score=None, sleep_avg_hrv_ms=None),
            recovery("2026-03-12", sleep_seconds=30000, sleep_score=90, hrv_weekly_avg_ms=47.0),
            recovery("2026-03-20"),  # outside the window
        ]
    )
    rec = snapshot.recovery

    assert rec.dates_with_row == (date(2026, 3, 8), date(2026, 3, 10), date(2026, 3, 12))
    assert rec.dates_without_row == (
        date(2026, 3, 9),
        date(2026, 3, 11),
        date(2026, 3, 13),
        date(2026, 3, 14),
    )
    fields = {item.field: item for item in rec.numeric_fields}
    sleep = fields["sleep_seconds"]
    assert sleep.rule is RecoveryRule.DAILY
    assert sleep.null_dates == (date(2026, 3, 10),)
    assert sleep.available_dates == (date(2026, 3, 8), date(2026, 3, 12))
    assert sleep.mean == 25000.0
    assert (sleep.minimum, sleep.maximum) == (20000.0, 30000.0)
    assert (sleep.latest_value, sleep.latest_date) == (30000.0, date(2026, 3, 12))
    weekly = fields["hrv_weekly_avg_ms"]
    assert weekly.rule is RecoveryRule.STATE
    assert (weekly.latest_value, weekly.latest_date) == (47.0, date(2026, 3, 12))
    assert weekly.mean is None


def test_recovery_categorical_fields_report_latest_with_date() -> None:
    snapshot = _snapshot(
        recoveries=[
            recovery("2026-03-12", training_status_key="PRODUCTIVE"),
            recovery("2026-03-13", training_status_key="RECOVERY"),
            recovery("2026-03-14", training_status_key=None),
        ]
    )
    status = next(item for item in snapshot.recovery.categorical_fields if item.field == "training_status_key")

    assert (status.latest_value, status.latest_date) == ("RECOVERY", date(2026, 3, 13))
    assert status.null_dates == (date(2026, 3, 14),)


def test_recovery_with_no_rows_is_unavailable_not_zero() -> None:
    rec = _snapshot().recovery

    assert rec.dates_with_row == ()
    assert len(rec.dates_without_row) == 7
    assert all(item.latest_value is None and item.mean is None for item in rec.numeric_fields)


def test_duplicate_recovery_date_is_rejected() -> None:
    with pytest.raises(ValueError, match="duplicate"):
        _snapshot(recoveries=[recovery("2026-03-12"), recovery("2026-03-12")])


# Presentation


def _full_snapshot() -> TrainingSnapshot:
    sets = (strength_set(1), strength_set(2, category="UNKNOWN"), strength_set(3, weight_kg=-0.001))
    return _snapshot(
        [
            _phantom_swim(),
            activity("s", "2026-03-10T08:00:00", ActivityType.STRENGTH, strength_sets=sets),
            activity("undated", None),
        ],
        [recovery("2026-03-12"), recovery("2026-03-13", sleep_seconds=None)],
    )


def test_text_rendering_is_cp949_safe_and_shows_missing_as_unavailable() -> None:
    text = render_training_snapshot(_full_snapshot())

    text.encode("cp949")
    assert text.isascii()
    assert "Plausible lap detail distance" in text
    assert "[summary includes implausible laps]" in text
    assert "swim_lap_implausible_speed swim" in text
    assert "no row: 2026-03-08" in text


def test_json_rendering_is_ascii_and_carries_provenance() -> None:
    rendered = render_training_snapshot_json(_full_snapshot())
    payload = json.loads(rendered)

    assert rendered.isascii()
    assert payload["window"] == {"as_of": "2026-03-14", "lookback_days": 7, "start": "2026-03-08"}
    load = {item["key"]: item for item in payload["activities"]["load_metrics"]}
    assert load["training_load"]["rule"] == "sum"
    assert [item["source_id"] for item in load["training_load"]["values"]] == ["s", "swim"]
    assert payload["swimming"]["sessions"][0]["implausible_lap_sequences"] == [1]
    assert payload["recovery"]["days"][1]["sleep_seconds"] is None
