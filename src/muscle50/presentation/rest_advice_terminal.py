"""Text lines and the JSON payload of Rest Interval Advice v1 (advice only).

ASCII only; exercise labels are Garmin values and already ASCII. Every line carries an approved evidence
ID (REST-01..08) or ``design``; per-exercise lines and ``unavailable`` lines follow the group lines above
them. The evidence sentences are fixed: only the band names and the option lines depend on the medians.
Never printed: a score, a verdict, a ranking of the options, REST-09 or TEMPO-01, or anything about the
user's age. The payload is built by hand with a fixed key order (no ``dataclasses.asdict``).
"""

from __future__ import annotations

from typing import Any

from muscle50.domain.rest_interval_advice import (
    BAND_EVIDENCE,
    GROUP_EVIDENCE,
    GROUP_ORDER,
    LONG_MIN_MS,
    NOTE_EVIDENCE,
    OPTION_CODE,
    OPTION_EVIDENCE,
    SHORT_MAX_MS,
    SUSPECT_EXCLUSION_EVIDENCE,
    VERY_LONG_MIN_MS,
    ExerciseRestInterval,
    RestBand,
    RestIntervalAdvice,
    RestIntervalStat,
)
from muscle50.domain.strength_set_timing import MIN_MILLISECONDS_PER_REP

BASIS = "recorded_rest_before_normal_set"

BAND_TEXT = {
    RestBand.SHORT: f"short <= {SHORT_MAX_MS / 1000:.0f} s",
    RestBand.INTERMEDIATE: f"{SHORT_MAX_MS / 1000:.0f}-{LONG_MIN_MS / 1000:.0f} s",
    RestBand.LONG: f"{LONG_MIN_MS / 1000:.0f}-{VERY_LONG_MIN_MS / 1000:.0f} s",
    RestBand.VERY_LONG: f">= {VERY_LONG_MIN_MS / 1000:.0f} s",
}

HEADER_LINE = (
    "  Rest advice [advice only; used by no rule]: recorded REST between two sets of the same Garmin exercise "
    f"label; rests before a set under {MIN_MILLISECONDS_PER_REP / 1000:.1f} s/rep are excluded [design]"
)
# REST-01's condition column: the study population only, not the user.
EVIDENCE_HEADER_LINE = (
    "    evidence (fixed lines, the same for every median; REST-01 trials: 8 of 9 in adults 18-35, 1 in > 65; "
    "no trained-only analysis) [REST-01; design]:"
)
# One fixed sentence per approved row, in NOTE_EVIDENCE order (docs/evidence/training-nutrition-evidence.md
# section 1, rows as approved 2026-11-01).
EVIDENCE_LINES = {
    "REST-01": "rest > 60 s: small, uncertain hypertrophy benefit (credible intervals include 0), possibly through "
    "volume load; whether > 90 s adds more is equivocal",
    "REST-02": "3 min vs 1 min, trained men, whole-body routine, 8 weeks, n=21: larger squat and bench 1RM and "
    "front-thigh thickness gains with 3 min",
    "REST-04": "untrained adults, knee extension, 10 weeks, n=28: hypertrophy followed total volume load more than "
    "rest length (1 min with volume load matched to 3 min: 12.9 % vs 3 min: 13.1 %)",
    "REST-05": "acute, reps kept in later sets: the largest loss was between 1 min and 2-3 min, 2 vs 3 min differed "
    "trivially (lower body); heavy bench at 85 % 1RM kept reps over 4 sets only with 8 min",
    "REST-06": "self-selected vs fixed 75 s rest, trained men, 8 weeks, n=33: similar strength gains (6.8 % vs "
    "7.4 %); fixed rest was 37 % more time-efficient",
    "REST-07": "ACSM 2009, replaced by REST-08: strength, at least 2-3 min for heavy core lifts such as squat and "
    "bench, 1-2 min for assistance lifts; hypertrophy, 1-2 min for novice and intermediate",
    "REST-08": "ACSM 2026 sets no rest time: strength was unaffected by < 1 vs > 1 min rests (2 reviews, n=982); "
    "for hypertrophy the data could not decide (4 reviews, n=265)",
}
# The same sentence for every group; both options together, unranked (REST-01, REST-04).
OPTION_TEXT = (
    "no ranking: rest longer [REST-01] / keep short rests and match volume load (sets x reps x load) [REST-04]"
)


