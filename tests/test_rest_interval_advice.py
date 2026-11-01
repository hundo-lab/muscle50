"""Rest Interval Advice v1: domain rules and the text/JSON presenter. Synthetic values only."""

from __future__ import annotations

import json
import re
from dataclasses import replace
from datetime import date
from typing import Any

import pytest
from strength_set_timing_builders import Active, Rest, build_session, strength_activity, timed_set

from muscle50.domain.activity import NormalizedActivity
from muscle50.domain.rest_interval_advice import (
    NOTE_EVIDENCE,
    OPTION_CODE,
    ExerciseRestInterval,
    RestBand,
    RestExclusions,
    RestIntervalAdvice,
    RestIntervalStat,
    rest_band,
    summarize_rest_intervals,
)
from muscle50.domain.strength_set_timing import RestGroupName, rest_group, rest_triples
from muscle50.presentation import rest_advice_terminal
from muscle50.presentation.rest_advice_terminal import rest_advice_lines, rest_advice_payload

DAY = date(2026, 3, 12)
_SQUAT = {"category": "SQUAT", "name": "BARBELL_BACK_SQUAT"}
_CURL = {"category": "CURL"}

BANNED = (
    "enough",
    "sufficient",
    "optimal",
    "must",
    "should",
    "too short",
    "too long",
    "stops",
    "no benefit",
    "ceiling",
    "plateau",
    "warning",
    "recommended rest",
)


def _normal(**overrides: Any) -> Active:
    fields: dict[str, Any] = {"reps": 10, "seconds": 20.0}
    fields.update(overrides)
    return Active(**fields)


def _activity(rows: list[Active | Rest], source_id: str = "9101") -> NormalizedActivity:
    return strength_activity(source_id, build_session(rows))


def _advice(rows: list[Active | Rest]) -> RestIntervalAdvice:
    advice = summarize_rest_intervals([(DAY, _activity(rows))])
    assert advice is not None
    return advice


def happy_rows() -> list[Active | Rest]:
    """The section 5 fixture: compound BENCH_PRESS and SQUAT, isolation CURL, one of each exclusion."""
    return [
        _normal(),  # BENCH_PRESS/None
        Rest(50.0),
        _normal(),
        Rest(56.0),
        _normal(),
        Rest(90.0),  # label change BENCH_PRESS -> SQUAT
        _normal(**_SQUAT),
        Rest(100.0),
        _normal(**_SQUAT),
        Rest(30.0),  # label change SQUAT -> CURL
        _normal(**_CURL),
        Rest(75.0),
        _normal(**_CURL),
        Rest(40.0),
        _normal(reps=None, **_CURL),  # unchecked
        Rest(40.0),
        _normal(reps=8, seconds=4.0, **_CURL),  # suspect (0.5 s/rep)
        Rest(None),
        _normal(**_CURL),  # missing REST duration
        Rest(65.0),
        _normal(**_CURL),
        Rest(40.0),
        _normal(reps=8, seconds=8.0, **_CURL),  # exactly 1.0 s/rep: normal, counted
    ]


# Bands (AC4)


@pytest.mark.parametrize(
    ("median_ms", "band"),
    [
        (0, RestBand.SHORT),
        (60_000, RestBand.SHORT),
        (60_000.5, RestBand.INTERMEDIATE),
        (60_001, RestBand.INTERMEDIATE),
        (90_000, RestBand.INTERMEDIATE),
        (119_999, RestBand.INTERMEDIATE),
        (120_000, RestBand.LONG),
        (179_999, RestBand.LONG),
        (180_000, RestBand.VERY_LONG),
        (600_000, RestBand.VERY_LONG),
    ],
)
def test_band_edges_follow_singer_categories(median_ms: float, band: RestBand) -> None:
    assert rest_band(median_ms) is band


