"""Telegram Goal Summary v1 (AC1-AC12): the `/daily` goal lines, copied from `recommendation.goal_mode`.

Inputs are real `recommend --json` documents of the Aerobic Guide scenario (`aerobic_builders`, a temporary
MUSCLE50_HOME, synthetic values only) placed into the `daily_2026-10-02.json` golden envelope, plus mutated
copies for the states the scenario does not reach. `daily`'s `recommendation` is exactly `recommend --json`
(`test_daily_embeds_the_recommend_document`).
"""

from __future__ import annotations

import builtins
import contextlib
import copy
import html
import io
import json
import os
import re
import urllib.request
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any

import aerobic_builders as aerobic
import pytest
import sync_coverage_builders as builders

import muscle50.cli as cli
from muscle50.application.telegram_bot import SummaryUnavailableError
from muscle50.cli import main
from muscle50.domain.aerobic_guide import plateau_options
from muscle50.domain.telegram_commands import ReplyKind
from muscle50.infrastructure.garmin.client import PythonGarminConnector
from muscle50.presentation.goal_terminal import _km
from muscle50.presentation.telegram_summary import _OPTION_EVIDENCE, TelegramSummaries, daily_summary, today_summary

EVIDENCE_DOC = Path(__file__).parents[1] / "docs" / "evidence" / "training-nutrition-evidence.md"
RECOMMEND = ("recommend", "--date", aerobic.AS_OF, "--json")
TAGGED = re.compile(r"\[(?:[A-Z]+-\d\d|design)[^\]]*\]")
EVIDENCE_ID = re.compile(r"\b[A-Z]+-\d\d\b")
FORBIDDEN_ENGLISH = ("stop", "ceiling", "limit", "upper", "max")
FORBIDDEN_KOREAN = ("상한", "최대", "최고", "한계", "한도", "제한", "멈", "그만", "충분", "목표")
VERDICT_WORDS = ("달성", "부족", "초과", "미달")
RANKING_WORDS = ("추천", "먼저", "가장", "권장", "낫", "약한", "우선")

# AC2: the cut scenario (plateau met) after the nutrition line, in this order.
CUT_BLOCK = [
    "목표: cut (내 설정) [design: user setting]",
    "체중 변화 11-06 -> 11-20: -0.05 %/주 [MAINT-05; design]",
    "  -> 내 목표 감량 0.3-0.5 %/주 밖 [design: user setting]",
    "골격근량: 내 하한 41 kg 아래 (InBody 11-20) [design: user setting]",
    "목표 진행: 체지방 18 %까지 -0.42 %/주 필요 (기한 2027-02-28), 실제 -0.05 %/주 "
    "[design: fat-free mass assumed constant]",
    "유산소(러닝·수영) 11-13..11-19: 200분 이상 (중강도 140 + 고강도 60) [EXL-03; design]",
    "  하한: intensity minutes 없는 활동 1개 빠짐 [design]",
    "  기준선: 150분 지침 최소(고강도면 75분) [EXL-03] · 300분 연구된 범위의 끝 [FATEX-02]",
    "러닝 길이 11-19: 12.5 km, 지난 30일 최장보다 25.0 % 김 [RUNPROG-03: 관찰 연구의 연관, 알림만]",
    "정체 확인: 조건 충족 (내 설정 3주, 0.3 %/주 미만 감량, InBody 구간 2개 이상) "
    "[design: user setting; PLAT-01, PLAT-02]",
    "  체중은 주 안에서 약 0.35 % 오르내림, 같은 기기·조건 InBody끼리 비교 [PLAT-02]",
    "  선택지, 순위 없음 (표시 순서) [PLAT-06]; 내 선호·지킬 수 있는 것도 정당한 기준 [FATEX-07]",
    "  a) 식사 기록이 빠짐없는지 확인 (빠진 끼니, 일반식, 주말) [PLAT-04]",
    "  b) 하루 100-150 kcal 덜 먹기 [design]; 결손은 약 500 kcal/일 이하, muscle50은 결손을 잴 수 없음 [PRO-04]",
    "  c) 섭취는 두고 활동 늘리기: 같은 결손이면 같은 지방 감소, 활동 뒤 더 먹으면 결손 일부가 상쇄될 수 "
    "있음(개인차 큼) [FATEX-05, FATEX-04]",
    "     러닝 길이·러닝/하체 3시간 간격 주의 [RUNPROG-03, CONC-04]",
    "  d) 1주 유지 휴식: 체중이 글리코겐·수분으로 오를 수 있고 기한이 1주 늦어짐 [PLAT-05]",
]
PLATEAU_HEAD = CUT_BLOCK[9]
BASELINE = CUT_BLOCK[7]


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(urllib.request, "urlopen", lambda *args, **kwargs: pytest.fail("no network in tests"))