def rest_advice_lines(advice: RestIntervalAdvice) -> list[str]:
    lines = [HEADER_LINE]
    group_tag = f"[{'; '.join(BAND_EVIDENCE)}; groups {', '.join(GROUP_EVIDENCE)}]"
    for name in GROUP_ORDER:
        stat = advice.group(name)
        if stat.median_seconds is None or stat.band is None:
            lines.append(f"    {name}: unavailable ({stat.rest_count})")
        else:
            lines.append(
                f"    {name}: median {stat.median_seconds:.0f} s from {stat.rest_count} rests "
                f"(band {BAND_TEXT[stat.band]}) {group_tag}"
            )
    excluded = advice.excluded
    lines.append(
        f"    excluded: label change or UNKNOWN {excluded.label_change_or_unknown}, unchecked {excluded.unchecked}, "
        f"suspect set {excluded.suspect_set} [{', '.join(SUSPECT_EXCLUSION_EVIDENCE)}], "
        f"missing duration {excluded.missing_duration}"
    )
    lines.extend(_exercise_line(item) for item in advice.exercises)
    lines.append(EVIDENCE_HEADER_LINE)
    lines.extend(f"      [{key}] {EVIDENCE_LINES[key]}" for key in NOTE_EVIDENCE)
    lines.extend(
        f"    option for {name} (median in band {BAND_TEXT[RestBand.SHORT]}), {OPTION_TEXT}"
        for name in advice.option_groups
    )
    return lines


def rest_advice_payload(advice: RestIntervalAdvice) -> dict[str, Any]:
    return {
        "rest_advice_version": advice.version,
        "advice_only": True,
        "basis": BASIS,
        "band_edges_seconds": [SHORT_MAX_MS / 1000, LONG_MIN_MS / 1000, VERY_LONG_MIN_MS / 1000],
        "evidence": {
            "bands": list(BAND_EVIDENCE),
            "groups": list(GROUP_EVIDENCE),
            "suspect_exclusion": list(SUSPECT_EXCLUSION_EVIDENCE),
            "notes": list(NOTE_EVIDENCE),
            "option_short_rest": list(OPTION_EVIDENCE),
        },
        "groups": {name.value: _stat_payload(advice.group(name)) for name in GROUP_ORDER},
        "excluded": {
            "label_change_or_unknown": advice.excluded.label_change_or_unknown,
            "unchecked": advice.excluded.unchecked,
            "suspect_set": advice.excluded.suspect_set,
            "missing_duration": advice.excluded.missing_duration,
        },
        "exercises": [_exercise_payload(item) for item in advice.exercises],
        "options": [{"group": name.value, "code": OPTION_CODE} for name in advice.option_groups],
    }


def _exercise_line(item: ExerciseRestInterval) -> str:
    label = f"{item.exercise_category or 'no category'}/{item.exercise_name or '-'}"
    stat = item.stat
    assert stat.median_seconds is not None  # only labels with a counted rest are listed
    return f"    {label} ({item.group}): median {stat.median_seconds:.0f} s from {stat.rest_count} rests"


def _stat_payload(stat: RestIntervalStat) -> dict[str, Any]:
    return {
        "median_seconds": stat.median_seconds,
        "rest_count": stat.rest_count,
        "band": None if stat.band is None else stat.band.value,
    }


def _exercise_payload(item: ExerciseRestInterval) -> dict[str, Any]:
    return {
        "exercise_category": item.exercise_category,
        "exercise_name": item.exercise_name,
        "group": item.group.value,
        **_stat_payload(item.stat),
    }
