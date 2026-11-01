"""Telegram Mobile Replies v1.1: short Korean summaries of the CLI's own JSON documents.

Every number, weight, label and state is copied from the JSON (`recommend --json`, `daily --json`,
`nutrition status --json`); nothing is recalculated or re-rounded. Kilograms use the CLI's
`kg_text`, swim metres `_fixed` and sleep `_duration`, so the same value reads the same way as in
the full report. A null value is written as ``알 수 없음`` or as a specific state ("오늘 수면 기록
없음"), never as 0. Caution markers (low load confidence, a non-normal recovery level, a session
adjustment from a non-recovery rule, a missing or partial recovery row) are never dropped.

The bot-own fixed texts live in `domain/telegram_commands.py`; the data-driven layouts live here.
An unexpected JSON shape raises `SummaryUnavailableError` (the bot then points to the full text).
Telegram Goal Summary v1: with a goal set, a successful `/daily` adds the `goal_mode` lines, copied from
`recommendation.goal_mode` with the CLI's evidence tags; an unknown state value is a shape error.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import date
from typing import Any

from muscle50.application.activity_unknown_sets import ActivityUnknownSets
from muscle50.application.telegram_bot import (
    MAX_CONSECUTIVE_REFRESH_FAILURES,
    BulkRefreshResult,
    RefreshItem,
    RefreshItemStatus,
    RefreshStop,
    RefreshTarget,
    SummaryUnavailableError,
)
from muscle50.domain.goal_mode import GOAL_MODE_VERSION
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
from muscle50.domain.sync_catch_up import CATCH_UP_LOOKBACK_DAYS
from muscle50.domain.telegram_commands import (
    REFRESH_ALL_CAP,
    REFRESH_ALL_LINE,
    ReplyKind,
    refresh_login_text,
    unexpected_error_text,
)
from muscle50.domain.telegram_sync import older_unsynced_line, range_text, sync_command_text
from muscle50.domain.training_goal import GoalMode
from muscle50.presentation.goal_terminal import _km
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

    def refresh_targets(self, document: Any) -> tuple[RefreshTarget, ...]:
        try:
            return refresh_targets(document)
        except (AttributeError, IndexError, KeyError, TypeError, ValueError) as exc:
            raise SummaryUnavailableError(type(exc).__name__) from exc

    def refresh_all(self, result: BulkRefreshResult) -> list[str]:
        return reply_messages(refresh_all_reply(result))

    def confirm_offer(self, body: str, command: str) -> list[str]:
        """Daily Catch-up v1 `/sync` offer: the body, then the `/sync_ok_` command as plain text (one tap sends it)."""
        return reply_messages(BotReply(body, (((command,),),)))


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
    # Daily Catch-up v1: only when `daily` started before D-1 (the `catch_up` key is absent otherwise).
    catch_up, catch_up_tail = _catch_up(daily)
    if not _bool(daily["ok"]):
        # Never a plan after a failed stage (the daily rule): the stage errors verbatim, then where to go.
        failed = [_text(item) for item in _list(daily["failed_stages"])]
        lines = [f"daily {as_of}: 실패" + (f" ({', '.join(failed)} 단계)" if failed else ""), *catch_up]
        for stage in stages:
            if _text(stage["stage"]) in failed:
                error = stage["error"]
                lines.append(f"  {_text(stage['stage'])}: {_text(error) if error is not None else '오류 문구 없음'}")
        lines.extend(f"  {warning}" for warning in warnings)
        tail: RichGroups = (
            *catch_up_tail,
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
    lines = [f"daily {as_of}: 동기화 완료 ({new}, {updated})", *catch_up, *warnings, *_plan_lines(recommendation)]
    # Telegram Goal Summary v1: only with a goal set (the CLI omits the key otherwise); `/today` stays as it was.
    if "goal_mode" in recommendation:
        lines += ["", *_goal_lines(_object(recommendation["goal_mode"]))]
    return BotReply("\n".join(lines), (*catch_up_tail, *_plan_tail(recommendation)))


def _catch_up(daily: dict[str, Any]) -> tuple[list[str], RichGroups]:
    """The `이어 받기` line and, when `daily` left older days out, the `/sync` group (a `<code>` command: tapping a
    command with arguments would send a bare `/sync`)."""
    if "catch_up" not in daily:
        return [], ()
    catch_up = _object(daily["catch_up"])
    start = _month_day(catch_up["from"])
    last = catch_up["last_synced"]
    if last is None:
        line = f"이어 받기: {start}부터 (최근 {CATCH_UP_LOOKBACK_DAYS}일에 모두 동기화된 날 없음)"
    else:
        line = f"이어 받기: {start}부터 (마지막 동기화 {_month_day(last)})"
    older = catch_up["older_unsynced"]
    if older is None:
        return [line], ()
    # `/daily` runs for the bot's today, so `as_of` is the year `MM-DD` means.
    today = _date(daily["as_of"])
    first, end = _date(_object(older)["from"]), _date(_object(older)["to"])
    group: tuple[RichLine, ...] = (
        (older_unsynced_line(first, end, today, daily="daily"), Code(sync_command_text(first, end, today))),
    )
    return [line], (group,)


# --- /sync (Daily Catch-up v1) -----------------------------------------------------------------------------


def sync_summary(document: Any) -> BotReply:
    """`garmin sync --json`: the range, new activities, new recovery days and what failed (never 0 for unknown)."""
    sync = _object(document)
    if _text(sync["mode"]) != "sync":
        raise ValueError("not a garmin sync document")
    start, end = _date(sync["sync_from"]), _date(sync["as_of"])
    period = range_text(start, end, end)
    stages = [_object(item) for item in _list(sync["stages"])]
    warnings = [
        f"경고({_text(stage['stage'])}): {_text(warning)}" for stage in stages for warning in _list(stage["warnings"])
    ]
    failures: list[str] = []
    activities = sync["activities"]
    if activities is None:
        new_activities = f"운동 새로 저장 {UNKNOWN}"
    else:
        found = _object(activities)
        new_activities = f"운동 새로 저장 {_int(found['inserted'])}건"
        failures.extend(
            f"운동 {_text(item['source_activity_id'])}"
            for item in (_object(entry) for entry in _list(found["outcomes"]))
            if _text(item["status"]) == "failed"
        )
    recovery = sync["recovery"]
    if recovery is None:
        new_recovery = f"회복 새로 저장 {UNKNOWN}"
    else:
        outcomes = [_object(item) for item in _list(_object(recovery)["outcomes"])]
        statuses = [_text(item["status"]) for item in outcomes]
        new_recovery = f"회복 새로 저장 {statuses.count('created')}일"
        if statuses.count("updated"):
            new_recovery += f" (갱신 {statuses.count('updated')}일)"
        for item, status in zip(outcomes, statuses, strict=True):
            if status == "failed":
                failures.append(_month_day(item["calendar_date"]))
            elif status == "not_attempted":
                failures.append(f"{_month_day(item['calendar_date'])}(받지 않음)")
    counts = " · ".join([new_activities, new_recovery, f"실패: {', '.join(failures)}" if failures else "실패 없음"])
    if _bool(sync["ok"]):
        return BotReply("\n".join([f"동기화했습니다: {period}", counts, *warnings]), ((("오늘 추천: /daily",),),))
    failed = [_text(item) for item in _list(sync["failed_stages"])]
    lines = [f"동기화 일부 실패: {period}" + (f" ({', '.join(failed)} 단계)" if failed else ""), counts]
    for stage in stages:
        if _text(stage["stage"]) in failed:
            error = stage["error"]
            lines.append(f"  {_text(stage['stage'])}: {_text(error) if error is not None else '오류 문구 없음'}")
    lines.extend(f"  {warning}" for warning in warnings)
    retry = ("이미 받은 데이터는 저장되어 있습니다. 다시 받기: ", Code(sync_command_text(start, end, end)))
    return BotReply("\n".join(lines), ((retry,),))


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
        groups.append(((REFRESH_ALL_LINE,),))
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


# --- the goal lines of /daily (Telegram Goal Summary v1) ---------------------------------------------

# Each line carries the tag of the CLI goal-section line that shows the same content. An indented line
# belongs to the tagged line above it; the reference marks and the options carry their own tags.
_USER_SETTING_TAG = "[design: user setting]"
_WEIGHT_TAG = "[MAINT-05; design]"
_AEROBIC_TAG = "[EXL-03; design]"
_PLATEAU_TAG = "[design: user setting; PLAT-01, PLAT-02]"
_RUN_TAG = "[RUNPROG-03: 관찰 연구의 연관, 알림만]"
_ASSUMPTION_TAG = "[design: fat-free mass assumed constant]"
_AEROBIC_TYPE_NAMES = {"running": "러닝", "swimming": "수영"}
# FATEX-02: 300 is the end of the studied range, never a point past which the benefit is gone. The 75 is
# the CLI's own fixed wording of EXL-03 ("150 moderate or 75 vigorous").
_REFERENCE_MEANINGS = {
    "guideline_minimum": "분 지침 최소(고강도면 75분)",
    "end_of_studied_range": "분 연구된 범위의 끝",
}
_UNFLAGGED_RUN_STATUSES = frozenset({"within", "no_previous_run", "no_distance"})
_CHOICE_EVIDENCE = ["PLAT-06", "FATEX-07"]
# The wording of each option is written for exactly these IDs (`aerobic_guide.plateau_options()`), so other
# IDs in the JSON are a shape error rather than a tag next to text that does not say what it supports.
_OPTION_EVIDENCE = {
    "check_meal_logging": ("PLAT-04",),
    "eat_less": ("design", "PRO-04"),
    "keep_intake_add_activity": ("FATEX-05", "FATEX-04", "RUNPROG-03", "CONC-04"),
    "maintenance_week": ("PLAT-05",),
}


def _goal_lines(goal_mode: dict[str, Any]) -> list[str]:
    """`recommendation.goal_mode` as short lines: rates, flags, dates, minutes and the user's own settings.

    Nothing is recalculated and no measured kg is shown; an unknown status, flag, option code, meaning or
    activity type raises `ValueError` (never a dropped line).
    """
    if _int(goal_mode["goal_mode_version"]) != GOAL_MODE_VERSION:
        raise ValueError("unsupported goal_mode_version")
    goal = _object(goal_mode["goal"])
    mode = GoalMode(_text(goal["mode"]))
    return [
        f"목표: {mode.value} (내 설정) {_USER_SETTING_TAG}",
        *_goal_weight_lines(_object(goal_mode["weight_change"]), goal),
        _goal_smm_line(_object(goal_mode["smm_floor"])),
        _goal_progress_line(_object(goal_mode["goal_progress"]), goal),
        *_goal_aerobic_lines(_object(goal_mode["aerobic_minutes"])),
        *_goal_run_lines(_object(goal_mode["run_length"])),
        *_goal_plateau_lines(goal_mode["plateau"]),
    ]


def _goal_weight_lines(change: dict[str, Any], goal: dict[str, Any]) -> list[str]:
    status = _text(change["status"])
    if status == "known":
        span = f"{_month_day(change['from_date'])} -> {_month_day(change['to_date'])}"
        lines = [f"체중 변화 {span}: {_text(change['percent_per_week'])} %/주 {_WEIGHT_TAG}"]
    elif status == "unknown":
        lines = [f"체중 변화: {UNKNOWN} ({_text(change['reason'])}) {_WEIGHT_TAG}"]
    else:
        raise ValueError(f"unknown weight_change status {status}")
    # Caution markers: one line per flag, in JSON order, never dropped.
    for flag in (_text(item) for item in _list(change["flags"])):
        if flag == "faster_than_evidence":
            maximum = _text(_object(change["evidence_range_percent_per_week"])["maximum"])
            lines.append(f"  -> 감량이 주 {maximum} %보다 빠름: 근육 유지에 불리할 수 있음 [MAINT-05]")
        elif flag == "outside_user_target":
            rate = _object(goal["weekly_loss_percent"])
            target = f"{_text(rate['minimum'])}-{_text(rate['maximum'])}"
            lines.append(f"  -> 내 목표 감량 {target} %/주 밖 {_USER_SETTING_TAG}")
        elif flag == "gaining":
            lines.append("  -> 감량 중 체중 증가 [design]")
        else:
            raise ValueError(f"unknown weight_change flag {flag}")
    return lines


def _goal_smm_line(floor: dict[str, Any]) -> str:
    """The user's own SMM floor (a setting, not a measurement) and where the latest InBody stands."""
    status = _text(floor["status"])
    if status == "not_set":
        return f"골격근량 하한: 설정 안 함 {_USER_SETTING_TAG}"
    limit = f"내 하한 {_text(floor['floor_kg'])} kg"
    if status == "unknown":
        return f"골격근량: {limit} 대비 {UNKNOWN} (InBody 골격근량 없음) {_USER_SETTING_TAG}"
    if status in ("at_or_above", "below"):
        where = "이상" if status == "at_or_above" else "아래"
        return f"골격근량: {limit} {where} (InBody {_month_day(floor['measurement_date'])}) {_USER_SETTING_TAG}"
    raise ValueError(f"unknown smm_floor status {status}")


