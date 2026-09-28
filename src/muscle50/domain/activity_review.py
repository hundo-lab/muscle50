"""Structured review signals derived from canonical activity data."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from muscle50.domain.activity import NormalizedActivity


class ActivityReviewReasonCode(StrEnum):
    UNKNOWN_EXERCISE_CLASSIFICATION = "unknown_exercise_classification"


@dataclass(frozen=True)
class ActivityReviewReason:
    code: ActivityReviewReasonCode
    set_sequences: tuple[int, ...]


@dataclass(frozen=True)
class ActivityReviewState:
    required: bool
    reasons: tuple[ActivityReviewReason, ...]


def derive_activity_review(activity: NormalizedActivity) -> ActivityReviewState:
    """Derive review needs without persisting duplicate state or guessing classifications."""
    unknown_sequences = tuple(
        item.sequence
        for item in activity.strength_sets
        if item.set_type == "ACTIVE"
        and (
            item.source_exercise_key is None
            or item.source_exercise_key.strip().upper() == "UNKNOWN"
            or item.source_exercise_category is None
            or item.source_exercise_category.strip().upper() == "UNKNOWN"
        )
    )
    reasons = (
        (
            ActivityReviewReason(
                code=ActivityReviewReasonCode.UNKNOWN_EXERCISE_CLASSIFICATION,
                set_sequences=unknown_sequences,
            ),
        )
        if unknown_sequences
        else ()
    )
    return ActivityReviewState(required=bool(reasons), reasons=reasons)
