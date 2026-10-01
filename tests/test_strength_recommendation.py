from __future__ import annotations

import dataclasses
import json
from collections.abc import Sequence
from datetime import date, timedelta

from analytics_builders import activity, load_metrics, recovery, strength_set

from muscle50.domain.activity import ActivityType, NormalizedActivity, StrengthSet
from muscle50.domain.analytics import LabelOriginCounts
from muscle50.domain.exercise_taxonomy import MuscleGroup
from muscle50.domain.recovery import DailyRecovery
from muscle50.domain.recovery_assessment import AdjustmentLevel, assess_recovery
from muscle50.domain.strength_recommendation import (
    REPS_BELOW_TOP_AFTER_LOAD_INCREASE,
    ExerciseLabel,
    ExerciseOccurrence,
    PerformedSet,
    ProgressionAction,
    StrengthRecommendation,
    SwimOverlap,
    build_strength_recommendation,
    kg_text,
    plan_progression,
    summarize_occurrence,
)
from muscle50.domain.training_goals import DEFAULT_TRAINING_GOALS, RepRange

AS_OF = date(2026, 3, 20)
COMPOUND = RepRange(5, 12)
BENCH = ExerciseLabel("BENCH_PRESS", None)


def _occurrence(day: str, *sets: tuple[int | None, float | None], source_id: str = "1") -> ExerciseOccurrence:
    return ExerciseOccurrence(
        source_id,
        date.fromisoformat(day),
        tuple(PerformedSet(index, reps, weight) for index, (reps, weight) in enumerate(sets)),
        LabelOriginCounts(confirmed=len(sets), auto_detected=0, unspecified=0),
    )


def _sets(category: str, name: str | None, *pairs: tuple[int, float], start: int = 0) -> list[StrengthSet]:
    return [
        strength_set(start + index, category=category, name=name, reps=reps, weight_kg=weight, probability=100.0)
        for index, (reps, weight) in enumerate(pairs)
    ]


def _strength(source_id: str, day: date, sets: list[StrengthSet], hour: int = 12) -> NormalizedActivity:
    return activity(
        source_id,
        f"{day.isoformat()}T{hour:02d}:00:00",
        ActivityType.STRENGTH,
        strength_sets=tuple(dataclasses.replace(item, sequence=index) for index, item in enumerate(sets)),
    )


def _days_ago(days: int) -> date:
    return AS_OF - timedelta(days=days)


def _push_pull_legs_history() -> list[NormalizedActivity]:
    """Push trained 2 and 5 days ago, pull 3 and 6 days ago, legs 10 days ago."""
    return [
        _strength(
            "p1",
            _days_ago(5),
            _sets("BENCH_PRESS", None, (10, 50.0), (9, 50.0), (8, 50.0))
            + _sets("TRICEPS_EXTENSION", None, (15, 20.0), (14, 20.0), start=3),
        ),
        _strength(
            "p2",
            _days_ago(2),
            _sets("BENCH_PRESS", None, (10, 50.0), (10, 50.0), (9, 50.0))
            + _sets("SHOULDER_PRESS", None, (10, 20.0), (9, 20.0), start=3)
            + _sets("TRICEPS_EXTENSION", None, (15, 20.0), start=5),
        ),
        _strength(
            "u1",
            _days_ago(6),
            _sets("PULL_UP", "LAT_PULLDOWN", (10, 40.0), (10, 40.0), (9, 40.0))
            + _sets("ROW", None, (10, 40.0), (10, 40.0), start=3)
            + _sets("CURL", None, (12, 10.0), (12, 10.0), start=5),
        ),
        _strength(
            "u2",
            _days_ago(3),
            _sets("PULL_UP", "LAT_PULLDOWN", (11, 40.0), (10, 40.0), (10, 40.0))
            + _sets("ROW", None, (11, 40.0), (10, 40.0), start=3)
            + _sets("CURL", None, (13, 10.0), start=5),
        ),
        _strength(
            "l1",
            _days_ago(10),
            _sets("SQUAT", None, (8, 60.0), (8, 60.0), (7, 60.0))
            + _sets("LUNGE", None, (10, 20.0), (10, 20.0), start=3)
            + _sets("LEG_CURL", None, (12, 30.0), (12, 30.0), start=5),
        ),
    ]


