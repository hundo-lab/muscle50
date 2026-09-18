"""Plain terminal summary output."""

from __future__ import annotations

from muscle50.application.ingest_activity_range import RangeIngestResult
from muscle50.application.sync_garmin_recovery import RecoverySyncResult
from muscle50.application.sync_latest_garmin import SyncResult
from muscle50.domain.activity import ActivityMetric, ActivityType, StrengthSet
from muscle50.domain.derivation import derive_summary
from muscle50.domain.swimming import NormalizedSwimActivity, derive_lap_metrics

_TYPE_LABELS = {
    ActivityType.RUNNING: "러닝",
    ActivityType.SWIMMING: "수영",
    ActivityType.STRENGTH: "웨이트",
    ActivityType.CYCLING: "사이클링",
    ActivityType.WALKING: "걷기",
    ActivityType.OTHER: "기타",
}


def render_sync_result(result: SyncResult) -> str:
    activity = result.activity
    state = "새 activity 저장 완료" if result.created else "이미 저장된 activity (변경 없음)"
    lines = [
        state,
        f"Garmin activity ID: {activity.source_activity_id}",
        f"종류: {_TYPE_LABELS[activity.canonical_type]} ({activity.source_type_key})",
    ]
    if activity.name:
        lines.append(f"이름: {activity.name}")
    if activity.started_at_local or activity.started_at_utc:
        lines.append(f"시작: {activity.started_at_local or activity.started_at_utc}")
    if activity.elapsed_seconds is not None:
        lines.append(f"시간: {_duration(activity.elapsed_seconds)}")
    if activity.distance_meters is not None:
        lines.append(f"거리: {activity.distance_meters / 1000:.2f} km")
    if activity.calories_kcal is not None:
        lines.append(f"칼로리: {activity.calories_kcal:.0f} kcal")
    if activity.average_hr_bpm is not None:
        lines.append(f"평균 심박: {activity.average_hr_bpm:.0f} bpm")

    metrics = {metric.key: metric for metric in activity.metrics}
    if activity.canonical_type is ActivityType.RUNNING:
        pace = derive_summary(activity).pace_seconds_per_km
        if pace is not None:
            lines.append(f"평균 페이스: {int(pace // 60)}:{int(pace % 60):02d} /km")
    elif activity.canonical_type is ActivityType.SWIMMING:
        _metric_line(lines, metrics, "pool_length", "풀 길이")
        _metric_line(lines, metrics, "lap_count", "랩", "")
        _metric_line(lines, metrics, "average_swolf", "평균 SWOLF", "")
        if activity.swim_detail is not None:
            _swim_detail_lines(lines, activity.swim_detail, activity.distance_meters)
    elif activity.canonical_type is ActivityType.STRENGTH:
        if activity.strength_sets:
            _strength_set_lines(lines, activity.strength_sets)
        else:
            _metric_line(lines, metrics, "set_count", "세트", "")
            _metric_line(lines, metrics, "rep_count", "반복", "")

    lines.extend(f"경고: {warning}" for warning in result.warnings)
    return "\n".join(lines)


def render_range_result(result: RangeIngestResult) -> str:
    lines = [
        f"기간: {result.from_date.isoformat()} ~ {result.to_date.isoformat()}",
        f"발견: {result.discovered_count}건",
        f"신규 저장: {result.inserted_count}건",
        f"이미 저장됨: {result.skipped_count}건",
        f"실패: {result.failed_count}건",
    ]
    if result.undated_count:
        lines.append(f"시작 시각 확인 불가로 제외: {result.undated_count}건")
    if result.page_limit_reached:
        lines.append("경고: 페이지 조회 한도에 도달해 전체 기간을 확인하지 못했을 수 있습니다.")
    for outcome in result.outcomes:
        if outcome.status == "failed":
            lines.append(f"실패: Garmin activity ID {outcome.source_activity_id} ({outcome.source_type_key})")
    return "\n".join(lines)


