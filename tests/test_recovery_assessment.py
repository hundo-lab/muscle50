from __future__ import annotations

from datetime import date

import pytest
from analytics_builders import recovery

from muscle50.domain.recovery_assessment import AdjustmentLevel, assess_recovery

AS_OF = date(2026, 9, 25)


def test_no_rows_is_missing_not_poor() -> None:
    assessment = assess_recovery(AS_OF, ())

    assert assessment.level is AdjustmentLevel.NORMAL
    assert not assessment.data_available
    assert not assessment.requested_date_row_available
    assert assessment.fired == ()
    assert "sleep_seconds" in assessment.missing_fields


def test_null_fields_never_fire() -> None:
    row = recovery(
        AS_OF.isoformat(),
        sleep_seconds=None,
        sleep_score=None,
        hrv_status=None,
        training_readiness_level=None,
        recovery_time_minutes=None,
    )

    assessment = assess_recovery(AS_OF, (row,))

    assert assessment.level is AdjustmentLevel.NORMAL
    assert set(assessment.missing_fields) >= {"sleep_seconds", "sleep_score", "hrv_status", "recovery_time_minutes"}


@pytest.mark.parametrize(
    ("overrides", "level"),
    [
        ({}, AdjustmentLevel.NORMAL),
        ({"sleep_seconds": 4 * 3600 + 60}, AdjustmentLevel.HOLD),
        ({"sleep_seconds": 3 * 3600}, AdjustmentLevel.REDUCE),
        ({"sleep_score": 45}, AdjustmentLevel.HOLD),
        ({"hrv_status": "UNBALANCED"}, AdjustmentLevel.HOLD),
        ({"training_readiness_level": "LOW"}, AdjustmentLevel.HOLD),
        ({"training_readiness_level": "POOR"}, AdjustmentLevel.REDUCE),
        ({"recovery_time_minutes": 800}, AdjustmentLevel.HOLD),
        ({"recovery_time_minutes": 1500}, AdjustmentLevel.REDUCE),
        # Day-level values that can describe the state after training are never used.
        ({"body_battery_high": 5, "stress_average": 90, "resting_heart_rate_bpm": 80.0}, AdjustmentLevel.NORMAL),
    ],
)
def test_each_rule_fires_alone(overrides: dict[str, object], level: AdjustmentLevel) -> None:
    row = recovery(AS_OF.isoformat(), **{"recovery_time_minutes": 0, **overrides})
    assert assess_recovery(AS_OF, (row,)).level is level


def test_training_status_comes_from_the_previous_day() -> None:
    today = recovery(AS_OF.isoformat(), training_status_key="STRAINED", recovery_time_minutes=0)
    yesterday = recovery("2026-09-24", training_status_key="UNPRODUCTIVE")

    assessment = assess_recovery(AS_OF, (today, yesterday))

    status = next(item for item in assessment.observations if item.field == "training_status_key")
    assert status.source_date == date(2026, 9, 24)
    assert status.value == "UNPRODUCTIVE"
    assert assessment.level is AdjustmentLevel.HOLD


def test_strongest_rule_wins_and_every_fired_rule_is_listed() -> None:
    row = recovery(AS_OF.isoformat(), sleep_score=40, training_readiness_level="POOR", recovery_time_minutes=0)

    assessment = assess_recovery(AS_OF, (row,))

    assert assessment.level is AdjustmentLevel.REDUCE
    assert {item.field for item in assessment.fired} == {"sleep_score", "training_readiness_level"}


# --- lookback when the requested date has no sleep measurement -------------------------------


def _day(offset: int) -> str:
    return date.fromordinal(AS_OF.toordinal() - offset).isoformat()


def test_complete_requested_row_uses_no_lookback() -> None:
    rows = (recovery(_day(0)), recovery(_day(1), sleep_seconds=3 * 3600, training_readiness_level="POOR"))

    assessment = assess_recovery(AS_OF, rows)

    assert assessment.lookback is None
    assert assessment.level is AdjustmentLevel.NORMAL


def test_partial_row_does_not_erase_a_very_short_sleep_yesterday() -> None:
    # 2026-10-01 shape: today has readiness but no sleep; yesterday slept 3.8 h with LOW readiness.
    rows = (
        recovery(_day(0), sleep_seconds=None, sleep_score=None, training_readiness_level="MODERATE"),
        recovery(_day(1), sleep_seconds=13740, sleep_score=50, training_readiness_level="LOW"),
        recovery(_day(2), sleep_seconds=18960, sleep_score=51, training_readiness_level="LOW"),
    )

    assessment = assess_recovery(AS_OF, rows)

    assert assessment.level is AdjustmentLevel.HOLD  # capped: not today's measurement
    assert assessment.carried
    assert assessment.lookback is not None
    assert assessment.lookback.poor_dates == (date.fromisoformat(_day(1)), date.fromisoformat(_day(2)))
    assert "fired a reduce-level rule" in assessment.lookback.explanation
    assert "sleep_seconds 3h49m" in assessment.lookback.explanation
    # Today's own observations and missing fields are not polluted by earlier days.
    assert assessment.fired == ()
    assert {item.source_date for item in assessment.observations} <= {AS_OF, date.fromisoformat(_day(1))}
    assert "sleep_seconds" in assessment.missing_fields


def test_two_poor_mornings_carry_hold_when_today_has_no_row() -> None:
    rows = (
        recovery(_day(1), training_readiness_level="LOW"),
        recovery(_day(2), training_readiness_level="LOW"),
    )

    assessment = assess_recovery(AS_OF, rows)

    assert assessment.level is AdjustmentLevel.HOLD
    assert assessment.lookback is not None
    assert "both of the previous 2 mornings were poor" in assessment.lookback.explanation


def test_one_hold_level_morning_is_reported_but_not_carried() -> None:
    rows = (recovery(_day(0), sleep_seconds=None), recovery(_day(1), training_readiness_level="LOW"), recovery(_day(2)))

    assessment = assess_recovery(AS_OF, rows)

    assert assessment.level is AdjustmentLevel.NORMAL
    assert assessment.lookback is not None and not assessment.carried
    assert "not enough to carry forward" in assessment.lookback.explanation


def test_missing_earlier_rows_never_fire_the_lookback() -> None:
    assessment = assess_recovery(AS_OF, (recovery(_day(0), sleep_seconds=None),))

    assert assessment.level is AdjustmentLevel.NORMAL
    assert assessment.lookback is not None and assessment.lookback.poor_dates == ()
    assert "fired no rule" in assessment.lookback.explanation


def test_carried_hold_never_weakens_a_poor_reading_today() -> None:
    rows = (
        recovery(_day(0), sleep_seconds=None, training_readiness_level="POOR"),
        recovery(_day(1), training_readiness_level="LOW"),
        recovery(_day(2), training_readiness_level="LOW"),
    )

    assert assess_recovery(AS_OF, rows).level is AdjustmentLevel.REDUCE
