"""Goal-mode rules (pure domain): cut progression, weekly sets, InBody rates, run/legs gaps, short nights."""

from __future__ import annotations

import re
from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from analytics_builders import activity, recovery, strength_set
from goal_mode_builders import legs, run

from muscle50.domain import goal_mode
from muscle50.domain.activity import ActivityType, NormalizedActivity
from muscle50.domain.body_composition_trend import StoredBodyComposition, TrendMetric, metric_points
from muscle50.domain.goal_mode import (
    GoalModeReport,
    apply_cut_progression,
    cut_nutrition_reference,
    goal_progress,
    run_legs_pairs,
    short_sleep_nights,
    smm_floor,
    weekly_muscle_sets,
    weight_change,
)
from muscle50.domain.recovery_assessment import DEFAULT_SLEEP_THRESHOLDS
from muscle50.domain.strength_recommendation import (
    LOAD_STEP_SMALLEST_AVAILABLE,
    ProgressionAction,
    StrengthRecommendation,
)
from muscle50.domain.training_goal import DEFAULT_SLEEP_SETTING, GoalMode, TrainingGoal, WeeklyRateRange
from muscle50.domain.training_recommendation import TrainingRecommendation, build_training_recommendation

D = date(2026, 3, 16)
EVIDENCE_DOC = Path(__file__).parents[1] / "docs" / "evidence" / "training-nutrition-evidence.md"
CUT = TrainingGoal(GoalMode.CUT, weekly_loss_percent=WeeklyRateRange(Decimal("0.3"), Decimal("0.5")))


def _day(offset: int) -> str:
    return (D - timedelta(days=offset)).isoformat()


def _squat(source_id: str, offset: int, reps: tuple[int | None, ...], weight: float | None) -> NormalizedActivity:
    sets = tuple(
        strength_set(index, category="SQUAT", reps=count, weight_kg=weight) for index, count in enumerate(reps, 1)
    )
    return activity(source_id, f"{_day(offset)}T18:00:00", ActivityType.STRENGTH, strength_sets=sets)


def _plan(
    activities: list[NormalizedActivity], *, goal: TrainingGoal | None = None, sleep: int | None = 27000
) -> TrainingRecommendation:
    return build_training_recommendation(D, activities, [recovery(D.isoformat(), sleep_seconds=sleep)], goal=goal)


def _strength(activities: list[NormalizedActivity], *, sleep: int | None = 27000) -> StrengthRecommendation:
    return _plan(activities, sleep=sleep).strength


# --- cut progression (AC3) ---------------------------------------------------------------------


def test_increase_load_with_a_numeric_target_becomes_maintain_load() -> None:
    history = [_squat("1", 6, (12, 12, 12), 60.0)]
    gain = _strength(history).exercises[0].progression
    assert (gain.action, gain.load_kg, gain.target_reps) == (ProgressionAction.INCREASE_LOAD, 62.5, 8)

    cut, changes = apply_cut_progression(_strength(history))
    target = cut.exercises[0].progression
    assert (target.action, target.load_kg, target.target_reps) == (ProgressionAction.MAINTAIN_LOAD, 60.0, 12)
    assert (target.load_increase_from_kg, target.load_step) == (None, None)
    assert target.basis == (
        *gain.basis,
        "cut goal (user setting): keep 60 kg x 12 instead of increase_load; that target is optional "
        "[MAINT-02, MAINT-06; optional PROG-03]",
    )
    assert target.load_confidence == gain.load_confidence
    (change,) = changes
    assert (change.label, change.load_kg, change.target_reps) == ("SQUAT/-", 60.0, 12)
    assert (change.optional_action, change.optional_load_kg, change.optional_target_reps) == (
        ProgressionAction.INCREASE_LOAD,
        62.5,
        8,
    )
    assert change.evidence == ("MAINT-02", "MAINT-06", "PROG-03")


