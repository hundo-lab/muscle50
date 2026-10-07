"""Telegram Mobile Replies v1.1: the pure summaries of the CLI JSON (docs/specs/telegram-mobile.md).

Inputs are the existing CLI goldens (`tests/fixtures/sync_coverage_golden/`) and mutated copies.
Expected lines are built here from the JSON fields with f-strings, never by calling the summarizer,
so every number, weight, label and state is checked against its JSON source (AC1). Covers the
caution markers and `알 수 없음` (AC3), the `/daily` failure layout (AC4), the UNKNOWN section and
`/unknown` (AC5), determinism (AC7), and the message packing. Synthetic values only; no I/O.
"""

from __future__ import annotations

import copy
import html
import json
import re
import urllib.request
from datetime import date
from typing import Any

import pytest
import sync_coverage_builders as builders

from muscle50.application.activity_unknown_sets import ActivityUnknownSets
from muscle50.application.telegram_bot import SummaryUnavailableError
from muscle50.domain.telegram_commands import ReplyKind
from muscle50.presentation.telegram_format import (
    TELEGRAM_MESSAGE_LIMIT,
    BotReply,
    Code,
    Link,
    reply_messages,
    telegram_messages,
    utf16_units,
)
from muscle50.presentation.telegram_summary import (
    TelegramSummaries,
    daily_summary,
    refresh_reply,
    status_summary,
    today_summary,
    unknown_list,
)

GARMIN = "https://connect.garmin.com/modern/activity/"
OTHER_NOTICES_EXCLUDED = {"strength_unknown_exercise", "recovery_row_partial", "recovery_row_missing"}


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(urllib.request, "urlopen", lambda *args, **kwargs: pytest.fail("no network in tests"))


def _golden(name: str) -> Any:
    return json.loads(builders.golden(name))


def _recommend() -> Any:
    return _golden("recommend_2026-03-16.json")


def _plain(messages: list[str]) -> str:
    """The text a reader sees: tags removed, entities unescaped, messages joined by a newline."""
    stripped = [re.sub(r'</?pre>|</?code>|<a href="[^"]*">|</a>', "", message) for message in messages]
    return html.unescape("\n".join(stripped))


def _lines(reply: BotReply) -> list[str]:
    return reply.plain_text().split("\n")


def _observation(document: Any, field: str) -> Any:
    return next(item["value"] for item in document["recovery"]["observations"] if item["field"] == field)


def _other_notices(document: Any) -> int:
    return sum(1 for notice in document["notices"] if notice["code"] not in OTHER_NOTICES_EXCLUDED)


def _notice(activity_id: str, local_date: str, count: int) -> dict[str, Any]:
    return {
        "source_activity_id": activity_id,
        "local_date": local_date,
        "unknown_set_count": count,
        "set_sequences": list(range(1, count + 1)),
        "action": f"set the exercise in Garmin Connect, then run: muscle50 garmin refresh {activity_id}",
    }


# --- AC1: goldens, expected values built from the JSON -------------------------------------------------


def test_today_summary_of_the_recommend_golden_matches_its_json() -> None:
    document = _recommend()
    strength = document["strength"]
    exercise = strength["exercises"][0]
    progression = exercise["progression"]
    goal = document["swimming"]["goal"]
    notice = strength["unknown_notices"][0]
    # The branches this golden takes (so the expected lines below are the right ones).
    assert document["recovery"]["level"] == strength["adjustment_level"] == "normal"
    assert document["data_freshness"]["requested_date_recovery_row"] is True
    assert document["data_freshness"]["requested_date_sleep_recorded"] is False
    assert progression["load_confidence"] == "normal" and progression["load_kg"] is not None
    assert document["nutrition"]["availability"] == "no_targets_configured"
    assert len(strength["exercises"]) == 1 and len(strength["unknown_notices"]) == 1

    reply = today_summary(document)

    assert _lines(reply) == [
        f"오늘 추천 {document['as_of'][5:]}",
        "",
        f"근력: {strength['focus']} · 약 {strength['estimated_minutes']}분 · {strength['working_sets']}세트",
        f" 1. {exercise['label']} {exercise['sets']}x{progression['target_reps']} @ {progression['load_kg']:g} kg",
        f"회복: {document['recovery']['level']} (readiness {_observation(document, 'training_readiness_level')} "
        f"{_observation(document, 'training_readiness_score')}, HRV {_observation(document, 'hrv_status')}, "
        "오늘 수면 기록 없음)",
        f"수영: {goal['session_type']} 약 {goal['total_meters']:g} m "
        f"(마지막 수영 {document['swimming']['baseline']['days_since_last_swim']}일 전) "
        f"· 주의 {len(goal['cautions'])}건",
        "영양: 목표 없음",
        "확인 필요: Garmin UNKNOWN 세트",
        f"• {notice['local_date'][5:]} 근력 {notice['unknown_set_count']}세트: {GARMIN}{notice['source_activity_id']}",
        f"  고친 뒤: /refresh {notice['source_activity_id']}",
        f"기타 알림 {_other_notices(document)}건 · 전체: /today full",
    ]
    activity_id = notice["source_activity_id"]
    messages = TelegramSummaries().summary(ReplyKind.TODAY_SUMMARY, document)
    assert len(messages) == 1
    assert messages[0].startswith("<pre>오늘 추천 03-16\n")
    assert f'<a href="{GARMIN}{activity_id}">{GARMIN}{activity_id}</a>' in messages[0]
    assert f"<code>/refresh {activity_id}</code>" in messages[0]
    assert messages[0].endswith(" · 전체: <code>/today full</code>")
    assert _plain(messages) == reply.plain_text()


