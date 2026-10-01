from __future__ import annotations

import json
import random
from collections.abc import Sequence
from datetime import date

from analytics_builders import activity, strength_set

from muscle50.domain.activity import ActivityType, NormalizedActivity, StrengthSet
from muscle50.domain.analytics import (
    LabelOriginCounts,
    QualityIssueCode,
    SetRef,
    StrengthTaxonomySummary,
    TaxonomyExerciseGroup,
    TaxonomyGroup,
    TrainingSnapshot,
    build_training_snapshot,
)
from muscle50.domain.exercise_taxonomy import TAXONOMY_VERSION
from muscle50.presentation.terminal import render_training_snapshot, render_training_snapshot_json

AS_OF = date(2026, 3, 14)


def _snapshot(activities: Sequence[NormalizedActivity]) -> TrainingSnapshot:
    return build_training_snapshot(AS_OF, 7, activities, ())


def _strength(source_id: str, day: str, *sets: StrengthSet) -> NormalizedActivity:
    return activity(source_id, f"2026-03-{day}T08:00:00", ActivityType.STRENGTH, strength_sets=sets)


def _groups(groups: tuple[TaxonomyGroup, ...]) -> dict[str, int]:
    return {item.key: item.active_set_count for item in groups}


def _labels(taxonomy: StrengthTaxonomySummary) -> dict[tuple[str | None, str | None], TaxonomyExerciseGroup]:
    return {(item.category, item.exercise_name): item for item in taxonomy.by_exercise}


def _mixed_week() -> list[NormalizedActivity]:
    return [
        _strength(
            "s1",
            "10",
            strength_set(1, category="BENCH_PRESS", probability=45.0),
            strength_set(2, set_type="REST", category=None),
            strength_set(3, category="BENCH_PRESS", probability=45.0),
            strength_set(4, category="PULL_UP", name="LAT_PULLDOWN", probability=100.0),
            strength_set(5, category="UNKNOWN", probability=99.609375),
        ),
        _strength(
            "s2",
            "12",
            strength_set(1, category="SQUAT", name="BARBELL_BACK_SQUAT", probability=100.0),
            strength_set(2, category="TRICEPS_EXTENSION", name="BENCH_DIP"),
            strength_set(3, category="PLYO", name="BOX_JUMP", probability=37.5),
            strength_set(4, category=None),
        ),
    ]


def _taxonomy() -> StrengthTaxonomySummary:
    return _snapshot(_mixed_week()).strength.taxonomy


def test_primary_dimensions_count_each_active_set_exactly_once() -> None:
    taxonomy = _taxonomy()

    assert taxonomy.taxonomy_version == TAXONOMY_VERSION
    assert taxonomy.active_set_count == 8
    assert taxonomy.mapped_active_set_count == 5
    assert taxonomy.unmapped_active_set_count == 3
    assert taxonomy.unknown_active_set_count + taxonomy.no_rule_active_set_count == taxonomy.unmapped_active_set_count
    assert sum(item.active_set_count for item in taxonomy.by_exercise) == taxonomy.active_set_count
    mapped_labels = [item for item in taxonomy.by_exercise if item.unmapped_reason is None]
    assert sum(item.active_set_count for item in mapped_labels) == taxonomy.mapped_active_set_count
    for groups in (taxonomy.by_movement_pattern, taxonomy.by_primary_muscle):
        assert sum(item.active_set_count for item in groups) == taxonomy.mapped_active_set_count
        assert (
            sum(item.active_set_count for item in groups) + taxonomy.unmapped_active_set_count
            == taxonomy.active_set_count
        )


