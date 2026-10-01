from __future__ import annotations

import dataclasses
from datetime import date, timedelta

from analytics_builders import activity, lap, length, load_metrics, swim_detail

from muscle50.domain.activity import ActivityType, NormalizedActivity
from muscle50.domain.recovery_assessment import AdjustmentLevel
from muscle50.domain.swim_recommendation import (
    StrengthContext,
    SwimRecommendation,
    SwimSessionType,
    analyze_swims,
    build_swim_recommendation,
)
from muscle50.domain.swimming import SwimLap, SwimLength
from muscle50.domain.training_goals import DEFAULT_TRAINING_GOALS

AS_OF = date(2026, 3, 20)
NO_STRENGTH = StrengthContext(0, 0, None)


def _length(sequence: int, distance: float, seconds: float, stroke: str | None = "freestyle") -> SwimLength:
    return dataclasses.replace(length(sequence, distance, seconds), stroke_type=stroke)


def _lap(sequence: int, lengths: list[SwimLength]) -> SwimLap:
    distance = sum(item.distance.garmin_meters or 0.0 for item in lengths)
    seconds = sum(item.duration_seconds or 0.0 for item in lengths)
    return lap(sequence, distance, seconds, tuple(lengths))


def _continuous(sequence: int, meters: float, seconds_per_25: float = 30.0, stroke: str = "freestyle") -> SwimLap:
    return _lap(sequence, [_length(index, 25.0, seconds_per_25, stroke) for index in range(int(meters // 25))])


def _swim(
    source_id: str, day: date, laps: list[SwimLap], *, summary: float | None = None, **metrics: float
) -> NormalizedActivity:
    distance = summary if summary is not None else sum(item.distance.garmin_meters or 0.0 for item in laps)
    values = {"hr_time_in_zone_5_seconds": 0.0, "anaerobic_training_effect": 1.5, **metrics}
    return activity(
        source_id,
        f"{day.isoformat()}T06:00:00",
        ActivityType.SWIMMING,
        distance_meters=distance,
        swim_detail=swim_detail(source_id, tuple(laps)),
        metrics=load_metrics(**values),
    )


def _days_ago(days: int) -> date:
    return AS_OF - timedelta(days=days)


def _recommend(
    swims: list[NormalizedActivity],
    level: AdjustmentLevel = AdjustmentLevel.NORMAL,
    strength: StrengthContext = NO_STRENGTH,
) -> SwimRecommendation:
    return build_swim_recommendation(AS_OF, analyze_swims(AS_OF, swims), level, strength, DEFAULT_TRAINING_GOALS)


def test_phantom_lap_and_contaminated_summary_are_never_baselines() -> None:
    # 2026-09-17 shape: a 2500 m lap in under 2 s, included in the Garmin summary distance.
    phantom = lap(0, 2500.0, 1.787, tuple(length(index, 25.0, 0.01) for index in range(100)))
    swim = _swim("anomaly", _days_ago(2), [phantom, _continuous(1, 200.0)], summary=2700.0)

    recommendation = _recommend([swim])

    session = recommendation.sessions[0]
    assert session.summary_distance_meters == 2700.0  # reported unchanged
    assert session.distance_meters == 200.0
    assert session.excluded_lap_sequences == (0,)
    assert session.longest_segment is not None and session.longest_segment.distance_meters == 200.0
    assert recommendation.baseline.recent_longest_segment is not None
    assert recommendation.baseline.recent_longest_segment.distance_meters == 200.0
    assert recommendation.baseline.progression_anchor_meters == DEFAULT_TRAINING_GOALS.continuous_swim_baseline_meters
    assert "2700 m includes implausible lap(s) 0" in recommendation.excluded_baselines[0]


def test_distance_progression_without_a_recent_distance_effort() -> None:
    recommendation = _recommend([_swim("short", _days_ago(2), [_continuous(0, 200.0), _continuous(1, 200.0)])])

    goal = recommendation.goal
    assert goal.session_type == SwimSessionType.DISTANCE_PROGRESSION
    assert goal.target_continuous_meters == 1100.0  # configured 1000 m + 100 m
    assert "no stops" in goal.main_set


def test_recent_data_above_the_configured_baseline_moves_the_anchor() -> None:
    # Last distance effort over a week ago, followed by a short swim.
    recommendation = _recommend(
        [_swim("long", _days_ago(10), [_continuous(0, 1200.0)]), _swim("short", _days_ago(2), [_continuous(0, 200.0)])]
    )

    assert recommendation.baseline.progression_anchor_meters == 1200.0
    assert recommendation.goal.session_type == SwimSessionType.DISTANCE_PROGRESSION
    assert recommendation.goal.target_continuous_meters == 1300.0


def test_distance_target_is_capped_at_the_goal_and_becomes_a_time_goal() -> None:
    # Last distance effort over a week ago, followed by a short swim.
    recommendation = _recommend(
        [_swim("long", _days_ago(10), [_continuous(0, 1500.0)]), _swim("short", _days_ago(2), [_continuous(0, 200.0)])]
    )

    goal = recommendation.goal
    assert goal.target_continuous_meters == 1500.0
    assert "24:00-27:30" in goal.main_set


def test_pace_intervals_follow_a_distance_effort() -> None:
    swims = [_swim("distance", _days_ago(2), [_continuous(0, 1000.0, seconds_per_25=26.0)])]

    recommendation = _recommend(swims)

    goal = recommendation.goal
    assert goal.session_type == SwimSessionType.PACE_INTERVALS
    # Current pace 104 s/100 m: intervals 4 s and 1 s faster, inside the 96-110 s goal band.
    assert goal.target_pace_seconds_per_100m == (100.0, 103.0)
    assert goal.main_set.startswith("8 x 100 m freestyle at 1:40/100 m-1:43/100 m")


def test_easy_swim_when_a_distance_effort_is_recent_but_not_last() -> None:
    swims = [
        _swim("distance", _days_ago(4), [_continuous(0, 1000.0)]),
        _swim("short", _days_ago(2), [_continuous(0, 200.0)]),
    ]

    assert _recommend(swims).goal.session_type == SwimSessionType.EASY_CONTINUOUS


def test_recovery_swim_after_poor_recovery_or_a_hard_swim() -> None:
    easy = [_swim("distance", _days_ago(2), [_continuous(0, 1000.0)])]
    hard = [_swim("hard", _days_ago(1), [_continuous(0, 400.0)], hr_time_in_zone_5_seconds=300.0)]

    assert _recommend(easy, AdjustmentLevel.REDUCE).goal.session_type == SwimSessionType.RECOVERY_TECHNIQUE
    goal = _recommend(hard).goal
    assert goal.session_type == SwimSessionType.RECOVERY_TECHNIQUE
    assert "no butterfly" in goal.main_set


def test_heavy_upper_body_strength_moves_intervals_to_easy_and_adds_cautions() -> None:
    swims = [_swim("distance", _days_ago(2), [_continuous(0, 1000.0)])]

    goal = _recommend(swims, strength=StrengthContext(12, 0, "push")).goal

    assert goal.session_type == SwimSessionType.EASY_CONTINUOUS
    assert any("no butterfly or paddles" in item for item in goal.cautions)
    assert any("separate them by several hours" in item for item in goal.cautions)


def test_requested_shoulders_focus_keeps_the_upper_body_swim_cautions() -> None:
    swims = [_swim("distance", _days_ago(2), [_continuous(0, 1000.0)])]

    goal = _recommend(swims, strength=StrengthContext(0, 0, "shoulders")).goal

    assert any("no butterfly or paddles" in item for item in goal.cautions)
    assert any("today's strength focus is shoulders" in item for item in goal.cautions)
    assert not any("kick sets" in item for item in goal.cautions)


def test_idle_length_splits_a_lap_into_separate_continuous_segments() -> None:
    lengths = [_length(index, 25.0, 30.0) for index in range(8)]
    lengths.insert(4, _length(99, 0.0, 45.0, stroke=None))  # 45 s wall rest recorded as idle
    lengths.insert(2, _length(98, 0.0, 0.8, stroke=None))  # sub-second idle artefact: not a rest
    swim = _swim("rest", _days_ago(3), [_lap(0, lengths)])

    session = _recommend([swim]).sessions[0]

    assert session.longest_segment is not None
    assert session.longest_segment.distance_meters == 100.0


def test_butterfly_and_hr_zone_mark_high_intensity_only_from_stored_signals() -> None:
    fly = _swim("fly", _days_ago(1), [_continuous(0, 200.0, stroke="butterfly")])
    hr = _swim("hr", _days_ago(1), [_continuous(0, 200.0)], anaerobic_training_effect=2.6)

    fly_session, hr_session = _recommend([fly, hr]).sessions

    assert fly_session.butterfly_meters == 200.0
    assert not fly_session.high_intensity
    assert hr_session.high_intensity
    assert hr_session.high_intensity_reasons == ("anaerobic TE 2.6 >= 2.5",)


def test_pace_baseline_ignores_mixed_strokes_and_implausibly_fast_lengths() -> None:
    mixed = _continuous(0, 400.0, seconds_per_25=20.0, stroke="breaststroke")
    fast = _lap(1, [_length(index, 25.0, 30.0) for index in range(7)] + [_length(7, 25.0, 5.0)])
    swim = _swim("pace", _days_ago(3), [mixed, fast])

    assert _recommend([swim]).baseline.recent_best_pace_segment is None


def test_missing_metrics_are_not_high_intensity() -> None:
    swim = activity(
        "bare",
        f"{_days_ago(1).isoformat()}T06:00:00",
        ActivityType.SWIMMING,
        distance_meters=400.0,
        swim_detail=swim_detail("bare", (_continuous(0, 400.0),)),
        metrics=(),
    )

    session = _recommend([swim]).sessions[0]

    assert session.hr_zone_5_seconds is None
    assert not session.high_intensity


def test_long_lap_with_implausible_length_timing_is_not_a_distance_baseline() -> None:
    # 2026-07-28 shape: one 1900 m lap whose lengths include impossible 14 s / 50 m timings.
    lengths = [_length(index, 50.0, 47.0) for index in range(36)] + [_length(36, 50.0, 14.0) for _ in range(2)]
    swim = _swim("long", _days_ago(3), [_lap(0, lengths), _continuous(1, 400.0)])

    recommendation = _recommend([swim])

    session = recommendation.sessions[0]
    assert session.longest_segment is not None and session.longest_segment.distance_meters == 400.0
    assert session.longest_implausible_segment is not None
    assert session.longest_implausible_segment.distance_meters == 1900.0
    assert recommendation.baseline.progression_anchor_meters == 1000.0
    assert any(caution.startswith("ignored as baseline: 1900 m") for caution in recommendation.goal.cautions)


# --- history window and return-to-swim -------------------------------------------------------


def test_swim_history_starts_on_the_same_day_as_strength_history() -> None:
    from muscle50.domain.strength_recommendation import HISTORY_DAYS, strength_history

    on_start = _swim("start", _days_ago(28), [_continuous(0, 400.0)])
    before_start = _swim("before", _days_ago(29), [_continuous(0, 400.0)])

    sessions = analyze_swims(AS_OF, [on_start, before_start])

    assert [item.source_activity_id for item in sessions] == ["start"]
    strength = [
        activity(source_id, f"{day.isoformat()}T12:00:00", ActivityType.STRENGTH)
        for source_id, day in (("s_start", _days_ago(28)), ("s_before", _days_ago(29)))
    ]
    window = strength_history(strength, AS_OF - timedelta(days=HISTORY_DAYS), AS_OF - timedelta(days=1))
    assert [item.source_activity_id for _day, item in window] == ["s_start"]


def test_long_swim_gap_gives_an_easy_re_entry_instead_of_more_distance() -> None:
    # 2026-10-01 shape: last stored swim 14 days ago, configured baseline 1000 m.
    plan = _recommend([_swim("old", _days_ago(14), [_continuous(0, 650.0)])])

    goal = plan.goal
    assert goal.session_type == SwimSessionType.RETURN_EASY
    assert goal.target_continuous_meters == 800.0  # below the 1000 m anchor: no distance increase
    assert goal.target_pace_seconds_per_100m is None  # no intensity increase
    assert goal.total_meters == 800.0
    assert "no pace target" in goal.main_set
    assert "butterfly" not in goal.main_set and "freestyle" not in goal.main_set  # no invented stroke detail
    assert any("14 days ago (>= 10 days)" in text for text in goal.reasons)
    assert any("long-term target 1500 m is unchanged" in text for text in goal.reasons)
    assert any("not synced" in text for text in goal.reasons)
    assert plan.baseline.days_since_last_swim == 14
    assert plan.baseline.long_term_target_meters == 1500.0


def test_a_normal_gap_keeps_distance_progression() -> None:
    plan = _recommend([_swim("recent", _days_ago(9), [_continuous(0, 400.0)])])

    assert plan.goal.session_type == SwimSessionType.DISTANCE_PROGRESSION
    assert plan.goal.target_continuous_meters == 1100.0


def test_no_stored_swim_is_a_re_entry() -> None:
    plan = _recommend([])

    assert plan.goal.session_type == SwimSessionType.RETURN_EASY
    assert plan.baseline.days_since_last_swim is None
    assert any("no swim stored in the last 28 days" in text for text in plan.goal.reasons)


def test_recovery_reduce_still_wins_over_a_re_entry() -> None:
    plan = _recommend([_swim("old", _days_ago(14), [_continuous(0, 650.0)])], AdjustmentLevel.REDUCE)

    assert plan.goal.session_type == SwimSessionType.RECOVERY_TECHNIQUE


def test_re_entry_keeps_anomaly_safe_baselines() -> None:
    phantom = lap(0, 2500.0, 1.787, ())
    plan = _recommend([_swim("phantom", _days_ago(12), [phantom, _continuous(1, 500.0)], summary=3025.0)])

    assert plan.goal.session_type == SwimSessionType.RETURN_EASY
    assert plan.baseline.progression_anchor_meters == 1000.0
    assert plan.excluded_baselines