def test_today_summary_of_the_targets_golden_says_no_meals_logged_not_zero() -> None:
    document = _golden("recommend_2026-03-16_targets.json")
    assert document["nutrition"]["availability"] == "no_intake_logged"
    assert _lines(today_summary(document))[6] == "영양: 오늘 기록 없음 (0 kcal이 아님)"


def test_daily_summary_of_the_daily_golden_matches_its_json() -> None:
    document = _golden("daily_2026-10-02.json")
    recommendation = document["recommendation"]
    strength = recommendation["strength"]
    exercise = strength["exercises"][0]
    progression = exercise["progression"]
    goal = recommendation["swimming"]["goal"]
    recovered = [item for item in document["recovery"]["outcomes"] if item["status"] in ("created", "updated")]
    assert document["ok"] is True and not strength["unknown_notices"]
    assert recommendation["swimming"]["baseline"]["days_since_last_swim"] is None
    assert recommendation["data_freshness"]["requested_date_sleep_recorded"] is True
    assert progression["load_confidence"] == "normal" and progression["load_kg"] is not None
    readiness = _observation(recommendation, "training_readiness_level")
    hrv = _observation(recommendation, "hrv_status")
    assert readiness is None and hrv is None
    sleep = _observation(recommendation, "sleep_seconds")

    assert _lines(daily_summary(document)) == [
        f"daily {document['as_of'][5:]}: 동기화 완료 (새 운동 {document['activities']['inserted']}, "
        f"회복 {len(recovered)}일 갱신)",
        "",
        f"근력: {strength['focus']} · 약 {strength['estimated_minutes']}분 · {strength['working_sets']}세트",
        f" 1. {exercise['label']} {exercise['sets']}x{progression['target_reps']} @ {progression['load_kg']:g} kg",
        f"회복: {recommendation['recovery']['level']} (readiness 알 수 없음, HRV 알 수 없음, "
        f"수면 {sleep // 3600:02d}:{sleep % 3600 // 60:02d}:{sleep % 60:02d})",
        f"수영: {goal['session_type']} 약 {goal['total_meters']:g} m (최근 28일 수영 기록 없음) · "
        f"주의 {len(goal['cautions'])}건",
        "영양: 목표 없음",
        f"기타 알림 {_other_notices(recommendation)}건 · 전체: /today full",
    ]


def test_unknown_list_of_the_recommend_golden_lists_every_set_sequence() -> None:
    document = _recommend()
    notice = document["strength"]["unknown_notices"][0]
    sequences = ", ".join(str(item) for item in notice["set_sequences"])
    assert _lines(unknown_list(document)) == [
        "Garmin UNKNOWN 세트가 있는 운동 1개 (최근 14일, 오늘 운동 제외)",
        f"• {notice['local_date'][5:]} 근력 {notice['unknown_set_count']}세트 (세트 {sequences}): "
        f"{GARMIN}{notice['source_activity_id']}",
        f"  고친 뒤: /refresh {notice['source_activity_id']}",
        "Garmin Connect에서 운동 이름을 고친 뒤 /refresh로 다시 받습니다.",
    ]


# --- AC3: caution markers and missing values -------------------------------------------------------------


def _progression(document: Any) -> Any:
    return document["strength"]["exercises"][0]["progression"]


def _exercise_line(document: Any) -> str:
    return next(line for line in _lines(today_summary(document)) if line.startswith(" 1. "))