def _goal_progress_line(progress: dict[str, Any], goal: dict[str, Any]) -> str:
    assumption = progress["assumption"]
    tag = "[design]" if assumption is None else _ASSUMPTION_TAG
    if assumption is not None:
        _text(assumption)  # the CLI's `fat_free_mass_constant`: a body-fat target
    status = _text(progress["status"])
    if status == "known":
        actual = progress["actual_percent_per_week"]
        actual_text = f"실제 {_text(actual)} %/주" if actual is not None else f"실제 {UNKNOWN}"
        required = _text(progress["required_percent_per_week"])
        text = f"{_goal_target(goal)}까지 {required} %/주 필요 (기한 {_text(goal['target_date'])}), {actual_text}"
    elif status == "reached":
        text = f"{_goal_target(goal)} 도달 (InBody {_month_day(progress['measurement_date'])})"
    elif status == "deadline_passed":
        text = f"기한 {_text(goal['target_date'])} 지남"
    elif status == "not_set":
        text = "계산 안 함 (목표와 기한이 둘 다 있어야 함)"
    elif status == "unknown":
        text = f"{UNKNOWN} ({_text(progress['reason'])})"
    else:
        raise ValueError(f"unknown goal_progress status {status}")
    return f"목표 진행: {text} {tag}"


