"""Strength set timing v1 domain rules. Synthetic values only."""

from __future__ import annotations

from datetime import date

import pytest
from strength_set_timing_builders import (
    BASE_BPM,
    LAG_MS,
    START_MS,
    Active,
    Rest,
    Session,
    build_session,
    details_payload,
    heart_rate_samples,
    strength_activity,
    timed_set,
)

from muscle50.domain.strength_set_timing import (
    Confidence,
    HeartRateLoad,
    HeartRateSample,
    HeartRateStatus,
    LagStatus,
    NotEstimatedReason,
    RestBetweenSets,
    SuspectSet,
    TimingMethod,
    estimate_session,
    find_rise_onset,
    is_checked,
    is_suspect,
    needs_heart_rate,
    parse_direct_heart_rate,
    summarize_set_timing,
)

DAY = date(2026, 3, 12)


def _normal(**overrides: object) -> Active:
    fields: dict[str, object] = {"reps": 10, "seconds": 20.0}
    fields.update(overrides)
    return Active(**fields)  # type: ignore[arg-type]


def _ac2_rows(calibration_sets: int = 5, **suspect: object) -> list[Active | Rest]:
    """A first set, ``calibration_sets`` normal sets after a REST, then a 50 s REST and a suspect set."""
    rows: list[Active | Rest] = [_normal()]
    for _ in range(calibration_sets):
        rows.extend((Rest(40.0), _normal()))
    fields: dict[str, object] = {"reps": 4, "seconds": 1.629, "hidden_s": 20.0}
    fields.update(suspect)
    rows.extend((Rest(50.0), Active(**fields)))  # type: ignore[arg-type]
    return rows


def _available(samples: list[HeartRateSample]) -> HeartRateLoad:
    return HeartRateLoad(HeartRateStatus.AVAILABLE, tuple(samples), "raw/garmin/activities/9101/details.json")


def _estimate(session: Session, heart_rate: HeartRateLoad | None = None) -> SuspectSet:
    load = heart_rate if heart_rate is not None else _available(heart_rate_samples(session))
    _session, suspects = estimate_session(DAY, strength_activity("9101", session), load)
    return suspects[-1]


def _assert_not_estimated(item: SuspectSet, reason: NotEstimatedReason) -> None:
    assert item.method is TimingMethod.NONE
    assert item.not_estimated_reason is reason
    assert item.heart_rate_onset_at_ms is None
    assert item.estimated_start_at_ms is None
    assert item.estimated_work_ms is None
    assert item.estimated_work_range_ms is None
    assert item.estimated_rest_ms is None
    assert item.estimated_rest_range_ms is None
    assert item.confidence is None


# AC1: which sets are suspect


@pytest.mark.parametrize(
    ("reps", "seconds", "suspect"),
    [
        (5, 1.699, True),
        (4, 1.629, True),
        (20, 60.0, False),
        (10, 10.0, False),  # exactly 1.0 s/rep is not suspect
        (10, 9.999, True),
    ],
)
def test_active_set_is_suspect_below_one_second_per_rep(reps: int, seconds: float, suspect: bool) -> None:
    strength_set = timed_set(1, reps=reps, seconds=seconds)

    assert is_checked(strength_set)
    assert is_suspect(strength_set) is suspect


@pytest.mark.parametrize(("reps", "seconds"), [(None, 1.0), (0, 1.0), (5, None)])
def test_sets_without_reps_or_duration_are_unchecked_not_suspect(reps: int | None, seconds: float | None) -> None:
    strength_set = timed_set(1, reps=reps, seconds=seconds)

    assert not is_checked(strength_set)
    assert not is_suspect(strength_set)


def test_rest_rows_are_never_checked() -> None:
    rest = timed_set(1, set_type="REST", category=None, reps=None, seconds=0.5)

    assert not is_checked(rest)
    assert not is_suspect(rest)