def test_aggregation_by_original_garmin_label_pattern_and_primary_muscle() -> None:
    taxonomy = _taxonomy()
    labels = _labels(taxonomy)

    assert {label: item.active_set_count for label, item in labels.items()} == {
        ("BENCH_PRESS", None): 2,
        ("PULL_UP", "LAT_PULLDOWN"): 1,
        ("SQUAT", "BARBELL_BACK_SQUAT"): 1,
        ("TRICEPS_EXTENSION", "BENCH_DIP"): 1,
        ("UNKNOWN", None): 1,
        ("PLYO", "BOX_JUMP"): 1,
        (None, None): 1,
    }
    dip = labels[("TRICEPS_EXTENSION", "BENCH_DIP")]
    assert (dip.movement_pattern, dip.primary_muscle, dip.secondary_muscles, dip.mapping_basis) == (
        "elbow_extension",
        "triceps",
        ("chest", "anterior_deltoid"),
        "exercise_name",
    )
    assert _groups(taxonomy.by_movement_pattern) == {
        "horizontal_push": 2,
        "elbow_extension": 1,
        "squat": 1,
        "vertical_pull": 1,
    }
    assert _groups(taxonomy.by_primary_muscle) == {"chest": 2, "lats": 1, "quadriceps": 1, "triceps": 1}
    # Sorted by count descending, then key.
    assert [item.key for item in taxonomy.by_primary_muscle] == ["chest", "lats", "quadriceps", "triceps"]


def test_distinct_garmin_labels_are_never_merged_even_with_identical_taxonomy() -> None:
    taxonomy = _snapshot(
        [
            _strength(
                "s",
                "10",
                strength_set(1, category="CRUNCH", name="LEG_EXTENSIONS", probability=100.0),
                strength_set(2, category="CRUNCH", name="WEIGHTED_LEG_EXTENSIONS", probability=100.0),
                strength_set(3, category="BENCH_PRESS"),
                strength_set(4, category="BENCH_PRESS", name="DUMBBELL_BENCH_PRESS"),
            )
        ]
    ).strength.taxonomy
    labels = _labels(taxonomy)

    assert labels[("CRUNCH", "LEG_EXTENSIONS")].sets == (SetRef("s", 1),)
    assert labels[("CRUNCH", "WEIGHTED_LEG_EXTENSIONS")].sets == (SetRef("s", 2),)
    assert labels[("BENCH_PRESS", None)].sets == (SetRef("s", 3),)
    assert labels[("BENCH_PRESS", "DUMBBELL_BENCH_PRESS")].sets == (SetRef("s", 4),)
    # Pattern and primary-muscle views may combine them.
    assert _groups(taxonomy.by_movement_pattern) == {"horizontal_push": 2, "knee_extension": 2}
    assert labels[("CRUNCH", "LEG_EXTENSIONS")].mapping_basis == "category_override"


def test_shoulder_variants_stay_separate_garmin_labels() -> None:
    taxonomy = _snapshot(
        [
            _strength(
                "s",
                "10",
                strength_set(1, category="SHOULDER_PRESS", name="SEATED_BARBELL_SHOULDER_PRESS", probability=100.0),
                strength_set(2, category="SHOULDER_PRESS", name="DUMBBELL_SHOULDER_PRESS", probability=100.0),
                strength_set(3, category="SHOULDER_PRESS"),
                strength_set(4, category="LATERAL_RAISE", name="ONE_ARM_CABLE_LATERAL_RAISE", probability=100.0),
                strength_set(5, category="LATERAL_RAISE"),
            )
        ]
    ).strength.taxonomy
    labels = _labels(taxonomy)

    assert labels[("SHOULDER_PRESS", "SEATED_BARBELL_SHOULDER_PRESS")].sets == (SetRef("s", 1),)
    assert labels[("SHOULDER_PRESS", "DUMBBELL_SHOULDER_PRESS")].sets == (SetRef("s", 2),)
    assert labels[("SHOULDER_PRESS", None)].sets == (SetRef("s", 3),)
    assert labels[("LATERAL_RAISE", "ONE_ARM_CABLE_LATERAL_RAISE")].sets == (SetRef("s", 4),)
    assert labels[("LATERAL_RAISE", None)].sets == (SetRef("s", 5),)
    assert taxonomy.no_rule_active_set_count == 0
    assert _groups(taxonomy.by_primary_muscle) == {"anterior_deltoid": 3, "lateral_deltoid": 2}


