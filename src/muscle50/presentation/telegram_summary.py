"""Telegram Mobile Replies v1.1: short Korean summaries of the CLI's own JSON documents.

Every number, weight, label and state is copied from the JSON (`recommend --json`, `daily --json`,
`nutrition status --json`); nothing is recalculated or re-rounded. Kilograms use the CLI's
`kg_text`, swim metres `_fixed` and sleep `_duration`, so the same value reads the same way as in
the full report. A null value is written as ``알 수 없음`` or as a specific state ("오늘 수면 기록
없음"), never as 0. Caution markers (low load confidence, a non-normal recovery level, a session
adjustment from a non-recovery rule, a missing or partial recovery row) are never dropped.

The bot-own fixed texts live in `domain/telegram_commands.py`; the data-driven layouts live here.
An unexpected JSON shape raises `SummaryUnavailableError` (the bot then points to the full text).
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

from muscle50.application.activity_unknown_sets import ActivityUnknownSets
from muscle50.application.telegram_bot import SummaryUnavailableError
from muscle50.domain.nutrition import NutrientField
from muscle50.domain.nutrition_guidance import NutritionAvailability
from muscle50.domain.nutrition_targets import TargetStatus
from muscle50.domain.recovery_assessment import AdjustmentLevel
from muscle50.domain.strength_recommendation import (
    LOAD_STEP_SMALLEST_AVAILABLE_DIRECTION_UNKNOWN,
    UNKNOWN_NOTICE_DAYS,
    ProgressionAction,
    kg_text,
)
from muscle50.domain.swim_recommendation import SWIM_HISTORY_DAYS
from muscle50.domain.telegram_commands import ReplyKind
from muscle50.presentation.telegram_format import BotReply, Code, Link, RichLine, reply_messages
from muscle50.presentation.terminal import _duration, _fixed

UNKNOWN = "알 수 없음"
# `/today` and `/daily` list at most this many UNKNOWN activities; `/unknown` lists all of them.
UNKNOWN_SUMMARY_CAP = 3
GARMIN_ACTIVITY_URL = "https://connect.garmin.com/modern/activity/"
# Notices the summary already shows (the UNKNOWN items, and the recovery line's missing/partial row).
SHOWN_NOTICE_CODES = frozenset({"strength_unknown_exercise", "recovery_row_partial", "recovery_row_missing"})
LOW_LOAD_CONFIDENCE = "low"
_ASCII_DIGITS = re.compile(r"[0-9]+")
_NUTRIENT_NAMES = {
    NutrientField.CALORIES_KCAL: "kcal",
    NutrientField.PROTEIN_G: "단백질",
    NutrientField.CARBOHYDRATE_G: "탄수화물",
    NutrientField.FAT_G: "지방",
}

RichGroups = tuple[tuple[RichLine, ...], ...]


class TelegramSummaries:
    """The `ReplySummaries` port: summaries and refresh replies as HTML messages."""

    def summary(self, kind: ReplyKind, document: Any) -> list[str]:
        builder = _BUILDERS.get(kind)
        if builder is None:
            raise SummaryUnavailableError(f"no summary for {kind.value}")
        try:
            reply = builder(document)
        except (AttributeError, IndexError, KeyError, TypeError, ValueError) as exc:
            raise SummaryUnavailableError(type(exc).__name__) from exc
        return reply_messages(reply)

    def refresh(
        self,
        activity_id: str,
        before: ActivityUnknownSets | None,
        after: ActivityUnknownSets | None,
        cli_stdout: str,
    ) -> list[str]:
        return reply_messages(refresh_reply(activity_id, before, after, cli_stdout))


# --- /today and /daily -------------------------------------------------------------------------------


def today_summary(document: Any) -> BotReply:
    recommendation = _object(document)
    lines = [f"오늘 추천 {_month_day(recommendation['as_of'])}", *_plan_lines(recommendation)]
    return BotReply("\n".join(lines), _plan_tail(recommendation))


def daily_summary(document: Any) -> BotReply:
    daily = _object(document)
    as_of = _month_day(daily["as_of"])
    stages = [_object(item) for item in _list(daily["stages"])]
    warnings = [
        f"경고({_text(stage['stage'])}): {_text(warning)}" for stage in stages for warning in _list(stage["warnings"])
    ]
    if not _bool(daily["ok"]):
        # Never a plan after a failed stage (the daily rule): the stage errors verbatim, then where to go.
        failed = [_text(item) for item in _list(daily["failed_stages"])]
        lines = [f"daily {as_of}: 실패" + (f" ({', '.join(failed)} 단계)" if failed else "")]
        for stage in stages:
            if _text(stage["stage"]) in failed:
                error = stage["error"]
                lines.append(f"  {_text(stage['stage'])}: {_text(error) if error is not None else '오류 문구 없음'}")
        lines.extend(f"  {warning}" for warning in warnings)
        tail: RichGroups = (
            (
                ("추천은 만들지 않았습니다. 이미 받은 데이터는 저장되어 있습니다.",),
                ("저장된 데이터로 본 계획: /today · 다시 동기화: /daily",),
            ),
        )
        return BotReply("\n".join(lines), tail)
    activities = daily["activities"]
    new = f"새 운동 {_int(_object(activities)['inserted'])}" if activities is not None else f"새 운동 {UNKNOWN}"
    recovery = daily["recovery"]
    if recovery is None:
        updated = f"회복 {UNKNOWN}"
    else:
        outcomes = [_object(item) for item in _list(_object(recovery)["outcomes"])]
        days = sum(1 for item in outcomes if _text(item["status"]) in ("created", "updated"))
        updated = f"회복 {days}일 갱신"
    recommendation = _object(daily["recommendation"])
    lines = [f"daily {as_of}: 동기화 완료 ({new}, {updated})", *warnings, *_plan_lines(recommendation)]
    return BotReply("\n".join(lines), _plan_tail(recommendation))


def _plan_lines(recommendation: dict[str, Any]) -> list[str]:
    """The plan body after the header line: cautions first, then strength, recovery, swim, nutrition."""
    recovery = _object(recommendation["recovery"])
    strength = _object(recommendation["strength"])
    return [
        *_caution_lines(recovery, strength),
        "",
        *_strength_lines(strength),
        _recovery_line(recovery, _object(recommendation["data_freshness"])),
        _swim_line(_object(recommendation["swimming"])),
        _nutrition_line(recommendation),
    ]


def _caution_lines(recovery: dict[str, Any], strength: dict[str, Any]) -> list[str]:
    level = _text(recovery["level"])
    lines = []
    if level != AdjustmentLevel.NORMAL.value:
        reasons = [
            f"{_text(item['field'])} {_observation_value(item)}"
            for item in (_object(entry) for entry in _list(recovery["observations"]))
            if item["fired_level"] is not None
        ]
        lookback = recovery["lookback"]
        carried = _object(lookback)["carried_level"] if lookback is not None else None
        if carried is not None:
            reasons.append(f"이전 아침 기록으로 {_text(carried)} 유지")
        lines.append(f"주의: 회복 {level}" + (f" - {', '.join(reasons)}" if reasons else ""))
    adjustment = _text(strength["adjustment_level"])
    if adjustment != level:
        lines.append(f"주의: 세션 조정 {adjustment} (회복이 아닌 규칙)")
    return lines


def _strength_lines(strength: dict[str, Any]) -> list[str]:
    focus = strength["focus"]
    if focus is None:
        return ["근력: 계획 없음 (사용할 근력 기록 없음)"]
    chosen = " (직접 선택)" if _text(strength["focus_source"]) == "user" else ""
    lines = [
        f"근력: {_text(focus)}{chosen} · 약 {_int(strength['estimated_minutes'])}분 · "
        f"{_int(strength['working_sets'])}세트"
    ]
    for index, exercise in enumerate(_list(strength["exercises"]), start=1):
        lines.append(f" {index}. {_exercise_text(_object(exercise))}")
    return lines


def _exercise_text(exercise: dict[str, Any]) -> str:
    """One planned exercise, mirroring the CLI `_prescription` (a low-confidence load is never shown as exact)."""
    progression = _object(exercise["progression"])
    rep_range = _object(progression["rep_range"])
    target_reps = progression["target_reps"]
    if target_reps is not None:
        reps = str(_int(target_reps))
    else:
        reps = f"{_int(rep_range['minimum'])}-{_int(rep_range['maximum'])}"
    load_kg = progression["load_kg"]
    reference = load_kg if load_kg is not None else progression["load_increase_from_kg"]
    low = reference is not None and _text(progression["load_confidence"]) == LOW_LOAD_CONFIDENCE
    if reference is None:
        load = " (무게 목표 없음)"
    else:
        shown = f"{'~' if low else ''}{kg_text(_number(reference))}"
        if load_kg is not None:
            load = f" @ {shown}"
        elif progression["load_step"] == LOAD_STEP_SMALLEST_AVAILABLE_DIRECTION_UNKNOWN:
            load = f" @ {shown}에서 한 단계 (보조인지 추가 무게인지 확인)"
        else:
            load = f" @ {shown}에서 다음 단계 위"
    caution = ""
    if low:
        caution = " (무게 불확실)" if _bool(progression["same_load_evidence"]) else " (무게 불확실, 지난 무게 확인)"
    if _text(progression["action"]) == ProgressionAction.ESTABLISH_BASELINE.value:
        load, caution = " (무게 직접 선택: 비교 기록 없음)", ""
    return f"{_text(exercise['label'])} {_int(exercise['sets'])}x{reps}{load}{caution}"


def _recovery_line(recovery: dict[str, Any], freshness: dict[str, Any]) -> str:
    level = _text(recovery["level"])
    if not _bool(freshness["requested_date_recovery_row"]):
        return f"회복: {level} (오늘 회복 기록 없음 · 없음은 나쁜 회복이 아님)"
    observations: dict[str, Any] = {}
    for entry in _list(recovery["observations"]):
        item = _object(entry)
        observations.setdefault(_text(item["field"]), item["value"])
    readiness = f"readiness {_value(observations.get('training_readiness_level'))}"
    score = observations.get("training_readiness_score")
    if score is not None:
        readiness += f" {_value(score)}"
    if not _bool(freshness["requested_date_sleep_recorded"]):
        sleep = "오늘 수면 기록 없음"
    else:
        sleep = f"수면 {_sleep(observations.get('sleep_seconds'))}"
    return f"회복: {level} ({readiness}, HRV {_value(observations.get('hrv_status'))}, {sleep})"


def _swim_line(swimming: dict[str, Any]) -> str:
    goal = _object(swimming["goal"])
    days = _object(swimming["baseline"])["days_since_last_swim"]
    last = f"마지막 수영 {_int(days)}일 전" if days is not None else f"최근 {SWIM_HISTORY_DAYS}일 수영 기록 없음"
    line = f"수영: {_text(goal['session_type'])} 약 {_fixed(_number(goal['total_meters']))} m ({last})"
    cautions = len(_list(goal["cautions"]))
    return f"{line} · 주의 {cautions}건" if cautions else line


def _nutrition_line(recommendation: dict[str, Any]) -> str:
    if "nutrition" not in recommendation:
        return f"영양: {UNKNOWN}"
    nutrition = _object(recommendation["nutrition"])
    availability = NutritionAvailability(_text(nutrition["availability"]))
    if availability is NutritionAvailability.NO_TARGETS_CONFIGURED:
        return "영양: 목표 없음"
    if availability is NutritionAvailability.UNAVAILABLE:
        return f"영양: 읽을 수 없음 ({_value(nutrition['unavailable_reason'])})"
    if availability is NutritionAvailability.NO_INTAKE_LOGGED:
        return "영양: 오늘 기록 없음 (0 kcal이 아님)"
    nutrients = _object(nutrition["nutrients"])
    parts = [
        _nutrient_text(field, entry)
        for field, entry in ((field, _object(nutrients[field.value])) for field in NutrientField)
        if _text(_object(entry["target"])["kind"]) != "unset"
    ]
    line = f"영양: 식사 {_int(nutrition['meal_count'])}끼"
    if parts:
        line += " · " + "; ".join(parts)
    actions = len(_list(nutrition["actions"]))
    return f"{line} · 안내 {actions}건" if actions else line


def _plan_tail(recommendation: dict[str, Any]) -> RichGroups:
    notices = _list(_object(recommendation["strength"])["unknown_notices"])
    groups: list[tuple[RichLine, ...]] = []
    if notices:
        groups.append((("확인 필요: Garmin UNKNOWN 세트",),))
        # JSON order: newest first, as the recommendation sorts them.
        groups.extend(_unknown_groups(notices[:UNKNOWN_SUMMARY_CAP], with_sequences=False))
        hidden = len(notices) - UNKNOWN_SUMMARY_CAP
        if hidden > 0:
            groups.append(((f"외 {hidden}개 · /unknown",),))
    other = sum(
        1 for notice in _list(recommendation["notices"]) if _text(_object(notice)["code"]) not in SHOWN_NOTICE_CODES
    )
    groups.append(((f"기타 알림 {other}건 · 전체: ", Code("/today full")),))
    return tuple(groups)


def _unknown_groups(notices: list[Any], *, with_sequences: bool) -> list[tuple[RichLine, ...]]:
    groups: list[tuple[RichLine, ...]] = []
    for entry in notices:
        notice = _object(entry)
        activity_id = _activity_id(notice["source_activity_id"])
        sequences = ""
        if with_sequences:
            sequences = f" (세트 {', '.join(str(_int(item)) for item in _list(notice['set_sequences']))})"
        head = f"• {_month_day(notice['local_date'])} 근력 {_int(notice['unknown_set_count'])}세트{sequences}: "
        groups.append(
            ((head, Link(f"{GARMIN_ACTIVITY_URL}{activity_id}")), ("  고친 뒤: ", Code(f"/refresh {activity_id}")))
        )
    return groups


# --- /unknown ----------------------------------------------------------------------------------------


def unknown_list(document: Any) -> BotReply:
    notices = _list(_object(_object(document)["strength"])["unknown_notices"])
    window = f"최근 {UNKNOWN_NOTICE_DAYS}일, 오늘 운동 제외"
    if not notices:
        return BotReply(f"Garmin UNKNOWN 세트가 있는 운동 없음 ({window})")
    groups = _unknown_groups(notices, with_sequences=True)
    groups.append((("Garmin Connect에서 운동 이름을 고친 뒤 /refresh로 다시 받습니다.",),))
    return BotReply(f"Garmin UNKNOWN 세트가 있는 운동 {len(notices)}개 ({window})", tuple(groups))


# --- /status -----------------------------------------------------------------------------------------


def status_summary(document: Any) -> BotReply:
    status = _object(document)
    day = _month_day(status["date"])
    meals = _int(status["meal_count"])
    if meals == 0:
        header = f"영양 {day}: 오늘 기록 없음 (0 kcal이 아님)"
    else:
        header = f"영양 {day} (UTC{_text(status['timezone'])}): 식사 {meals}끼, {_int(status['item_count'])}개"
    nutrients = _object(status["nutrients"])
    lines = [header, *(_nutrient_text(field, _object(nutrients[field.value])) for field in NutrientField)]
    return BotReply("\n".join(lines), ((("전체: ", Code("/status full")),),))


def _nutrient_text(field: NutrientField, entry: dict[str, Any]) -> str:
    """`{name} {amount} / 목표 {target} ({status}{extra})`; an incomplete amount is a lower bound, never a total."""
    unit = "" if field is NutrientField.CALORIES_KCAL else " g"
    if _bool(entry["complete"]):
        amount = _amount(entry["consumed"], unit)
    elif entry["known_subtotal"] is None:
        amount = UNKNOWN
    else:
        missing = len(_list(entry["missing_items"]))
        amount = f"{_text(entry['known_subtotal'])}{unit} 이상 (값 없는 항목 {missing}개)"
    status = TargetStatus(_text(entry["status"]))
    estimated = " (추정 포함)" if _bool(entry["estimated"]) else ""
    target = _target_text(_object(entry["target"]), unit)
    extra = _status_extra(status, entry, unit)
    return f"{_NUTRIENT_NAMES[field]} {amount} / 목표 {target} ({status.value}{extra}){estimated}"


def _target_text(target: dict[str, Any], unit: str) -> str:
    kind = _text(target["kind"])
    if kind == "exact":
        return f"{_text(target['value'])}{unit}"
    if kind == "range":
        return f"{_text(target['minimum'])}-{_text(target['maximum'])}{unit}"
    if kind == "unset":
        return "없음"
    raise ValueError(f"unknown target kind {kind!r}")


def _status_extra(status: TargetStatus, entry: dict[str, Any], unit: str) -> str:
    if status is TargetStatus.BELOW_TARGET:
        return f", {_amount(entry['remaining'], unit)} 남음"
    if status is TargetStatus.BELOW_RANGE:
        return f", 최소까지 {_amount(entry['remaining'], unit)}"
    if status is TargetStatus.WITHIN_RANGE:
        return f", 최대까지 {_amount(entry['remaining_to_maximum'], unit)}"
    if status in (TargetStatus.ABOVE_TARGET, TargetStatus.ABOVE_RANGE):
        excess = entry["excess"]
        return f", {_text(excess)}{unit} 초과" if excess is not None else ", 초과량 알 수 없음"
    return ""


# --- /refresh ----------------------------------------------------------------------------------------


def refresh_reply(
    activity_id: str, before: ActivityUnknownSets | None, after: ActivityUnknownSets | None, cli_stdout: str
) -> BotReply:
    """Before/after UNKNOWN counts of a strength activity; otherwise only the CLI's first line (no guess)."""
    lines = []
    if before is not None and after is not None and before.is_strength and after.is_strength:
        day = f"{after.local_date:%m-%d}" if after.local_date is not None else "날짜 알 수 없음"
        lines.append(
            f"refresh {activity_id} 완료: {day} 근력, "
            f"UNKNOWN {before.unknown_set_count} → {after.unknown_set_count}세트"
        )
        if after.unknown_set_count > 0:
            lines.append(
                f"아직 UNKNOWN {after.unknown_set_count}세트: "
                f"Garmin Connect에서 고친 뒤 /refresh {activity_id}를 다시 보내세요."
            )
    else:
        lines.append(cli_stdout.split("\n", 1)[0])
    # Garmin endpoint warnings of `render_refresh_result` (it has no --json), verbatim.
    lines.extend(line for line in cli_stdout.split("\n") if line.startswith("경고: "))
    return BotReply("\n".join(lines))