def test_unchecked_sets_are_counted_separately() -> None:
    session = build_session(
        [Active(5, 1.699), Rest(40.0), Active(None, 20.0), Rest(40.0), Active(0, 20.0), Rest(40.0), Active(8, None)]
    )

    summary = summarize_set_timing([(DAY, strength_activity("9101", session))], {})

    assert summary is not None
    assert (summary.active_set_count, summary.checked_set_count, summary.unchecked_set_count) == (4, 1, 3)
    assert summary.suspect_set_count == 1


def test_summary_is_none_without_a_suspect_set() -> None:
    session = build_session([_normal(), Rest(40.0), _normal(), Rest(40.0), Active(20, 60.0)])

    assert summarize_set_timing([(DAY, strength_activity("9101", session))], {}) is None


def test_ac7_shape_marks_both_short_pull_up_sets_and_not_the_normal_one() -> None:
    label = {"category": "PULL_UP", "name": "WIDE_GRIP_PULL_UP"}
    session = build_session(
        [
            Active(5, 1.699, **label),  # type: ignore[arg-type]
            Rest(50.38),
            Active(4, 1.629, **label),  # type: ignore[arg-type]
            Rest(46.6),
            Active(4, 22.089, **label),  # type: ignore[arg-type]
        ]
    )
    item = strength_activity("24797858737", session)

    summary = summarize_set_timing([(DAY, item)], {"24797858737": HeartRateLoad(HeartRateStatus.RAW_MISSING, (), None)})

    assert summary is not None
    assert [(s.sequence, s.label_set_number) for s in summary.suspect_sets] == [(1, 1), (3, 2)]
    assert summary.suspect_sets[0].not_estimated_reason is NotEstimatedReason.NO_PRECEDING_REST
    assert summary.suspect_sets[0].preceding_rest_sequence is None
    assert summary.suspect_sets[1].preceding_rest_sequence == 2
    assert summary.suspect_sets[1].recorded_rest_seconds == 50.38
    assert 5 not in summary.sessions[0].suspect_set_sequences


# Heart-rate parsing


def _series() -> list[HeartRateSample]:
    return [HeartRateSample(START_MS + index * 1000, BASE_BPM + index) for index in range(5)]


def test_parse_finds_columns_by_key_whatever_the_descriptor_order() -> None:
    first = parse_direct_heart_rate(details_payload(_series()))
    permuted = parse_direct_heart_rate(
        details_payload(_series(), order=("directHeartRate", "sumDuration", "directTimestamp"))
    )

    assert first == permuted
    assert first == (HeartRateStatus.AVAILABLE, tuple(_series()))


def test_parse_skips_null_and_non_numeric_cells_never_zero() -> None:
    replacements: dict[int, object] = {1: None, 2: "x", 3: True}

    def cells(sample: HeartRateSample) -> dict[str, object]:
        index = (sample.at_ms - START_MS) // 1000
        return {"directHeartRate": replacements[index]} if index in replacements else {}

    status, samples = parse_direct_heart_rate(details_payload(_series(), cells=cells))

    assert status is HeartRateStatus.AVAILABLE
    assert [sample.at_ms - START_MS for sample in samples] == [0, 4000]
    assert all(sample.bpm > 0 for sample in samples)


def test_parse_conflicting_duplicate_timestamp_is_unreadable() -> None:
    series = [*_series(), HeartRateSample(START_MS, BASE_BPM + 30)]

    assert parse_direct_heart_rate(details_payload(series)) == (HeartRateStatus.RAW_UNREADABLE, ())


def test_parse_identical_duplicate_timestamp_is_kept_once() -> None:
    series = [*_series(), HeartRateSample(START_MS, BASE_BPM)]

    status, samples = parse_direct_heart_rate(details_payload(series))

    assert status is HeartRateStatus.AVAILABLE
    assert len(samples) == 5


def test_parse_without_heart_rate_descriptor_is_not_in_raw() -> None:
    payload = details_payload(_series(), order=("sumDuration", "directTimestamp"))

    assert parse_direct_heart_rate(payload) == (HeartRateStatus.NOT_IN_RAW, ())