@pytest.mark.parametrize(
    ("same_load_evidence", "caution"), [(True, " (무게 불확실)"), (False, " (무게 불확실, 지난 무게 확인)")]
)
def test_low_load_confidence_is_never_shown_as_exact(same_load_evidence: bool, caution: str) -> None:
    document = _recommend()
    _progression(document).update(load_confidence="low", same_load_evidence=same_load_evidence)
    assert _exercise_line(document) == f" 1. BENCH_PRESS/- 3x11 @ ~50 kg{caution}"


@pytest.mark.parametrize(
    ("changes", "load"),
    [
        (
            {"load_kg": None, "load_increase_from_kg": 50.0, "load_step": "smallest_available_direction_unknown"},
            " @ 50 kg에서 한 단계 (보조인지 추가 무게인지 확인)",
        ),
        (
            {"load_kg": None, "load_increase_from_kg": 50.0, "load_step": "smallest_available"},
            " @ 50 kg에서 다음 단계 위",
        ),
        ({"load_kg": None, "load_increase_from_kg": None}, " (무게 목표 없음)"),
        ({"load_kg": -0.0}, " @ 0 kg"),  # a recorded 0 kg load (body weight) is a value, shown as the CLI shows it
        ({"target_reps": None}, " @ 50 kg"),
        (
            {"action": "establish_baseline", "load_kg": None, "load_confidence": "low"},
            " (무게 직접 선택: 비교 기록 없음)",
        ),
    ],
)
def test_exercise_load_mirrors_the_cli_prescription(changes: dict[str, Any], load: str) -> None:
    document = _recommend()
    _progression(document).update(changes)
    reps = "5-12" if changes.get("target_reps", 11) is None else "11"
    assert _exercise_line(document) == f" 1. BENCH_PRESS/- 3x{reps}{load}"


def _caution_document(level: str, *, adjustment: str | None = None) -> Any:
    document = _recommend()
    document["recovery"]["level"] = level
    document["strength"]["adjustment_level"] = adjustment if adjustment is not None else level
    return document


def _fire(document: Any, field: str, value: Any, level: str) -> None:
    item = next(item for item in document["recovery"]["observations"] if item["field"] == field)
    item.update(value=value, fired_level=level, rule="synthetic rule")


def test_non_normal_recovery_level_is_the_first_line_after_the_header() -> None:
    hold = _caution_document("hold")
    _fire(hold, "hrv_status", "LOW", "hold")
    assert _lines(today_summary(hold))[:3] == ["오늘 추천 03-16", "주의: 회복 hold - hrv_status LOW", ""]
    assert _lines(today_summary(hold))[5].startswith("회복: hold (readiness MODERATE 60, HRV LOW, ")

    reduce = _caution_document("reduce")
    _fire(reduce, "sleep_seconds", 14400, "reduce")
    _fire(reduce, "training_readiness_level", "LOW", "reduce")
    assert (
        _lines(today_summary(reduce))[1] == "주의: 회복 reduce - sleep_seconds 04:00:00, training_readiness_level LOW"
    )

    carried = _caution_document("hold")
    carried["recovery"]["lookback"]["carried_level"] = "hold"
    assert _lines(today_summary(carried))[1] == "주의: 회복 hold - 이전 아침 기록으로 hold 유지"

    without_reason = _caution_document("hold")
    assert _lines(today_summary(without_reason))[1] == "주의: 회복 hold"
    without_lookback = _caution_document("hold")
    without_lookback["recovery"]["lookback"] = None
    assert _lines(today_summary(without_lookback))[1] == "주의: 회복 hold"


def test_session_adjustment_from_a_non_recovery_rule_is_shown() -> None:
    raised = _caution_document("normal", adjustment="reduce")
    assert _lines(today_summary(raised))[:3] == ["오늘 추천 03-16", "주의: 세션 조정 reduce (회복이 아닌 규칙)", ""]
    both = _caution_document("hold", adjustment="reduce")
    _fire(both, "hrv_status", "LOW", "hold")
    assert _lines(today_summary(both))[1:4] == [
        "주의: 회복 hold - hrv_status LOW",
        "주의: 세션 조정 reduce (회복이 아닌 규칙)",
        "",
    ]


def _recovery_line(document: Any) -> str:
    return next(line for line in _lines(today_summary(document)) if line.startswith("회복: "))


