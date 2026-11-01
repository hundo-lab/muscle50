"""Rest Interval Advice v1: the recorded rest between two sets of the same exercise, next to the evidence.

**Advice only.** No rule, score, warning, recommendation, set count, load progression or Telegram reply
reads these values; they are computed on read for ``analytics snapshot`` and never stored.

The value is the recorded REST ``duration`` only, and only before a confirmed normal set (design decision
D1-A): heart-rate estimates depend on [design] constants and are never compared with the evidence. Every
``ACTIVE, REST, ACTIVE`` triple that is not counted is excluded for exactly one reason, and the counts are
always reported. Missing is not zero: a group without a counted rest has no median and no band.

Evidence IDs refer to docs/evidence/training-nutrition-evidence.md section 1 (REST-01..08); ``design``
marks a choice the evidence does not give. All arithmetic is in integer milliseconds.
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from enum import StrEnum

from muscle50.domain.activity import NormalizedActivity
from muscle50.domain.strength_set_timing import (
    REST_GROUP_EVIDENCE,
    SUSPECT_EVIDENCE,
    RestGroupName,
    is_checked,
    is_suspect,
    rest_group,
    rest_triples,
    set_duration_ms,
)

REST_ADVICE_VERSION = 1

# REST-01: Singer 2024's analysis categories (short <= 60 s, intermediate 60-120 s, long 120-180 s,
# very long >= 180 s). They are position labels only, not effect thresholds. 90 s is deliberately not an
# edge: it is not one of Singer's categories and the authors call a further benefit above 90 s
# "equivocal".
SHORT_MAX_MS = 60_000
LONG_MIN_MS = 120_000
VERY_LONG_MIN_MS = 180_000

BAND_EVIDENCE = ("REST-01",)
# REST-07 separates compound from accessory rest; [design] for using movement patterns for it.
GROUP_EVIDENCE = REST_GROUP_EVIDENCE
# [design]: the 1.0 s/rep threshold of strength set timing (MIN_MILLISECONDS_PER_REP) is reused.
SUSPECT_EXCLUSION_EVIDENCE = SUSPECT_EVIDENCE
# The fixed evidence lines, in printed order. REST-03 (strength sets, a different goal), REST-09 (adults
# over 65) and TEMPO-01 (repetition duration, not rest) are not printed.
NOTE_EVIDENCE = ("REST-01", "REST-02", "REST-04", "REST-05", "REST-06", "REST-07", "REST-08")
# REST-01 (a longer rest is one option) and REST-04 (matching volume load with short rests is another).
# REST-02 is not attached: it compares 1 vs 3 min in a whole-body routine, not by exercise type.
OPTION_EVIDENCE = ("REST-01", "REST-04")
# Display selection only ([design] on top of the REST-01 edge): the option line is shown for a group whose
# median is in the short band, and both options are always shown together, unranked.
OPTION_CODE = "rest_longer_or_match_volume_load"

GROUP_ORDER = (RestGroupName.COMPOUND, RestGroupName.ISOLATION, RestGroupName.UNCLASSIFIED)


class RestBand(StrEnum):
    SHORT = "short"
    INTERMEDIATE = "intermediate"
    LONG = "long"
    VERY_LONG = "very_long"


@dataclass(frozen=True)
class RestIntervalStat:
    median_seconds: float | None
    """None (unavailable) when nothing was counted, never 0."""
    rest_count: int
    band: RestBand | None
    """None exactly when ``median_seconds`` is None."""


@dataclass(frozen=True)
class ExerciseRestInterval:
    exercise_category: str | None
    exercise_name: str | None
    group: RestGroupName
    stat: RestIntervalStat


@dataclass(frozen=True)
class RestExclusions:
    """Why a triple was not counted; the first reason that applies, in this order."""

    label_change_or_unknown: int
    unchecked: int
    suspect_set: int
    missing_duration: int


@dataclass(frozen=True)
class RestIntervalAdvice:
    version: int
    compound: RestIntervalStat
    isolation: RestIntervalStat
    unclassified: RestIntervalStat
    excluded: RestExclusions
    exercises: tuple[ExerciseRestInterval, ...]
    """Only labels with at least one counted rest, in group order then by (category, name)."""
    option_groups: tuple[RestGroupName, ...]
    """Groups whose median is in the short band, in group order."""

    def group(self, name: RestGroupName) -> RestIntervalStat:
        return {
            RestGroupName.COMPOUND: self.compound,
            RestGroupName.ISOLATION: self.isolation,
            RestGroupName.UNCLASSIFIED: self.unclassified,
        }[name]


def rest_band(median_ms: float) -> RestBand:
    """Singer 2024's category of a median in milliseconds (REST-01); exactly 60 s is short."""
    if median_ms <= SHORT_MAX_MS:
        return RestBand.SHORT
    if median_ms < LONG_MIN_MS:
        return RestBand.INTERMEDIATE
    if median_ms < VERY_LONG_MIN_MS:
        return RestBand.LONG
    return RestBand.VERY_LONG


