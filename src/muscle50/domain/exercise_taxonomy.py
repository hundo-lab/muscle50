"""Exercise taxonomy v1: attributes attached to original Garmin exercise labels.

This is a pure lookup table, not a classifier. Rules:

- The original Garmin ``(category, name)`` label, exactly as stored, is the exercise
  identity. The taxonomy never renames, canonicalizes, or merges labels; it only attaches
  a movement pattern, one primary muscle group, and secondary muscle groups to a label.
  ``name`` is ``None`` for labels where Garmin supplied only a category.
- Rules exist only for labels observed in real data and reviewed by hand. Lookup is an
  exact match on the stored values: no fuzzy matching, no inference from weight/reps/
  neighbouring sets, and no fallback from an unlisted name to its category rule (that
  would silently map new Garmin variants).
- Garmin UNKNOWN/missing labels use exactly the predicate of ``derive_activity_review``
  and are never resolved.
- Secondary muscle groups are exposure labels only; they are never counted as sets.
- The taxonomy is independent of set weight, reps, and any training recommendation.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType

from muscle50.domain.activity import StrengthSet

TAXONOMY_VERSION = 1

# Garmin reports a full-certainty label (probability 100) only for labels set in Garmin
# Connect; the watch's own auto-detection always reports < 100 (see docs/exercise-taxonomy.md).
CONFIRMED_LABEL_PROBABILITY = 100.0


class MovementPattern(StrEnum):
    HORIZONTAL_PUSH = "horizontal_push"
    VERTICAL_PUSH = "vertical_push"
    HORIZONTAL_PULL = "horizontal_pull"
    VERTICAL_PULL = "vertical_pull"
    SQUAT = "squat"
    HINGE = "hinge"
    LUNGE = "lunge"
    KNEE_FLEXION = "knee_flexion"
    KNEE_EXTENSION = "knee_extension"
    ELBOW_FLEXION = "elbow_flexion"
    ELBOW_EXTENSION = "elbow_extension"
    SHOULDER_ABDUCTION = "shoulder_abduction"
    SHOULDER_HORIZONTAL_ADDUCTION = "shoulder_horizontal_adduction"
    SCAPULAR_ELEVATION = "scapular_elevation"
    CORE = "core"


class MuscleGroup(StrEnum):
    CHEST = "chest"
    LATS = "lats"
    UPPER_BACK = "upper_back"
    ANTERIOR_DELTOID = "anterior_deltoid"
    LATERAL_DELTOID = "lateral_deltoid"
    POSTERIOR_DELTOID = "posterior_deltoid"
    BICEPS = "biceps"
    TRICEPS = "triceps"
    FOREARMS = "forearms"
    QUADRICEPS = "quadriceps"
    HAMSTRINGS = "hamstrings"
    GLUTES = "glutes"
    CORE = "core"


class MappingBasis(StrEnum):
    EXERCISE_NAME = "exercise_name"
    """Garmin supplied a category and a specific exercise name."""
    CATEGORY_ONLY = "category_only"
    """Garmin supplied only a category (no specific exercise name)."""
    CATEGORY_OVERRIDE = "category_override"
    """The rule deliberately departs from Garmin's category; the reason is in ``ExerciseRule.note``."""


class UnmappedReason(StrEnum):
    UNKNOWN_SOURCE_LABEL = "unknown_source_label"
    """Garmin's label is UNKNOWN or missing. Never guessed."""
    NO_RULE = "no_rule"
    """A known Garmin label without a v1 rule, including unlisted names under a mapped category."""


class LabelOrigin(StrEnum):
    CONFIRMED = "confirmed"
    """Garmin probability is 100: the label was set or kept in Garmin Connect."""
    AUTO_DETECTED = "auto_detected"
    """Garmin probability is below 100: the watch's automatic exercise detection."""
    UNSPECIFIED = "unspecified"
    """No probability was stored."""


@dataclass(frozen=True)
class ExerciseRule:
    """Taxonomy attributes for one original Garmin label."""

    source_category: str
    source_name: str | None
    movement_pattern: MovementPattern
    primary_muscle: MuscleGroup
    secondary_muscles: tuple[MuscleGroup, ...]
    basis: MappingBasis
    note: str | None = None


@dataclass(frozen=True)
class ExerciseClassification:
    """A stored Garmin label (unchanged) with its rule, or the reason it has none."""

    source_category: str | None
    source_name: str | None
    rule: ExerciseRule | None
    unmapped_reason: UnmappedReason | None

    @property
    def mapped(self) -> bool:
        return self.rule is not None


_P = MovementPattern
_M = MuscleGroup