def test_increase_load_by_the_next_step_becomes_maintain_load() -> None:
    history = [_squat("1", 6, (12, 12, 12), 10.0)]  # 2.5 kg is 25 % of 10 kg: no exact number
    gain = _strength(history).exercises[0].progression
    assert (gain.action, gain.load_kg, gain.load_increase_from_kg, gain.load_step) == (
        ProgressionAction.INCREASE_LOAD,
        None,
        10.0,
        LOAD_STEP_SMALLEST_AVAILABLE,
    )
    cut, (change,) = apply_cut_progression(_strength(history))
    target = cut.exercises[0].progression
    assert (target.action, target.load_kg, target.target_reps, target.load_step) == (
        ProgressionAction.MAINTAIN_LOAD,
        10.0,
        12,
        None,
    )
    assert (change.optional_load_kg, change.optional_load_increase_from_kg, change.optional_load_step) == (
        None,
        10.0,
        LOAD_STEP_SMALLEST_AVAILABLE,
    )


def test_add_reps_becomes_maintain_load_at_the_last_reps() -> None:
    history = [_squat("1", 6, (10, 9, 8), 60.0)]
    cut, (change,) = apply_cut_progression(_strength(history))
    target = cut.exercises[0].progression
    assert (target.action, target.load_kg, target.target_reps) == (ProgressionAction.MAINTAIN_LOAD, 60.0, 10)
    assert (change.optional_action, change.optional_load_kg, change.optional_target_reps) == (
        ProgressionAction.ADD_REPS,
        60.0,
        11,
    )


def test_recovery_maintain_is_kept() -> None:
    history = [_squat("1", 6, (12, 12, 12), 60.0)]
    held = _strength(history, sleep=4 * 3600 + 1800)  # 4.5 h: recovery hold
    assert held.exercises[0].progression.action is ProgressionAction.MAINTAIN
    cut, changes = apply_cut_progression(held)
    assert cut == held and changes == ()


def test_establish_baseline_and_unloaded_add_reps_are_kept() -> None:
    baseline = [_squat("1", 6, (None, None, None), 60.0)]
    unloaded = [_squat("1", 6, (10, 10, 10), 0.0)]
    for history, action in ((baseline, ProgressionAction.ESTABLISH_BASELINE), (unloaded, ProgressionAction.ADD_REPS)):
        strength = _strength(history)
        assert strength.exercises[0].progression.action is action
        cut, changes = apply_cut_progression(strength)
        assert cut == strength and changes == ()


def test_cut_changes_only_progression_targets() -> None:
    # No regression (best reps rose 10 -> 12 at 60 kg), so the gain plan really increases the load.
    history = [_squat("1", 6, (10, 10, 9), 60.0), _squat("2", 3, (12, 12, 11), 60.0)]
    gain = _plan(history)
    cut = _plan(history, goal=CUT)
    assert gain.strength.exercises[0].progression.action is ProgressionAction.INCREASE_LOAD
    assert cut.strength.exercises[0].progression.action is ProgressionAction.MAINTAIN_LOAD
    assert cut.strength.focus == gain.strength.focus
    assert cut.strength.working_sets == gain.strength.working_sets
    assert [item.sets for item in cut.strength.exercises] == [item.sets for item in gain.strength.exercises]
    assert [
        replace(item, progression=before.progression)
        for item, before in zip(cut.strength.exercises, gain.strength.exercises, strict=True)
    ] == list(gain.strength.exercises)
    assert replace(cut.strength, exercises=()) == replace(gain.strength, exercises=())
    assert replace(cut, strength=gain.strength, goal_mode=None) == gain
    # maintain/gain modes keep the gain progression (D4).
    for mode in (GoalMode.MAINTAIN, GoalMode.GAIN):
        other = _plan(history, goal=TrainingGoal(mode))
        assert other.strength == gain.strength
        assert other.goal_mode is not None and other.goal_mode.progression == ()


# --- weekly sets (AC4) -------------------------------------------------------------------------


def _bench(source_id: str, offset: int, count: int, *, category: str = "BENCH_PRESS") -> NormalizedActivity:
    sets = tuple(strength_set(index, category=category) for index in range(1, count + 1))
    return activity(source_id, f"{_day(offset)}T12:00:00", ActivityType.STRENGTH, strength_sets=sets)