def _recommend(
    activities: list[NormalizedActivity],
    *,
    recoveries: Sequence[DailyRecovery] | None = None,
    overlaps: Sequence[SwimOverlap] = (),
    avoid_muscles: Sequence[MuscleGroup] = (),
) -> StrengthRecommendation:
    rows = (recovery(AS_OF.isoformat()),) if recoveries is None else recoveries
    return build_strength_recommendation(
        AS_OF, activities, assess_recovery(AS_OF, rows), overlaps, DEFAULT_TRAINING_GOALS, avoid_muscles
    )


# --- progression -----------------------------------------------------------------------


def test_rep_progression_at_same_load() -> None:
    target = plan_progression(
        BENCH, [_occurrence("2026-03-15", (8, 50.0), (8, 50.0), (7, 50.0))], COMPOUND, AdjustmentLevel.NORMAL
    )

    assert target.action is ProgressionAction.ADD_REPS
    assert target.load_kg == 50.0
    assert target.target_reps == 9


def test_load_increase_after_two_work_sets_reach_the_top_of_the_range() -> None:
    target = plan_progression(
        BENCH, [_occurrence("2026-03-15", (12, 50.0), (12, 50.0), (11, 50.0))], COMPOUND, AdjustmentLevel.NORMAL
    )

    assert target.action is ProgressionAction.INCREASE_LOAD
    assert target.load_kg == 52.5
    assert target.target_reps == max(COMPOUND.minimum, COMPOUND.maximum - REPS_BELOW_TOP_AFTER_LOAD_INCREASE)


def test_one_top_set_is_not_enough_for_a_load_increase() -> None:
    target = plan_progression(
        BENCH, [_occurrence("2026-03-15", (12, 50.0), (9, 50.0))], COMPOUND, AdjustmentLevel.NORMAL
    )

    assert target.action is ProgressionAction.ADD_REPS
    assert target.load_kg == 50.0
    assert target.target_reps == 12


def test_real_pyramid_shape_does_not_increase_load() -> None:
    # 2026-09-28 BENCH_PRESS/-: warm-up, pyramid to a heavy set of 6, then a back-off set.
    occurrence = _occurrence("2026-09-28", (18, 20.0), (12, 40.0), (10, 50.0), (6, 60.0), (20, 40.0))

    summary = summarize_occurrence(occurrence, COMPOUND)
    target = plan_progression(BENCH, [occurrence], COMPOUND, AdjustmentLevel.NORMAL)

    assert summary.work_load_kg == 60.0
    assert summary.work_set_reps == (6,)
    assert target.action is ProgressionAction.ADD_REPS
    assert (target.load_kg, target.target_reps) == (60.0, 7)


def test_heaviest_set_below_the_rep_range_is_not_the_work_load() -> None:
    occurrence = _occurrence("2026-07-01", (12, 40.0), (10, 60.0), (6, 80.0), (3, 100.0), (6, 80.0))

    summary = summarize_occurrence(occurrence, COMPOUND)

    assert summary.work_load_kg == 80.0
    assert summary.work_set_reps == (6, 6)
    assert not summary.below_range


def test_hold_recovery_never_forces_a_load_increase() -> None:
    occurrence = _occurrence("2026-03-15", (12, 50.0), (12, 50.0), (12, 50.0))

    for level in (AdjustmentLevel.HOLD, AdjustmentLevel.REDUCE):
        target = plan_progression(BENCH, [occurrence], COMPOUND, level)
        assert target.action is ProgressionAction.MAINTAIN
        assert (target.load_kg, target.target_reps) == (50.0, 12)


def test_reps_dropping_at_the_same_load_holds_progression() -> None:
    occurrences = [
        _occurrence("2026-03-10", (10, 50.0), (10, 50.0)),
        _occurrence("2026-03-15", (7, 50.0), (6, 50.0)),
    ]

    target = plan_progression(BENCH, occurrences, COMPOUND, AdjustmentLevel.NORMAL)

    assert target.regression
    assert target.action is ProgressionAction.MAINTAIN
    assert (target.load_kg, target.target_reps) == (50.0, 7)


def test_a_lower_load_alone_is_not_a_regression() -> None:
    occurrences = [_occurrence("2026-03-10", (6, 60.0)), _occurrence("2026-03-15", (10, 30.0), (9, 30.0))]

    target = plan_progression(BENCH, occurrences, COMPOUND, AdjustmentLevel.NORMAL)

    assert not target.regression
    assert target.action is ProgressionAction.ADD_REPS
    assert target.load_confidence == "low"  # 30-60 kg under one label: equipment may differ