def test_90_seconds_is_not_an_edge_or_a_band_name() -> None:
    payload = rest_advice_payload(_advice(happy_rows()))

    assert payload["band_edges_seconds"] == [60.0, 120.0, 180.0]
    assert 90.0 not in payload["band_edges_seconds"]
    assert all("90" not in text for text in rest_advice_terminal.BAND_TEXT.values())
    assert [band.value for band in RestBand] == ["short", "intermediate", "long", "very_long"]
    # 90 s appears only in the REST-01 "equivocal" clause.
    lines = rest_advice_lines(_advice(happy_rows()))
    assert [line for line in lines if "90" in line] == [
        "      [REST-01] " + rest_advice_terminal.EVIDENCE_LINES["REST-01"]
    ]
    assert "> 90 s adds more is equivocal" in rest_advice_terminal.EVIDENCE_LINES["REST-01"]


# Counting (AC1, AC3)


def test_happy_path_medians_and_counts_match_hand_calculation() -> None:
    advice = _advice(happy_rows())

    # compound: BENCH_PRESS 50, 56 and SQUAT 100 -> median 56; isolation: CURL 75, 65, 40 -> median 65.
    assert advice.compound == RestIntervalStat(56.0, 3, RestBand.SHORT)
    assert advice.isolation == RestIntervalStat(65.0, 3, RestBand.INTERMEDIATE)
    assert advice.unclassified == RestIntervalStat(None, 0, None)
    assert advice.excluded == RestExclusions(label_change_or_unknown=2, unchecked=1, suspect_set=1, missing_duration=1)
    assert advice.exercises == (
        ExerciseRestInterval("BENCH_PRESS", None, RestGroupName.COMPOUND, RestIntervalStat(53.0, 2, RestBand.SHORT)),
        ExerciseRestInterval(
            "SQUAT", "BARBELL_BACK_SQUAT", RestGroupName.COMPOUND, RestIntervalStat(100.0, 1, RestBand.INTERMEDIATE)
        ),
        ExerciseRestInterval("CURL", None, RestGroupName.ISOLATION, RestIntervalStat(65.0, 3, RestBand.INTERMEDIATE)),
    )
    assert advice.option_groups == (RestGroupName.COMPOUND,)
    assert advice.version == 1


def _excluded(rows: list[Active | Rest]) -> RestExclusions:
    advice = _advice(rows)
    assert advice.exercises == ()
    return advice.excluded


def test_label_change_wins_over_an_unchecked_following_set() -> None:
    assert _excluded([_normal(), Rest(40.0), _normal(reps=None, **_CURL)]) == RestExclusions(1, 0, 0, 0)


@pytest.mark.parametrize(
    "rows",
    [
        [_normal(category="UNKNOWN"), Rest(40.0), _normal(category="UNKNOWN")],
        [_normal(), Rest(40.0), _normal(category="UNKNOWN")],
        [_normal(category="unknown "), Rest(40.0), _normal()],
        [_normal(category=None), Rest(40.0), _normal(category=None)],
    ],
)
def test_unknown_label_on_either_side_is_a_label_exclusion(rows: list[Active | Rest]) -> None:
    assert _excluded(rows) == RestExclusions(1, 0, 0, 0)


@pytest.mark.parametrize(
    "after", [_normal(reps=None), _normal(reps=0), _normal(seconds=None)], ids=["no reps", "0 reps", "no time"]
)
def test_unchecked_wins_over_a_missing_rest_duration(after: Active) -> None:
    assert _excluded([_normal(), Rest(None), after]) == RestExclusions(0, 1, 0, 0)


def test_suspect_wins_over_a_missing_rest_duration() -> None:
    assert _excluded([_normal(), Rest(None), _normal(reps=8, seconds=4.0)]) == RestExclusions(0, 0, 1, 0)


def test_missing_rest_duration_is_excluded_not_zero() -> None:
    advice = _advice([_normal(), Rest(None), _normal()])

    assert advice.excluded == RestExclusions(0, 0, 0, 1)
    assert advice.compound == RestIntervalStat(None, 0, None)