@pytest.mark.parametrize(
    "payload",
    [
        [],
        {"metricDescriptors": "x"},
        {"metricDescriptors": [{"key": "directHeartRate", "metricsIndex": "0"}, {"key": "directTimestamp"}]},
        {
            "metricDescriptors": [
                {"key": "directHeartRate", "metricsIndex": 0},
                {"key": "directTimestamp", "metricsIndex": 1},
            ],
            "activityDetailMetrics": [{"metrics": "x"}],
        },
    ],
)
def test_parse_malformed_structure_is_unreadable(payload: object) -> None:
    assert parse_direct_heart_rate(payload)[0] is HeartRateStatus.RAW_UNREADABLE


# AC2: estimate from a clear rise in the preceding REST, lag-corrected


def test_clear_rise_gives_work_and_rest_with_medium_confidence() -> None:
    session = build_session(_ac2_rows())
    item = _estimate(session)
    pressed = session.press_ms[item.sequence]

    assert item.method is TimingMethod.HEART_RATE
    assert item.not_estimated_reason is None
    assert item.estimated_work_ms == 20_000
    assert item.estimated_rest_ms == 30_000
    assert item.confidence is Confidence.MEDIUM
    # Identical calibration lags: the range is the point.
    assert item.estimated_work_range_ms == (20_000, 20_000)
    assert item.estimated_rest_range_ms == (30_000, 30_000)
    assert item.estimated_start_at_ms == pressed - 20_000


def test_lag_is_calibrated_from_the_normal_sets() -> None:
    session = build_session(_ac2_rows())
    timing, _suspects = estimate_session(
        DAY, strength_activity("9101", session), _available(heart_rate_samples(session))
    )

    assert timing.lag is not None
    assert timing.lag.status is LagStatus.CALIBRATED
    assert (timing.lag.median_ms, timing.lag.min_ms, timing.lag.max_ms) == (LAG_MS, LAG_MS, LAG_MS)
    assert timing.lag.set_sequences == (3, 5, 7, 9, 11)


def test_lag_correction_recovers_the_true_start_not_the_heart_rate_low() -> None:
    session = build_session(_ac2_rows())
    item = _estimate(session)
    true_start = session.press_ms[item.sequence] - 20_000

    # The wrist trace starts rising LAG_MS after the work; without the lag the start would be 8 s late.
    assert item.heart_rate_onset_at_ms == true_start + LAG_MS
    assert item.estimated_start_at_ms == true_start


def test_four_calibration_sets_give_low_confidence() -> None:
    item = _estimate(build_session(_ac2_rows(calibration_sets=4)))

    assert item.method is TimingMethod.HEART_RATE
    assert item.confidence is Confidence.LOW


def test_wide_lag_spread_gives_low_confidence_and_a_range() -> None:
    rows = _ac2_rows()
    rows[2] = _normal(lag_ms=20_000)  # first calibration set: lag spread 12 s > 10 s
    item = _estimate(build_session(rows))

    assert item.confidence is Confidence.LOW
    assert item.estimated_work_ms == 20_000
    # Start range [onset - 20 s, onset - 8 s]: work 20..32 s, rest 18..30 s.
    assert item.estimated_work_range_ms == (20_000, 32_000)
    assert item.estimated_rest_range_ms == (18_000, 30_000)


def test_range_ends_are_clipped_to_the_rest() -> None:
    rows = _ac2_rows(hidden_s=3.0, rise_per_s=4.0)
    rows[2] = _normal(lag_ms=2_000)  # lags 2, 8, 8, 8, 8 s: median 8, min 2
    item = _estimate(build_session(rows))

    assert item.method is TimingMethod.HEART_RATE
    assert item.estimated_work_ms == 3_000
    assert item.estimated_rest_ms == 47_000
    # onset - 2 s lies after the button press; that end is clipped to the press.
    assert item.estimated_work_range_ms == (0, 3_000)
    assert item.estimated_rest_range_ms == (47_000, 50_000)


