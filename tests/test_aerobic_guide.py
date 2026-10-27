"""Aerobic Guide v1 domain rules (AC1, AC3, AC4): minutes, the run-length notice and the plateau check."""

from __future__ import annotations

import random
from datetime import date
from decimal import Decimal

import pytest
from aerobic_builders import other, run, scenario_activities, swim
from analytics_builders import activity

from muscle50.domain import aerobic_guide
from muscle50.domain.activity import ActivityMetric, ActivityType, NormalizedActivity
from muscle50.domain.aerobic_guide import (
    PlateauOption,
    aerobic_history_start,
    plateau_check,
    run_length_checks,
    weekly_aerobic_minutes,
)
from muscle50.domain.body_composition_trend import TrendMetric
from muscle50.domain.goal_mode import weight_change
from muscle50.domain.training_goal import GoalMode, TrainingGoal, WeeklyRateRange

D = date(2026, 11, 20)
CUT = TrainingGoal(
    GoalMode.CUT,
    target_body_fat_percent=Decimal("18"),
    target_date=date(2027, 2, 28),
    weekly_loss_percent=WeeklyRateRange(Decimal("0.3"), Decimal("0.5")),
    plateau_weeks=3,
)


# --- weekly aerobic minutes (AC1) --------------------------------------------------------------


def test_minutes_are_summed_per_bucket_over_d_minus_7_to_d_minus_1() -> None:
    activities = (
        run("1", "2026-11-12T07:00:00", 5000.0, moderate=500.0, vigorous=500.0),  # D-8: outside
        run("2", "2026-11-13T07:00:00", 5000.0, moderate=30.0, vigorous=5.0),  # D-7: inside
        swim("3", "2026-11-19T19:00:00", moderate=20.5, vigorous=0.0),  # D-1: inside, a stored 0 is 0
        run("4", "2026-11-20T07:00:00", 5000.0, moderate=500.0, vigorous=500.0),  # D: outside
        run("5", None, 5000.0, moderate=500.0, vigorous=500.0),  # undated: never counted
    )
    result = weekly_aerobic_minutes(D, activities)
    assert (result.from_date, result.to_date) == (date(2026, 11, 13), date(2026, 11, 19))
    assert result.status == "known"
    assert (result.moderate_minutes, result.vigorous_minutes, result.total_minutes) == (50.5, 5.0, 55.5)
    assert [item.source_activity_id for item in result.activities] == ["2", "3"]
    assert result.activity_types == ("running", "swimming")
    assert result.evidence == ("EXL-03", "FATEX-02", "design")


@pytest.mark.parametrize(
    "kind", [ActivityType.STRENGTH, ActivityType.OTHER, ActivityType.WALKING, ActivityType.CYCLING]
)
def test_strength_other_walking_and_cycling_are_not_counted(kind: ActivityType) -> None:
    result = weekly_aerobic_minutes(D, (other("1", "2026-11-15T07:00:00", kind),))
    assert result.status == "none_stored"
    assert (result.moderate_minutes, result.vigorous_minutes, result.total_minutes) == (None, None, None)


def test_no_counted_activity_is_none_stored_never_zero() -> None:
    result = weekly_aerobic_minutes(D, ())
    assert (result.status, result.total_minutes, result.activities) == ("none_stored", None, ())


def test_one_metric_missing_is_a_lower_bound_and_the_stored_one_counts() -> None:
    result = weekly_aerobic_minutes(
        D,
        (
            run("1", "2026-11-14T07:00:00", 5000.0, moderate=30.0, vigorous=None),
            run("2", "2026-11-15T07:00:00", 5000.0, moderate=10.0, vigorous=10.0),
        ),
    )
    assert result.status == "lower_bound"
    assert (result.moderate_minutes, result.vigorous_minutes, result.total_minutes) == (40.0, 10.0, 50.0)
    assert (result.partial_intensity_count, result.without_intensity_count) == (1, 0)
    assert result.activities[0].vigorous_minutes is None