def test_zero_and_sentinel_weights_give_rep_only_targets() -> None:
    occurrence = _occurrence("2026-03-15", (12, 0.0), (10, -0.0), (11, None), (9, -0.001))

    target = plan_progression(ExerciseLabel("PULL_UP", None), [occurrence], COMPOUND, AdjustmentLevel.NORMAL)

    assert target.load_kg is None
    assert target.load_confidence == "none"
    assert target.target_reps == 12
    assert kg_text(-0.0) == "0 kg"


def test_missing_reps_only_history_establishes_a_baseline() -> None:
    target = plan_progression(
        BENCH, [_occurrence("2026-03-15", (None, 50.0), (0, 50.0))], COMPOUND, AdjustmentLevel.NORMAL
    )

    assert target.action is ProgressionAction.ESTABLISH_BASELINE
    assert target.load_kg is None


# --- selection -------------------------------------------------------------------------


def test_familiar_exercise_is_preferred_over_an_occasional_variant() -> None:
    history = _push_pull_legs_history()
    history.append(_strength("p0", _days_ago(8), _sets("BENCH_PRESS", "DUMBBELL_BENCH_PRESS", (10, 24.0), (10, 24.0))))

    plan = _recommend(
        history,
        avoid_muscles=(
            MuscleGroup.QUADRICEPS,
            MuscleGroup.HAMSTRINGS,
            MuscleGroup.GLUTES,
            MuscleGroup.LATS,
            MuscleGroup.UPPER_BACK,
            MuscleGroup.BICEPS,
            MuscleGroup.POSTERIOR_DELTOID,
            MuscleGroup.FOREARMS,
        ),
    )

    assert plan.focus == "push"
    key = plan.exercises[0]
    assert (key.category, key.exercise_name) == ("BENCH_PRESS", None)
    assert plan.alternative is None


def test_distinct_garmin_variants_are_never_combined() -> None:
    history = [
        _strength(
            "a",
            _days_ago(4),
            _sets("BENCH_PRESS", None, (8, 50.0), (8, 50.0))
            + _sets("BENCH_PRESS", "DUMBBELL_BENCH_PRESS", (12, 100.0), (12, 100.0), start=2),
        ),
        _strength("b", _days_ago(9), _sets("BENCH_PRESS", None, (8, 50.0), (7, 50.0))),
    ]

    plan = _recommend(history)

    labels = [item.label for item in plan.exercises]
    assert labels[:2] == ["BENCH_PRESS/-", "BENCH_PRESS/DUMBBELL_BENCH_PRESS"]
    bench, dumbbell = plan.exercises[0], plan.exercises[1]
    assert (bench.progression.load_kg, bench.progression.target_reps) == (50.0, 9)
    assert dumbbell.progression.action is ProgressionAction.INCREASE_LOAD
    assert dumbbell.progression.load_kg == 102.5


def test_genuinely_neglected_legs_rise_in_priority() -> None:
    plan = _recommend(_push_pull_legs_history())

    # Legs: no strength session for 10 days, below the 1/week goal floor.
    assert plan.focus == "legs"
    assert [item.label for item in plan.exercises] == ["SQUAT/-", "LUNGE/-", "LEG_CURL/-"]
    assert plan.reasons[0].startswith("legs: no strength session for 7+ days")
    legs = next(item for item in plan.regions if item.region == "legs")
    assert legs.neglected


def _squat(source_id: str, days: int) -> NormalizedActivity:
    return _strength(source_id, _days_ago(days), _sets("SQUAT", None, (8, 60.0), (8, 60.0), (8, 60.0)))


def _bench(source_id: str, days: int) -> NormalizedActivity:
    return _strength(source_id, _days_ago(days), _sets("BENCH_PRESS", None, (10, 50.0), (10, 50.0), (10, 50.0)))


def test_region_below_a_weekly_count_is_not_chosen_over_a_more_due_region() -> None:
    # Legs: one session 3 days ago, usually weekly (due 3/7). Push: trained every 2 days,
    # last 3 days ago (due 3/2). A weekly count says legs is "below 2/week"; push is more due.
    history = [_squat("l", 3), _squat("l0", 10)] + [_bench(f"p{days}", days) for days in (3, 5, 7, 9, 11, 13, 15)]

    plan = _recommend(history)

    assert plan.focus == "push"
    assert plan.reasons[0].startswith("push: more due against its own usual interval than legs")