def render_recovery_sync_result(result: RecoverySyncResult) -> str:
    recovery = result.recovery
    if result.created:
        state = "새 recovery 저장 완료"
    elif result.updated:
        state = "recovery 갱신 완료"
    else:
        state = "이미 저장된 recovery (변경 없음)"
    lines = [state, "", f"Recovery — {recovery.calendar_date}"]
    lines.append(
        f"Sleep: {_duration(recovery.sleep_seconds) if recovery.sleep_seconds is not None else 'unavailable'}"
    )
    lines.append(f"Sleep Score: {_number(recovery.sleep_score)}")
    lines.append(f"HRV: {_number(recovery.hrv_last_night_avg_ms, ' ms')}")
    lines.append(f"Resting HR: {_number(recovery.resting_heart_rate_bpm, ' bpm')}")
    if recovery.body_battery_high is None and recovery.body_battery_low is None:
        lines.append("Body Battery: unavailable")
    else:
        lines.append(
            f"Body Battery: high {_number(recovery.body_battery_high)} / low {_number(recovery.body_battery_low)}"
        )
    lines.append(f"Stress: {_number(recovery.stress_average)}")
    readiness_suffix = f" ({recovery.training_readiness_level})" if recovery.training_readiness_level else ""
    readiness = _number(recovery.training_readiness_score)
    lines.append(f"Training Readiness: {readiness}{readiness_suffix if readiness != 'unavailable' else ''}")
    lines.append(f"Recovery Time: {_number(recovery.recovery_time_minutes, ' min')}")
    lines.append(f"Training Status: {recovery.training_status_key or 'unavailable'}")
    lines.append(f"Respiration: {_number(recovery.respiration_avg_brpm, ' brpm')}")
    lines.extend(f"경고: {warning}" for warning in result.warnings)
    return "\n".join(lines)


def _number(value: float | int | None, suffix: str = "") -> str:
    if value is None:
        return "unavailable"
    rendered = f"{value:g}" if isinstance(value, float) else str(value)
    return f"{rendered}{suffix}"


def _metric_line(
    lines: list[str],
    metrics: dict[str, ActivityMetric],
    key: str,
    label: str,
    unit: str | None = None,
) -> None:
    metric = metrics.get(key)
    if metric is not None:
        display_unit = metric.unit if unit is None else unit
        suffix = f" {display_unit}" if display_unit else ""
        rendered = f"{metric.value:g}" if isinstance(metric.value, float) else str(metric.value)
        lines.append(f"{label}: {rendered}{suffix}")


def _duration(seconds: float) -> str:
    total = int(seconds)
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def _swim_detail_lines(
    lines: list[str],
    swim: NormalizedSwimActivity,
    activity_distance_meters: float | None,
) -> None:
    lap_metrics = [(lap, derive_lap_metrics(lap)) for lap in swim.laps]
    distances = [
        metric.effective_distance_meters
        for _lap, metric in lap_metrics
        if metric.effective_distance_meters is not None and metric.effective_distance_meters > 0
    ]
    distance = sum(distances) if distances else activity_distance_meters
    length_count = sum(len(lap.lengths) for lap in swim.laps)

    lines.extend(("", "Swim"))
    if distance is not None:
        lines.append(f"Distance: {distance:g} m")
    lines.append(f"Laps: {len(swim.laps)}")
    lines.append(f"Lengths: {length_count}")

    timed_distance = 0.0
    timed_duration = 0.0
    for lap, metric in lap_metrics:
        if (
            metric.effective_distance_meters is not None
            and metric.effective_distance_meters > 0
            and lap.duration_seconds is not None
            and lap.duration_seconds > 0
        ):
            timed_distance += metric.effective_distance_meters
            timed_duration += lap.duration_seconds
    if timed_distance > 0:
        pace = timed_duration * 100 / timed_distance
        lines.append(f"Average pace: {int(pace // 60)}:{int(pace % 60):02d} /100m")


def _strength_set_lines(lines: list[str], strength_sets: tuple[StrengthSet, ...]) -> None:
    active_sets = [item for item in strength_sets if item.set_type == "ACTIVE"]
    rest_sets = [item for item in strength_sets if item.set_type == "REST"]
    by_exercise: dict[str, list[StrengthSet]] = {}
    for strength_set in active_sets:
        name = strength_set.display_exercise_name or "Unknown Exercise"
        by_exercise.setdefault(name, []).append(strength_set)

    for name, exercise_sets in by_exercise.items():
        lines.append("")
        lines.append(name)
        lines.extend(f"  {_strength_set_value(item)}" for item in exercise_sets)

    lines.append("")
    if all(item.reps is not None for item in active_sets):
        total_reps = sum(item.reps for item in active_sets if item.reps is not None)
        lines.append(f"총 {len(active_sets)}세트 / {total_reps}회")
    else:
        lines.append(f"총 {len(active_sets)}세트 / 반복수 미제공")
    if rest_sets:
        lines.append(f"휴식 구간: {len(rest_sets)}개 (운동 세트/반복 합계 제외)")


def _strength_set_value(strength_set: StrengthSet) -> str:
    if strength_set.normalized_weight_kg is not None:
        weight = f"{strength_set.normalized_weight_kg:g} kg"
    elif strength_set.source_weight is not None:
        unit = f" {strength_set.source_weight_unit}" if strength_set.source_weight_unit else " (단위 미제공)"
        weight = f"{strength_set.source_weight:g}{unit}"
    else:
        weight = "중량 미제공"

    reps = str(strength_set.reps) if strength_set.reps is not None else "반복수 미제공"
    return f"{weight} × {reps}"
