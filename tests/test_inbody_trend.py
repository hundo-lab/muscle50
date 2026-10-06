"""Pure rules of the InBody body-composition trend (domain and use case). Synthetic values only."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from muscle50.application.inbody_trend import ShowBodyCompositionTrend
from muscle50.domain.body_composition_trend import (
    METRICS,
    BodyCompositionTrend,
    GoalProgress,
    IntervalChange,
    InvalidStoredMeasurementError,
    InvalidTrendRangeError,
    MetricConflict,
    OverallChange,
    StoredBodyComposition,
    TrendMetric,
    build_body_composition_trend,
    round_tenth,
)
from muscle50.domain.inbody_normalization import _canonical_number
from muscle50.domain.training_goals import DEFAULT_TRAINING_GOALS

WEIGHT = TrendMetric.WEIGHT_KG
SMM = TrendMetric.SKELETAL_MUSCLE_MASS_KG
BFM = TrendMetric.BODY_FAT_MASS_KG
PBF = TrendMetric.BODY_FAT_PERCENT
REFERENCE = date(2026, 10, 5)


def _row(
    row_id: int,
    measured_at: str,
    weight: float | None = None,
    smm: float | None = None,
    bfm: float | None = None,
    pbf: float | None = None,
) -> StoredBodyComposition:
    return StoredBodyComposition(row_id, measured_at, weight, smm, bfm, pbf)


def _trend(
    *rows: StoredBodyComposition,
    from_date: date | None = None,
    to_date: date | None = None,
    reference: date = REFERENCE,
) -> BodyCompositionTrend:
    return build_body_composition_trend(
        rows, from_date=from_date, to_date=to_date, reference_date=reference, goals=DEFAULT_TRAINING_GOALS
    )


def _d(text: str) -> Decimal:
    return Decimal(text)


AC1 = (
    _row(1, "2026-07-02T08:10:00+09:00", 80.0, 36.0, 15.0, 18.8),
    _row(2, "2026-08-05T08:05:00+09:00", 80.6, 36.5, 15.1, 18.7),
    _row(3, "2026-09-16T16:43:00+09:00", 81.0, 36.9),
)


# --- rounding ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("stored", "expected"),
    [
        (41.400001525878906, "41.4"),  # float32 noise
        (80.40000152587891, "80.4"),
        (36.05, "36.0"),  # an exact .x5 tie goes to even
        (36.15, "36.2"),
        (36.25, "36.2"),
        (36.35, "36.4"),
        (80.0, "80.0"),
        (0.0, "0.0"),
        (-0.04, "0.0"),  # a negative zero is normalized
    ],
)
def test_round_tenth_is_half_even_on_the_shortest_repr(stored: float, expected: str) -> None:
    assert str(round_tenth(stored)) == expected


@pytest.mark.parametrize("stored", [41.400001525878906, 36.05, 36.15, 36.25, 18.75, 0.05, 99.95, 15.0, 7.123])
def test_round_tenth_equals_the_inbody_fingerprint_rule(stored: float) -> None:
    assert str(round_tenth(stored)) == _canonical_number(stored)


@pytest.mark.parametrize("stored", [float("nan"), float("inf")])
def test_round_tenth_refuses_non_finite_values(stored: float) -> None:
    with pytest.raises(InvalidStoredMeasurementError):
        round_tenth(stored)


# --- AC1 happy path ----------------------------------------------------------------------------


def test_three_dates_give_every_field() -> None:
    trend = _trend(*AC1)

    assert [(item.measured_at, item.local_date, item.values) for item in trend.measurements] == [
        ("2026-07-02T08:10:00+09:00", date(2026, 7, 2), (_d("80.0"), _d("36.0"), _d("15.0"), _d("18.8"))),
        ("2026-08-05T08:05:00+09:00", date(2026, 8, 5), (_d("80.6"), _d("36.5"), _d("15.1"), _d("18.7"))),
        ("2026-09-16T16:43:00+09:00", date(2026, 9, 16), (_d("81.0"), _d("36.9"), None, None)),
    ]
    assert trend.intervals == (
        IntervalChange(date(2026, 7, 2), date(2026, 8, 5), 34, (_d("0.6"), _d("0.5"), _d("0.1"), _d("-0.1"))),
        IntervalChange(date(2026, 8, 5), date(2026, 9, 16), 42, (_d("0.4"), _d("0.4"), None, None)),
    )
    assert trend.overall == (
        OverallChange(WEIGHT, date(2026, 7, 2), date(2026, 9, 16), 76, _d("1.0"), _d("0.4")),
        OverallChange(SMM, date(2026, 7, 2), date(2026, 9, 16), 76, _d("0.9"), _d("0.3")),
        OverallChange(BFM, date(2026, 7, 2), date(2026, 8, 5), 34, _d("0.1"), _d("0.1")),
        OverallChange(PBF, date(2026, 7, 2), date(2026, 8, 5), 34, _d("-0.1"), _d("-0.1")),
    )
    assert trend.goal.latest == _d("36.9")
    assert trend.goal.latest_date == date(2026, 9, 16)
    assert trend.goal.milestone == GoalProgress(_d("43.0"), _d("6.1"), False)
    assert trend.goal.long_term == GoalProgress(_d("50.0"), _d("13.1"), False)
    assert trend.conflicts == ()
    assert trend.last_measurement_date == date(2026, 9, 16)
    assert trend.days_since_last_measurement == 19
    assert trend.dates == (date(2026, 7, 2), date(2026, 8, 5), date(2026, 9, 16))


def test_changes_are_rounded_minus_rounded() -> None:
    # The raw difference (about 0.05) would round to 0.0; the shown values 80.0 -> 80.1 must give 0.1.
    trend = _trend(_row(1, "2026-07-01T08:00:00+09:00", 80.04), _row(2, "2026-08-01T08:00:00+09:00", 80.09))

    assert trend.measurements[0].value(WEIGHT) == _d("80.0")
    assert trend.measurements[1].value(WEIGHT) == _d("80.1")
    assert trend.intervals[0].change(WEIGHT) == _d("0.1")


# --- AC2 missing is not zero -------------------------------------------------------------------


def test_missing_body_fat_mass_is_unknown_and_never_zero() -> None:
    trend = _trend(
        _row(1, "2026-07-01T08:00:00+09:00", 80.0, 36.0, 15.0, 18.8),
        _row(2, "2026-08-01T08:00:00+09:00", 80.5, 36.2, None, 18.6),
        _row(3, "2026-09-01T08:00:00+09:00", 81.0, 36.4, 15.4, 18.9),
    )

    assert trend.measurements[1].value(BFM) is None
    assert [interval.change(BFM) for interval in trend.intervals] == [None, None]
    assert trend.intervals[0].change(PBF) == _d("-0.2")
    # The series skips the missing date: first to last runs over the dates that have a value.
    assert trend.overall[METRICS.index(BFM)] == OverallChange(
        BFM, date(2026, 7, 1), date(2026, 9, 1), 62, _d("0.4"), _d("0.2")
    )


def test_a_row_with_only_weight_feeds_only_the_weight_series() -> None:
    trend = _trend(_row(1, "2026-07-01T08:00:00+09:00", 80.0), _row(2, "2026-08-01T08:00:00+09:00", 80.3))

    assert trend.intervals[0].changes == (_d("0.3"), None, None, None)
    assert trend.overall[1:] == tuple(OverallChange(metric, None, None, None, None, None) for metric in METRICS[1:])
    assert trend.goal.latest is None


# --- AC3 same-date rows ------------------------------------------------------------------------


def test_equal_same_date_rows_give_one_point_per_metric() -> None:
    trend = _trend(
        _row(1, "2026-07-01T08:00:00+09:00", 80.0, 36.0),
        _row(2, "2026-09-16T16:43:00+09:00", 81.0, 36.9, 15.0),
        _row(3, "2026-09-16T16:43:00+09:00", 81.04),  # same weight after rounding, no SMM
    )

    assert len(trend.measurements) == 3  # every stored row is listed, nothing is merged
    assert trend.conflicts == ()
    assert len(trend.intervals) == 1  # intervals are between dates, never between rows of one date
    assert trend.intervals[0].changes == (_d("1.0"), _d("0.9"), None, None)
    assert trend.goal.latest == _d("36.9")


def test_different_same_date_values_are_a_conflict_left_out_of_that_metric_only() -> None:
    trend = _trend(
        _row(1, "2026-07-01T08:00:00+09:00", 80.0, 36.0),
        _row(2, "2026-09-16T16:43:00+09:00", 81.0, 36.9),
        _row(3, "2026-09-16T16:43:00+09:00", 81.4, 36.9),
    )

    assert len(trend.measurements) == 3
    assert trend.conflicts == (MetricConflict(date(2026, 9, 16), WEIGHT, (_d("81.0"), _d("81.4"))),)
    assert trend.intervals[0].changes == (None, _d("0.9"), None, None)
    # Weight's last usable point is now 07-01 alone.
    assert trend.overall[0] == OverallChange(WEIGHT, date(2026, 7, 1), date(2026, 7, 1), 0, None, None)
    assert trend.overall[1] == OverallChange(SMM, date(2026, 7, 1), date(2026, 9, 16), 77, _d("0.9"), _d("0.3"))


def test_conflict_values_come_from_the_rows_that_have_the_metric_in_list_order() -> None:
    trend = _trend(
        _row(5, "2026-09-16T09:00:00+09:00", 81.4),
        _row(6, "2026-09-16T08:00:00+09:00", None, 36.0),
        _row(7, "2026-09-16T07:00:00+09:00", 81.0),
        _row(8, "2026-09-16T10:00:00+09:00", 81.4),
    )

    assert trend.conflicts == (MetricConflict(date(2026, 9, 16), WEIGHT, (_d("81.0"), _d("81.4"), _d("81.4"))),)


# --- AC4 goal -----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("smm", "milestone", "long_term"),
    [
        (36.9, GoalProgress(_d("43.0"), _d("6.1"), False), GoalProgress(_d("50.0"), _d("13.1"), False)),
        (42.96, GoalProgress(_d("43.0"), None, True), GoalProgress(_d("50.0"), _d("7.0"), False)),  # shows 43.0
        (44.0, GoalProgress(_d("43.0"), None, True), GoalProgress(_d("50.0"), _d("6.0"), False)),
        (51.2, GoalProgress(_d("43.0"), None, True), GoalProgress(_d("50.0"), None, True)),
    ],
)
def test_goal_progress_from_the_latest_point(smm: float, milestone: GoalProgress, long_term: GoalProgress) -> None:
    trend = _trend(_row(1, "2026-09-16T08:00:00+09:00", 80.0, smm))

    assert (trend.goal.milestone, trend.goal.long_term) == (milestone, long_term)


def test_goal_is_unknown_without_a_skeletal_muscle_mass_point() -> None:
    trend = _trend(_row(1, "2026-09-16T08:00:00+09:00", 80.0))

    assert trend.goal.latest is None
    assert trend.goal.latest_date is None
    assert trend.goal.milestone == GoalProgress(_d("43.0"), None, None)
    assert trend.goal.long_term == GoalProgress(_d("50.0"), None, None)


def test_a_conflicted_last_smm_date_falls_back_to_the_earlier_point() -> None:
    trend = _trend(
        _row(1, "2026-08-01T08:00:00+09:00", 80.0, 36.5),
        _row(2, "2026-09-16T08:00:00+09:00", 81.0, 36.9),
        _row(3, "2026-09-16T08:00:00+09:00", 81.0, 37.3),
    )

    assert trend.goal.latest == _d("36.5")
    assert trend.goal.latest_date == date(2026, 8, 1)
    assert trend.last_measurement_date == date(2026, 9, 16)


# --- first to last and the 28-day rule ----------------------------------------------------------


@pytest.mark.parametrize(
    ("second", "days", "per_28_days"),
    [
        ("2026-07-28T08:00:00+09:00", 27, None),
        ("2026-07-29T08:00:00+09:00", 28, _d("0.7")),
        ("2026-07-30T08:00:00+09:00", 29, _d("0.7")),
    ],
)
def test_per_28_days_only_from_28_days(second: str, days: int, per_28_days: Decimal | None) -> None:
    trend = _trend(_row(1, "2026-07-01T08:00:00+09:00", 80.0), _row(2, second, 80.7))

    assert trend.overall[0] == OverallChange(WEIGHT, date(2026, 7, 1), trend.dates[-1], days, _d("0.7"), per_28_days)


def test_one_point_has_no_change() -> None:
    trend = _trend(_row(1, "2026-07-01T08:00:00+09:00", 80.0))

    assert trend.overall[0] == OverallChange(WEIGHT, date(2026, 7, 1), date(2026, 7, 1), 0, None, None)
    assert trend.intervals == ()


def test_no_change_is_an_unsigned_zero() -> None:
    trend = _trend(_row(1, "2026-07-01T08:00:00+09:00", 80.0), _row(2, "2026-09-01T08:00:00+09:00", 80.04))

    assert str(trend.intervals[0].change(WEIGHT)) == "0.0"
    assert str(trend.overall[0].change) == "0.0"
    assert str(trend.overall[0].per_28_days) == "0.0"


# --- range, local dates and ordering -------------------------------------------------------------


def test_range_filter_uses_the_stored_local_date_inclusive() -> None:
    # 23:30 at -05:00 is already 07-03 in UTC; the stored local date 07-02 decides.
    rows = (
        _row(1, "2026-07-01T08:00:00+09:00", 80.0),
        _row(2, "2026-07-02T23:30:00-05:00", 80.2),
        _row(3, "2026-07-03T08:00:00+09:00", 80.4),
    )

    only_second = _trend(*rows, from_date=date(2026, 7, 2), to_date=date(2026, 7, 2))
    after = _trend(*rows, from_date=date(2026, 7, 3))
    before = _trend(*rows, to_date=date(2026, 7, 2))

    assert [item.measured_at for item in only_second.measurements] == ["2026-07-02T23:30:00-05:00"]
    assert only_second.measurements[0].local_date == date(2026, 7, 2)
    assert [item.local_date for item in after.measurements] == [date(2026, 7, 3)]
    assert [item.local_date for item in before.measurements] == [date(2026, 7, 1), date(2026, 7, 2)]


def test_order_is_local_date_then_stored_clock_time_not_utc() -> None:
    # 09:00+09:00 is 00:00Z, before 08:00+00:00 (08:00Z) in UTC; the stored clock time decides.
    trend = _trend(
        _row(1, "2026-07-02T09:00:00+09:00", 80.0),
        _row(2, "2026-07-02T08:00:00+00:00", 80.0),
        _row(3, "2026-07-01T23:00:00-05:00", 80.0),
    )

    assert [item.measured_at for item in trend.measurements] == [
        "2026-07-01T23:00:00-05:00",
        "2026-07-02T08:00:00+00:00",
        "2026-07-02T09:00:00+09:00",
    ]
    assert [item.local_time.strftime("%H:%M") for item in trend.measurements] == ["23:00", "08:00", "09:00"]


def test_mixed_naive_and_aware_rows_sort_without_guessing_a_zone() -> None:
    # Same date and clock time: the naive row (no offset, no zone guessed) sorts first, then the UTC
    # instant breaks the tie between offsets, then the stored id. A higher id never decides first.
    trend = _trend(
        _row(1, "2026-07-02T08:10:00+00:00", 80.0),
        _row(2, "2026-07-02T08:10:00+09:00", 80.0),
        _row(3, "2026-07-02T08:10:00", 80.0),
        _row(4, "2026-07-02T08:10:00", 80.0),
        _row(5, "2026-07-02T08:10:00.500000+09:00", 80.0),
    )

    assert [item.measured_at for item in trend.measurements] == [
        "2026-07-02T08:10:00",
        "2026-07-02T08:10:00",
        "2026-07-02T08:10:00+09:00",
        "2026-07-02T08:10:00+00:00",
        "2026-07-02T08:10:00.500000+09:00",
    ]
    reversed_input = _trend(*reversed((_row(3, "2026-07-02T08:10:00", 80.0), _row(2, "2026-07-02T08:10:00+09:00"))))
    assert [item.measured_at for item in reversed_input.measurements] == [
        "2026-07-02T08:10:00",
        "2026-07-02T08:10:00+09:00",
    ]


def test_stored_id_breaks_a_full_tie() -> None:
    trend = _trend(_row(9, "2026-07-02T08:10:00+09:00", 80.0), _row(4, "2026-07-02T08:10:00+09:00", 80.4))

    assert [item.value(WEIGHT) for item in trend.measurements] == [_d("80.4"), _d("80.0")]


def test_reversed_range_is_refused_with_the_exact_message() -> None:
    with pytest.raises(InvalidTrendRangeError) as error:
        _trend(from_date=date(2026, 8, 1), to_date=date(2026, 7, 1))

    assert str(error.value) == "--from은 --to보다 이후일 수 없습니다."


def test_unreadable_stored_values_are_refused_not_guessed() -> None:
    with pytest.raises(InvalidStoredMeasurementError, match="unreadable measured_at"):
        _trend(_row(1, "not a timestamp", 80.0))
    with pytest.raises(InvalidStoredMeasurementError, match="non-finite weight_kg"):
        _trend(_row(1, "2026-07-01T08:00:00+09:00", float("nan")))


def test_no_rows_give_nulls_and_empty_lists() -> None:
    trend = _trend()

    assert trend.measurements == ()
    assert trend.intervals == ()
    assert trend.conflicts == ()
    assert trend.overall == tuple(OverallChange(metric, None, None, None, None, None) for metric in METRICS)
    assert trend.goal.milestone == GoalProgress(_d("43.0"), None, None)
    assert trend.last_measurement_date is None
    assert trend.days_since_last_measurement is None


def test_days_since_can_be_negative_for_a_future_dated_row() -> None:
    trend = _trend(_row(1, "2026-10-07T08:00:00+09:00", 80.0))

    assert trend.days_since_last_measurement == -2


# --- use case -----------------------------------------------------------------------------------


class _Reader:
    def __init__(self, rows: tuple[StoredBodyComposition, ...]):
        self.rows = rows
        self.calls = 0

    def load_measurements(self) -> tuple[StoredBodyComposition, ...]:
        self.calls += 1
        return self.rows


def test_reference_date_is_to_or_today() -> None:
    reader = _Reader(AC1)
    use_case = ShowBodyCompositionTrend(reader)

    without_to = use_case.execute(None, None, today=REFERENCE)
    with_to = use_case.execute(None, date(2026, 8, 31), today=REFERENCE)

    assert (without_to.reference_date, without_to.days_since_last_measurement) == (REFERENCE, 19)
    assert (with_to.reference_date, with_to.days_since_last_measurement) == (date(2026, 8, 31), 26)
    assert with_to.last_measurement_date == date(2026, 8, 5)


def test_use_case_refuses_a_reversed_range_before_reading() -> None:
    reader = _Reader(AC1)

    with pytest.raises(InvalidTrendRangeError):
        ShowBodyCompositionTrend(reader).execute(date(2026, 8, 1), date(2026, 7, 1), today=REFERENCE)
    assert reader.calls == 0