def summarize_rest_intervals(activities: Sequence[tuple[date, NormalizedActivity]]) -> RestIntervalAdvice | None:
    """Recorded rests between two sets of the same known label; None when the window has no triple.

    Each ``(ACTIVE, REST, ACTIVE)`` triple is excluded for the first reason that applies: a label change
    or UNKNOWN label, an unchecked following set, a suspect following set (< 1.0 s/rep [design], whether
    or not it was estimated), a missing REST duration. What is left is the REST duration. No heart rate
    is read, so the result does not depend on the set-timing estimates. Input order does not matter.
    """
    triple_count = 0
    excluded = {"label_change_or_unknown": 0, "unchecked": 0, "suspect_set": 0, "missing_duration": 0}
    by_group: dict[RestGroupName, list[int]] = {name: [] for name in GROUP_ORDER}
    by_label: dict[tuple[str | None, str | None], list[int]] = defaultdict(list)
    label_groups: dict[tuple[str | None, str | None], RestGroupName] = {}
    for _day, activity in activities:
        for before, rest, after in rest_triples(activity):
            triple_count += 1
            group = rest_group(before, after)
            rest_ms = set_duration_ms(rest)
            if group is None:
                excluded["label_change_or_unknown"] += 1
            elif not is_checked(after):
                excluded["unchecked"] += 1
            elif is_suspect(after):
                excluded["suspect_set"] += 1
            elif rest_ms is None:
                excluded["missing_duration"] += 1
            else:
                label = (after.source_exercise_category, after.source_exercise_name)
                by_group[group].append(rest_ms)
                by_label[label].append(rest_ms)
                label_groups[label] = group
    if triple_count == 0:
        return None
    exercises = sorted(
        (
            ExerciseRestInterval(category, name, label_groups[(category, name)], _stat(values))
            for (category, name), values in by_label.items()
        ),
        key=lambda item: (
            GROUP_ORDER.index(item.group),
            item.exercise_category or "",
            item.exercise_name or "",
            item.exercise_category is not None,
            item.exercise_name is not None,
        ),
    )
    stats = {name: _stat(values) for name, values in by_group.items()}
    return RestIntervalAdvice(
        version=REST_ADVICE_VERSION,
        compound=stats[RestGroupName.COMPOUND],
        isolation=stats[RestGroupName.ISOLATION],
        unclassified=stats[RestGroupName.UNCLASSIFIED],
        excluded=RestExclusions(**excluded),
        exercises=tuple(exercises),
        option_groups=tuple(name for name in GROUP_ORDER if stats[name].band is RestBand.SHORT),
    )


def _stat(values: Sequence[int]) -> RestIntervalStat:
    if not values:
        return RestIntervalStat(None, 0, None)
    median_ms = statistics.median(values)
    return RestIntervalStat(median_seconds=median_ms / 1000, rest_count=len(values), band=rest_band(median_ms))