def test_secondary_exposures_are_reported_separately_and_not_added_to_primary_totals() -> None:
    taxonomy = _taxonomy()

    # bench press x2 -> triceps, anterior_deltoid; lat pulldown -> biceps, upper_back;
    # back squat -> glutes; bench dip -> chest, anterior_deltoid.
    assert _groups(taxonomy.secondary_muscle_set_exposures) == {
        "anterior_deltoid": 3,
        "triceps": 2,
        "biceps": 1,
        "chest": 1,
        "glutes": 1,
        "upper_back": 1,
    }
    primary = _groups(taxonomy.by_primary_muscle)
    # Triceps is primary for one set (bench dip) and secondary for two (bench press): the
    # headline stays 1, and chest stays 2 even though the bench dip also exposes it.
    assert primary["triceps"] == 1
    assert primary["chest"] == 2
    assert sum(primary.values()) == taxonomy.mapped_active_set_count
    assert "anterior_deltoid" not in primary


def test_no_double_counting_when_one_set_has_many_muscles() -> None:
    sets = tuple(strength_set(i, category="ROW") for i in range(1, 4))
    taxonomy = _snapshot([_strength("s", "10", *sets)]).strength.taxonomy

    assert _groups(taxonomy.by_primary_muscle) == {"upper_back": 3}
    assert _groups(taxonomy.secondary_muscle_set_exposures) == {"biceps": 3, "lats": 3, "posterior_deltoid": 3}
    assert taxonomy.mapped_active_set_count == 3


def test_unknown_and_unruled_labels_stay_explicit_with_provenance() -> None:
    snapshot = _snapshot(_mixed_week())
    taxonomy = snapshot.strength.taxonomy
    labels = _labels(taxonomy)

    unknown = labels[("UNKNOWN", None)]
    assert unknown.unmapped_reason == "unknown_source_label"
    assert (unknown.movement_pattern, unknown.primary_muscle, unknown.secondary_muscles) == (None, None, ())
    assert unknown.sets == (SetRef("s1", 5),)
    assert labels[(None, None)].unmapped_reason == "unknown_source_label"
    assert labels[(None, None)].sets == (SetRef("s2", 4),)
    assert labels[("PLYO", "BOX_JUMP")].unmapped_reason == "no_rule"
    assert labels[("PLYO", "BOX_JUMP")].sets == (SetRef("s2", 3),)

    # UNKNOWN count and affected activities are reported and reconcile with the review count.
    assert taxonomy.unknown_active_set_count == snapshot.strength.unclassified_active_set_count == 2
    assert taxonomy.unknown_source_activity_ids == ("s1", "s2")
    assert taxonomy.no_rule_active_set_count == 1

    issues = [issue for issue in snapshot.quality_issues if issue.code is QualityIssueCode.STRENGTH_UNMAPPED_EXERCISE]
    assert [(issue.source_activity_id, issue.set_sequences) for issue in issues] == [("s2", (3,))]


def test_group_provenance_lists_activities_and_set_sequences() -> None:
    taxonomy = _snapshot(
        [
            _strength("s1", "10", strength_set(1, category="CURL"), strength_set(2, category="CURL")),
            _strength("s2", "12", strength_set(7, category="CURL", name="DUMBBELL_HAMMER_CURL")),
        ]
    ).strength.taxonomy
    biceps = next(item for item in taxonomy.by_primary_muscle if item.key == "biceps")

    assert biceps.active_set_count == 3
    assert biceps.source_activity_ids == ("s1", "s2")
    assert biceps.sets == (SetRef("s1", 1), SetRef("s1", 2), SetRef("s2", 7))
    forearms = next(item for item in taxonomy.secondary_muscle_set_exposures if item.key == "forearms")
    assert forearms.sets == (SetRef("s2", 7),)