_LEG_EXTENSION_NOTE = (
    "Garmin's catalogue has no machine knee-extension exercise; 'leg extension' exists only under "
    "CRUNCH (and banded exercises), so a machine leg extension can only be logged as this label."
)


def _rule(
    category: str,
    name: str | None,
    pattern: MovementPattern,
    primary: MuscleGroup,
    *secondary: MuscleGroup,
    override_note: str | None = None,
) -> ExerciseRule:
    if override_note is not None:
        basis = MappingBasis.CATEGORY_OVERRIDE
    elif name is None:
        basis = MappingBasis.CATEGORY_ONLY
    else:
        basis = MappingBasis.EXERCISE_NAME
    return ExerciseRule(category, name, pattern, primary, secondary, basis, override_note)


EXERCISE_RULES: tuple[ExerciseRule, ...] = (
    _rule("BENCH_PRESS", None, _P.HORIZONTAL_PUSH, _M.CHEST, _M.TRICEPS, _M.ANTERIOR_DELTOID),
    # Close grip shifts the target to the triceps (decision recorded in docs).
    _rule(
        "BENCH_PRESS", "CLOSE_GRIP_BARBELL_BENCH_PRESS", _P.HORIZONTAL_PUSH, _M.TRICEPS, _M.CHEST, _M.ANTERIOR_DELTOID
    ),
    _rule("BENCH_PRESS", "DUMBBELL_BENCH_PRESS", _P.HORIZONTAL_PUSH, _M.CHEST, _M.TRICEPS, _M.ANTERIOR_DELTOID),
    _rule(
        "BENCH_PRESS",
        "INCLINE_SMITH_MACHINE_BENCH_PRESS",
        _P.HORIZONTAL_PUSH,
        _M.CHEST,
        _M.ANTERIOR_DELTOID,
        _M.TRICEPS,
    ),
    _rule("CRUNCH", "LEG_EXTENSIONS", _P.KNEE_EXTENSION, _M.QUADRICEPS, override_note=_LEG_EXTENSION_NOTE),
    _rule("CRUNCH", "WEIGHTED_LEG_EXTENSIONS", _P.KNEE_EXTENSION, _M.QUADRICEPS, override_note=_LEG_EXTENSION_NOTE),
    # "biceps" stands for the elbow flexors.
    _rule("CURL", None, _P.ELBOW_FLEXION, _M.BICEPS),
    _rule("CURL", "CLOSE_GRIP_EZ_BAR_BICEPS_CURL", _P.ELBOW_FLEXION, _M.BICEPS),
    _rule("CURL", "DUMBBELL_HAMMER_CURL", _P.ELBOW_FLEXION, _M.BICEPS, _M.FOREARMS),
    _rule("DEADLIFT", "BARBELL_DEADLIFT", _P.HINGE, _M.GLUTES, _M.HAMSTRINGS, _M.QUADRICEPS),
    _rule("DEADLIFT", "STRAIGHT_LEG_DEADLIFT", _P.HINGE, _M.HAMSTRINGS, _M.GLUTES),
    _rule("FLYE", "CABLE_CROSSOVER", _P.SHOULDER_HORIZONTAL_ADDUCTION, _M.CHEST, _M.ANTERIOR_DELTOID),
    _rule("FLYE", "DUMBBELL_FLYE", _P.SHOULDER_HORIZONTAL_ADDUCTION, _M.CHEST, _M.ANTERIOR_DELTOID),
    _rule("HIP_RAISE", "BARBELL_HIP_THRUST_ON_FLOOR", _P.HINGE, _M.GLUTES, _M.HAMSTRINGS),
    _rule("LATERAL_RAISE", None, _P.SHOULDER_ABDUCTION, _M.LATERAL_DELTOID),
    _rule("LEG_CURL", None, _P.KNEE_FLEXION, _M.HAMSTRINGS),
    _rule("LEG_RAISE", "WEIGHTED_HANGING_LEG_RAISE", _P.CORE, _M.CORE),
    _rule("LUNGE", None, _P.LUNGE, _M.QUADRICEPS, _M.GLUTES),
    _rule("LUNGE", "BARBELL_LUNGE", _P.LUNGE, _M.QUADRICEPS, _M.GLUTES),
    _rule("PULL_UP", None, _P.VERTICAL_PULL, _M.LATS, _M.BICEPS, _M.UPPER_BACK),
    _rule("PULL_UP", "LAT_PULLDOWN", _P.VERTICAL_PULL, _M.LATS, _M.BICEPS, _M.UPPER_BACK),
    # Straight-arm pulldown and pullover are lat-dominant shoulder extension in the vertical
    # plane; v1 keeps them in vertical_pull.
    _rule("PULL_UP", "STANDING_CABLE_PULLOVER", _P.VERTICAL_PULL, _M.LATS),
    _rule("PULL_UP", "STRAIGHT_ARM_PULLDOWN", _P.VERTICAL_PULL, _M.LATS),
    _rule("PUSH_UP", None, _P.HORIZONTAL_PUSH, _M.CHEST, _M.TRICEPS, _M.ANTERIOR_DELTOID),
    _rule("ROW", None, _P.HORIZONTAL_PULL, _M.UPPER_BACK, _M.LATS, _M.BICEPS, _M.POSTERIOR_DELTOID),
    _rule("ROW", "SEATED_CABLE_ROW", _P.HORIZONTAL_PULL, _M.UPPER_BACK, _M.LATS, _M.BICEPS, _M.POSTERIOR_DELTOID),
    _rule("SHOULDER_PRESS", None, _P.VERTICAL_PUSH, _M.ANTERIOR_DELTOID, _M.LATERAL_DELTOID, _M.TRICEPS),
    _rule("SHRUG", None, _P.SCAPULAR_ELEVATION, _M.UPPER_BACK),
    _rule("SHRUG", "UPRIGHT_ROW", _P.SHOULDER_ABDUCTION, _M.LATERAL_DELTOID, _M.UPPER_BACK),
    _rule("SIT_UP", None, _P.CORE, _M.CORE),
    _rule("SQUAT", None, _P.SQUAT, _M.QUADRICEPS, _M.GLUTES),
    _rule("SQUAT", "BARBELL_BACK_SQUAT", _P.SQUAT, _M.QUADRICEPS, _M.GLUTES),
    _rule("TRICEPS_EXTENSION", None, _P.ELBOW_EXTENSION, _M.TRICEPS),
    _rule("TRICEPS_EXTENSION", "BENCH_DIP", _P.ELBOW_EXTENSION, _M.TRICEPS, _M.CHEST, _M.ANTERIOR_DELTOID),
    _rule("TRICEPS_EXTENSION", "CABLE_OVERHEAD_TRICEPS_EXTENSION", _P.ELBOW_EXTENSION, _M.TRICEPS),
    _rule("TRICEPS_EXTENSION", "DUMBBELL_KICKBACK", _P.ELBOW_EXTENSION, _M.TRICEPS),
    _rule("TRICEPS_EXTENSION", "OVERHEAD_DUMBBELL_TRICEPS_EXTENSION", _P.ELBOW_EXTENSION, _M.TRICEPS),
    _rule("TRICEPS_EXTENSION", "TRICEPS_PRESSDOWN", _P.ELBOW_EXTENSION, _M.TRICEPS),
)