def test_exactly_one_second_per_rep_counts_and_just_below_is_suspect() -> None:
    below = _advice([_normal(), Rest(40.0), _normal(reps=10, seconds=9.999)])
    exact = _advice([_normal(), Rest(40.0), _normal(reps=10, seconds=10.0)])

    assert below.excluded == RestExclusions(0, 0, 1, 0)
    assert below.compound.rest_count == 0
    assert exact.excluded == RestExclusions(0, 0, 0, 0)
    assert exact.compound == RestIntervalStat(40.0, 1, RestBand.SHORT)


def test_only_excluded_triples_still_give_an_empty_block() -> None:
    advice = _advice([_normal(), Rest(40.0), _normal(**_CURL), Rest(None), _normal(**_CURL)])

    for stat in (advice.compound, advice.isolation, advice.unclassified):
        assert stat == RestIntervalStat(None, 0, None)
    assert advice.excluded == RestExclusions(1, 0, 0, 1)
    assert (advice.exercises, advice.option_groups) == ((), ())
    lines = rest_advice_lines(advice)
    assert lines[1:4] == [
        "    compound: unavailable (0)",
        "    isolation: unavailable (0)",
        "    unclassified: unavailable (0)",
    ]
    assert not any(line.startswith("    option for") for line in lines)
    assert rest_advice_payload(advice)["options"] == []


@pytest.mark.parametrize(
    "rows",
    [
        [],
        [_normal(), Rest(40.0)],
        [Rest(40.0), _normal(), _normal()],
        [_normal(), Rest(40.0), Rest(40.0), _normal()],
        [_normal(), _normal(), _normal()],
    ],
    ids=["no sets", "active-rest", "rest-active-active", "rest-rest", "active-active"],
)
def test_no_active_rest_active_triple_gives_none(rows: list[Active | Rest]) -> None:
    assert summarize_rest_intervals([(DAY, _activity(rows))]) is None


def test_no_activities_gives_none() -> None:
    assert summarize_rest_intervals([]) is None


def test_a_triple_does_not_span_two_activities() -> None:
    first = _activity([_normal(), Rest(40.0)], "9101")
    second = _activity([_normal()], "9102")

    assert summarize_rest_intervals([(DAY, first), (DAY, second)]) is None


# The extracted set-timing helpers (D6-A)


def test_rest_group_follows_the_taxonomy_rule_of_the_label() -> None:
    def pair(**label: Any) -> tuple[Any, Any]:
        return timed_set(1, **label), timed_set(3, **label)

    assert rest_group(*pair(category="BENCH_PRESS")) is RestGroupName.COMPOUND
    assert rest_group(*pair(category="SQUAT", name="BARBELL_BACK_SQUAT")) is RestGroupName.COMPOUND
    assert rest_group(*pair(category="CURL")) is RestGroupName.ISOLATION
    # PULL_UP/WIDE_GRIP_PULL_UP has no taxonomy rule.
    assert rest_group(*pair(category="PULL_UP", name="WIDE_GRIP_PULL_UP")) is RestGroupName.UNCLASSIFIED
    assert rest_group(*pair(category="UNKNOWN")) is None
    assert rest_group(timed_set(1, category="BENCH_PRESS"), timed_set(3, category="CURL")) is None
    assert rest_group(timed_set(1, category="CURL"), timed_set(3, category="CURL", name="DUMBBELL_HAMMER_CURL")) is None


def test_rest_triples_use_sequence_order_not_storage_order() -> None:
    item = _activity([_normal(), Rest(40.0), _normal(), Rest(50.0), _normal()])
    shuffled = replace(item, strength_sets=tuple(reversed(item.strength_sets)))

    triples = rest_triples(shuffled)

    assert [tuple(row.sequence for row in triple) for triple in triples] == [(1, 2, 3), (3, 4, 5)]
    assert summarize_rest_intervals([(DAY, shuffled)]) == summarize_rest_intervals([(DAY, item)])


# Options (AC5)


