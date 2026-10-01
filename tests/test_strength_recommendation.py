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
    StrengthFocus,
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
    focus: StrengthFocus | None = None,
) -> StrengthRecommendation:
    rows = (recovery(AS_OF.isoformat()),) if recoveries is None else recoveries
    return build_strength_recommendation(
        AS_OF, activities, assess_recovery(AS_OF, rows), overlaps, DEFAULT_TRAINING_GOALS, avoid_muscles, focus
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


# --- user-requested focus ----------------------------------------------------------------

_LEG_MUSCLES = {"quadriceps", "hamstrings", "glutes"}
_SHOULDER_MUSCLES = {"anterior_deltoid", "lateral_deltoid", "posterior_deltoid"}


def _calm_upper_body_history() -> list[NormalizedActivity]:
    """A light leg session yesterday makes push/pull the automatic choice."""
    history = _push_pull_legs_history()
    history.append(_strength("l2", _days_ago(1), _sets("SQUAT", None, (8, 60.0), (8, 60.0), (8, 60.0))))
    return history


def _shoulder_history() -> list[NormalizedActivity]:
    """Shoulder-primary work next to exercises that list a deltoid only as a secondary muscle."""
    return [
        _strength(
            "s1",
            _days_ago(8),
            _sets("SHOULDER_PRESS", None, (10, 20.0), (10, 20.0), (9, 20.0))
            + _sets("LATERAL_RAISE", None, (15, 8.0), (14, 8.0), start=3)
            + _sets("BENCH_PRESS", None, (10, 50.0), (10, 50.0), (10, 50.0), start=5),
        ),
        _strength(
            "s2",
            _days_ago(4),
            _sets("SHOULDER_PRESS", None, (11, 20.0), (10, 20.0), (10, 20.0))
            + _sets("LATERAL_RAISE", None, (15, 8.0), (15, 8.0), start=3)
            + _sets("SHRUG", "UPRIGHT_ROW", (12, 20.0), (12, 20.0), start=5)
            + _sets("ROW", None, (10, 40.0), (10, 40.0), (10, 40.0), start=7),
        ),
    ]


def test_without_a_requested_focus_the_automatic_choice_is_unchanged() -> None:
    history = _push_pull_legs_history()

    implicit = _recommend(history)
    explicit = _recommend(history, focus=None)

    assert implicit == explicit
    assert implicit.focus == "legs"
    assert implicit.focus_source == "auto"
    assert implicit.auto_focus == implicit.focus


def test_requested_legs_overrides_an_automatic_upper_body_focus() -> None:
    history = _calm_upper_body_history()
    automatic = _recommend(history)

    plan = _recommend(history, focus=StrengthFocus.LEGS)

    assert automatic.focus in ("push", "pull")
    assert plan.focus == "legs"
    assert plan.focus_source == "user"
    assert plan.auto_focus == automatic.focus
    assert plan.focus_muscles == ("quadriceps", "hamstrings", "glutes")
    assert plan.exercises
    assert {item.primary_muscle for item in plan.exercises} <= _LEG_MUSCLES
    assert plan.reasons[0].startswith(f"legs: user-selected focus (automatic selection would be {automatic.focus})")
    # The region ranking is still reported as evidence, unchanged.
    assert plan.regions == automatic.regions


def test_requested_shoulders_uses_only_shoulder_primary_exercises() -> None:
    plan = _recommend(_shoulder_history(), focus=StrengthFocus.SHOULDERS)

    assert plan.focus == "shoulders"
    assert plan.focus_source == "user"
    assert plan.auto_focus != "shoulders"  # never an automatic region
    assert plan.focus_muscles == ("anterior_deltoid", "lateral_deltoid", "posterior_deltoid")
    assert [item.label for item in plan.exercises] == ["SHOULDER_PRESS/-", "LATERAL_RAISE/-"]
    assert {item.primary_muscle for item in plan.exercises} <= _SHOULDER_MUSCLES
    # BENCH_PRESS and ROW only list a deltoid as a secondary muscle, so they never qualify.
    assert all(item.category not in ("BENCH_PRESS", "ROW") for item in plan.exercises)
    assert "anterior_deltoid 3 primary sets in 7 d" in plan.reasons[0]
    # No v1 rule has posterior deltoid as primary: it is said, not shown as neglected.
    assert "posterior_deltoid: no v1 taxonomy rule uses it as a primary muscle" in plan.reasons[0]
    # Two familiar exercises cannot fill the time goal; that is reported, never padded.
    assert plan.estimated_minutes == 23
    coverage = {item.muscle: item for item in plan.focus_coverage}
    assert coverage["anterior_deltoid"].exercises == ("SHOULDER_PRESS/-",)
    assert coverage["lateral_deltoid"].exercises == ("LATERAL_RAISE/-",)
    assert coverage["posterior_deltoid"].status == "no_taxonomy_rule"
    shortfall = next(text for text in plan.reasons if "against the 40-minute goal" in text)
    assert shortfall.startswith("history is limited: shoulders session is about 23 min with 2 exercises")
    assert "posterior_deltoid missing" in shortfall
    # A second lateral-deltoid exercise with one session is considered but not used as filler.
    assert "SHRUG/UPRIGHT_ROW considered, not added: lateral_deltoid already covered and only 1 session" in shortfall
    assert shortfall.endswith("nothing was added to fill the time")


def test_a_full_requested_session_is_not_reported_as_limited_history() -> None:
    history = _calm_upper_body_history()
    for source_id, days in (("u3", 9), ("u4", 13)):
        history.append(_strength(source_id, _days_ago(days), _sets("PULL_UP", None, (8, 0.0), (8, 0.0), (7, 0.0))))

    plan = _recommend(history, focus=StrengthFocus.PULL)

    assert [item.role.value for item in plan.exercises] == ["key", "accessory", "accessory", "isolation"]
    assert plan.estimated_minutes == 41
    assert not any(text.startswith("history is limited") for text in plan.reasons)
    assert not any("against the 40-minute goal" in text for text in plan.reasons)


def test_a_short_session_reports_why_instead_of_padding() -> None:
    plan = _recommend(_calm_upper_body_history(), focus=StrengthFocus.PULL)

    assert len(plan.exercises) == 3
    shortfall = next(text for text in plan.reasons if "against the 40-minute goal" in text)
    assert "pull session is about 32 min with 3 exercises" in shortfall
    assert "no other familiar pull exercise in the last 28 days" in shortfall


def test_hard_swim_keeps_requested_shoulders_but_drops_overhead_press_and_trims_sets() -> None:
    overlap = SwimOverlap("swim", _days_ago(1), False, 1500.0, True, 0.0, ("HR zone 5 300 s >= 120 s",))

    plan = _recommend(_shoulder_history(), overlaps=(overlap,), focus=StrengthFocus.SHOULDERS)

    assert plan.focus == "shoulders"
    assert plan.exercises
    assert all(item.movement_pattern != "vertical_push" for item in plan.exercises)
    assert {item.primary_muscle for item in plan.exercises} <= _SHOULDER_MUSCLES
    assert any("SHOULDER_PRESS/- not used as key exercise" in text for text in plan.adjustments)
    assert all(item.sets == 2 for item in plan.exercises)
    assert all(any("hard swim overlap" in text for text in item.adjustments) for item in plan.exercises)
    assert any("swim yesterday" in text for text in plan.adjustments)
    assert any(
        "anterior_deltoid missing (its only familiar exercises are overhead presses, excluded after a hard swim)"
        in text
        for text in plan.reasons
    )
    coverage = {item.muscle: item.status for item in plan.focus_coverage}
    assert coverage["anterior_deltoid"] == "excluded_after_hard_swim"


def test_poor_recovery_keeps_the_requested_focus_and_holds_progression() -> None:
    history = _push_pull_legs_history()
    # Two work sets at the top of the compound range: normally a load increase.
    history.append(_strength("l2", _days_ago(4), _sets("SQUAT", None, (12, 60.0), (12, 60.0), (12, 60.0))))
    poor = (recovery(AS_OF.isoformat(), training_readiness_level="POOR"),)

    normal = _recommend(history, focus=StrengthFocus.LEGS)
    reduced = _recommend(history, recoveries=poor, focus=StrengthFocus.LEGS)

    squat = next(item for item in normal.exercises if item.category == "SQUAT")
    assert squat.progression.action is ProgressionAction.INCREASE_LOAD
    assert reduced.focus == "legs"
    assert reduced.focus_source == "user"
    assert reduced.adjustment_level == "reduce"
    assert all(item.progression.action is not ProgressionAction.INCREASE_LOAD for item in reduced.exercises)
    assert all(item.sets == 2 for item in reduced.exercises)


def test_requested_focus_trained_heavily_yesterday_is_kept_but_reduced() -> None:
    history = _push_pull_legs_history()
    history.append(_strength("l2", _days_ago(1), _sets("SQUAT", None, *([(8, 60.0)] * 6))))

    automatic = _recommend(history)
    plan = _recommend(history, focus=StrengthFocus.LEGS)

    assert automatic.focus != "legs"  # the ranking rests a region trained heavily yesterday
    assert plan.focus == "legs"
    assert plan.adjustment_level == "reduce"
    assert any("requested legs had 6 primary sets yesterday" in text for text in plan.adjustments)
    assert all(item.progression.action is not ProgressionAction.INCREASE_LOAD for item in plan.exercises)


def test_requested_focus_without_history_is_not_switched_and_invents_nothing() -> None:
    bench_only = [
        _strength("b1", _days_ago(5), _sets("BENCH_PRESS", None, (10, 50.0), (10, 50.0), (10, 50.0))),
        _strength("b2", _days_ago(2), _sets("BENCH_PRESS", None, (10, 50.0), (10, 50.0), (10, 50.0))),
    ]

    plan = _recommend(bench_only, focus=StrengthFocus.SHOULDERS)

    assert plan.focus == "shoulders"
    assert plan.focus_source == "user"
    assert plan.auto_focus == "push"
    assert plan.exercises == ()
    assert plan.working_sets == 0
    assert any(text.startswith("history is limited: no familiar mapped shoulders exercise") for text in plan.reasons)


def test_single_unloaded_session_gives_a_rep_only_target_and_reports_limited_history() -> None:
    history = [_strength("s1", _days_ago(3), _sets("LATERAL_RAISE", None, (15, 0.0), (14, 0.0)))]

    plan = _recommend(history, focus=StrengthFocus.SHOULDERS)

    raise_ = plan.exercises[0]
    assert raise_.label == "LATERAL_RAISE/-"
    assert raise_.progression.load_kg is None
    assert raise_.progression.load_confidence == "none"
    assert any("only one session" in text for text in plan.reasons)


def test_requested_focus_still_respects_avoid() -> None:
    plan = _recommend(_shoulder_history(), focus=StrengthFocus.SHOULDERS, avoid_muscles=(MuscleGroup.ANTERIOR_DELTOID,))

    assert plan.focus == "shoulders"
    assert [item.label for item in plan.exercises] == ["LATERAL_RAISE/-", "SHRUG/UPRIGHT_ROW"]
    assert all(item.primary_muscle != "anterior_deltoid" for item in plan.exercises)
    assert plan.avoided_muscles == ("anterior_deltoid",)


def test_requested_focus_is_deterministic_and_order_independent() -> None:
    history = _shoulder_history() + _calm_upper_body_history()

    for focus in StrengthFocus:
        first = _recommend(history, focus=focus)
        second = _recommend(list(reversed(history)), focus=focus)
        assert json.dumps(dataclasses.asdict(first), default=str) == json.dumps(dataclasses.asdict(second), default=str)


# --- muscle balance, low-confidence loads, no-rule warnings ---------------------------------


def _legs_history_with_hinges() -> list[NormalizedActivity]:
    """2026-10-01 shape: lunges/squats are most familiar, hinge work exists once each."""
    return [
        _strength(
            "l1",
            _days_ago(20),
            _sets("LUNGE", None, (12, 20.0), (12, 20.0)) + _sets("SQUAT", None, (8, 40.0), start=2),
        ),
        _strength(
            "l2",
            _days_ago(13),
            _sets("SQUAT", None, (12, 40.0), (10, 40.0))
            + _sets("CRUNCH", "LEG_EXTENSIONS", (12, 50.0), (12, 50.0), start=2),
        ),
        _strength(
            "l3",
            _days_ago(12),
            _sets("DEADLIFT", "BARBELL_DEADLIFT", (12, 35.0), (11, 35.0), (10, 35.0))
            + _sets("LUNGE", None, (12, 30.0), start=3),
        ),
        _strength(
            "l4",
            _days_ago(8),
            _sets("DEADLIFT", "STRAIGHT_LEG_DEADLIFT", (10, 50.0), (8, 50.0))
            + _sets("LUNGE", None, (11, 40.0), (11, 40.0), start=2),
        ),
    ]


def _legs_history_with_hinges_and_leg_curl() -> list[NormalizedActivity]:
    """As above, plus a familiar non-hinge hamstring exercise."""
    return _legs_history_with_hinges() + [
        _strength("h1", _days_ago(6), _sets("LEG_CURL", None, (12, 30.0), (12, 30.0), (11, 30.0)))
    ]


def _deadlifts(plan: StrengthRecommendation) -> list[str]:
    return [item.label for item in plan.exercises if item.category == "DEADLIFT"]


def test_two_familiar_deadlift_variants_are_never_both_selected() -> None:
    plan = _recommend(_legs_history_with_hinges(), focus=StrengthFocus.LEGS)

    # The existing ranking picks one hinge (more familiar: 3 sets vs 2); the other is not added.
    assert _deadlifts(plan) == ["DEADLIFT/BARBELL_DEADLIFT"]
    assert all(item.label != "DEADLIFT/STRAIGHT_LEG_DEADLIFT" for item in plan.exercises)


def test_a_non_hinge_alternative_covers_the_muscle_the_second_hinge_would_have() -> None:
    plan = _recommend(_legs_history_with_hinges_and_leg_curl(), focus=StrengthFocus.LEGS)

    muscles = [item.primary_muscle for item in plan.exercises]
    assert plan.exercises[0].label == "LUNGE/-"  # most familiar compound stays the key
    assert _deadlifts(plan) == ["DEADLIFT/BARBELL_DEADLIFT"]
    assert "LEG_CURL/-" in [item.label for item in plan.exercises]
    assert muscles.count("quadriceps") <= 2
    assert {"glutes", "hamstrings"} <= set(muscles)
    assert {item.status for item in plan.focus_coverage} == {"covered"}
    assert plan.estimated_minutes == 41


def test_without_a_non_hinge_alternative_the_session_stays_short_and_says_why() -> None:
    plan = _recommend(_legs_history_with_hinges(), focus=StrengthFocus.LEGS)

    assert len(plan.exercises) == 3
    assert plan.estimated_minutes == 32
    assert [item.primary_muscle for item in plan.exercises].count("quadriceps") == 2  # no third quad as filler
    shortfall = next(text for text in plan.reasons if "against the 40-minute goal" in text)
    assert (
        "DEADLIFT/STRAIGHT_LEG_DEADLIFT considered, not added: one heavy hinge per session "
        "(DEADLIFT/BARBELL_DEADLIFT is planned)" in shortfall
    )
    assert "CRUNCH/LEG_EXTENSIONS considered, not added: quadriceps already has 2 exercises" in shortfall
    assert shortfall.endswith("nothing was added to fill the time")
    hamstrings = next(item for item in plan.focus_coverage if item.muscle == "hamstrings")
    assert hamstrings.status == "not_selected"
    assert "one heavy hinge per session" in hamstrings.note


def test_hinge_rule_never_changes_the_automatic_focus() -> None:
    history = _legs_history_with_hinges()

    automatic = _recommend(history)
    requested = _recommend(history, focus=StrengthFocus.LEGS)

    assert (automatic.focus, automatic.focus_source) == ("legs", "auto")
    assert automatic.regions == requested.regions
    assert len(_deadlifts(automatic)) == 1
    # Upper-body automatic choices are unaffected (no deadlift candidates there).
    assert _recommend(_push_pull_legs_history()).focus == "legs"
    assert _recommend(_calm_upper_body_history()).focus in ("push", "pull")


def test_hinge_rule_keeps_a_user_selected_focus() -> None:
    history = _legs_history_with_hinges() + _calm_upper_body_history()

    legs = _recommend(history, focus=StrengthFocus.LEGS)
    pull = _recommend(history, focus=StrengthFocus.PULL)

    assert (legs.focus, legs.focus_source) == ("legs", "user")
    assert len(_deadlifts(legs)) == 1
    assert (pull.focus, pull.focus_source) == ("pull", "user")
    assert _deadlifts(pull) == []


def test_quad_only_history_is_not_balanced_with_invented_exercises() -> None:
    history = [
        _strength(
            f"q{days}",
            _days_ago(days),
            _sets("SQUAT", None, (10, 40.0), (10, 40.0)) + _sets("LUNGE", None, (10, 20.0), (10, 20.0), start=2),
        )
        for days in (4, 9)
    ]

    plan = _recommend(history, focus=StrengthFocus.LEGS)

    assert {item.primary_muscle for item in plan.exercises} == {"quadriceps"}
    coverage = {item.muscle: item.status for item in plan.focus_coverage}
    assert coverage["hamstrings"] == coverage["glutes"] == "no_familiar_history"


def test_a_third_exercise_for_one_muscle_waits_for_an_uncovered_muscle() -> None:
    history = [
        _strength(
            f"q{days}",
            _days_ago(days),
            _sets("SQUAT", None, (10, 40.0), (10, 40.0))
            + _sets("LUNGE", None, (10, 20.0), (10, 20.0), start=2)
            + _sets("SQUAT", "BARBELL_BACK_SQUAT", (8, 60.0), (8, 60.0), start=4),
        )
        for days in (4, 9)
    ] + [_strength("h1", _days_ago(6), _sets("LEG_CURL", None, (12, 30.0), (12, 30.0)))]

    plan = _recommend(history, focus=StrengthFocus.LEGS)

    muscles = [item.primary_muscle for item in plan.exercises]
    assert muscles.count("quadriceps") == 2
    assert "hamstrings" in muscles
    shortfall = next(text for text in plan.reasons if "against the 40-minute goal" in text)
    assert "quadriceps already has 2 exercises" in shortfall


def test_mixed_equipment_load_is_low_confidence_with_a_range_and_a_confirm_step() -> None:
    # 2026-10-01 SHOULDER_PRESS/- shape: 30 kg then 16 kg under one auto-detected label.
    occurrences = [_occurrence("2026-09-10", (10, 30.0)), _occurrence("2026-09-22", (12, 16.0))]

    target = plan_progression(ExerciseLabel("SHOULDER_PRESS", None), occurrences, COMPOUND, AdjustmentLevel.NORMAL)

    assert target.load_confidence == "low"
    assert target.recorded_load_range_kg == (16.0, 30.0)
    assert not target.same_load_evidence
    assert target.load_guidance is not None
    assert "confirm the equipment and load used last time" in target.load_guidance
    # The progression rule itself is unchanged.
    assert target.action is ProgressionAction.ADD_REPS
    assert target.load_kg == 16.0


def test_low_confidence_load_repeated_last_time_is_the_comparable_start() -> None:
    occurrences = [
        _occurrence("2026-09-03", (10, 6.0)),
        _occurrence("2026-09-10", (12, 10.0)),
        _occurrence("2026-09-17", (12, 6.0)),
    ]

    target = plan_progression(
        ExerciseLabel("LATERAL_RAISE", None), occurrences, RepRange(10, 20), AdjustmentLevel.NORMAL
    )

    assert target.load_confidence == "low"
    assert target.same_load_evidence
    assert target.load_guidance is not None and "also used on 2026-09-03" in target.load_guidance


def test_consistent_load_has_no_guidance() -> None:
    occurrences = [_occurrence("2026-09-10", (10, 50.0)), _occurrence("2026-09-17", (11, 50.0))]

    target = plan_progression(BENCH, occurrences, COMPOUND, AdjustmentLevel.NORMAL)

    assert target.load_confidence == "normal"
    assert target.load_guidance is None
    assert target.recorded_load_range_kg == (50.0, 50.0)


def _no_rule_history() -> list[NormalizedActivity]:
    """2026-09-30 shape: a confirmed pull session whose labels have no taxonomy rule yet."""
    history = _push_pull_legs_history()
    history.append(
        _strength(
            "nr1",
            _days_ago(1),
            _sets("PULL_UP", "WIDE_GRIP_LAT_PULLDOWN", (12, 30.0), (10, 30.0), (20, 20.0), (17, 20.0))
            + _sets("ROW", "BENT_OVER_ROW_WITH_BARBELL", (12, 50.0), (10, 50.0), (8, 60.0), start=4)
            + _sets("PLYO", "BOX_JUMP", (3, 10.0), start=7),
        )
    )
    return history


def test_no_rule_sets_are_warned_about_but_never_counted() -> None:
    plan = _recommend(_no_rule_history())
    baseline = _recommend(_push_pull_legs_history())

    pull = next(item for item in plan.regions if item.region == "pull")
    assert pull.sets_previous_day == 0  # still not counted or ranked
    assert pull.no_rule_hint_sets_previous_day == 7
    assert any("may be underestimated" in text for text in pull.notes)
    assert plan.focus == baseline.focus
    notices = {item.label: item for item in plan.no_rule_notices}
    assert set(notices) == {"PULL_UP/WIDE_GRIP_LAT_PULLDOWN", "ROW/BENT_OVER_ROW_WITH_BARBELL", "PLYO/BOX_JUMP"}
    assert notices["PULL_UP/WIDE_GRIP_LAT_PULLDOWN"].category_hint_region == "pull"
    assert notices["PULL_UP/WIDE_GRIP_LAT_PULLDOWN"].set_count == 4
    assert notices["PLYO/BOX_JUMP"].category_hint_muscle is None  # no category rule: region unknown
    assert notices["PLYO/BOX_JUMP"].category_hint_region is None
    assert plan.no_rule_active_sets_last_7_days == 8
    assert any("8 sets in the last 7 days use labels without a taxonomy rule" in text for text in plan.reasons)
    assert all(item.label not in notices for item in plan.exercises)


def test_requested_focus_warns_when_no_rule_work_yesterday_may_hide_the_rest_rule() -> None:
    plan = _recommend(_no_rule_history(), focus=StrengthFocus.PULL)

    assert plan.adjustment_level == "normal"  # not inferred from an unmapped label
    assert any(
        "7 sets yesterday under labels without a taxonomy rule" in text and "may have missed it" in text
        for text in plan.adjustments
    )


def test_carried_recovery_hold_names_its_source_dates() -> None:
    rows = (
        recovery(AS_OF.isoformat(), sleep_seconds=None, sleep_score=None),
        recovery(_days_ago(1).isoformat(), sleep_seconds=13740, training_readiness_level="LOW"),
    )

    plan = _recommend(_push_pull_legs_history(), recoveries=rows)

    assert plan.adjustment_level == "hold"
    assert "carried from earlier mornings" in plan.adjustments[0]
    assert _days_ago(1).isoformat() in plan.adjustments[0]
    assert all(item.progression.action is not ProgressionAction.INCREASE_LOAD for item in plan.exercises)


def test_uncovered_muscles_win_the_last_slots_over_a_second_chest_compound() -> None:
    # 2026-09-21 shape: a familiar push-up would make chest the only muscle with two exercises
    # while lateral deltoid and triceps both have familiar isolation work.
    history = _push_pull_legs_history() + [
        _strength(
            f"x{days}",
            _days_ago(days),
            _sets("PUSH_UP", None, (15, 0.0), (15, 0.0)) + _sets("LATERAL_RAISE", None, (15, 8.0), start=2),
        )
        for days in (8, 12)
    ]

    plan = _recommend(history, focus=StrengthFocus.PUSH)

    assert [item.primary_muscle for item in plan.exercises] == [
        "chest",
        "anterior_deltoid",
        "triceps",
        "lateral_deltoid",
    ]
    assert {item.status for item in plan.focus_coverage} == {"covered"}


def test_a_reduced_full_size_session_names_recovery_not_unused_exercises() -> None:
    history = _legs_history_with_hinges_and_leg_curl()
    poor = (recovery(AS_OF.isoformat(), training_readiness_level="POOR"),)

    plan = _recommend(history, recoveries=poor, focus=StrengthFocus.LEGS)

    assert len(plan.exercises) == 4
    shortfall = next(text for text in plan.reasons if "against the 40-minute goal" in text)
    assert "recovery reduce: one set fewer per exercise" in shortfall
    assert "considered, not added" not in shortfall
    assert not shortfall.startswith("history is limited")


def test_focus_names_no_rule_work_that_its_category_puts_in_the_focus() -> None:
    plan = _recommend(_no_rule_history(), focus=StrengthFocus.PULL)

    line = next(text for text in plan.reasons if text.startswith("pull counts may be underestimated"))
    assert "7 sets in the last 28 days" in line
    assert "PULL_UP/WIDE_GRIP_LAT_PULLDOWN" in line and "ROW/BENT_OVER_ROW_WITH_BARBELL" in line
    assert "PLYO/BOX_JUMP" not in line