_RULES_BY_LABEL: Mapping[tuple[str, str | None], ExerciseRule] = MappingProxyType(
    {(rule.source_category, rule.source_name): rule for rule in EXERCISE_RULES}
)


def _is_unknown(value: str | None) -> bool:
    # Exactly derive_activity_review(): missing, or UNKNOWN after strip/upper.
    return value is None or value.strip().upper() == "UNKNOWN"


def classify_exercise(source_category: str | None, source_name: str | None) -> ExerciseClassification:
    """Classify one Garmin label; the key is Garmin's ``name or category`` as in normalization."""
    return _classify(source_category, source_name, source_name or source_category)


def classify_strength_set(strength_set: StrengthSet) -> ExerciseClassification:
    """Classify a stored set using its stored key, exactly as ``derive_activity_review`` does."""
    return _classify(
        strength_set.source_exercise_category,
        strength_set.source_exercise_name,
        strength_set.source_exercise_key,
    )


def _classify(source_category: str | None, source_name: str | None, source_key: str | None) -> ExerciseClassification:
    if _is_unknown(source_category) or _is_unknown(source_key):
        return ExerciseClassification(source_category, source_name, None, UnmappedReason.UNKNOWN_SOURCE_LABEL)
    rule = _RULES_BY_LABEL.get((source_category, source_name)) if source_category is not None else None
    if rule is None:
        return ExerciseClassification(source_category, source_name, None, UnmappedReason.NO_RULE)
    return ExerciseClassification(source_category, source_name, rule, None)


def label_origin(probability: float | None) -> LabelOrigin:
    if probability is None:
        return LabelOrigin.UNSPECIFIED
    if probability >= CONFIRMED_LABEL_PROBABILITY:
        return LabelOrigin.CONFIRMED
    return LabelOrigin.AUTO_DETECTED