@pytest.mark.parametrize("hidden_s", [0.0, 1.0, 5.0, 12.0, 25.0, 33.0, 40.0, 45.0, 49.0, 50.0])
def test_estimates_never_leave_the_rest(hidden_s: float) -> None:
    session = build_session(_ac2_rows(hidden_s=hidden_s, rise_per_s=4.0))
    item = _estimate(session)
    pressed = session.press_ms[item.sequence]
    rest_span = 50_000

    if item.method is TimingMethod.NONE:
        assert item.not_estimated_reason is not None
        _assert_not_estimated(item, item.not_estimated_reason)
        return
    assert item.estimated_rest_ms is not None and item.estimated_work_ms is not None
    assert item.estimated_rest_ms >= 0
    assert item.estimated_work_ms <= rest_span
    assert item.estimated_rest_ms + item.estimated_work_ms == rest_span
    assert item.estimated_start_at_ms is not None
    assert pressed - rest_span <= item.estimated_start_at_ms <= pressed
    assert item.estimated_work_range_ms is not None and item.estimated_rest_range_ms is not None
    for low, high in (item.estimated_work_range_ms, item.estimated_rest_range_ms):
        assert 0 <= low <= high <= rest_span


def test_most_onset_positions_are_estimated() -> None:
    estimated = [
        _estimate(build_session(_ac2_rows(hidden_s=hidden, rise_per_s=4.0))).method is TimingMethod.HEART_RATE
        for hidden in (5.0, 12.0, 25.0, 33.0)
    ]

    assert all(estimated)


# AC3: no estimate without clear evidence


def test_missing_details_is_not_estimated() -> None:
    item = _estimate(build_session(_ac2_rows()), HeartRateLoad(HeartRateStatus.RAW_MISSING, (), None))

    _assert_not_estimated(item, NotEstimatedReason.HEART_RATE_RAW_MISSING)


@pytest.mark.parametrize(
    ("status", "reason"),
    [
        (HeartRateStatus.RAW_UNREADABLE, NotEstimatedReason.HEART_RATE_RAW_UNREADABLE),
        (HeartRateStatus.NOT_IN_RAW, NotEstimatedReason.HEART_RATE_NOT_IN_RAW),
    ],
)
def test_unusable_heart_rate_raw_is_not_estimated(status: HeartRateStatus, reason: NotEstimatedReason) -> None:
    item = _estimate(build_session(_ac2_rows()), HeartRateLoad(status, (), "raw/garmin/activities/9101/details.json"))

    _assert_not_estimated(item, reason)


def test_details_without_heart_rate_descriptor_is_not_estimated() -> None:
    session = build_session(_ac2_rows())
    status, samples = parse_direct_heart_rate(
        details_payload(heart_rate_samples(session), order=("sumDuration", "directTimestamp"))
    )

    item = _estimate(session, HeartRateLoad(status, samples, None))

    _assert_not_estimated(item, NotEstimatedReason.HEART_RATE_NOT_IN_RAW)


def _suspect_rest_start(session: Session) -> int:
    return session.press_ms[max(session.press_ms)] - 50_000


def test_long_gap_in_the_window_is_not_estimated() -> None:
    session = build_session(_ac2_rows())
    rest_start = _suspect_rest_start(session)
    # An 11 s hole inside the suspect set's REST; the calibration sets are untouched.
    samples = heart_rate_samples(session, drop=lambda at: rest_start + 20_000 < at < rest_start + 31_000)

    _assert_not_estimated(_estimate(session, _available(samples)), NotEstimatedReason.HEART_RATE_GAP)


def test_ten_second_gap_is_still_estimated() -> None:
    session = build_session(_ac2_rows())
    rest_start = _suspect_rest_start(session)
    samples = heart_rate_samples(session, drop=lambda at: rest_start + 20_000 < at < rest_start + 30_000)

    assert _estimate(session, _available(samples)).method is TimingMethod.HEART_RATE


def test_nine_bpm_rise_is_unclear() -> None:
    _assert_not_estimated(_estimate(build_session(_ac2_rows(cap=9.0))), NotEstimatedReason.RISE_UNCLEAR)