def test_label_origin_is_counted_per_group_without_weighting() -> None:
    taxonomy = _taxonomy()
    chest = next(item for item in taxonomy.by_primary_muscle if item.key == "chest")
    triceps = next(item for item in taxonomy.by_primary_muscle if item.key == "triceps")

    assert chest.label_origins == LabelOriginCounts(confirmed=0, auto_detected=2, unspecified=0)
    assert triceps.label_origins == LabelOriginCounts(confirmed=0, auto_detected=0, unspecified=1)
    assert taxonomy.mapped_label_origins == LabelOriginCounts(confirmed=2, auto_detected=2, unspecified=1)
    assert _labels(taxonomy)[("PULL_UP", "LAT_PULLDOWN")].label_origins == LabelOriginCounts(1, 0, 0)
    # Counts never change with origin: an auto-detected set is still one full set.
    assert chest.active_set_count == 2


def test_rest_rows_and_sessions_without_set_detail_are_not_counted() -> None:
    taxonomy = _snapshot(
        [
            _strength("s1", "10", strength_set(1, set_type="REST", category="SQUAT")),
            activity("s2", "2026-03-11T08:00:00", ActivityType.STRENGTH),
        ]
    ).strength.taxonomy

    assert taxonomy.active_set_count == 0
    assert taxonomy.by_exercise == ()
    assert taxonomy.by_primary_muscle == ()
    assert taxonomy.secondary_muscle_set_exposures == ()
    assert taxonomy.unknown_source_activity_ids == ()


def test_existing_exercise_aggregates_keep_original_garmin_identity() -> None:
    exercises = {(item.exercise_key, item.category) for item in _snapshot(_mixed_week()).strength.exercises}

    assert ("BENCH_PRESS", "BENCH_PRESS") in exercises
    assert ("LAT_PULLDOWN", "PULL_UP") in exercises
    assert ("BOX_JUMP", "PLYO") in exercises


def test_taxonomy_output_is_deterministic_and_independent_of_input_order() -> None:
    activities = _mixed_week()
    expected = render_training_snapshot_json(_snapshot(activities))
    rng = random.Random(7)
    for _ in range(5):
        shuffled = activities[:]
        rng.shuffle(shuffled)
        assert render_training_snapshot_json(_snapshot(shuffled)) == expected


def test_taxonomy_rendering_is_ascii_and_keeps_secondary_separate() -> None:
    snapshot = _snapshot(_mixed_week())
    text = render_training_snapshot(snapshot)

    text.encode("cp949")
    assert text.isascii()
    assert "Exercise taxonomy v1: 5/8 ACTIVE sets mapped, 3 unmapped (UNKNOWN 2, no rule 1)" in text
    assert "UNKNOWN activities (2): s1, s2" in text
    assert "Secondary muscle set exposures (not added to primary totals):" in text
    assert "PLYO/BOX_JUMP: 1 [unmapped: no_rule]" in text
    assert (
        "TRICEPS_EXTENSION/BENCH_DIP: 1 [elbow_extension, primary triceps, secondary chest, anterior_deltoid]" in text
    )

    payload = json.loads(render_training_snapshot_json(snapshot))
    taxonomy = payload["strength"]["taxonomy"]
    assert taxonomy["taxonomy_version"] == 1
    assert taxonomy["by_primary_muscle"][0]["key"] == "chest"
    assert taxonomy["by_exercise"][0]["category"] == "BENCH_PRESS"
    assert taxonomy["by_exercise"][0]["exercise_name"] is None
    assert "canonical" not in json.dumps(taxonomy)
    assert taxonomy["by_primary_muscle"][0]["sets"] == [
        {"source_activity_id": "s1", "sequence": 1},
        {"source_activity_id": "s1", "sequence": 3},
    ]