_BUILDERS: dict[ReplyKind, Callable[[Any], BotReply]] = {
    ReplyKind.TODAY_SUMMARY: today_summary,
    ReplyKind.DAILY_SUMMARY: daily_summary,
    ReplyKind.STATUS_SUMMARY: status_summary,
    ReplyKind.UNKNOWN_LIST: unknown_list,
}


# --- typed JSON access: a wrong type is a shape error, never a "None" or a 0 in the reply ---------------


def _object(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise TypeError("expected a JSON object")
    return value


def _list(value: Any) -> list[Any]:
    if not isinstance(value, list):
        raise TypeError("expected a JSON array")
    return value


def _text(value: Any) -> str:
    if not isinstance(value, str):
        raise TypeError("expected a JSON string")
    return value


def _int(value: Any) -> int:
    if type(value) is not int:  # a bool is not a count
        raise TypeError("expected a JSON integer")
    return value


def _bool(value: Any) -> bool:
    if type(value) is not bool:
        raise TypeError("expected a JSON boolean")
    return value


def _number(value: Any) -> float:
    if type(value) not in (int, float):
        raise TypeError("expected a JSON number")
    return float(value)


def _value(value: Any) -> str:
    """A nullable scalar as written in the JSON; null is `알 수 없음`."""
    if value is None:
        return UNKNOWN
    if isinstance(value, str):
        return value
    if type(value) in (int, float):
        return str(value)
    raise TypeError("expected a JSON scalar")


def _amount(value: Any, unit: str) -> str:
    """A nullable Decimal string with its unit; null is `알 수 없음`."""
    return UNKNOWN if value is None else f"{_text(value)}{unit}"


def _sleep(value: Any) -> str:
    return UNKNOWN if value is None else _duration(_number(value))


def _observation_value(item: dict[str, Any]) -> str:
    if item["field"] == "sleep_seconds" and item["value"] is not None:
        return _sleep(item["value"])
    return _value(item["value"])


def _month_day(value: Any) -> str:
    """`MM-DD` of an ISO date string (a slice, not a date calculation)."""
    text = _text(value)
    if len(text) != 10:
        raise ValueError("expected a YYYY-MM-DD date")
    return text[5:]


def _activity_id(value: Any) -> str:
    """Checked to be ASCII digits before it goes into a link or a command."""
    text = _text(value)
    if _ASCII_DIGITS.fullmatch(text) is None:
        raise ValueError("activity id is not ASCII digits")
    return text