def test_weekly_sets_count_primary_one_and_secondary_half_in_d7_to_d1() -> None:
    activities = [
        _bench("8", 8, 5),  # D-8: outside
        _bench("7", 7, 3),  # D-7: inside
        _bench("1", 1, 4),  # D-1: inside
        _bench("0", 0, 9),  # D: outside (the plan's history ends at D-1)
        _bench("u", 2, 2, category="UNKNOWN"),
        _bench("n", 2, 1, category="NOT_A_RULE"),
        activity("w", f"{_day(2)}T12:00:00", ActivityType.STRENGTH, strength_sets=(strength_set(1, set_type="REST"),)),
    ]
    sets = weekly_muscle_sets(D, activities)
    by_muscle = {item.muscle: item for item in sets.muscles}
    assert (sets.from_date, sets.to_date) == (date(2026, 3, 9), date(2026, 3, 15))
    chest, triceps = by_muscle["chest"], by_muscle["triceps"]
    assert (chest.direct_sets, chest.indirect_sets, chest.fractional_sets, chest.below_threshold) == (7, 0, 7.0, True)
    assert (triceps.direct_sets, triceps.indirect_sets, triceps.fractional_sets) == (0, 7, 3.5)
    assert by_muscle["anterior_deltoid"].fractional_sets == 3.5
    assert (sets.unknown_sets, sets.no_rule_sets, sets.lower_bound) == (2, 1, True)
    assert [item.muscle for item in sets.muscles][:3] == ["quadriceps", "hamstrings", "glutes"]
    assert sets.evidence == ("VOL-04", "VOL-02")


def test_ten_fractional_sets_are_not_below_the_threshold() -> None:
    sets = weekly_muscle_sets(D, [_bench("1", 1, 10)])
    chest = next(item for item in sets.muscles if item.muscle == "chest")
    assert (chest.fractional_sets, chest.below_threshold) == (10.0, False)
    assert sets.lower_bound is False


def test_a_muscle_no_rule_trains_is_not_countable(monkeypatch: pytest.MonkeyPatch) -> None:
    from muscle50.domain.exercise_taxonomy import MuscleGroup

    monkeypatch.setattr(goal_mode, "COUNTABLE_MUSCLES", goal_mode.COUNTABLE_MUSCLES - {MuscleGroup.FOREARMS})
    forearms = next(item for item in weekly_muscle_sets(D, []).muscles if item.muscle == "forearms")
    assert (forearms.countable, forearms.below_threshold, forearms.fractional_sets) == (False, None, 0.0)


# --- InBody rates and flags (AC5) --------------------------------------------------------------


def _rows(*points: tuple[str, float | None, float | None, float | None]) -> tuple[StoredBodyComposition, ...]:
    """(date, weight, smm, bfm) as stored rows."""
    return tuple(
        StoredBodyComposition(index, f"{day}T08:00:00+09:00", weight, smm, bfm, None)
        for index, (day, weight, smm, bfm) in enumerate(points, 1)
    )


def _points(*points: tuple[str, float | None, float | None, float | None]) -> dict[TrendMetric, dict[date, Decimal]]:
    return metric_points(_rows(*points), to_date=D)


def test_weight_rate_is_exact_and_rounded_half_even() -> None:
    change = weight_change(CUT, _points(("2026-02-16", 80.0, None, None), ("2026-03-16", 78.0, None, None)), D, None)
    assert change.status == "known"
    assert (change.from_date, change.to_date, change.days) == (date(2026, 2, 16), D, 28)
    assert change.percent_per_week == Decimal("-0.625")
    assert goal_mode.percent_text(change.percent_per_week) == "-0.62"
    assert change.flags == ("outside_user_target",)
    assert change.evidence_range == goal_mode.EVIDENCE_LOSS_RANGE
    assert change.evidence == ("MAINT-05", "design")