def test_missing_and_partial_recovery_rows_are_named_not_zeroed() -> None:
    missing = _recommend()
    missing["data_freshness"]["requested_date_recovery_row"] = False
    assert _recovery_line(missing) == "회복: normal (오늘 회복 기록 없음 · 없음은 나쁜 회복이 아님)"

    partial = _recommend()  # the golden itself: a row without sleep
    assert _recovery_line(partial) == "회복: normal (readiness MODERATE 60, HRV BALANCED, 오늘 수면 기록 없음)"

    nulls = _recommend()
    nulls["data_freshness"]["requested_date_sleep_recorded"] = True
    for item in nulls["recovery"]["observations"]:
        item["value"] = None
    assert _recovery_line(nulls) == "회복: normal (readiness 알 수 없음, HRV 알 수 없음, 수면 알 수 없음)"
    assert "0" not in _recovery_line(nulls)

    absent = _recommend()
    absent["data_freshness"]["requested_date_sleep_recorded"] = True
    absent["recovery"]["observations"] = []
    assert _recovery_line(absent) == "회복: normal (readiness 알 수 없음, HRV 알 수 없음, 수면 알 수 없음)"

    zero = _recommend()  # a score of 0 is a value, not a missing one
    next(item for item in zero["recovery"]["observations"] if item["field"] == "training_readiness_score")["value"] = 0
    assert _recovery_line(zero).startswith("회복: normal (readiness MODERATE 0, ")


def test_strength_header_without_a_plan_and_with_a_user_focus() -> None:
    none = _recommend()
    none["strength"].update(focus=None, exercises=[])
    lines = _lines(today_summary(none))
    assert lines[2] == "근력: 계획 없음 (사용할 근력 기록 없음)"
    assert lines[3].startswith("회복: ")
    user = _recommend()
    user["strength"]["focus_source"] = "user"
    assert _lines(today_summary(user))[2] == "근력: push (직접 선택) · 약 14분 · 3세트"


def test_swim_without_a_recent_swim_is_not_zero_days() -> None:
    document = _recommend()
    document["swimming"]["baseline"]["days_since_last_swim"] = None
    document["swimming"]["goal"]["cautions"] = []
    swim = next(line for line in _lines(today_summary(document)) if line.startswith("수영: "))
    assert swim == "수영: distance_progression 약 1400 m (최근 28일 수영 기록 없음)"


def _evaluated(document: Any) -> Any:
    nutrition = document["nutrition"]
    nutrition.update(availability="evaluated", meal_count=2, item_count=3)
    nutrients = nutrition["nutrients"]
    nutrients["calories_kcal"].update(
        target={"kind": "range", "minimum": "2200", "maximum": "2500"},
        status="below_range",
        complete=True,
        consumed="845",
        known_subtotal="845",
        remaining="1355",
        remaining_to_maximum="1655",
    )
    nutrients["protein_g"].update(
        target={"kind": "exact", "value": "120"},
        status="indeterminate",
        known_subtotal="61.5",
        missing_items=[{"meal_id": "2026-03-16-lunch-1", "sequence": 2, "food_id": "x", "food_name": "x"}],
    )
    nutrition["actions"] = [{"code": "synthetic", "nutrient": "protein_g", "message": "synthetic"}]
    return document


def _nutrition_line(document: Any) -> str:
    return next(line for line in _lines(today_summary(document)) if line.startswith("영양"))


def test_nutrition_line_by_availability() -> None:
    evaluated = _evaluated(_recommend())
    assert _nutrition_line(evaluated) == (
        "영양: 식사 2끼 · kcal 845 / 목표 2200-2500 (below_range, 최소까지 1355); "
        "단백질 61.5 g 이상 (값 없는 항목 1개) / 목표 120 g (indeterminate) · 안내 1건"
    )
    unknown_subtotal = _evaluated(_recommend())
    unknown_subtotal["nutrition"]["nutrients"]["protein_g"]["known_subtotal"] = None
    assert "단백질 알 수 없음 / 목표 120 g (indeterminate)" in _nutrition_line(unknown_subtotal)

    unavailable = _recommend()
    unavailable["nutrition"].update(availability="unavailable", unavailable_reason="synthetic reason", meal_count=None)
    assert _nutrition_line(unavailable) == "영양: 읽을 수 없음 (synthetic reason)"
    no_reason = _recommend()
    no_reason["nutrition"].update(availability="unavailable", unavailable_reason=None)
    assert _nutrition_line(no_reason) == "영양: 읽을 수 없음 (알 수 없음)"

    no_key = _recommend()
    del no_key["nutrition"]
    assert _nutrition_line(no_key) == "영양: 알 수 없음"


# --- /status -------------------------------------------------------------------------------------------------


