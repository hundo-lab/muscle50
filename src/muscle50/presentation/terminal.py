"""Plain terminal summary output."""

from __future__ import annotations

from muscle50.application.sync_latest_garmin import SyncResult
from muscle50.domain.activity import ActivityMetric, ActivityType, StrengthSet
from muscle50.domain.derivation import derive_summary

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
    elif activity.canonical_type is ActivityType.STRENGTH:
        if activity.strength_sets:
            _strength_set_lines(lines, activity.strength_sets)
        else:
            _metric_line(lines, metrics, "set_count", "세트", "")
            _metric_line(lines, metrics, "rep_count", "반복", "")

    lines.extend(f"경고: {warning}" for warning in result.warnings)
    return "\n".join(lines)


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