@pytest.mark.parametrize(
    ("latest", "flags"),
    [
        (78.8, ()),  # -1.5 % in 4 weeks = -0.375 %/week: inside 0.3-0.5
        (76.0, ("faster_than_evidence", "outside_user_target")),  # -1.25 %/week
        (78.4, ()),  # exactly -0.5 %/week: the user's band is inclusive
        (79.6, ("outside_user_target",)),  # -0.125 %/week: slower than the user's band
        (80.4, ("outside_user_target", "gaining")),
    ],
)
def test_cut_flags(latest: float, flags: tuple[str, ...]) -> None:
    points = _points(("2026-02-16", 80.0, None, None), ("2026-03-16", latest, None, None))
    assert weight_change(CUT, points, D, None).flags == flags


def test_exactly_one_percent_per_week_is_not_faster_than_the_evidence() -> None:
    points = _points(("2026-02-16", 100.0, None, None), ("2026-03-16", 96.0, None, None))
    change = weight_change(TrainingGoal(GoalMode.CUT), points, D, None)
    assert change.percent_per_week == Decimal("-1")
    assert change.flags == ()  # no user band set, and 1.0 is not over 1.0


def test_maintain_and_gain_show_the_rate_without_alerts() -> None:
    points = _points(("2026-02-16", 80.0, None, None), ("2026-03-16", 76.0, None, None))
    for mode in (GoalMode.MAINTAIN, GoalMode.GAIN):
        change = weight_change(TrainingGoal(mode), points, D, None)
        assert (change.status, change.flags, change.evidence_range) == ("known", (), None)


def test_weight_rate_unknown_cases() -> None:
    one = weight_change(CUT, _points(("2026-03-16", 78.0, None, None)), D, None)
    assert (one.status, one.percent_per_week) == ("unknown", None)
    assert one.reason == "no InBody weight at least 7 days before the latest (2026-03-16)"
    assert (one.latest_measurement_date, one.days_since_latest_measurement) == (D, 0)
    no_weight = weight_change(CUT, _points(("2026-02-16", None, 36.0, None), ("2026-03-16", None, 36.0, None)), D, None)
    assert (no_weight.status, no_weight.reason) == ("unknown", "no InBody weight on or before 2026-03-16")
    unavailable = weight_change(CUT, None, D, "InBody data unavailable: no table")
    assert (unavailable.status, unavailable.reason) == ("unknown", "InBody data unavailable: no table")


def test_short_interval_falls_back_to_an_earlier_point_and_later_points_are_ignored() -> None:
    points = _points(
        ("2026-02-16", 80.0, None, None),
        ("2026-03-12", 79.0, None, None),  # only 4 days before the latest
        ("2026-03-16", 78.0, None, None),
        ("2026-03-20", 60.0, None, None),  # after D
    )
    change = weight_change(CUT, points, D, None)
    assert (change.from_date, change.to_date, change.percent_per_week) == (date(2026, 2, 16), D, Decimal("-0.625"))


def test_a_conflicting_date_is_skipped() -> None:
    rows = (
        *_rows(("2026-02-16", 80.0, None, None), ("2026-03-16", 78.0, None, None)),
        StoredBodyComposition(9, "2026-03-16T09:00:00+09:00", 77.0, None, None, None),
    )
    change = weight_change(CUT, metric_points(rows, to_date=D), D, None)
    assert change.status == "unknown"  # 2026-03-16 conflicts; 2026-02-16 alone has no earlier point


def test_smm_floor_statuses() -> None:
    floor = replace(CUT, min_skeletal_muscle_mass_kg=Decimal("36"))
    assert smm_floor(floor, _points(("2026-03-16", None, 35.9, None))).status == "below"
    at = smm_floor(floor, _points(("2026-03-16", None, 36.0, None)))
    assert (at.status, at.measurement_date, at.floor_kg) == ("at_or_above", D, Decimal("36"))
    assert smm_floor(floor, _points(("2026-03-16", 78.0, None, None))).status == "unknown"
    assert smm_floor(floor, None).status == "unknown"
    assert smm_floor(CUT, _points(("2026-03-16", None, 35.9, None))).status == "not_set"