def test_heart_rate_rising_from_the_rest_start_is_unclear() -> None:
    session = build_session(_ac2_rows())
    rest_start = _suspect_rest_start(session)

    def rising(at: int) -> float | None:
        if rest_start <= at <= rest_start + 80_000:
            return BASE_BPM + (at - rest_start) / 1000
        return None

    item = _estimate(session, _available(heart_rate_samples(session, override=rising)))

    _assert_not_estimated(item, NotEstimatedReason.RISE_UNCLEAR)


def test_two_calibration_sets_leave_the_lag_uncalibrated() -> None:
    session = build_session(_ac2_rows(calibration_sets=2))
    timing, suspects = estimate_session(
        DAY, strength_activity("9101", session), _available(heart_rate_samples(session))
    )

    _assert_not_estimated(suspects[-1], NotEstimatedReason.LAG_UNCALIBRATED)
    assert timing.lag is not None
    assert timing.lag.status is LagStatus.UNCALIBRATED
    assert timing.lag.median_ms is None
    assert timing.lag.set_sequences == (3, 5)


def test_suspect_first_row_has_no_preceding_rest() -> None:
    session = build_session([Active(5, 1.699), Rest(40.0), _normal()])
    item = strength_activity("9101", session)

    assert not needs_heart_rate(item)
    timing, suspects = estimate_session(DAY, item, None)
    _assert_not_estimated(suspects[0], NotEstimatedReason.NO_PRECEDING_REST)
    assert timing.heart_rate is None
    assert timing.lag is None


def test_suspect_after_an_active_set_has_no_preceding_rest() -> None:
    session = build_session([_normal(), Active(5, 1.699)])
    item = strength_activity("9101", session)

    assert not needs_heart_rate(item)
    _timing, suspects = estimate_session(DAY, item, None)
    _assert_not_estimated(suspects[0], NotEstimatedReason.NO_PRECEDING_REST)


def test_unparseable_set_time_is_not_estimated() -> None:
    session = build_session(_ac2_rows())
    samples = heart_rate_samples(session)
    sets = list(session.sets)
    sets[-1] = timed_set(sets[-1].sequence, reps=4, seconds=1.629, started_at="not a time")
    session.sets = tuple(sets)

    _assert_not_estimated(_estimate(session, _available(samples)), NotEstimatedReason.SET_TIME_MISSING)


def test_set_clock_nine_hours_off_the_series_is_unverified() -> None:
    session = build_session(_ac2_rows())
    samples = heart_rate_samples(session, clock_shift_ms=9 * 3600 * 1000)

    timing, suspects = estimate_session(DAY, strength_activity("9101", session), _available(samples))

    _assert_not_estimated(suspects[-1], NotEstimatedReason.CLOCK_UNVERIFIED)
    assert timing.lag is None


def test_needed_heart_rate_missing_from_the_loads_counts_as_raw_missing() -> None:
    summary = summarize_set_timing([(DAY, strength_activity("9101", build_session(_ac2_rows())))], {})

    assert summary is not None
    _assert_not_estimated(summary.suspect_sets[-1], NotEstimatedReason.HEART_RATE_RAW_MISSING)


# find_rise_onset directly


def _points(points: list[tuple[int, float]]) -> list[HeartRateSample]:
    return [HeartRateSample(START_MS + seconds * 1000, bpm) for seconds, bpm in points]


def test_rise_onset_is_the_latest_low_point() -> None:
    samples = _points([(0, 120.0), (2, 100.0), (4, 100.0), (6, 105.0), (8, 112.0)])

    assert find_rise_onset(samples, START_MS, START_MS + 5000, START_MS + 8000) == START_MS + 4000


def test_rise_onset_needs_samples_near_both_window_ends() -> None:
    samples = _points([(0, 120.0), (2, 100.0), (4, 100.0), (6, 115.0)])

    # The window runs to 20 s, but the last sample is at 6 s: 14 s uncovered.
    onset = find_rise_onset(samples, START_MS, START_MS + 5000, START_MS + 20_000)

    assert onset is NotEstimatedReason.HEART_RATE_GAP