def _goal_target(goal: dict[str, Any]) -> str:
    """The user's own target, as entered (a setting, not a measurement)."""
    body_fat, weight = goal["target_body_fat_percent"], goal["target_weight_kg"]
    if body_fat is not None:
        return f"체지방 {_text(body_fat)} %"
    if weight is not None:
        return f"체중 {_text(weight)} kg"
    raise ValueError("goal progress without a body fat or weight target")


def _goal_aerobic_lines(aerobic: dict[str, Any]) -> list[str]:
    """Stored Garmin intensity minutes of the counted types, then the 150/300 marks side by side (no verdict)."""
    types = "·".join(_aerobic_type_name(item) for item in _list(aerobic["activity_types"]))
    head = f"유산소({types}) {_month_day(aerobic['from'])}..{_month_day(aerobic['to'])}: "
    status = _text(aerobic["status"])
    if status in ("known", "lower_bound"):
        total = f"{_number(aerobic['total_minutes']):g}분" + (" 이상" if status == "lower_bound" else "")
        parts = (
            f"중강도 {_goal_minutes(aerobic['moderate_minutes'])} + 고강도 {_goal_minutes(aerobic['vigorous_minutes'])}"
        )
        lines = [f"{head}{total} ({parts}) {_AEROBIC_TAG}"]
        if status == "lower_bound":
            without = _object(aerobic["without_intensity_minutes"])
            missing, partial = _int(without["activity_count"]), _int(without["one_metric_only_count"])
            reasons = []
            if missing:
                reasons.append(f"intensity minutes 없는 활동 {missing}개 빠짐")
            if partial:
                reasons.append(f"중강도·고강도 중 하나만 있는 활동 {partial}개")
            if not reasons:
                raise ValueError("a lower bound without an activity that lacks intensity minutes")
            lines.append(f"  하한: {' · '.join(reasons)} [design]")
    elif status == "unknown":
        count = _int(_object(aerobic["without_intensity_minutes"])["activity_count"])
        lines = [f"{head}{UNKNOWN} (활동 {count}개 모두 intensity minutes 없음) {_AEROBIC_TAG}"]
    elif status == "none_stored":
        lines = [f"{head}저장된 활동 없음 (동기화 안 됐을 수 있음, 0분이 아님) {_AEROBIC_TAG}"]
    else:
        raise ValueError(f"unknown aerobic_minutes status {status}")
    references = [_reference_text(_object(item)) for item in _list(aerobic["reference_minutes_per_week"])]
    if not references:
        raise ValueError("no aerobic reference marks")
    lines.append(f"  기준선: {' · '.join(references)}")
    return lines