def test_both_metrics_missing_shows_the_duration_apart_and_never_adds_it() -> None:
    result = weekly_aerobic_minutes(
        D,
        (
            run("1", "2026-11-14T07:00:00", 5000.0, moderate=30.0, vigorous=10.0),
            swim("2", "2026-11-15T19:00:00", moving=2700.0),  # 45 min moving
            swim("3", "2026-11-16T19:00:00", moving=None, elapsed=1230.0),  # elapsed 20.5 min
            swim("4", "2026-11-17T19:00:00", moving=None, elapsed=None),  # no duration either
        ),
    )
    assert result.status == "lower_bound"
    assert (result.moderate_minutes, result.vigorous_minutes, result.total_minutes) == (30.0, 10.0, 40.0)
    assert result.without_intensity_count == 3
    assert result.without_intensity_duration_minutes == 66  # 3930 s = 65.5 min -> 66 (HALF_EVEN)
    assert result.without_duration_count == 1
    assert [item.duration_minutes for item in result.activities] == [30, 45, 20, None]


def test_all_metrics_missing_is_unknown_with_no_total() -> None:
    result = weekly_aerobic_minutes(D, (swim("1", "2026-11-15T19:00:00"),))
    assert result.status == "unknown"
    assert (result.moderate_minutes, result.vigorous_minutes, result.total_minutes) == (None, None, None)
    assert (result.without_intensity_count, result.without_intensity_duration_minutes) == (1, 45)


def test_a_non_numeric_metric_is_unknown_not_zero() -> None:
    item = activity(
        "1",
        "2026-11-15T07:00:00",
        ActivityType.RUNNING,
        metrics=(
            ActivityMetric("moderate_intensity_minutes", "30", "min", "moderateIntensityMinutes"),
            ActivityMetric("vigorous_intensity_minutes", 5.0, "min", "vigorousIntensityMinutes"),
        ),
    )
    result = weekly_aerobic_minutes(D, (item,))
    # No activity stored a usable moderate value: that bucket is unknown, not 0; the total is a lower bound.
    assert (result.status, result.moderate_minutes, result.vigorous_minutes) == ("lower_bound", None, 5.0)
    assert (result.total_minutes, result.partial_intensity_count) == (5.0, 1)
    assert result.activities[0].moderate_minutes is None


# --- run-length notice (AC4) -------------------------------------------------------------------


def _check(*activities: NormalizedActivity) -> dict[str, tuple[str, str | None]]:
    report = run_length_checks(D, activities)
    return {
        item.source_activity_id: (
            item.status,
            format(item.increase_percent, "f") if item.increase_percent is not None else None,
        )
        for item in report.runs
    }


def test_more_than_10_percent_longer_gives_a_notice() -> None:
    report = run_length_checks(D, (run("1", "2026-11-02T07:00:00", 10000.0), run("2", "2026-11-19T07:00:00", 12500.0)))
    assert (report.from_date, report.to_date) == (date(2026, 11, 13), D)
    (check,) = report.runs
    assert check.status == "longer_than_threshold"
    assert check.increase_percent == Decimal("25.0")
    assert (check.longest_previous_meters, check.longest_previous_activity_id) == (10000.0, "1")
    assert check.longest_previous_date == date(2026, 11, 2)
    assert (check.previous_without_distance, check.baseline_lower_bound) == (0, False)
    assert report.evidence == ("RUNPROG-03",)


def test_exactly_10_percent_longer_gives_no_notice_and_a_hair_more_does() -> None:
    base = run("1", "2026-11-02T07:00:00", 10000.0)
    assert _check(base, run("2", "2026-11-19T07:00:00", 11000.0)) == {"2": ("within", "10.0")}
    assert _check(base, run("2", "2026-11-19T07:00:00", 11001.0)) == {"2": ("longer_than_threshold", "10.0")}
    # Compared on the exact decimal reprs (distance * 10 > longest * 11), never a binary 1.1.
    assert _check(run("1", "2026-11-02T07:00:00", 0.3), run("2", "2026-11-19T07:00:00", 0.33)) == {
        "2": ("within", "10.0")
    }


def test_the_baseline_is_the_30_days_before_the_run_date() -> None:
    # Run on 11-19: 10-20 is day -30 (included), 10-19 is day -31 (excluded).
    included = _check(run("1", "2026-10-20T07:00:00", 10000.0), run("2", "2026-11-19T07:00:00", 12000.0))
    excluded = _check(run("1", "2026-10-19T07:00:00", 10000.0), run("2", "2026-11-19T07:00:00", 12000.0))
    assert included == {"2": ("longer_than_threshold", "20.0")}
    assert excluded == {"2": ("no_previous_run", None)}