def test_region_trained_yesterday_is_not_reselected_for_being_under_target() -> None:
    # Legs trained lightly yesterday (one session in 7 days); push last trained 3 days ago.
    history = [_squat("l", 1), _bench("p", 3), _bench("p2", 6)]

    plan = _recommend(history)

    legs = next(item for item in plan.regions if item.region == "legs")
    assert legs.eligible  # 3 sets yesterday is light, not a hard exclusion
    assert plan.focus == "push"


def test_swimming_never_counts_as_lower_body_training() -> None:
    swims = [
        activity(f"s{days}", f"{_days_ago(days).isoformat()}T06:00:00", ActivityType.SWIMMING, distance_meters=1500.0)
        for days in (1, 2, 4)
    ]
    history = [_squat("l", 9), _bench("p", 2), _bench("p2", 4), *swims]

    plan = _recommend(history)

    legs = next(item for item in plan.regions if item.region == "legs")
    assert legs.neglected and legs.days_since_last_trained == 9
    assert plan.focus == "legs"


def test_reduce_recovery_prefers_the_most_rested_region() -> None:
    # Push is most due by its own interval but was trained 2 days ago; legs 4 days ago.
    history = [_squat("l", 4), _squat("l2", 11)] + [_bench(f"p{days}", days) for days in range(2, 28, 2)]
    poor = (recovery(AS_OF.isoformat(), training_readiness_level="POOR"),)

    assert _recommend(history).focus == "push"
    plan = _recommend(history, recoveries=poor)
    assert plan.focus == "legs"
    assert "recovery reduce: push was trained in the last 2 days" in plan.reasons[0]


def test_focus_selection_reports_muscle_level_detail() -> None:
    plan = _recommend(_push_pull_legs_history())

    pull = next(item for item in plan.regions if item.region == "pull")
    lats = next(item for item in pull.muscle_detail if item.muscle == "lats")
    assert lats.sets_last_7_days == 6
    assert lats.last_trained_date == _days_ago(3)
    assert pull.personal_interval_days == 7.0  # 2 sessions in 28 days -> capped at weekly


def test_region_trained_heavily_yesterday_is_rested() -> None:
    history = _push_pull_legs_history()
    history.append(
        _strength(
            "l2", _days_ago(1), _sets("SQUAT", None, (8, 60.0), (8, 60.0), (8, 60.0), (8, 60.0), (8, 60.0), (8, 60.0))
        )
    )

    plan = _recommend(history)

    legs = next(item for item in plan.regions if item.region == "legs")
    assert not legs.eligible
    assert plan.focus != "legs"


def test_avoided_muscle_is_left_out() -> None:
    plan = _recommend(_push_pull_legs_history(), avoid_muscles=(MuscleGroup.HAMSTRINGS,))

    assert plan.focus == "legs"
    assert "LEG_CURL/-" not in [item.label for item in plan.exercises]
    assert plan.avoided_muscles == ("hamstrings",)


def test_stagnation_offers_one_familiar_alternative() -> None:
    history = [
        _strength(
            f"s{index}",
            _days_ago(days),
            _sets("BENCH_PRESS", None, (8, 50.0), (8, 50.0))
            + _sets("BENCH_PRESS", "DUMBBELL_BENCH_PRESS", (10, 20.0), start=2),
        )
        for index, days in enumerate((10, 7, 4))
    ]
    # Done once: too occasional for the plan, but a familiar same-pattern variation.
    history.append(_strength("once", _days_ago(12), _sets("PUSH_UP", None, (15, 0.0))))

    plan = _recommend(history)

    assert plan.exercises[0].progression.stagnant
    assert plan.alternative is not None
    assert plan.alternative.replaces_label == "BENCH_PRESS/-"
    assert plan.alternative.label == "PUSH_UP/-"
    assert plan.alternative.label not in {item.label for item in plan.exercises}