def _aerobic_type_name(value: Any) -> str:
    name = _AEROBIC_TYPE_NAMES.get(_text(value))
    if name is None:
        raise ValueError(f"unknown aerobic activity type {value}")
    return name


def _goal_minutes(value: Any) -> str:
    """Minutes as the CLI writes them (`:g`); null is `알 수 없음`, never 0."""
    return UNKNOWN if value is None else f"{_number(value):g}"


def _reference_text(reference: dict[str, Any]) -> str:
    meaning = _REFERENCE_MEANINGS.get(_text(reference["meaning"]))
    if meaning is None:
        raise ValueError("unknown aerobic reference meaning")
    tags = ", ".join(_text(item) for item in _list(reference["evidence"]))
    return f"{_int(reference['minutes'])}{meaning} [{tags}]"


def _goal_run_lines(report: dict[str, Any]) -> list[str]:
    """One line per run flagged `longer_than_threshold` (a caution marker: every one, never capped)."""
    previous_days = _int(report["previous_days"])
    lines = []
    for entry in _list(report["runs"]):
        run = _object(entry)
        status = _text(run["status"])
        if status in _UNFLAGGED_RUN_STATUSES:
            continue
        if status != "longer_than_threshold":
            raise ValueError(f"unknown run_length status {status}")
        caveat = ""
        if _bool(run["baseline_lower_bound"]):
            caveat = f" (이전 러닝 {_int(run['previous_without_distance'])}개 거리 없음, 최장이 더 길 수 있음)"
        lines.append(
            f"러닝 길이 {_month_day(run['date'])}: {_km(_number(run['distance_meters']))} km, 지난 {previous_days}일 "
            f"최장보다 {_text(run['increase_percent'])} % 김{caveat} {_RUN_TAG}"
        )
    return lines


