from __future__ import annotations

import dataclasses
import itertools

import pytest
from analytics_builders import activity, strength_set

from muscle50.domain.activity import ActivityType
from muscle50.domain.activity_review import derive_activity_review
from muscle50.domain.exercise_taxonomy import (
    EXERCISE_RULES,
    ExerciseClassification,
    ExerciseRule,
    LabelOrigin,
    MappingBasis,
    MovementPattern,
    MuscleGroup,
    UnmappedReason,
    classify_exercise,
    classify_strength_set,
    label_origin,
)

# Every (category, name) label observed in production on 2026-10-01 (ACTIVE sets).
# PLYO/BOX_JUMP is deliberately without a rule; UNKNOWN is never resolved.
PRODUCTION_LABELS: tuple[tuple[str, str | None], ...] = (
    ("BENCH_PRESS", None),
    ("BENCH_PRESS", "CLOSE_GRIP_BARBELL_BENCH_PRESS"),
    ("BENCH_PRESS", "DUMBBELL_BENCH_PRESS"),
    ("BENCH_PRESS", "INCLINE_SMITH_MACHINE_BENCH_PRESS"),
    ("CRUNCH", "LEG_EXTENSIONS"),
    ("CRUNCH", "WEIGHTED_LEG_EXTENSIONS"),
    ("CURL", None),
    ("CURL", "CLOSE_GRIP_EZ_BAR_BICEPS_CURL"),
    ("CURL", "DUMBBELL_HAMMER_CURL"),
    ("DEADLIFT", "BARBELL_DEADLIFT"),
    ("DEADLIFT", "STRAIGHT_LEG_DEADLIFT"),
    ("FLYE", "CABLE_CROSSOVER"),
    ("FLYE", "DUMBBELL_FLYE"),
    ("HIP_RAISE", "BARBELL_HIP_THRUST_ON_FLOOR"),
    ("LATERAL_RAISE", None),
    ("LEG_CURL", None),
    ("LEG_RAISE", "WEIGHTED_HANGING_LEG_RAISE"),
    ("LUNGE", None),
    ("LUNGE", "BARBELL_LUNGE"),
    ("PULL_UP", None),
    ("PULL_UP", "LAT_PULLDOWN"),
    ("PULL_UP", "STANDING_CABLE_PULLOVER"),
    ("PULL_UP", "STRAIGHT_ARM_PULLDOWN"),
    ("PUSH_UP", None),
    ("ROW", None),
    ("ROW", "SEATED_CABLE_ROW"),
    ("SHOULDER_PRESS", None),
    ("SHRUG", None),
    ("SHRUG", "UPRIGHT_ROW"),
    ("SIT_UP", None),
    ("SQUAT", None),
    ("SQUAT", "BARBELL_BACK_SQUAT"),
    ("TRICEPS_EXTENSION", None),
    ("TRICEPS_EXTENSION", "BENCH_DIP"),
    ("TRICEPS_EXTENSION", "CABLE_OVERHEAD_TRICEPS_EXTENSION"),
    ("TRICEPS_EXTENSION", "DUMBBELL_KICKBACK"),
    ("TRICEPS_EXTENSION", "OVERHEAD_DUMBBELL_TRICEPS_EXTENSION"),
    ("TRICEPS_EXTENSION", "TRICEPS_PRESSDOWN"),
)


# Rule table integrity


def test_rules_are_unique_per_original_garmin_label() -> None:
    labels = [(rule.source_category, rule.source_name) for rule in EXERCISE_RULES]
    assert len(labels) == len(set(labels))


def test_taxonomy_has_no_canonical_names_or_merging() -> None:
    # The original Garmin label is the identity: no field renames or re-keys an exercise.
    for model in (ExerciseRule, ExerciseClassification):
        names = {item.name for item in dataclasses.fields(model)}
        assert not {name for name in names if "canonical" in name or name in {"key", "exercise_key", "display_name"}}
    # Distinct Garmin labels stay distinct even when their taxonomy is identical.
    plain = classify_exercise("CRUNCH", "LEG_EXTENSIONS")
    weighted = classify_exercise("CRUNCH", "WEIGHTED_LEG_EXTENSIONS")
    assert plain.rule is not None and weighted.rule is not None
    assert plain.rule != weighted.rule
    assert (plain.source_category, plain.source_name) != (weighted.source_category, weighted.source_name)