def _status_document() -> dict[str, Any]:
    def entry(target: Any, status: str, **values: Any) -> dict[str, Any]:
        base: dict[str, Any] = {
            "target": target,
            "status": status,
            "complete": False,
            "estimated": False,
            "consumed": None,
            "known_subtotal": None,
            "remaining": None,
            "remaining_to_maximum": None,
            "excess": None,
            "missing_items": [],
        }
        base.update(values)
        return base

    missing = [{"meal_id": "2026-10-07-lunch-1", "sequence": 2, "food_id": "x", "food_name": "x"}]
    return {
        "date": "2026-10-07",
        "timezone": "+09:00",
        "scope": "intake_vs_current_targets",
        "meal_count": 2,
        "item_count": 3,
        "nutrients": {
            "calories_kcal": entry(
                {"kind": "range", "minimum": "2200", "maximum": "2500"},
                "below_range",
                complete=True,
                consumed="845",
                known_subtotal="845",
                remaining="1355",
                remaining_to_maximum="1655",
            ),
            "protein_g": entry(
                {"kind": "exact", "value": "120"}, "indeterminate", known_subtotal="61.5", missing_items=missing
            ),
            "carbohydrate_g": entry(
                {"kind": "unset"}, "no_target", complete=True, consumed="140", known_subtotal="140"
            ),
            "fat_g": entry({"kind": "unset"}, "no_target", estimated=True, missing_items=missing),
        },
    }


def test_status_summary_lists_every_nutrient_with_lower_bounds() -> None:
    reply = status_summary(_status_document())
    assert _lines(reply) == [
        "영양 10-07 (UTC+09:00): 식사 2끼, 3개",
        "kcal 845 / 목표 2200-2500 (below_range, 최소까지 1355)",
        "단백질 61.5 g 이상 (값 없는 항목 1개) / 목표 120 g (indeterminate)",
        "탄수화물 140 g / 목표 없음 (no_target)",
        "지방 알 수 없음 / 목표 없음 (no_target) (추정 포함)",
        "전체: /status full",
    ]
    assert reply_messages(reply) == [
        "<pre>" + "\n".join(_lines(reply)[:5]) + "</pre>\n전체: <code>/status full</code>",
    ]


@pytest.mark.parametrize(
    ("status", "values", "text"),
    [
        ("below_target", {"remaining": "58.5"}, "(below_target, 58.5 g 남음)"),
        ("target_reached", {}, "(target_reached)"),
        ("within_range", {"remaining_to_maximum": "10"}, "(within_range, 최대까지 10 g)"),
        ("above_target", {"excess": "4.5"}, "(above_target, 4.5 g 초과)"),
        ("above_range", {"excess": None}, "(above_range, 초과량 알 수 없음)"),
        ("below_target", {"remaining": None}, "(below_target, 알 수 없음 남음)"),
    ],
)
def test_status_extra_by_target_status(status: str, values: dict[str, Any], text: str) -> None:
    document = _status_document()
    document["nutrients"]["protein_g"].update(status=status, complete=True, consumed="61.5", **values)
    assert _lines(status_summary(document))[2] == f"단백질 61.5 g / 목표 120 g {text}"


def test_status_without_meals_says_so_and_never_zero() -> None:
    document = _status_document()
    document.update(meal_count=0, item_count=0)
    for entry in document["nutrients"].values():
        entry.update(complete=False, consumed=None, known_subtotal=None, missing_items=[], estimated=False)
        if entry["target"]["kind"] != "unset":
            entry["status"] = "no_intake_logged"
    assert _lines(status_summary(document))[:5] == [
        "영양 10-07: 오늘 기록 없음 (0 kcal이 아님)",
        "kcal 알 수 없음 / 목표 2200-2500 (no_intake_logged)",
        "단백질 알 수 없음 / 목표 120 g (no_intake_logged)",
        "탄수화물 알 수 없음 / 목표 없음 (no_target)",
        "지방 알 수 없음 / 목표 없음 (no_target)",
    ]


# --- AC5: the UNKNOWN section and /unknown -------------------------------------------------------------------


def _with_notices(count: int) -> Any:
    document = _recommend()
    # Deliberately not in date order: the summary keeps the JSON order and never re-sorts.
    notices = [_notice(str(9000 + index), f"2026-03-{10 - index % 3:02d}", index + 1) for index in range(count)]
    document["strength"]["unknown_notices"] = notices
    others = [notice for notice in document["notices"] if notice["code"] != "strength_unknown_exercise"]
    unknown = [
        {
            "code": "strength_unknown_exercise",
            "message": "x",
            "source_activity_id": item["source_activity_id"],
            "local_date": item["local_date"],
        }
        for item in notices
    ]
    document["notices"] = others + unknown
    return document