# Rest between sets


def _rest_summary(rows: list[Active | Rest], *, heart_rate: bool = True) -> RestBetweenSets:
    session = build_session(rows)
    item = strength_activity("9101", session)
    loads = {"9101": _available(heart_rate_samples(session))} if heart_rate else {}
    summary = summarize_set_timing([(DAY, item)], loads)
    assert summary is not None
    return summary.rest_between_sets


def test_rest_between_sets_uses_recorded_rest_and_the_estimate_where_available() -> None:
    rest = _rest_summary(_ac2_rows())

    # Five recorded 40 s rests and one estimated 30 s rest, all BENCH_PRESS (compound).
    assert (rest.overall.median_seconds, rest.overall.rest_count, rest.overall.estimated_rest_count) == (40.0, 6, 1)
    assert rest.compound.rest_count == 6
    assert (rest.isolation.median_seconds, rest.isolation.rest_count) == (None, 0)
    assert rest.unclassified.median_seconds is None


def test_estimated_rest_replaces_the_recorded_rest() -> None:
    rows: list[Active | Rest] = [_normal()]
    for _ in range(5):
        rows.extend((Rest(40.0), _normal(category="CURL")))
    rows.extend((Rest(50.0), Active(4, 1.629, category="CURL", hidden_s=20.0)))
    rest = _rest_summary(rows)

    # 4 recorded CURL rests of 40 s and the estimated 30 s (not the recorded 50 s).
    assert (rest.isolation.rest_count, rest.isolation.estimated_rest_count) == (5, 1)
    assert rest.isolation.median_seconds == 40.0
    assert rest.excluded_label_change_or_unknown == 1


def test_rest_between_sets_counts_exclusions() -> None:
    rows: list[Active | Rest] = [
        Active(5, 1.699),
        Rest(40.0),
        Active(4, 1.629),  # suspect, not estimated (no heart rate given)
        Rest(None),
        _normal(),  # recorded rest missing
        Rest(40.0),
        _normal(category="CURL"),  # label change
        Rest(40.0),
        _normal(category="CURL", reps=None),  # unchecked
        Rest(40.0),
        _normal(category="UNKNOWN"),  # UNKNOWN label (this and the next two)
        Rest(40.0),
        _normal(category="UNKNOWN"),
        Rest(45.0),
        _normal(category="UNKNOWN"),
    ]
    rest = _rest_summary(rows, heart_rate=False)

    assert rest.excluded_not_estimated == 1
    assert rest.excluded_missing_duration == 1
    assert rest.excluded_label_change_or_unknown == 4
    assert rest.excluded_unchecked == 1
    assert (rest.overall.median_seconds, rest.overall.rest_count) == (None, 0)


def test_rest_between_sets_groups_compound_isolation_and_unclassified() -> None:
    rows: list[Active | Rest] = [
        Active(5, 1.699),
        Rest(60.0),
        _normal(),
        Rest(90.0),
        _normal(),
        Rest(30.0),
        _normal(category="CURL"),
        Rest(50.0),
        _normal(category="CURL"),
        Rest(40.0),
        _normal(category="PULL_UP", name="WIDE_GRIP_PULL_UP"),
        Rest(44.0),
        _normal(category="PULL_UP", name="WIDE_GRIP_PULL_UP"),
    ]
    rest = _rest_summary(rows, heart_rate=False)

    assert (rest.compound.median_seconds, rest.compound.rest_count) == (75.0, 2)
    assert (rest.isolation.median_seconds, rest.isolation.rest_count) == (50.0, 1)
    # PULL_UP/WIDE_GRIP_PULL_UP has no taxonomy rule.
    assert (rest.unclassified.median_seconds, rest.unclassified.rest_count) == (44.0, 1)
    assert (rest.overall.median_seconds, rest.overall.rest_count) == (55.0, 4)
    # BENCH_PRESS -> CURL and CURL -> PULL_UP are label changes.
    assert rest.excluded_label_change_or_unknown == 2
    assert rest.excluded_not_estimated == 0