def test_option_only_for_short_groups_with_the_same_sentence() -> None:
    advice = _advice(
        [
            _normal(),
            Rest(60.0),  # compound median exactly 60 s: short
            _normal(),
            Rest(30.0),
            _normal(**_CURL),
            Rest(45.0),  # isolation 45 s: short
            _normal(**_CURL),
            Rest(40.0),
            _normal(category="PULL_UP", name="WIDE_GRIP_PULL_UP"),
            Rest(61.0),  # unclassified 61 s: intermediate, no option
            _normal(category="PULL_UP", name="WIDE_GRIP_PULL_UP"),
        ]
    )

    assert advice.option_groups == (RestGroupName.COMPOUND, RestGroupName.ISOLATION)
    options = [line for line in rest_advice_lines(advice) if line.startswith("    option for ")]
    assert options == [
        "    option for compound (median in band short <= 60 s), no ranking: rest longer [REST-01] / keep short rests "
        "and match volume load (sets x reps x load) [REST-04]",
        "    option for isolation (median in band short <= 60 s), no ranking: rest longer [REST-01] / keep short rests "
        "and match volume load (sets x reps x load) [REST-04]",
    ]
    assert len({line.split(")", 1)[1] for line in options}) == 1
    assert all("REST-02" not in line for line in options)
    assert rest_advice_payload(advice)["options"] == [
        {"group": "compound", "code": OPTION_CODE},
        {"group": "isolation", "code": OPTION_CODE},
    ]
    assert OPTION_CODE == "rest_longer_or_match_volume_load"


def test_no_short_group_gives_no_option() -> None:
    advice = _advice([_normal(), Rest(61.0), _normal(), Rest(200.0), _normal(**_CURL), Rest(130.0), _normal(**_CURL)])

    assert advice.compound.band is RestBand.INTERMEDIATE
    assert advice.isolation.band is RestBand.LONG
    assert advice.option_groups == ()
    assert not any(line.startswith("    option for") for line in rest_advice_lines(advice))
    assert rest_advice_payload(advice)["options"] == []


def test_very_long_band_text() -> None:
    lines = rest_advice_lines(_advice([_normal(), Rest(180.0), _normal()]))

    assert lines[1] == "    compound: median 180 s from 1 rests (band >= 180 s) [REST-01; groups REST-07, design]"


# Determinism (AC10)


def test_activity_order_does_not_matter_and_exercises_are_sorted() -> None:
    curl = (date(2026, 3, 10), _activity([_normal(**_CURL), Rest(70.0), _normal(**_CURL)], "9001"))
    bench = (date(2026, 3, 12), _activity([_normal(), Rest(50.0), _normal()], "9002"))
    squat = (date(2026, 3, 11), _activity([_normal(**_SQUAT), Rest(110.0), _normal(**_SQUAT)], "9003"))
    pull = (date(2026, 3, 9), _activity([_normal(category="PULL_UP", name="WIDE_GRIP_PULL_UP")], "9004"))

    first = summarize_rest_intervals([curl, bench, squat, pull])
    second = summarize_rest_intervals([pull, squat, bench, curl])

    assert first == second
    assert first is not None
    assert [(item.exercise_category, item.exercise_name) for item in first.exercises] == [
        ("BENCH_PRESS", None),
        ("SQUAT", "BARBELL_BACK_SQUAT"),
        ("CURL", None),
    ]
    assert first.compound == RestIntervalStat(80.0, 2, RestBand.INTERMEDIATE)


# Presenter: exact text and payload (AC1, AC3, AC6, AC7, AC10)