def test_rules_cover_exactly_the_reviewed_production_labels() -> None:
    # A rule for a label that was never observed would be unreviewed against real data.
    assert {(rule.source_category, rule.source_name) for rule in EXERCISE_RULES} == set(PRODUCTION_LABELS)


def test_rule_basis_matches_label_shape() -> None:
    for rule in EXERCISE_RULES:
        if rule.basis is MappingBasis.CATEGORY_ONLY:
            assert rule.source_name is None
        else:
            assert rule.source_name is not None
        assert (rule.note is not None) == (rule.basis is MappingBasis.CATEGORY_OVERRIDE)


def test_every_rule_has_one_primary_muscle_never_repeated_as_secondary() -> None:
    for rule in EXERCISE_RULES:
        assert isinstance(rule.primary_muscle, MuscleGroup)
        assert rule.primary_muscle not in rule.secondary_muscles
        assert len(rule.secondary_muscles) == len(set(rule.secondary_muscles))


def test_every_pattern_and_muscle_group_is_used_by_the_data_backed_rules() -> None:
    assert {rule.movement_pattern for rule in EXERCISE_RULES} == set(MovementPattern)
    used_muscles = {rule.primary_muscle for rule in EXERCISE_RULES} | {
        muscle for rule in EXERCISE_RULES for muscle in rule.secondary_muscles
    }
    assert used_muscles == set(MuscleGroup)


def test_taxonomy_does_not_define_patterns_or_muscles_without_data() -> None:
    assert "calf" not in {item.value for item in MovementPattern}
    assert "carry" not in {item.value for item in MovementPattern}
    assert "calves" not in {item.value for item in MuscleGroup}


# Known mappings (the reviewed v1 decisions)

_P = MovementPattern
_M = MuscleGroup