def _goal_plateau_lines(value: Any) -> list[str]:
    """Cut only (null otherwise). `insufficient_measurements` is "not known", never "not a plateau"."""
    if value is None:
        return []
    plateau = _object(value)
    status = _text(plateau["status"])
    options = [_object(item) for item in _list(plateau["options"])]
    if options and status != "met":
        raise ValueError(f"plateau options with status {status}")
    if status in ("met", "not_met"):
        setting = (
            f"내 설정 {_int(plateau['weeks'])}주, {_text(plateau['below_loss_percent_per_week'])} %/주 미만 감량, "
            f"InBody 구간 {_int(plateau['min_intervals'])}개 이상"
        )
        if status == "not_met":
            return [f"정체 확인: 조건 미충족 ({setting}) {_PLATEAU_TAG}"]
        if [_text(item) for item in _list(plateau["choice_evidence"])] != _CHOICE_EVIDENCE:
            raise ValueError("unexpected plateau choice evidence")
        noise = _text(_object(plateau["noise"])["within_week_weight_percent"])
        lines = [
            f"정체 확인: 조건 충족 ({setting}) {_PLATEAU_TAG}",
            f"  체중은 주 안에서 약 {noise} % 오르내림, 같은 기기·조건 InBody끼리 비교 [PLAT-02]",
            "  선택지, 순위 없음 (표시 순서) [PLAT-06]; 내 선호·지킬 수 있는 것도 정당한 기준 [FATEX-07]",
        ]
        for option in options:
            lines.extend(_option_lines(option))
        return lines
    if status == "insufficient_measurements":
        return [f"정체 확인: 판단 못 함, 정체 여부 모름 ({_text(plateau['reason'])}) [design: user setting; PLAT-02]"]
    if status == "unknown":
        return [f"정체 확인: {UNKNOWN} ({_text(plateau['reason'])}) {_USER_SETTING_TAG}"]
    if status == "not_set":
        return ["정체 확인: 설정 안 함 (근거로 정한 기준 없음; goal set ... --plateau-weeks N) [design; PLAT-01]"]
    raise ValueError(f"unknown plateau status {status}")