EXPECTED_BLOCK_LINES = [
    "  Rest advice [advice only; used by no rule]: recorded REST between two sets of the same Garmin exercise label; "
    "rests before a set under 1.0 s/rep are excluded [design]",
    "    compound: median 56 s from 3 rests (band short <= 60 s) [REST-01; groups REST-07, design]",
    "    isolation: median 65 s from 3 rests (band 60-120 s) [REST-01; groups REST-07, design]",
    "    unclassified: unavailable (0)",
    "    excluded: label change or UNKNOWN 2, unchecked 1, suspect set 1 [design], missing duration 1",
    "    BENCH_PRESS/- (compound): median 53 s from 2 rests",
    "    SQUAT/BARBELL_BACK_SQUAT (compound): median 100 s from 1 rests",
    "    CURL/- (isolation): median 65 s from 3 rests",
    "    evidence (fixed lines, the same for every median; REST-01 trials: 8 of 9 in adults 18-35, 1 in > 65; "
    "no trained-only analysis) [REST-01; design]:",
    "      [REST-01] rest > 60 s: small, uncertain hypertrophy benefit (credible intervals include 0), possibly "
    "through volume load; whether > 90 s adds more is equivocal",
    "      [REST-02] 3 min vs 1 min, trained men, whole-body routine, 8 weeks, n=21: larger squat and bench 1RM and "
    "front-thigh thickness gains with 3 min",
    "      [REST-04] untrained adults, knee extension, 10 weeks, n=28: hypertrophy followed total volume load more "
    "than rest length (1 min with volume load matched to 3 min: 12.9 % vs 3 min: 13.1 %)",
    "      [REST-05] acute, reps kept in later sets: the largest loss was between 1 min and 2-3 min, 2 vs 3 min "
    "differed trivially (lower body); heavy bench at 85 % 1RM kept reps over 4 sets only with 8 min",
    "      [REST-06] self-selected vs fixed 75 s rest, trained men, 8 weeks, n=33: similar strength gains (6.8 % vs "
    "7.4 %); fixed rest was 37 % more time-efficient",
    "      [REST-07] ACSM 2009, replaced by REST-08: strength, at least 2-3 min for heavy core lifts such as squat "
    "and bench, 1-2 min for assistance lifts; hypertrophy, 1-2 min for novice and intermediate",
    "      [REST-08] ACSM 2026 sets no rest time: strength was unaffected by < 1 vs > 1 min rests (2 reviews, "
    "n=982); for hypertrophy the data could not decide (4 reviews, n=265)",
    "    option for compound (median in band short <= 60 s), no ranking: rest longer [REST-01] / keep short rests "
    "and match volume load (sets x reps x load) [REST-04]",
]

EXPECTED_PAYLOAD: dict[str, Any] = {
    "rest_advice_version": 1,
    "advice_only": True,
    "basis": "recorded_rest_before_normal_set",
    "band_edges_seconds": [60.0, 120.0, 180.0],
    "evidence": {
        "bands": ["REST-01"],
        "groups": ["REST-07", "design"],
        "suspect_exclusion": ["design"],
        "notes": ["REST-01", "REST-02", "REST-04", "REST-05", "REST-06", "REST-07", "REST-08"],
        "option_short_rest": ["REST-01", "REST-04"],
    },
    "groups": {
        "compound": {"median_seconds": 56.0, "rest_count": 3, "band": "short"},
        "isolation": {"median_seconds": 65.0, "rest_count": 3, "band": "intermediate"},
        "unclassified": {"median_seconds": None, "rest_count": 0, "band": None},
    },
    "excluded": {"label_change_or_unknown": 2, "unchecked": 1, "suspect_set": 1, "missing_duration": 1},
    "exercises": [
        {
            "exercise_category": "BENCH_PRESS",
            "exercise_name": None,
            "group": "compound",
            "median_seconds": 53.0,
            "rest_count": 2,
            "band": "short",
        },
        {
            "exercise_category": "SQUAT",
            "exercise_name": "BARBELL_BACK_SQUAT",
            "group": "compound",
            "median_seconds": 100.0,
            "rest_count": 1,
            "band": "intermediate",
        },
        {
            "exercise_category": "CURL",
            "exercise_name": None,
            "group": "isolation",
            "median_seconds": 65.0,
            "rest_count": 3,
            "band": "intermediate",
        },
    ],
    "options": [{"group": "compound", "code": "rest_longer_or_match_volume_load"}],
}


def test_text_lines_are_exact() -> None:
    assert rest_advice_lines(_advice(happy_rows())) == EXPECTED_BLOCK_LINES