@pytest.mark.parametrize(
    ("category", "name", "pattern", "primary", "secondary", "basis"),
    [
        (
            "BENCH_PRESS",
            None,
            _P.HORIZONTAL_PUSH,
            _M.CHEST,
            (_M.TRICEPS, _M.ANTERIOR_DELTOID),
            MappingBasis.CATEGORY_ONLY,
        ),
        ("PULL_UP", None, _P.VERTICAL_PULL, _M.LATS, (_M.BICEPS, _M.UPPER_BACK), MappingBasis.CATEGORY_ONLY),
        ("SQUAT", None, _P.SQUAT, _M.QUADRICEPS, (_M.GLUTES,), MappingBasis.CATEGORY_ONLY),
        ("PULL_UP", "LAT_PULLDOWN", _P.VERTICAL_PULL, _M.LATS, (_M.BICEPS, _M.UPPER_BACK), MappingBasis.EXERCISE_NAME),
        (
            "BENCH_PRESS",
            "CLOSE_GRIP_BARBELL_BENCH_PRESS",
            _P.HORIZONTAL_PUSH,
            _M.TRICEPS,
            (_M.CHEST, _M.ANTERIOR_DELTOID),
            MappingBasis.EXERCISE_NAME,
        ),
        (
            "ROW",
            None,
            _P.HORIZONTAL_PULL,
            _M.UPPER_BACK,
            (_M.LATS, _M.BICEPS, _M.POSTERIOR_DELTOID),
            MappingBasis.CATEGORY_ONLY,
        ),
        (
            "ROW",
            "SEATED_CABLE_ROW",
            _P.HORIZONTAL_PULL,
            _M.UPPER_BACK,
            (_M.LATS, _M.BICEPS, _M.POSTERIOR_DELTOID),
            MappingBasis.EXERCISE_NAME,
        ),
        (
            "DEADLIFT",
            "BARBELL_DEADLIFT",
            _P.HINGE,
            _M.GLUTES,
            (_M.HAMSTRINGS, _M.QUADRICEPS),
            MappingBasis.EXERCISE_NAME,
        ),
        ("DEADLIFT", "STRAIGHT_LEG_DEADLIFT", _P.HINGE, _M.HAMSTRINGS, (_M.GLUTES,), MappingBasis.EXERCISE_NAME),
        (
            "SHRUG",
            "UPRIGHT_ROW",
            _P.SHOULDER_ABDUCTION,
            _M.LATERAL_DELTOID,
            (_M.UPPER_BACK,),
            MappingBasis.EXERCISE_NAME,
        ),
        ("SHRUG", None, _P.SCAPULAR_ELEVATION, _M.UPPER_BACK, (), MappingBasis.CATEGORY_ONLY),
        (
            "FLYE",
            "DUMBBELL_FLYE",
            _P.SHOULDER_HORIZONTAL_ADDUCTION,
            _M.CHEST,
            (_M.ANTERIOR_DELTOID,),
            MappingBasis.EXERCISE_NAME,
        ),
        (
            "FLYE",
            "CABLE_CROSSOVER",
            _P.SHOULDER_HORIZONTAL_ADDUCTION,
            _M.CHEST,
            (_M.ANTERIOR_DELTOID,),
            MappingBasis.EXERCISE_NAME,
        ),
        ("PULL_UP", "STRAIGHT_ARM_PULLDOWN", _P.VERTICAL_PULL, _M.LATS, (), MappingBasis.EXERCISE_NAME),
        ("PULL_UP", "STANDING_CABLE_PULLOVER", _P.VERTICAL_PULL, _M.LATS, (), MappingBasis.EXERCISE_NAME),
        ("CURL", "DUMBBELL_HAMMER_CURL", _P.ELBOW_FLEXION, _M.BICEPS, (_M.FOREARMS,), MappingBasis.EXERCISE_NAME),
        ("TRICEPS_EXTENSION", "TRICEPS_PRESSDOWN", _P.ELBOW_EXTENSION, _M.TRICEPS, (), MappingBasis.EXERCISE_NAME),
        ("LEG_CURL", None, _P.KNEE_FLEXION, _M.HAMSTRINGS, (), MappingBasis.CATEGORY_ONLY),
        ("SIT_UP", None, _P.CORE, _M.CORE, (), MappingBasis.CATEGORY_ONLY),
    ],
)
def test_known_mappings(
    category: str,
    name: str | None,
    pattern: MovementPattern,
    primary: MuscleGroup,
    secondary: tuple[MuscleGroup, ...],
    basis: MappingBasis,
) -> None:
    result = classify_exercise(category, name)

    assert result.mapped
    assert result.rule is not None
    assert (result.source_category, result.source_name) == (category, name)
    assert (result.rule.source_category, result.rule.source_name) == (category, name)
    assert result.rule.movement_pattern is pattern
    assert result.rule.primary_muscle is primary
    assert result.rule.secondary_muscles == secondary
    assert result.rule.basis is basis
    assert result.unmapped_reason is None


def test_garmin_leg_extensions_under_crunch_is_a_visible_category_override() -> None:
    for name in ("LEG_EXTENSIONS", "WEIGHTED_LEG_EXTENSIONS"):
        result = classify_exercise("CRUNCH", name)
        assert result.rule is not None
        assert result.source_name == name
        assert result.rule.movement_pattern is MovementPattern.KNEE_EXTENSION
        assert result.rule.primary_muscle is MuscleGroup.QUADRICEPS
        assert result.rule.basis is MappingBasis.CATEGORY_OVERRIDE
        assert result.rule.note