def _unknown_items(document: Any) -> list[str]:
    return [line for line in _lines(today_summary(document)) if line.startswith("• ")]


def test_unknown_section_is_absent_without_notices() -> None:
    lines = _lines(today_summary(_with_notices(0)))
    assert "확인 필요: Garmin UNKNOWN 세트" not in lines
    assert not [line for line in lines if "/refresh" in line or line.startswith("외 ")]
    assert lines[-1] == "기타 알림 2건 · 전체: /today full"
    assert _lines(unknown_list(_with_notices(0))) == [
        "Garmin UNKNOWN 세트가 있는 운동 없음 (최근 14일, 오늘 운동 제외)"
    ]


def test_three_unknown_activities_are_all_listed() -> None:
    document = _with_notices(3)
    assert _unknown_items(document) == [
        f"• {notice['local_date'][5:]} 근력 {notice['unknown_set_count']}세트: {GARMIN}{notice['source_activity_id']}"
        for notice in document["strength"]["unknown_notices"]
    ]
    assert not [line for line in _lines(today_summary(document)) if line.startswith("외 ")]


def test_more_than_three_are_folded_and_unknown_lists_all() -> None:
    document = _with_notices(5)
    notices = document["strength"]["unknown_notices"]
    lines = _lines(today_summary(document))
    assert _unknown_items(document) == [
        f"• {notice['local_date'][5:]} 근력 {notice['unknown_set_count']}세트: {GARMIN}{notice['source_activity_id']}"
        for notice in notices[:3]
    ]
    assert lines[-2:] == ["외 2개 · /unknown", "기타 알림 2건 · 전체: /today full"]
    every = _lines(unknown_list(document))
    assert every[0] == "Garmin UNKNOWN 세트가 있는 운동 5개 (최근 14일, 오늘 운동 제외)"
    assert [line for line in every if line.startswith("  고친 뒤: ")] == [
        f"  고친 뒤: /refresh {notice['source_activity_id']}" for notice in notices
    ]
    assert every[9] == "• 03-09 근력 5세트 (세트 1, 2, 3, 4, 5): https://connect.garmin.com/modern/activity/9004"


def test_other_notice_count_excludes_only_what_the_summary_shows() -> None:
    document = _recommend()
    codes = [
        "strength_unknown_exercise",
        "recovery_row_partial",
        "recovery_row_missing",
        "recovery_fields_missing",
        "swim_gap",
        "strength_no_rule_exercise",
        "strength_unknown_exercise",
    ]
    document["notices"] = [
        {"code": code, "message": "x", "source_activity_id": None, "local_date": None} for code in codes
    ]
    assert _lines(today_summary(document))[-1] == "기타 알림 3건 · 전체: /today full"
    document["notices"] = []
    assert _lines(today_summary(document))[-1] == "기타 알림 0건 · 전체: /today full"


# --- AC4: /daily ------------------------------------------------------------------------------------------------


def _failed_daily() -> Any:
    document = _golden("daily_2026-10-02.json")
    stages = {stage["stage"]: stage for stage in document["stages"]}
    stages["recovery"].update(status="failed", error="Garmin recovery <원본> & 실패")
    stages["load_metrics"].update(status="failed", error=None)
    stages["activities"]["warnings"] = ["synthetic warning"]
    stages["recommendation"].update(status="not_run")
    document.update(ok=False, failed_stages=["load_metrics", "recovery"], recommendation=None)
    return document


def test_failed_daily_shows_each_failed_stage_and_no_plan() -> None:
    reply = daily_summary(_failed_daily())
    assert _lines(reply) == [
        "daily 10-02: 실패 (load_metrics, recovery 단계)",
        "  load_metrics: 오류 문구 없음",
        "  recovery: Garmin recovery <원본> & 실패",
        "  경고(activities): synthetic warning",
        "추천은 만들지 않았습니다. 이미 받은 데이터는 저장되어 있습니다.",
        "저장된 데이터로 본 계획: /today · 다시 동기화: /daily",
    ]
    assert reply_messages(reply) == [
        "<pre>daily 10-02: 실패 (load_metrics, recovery 단계)\n  load_metrics: 오류 문구 없음\n"
        "  recovery: Garmin recovery &lt;원본&gt; &amp; 실패\n  경고(activities): synthetic warning</pre>\n"
        "추천은 만들지 않았습니다. 이미 받은 데이터는 저장되어 있습니다.\n"
        "저장된 데이터로 본 계획: /today · 다시 동기화: /daily"
    ]
    assert "근력" not in reply.plain_text() and "/daily full" not in reply.plain_text()