def test_payload_is_exact_with_a_fixed_key_order() -> None:
    payload = rest_advice_payload(_advice(happy_rows()))

    assert payload == EXPECTED_PAYLOAD
    assert json.dumps(payload, indent=2) == json.dumps(EXPECTED_PAYLOAD, indent=2)
    assert list(payload["excluded"]) == ["label_change_or_unknown", "unchecked", "suspect_set", "missing_duration"]


def test_every_fixed_sentence_is_ascii() -> None:
    texts = [
        rest_advice_terminal.HEADER_LINE,
        rest_advice_terminal.EVIDENCE_HEADER_LINE,
        rest_advice_terminal.OPTION_TEXT,
        *rest_advice_terminal.EVIDENCE_LINES.values(),
        *rest_advice_terminal.BAND_TEXT.values(),
    ]
    assert all(text.isascii() for text in texts)
    assert list(rest_advice_terminal.EVIDENCE_LINES) == list(NOTE_EVIDENCE)


def banned_hits(text: str) -> list[str]:
    """Banned words, case-insensitive, on word boundaries; ``_`` counts as a space (snake_case codes)."""
    normalized = text.replace("_", " ").lower()
    return [word for word in BANNED if re.search(rf"\b{re.escape(word)}\b", normalized)]


def json_strings(value: object) -> list[str]:
    """Every key and string value in a JSON document."""
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [text for key, item in value.items() for text in (str(key), *json_strings(item))]
    if isinstance(value, list):
        return [text for item in value for text in json_strings(item)]
    return []


def json_keys(value: object) -> set[str]:
    if isinstance(value, dict):
        return {str(key) for key in value} | {key for item in value.values() for key in json_keys(item)}
    if isinstance(value, list):
        return {key for item in value for key in json_keys(item)}
    return set()


def test_banned_word_scan_uses_word_boundaries() -> None:
    assert banned_hits("SHOULDER_PRESS/DUMBBELL_SHOULDER_PRESS") == []
    assert banned_hits("too_short") == ["too short"]
    assert banned_hits("You SHOULD rest") == ["should"]
    assert banned_hits("mustard, enoughness") == []


def test_no_banned_word_in_text_json_or_constants() -> None:
    rows: list[Active | Rest] = [
        _normal(category="SHOULDER_PRESS", name="DUMBBELL_SHOULDER_PRESS"),
        Rest(50.0),
        _normal(category="SHOULDER_PRESS", name="DUMBBELL_SHOULDER_PRESS"),
        *happy_rows(),
    ]
    advice = _advice(rows)
    texts = [
        *rest_advice_lines(advice),
        *json_strings(rest_advice_payload(advice)),
        rest_advice_terminal.HEADER_LINE,
        rest_advice_terminal.EVIDENCE_HEADER_LINE,
        rest_advice_terminal.OPTION_TEXT,
        *rest_advice_terminal.EVIDENCE_LINES.values(),
    ]

    assert any("SHOULDER_PRESS" in text for text in texts)
    assert {text: banned_hits(text) for text in texts if banned_hits(text)} == {}


EVIDENCE_TAG = re.compile(r"\[REST-0[1-8]|design")


def evidence_tag_failures(lines: list[str]) -> list[str]:
    """Lines without REST-01..08 or design; exercise and unavailable lines follow the group lines."""
    return [
        line
        for line in lines
        if not EVIDENCE_TAG.search(line) and not line.endswith(" rests") and not line.endswith(": unavailable (0)")
    ]


def test_every_line_carries_an_approved_evidence_id_or_design() -> None:
    lines = rest_advice_lines(_advice(happy_rows()))
    text = "\n".join(lines)

    assert evidence_tag_failures(lines) == []
    assert set(re.findall(r"[A-Z]+-\d{2}", text)) == {f"REST-0{number}" for number in (1, 2, 4, 5, 6, 7, 8)}
    assert "REST-09" not in text
    assert "TEMPO-01" not in text


def test_no_score_grade_warning_or_verdict_key() -> None:
    payload = rest_advice_payload(_advice(happy_rows()))

    assert payload["advice_only"] is True
    assert [key for key in json_keys(payload) if re.search(r"score|grade|warning|level|verdict", key)] == []