def test_lookup_is_an_exact_match_on_the_stored_label() -> None:
    assert classify_exercise("BENCH_PRESS", "DUMBBELL_BENCH_PRESS").mapped
    for category, name in (("bench_press", "DUMBBELL_BENCH_PRESS"), ("BENCH_PRESS", " DUMBBELL_BENCH_PRESS ")):
        result = classify_exercise(category, name)
        assert result.unmapped_reason is UnmappedReason.NO_RULE
        assert (result.source_category, result.source_name) == (category, name)


# Unmapped / UNKNOWN


@pytest.mark.parametrize(
    ("category", "name"),
    [("UNKNOWN", None), (" unknown ", None), (None, None), (None, "BENCH_PRESS"), ("BENCH_PRESS", "UNKNOWN")],
)
def test_unknown_or_missing_labels_are_never_resolved(category: str | None, name: str | None) -> None:
    result = classify_exercise(category, name)

    assert not result.mapped
    assert result.rule is None
    assert result.unmapped_reason is UnmappedReason.UNKNOWN_SOURCE_LABEL
    assert (result.source_category, result.source_name) == (category, name)


def test_unlisted_name_under_a_mapped_category_does_not_fall_back_to_the_category() -> None:
    result = classify_exercise("BENCH_PRESS", "SOME_FUTURE_BENCH_VARIANT")

    assert result.rule is None
    assert result.unmapped_reason is UnmappedReason.NO_RULE


def test_known_label_without_rule_is_unmapped_with_no_rule() -> None:
    # An empty (not UNKNOWN) category is not UNKNOWN for activity review either; it has no rule.
    for category, name in (("PLYO", "BOX_JUMP"), ("CARRY", None), ("DEADLIFT", None), (" ", "BENCH_DIP")):
        result = classify_exercise(category, name)
        assert result.rule is None
        assert result.unmapped_reason is UnmappedReason.NO_RULE


def test_stored_set_unknown_predicate_matches_activity_review_exactly() -> None:
    categories = ("BENCH_PRESS", "UNKNOWN", "unknown", " ", None)
    names = ("DUMBBELL_BENCH_PRESS", "UNKNOWN", None)
    keys = ("DUMBBELL_BENCH_PRESS", "BENCH_PRESS", "UNKNOWN", " unknown ", "", None)
    sets = []
    for sequence, (category, name, key) in enumerate(itertools.product(categories, names, keys), start=1):
        # The stored key may disagree with name/category; the stored key decides, as in review.
        sets.append(dataclasses.replace(strength_set(sequence, category=category, name=name), source_exercise_key=key))
    strength = activity("s", "2026-03-10T08:00:00", ActivityType.STRENGTH, strength_sets=tuple(sets))
    review = derive_activity_review(strength)
    flagged = {sequence for reason in review.reasons for sequence in reason.set_sequences}

    for item in sets:
        unknown = classify_strength_set(item).unmapped_reason is UnmappedReason.UNKNOWN_SOURCE_LABEL
        assert unknown == (item.sequence in flagged), item


def test_classification_is_deterministic() -> None:
    first = [classify_exercise(category, name) for category, name in PRODUCTION_LABELS]
    second = [classify_exercise(category, name) for category, name in reversed(PRODUCTION_LABELS)]
    assert first == list(reversed(second))


def test_every_production_label_maps_except_box_jump() -> None:
    assert all(classify_exercise(category, name).mapped for category, name in PRODUCTION_LABELS)
    assert classify_exercise("PLYO", "BOX_JUMP").unmapped_reason is UnmappedReason.NO_RULE


# Label origin


@pytest.mark.parametrize(
    ("probability", "origin"),
    [
        (100.0, LabelOrigin.CONFIRMED),
        (99.609375, LabelOrigin.AUTO_DETECTED),
        (33.984375, LabelOrigin.AUTO_DETECTED),
        (0.0, LabelOrigin.AUTO_DETECTED),
        (None, LabelOrigin.UNSPECIFIED),
    ],
)
def test_label_origin_comes_only_from_garmin_probability(probability: float | None, origin: LabelOrigin) -> None:
    assert label_origin(probability) is origin