def _cli(*argv: str) -> str:
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        code = main(list(argv))
    assert code == 0, argv
    return buffer.getvalue()


@pytest.fixture(scope="module")
def documents(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    """Real `recommend --json` of the 2026-11-20 scenario for a cut (plateau met), a maintain and a gain goal."""
    root = tmp_path_factory.mktemp("telegram-goal-summary") / "home"
    found: dict[str, Any] = {}
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("MUSCLE50_HOME", str(root))
        patch.setattr(cli, "_local_timezone", lambda day: builders.KST)
        patch.setattr(cli, "_today", lambda: date(2026, 11, 20))
        patch.setattr(PythonGarminConnector, "authenticate", lambda *args, **kwargs: pytest.fail("no Garmin"))
        aerobic.build_database(root)
        found["no_goal"] = json.loads(_cli(*RECOMMEND))
        for name, argv in (
            ("cut", aerobic.CUT_PLATEAU_GOAL),
            ("maintain", ("goal", "set", "--mode", "maintain")),
            ("gain", ("goal", "set", "--mode", "gain", "--min-smm", "41")),
        ):
            _cli(*argv)
            found[name] = json.loads(_cli(*RECOMMEND))
    return found


def _daily(recommendation: Any) -> dict[str, Any]:
    """The `daily --json` golden envelope with this recommendation (a deep copy)."""
    document: dict[str, Any] = json.loads(builders.golden("daily_2026-10-02.json"))
    document["recommendation"] = copy.deepcopy(recommendation)
    return document


def _body(document: Any) -> list[str]:
    return daily_summary(document).pre.split("\n")


def _block(document: Any) -> list[str]:
    """The goal lines: everything after the blank line that follows the nutrition line."""
    lines = _body(document)
    start = next(index for index, line in enumerate(lines) if line.startswith("목표: "))
    assert lines[start - 1] == "" and lines[start - 2].startswith("영양: ")
    return lines[start:]


def _cut_block(documents: dict[str, Any], mutate: Callable[[dict[str, Any]], None]) -> list[str]:
    document = _daily(documents["cut"])
    mutate(document["recommendation"]["goal_mode"])
    return _block(document)


def _summary_error(document: Any) -> str:
    with pytest.raises(SummaryUnavailableError) as raised:
        TelegramSummaries().summary(ReplyKind.DAILY_SUMMARY, document)
    return str(raised.value)


# --- AC2: the cut scenario, exact lines in order ------------------------------------------------------


def test_cut_daily_adds_the_exact_goal_lines_after_the_nutrition_line(documents: dict[str, Any]) -> None:
    report = documents["cut"]["goal_mode"]
    assert report["plateau"]["status"] == "met" and report["aerobic_minutes"]["status"] == "lower_bound"
    document = _daily(documents["cut"])

    assert _block(document) == CUT_BLOCK
    # The numbers are the JSON strings as they are; minutes `:g`, km the CLI's `_km`.
    change, progress = report["weight_change"], report["goal_progress"]
    aerobic_minutes, run = report["aerobic_minutes"], report["run_length"]["runs"][-1]
    assert CUT_BLOCK[1].endswith(f": {change['percent_per_week']} %/주 [MAINT-05; design]")
    assert f"{progress['required_percent_per_week']} %/주 필요" in CUT_BLOCK[4]
    assert f"실제 {progress['actual_percent_per_week']} %/주" in CUT_BLOCK[4]
    assert (
        f"{aerobic_minutes['total_minutes']:g}분 이상 (중강도 {aerobic_minutes['moderate_minutes']:g}" in CUT_BLOCK[5]
    )
    assert f"{_km(run['distance_meters'])} km" in CUT_BLOCK[8] and f"{run['increase_percent']} % 김" in CUT_BLOCK[8]
    assert f"약 {report['plateau']['noise']['within_week_weight_percent']} %" in CUT_BLOCK[10]
    # The UNKNOWN group and the last line stay outside `<pre>`, unchanged; one message.
    messages = TelegramSummaries().summary(ReplyKind.DAILY_SUMMARY, document)
    assert len(messages) == 1
    assert messages[0].split("</pre>")[0].endswith(CUT_BLOCK[-1])
    assert messages[0].endswith(" · 전체: <code>/today full</code>")


# --- AC1 and AC10: no goal, or a failed daily, gives the reply of before -----------------------------------


def test_without_goal_mode_the_daily_reply_is_unchanged(documents: dict[str, Any]) -> None:
    with_goal = daily_summary(_daily(documents["cut"]))
    stripped = _daily(documents["cut"])
    del stripped["recommendation"]["goal_mode"]
    without = daily_summary(stripped)

    shown = with_goal.pre.split("\n")
    before = without.pre.split("\n")
    assert before[-1].startswith("영양: ")
    assert shown[: len(before)] == before
    assert shown[len(before) :] == ["", *CUT_BLOCK]
    assert with_goal.rich == without.rich
    # A real no-goal document has no key at all, and the existing golden has none either.
    assert "goal_mode" not in documents["no_goal"]
    assert daily_summary(_daily(documents["no_goal"])).pre.split("\n")[-1].startswith("영양: ")
    assert "goal_mode" not in json.loads(builders.golden("daily_2026-10-02.json"))["recommendation"]


def test_a_failed_daily_with_goal_mode_has_no_goal_lines(documents: dict[str, Any]) -> None:
    def failed(recommendation: Any) -> list[str]:
        document = _daily(recommendation)
        stages = {stage["stage"]: stage for stage in document["stages"]}
        stages["recovery"].update(status="failed", error="synthetic recovery failure")
        document.update(ok=False, failed_stages=["recovery"])
        return TelegramSummaries().summary(ReplyKind.DAILY_SUMMARY, document)

    stripped = copy.deepcopy(documents["cut"])
    del stripped["goal_mode"]
    assert failed(documents["cut"]) == failed(stripped) == failed(None)
    assert "목표" not in "\n".join(failed(documents["cut"]))


# --- AC3: each status and flag gives its wording; null is `알 수 없음`, never 0 ------------------------------

Mutation = Callable[[dict[str, Any]], None]


def _unchanged(report: dict[str, Any]) -> None:
    del report  # the scenario as it is


def _sets(**changes: Any) -> Mutation:
    """`section__key=value` changes in a goal_mode document (`without` is the aerobic missing-minutes object)."""

    def mutate(report: dict[str, Any]) -> None:
        for name, value in changes.items():
            section, key = name.split("__")
            target = report["aerobic_minutes"]["without_intensity_minutes"] if section == "without" else report[section]
            target[key] = copy.deepcopy(value)

    return mutate


WEIGHT_UNKNOWN = _sets(
    weight_change__status="unknown",
    weight_change__from_date=None,
    weight_change__to_date=None,
    weight_change__percent_per_week=None,
    weight_change__flags=[],
    weight_change__reason="only one InBody weight",
)
AEROBIC_UNKNOWN = _sets(
    aerobic_minutes__status="unknown",
    aerobic_minutes__moderate_minutes=None,
    aerobic_minutes__vigorous_minutes=None,
    aerobic_minutes__total_minutes=None,
    without__activity_count=3,
)
AEROBIC_NONE = _sets(
    aerobic_minutes__status="none_stored",
    aerobic_minutes__moderate_minutes=None,
    aerobic_minutes__vigorous_minutes=None,
    aerobic_minutes__total_minutes=None,
    aerobic_minutes__activities=[],
    without__activity_count=0,
)
AEROBIC_KNOWN = _sets(aerobic_minutes__status="known", without__activity_count=0)
# Only vigorous minutes are stored: moderate is unknown (not 0) and the total is a lower bound.
AEROBIC_ONE_METRIC = _sets(
    aerobic_minutes__moderate_minutes=None,
    aerobic_minutes__vigorous_minutes=5.0,
    aerobic_minutes__total_minutes=5.0,
    without__activity_count=0,
    without__one_metric_only_count=1,
)
AEROBIC_BOTH_REASONS = _sets(without__activity_count=1, without__one_metric_only_count=2)
AEROBIC_HEAD = "유산소(러닝·수영) 11-13..11-19: "
TARGET_WEIGHT = _sets(goal__target_body_fat_percent=None, goal__target_weight_kg="75", goal_progress__assumption=None)
NULL_ACTUAL = _sets(goal_progress__actual_percent_per_week=None)


def _plateau(status: str, reason: str | None) -> Mutation:
    def mutate(report: dict[str, Any]) -> None:
        report["plateau"].update(status=status, reason=reason, options=[])

    return mutate


def _plateau_not_set(report: dict[str, Any]) -> None:
    report["plateau"].update(
        status="not_set",
        weeks=None,
        below_loss_percent_per_week=None,
        source=None,
        intervals=[],
        reason="goal set --plateau-weeks N was not given",
        options=[],
    )


STATE_CASES: list[tuple[str, Mutation, list[str]]] = [
    # weight_change and its flags
    ("weight_known_no_flag", _sets(weight_change__flags=[]), [CUT_BLOCK[1], CUT_BLOCK[3]]),
    (
        "weight_unknown",
        WEIGHT_UNKNOWN,
        ["체중 변화: 알 수 없음 (only one InBody weight) [MAINT-05; design]", CUT_BLOCK[3]],
    ),
    (
        "flag_faster_than_evidence",
        _sets(weight_change__flags=["faster_than_evidence"]),
        [CUT_BLOCK[1], "  -> 감량이 주 1.0 %보다 빠름: 근육 유지에 불리할 수 있음 [MAINT-05]", CUT_BLOCK[3]],
    ),
    ("flag_outside_user_target", _unchanged, CUT_BLOCK[1:4]),
    (
        "flags_in_json_order",
        _sets(weight_change__flags=["gaining", "outside_user_target"]),
        [CUT_BLOCK[1], "  -> 감량 중 체중 증가 [design]", CUT_BLOCK[2], CUT_BLOCK[3]],
    ),
    # smm_floor
    (
        "smm_at_or_above",
        _sets(smm_floor__status="at_or_above"),
        ["골격근량: 내 하한 41 kg 이상 (InBody 11-20) [design: user setting]"],
    ),
    ("smm_below", _unchanged, [CUT_BLOCK[3]]),
    (
        "smm_unknown",
        _sets(smm_floor__status="unknown", smm_floor__measurement_date=None),
        ["골격근량: 내 하한 41 kg 대비 알 수 없음 (InBody 골격근량 없음) [design: user setting]"],
    ),
    (
        "smm_not_set",
        _sets(smm_floor__status="not_set", smm_floor__measurement_date=None, smm_floor__floor_kg=None),
        ["골격근량 하한: 설정 안 함 [design: user setting]"],
    ),
    # goal_progress (the tag follows `assumption`)
    ("progress_known", _unchanged, [CUT_BLOCK[4]]),
    (
        "progress_known_without_actual",
        NULL_ACTUAL,
        [
            "목표 진행: 체지방 18 %까지 -0.42 %/주 필요 (기한 2027-02-28), 실제 알 수 없음 "
            "[design: fat-free mass assumed constant]"
        ],
    ),
    (
        "progress_target_weight",
        TARGET_WEIGHT,
        ["목표 진행: 체중 75 kg까지 -0.42 %/주 필요 (기한 2027-02-28), 실제 -0.05 %/주 [design]"],
    ),
    (
        "progress_reached",
        _sets(goal_progress__status="reached", goal_progress__required_percent_per_week=None),
        ["목표 진행: 체지방 18 % 도달 (InBody 11-20) [design: fat-free mass assumed constant]"],
    ),
    (
        "progress_deadline_passed",
        _sets(goal_progress__status="deadline_passed", goal_progress__reason="the deadline has passed"),
        ["목표 진행: 기한 2027-02-28 지남 [design: fat-free mass assumed constant]"],
    ),
    (
        "progress_not_set",
        _sets(goal_progress__status="not_set", goal_progress__assumption=None, goal_progress__reason="needs both"),
        ["목표 진행: 계산 안 함 (목표와 기한이 둘 다 있어야 함) [design]"],
    ),
    (
        "progress_unknown",
        _sets(goal_progress__status="unknown", goal_progress__reason="InBody data unavailable"),
        ["목표 진행: 알 수 없음 (InBody data unavailable) [design: fat-free mass assumed constant]"],
    ),
    # aerobic_minutes (the reference marks always follow, last)
    (
        "aerobic_known",
        AEROBIC_KNOWN,
        [f"{AEROBIC_HEAD}200분 (중강도 140 + 고강도 60) [EXL-03; design]", BASELINE, CUT_BLOCK[8]],
    ),
    ("aerobic_lower_bound", _unchanged, CUT_BLOCK[5:9]),
    (
        "aerobic_one_metric_only",
        AEROBIC_ONE_METRIC,
        [
            f"{AEROBIC_HEAD}5분 이상 (중강도 알 수 없음 + 고강도 5) [EXL-03; design]",
            "  하한: 중강도·고강도 중 하나만 있는 활동 1개 [design]",
            BASELINE,
        ],
    ),
    (
        "aerobic_both_reasons",
        AEROBIC_BOTH_REASONS,
        [
            CUT_BLOCK[5],
            "  하한: intensity minutes 없는 활동 1개 빠짐 · 중강도·고강도 중 하나만 있는 활동 2개 [design]",
            BASELINE,
        ],
    ),
    (
        "aerobic_unknown",
        AEROBIC_UNKNOWN,
        [f"{AEROBIC_HEAD}알 수 없음 (활동 3개 모두 intensity minutes 없음) [EXL-03; design]", BASELINE],
    ),
    (
        "aerobic_none_stored",
        AEROBIC_NONE,
        [f"{AEROBIC_HEAD}저장된 활동 없음 (동기화 안 됐을 수 있음, 0분이 아님) [EXL-03; design]", BASELINE],
    ),
    # plateau (null: see the maintain/gain test)
    ("plateau_met", _unchanged, CUT_BLOCK[9:]),
    (
        "plateau_not_met",
        _plateau("not_met", None),
        [
            "정체 확인: 조건 미충족 (내 설정 3주, 0.3 %/주 미만 감량, InBody 구간 2개 이상) "
            "[design: user setting; PLAT-01, PLAT-02]"
        ],
    ),
    (
        "plateau_insufficient",
        _plateau("insufficient_measurements", "2 weights cover 1 interval"),
        ["정체 확인: 판단 못 함, 정체 여부 모름 (2 weights cover 1 interval) [design: user setting; PLAT-02]"],
    ),
    (
        "plateau_unknown",
        _plateau("unknown", "InBody data unavailable"),
        ["정체 확인: 알 수 없음 (InBody data unavailable) [design: user setting]"],
    ),
    (
        "plateau_not_set",
        _plateau_not_set,
        ["정체 확인: 설정 안 함 (근거로 정한 기준 없음; goal set ... --plateau-weeks N) [design; PLAT-01]"],
    ),
]
STATE_IDS = [case[0] for case in STATE_CASES]
MUTATIONS = {name: mutate for name, mutate, _expected in STATE_CASES}


def _contains(block: list[str], expected: list[str]) -> bool:
    return any(block[index : index + len(expected)] == expected for index in range(len(block)))


@pytest.mark.parametrize(("mutate", "expected"), [case[1:] for case in STATE_CASES], ids=STATE_IDS)
def test_each_state_gives_its_wording(documents: dict[str, Any], mutate: Mutation, expected: list[str]) -> None:
    block = _cut_block(documents, mutate)
    assert _contains(block, expected), block
    # Every other section is the scenario's own (a state changes its section's lines only).
    assert block[0] == CUT_BLOCK[0] and block[-1].startswith(("정체 확인: ", "  d) "))


@pytest.mark.parametrize(
    ("mutate", "needle"),
    [
        (WEIGHT_UNKNOWN, "체중 변화: 알 수 없음"),
        (AEROBIC_UNKNOWN, f"{AEROBIC_HEAD}알 수 없음"),
        (AEROBIC_ONE_METRIC, "중강도 알 수 없음"),
        (NULL_ACTUAL, "실제 알 수 없음"),
        (_sets(smm_floor__status="unknown", smm_floor__measurement_date=None), "대비 알 수 없음"),
    ],
    ids=["weight", "aerobic", "one_metric", "actual", "smm"],
)
def test_null_values_read_as_unknown_never_zero(documents: dict[str, Any], mutate: Mutation, needle: str) -> None:
    line = next(line for line in _cut_block(documents, mutate) if needle in line)
    assert re.search(r"(?<![\d.])0(?![\d.])", line) is None, line


def test_insufficient_measurements_is_not_read_as_no_plateau(documents: dict[str, Any]) -> None:
    line = _cut_block(documents, _plateau("insufficient_measurements", "1 weight covers 0 intervals"))[-1]
    assert line.startswith("정체 확인: ")
    assert "조건 미충족" not in line and "정체 여부 모름" in line


# --- AC4: one run line per flagged run ----------------------------------------------------------------


def _runs(block: list[str]) -> list[str]:
    return [line for line in block if line.startswith("러닝 길이 ")]


def test_no_flagged_run_gives_no_run_line(documents: dict[str, Any]) -> None:
    def unflag(report: dict[str, Any]) -> None:
        statuses = ["within", "no_previous_run", "no_distance"]
        for run, status in zip(report["run_length"]["runs"], statuses, strict=False):
            run["status"] = status

    assert _runs(_cut_block(documents, unflag)) == []
    assert _runs(_cut_block(documents, _sets(run_length__runs=[]))) == []


def test_every_flagged_run_has_its_line_in_json_order(documents: dict[str, Any]) -> None:
    def two_flagged(report: dict[str, Any]) -> None:
        first = report["run_length"]["runs"][0]
        first.update(status="longer_than_threshold", distance_meters=11004.0, increase_percent="10.0")
        first.update(baseline_lower_bound=True, previous_without_distance=2)

    assert _runs(_cut_block(documents, two_flagged)) == [
        "러닝 길이 11-14: 11 km, 지난 30일 최장보다 10.0 % 김 (이전 러닝 2개 거리 없음, 최장이 더 길 수 있음) "
        "[RUNPROG-03: 관찰 연구의 연관, 알림만]",
        CUT_BLOCK[8],
    ]


# --- AC5: the plateau and its unranked options ---------------------------------------------------------


@pytest.mark.parametrize("mode", ["maintain", "gain"])
def test_maintain_and_gain_have_no_plateau_lines_and_no_flags(documents: dict[str, Any], mode: str) -> None:
    report = documents[mode]["goal_mode"]
    assert report["plateau"] is None and report["weight_change"]["flags"] == []
    block = _block(_daily(documents[mode]))
    assert block[0] == f"목표: {mode} (내 설정) [design: user setting]"
    assert block[-1].startswith("러닝 길이 ")  # the run line is the last section here
    assert not [line for line in block if line.startswith(("정체", "  선택지", "  a)", "  ->"))]


def test_options_follow_the_json_order_and_only_when_met(documents: dict[str, Any]) -> None:
    def reversed_options(report: dict[str, Any]) -> None:
        report["plateau"]["options"].reverse()

    block = _cut_block(documents, reversed_options)
    letters = [line[2:4] for line in block if re.match(r"  [a-d]\) ", line)]
    assert letters == ["d)", "c)", "b)", "a)"]
    assert "순위 없음" in CUT_BLOCK[11]
    assert not [line for line in _cut_block(documents, _plateau("not_met", None)) if re.match(r"  [a-d]\) ", line)]


def test_no_ranking_words_and_option_c_keeps_the_compensation_caveat(documents: dict[str, Any]) -> None:
    for line in CUT_BLOCK:
        for word in RANKING_WORDS:
            assert word not in line, (word, line)
    option_c = next(line for line in CUT_BLOCK if line.startswith("  c) "))
    assert "같은 지방 감소" in option_c and "상쇄" in option_c  # FATEX-05 and FATEX-04
    assert _block(_daily(documents["cut"])) == CUT_BLOCK


def test_the_option_table_is_the_domain_option_list() -> None:
    expected = {option.code: option.evidence for option in plateau_options()}
    assert list(_OPTION_EVIDENCE) == list(expected)
    assert expected == _OPTION_EVIDENCE


# --- AC6: the 150/300 marks are references, read from the JSON -------------------------------------------


def _aerobic_section(block: list[str]) -> list[str]:
    start = next(index for index, line in enumerate(block) if line.startswith("유산소("))
    end = next(index for index, line in enumerate(block) if line.startswith("  기준선: "))
    return block[start : end + 1]


@pytest.mark.parametrize(
    "mutate",
    [_unchanged, AEROBIC_KNOWN, AEROBIC_ONE_METRIC, AEROBIC_BOTH_REASONS, AEROBIC_UNKNOWN, AEROBIC_NONE],
    ids=["lower_bound", "known", "one_metric", "both_reasons", "unknown", "none_stored"],
)
def test_aerobic_and_reference_lines_make_no_ceiling_or_verdict_claim(
    documents: dict[str, Any], mutate: Mutation
) -> None:
    section = _aerobic_section(_cut_block(documents, mutate))
    assert section[-1] == BASELINE
    for line in section:
        for word in FORBIDDEN_ENGLISH:
            assert word not in line.lower(), (word, line)
        for word in (*FORBIDDEN_KOREAN, *VERDICT_WORDS):
            assert word not in line, (word, line)


def test_reference_minutes_and_tags_come_from_the_json(documents: dict[str, Any]) -> None:
    def changed(report: dict[str, Any]) -> None:
        guideline, studied = report["aerobic_minutes"]["reference_minutes_per_week"]
        guideline["minutes"] = 151
        studied.update(minutes=301, evidence=["FATEX-02", "design"])

    assert _aerobic_section(_cut_block(documents, changed))[-1] == (
        "  기준선: 151분 지침 최소(고강도면 75분) [EXL-03] · 301분 연구된 범위의 끝 [FATEX-02, design]"
    )


# --- AC7 and AC8: every line tagged with a known ID; no measured kg -----------------------------------------


def _every_block(documents: dict[str, Any]) -> list[list[str]]:
    blocks = [_cut_block(documents, mutate) for mutate in MUTATIONS.values()]
    return [*blocks, _block(_daily(documents["maintain"])), _block(_daily(documents["gain"]))]


def test_every_new_line_carries_a_known_evidence_tag(documents: dict[str, Any]) -> None:
    rows = set(re.findall(r"^\| ([A-Z]+-\d\d) \|", EVIDENCE_DOC.read_text(encoding="utf-8"), re.MULTILINE))
    used: set[str] = set()
    for block in _every_block(documents):
        for line in block:
            tags = TAGGED.findall(line)
            assert tags, line
            used.update(identifier for tag in tags for identifier in EVIDENCE_ID.findall(tag))
    assert used <= rows, used - rows
    assert used == {
        "MAINT-05",
        "EXL-03",
        "FATEX-02",
        "RUNPROG-03",
        "PLAT-01",
        "PLAT-02",
        "PLAT-06",
        "FATEX-07",
        "PLAT-04",
        "PRO-04",
        "FATEX-05",
        "FATEX-04",
        "CONC-04",
        "PLAT-05",
    }


def test_no_measured_kg_only_the_users_own_settings(documents: dict[str, Any]) -> None:
    for name, mutate in (("cut", _unchanged), ("target_weight", TARGET_WEIGHT)):
        document = _daily(documents["cut"])
        mutate(document["recommendation"]["goal_mode"])
        goal = document["recommendation"]["goal_mode"]["goal"]
        settings = {goal["min_skeletal_muscle_mass_kg"], goal["target_weight_kg"]} - {None}
        text = "\n".join(_block(document))
        for measured in aerobic.MEASURED_TEXTS:
            assert measured not in text, (name, measured)
        values = re.findall(r"(\S+) kg\b", text)
        assert values and set(values) <= settings, (name, values)


# --- AC9: an unknown value or a wrong type is the fallback reply, never a dropped line ----------------------


def _option(report: dict[str, Any], code: str) -> dict[str, Any]:
    return next(option for option in report["plateau"]["options"] if option["code"] == code)


def _extra_option_id(report: dict[str, Any]) -> None:
    _option(report, "check_meal_logging")["evidence"].append("PLAT-02")


def _reordered_option_ids(report: dict[str, Any]) -> None:
    _option(report, "keep_intake_add_activity")["evidence"].reverse()


def _measurable_deficit(report: dict[str, Any]) -> None:
    _option(report, "eat_less")["deficit_measurable"] = True


def _unknown_option(report: dict[str, Any]) -> None:
    _option(report, "maintenance_week")["code"] = "refeed_days"


def _unknown_run_status(report: dict[str, Any]) -> None:
    report["run_length"]["runs"][0]["status"] = "much_longer"


def _unknown_meaning(report: dict[str, Any]) -> None:
    report["aerobic_minutes"]["reference_minutes_per_week"][1]["meaning"] = "upper_limit"


def _options_when_not_met(report: dict[str, Any]) -> None:
    report["plateau"]["status"] = "not_met"


def _version_2(report: dict[str, Any]) -> None:
    report["goal_mode_version"] = 2


SHAPE_ERRORS: list[tuple[str, Mutation, str]] = [
    ("goal_mode_version_2", _version_2, "ValueError"),
    ("unknown_mode", _sets(goal__mode="bulk"), "ValueError"),
    ("unknown_weight_status", _sets(weight_change__status="estimated"), "ValueError"),
    ("unknown_flag", _sets(weight_change__flags=["too_slow"]), "ValueError"),
    ("numeric_percent", _sets(weight_change__percent_per_week=-0.05), "TypeError"),
    ("unknown_smm_status", _sets(smm_floor__status="close"), "ValueError"),
    ("unknown_progress_status", _sets(goal_progress__status="on_track"), "ValueError"),
    ("unknown_aerobic_status", _sets(aerobic_minutes__status="partial"), "ValueError"),
    ("unknown_activity_type", _sets(aerobic_minutes__activity_types=["running", "cycling"]), "ValueError"),
    ("string_minutes", _sets(aerobic_minutes__total_minutes="200"), "TypeError"),
    ("lower_bound_without_reason", _sets(without__activity_count=0), "ValueError"),
    ("unknown_meaning", _unknown_meaning, "ValueError"),
    ("unknown_run_status", _unknown_run_status, "ValueError"),
    ("unknown_plateau_status", _plateau("stalled", None), "ValueError"),
    ("unknown_option_code", _unknown_option, "ValueError"),
    ("extra_option_id", _extra_option_id, "ValueError"),
    ("reordered_option_ids", _reordered_option_ids, "ValueError"),
    ("deficit_measurable", _measurable_deficit, "ValueError"),
    ("options_when_not_met", _options_when_not_met, "ValueError"),
    ("other_choice_evidence", _sets(plateau__choice_evidence=["PLAT-06"]), "ValueError"),
]


@pytest.mark.parametrize(("mutate", "error"), [case[1:] for case in SHAPE_ERRORS], ids=[c[0] for c in SHAPE_ERRORS])
def test_unexpected_goal_mode_is_a_summary_error(documents: dict[str, Any], mutate: Mutation, error: str) -> None:
    document = _daily(documents["cut"])
    mutate(document["recommendation"]["goal_mode"])
    assert _summary_error(document) == error


def test_a_null_or_non_object_goal_mode_is_a_summary_error(documents: dict[str, Any]) -> None:
    values: tuple[Any, ...] = (None, [], "cut")
    for value in values:
        document = _daily(documents["cut"])
        document["recommendation"]["goal_mode"] = value
        assert _summary_error(document) == "TypeError"


# --- AC11: /today, the coach's fallback input and a real `daily --json` -----------------------------------


def test_today_summary_ignores_goal_mode(documents: dict[str, Any]) -> None:
    stripped = copy.deepcopy(documents["cut"])
    del stripped["goal_mode"]
    summaries = TelegramSummaries()
    with_goal = summaries.summary(ReplyKind.TODAY_SUMMARY, documents["cut"])
    assert with_goal == summaries.summary(ReplyKind.TODAY_SUMMARY, stripped)
    assert today_summary(documents["cut"]) == today_summary(stripped)
    assert "목표: " not in "\n".join(with_goal)


def test_a_real_daily_json_with_a_goal_is_summarized(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("MUSCLE50_HOME", str(tmp_path / "home"))
    monkeypatch.setattr(cli, "_local_timezone", lambda day: builders.KST)
    monkeypatch.setattr(cli, "_today", lambda: builders.DAILY_TODAY)
    garmin = builders.daily_account()
    monkeypatch.setattr(PythonGarminConnector, "authenticate", lambda *args, **kwargs: garmin)
    assert main(list(aerobic.CUT_PLATEAU_GOAL)) == 0
    capsys.readouterr()
    assert main(["daily", "--json"]) == 0
    document = json.loads(capsys.readouterr().out)
    assert document["ok"] is True and "goal_mode" in document["recommendation"]

    messages = TelegramSummaries().summary(ReplyKind.DAILY_SUMMARY, document)
    block = _block(document)
    assert block[0] == "목표: cut (내 설정) [design: user setting]"
    # No InBody data in this account: named states, never a 0.
    assert block[1].startswith("체중 변화: 알 수 없음 (")
    assert block[-1].startswith("정체 확인: 알 수 없음 (") or block[-1].startswith("정체 확인: 판단 못 함")
    assert "\n".join(block) in html.unescape(messages[0])


# --- AC12: deterministic, and no clock, environment or file ------------------------------------------------


def test_the_summary_is_deterministic_and_reads_nothing(documents: dict[str, Any]) -> None:
    document = _daily(documents["cut"])
    first = TelegramSummaries().summary(ReplyKind.DAILY_SUMMARY, document)
    assert TelegramSummaries().summary(ReplyKind.DAILY_SUMMARY, _daily(documents["cut"])) == first

    def refuse(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("the summary must not read files or the environment")

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(builtins, "open", refuse)
        patch.setattr(os.environ, "get", refuse)
        again = TelegramSummaries().summary(ReplyKind.DAILY_SUMMARY, document)
    assert again == first