def test_successful_daily_shows_stage_warnings_and_unknown_counts() -> None:
    document = _golden("daily_2026-10-02.json")
    document["stages"][1]["warnings"] = ["synthetic activity warning"]
    document["stages"][3]["warnings"] = ["synthetic recovery warning"]
    lines = _lines(daily_summary(document))
    assert lines[:4] == [
        "daily 10-02: 동기화 완료 (새 운동 2, 회복 2일 갱신)",
        "경고(activities): synthetic activity warning",
        "경고(recovery): synthetic recovery warning",
        "",
    ]
    document.update(activities=None, recovery=None)
    assert _lines(daily_summary(document))[0] == "daily 10-02: 동기화 완료 (새 운동 알 수 없음, 회복 알 수 없음)"


def test_daily_unknown_section_comes_from_the_embedded_recommendation() -> None:
    document = _golden("daily_2026-10-02.json")
    document["recommendation"]["strength"]["unknown_notices"] = [_notice("24610155225", "2026-10-01", 11)]
    messages = TelegramSummaries().summary(ReplyKind.DAILY_SUMMARY, document)
    assert len(messages) == 1
    assert (
        "\n확인 필요: Garmin UNKNOWN 세트\n• 10-01 근력 11세트: "
        f'<a href="{GARMIN}24610155225">{GARMIN}24610155225</a>\n  고친 뒤: <code>/refresh 24610155225</code>\n'
    ) in messages[0]


# --- shape errors ----------------------------------------------------------------------------------------------


def _without_strength(document: Any) -> None:
    del document["strength"]


def _string_count(document: Any) -> None:
    document["strength"]["unknown_notices"][0]["unknown_set_count"] = "1"


def _bool_count(document: Any) -> None:
    document["strength"]["unknown_notices"][0]["unknown_set_count"] = True


def _arabic_indic_id(document: Any) -> None:
    document["strength"]["unknown_notices"][0]["source_activity_id"] = "٨٠٠١"


def _quote_in_id(document: Any) -> None:
    document["strength"]["unknown_notices"][0]["source_activity_id"] = '8001"><b>x</b>'


def _new_availability(document: Any) -> None:
    document["nutrition"]["availability"] = "something_new"


def _null_minutes(document: Any) -> None:
    document["strength"]["estimated_minutes"] = None


@pytest.mark.parametrize(
    ("mutate", "error"),
    [
        (_without_strength, "KeyError"),
        (_string_count, "TypeError"),
        (_bool_count, "TypeError"),
        (_arabic_indic_id, "ValueError"),
        (_quote_in_id, "ValueError"),
        (_new_availability, "ValueError"),
        (_null_minutes, "TypeError"),
    ],
    ids=lambda value: getattr(value, "__name__", value),
)
def test_unexpected_shape_is_a_summary_error_never_a_guess(mutate: Any, error: str) -> None:
    document = _recommend()
    mutate(document)
    with pytest.raises(SummaryUnavailableError) as raised:
        TelegramSummaries().summary(ReplyKind.TODAY_SUMMARY, document)
    assert str(raised.value) == error


def test_a_document_that_is_not_an_object_is_a_summary_error() -> None:
    for kind in (ReplyKind.TODAY_SUMMARY, ReplyKind.DAILY_SUMMARY, ReplyKind.STATUS_SUMMARY, ReplyKind.UNKNOWN_LIST):
        with pytest.raises(SummaryUnavailableError):
            TelegramSummaries().summary(kind, [1, 2])


# --- /refresh -------------------------------------------------------------------------------------------------

CLI_REFRESH = (
    "Garmin activity refresh complete\nGarmin activity ID: 222\nRAW snapshot: x\nStrength sets replaced: 2\n"
    "Swim laps/lengths replaced: 0/0\nReview warnings remaining: none\n경고: synthetic endpoint warning\n"
)


def _counts(count: int, *, day: date | None = date(2026, 10, 5), strength: bool = True) -> ActivityUnknownSets:
    return ActivityUnknownSets("222", day, strength, count, tuple(range(1, count + 1)))


def test_refresh_reply_reports_the_before_and_after_counts() -> None:
    assert _lines(refresh_reply("222", _counts(11), _counts(0), CLI_REFRESH)) == [
        "refresh 222 완료: 10-05 근력, UNKNOWN 11 → 0세트",
        "경고: synthetic endpoint warning",
    ]
    assert _lines(refresh_reply("222", _counts(11), _counts(2, day=None), "Garmin activity refresh complete\n")) == [
        "refresh 222 완료: 날짜 알 수 없음 근력, UNKNOWN 11 → 2세트",
        "아직 UNKNOWN 2세트: Garmin Connect에서 고친 뒤 /refresh 222를 다시 보내세요.",
    ]