def _option_lines(option: dict[str, Any]) -> list[str]:
    """One option, unranked (a fixed display letter per code); every tag sits next to the content it supports."""
    code = _text(option["code"])
    expected = _OPTION_EVIDENCE.get(code)
    if expected is None:
        raise ValueError(f"unknown plateau option {code}")
    if tuple(_text(item) for item in _list(option["evidence"])) != expected:
        raise ValueError(f"unexpected evidence for plateau option {code}")
    if code == "check_meal_logging":
        return ["  a) 식사 기록이 빠짐없는지 확인 (빠진 끼니, 일반식, 주말) [PLAT-04]"]
    if code == "eat_less":
        if _bool(option["deficit_measurable"]):
            raise ValueError("the eat_less line says muscle50 cannot measure the deficit")
        step = _object(option["step_kcal_per_day"])
        return [
            f"  b) 하루 {_int(step['minimum'])}-{_int(step['maximum'])} kcal 덜 먹기 [design]; 결손은 약 "
            f"{_int(option['deficit_limit_kcal_per_day'])} kcal/일 이하, muscle50은 결손을 잴 수 없음 [PRO-04]"
        ]
    if code == "keep_intake_add_activity":
        return [
            "  c) 섭취는 두고 활동 늘리기: 같은 결손이면 같은 지방 감소, 활동 뒤 더 먹으면 결손 일부가 "
            "상쇄될 수 있음(개인차 큼) [FATEX-05, FATEX-04]",
            f"     러닝 길이·러닝/하체 {_int(option['run_legs_gap_hours'])}시간 간격 주의 [RUNPROG-03, CONC-04]",
        ]
    weeks = _int(option["weeks"])
    return [f"  d) {weeks}주 유지 휴식: 체중이 글리코겐·수분으로 오를 수 있고 기한이 {weeks}주 늦어짐 [PLAT-05]"]


def unknown_list(document: Any) -> BotReply:
    notices = _list(_object(_object(document)["strength"])["unknown_notices"])
    window = f"최근 {UNKNOWN_NOTICE_DAYS}일, 오늘 운동 제외"
    if not notices:
        return BotReply(f"Garmin UNKNOWN 세트가 있는 운동 없음 ({window})")
    groups = _unknown_groups(notices, with_sequences=True)
    groups.append((("Garmin Connect에서 운동 이름을 고친 뒤 /refresh로 다시 받습니다.",),))
    groups.append(((REFRESH_ALL_LINE,),))
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


# --- bare /refresh (v1.2) ------------------------------------------------------------------------------

_STOP_REASONS = {
    RefreshStop.CONSECUTIVE_FAILURES: f"연속 {MAX_CONSECUTIVE_REFRESH_FAILURES}번 실패",
    RefreshStop.GARMIN_LOGIN: "Garmin 로그인 필요",
    RefreshStop.UNEXPECTED_ERROR: "예상하지 못한 오류",
}


def refresh_targets(document: Any) -> tuple[RefreshTarget, ...]:
    """The `/unknown` list of a `recommend --json` document, in JSON order (newest first)."""
    targets = []
    for entry in _list(_object(_object(document)["strength"])["unknown_notices"]):
        notice = _object(entry)
        local_date = _text(notice["local_date"])
        _month_day(local_date)
        targets.append(
            RefreshTarget(_activity_id(notice["source_activity_id"]), local_date, _int(notice["unknown_set_count"]))
        )
    return tuple(targets)