def test_a_same_day_earlier_run_is_not_a_baseline() -> None:
    assert _check(run("1", "2026-11-19T06:00:00", 3000.0), run("2", "2026-11-19T18:00:00", 9000.0)) == {
        "1": ("no_previous_run", None),
        "2": ("no_previous_run", None),
    }


def test_no_distance_is_not_judged_and_a_baseline_without_distance_is_a_lower_bound() -> None:
    report = run_length_checks(
        D,
        (
            run("1", "2026-11-01T07:00:00", 10000.0),
            run("2", "2026-11-05T07:00:00", None),  # treadmill without a distance
            run("3", "2026-11-06T07:00:00", 0.0),  # zero is no distance too
            run("4", "2026-11-18T07:00:00", None),
            run("5", "2026-11-19T07:00:00", 12500.0),
        ),
    )
    by_id = {item.source_activity_id: item for item in report.runs}
    assert set(by_id) == {"4", "5"}
    assert (by_id["4"].status, by_id["4"].increase_percent, by_id["4"].longest_previous_meters) == (
        "no_distance",
        None,
        None,
    )
    five = by_id["5"]
    assert (five.status, five.previous_without_distance, five.baseline_lower_bound) == (
        "longer_than_threshold",
        3,
        True,
    )


def test_no_run_in_the_window_and_only_older_runs() -> None:
    assert run_length_checks(D, (run("1", "2026-11-12T07:00:00", 10000.0),)).runs == ()
    assert run_length_checks(D, ()).runs == ()


def test_aerobic_history_covers_the_oldest_baseline() -> None:
    assert aerobic_history_start(D) == date(2026, 10, 14)  # D-7 run, minus 30 days


# --- plateau check (AC3) -----------------------------------------------------------------------


def _points(weights: dict[str, str]) -> dict[TrendMetric, dict[date, Decimal]]:
    points: dict[TrendMetric, dict[date, Decimal]] = {metric: {} for metric in TrendMetric}
    points[TrendMetric.WEIGHT_KG] = {date.fromisoformat(day): Decimal(value) for day, value in weights.items()}
    return points


PLATEAU = {"2026-10-23": "92.4", "2026-11-06": "92.2", "2026-11-20": "92.1"}


def test_every_interval_below_the_min_is_met_with_four_unranked_options() -> None:
    check = plateau_check(CUT, _points(PLATEAU), D, None)
    assert check is not None and check.status == "met"
    assert [(item.from_date.isoformat(), item.to_date.isoformat(), item.days) for item in check.intervals] == [
        ("2026-11-06", "2026-11-20", 14),
        ("2026-10-23", "2026-11-06", 14),
    ]
    assert (check.span_days, check.weeks, check.below_loss_percent, check.weights_used) == (28, 3, Decimal("0.3"), 3)
    assert (check.latest_measurement_date, check.days_since_latest_measurement, check.reason) == (D, 0, None)
    assert check.options == (
        PlateauOption("check_meal_logging", ("PLAT-04",)),
        PlateauOption("eat_less", ("design", "PRO-04")),
        PlateauOption("keep_intake_add_activity", ("FATEX-05", "FATEX-04", "RUNPROG-03", "CONC-04")),
        PlateauOption("maintenance_week", ("PLAT-05",)),
    )
    assert all(option.evidence for option in check.options)
    assert check.evidence == ("design", "PLAT-01", "PLAT-02")


def test_the_newest_interval_equals_the_goal_mode_weight_change() -> None:
    points = _points(PLATEAU)
    check = plateau_check(CUT, points, D, None)
    change = weight_change(CUT, points, D, None)
    assert check is not None
    newest = check.intervals[0]
    assert (newest.from_date, newest.to_date, newest.days, newest.percent_per_week) == (
        change.from_date,
        change.to_date,
        change.days,
        change.percent_per_week,
    )


def test_an_interval_at_exactly_the_min_is_not_met() -> None:
    # 100.0 -> 99.4 over 14 days is exactly -0.30 %/week: not below 0.3 (strict).
    check = plateau_check(CUT, _points({"2026-10-23": "99.5", "2026-11-06": "100.0", "2026-11-20": "99.4"}), D, None)
    assert check is not None
    assert check.intervals[0].percent_per_week == Decimal("-0.3")
    assert (check.status, check.options) == ("not_met", ())