def test_poor_recovery_reduces_sets_and_holds_progression() -> None:
    plan = _recommend(
        _push_pull_legs_history(),
        recoveries=(recovery(AS_OF.isoformat(), training_readiness_level="POOR"),),
    )

    assert plan.adjustment_level == "reduce"
    assert all(item.sets == 2 for item in plan.exercises)
    assert all(item.progression.action is not ProgressionAction.INCREASE_LOAD for item in plan.exercises)
    assert plan.adjustments[0].startswith("recovery reduce")


def test_missing_recovery_is_not_poor_recovery() -> None:
    plan = _recommend(_push_pull_legs_history(), recoveries=())

    assert plan.adjustment_level == "normal"
    assert all(item.sets == 3 for item in plan.exercises)
    assert "missing is not poor" in plan.adjustments[0]


def test_hard_swim_overlap_deprioritises_upper_body_and_overhead_pressing() -> None:
    history = _push_pull_legs_history()
    # A light leg session yesterday makes push/pull the natural pick on a calm day.
    history.append(_strength("l2", _days_ago(1), _sets("SQUAT", None, (8, 60.0), (8, 60.0), (8, 60.0))))
    overlap = SwimOverlap("swim", _days_ago(1), False, 1500.0, True, 0.0, ("HR zone 5 300 s >= 120 s",))

    calm = _recommend(history)
    hard = _recommend(history, overlaps=(overlap,))

    assert calm.focus in ("push", "pull")
    pushed = next(item for item in hard.regions if item.region == "push")
    assert pushed.swim_demoted
    assert hard.focus == "legs"
    assert any("swim yesterday" in text for text in hard.adjustments)


def test_hard_swim_removes_overhead_press_and_trims_lat_sets() -> None:
    history = [
        _strength(
            "p",
            _days_ago(3),
            _sets("SHOULDER_PRESS", None, (10, 20.0), (10, 20.0)) + _sets("BENCH_PRESS", None, (10, 50.0), start=2),
        ),
        _strength("q", _days_ago(5), _sets("SHOULDER_PRESS", None, (10, 20.0), (10, 20.0))),
    ]
    overlap = SwimOverlap("swim", AS_OF, True, 1000.0, False, 250.0, ("butterfly 250 m",))

    plan = _recommend(history, overlaps=(overlap,))

    assert plan.exercises[0].label == "BENCH_PRESS/-"
    assert all(item.movement_pattern != "vertical_push" for item in plan.exercises)
    assert any("not used as key exercise" in text for text in plan.adjustments)


def test_unknown_sets_produce_a_notice_and_are_never_recommended() -> None:
    history = _push_pull_legs_history()
    history.append(
        _strength(
            "unk",
            _days_ago(4),
            [
                strength_set(0, category="UNKNOWN", reps=10, weight_kg=40.0),
                strength_set(1, category=None, reps=8, weight_kg=40.0),
            ]
            + _sets("BENCH_PRESS", None, (10, 50.0), start=2),
        )
    )

    plan = _recommend(history)

    assert plan.exercises  # still usable
    assert all("UNKNOWN" not in item.label for item in plan.exercises)
    notice = next(item for item in plan.unknown_notices if item.source_activity_id == "unk")
    assert notice.unknown_set_count == 2
    assert notice.set_sequences == (0, 1)
    assert notice.local_date == _days_ago(4)
    assert "Garmin Connect" in notice.action and "muscle50 garmin refresh unk" in notice.action
    assert plan.unknown_active_sets_last_7_days == 2


def test_same_day_strength_is_not_history() -> None:
    history = _push_pull_legs_history()
    history.append(_strength("today", AS_OF, _sets("SQUAT", None, *([(8, 60.0)] * 10)), hour=7))

    plan = _recommend(history)

    assert plan.focus == "legs"
    squat = plan.exercises[0]
    assert squat.sessions_last_28_days == 1
    assert squat.last_performed == _days_ago(10)


def test_recommendation_is_deterministic_and_order_independent() -> None:
    history = _push_pull_legs_history()

    first = _recommend(history)
    second = _recommend(list(reversed(history)))

    assert json.dumps(dataclasses.asdict(first), default=str) == json.dumps(dataclasses.asdict(second), default=str)


def test_no_history_gives_no_exercises_without_crashing() -> None:
    plan = _recommend([activity("run", f"{_days_ago(1).isoformat()}T07:00:00", metrics=load_metrics())])

    assert plan.focus is None
    assert plan.exercises == ()
    assert "no mapped strength history" in plan.reasons[-1]
