"""Plain terminal summary output."""

from __future__ import annotations

from muscle50.application.sync_latest_garmin import SyncResult
from muscle50.domain.activity import ActivityMetric, ActivityType
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