def test_a_gain_counts_as_below_the_min() -> None:
    check = plateau_check(CUT, _points({"2026-10-23": "92.0", "2026-11-06": "92.4", "2026-11-20": "92.5"}), D, None)
    assert check is not None and check.status == "met"


def test_one_fast_interval_is_not_met() -> None:
    check = plateau_check(CUT, _points({"2026-10-23": "93.4", "2026-11-06": "92.2", "2026-11-20": "92.1"}), D, None)
    assert check is not None and check.status == "not_met"


def test_one_interval_is_insufficient_never_no_plateau() -> None:
    check = plateau_check(CUT, _points({"2026-10-23": "92.4", "2026-11-20": "92.1"}), D, None)
    assert check is not None
    assert check.status == "insufficient_measurements"
    assert check.reason == "2 weights cover 1 interval; the check needs 3 weeks and at least 2 intervals"
    assert check.options == ()


def test_a_span_shorter_than_n_weeks_is_insufficient() -> None:
    # Two 7-day intervals span 14 days; 3 weeks need 21.
    check = plateau_check(CUT, _points({"2026-11-06": "92.4", "2026-11-13": "92.3", "2026-11-20": "92.3"}), D, None)
    assert check is not None and check.status == "insufficient_measurements"
    assert check.reason == "3 weights cover 2 intervals; the check needs 3 weeks and at least 2 intervals"


def test_no_weight_is_insufficient_and_unreadable_inbody_is_unknown() -> None:
    empty = plateau_check(CUT, _points({}), D, None)
    assert empty is not None and empty.status == "insufficient_measurements"
    assert empty.reason == "0 weights cover 0 intervals; the check needs 3 weeks and at least 2 intervals"
    unknown = plateau_check(CUT, None, D, "InBody data unavailable: no table")
    assert unknown is not None
    assert (unknown.status, unknown.reason, unknown.options) == ("unknown", "InBody data unavailable: no table", ())


@pytest.mark.parametrize("mode", [GoalMode.GAIN, GoalMode.MAINTAIN])
def test_gain_and_maintain_have_no_plateau_check(mode: GoalMode) -> None:
    assert plateau_check(TrainingGoal(mode), _points(PLATEAU), D, None) is None


def test_cut_without_the_setting_is_not_set() -> None:
    goal = TrainingGoal(GoalMode.CUT, weekly_loss_percent=WeeklyRateRange(Decimal("0.3"), Decimal("0.5")))
    check = plateau_check(goal, _points(PLATEAU), D, None)
    assert check is not None
    assert (check.status, check.weeks, check.intervals, check.options) == ("not_set", None, (), ())


def test_older_weights_beyond_the_span_are_not_used() -> None:
    weights = {"2026-09-01": "80.0", **PLATEAU}  # a fast loss long before the 3 weeks
    check = plateau_check(CUT, _points(weights), D, None)
    assert check is not None and check.status == "met" and len(check.intervals) == 2


# --- determinism ------------------------------------------------------------------------------


def test_results_are_deterministic_and_independent_of_input_order() -> None:
    activities = list(scenario_activities())
    expected = (weekly_aerobic_minutes(D, activities), run_length_checks(D, activities))
    shuffled = activities[:]
    random.Random(7).shuffle(shuffled)
    assert (weekly_aerobic_minutes(D, shuffled), run_length_checks(D, shuffled)) == expected
    assert expected == (weekly_aerobic_minutes(D, activities), run_length_checks(D, activities))


def test_constants_carry_the_evidence_numbers() -> None:
    assert (aerobic_guide.GUIDELINE_MINIMUM_MINUTES, aerobic_guide.STUDIED_RANGE_END_MINUTES) == (150, 300)
    assert (aerobic_guide.RUN_PREVIOUS_DAYS, aerobic_guide.RUN_LONGER_THRESHOLD_PERCENT) == (30, 10)
    assert aerobic_guide.PLATEAU_MIN_INTERVALS == 2
    assert Decimal("0.35") == aerobic_guide.WITHIN_WEEK_WEIGHT_NOISE_PERCENT