@pytest.mark.parametrize(
    ("before", "after"),
    [
        (None, _counts(0)),
        (_counts(1), None),
        (_counts(0, strength=False), _counts(0, strength=False)),
    ],
)
def test_refresh_reply_without_both_counts_is_the_cli_headline(
    before: ActivityUnknownSets | None, after: ActivityUnknownSets | None
) -> None:
    assert _lines(refresh_reply("222", before, after, CLI_REFRESH)) == [
        "Garmin activity refresh complete",
        "경고: synthetic endpoint warning",
    ]
    assert TelegramSummaries().refresh("222", before, after, CLI_REFRESH) == [
        "<pre>Garmin activity refresh complete\n경고: synthetic endpoint warning</pre>"
    ]


# --- AC7 and packing ---------------------------------------------------------------------------------------


def test_summaries_are_byte_identical_for_the_same_input() -> None:
    cases = [
        (ReplyKind.TODAY_SUMMARY, _with_notices(5)),
        (ReplyKind.DAILY_SUMMARY, _golden("daily_2026-10-02.json")),
        (ReplyKind.DAILY_SUMMARY, _failed_daily()),
        (ReplyKind.STATUS_SUMMARY, _status_document()),
        (ReplyKind.UNKNOWN_LIST, _with_notices(5)),
    ]
    for kind, document in cases:
        first = TelegramSummaries().summary(kind, copy.deepcopy(document))
        assert TelegramSummaries().summary(kind, copy.deepcopy(document)) == first
    assert TelegramSummaries().refresh("222", _counts(3), _counts(1), CLI_REFRESH) == TelegramSummaries().refresh(
        "222", _counts(3), _counts(1), CLI_REFRESH
    )


def test_rich_parts_are_escaped_and_tagged() -> None:
    reply = BotReply("a < b & c", ((("x & <y> ", Link('https://e.invalid/?a=1&b="2"'), " ", Code("<c> & d")),),))
    assert reply_messages(reply) == [
        "<pre>a &lt; b &amp; c</pre>\n"
        'x &amp; &lt;y&gt; <a href="https://e.invalid/?a=1&amp;b=&quot;2&quot;">https://e.invalid/?a=1&amp;b="2"</a> '
        "<code>&lt;c&gt; &amp; d</code>"
    ]
    assert reply.plain_text() == 'a < b & c\nx & <y> https://e.invalid/?a=1&b="2" <c> & d'


def test_long_replies_are_packed_in_order_without_loss() -> None:
    pre = "\n".join(f"{index:04d} <synthetic> & 닭가슴살 " + "=" * (index % 40) for index in range(160))
    assert len(pre) > 6000
    groups = tuple(
        (
            (f"• 10-{index % 28 + 1:02d} 근력 {index}세트: ", Link(f"{GARMIN}{24610155000 + index}")),
            ("  고친 뒤: ", Code(f"/refresh {24610155000 + index}")),
        )
        for index in range(150)
    )
    reply = BotReply(pre, groups)
    messages = reply_messages(reply)
    assert len(messages) > 3
    for message in messages:
        assert utf16_units(message) <= TELEGRAM_MESSAGE_LIMIT
    assert _plain(messages) == reply.plain_text()
    # The body is cut exactly as v1 cuts a long text; a group is never split across messages.
    assert messages[: len(telegram_messages(pre)) - 1] == telegram_messages(pre)[:-1]
    for message in messages:
        assert message.count("<a href=") == message.count("<code>/refresh")


def test_a_rich_group_over_the_limit_is_cut_at_its_line_ends() -> None:
    lines = tuple((f"{index:03d} " + "가" * 90,) for index in range(100))
    reply = BotReply("", (lines,))
    messages = reply_messages(reply)
    assert len(messages) == 3
    for message in messages:
        assert utf16_units(message) <= TELEGRAM_MESSAGE_LIMIT
    assert "\n".join(messages) == reply.plain_text()


def test_a_normal_summary_is_one_message() -> None:
    assert len(TelegramSummaries().summary(ReplyKind.TODAY_SUMMARY, _with_notices(3))) == 1
    assert len(TelegramSummaries().summary(ReplyKind.UNKNOWN_LIST, _with_notices(14))) == 1