def test_goal_progress() -> None:
    goal = replace(CUT, target_body_fat_percent=Decimal("18"), target_date=date(2026, 6, 8))  # 12 weeks
    points = _points(("2026-03-16", 80.0, None, 20.0))  # fat-free 60 -> target 60 / 0.82
    progress = goal_progress(goal, points, D, Decimal("-0.5"))
    assert progress.status == "known"
    expected = (Decimal(60) / (1 - Decimal(18) / 100) / Decimal("80.0") - 1) / Decimal(12) * 100
    assert progress.required_percent_per_week == expected
    assert goal_mode.percent_text(progress.required_percent_per_week) == "-0.71"
    assert (progress.actual_percent_per_week, progress.assumption) == (Decimal("-0.5"), "fat_free_mass_constant")
    reached = goal_progress(goal, _points(("2026-03-16", 80.0, None, 12.0)), D, None)
    assert (reached.status, reached.measurement_date) == ("reached", D)
    passed = goal_progress(replace(goal, target_date=D), points, D, None)
    assert passed.status == "deadline_passed"
    no_fat = goal_progress(goal, _points(("2026-03-16", 80.0, 36.0, None)), D, None)
    assert (no_fat.status, no_fat.reason) == ("unknown", "no InBody date with both weight and body fat mass")
    assert goal_progress(CUT, points, D, None).status == "not_set"
    weight_goal = replace(CUT, target_weight_kg=Decimal("76"), target_date=date(2026, 6, 8))
    by_weight = goal_progress(weight_goal, points, D, None)
    assert (by_weight.status, by_weight.assumption) == ("known", None)
    assert by_weight.required_percent_per_week == (Decimal(76) / Decimal("80.0") - 1) / Decimal(12) * 100


def test_cut_nutrition_reference() -> None:
    rows = _rows(("2026-02-16", 80.0, None, 16.0), ("2026-03-16", 78.0, None, 15.0))
    reference = cut_nutrition_reference(rows, D)
    assert (reference.status, reference.protein_min_g, reference.protein_max_g, reference.measurement_date) == (
        "known",
        Decimal("145"),
        Decimal("195"),
        D,
    )
    missing = cut_nutrition_reference(_rows(("2026-03-16", 78.0, None, None)), D)
    assert (missing.status, missing.protein_min_g) == ("unknown", None)
    assert cut_nutrition_reference(None, D, "no table").reason == "no table"
    bad = (StoredBodyComposition(1, "not-a-time", 78.0, None, 15.0, None),)
    assert cut_nutrition_reference(bad, D).reason == "a stored InBody measurement cannot be read"


# --- run and legs (AC6) ------------------------------------------------------------------------


def _report_pairs(*activities: NormalizedActivity) -> list[tuple[str | None, int | None, bool | None, str | None]]:
    return [
        (pair.order, pair.gap_minutes, pair.under_threshold, pair.advice)
        for pair in run_legs_pairs(D, list(activities)).pairs
    ]


def test_a_run_one_hour_before_legs_is_flagged_with_lift_first() -> None:
    report = run_legs_pairs(
        D,
        [
            run("r", "2026-03-12T07:00:00", "2026-03-11T22:00:00+00:00"),
            legs("l", "2026-03-12T08:00:00", "2026-03-11T23:00:00+00:00"),
        ],
    )
    (pair,) = report.pairs
    assert (pair.run_local_time, pair.strength_local_time, pair.gap_minutes) == ("07:00", "08:00", 60)
    assert (pair.order, pair.under_threshold, pair.advice, pair.advice_evidence) == (
        "run_first",
        True,
        "lift_first",
        ("CONC-05",),
    )
    assert (report.from_date, report.to_date, report.evidence) == (
        date(2026, 3, 9),
        D,
        ("CONC-03", "CONC-04", "design"),
    )


def test_legs_before_the_run_is_flagged_without_advice() -> None:
    assert _report_pairs(
        legs("l", "2026-03-12T08:00:00", "2026-03-11T23:00:00+00:00"),
        run("r", "2026-03-12T09:30:00", "2026-03-12T00:30:00+00:00"),
    ) == [("legs_first", 90, True, None)]