def refresh_all_reply(result: BulkRefreshResult) -> BotReply:
    """One line per activity (before/after, failure verbatim, or not run), then what to do next."""
    statuses = [item.status for item in result.items]
    header = (
        f"refresh {'완료' if result.stopped is None else '중단'}: "
        f"{len(result.items)}개 중 {statuses.count(RefreshItemStatus.DONE)}개 받음"
    )
    failed = statuses.count(RefreshItemStatus.FAILED)
    if failed:
        header += f", {failed}개 실패"
    not_run = statuses.count(RefreshItemStatus.NOT_RUN)
    if not_run:
        header += f", {not_run}개 받지 않음"
    if result.stopped is not None:
        header += f" ({_STOP_REASONS[result.stopped]})"
    lines = [header]
    for item in result.items:
        lines.extend(_refresh_item_lines(item))
    if result.stop_detail is not None:
        if result.stopped is RefreshStop.GARMIN_LOGIN:
            lines.append(refresh_login_text(result.stop_detail))
        elif result.stopped is RefreshStop.UNEXPECTED_ERROR:
            lines.append(unexpected_error_text(result.stop_detail))
    tail: list[tuple[RichLine, ...]] = []
    if result.stopped is RefreshStop.CONSECUTIVE_FAILURES:
        tail.append((("Garmin 쪽 제한이나 장애일 수 있습니다. 잠시 뒤 다시 받기: /refresh",),))
    elif result.stopped is RefreshStop.GARMIN_LOGIN:
        tail.append((("로그인한 뒤 나머지 다시 받기: /refresh",),))
    if result.over_cap > 0:
        tail.append(
            (
                (
                    f"나머지 {result.over_cap}개는 받지 않았습니다(한 번에 {REFRESH_ALL_CAP}개까지). "
                    "다시 받기: /refresh · 목록: /unknown",
                ),
            )
        )
    if result.remaining is None:
        remaining = f"남은 UNKNOWN: {UNKNOWN} · /unknown"  # never 0 for a count that could not be read
    elif result.remaining == 0:
        remaining = f"남은 UNKNOWN 운동 없음 (최근 {UNKNOWN_NOTICE_DAYS}일, 오늘 운동 제외)"
    else:
        remaining = f"남은 UNKNOWN: {result.remaining}개 운동 · /unknown"
    tail.append(((remaining,),))
    return BotReply("\n".join(lines), tuple(tail))


def _refresh_item_lines(item: RefreshItem) -> list[str]:
    target = item.target
    head = f"• {_month_day(target.local_date)} {target.source_activity_id}: "
    if item.status is RefreshItemStatus.NOT_RUN:
        return [f"{head}받지 않음"]
    if item.status is RefreshItemStatus.FAILED:
        errors = item.error.split("\n") if item.error is not None else []
        return [f"{head}실패", *(f"  {line}" for line in errors)]
    before, after = item.before, item.after
    if before is not None and after is not None and before.is_strength and after.is_strength:
        old, new = before.unknown_set_count, after.unknown_set_count
        text = f"UNKNOWN {old} → {new}세트"
        if new > 0:
            # An equal count does not prove that Garmin was not changed, so it is not called "not fixed yet".
            text += " (변화 없음)" if new == old else " (아직 남음)"
    else:
        text = item.cli_stdout.split("\n", 1)[0]  # no count to compare: the CLI headline, as `/refresh <id>`
    warnings = [f"  {line}" for line in item.cli_stdout.split("\n") if line.startswith("경고: ")]
    return [f"{head}{text}", *warnings]


_BUILDERS: dict[ReplyKind, Callable[[Any], BotReply]] = {
    ReplyKind.TODAY_SUMMARY: today_summary,
    ReplyKind.DAILY_SUMMARY: daily_summary,
    ReplyKind.STATUS_SUMMARY: status_summary,
    ReplyKind.UNKNOWN_LIST: unknown_list,
    ReplyKind.SYNC_SUMMARY: sync_summary,
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


def _date(value: Any) -> date:
    return date.fromisoformat(_text(value))


def _activity_id(value: Any) -> str:
    """Checked to be ASCII digits before it goes into a link or a command."""
    text = _text(value)
    if _ASCII_DIGITS.fullmatch(text) is None:
        raise ValueError("activity id is not ASCII digits")
    return text