@pytest.mark.parametrize(
    ("utc", "under"),
    [("2026-03-12T01:00:00+00:00", False), ("2026-03-12T02:00:00+00:00", False), ("2026-03-12T00:59:00+00:00", True)],
)
def test_three_hours_is_not_under_the_threshold(utc: str, under: bool) -> None:
    pairs = _report_pairs(
        run("r", "2026-03-12T07:00:00", "2026-03-11T22:00:00+00:00"), legs("l", "2026-03-12T10:00:00", utc)
    )
    assert pairs[0][2] is under


def test_fewer_than_three_leg_sets_is_not_a_legs_session_and_other_days_do_not_pair() -> None:
    assert (
        _report_pairs(
            run("r", "2026-03-12T07:00:00", "2026-03-11T22:00:00+00:00"),
            legs("l", "2026-03-12T08:00:00", "2026-03-11T23:00:00+00:00", sets=2),
            legs("x", "2026-03-13T08:00:00", "2026-03-12T23:00:00+00:00"),
            legs("b", "2026-03-12T08:00:00", "2026-03-11T23:00:00+00:00", category="BENCH_PRESS"),
            legs("o", "2026-03-08T08:00:00", "2026-03-07T23:00:00+00:00"),  # D-8
        )
        == []
    )


@pytest.mark.parametrize("utc", [None, "2026-03-11T23:00:00", "garbage"])
def test_a_start_without_zone_gives_gap_unknown(utc: str | None) -> None:
    assert _report_pairs(
        run("r", "2026-03-12T07:00:00", "2026-03-11T22:00:00+00:00"), legs("l", "2026-03-12T08:00:00", utc)
    ) == [("run_first", None, None, None)]


# --- nights under 7 h (AC7) --------------------------------------------------------------------


def test_short_nights_exactly_seven_hours_is_not_short_and_missing_is_counted_apart() -> None:
    rows = [
        recovery(_day(0), sleep_seconds=7 * 3600),
        recovery(_day(1), sleep_seconds=7 * 3600 - 1),
        recovery(_day(2), sleep_seconds=None),
        recovery(_day(3), sleep_seconds=4 * 3600),
        recovery(_day(7), sleep_seconds=3600),  # outside D-6..D
    ]
    report = short_sleep_nights(D, rows, DEFAULT_SLEEP_SETTING)
    assert (report.from_date, report.to_date) == (date(2026, 3, 10), D)
    assert (report.nights_under, report.nights_with_data, report.nights_without_data) == (2, 3, 4)
    assert report.rules.thresholds == DEFAULT_SLEEP_THRESHOLDS
    assert report.evidence == ("SLEEP-05",)


# --- every item carries evidence (AC8) ---------------------------------------------------------


def test_every_report_item_carries_evidence() -> None:
    history = [_squat("1", 6, (12, 12, 12), 60.0)]
    rows = _rows(("2026-02-16", 80.0, 36.0, 16.0), ("2026-03-16", 78.0, 35.9, 15.0))
    report = build_training_recommendation(
        D, history, [], goal=replace(CUT, min_skeletal_muscle_mass_kg=Decimal("35")), body_composition=rows
    ).goal_mode
    assert isinstance(report, GoalModeReport)
    items: list[Any] = [
        *report.progression,
        report.weekly_sets,
        report.weight_change,
        report.smm_floor,
        report.goal_progress,
        report.run_legs,
        report.sleep,
    ]
    assert report.progression
    known = set(re.findall(r"^\| ([A-Z]+-[0-9]{2}) \|", EVIDENCE_DOC.read_text(encoding="utf-8"), re.MULTILINE))
    assert {"MAINT-02", "VOL-04", "SLEEP-05"} <= known
    for item in items:
        assert item.evidence, item
        assert all(tag == "design" or tag in known for tag in item.evidence), item
    assert set(report.run_legs.pairs) == set()  # no run in this history
    assert goal_mode.RUN_LEGS_ADVICE_EVIDENCE[0] in known


def test_no_goal_means_no_report() -> None:
    assert build_training_recommendation(D, [_squat("1", 6, (12, 12, 12), 60.0)], []).goal_mode is None
