"""Plain terminal summary output."""

from __future__ import annotations

import dataclasses
import json
from datetime import date

from muscle50.application.backfill_activity_load_metrics import ActivityLoadBackfillResult
from muscle50.application.daily_sync import (
    STAGE_ACTIVITIES,
    STAGE_LOAD_METRICS,
    STAGE_RECOVERY,
    DailyMode,
    DailySyncResult,
)
from muscle50.application.imported_load_metrics import ImportedLoadMetricsResult
from muscle50.application.ingest_activity_range import RangeIngestResult
from muscle50.application.nutrition_recommendation import NutritionContext
from muscle50.application.refresh_garmin_activity import ActivityRefreshResult
from muscle50.application.renormalize_garmin_recovery import RecoveryRenormalizeResult
from muscle50.application.sync_garmin_recovery import RecoveryRangeSyncResult, RecoverySyncResult
from muscle50.application.sync_latest_garmin import SyncResult
from muscle50.domain.activity import ActivityMetric, ActivityType, StrengthSet
from muscle50.domain.analytics import (
    MAX_PLAUSIBLE_SWIM_SPEED_MPS,
    LabelOriginCounts,
    MetricAggregate,
    RecoveryRule,
    StrengthTaxonomySummary,
    TaxonomyGroup,
    TrainingSnapshot,
)
from muscle50.domain.derivation import derive_summary
from muscle50.domain.recovery_assessment import RecoveryObservation
from muscle50.domain.strength_recommendation import (
    LOAD_STEP_SMALLEST_AVAILABLE_DIRECTION_UNKNOWN,
    PlannedExercise,
    ProgressionAction,
    kg_text,
)
from muscle50.domain.swim_recommendation import SwimSegment, pace_text
from muscle50.domain.swimming import NormalizedSwimActivity, derive_lap_metrics
from muscle50.domain.training_recommendation import TrainingRecommendation
from muscle50.presentation.nutrition_terminal import nutrition_context_lines, nutrition_context_payload

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


def render_refresh_result(result: ActivityRefreshResult) -> str:
    lines = [
        "Garmin activity refresh complete",
        f"Garmin activity ID: {result.activity.source_activity_id}",
        f"RAW snapshot: {result.capture.manifest_relative_path}",
        f"Strength sets replaced: {result.strength_set_count}",
        f"Swim laps/lengths replaced: {result.swim_lap_count}/{result.swim_length_count}",
    ]
    for reason in result.review.reasons:
        sequences = ", ".join(str(item) for item in reason.set_sequences)
        lines.append(f"Review warning: {reason.code.value} (sets: {sequences})")
    if not result.review.required:
        lines.append("Review warnings remaining: none")
    lines.extend(f"경고: {warning}" for warning in result.warnings)
    return "\n".join(lines)


def render_recovery_sync_result(result: RecoverySyncResult) -> str:
    recovery = result.recovery
    if result.created:
        state = "새 recovery 저장 완료"
    elif result.updated:
        state = "recovery 갱신 완료"
    else:
        state = "이미 저장된 recovery (변경 없음)"
    lines = [state, "", f"Recovery: {recovery.calendar_date}"]
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


def render_recovery_range_result(result: RecoveryRangeSyncResult) -> str:
    lines = [
        f"Recovery 기간: {result.from_date.isoformat()} ~ {result.to_date.isoformat()}",
        f"요청 날짜: {len(result.outcomes)}일",
        f"신규 저장: {result.count('created')}일",
        f"갱신: {result.count('updated')}일",
        f"변경 없음: {result.count('unchanged')}일",
        f"실패: {result.count('failed')}일",
        f"미시도: {result.count('not_attempted')}일",
    ]
    for outcome in result.outcomes:
        if outcome.status == "failed":
            lines.append(f"실패: {outcome.calendar_date} ({outcome.error})")
        elif outcome.status == "not_attempted":
            lines.append(f"미시도: {outcome.calendar_date}")
        elif outcome.result is not None and outcome.result.warnings:
            lines.append(f"경고: {outcome.calendar_date} endpoint 경고 {len(outcome.result.warnings)}건")
    if result.aborted_reason is not None:
        lines.append(f"중단: {result.aborted_reason}")
    return "\n".join(lines)


def render_recovery_renormalize_result(result: RecoveryRenormalizeResult) -> str:
    lines = [
        "Recovery re-normalization from stored RAW (dry run, nothing written)"
        if result.dry_run
        else "Recovery re-normalization from stored RAW complete",
        f"Dates examined: {result.dates_examined}",
        f"Dates updated: {len(result.dates_updated)}",
        f"Dates unchanged: {len(result.dates_unchanged)}",
        f"Dates failed: {len(result.failures)}",
    ]
    lines.extend(f"Field changed: {name} ({count} dates)" for name, count in result.field_changes.items())
    lines.extend(f"Failed: {failure.calendar_date} ({failure.error})" for failure in result.failures)
    return "\n".join(lines)


def render_activity_load_backfill_result(result: ActivityLoadBackfillResult) -> str:
    lines = [
        "Activity load metric backfill (dry run, nothing written)"
        if result.dry_run
        else "Activity load metric backfill complete",
        f"Activities examined: {result.activities_examined}",
        f"RAW summaries found: {result.raw_summaries_found}",
        f"Activities changed: {result.activities_changed}",
        f"Metric rows inserted: {result.metrics_inserted}",
        f"Metric rows updated: {result.metrics_updated}",
        f"Metrics already identical: {result.metrics_unchanged}",
        f"Missing RAW: {len(result.missing_raw)}",
        f"Unreadable RAW: {len(result.unreadable_raw)}",
        f"Malformed values: {len(result.malformed_values)}",
        f"Skipped values (missing/null): {len(result.skipped_values)}",
    ]
    lines.extend(f"Missing RAW: {activity_id}" for activity_id in result.missing_raw)
    lines.extend(f"Unreadable RAW: {activity_id}" for activity_id in result.unreadable_raw)
    lines.extend(
        f"Malformed: {item.source_activity_id} {item.issue.source_key}" for item in result.malformed_values
    )
    lines.extend(
        f"Skipped ({item.issue.kind}): {item.source_activity_id} {item.issue.source_key}"
        for item in result.skipped_values
    )
    return "\n".join(lines)


def render_imported_load_metrics(result: ImportedLoadMetricsResult) -> str:
    # The last stdout lines of `garmin latest`/`garmin activities`. ASCII labels (cp949 consoles), daily's
    # judgement texts; a backfill exception message is printed as received, as daily does.
    lines: list[str] = []
    backfill = result.backfill
    if backfill is not None:
        lines.append(
            f"Load metrics: metric rows inserted {backfill.metrics_inserted}, updated {backfill.metrics_updated}, "
            f"unchanged {backfill.metrics_unchanged}"
        )
    lines.extend(f"Load metrics warning: {warning}" for warning in result.warnings)
    if result.error is not None:
        lines.append(f"Load metrics failed: {result.error}")
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


def render_training_snapshot_json(snapshot: TrainingSnapshot) -> str:
    """Full snapshot including provenance; ASCII-only and stable for identical input."""
    return json.dumps(dataclasses.asdict(snapshot), indent=2, ensure_ascii=True, default=_json_default)


def render_training_snapshot(snapshot: TrainingSnapshot) -> str:
    # ASCII only: Windows cp949 consoles cannot encode some punctuation (see recovery output).
    window = snapshot.window
    lines = [
        f"Training snapshot: {window.start.isoformat()} ~ {window.as_of.isoformat()} "
        f"({window.lookback_days} days, analytics v{snapshot.analytics_version})",
        "Missing values are shown as unavailable, never as zero. [rule, n/m] = sources with a value.",
    ]

    overview = snapshot.activities
    lines.extend(("", f"Activities: {overview.activity_count} (training days: {len(overview.training_dates)})"))
    lines.extend(f"  {item.canonical_type}/{item.source_type_key}: {item.count}" for item in overview.by_type)
    lines.append(f"  Elapsed: {_aggregate_text(overview.elapsed_seconds, duration=True)}")
    if overview.activity_count:
        lines.append("  Load (window totals, not Garmin acute load; training effect = session max):")
        lines.extend(f"    {item.key}: {_aggregate_text(item)}" for item in overview.load_metrics)

    strength = snapshot.strength
    lines.extend(("", f"Strength: {strength.session_count} sessions"))
    if strength.session_count:
        excluded = strength.volume_exclusions
        lines.extend(
            (
                f"  Active sets: {strength.active_set_count} (rest rows {strength.rest_set_count})",
                f"  Reps: {_optional(strength.reps)} (sets missing reps {strength.sets_missing_reps}, "
                f"0-rep sets {strength.zero_rep_sets})",
                f"  Volume: {_optional(strength.volume_kg, ' kg')} from {strength.volume_set_count} sets "
                f"(excluded: missing reps {excluded.missing_reps}, zero reps {excluded.zero_reps}, "
                f"missing weight {excluded.missing_weight}, negative weight {excluded.negative_weight}, "
                f"zero weight {excluded.zero_weight})",
                f"  Unclassified ACTIVE sets: {strength.unclassified_active_set_count}",
                "  Exercises:",
            )
        )
        for exercise in strength.exercises:
            name = exercise.display_name or exercise.exercise_key or "Unclassified"
            flag = "" if exercise.classified else " (unclassified)"
            lines.append(
                f"    {name} [{exercise.category or 'no category'}]{flag}: {exercise.active_set_count} sets, "
                f"reps {_optional(exercise.reps)}, volume {_optional(exercise.volume_kg, ' kg')}, "
                f"max {_optional(exercise.max_weight_kg, ' kg')}"
            )
        _taxonomy_lines(lines, strength.taxonomy)

    swimming = snapshot.swimming
    lines.extend(("", f"Swimming: {swimming.session_count} sessions"))
    if swimming.session_count:
        pools = ", ".join(_fixed(item) for item in swimming.pool_lengths_meters) or "unavailable"
        lines.extend(
            (
                f"  Garmin summary distance: {_aggregate_text(swimming.summary_distance_meters)}",
                f"  Lap detail distance: {_aggregate_text(swimming.detail_distance_meters)}",
                f"  Plausible lap detail distance (laps <= {MAX_PLAUSIBLE_SWIM_SPEED_MPS:g} m/s): "
                f"{_aggregate_text(swimming.plausible_detail_distance_meters)}",
                f"  Elapsed: {_aggregate_text(swimming.elapsed_seconds, duration=True)}",
                f"  Moving: {_aggregate_text(swimming.moving_seconds, duration=True)}",
                f"  Pool lengths: {pools} m",
                f"  Implausible laps: {swimming.implausible_lap_count}, "
                f"implausible lengths in plausible laps: {swimming.implausible_length_count}",
                "  Sessions:",
            )
        )
        for session in swimming.sessions:
            marker = (
                " [summary includes implausible laps]" if session.summary_distance_includes_implausible_laps else ""
            )
            lines.append(
                f"    {session.local_date.isoformat()} {session.source_activity_id}: "
                f"summary {_optional(session.summary_distance_meters, ' m')}, "
                f"plausible detail {_optional(session.plausible_detail_distance_meters, ' m')}, "
                f"pool {_optional(session.pool_length_meters, ' m')}, laps {session.lap_count}, "
                f"lengths {session.length_count}{marker}"
            )
        lines.append("  Load (swimming only):")
        lines.extend(f"    {item.key}: {_aggregate_text(item)}" for item in swimming.load_metrics)

    recovery = snapshot.recovery
    missing_days = ", ".join(item.isoformat() for item in recovery.dates_without_row) or "none"
    lines.extend(
        (
            "",
            f"Recovery: {len(recovery.dates_with_row)}/{recovery.requested_day_count} days with a row "
            f"(no row: {missing_days})",
        )
    )
    for numeric in recovery.numeric_fields:
        count = f"[{len(numeric.available_dates)}/{len(recovery.dates_with_row)}]"
        if numeric.latest_value is None:
            lines.append(f"  {numeric.field}: unavailable {count}")
            continue
        duration = numeric.unit == "s"
        latest = (
            f"latest {_value_text(numeric.latest_value, numeric.unit, duration)} ({_date_text(numeric.latest_date)})"
        )
        if numeric.rule is RecoveryRule.DAILY:
            lines.append(
                f"  {numeric.field}: {latest}, mean {_value_text(numeric.mean, numeric.unit, duration)}, "
                f"min {_value_text(numeric.minimum, numeric.unit, duration)}, "
                f"max {_value_text(numeric.maximum, numeric.unit, duration)} {count}"
            )
        else:
            lines.append(f"  {numeric.field}: {latest} {count}")
    for categorical in recovery.categorical_fields:
        if categorical.latest_value is None:
            lines.append(f"  {categorical.field}: unavailable")
        else:
            lines.append(
                f"  {categorical.field}: latest {categorical.latest_value} ({_date_text(categorical.latest_date)})"
            )

    lines.extend(("", f"Quality issues: {len(snapshot.quality_issues)}"))
    lines.extend(
        f"  {issue.code.value} {issue.source_activity_id or '-'}: {issue.detail}" for issue in snapshot.quality_issues
    )
    return "\n".join(lines)


def _taxonomy_lines(lines: list[str], taxonomy: StrengthTaxonomySummary) -> None:
    origins = taxonomy.mapped_label_origins
    unknown_ids = ", ".join(taxonomy.unknown_source_activity_ids) or "none"
    lines.extend(
        (
            f"  Exercise taxonomy v{taxonomy.taxonomy_version}: {taxonomy.mapped_active_set_count}/"
            f"{taxonomy.active_set_count} ACTIVE sets mapped, {taxonomy.unmapped_active_set_count} unmapped "
            f"(UNKNOWN {taxonomy.unknown_active_set_count}, no rule {taxonomy.no_rule_active_set_count})",
            f"    Mapped Garmin labels: {_origins_text(origins)}",
            f"    UNKNOWN activities ({len(taxonomy.unknown_source_activity_ids)}): {unknown_ids}",
            "    Primary muscle (active sets, each set counted once):",
        )
    )
    lines.extend(_group_lines(taxonomy.by_primary_muscle))
    lines.append("    Movement pattern (active sets):")
    lines.extend(_group_lines(taxonomy.by_movement_pattern))
    lines.append("    Secondary muscle set exposures (not added to primary totals):")
    lines.extend(_group_lines(taxonomy.secondary_muscle_set_exposures))
    lines.append("    Garmin exercise label (active sets):")
    for item in taxonomy.by_exercise:
        label = f"{item.category or 'no category'}/{item.exercise_name or '-'}"
        if item.primary_muscle is None:
            mapping = f"unmapped: {item.unmapped_reason}"
        else:
            secondary = ", ".join(item.secondary_muscles) or "none"
            mapping = f"{item.movement_pattern}, primary {item.primary_muscle}, secondary {secondary}"
        lines.append(f"      {label}: {item.active_set_count} [{mapping}] ({_origins_text(item.label_origins)})")
    if not taxonomy.by_exercise:
        lines.append("      none")


def _group_lines(groups: tuple[TaxonomyGroup, ...]) -> list[str]:
    if not groups:
        return ["      none"]
    return [f"      {item.key}: {item.active_set_count} ({_origins_text(item.label_origins)})" for item in groups]


def _origins_text(origins: LabelOriginCounts) -> str:
    text = f"confirmed {origins.confirmed}, auto-detected {origins.auto_detected}"
    return f"{text}, unspecified {origins.unspecified}" if origins.unspecified else text


def render_training_recommendation_json(
    recommendation: TrainingRecommendation, nutrition: NutritionContext | None = None
) -> str:
    """Full recommendation with evidence; ASCII-only and stable for identical input.

    The training fields are unchanged; a nutrition context adds one trailing ``nutrition`` key.
    """
    payload = dataclasses.asdict(recommendation)
    if nutrition is not None:
        payload["nutrition"] = nutrition_context_payload(nutrition)
    return json.dumps(payload, indent=2, ensure_ascii=True, default=_json_default)


def render_training_recommendation(
    recommendation: TrainingRecommendation, nutrition: NutritionContext | None = None
) -> str:
    # ASCII only (cp949 consoles); Garmin activity names are never printed.
    strength = recommendation.strength
    goals = recommendation.goals
    lines = [
        f"Training recommendation for {recommendation.as_of.isoformat()} "
        f"(v{recommendation.recommendation_version}; history from {recommendation.history_start.isoformat()})",
        "Deterministic rules on stored data only. Rules: docs/training-recommendation.md",
        "",
        "== Strength ==",
    ]
    if strength.focus is None:
        lines.append("Focus: none (no usable strength history)")
    elif strength.focus_source == "user":
        automatic = f"automatic would be {strength.auto_focus}" if strength.auto_focus else "no automatic choice"
        lines.append(
            f"Focus: {strength.focus} ({', '.join(strength.focus_muscles)}) [user-selected; {automatic}]"
        )
    else:
        lines.append(f"Focus: {strength.focus} ({', '.join(strength.focus_muscles)}) [auto-selected]")
    lines.extend(f"  - {reason}" for reason in strength.reasons)
    lines.append("  Regions (ranked):")
    for region in strength.regions:
        due = f"{region.due_ratio:g}" if region.due_ratio is not None else "-"
        flags = [
            name
            for name, value in (
                ("resting", not region.eligible),
                ("neglected", region.neglected),
                ("swim overlap", region.swim_demoted),
                ("reduce-recent", region.recently_trained_under_reduce),
            )
            if value
        ]
        lines.append(
            f"    {region.region}: due {due} (interval {region.personal_interval_days:g} d), "
            f"{region.sets_last_7_days} sets/7 d, yesterday {region.sets_previous_day}"
            f"{' [' + ', '.join(flags) + ']' if flags else ''}"
        )
    if strength.exercises:
        lines.append(
            f"Session: {len(strength.exercises)} exercises, {strength.working_sets} working sets, "
            f"about {strength.estimated_minutes} min (goal {strength.session_minutes_goal} min); "
            f"stop {goals.reps_in_reserve_min}-{goals.reps_in_reserve_max} reps short of failure "
            "(advice; reps in reserve is not recorded)"
        )
    for index, exercise in enumerate(strength.exercises, start=1):
        lines.append(f"  {index}. [{exercise.role.value}] {exercise.label}: {_prescription(exercise)}")
        lines.append(
            f"       {exercise.primary_muscle} / {exercise.movement_pattern}; "
            f"{exercise.sessions_last_28_days} sessions, {exercise.active_sets_last_28_days} sets in 28 days; "
            f"last {exercise.last_performed.isoformat()}"
        )
        lines.extend(f"       adjustment: {text}" for text in exercise.adjustments)
    if strength.focus_coverage:
        lines.append("  Focus coverage (primary muscle):")
        lines.extend(f"    {item.muscle}: {item.status} - {item.note}" for item in strength.focus_coverage)
    if strength.alternative is not None:
        alternative = strength.alternative
        lines.append(f"  Optional alternative for {alternative.replaces_label}: {alternative.label}")
        lines.append(f"       {alternative.reason}")

    lines.extend(("", "== Progression targets =="))
    for exercise in strength.exercises:
        progression = exercise.progression
        lines.append(f"  {exercise.label} [{progression.action.value}, load confidence {progression.load_confidence}]")
        lines.extend(f"    - {text}" for text in progression.basis)
        lines.extend(f"    ! {text}" for text in progression.caveats)
        if progression.load_guidance:
            lines.append(f"    > load: {progression.load_guidance}")

    recovery = recommendation.recovery
    heading = f"Recovery adjustment: {recovery.level.value}"
    if strength.adjustment_level != recovery.level.value:
        # The session level was raised by a non-recovery rule (yesterday's training load).
        heading += f"; session adjustment: {strength.adjustment_level}"
    lines.extend(("", f"== {heading} =="))
    lines.extend(f"  {_observation_text(item)}" for item in recovery.observations)
    if recovery.lookback is not None:
        lines.append(f"  Lookback ({recovery.lookback.reason}):")
        lines.extend(f"    {_observation_text(item)}" for item in recovery.lookback.observations)
    lines.extend(f"  -> {text}" for text in strength.adjustments)

    swimming = recommendation.swimming
    goal = swimming.goal
    baseline = swimming.baseline
    lines.extend(
        (
            "",
            f"== Next swim goal: {goal.session_type} ==",
            f"  Main set: {goal.main_set}",
            f"  Total: about {_fixed(goal.total_meters)} m",
        )
    )
    lines.extend(f"  - {reason}" for reason in goal.reasons)
    lines.extend(f"  ! {caution}" for caution in goal.cautions)
    fast, slow = baseline.target_pace_seconds_per_100m
    lines.extend(
        (
            f"  Baseline: configured continuous {_fixed(baseline.configured_continuous_meters)} m; "
            f"recent longest continuous {_segment_line(baseline.recent_longest_segment)}",
            f"  Best recent freestyle pace: {_segment_line(baseline.recent_best_pace_segment)}",
            f"  1500 m goal: {pace_text(fast)}-{pace_text(slow)} "
            f"({_clock(goals.target_1500m_fastest_seconds)}-{_clock(goals.target_1500m_slowest_seconds)})",
            f"  Swims in the last 7 days: {swimming.sessions_last_7_days} "
            f"(goal {swimming.goal_sessions_per_week}/week); last stored swim "
            f"{_days_ago(baseline.days_since_last_swim)}; long-term target "
            f"{_fixed(baseline.long_term_target_meters)} m",
        )
    )
    for session in swimming.sessions[-4:]:
        longest = session.longest_segment.distance_meters if session.longest_segment else None
        lines.append(
            f"    {session.local_date.isoformat()} {session.source_activity_id}: "
            f"{_optional(session.distance_meters, ' m')} ({session.distance_basis}), "
            f"longest continuous {_optional(longest, ' m')}"
            f"{', high intensity' if session.high_intensity else ''}"
        )

    nutrition_lines = nutrition_context_lines(nutrition) if nutrition is not None else []
    if nutrition_lines:
        lines.append("")
        lines.extend(nutrition_lines)

    freshness = recommendation.data_freshness
    lines.extend(
        (
            "",
            "== Data freshness ==",
            f"  latest stored: activity {_date_text(freshness.latest_activity_date)}, "
            f"strength {_date_text(freshness.latest_strength_date)}, "
            f"swim {_date_text(freshness.latest_swim_date)}, "
            f"recovery row {_date_text(freshness.latest_recovery_date)}",
            f"  {recommendation.as_of.isoformat()} recovery row: "
            + (
                ("present" if freshness.requested_date_sleep_recorded else "present, no sleep (partial)")
                if freshness.requested_date_recovery_row
                else "missing"
            ),
            f"  {freshness.statement}",
        )
    )

    lines.extend(("", "== Data quality / UNKNOWN / no-rule notices =="))
    if not recommendation.notices:
        lines.append("  none")
    for notice in recommendation.notices:
        where = " ".join(
            part
            for part in (
                notice.local_date.isoformat() if notice.local_date else "",
                notice.source_activity_id or "",
            )
            if part
        )
        lines.append(f"  [{notice.code}] {where + ': ' if where else ''}{notice.message}")
    return "\n".join(lines)


def render_daily_sync_json(result: DailySyncResult) -> str:
    """Stage summaries plus the unchanged recommendation JSON; stable for identical input.

    Recovery rows are summarized by date and status only: their import timestamps would make
    repeated runs differ.
    """
    activities = result.activities
    load = result.load_metrics
    recovery = result.recovery
    payload = {
        "as_of": result.as_of.isoformat(),
        "mode": result.mode.value,
        "sync_from": result.sync_from.isoformat(),
        "ok": result.ok,
        "failed_stages": list(result.failed_stages),
        "stages": [
            {"stage": item.stage, "status": item.status.value, "error": item.error, "warnings": list(item.warnings)}
            for item in result.stages
        ],
        "activities": None
        if activities is None
        else {
            "from": activities.from_date.isoformat(),
            "to": activities.to_date.isoformat(),
            "discovered": activities.discovered_count,
            "inserted": activities.inserted_count,
            "already_stored": activities.skipped_count,
            "failed": activities.failed_count,
            "undated": activities.undated_count,
            "page_limit_reached": activities.page_limit_reached,
            "outcomes": [
                {
                    "source_activity_id": item.source_activity_id,
                    "source_type_key": item.source_type_key,
                    "status": item.status,
                    "error": item.error,
                    "warnings": list(item.warnings),
                }
                for item in activities.outcomes
            ],
        },
        "load_metrics": None
        if load is None
        else {
            "activities_examined": load.activities_examined,
            "metric_rows_inserted": load.metrics_inserted,
            "metric_rows_updated": load.metrics_updated,
            "metric_rows_unchanged": load.metrics_unchanged,
            "missing_raw": list(load.missing_raw),
            "unreadable_raw": list(load.unreadable_raw),
            "malformed_values": len(load.malformed_values),
            "skipped_values": len(load.skipped_values),
        },
        "recovery": None
        if recovery is None
        else {
            "from": recovery.from_date.isoformat(),
            "to": recovery.to_date.isoformat(),
            "aborted_reason": recovery.aborted_reason,
            "outcomes": [
                {
                    "calendar_date": item.calendar_date,
                    "status": item.status,
                    "error": item.error,
                    "warnings": list(item.result.warnings) if item.result is not None else [],
                }
                for item in recovery.outcomes
            ],
        },
        # Exactly the standalone `recommend --json` document, never re-serialized differently.
        "recommendation": None
        if result.recommendation is None
        else json.loads(render_training_recommendation_json(result.recommendation, result.nutrition)),
    }
    return json.dumps(payload, indent=2, ensure_ascii=True)


def render_daily_sync(result: DailySyncResult) -> str:
    # ASCII labels (cp949 consoles); Garmin error messages are printed as received.
    lines = [f"muscle50 daily for {result.as_of.isoformat()} ({result.mode.value.replace('_', '-')})", "Stages:"]
    for item in result.stages:
        lines.append(f"  {item.stage}: {item.status.value}{_daily_stage_detail(result, item.stage)}")
        if item.error:
            lines.append(f"    error: {item.error}")
        lines.extend(f"    warning: {warning}" for warning in item.warnings)
    recommendation = result.recommendation
    if recommendation is not None:
        freshness = recommendation.data_freshness
        lines.append(
            f"Stored data now: activity {_stored_date(freshness.latest_activity_date)}, "
            f"strength {_stored_date(freshness.latest_strength_date)}, "
            f"swim {_stored_date(freshness.latest_swim_date)}, "
            f"recovery {_stored_date(freshness.latest_recovery_date)}"
        )
    if not result.ok:
        failed = ", ".join(result.failed_stages) or "none"
        lines.append(f"FAILED stages: {failed}. Data already synced is kept; rerunning the same command is safe.")
        if result.mode is DailyMode.FULL and recommendation is None:
            lines.append(
                "No recommendation was built from possibly incomplete data. A read-only plan from the data stored "
                f"now: muscle50 recommend --date {result.as_of.isoformat()}"
            )
    elif result.mode is DailyMode.AFTER_WORKOUT:
        lines.append("Imported. The next `muscle50 daily` will count this workout.")
    text = "\n".join(lines)
    if recommendation is None:
        return text
    return f"{text}\n\n{render_training_recommendation(recommendation, result.nutrition)}"


def _daily_stage_detail(result: DailySyncResult, stage: str) -> str:
    activities = result.activities
    if stage == STAGE_ACTIVITIES and activities is not None:
        return (
            f" ({activities.from_date.isoformat()}..{activities.to_date.isoformat()}: found "
            f"{activities.discovered_count}, new {activities.inserted_count}, already stored "
            f"{activities.skipped_count}, failed {activities.failed_count})"
        )
    load = result.load_metrics
    if stage == STAGE_LOAD_METRICS and load is not None:
        return (
            f" (metric rows inserted {load.metrics_inserted}, updated {load.metrics_updated}, "
            f"unchanged {load.metrics_unchanged})"
        )
    recovery = result.recovery
    if stage == STAGE_RECOVERY and recovery is not None:
        return (
            f" ({recovery.from_date.isoformat()}..{recovery.to_date.isoformat()}: created {recovery.count('created')}, "
            f"updated {recovery.count('updated')}, unchanged {recovery.count('unchanged')}, "
            f"failed {recovery.count('failed')}, not attempted {recovery.count('not_attempted')})"
        )
    return ""


def _stored_date(value: date | None) -> str:
    return value.isoformat() if value is not None else "none stored"


def _prescription(exercise: PlannedExercise) -> str:
    progression = exercise.progression
    rep_range = progression.rep_range
    reps = f"{progression.target_reps} reps" if progression.target_reps is not None else "reps"
    reference = progression.load_kg if progression.load_kg is not None else progression.load_increase_from_kg
    low = reference is not None and progression.load_confidence == "low"
    # Never present a low-confidence load as exact.
    shown = f"{'~' if low else ''}{kg_text(reference)}" if reference is not None else ""
    if reference is None:
        load = " (no load target)"
    elif progression.load_kg is not None:
        load = f" @ {shown}"
    elif progression.load_step == LOAD_STEP_SMALLEST_AVAILABLE_DIRECTION_UNKNOWN:
        load = f" @ one smallest available step from {shown} (less if assistance, more if added resistance)"
    else:
        load = f" @ next available step above {shown}"
    if low:
        recorded = progression.recorded_load_range_kg
        spread = f"recorded {_fixed(recorded[0])}-{_fixed(recorded[1])} kg; " if recorded else ""
        check = "comparable to last time" if progression.same_load_evidence else "confirm equipment/load used last time"
        load += f" (low confidence: {spread}{check})"
    if progression.action is ProgressionAction.ESTABLISH_BASELINE:
        load = " (choose a load for the range; no comparable history)"
    return f"{exercise.sets} sets x {reps}{load} (range {rep_range.minimum}-{rep_range.maximum})"


def _observation_text(item: RecoveryObservation) -> str:
    if item.value is None:
        value = "missing (not treated as poor)"
    elif item.field == "sleep_seconds" and isinstance(item.value, (int, float)):
        value = _duration(float(item.value))
    else:
        value = str(item.value)
    fired = f" -> {item.fired_level.value} ({item.rule})" if item.fired_level is not None else ""
    return f"{item.field} [{item.source_date.isoformat()}]: {value}{fired}"


def _segment_line(segment: SwimSegment | None) -> str:
    if segment is None:
        return "none in the last 28 days"
    pace = segment.pace_seconds_per_100m
    pace_part = f", {pace_text(pace)}" if pace is not None else ""
    verified = "" if segment.verified_from_lengths else ", unverified lap"
    return (
        f"{_fixed(segment.distance_meters)} m ({segment.local_date.isoformat()} {segment.source_activity_id} "
        f"lap {segment.lap_sequence}, {'/'.join(segment.strokes)}{pace_part}{verified})"
    )


def _days_ago(days: int | None) -> str:
    return "none in the last 28 days" if days is None else f"{days} days ago"


def _clock(seconds: int) -> str:
    return f"{seconds // 60}:{seconds % 60:02d}"


def _json_default(value: object) -> str:
    if isinstance(value, date):
        return value.isoformat()
    raise TypeError(f"not JSON serializable: {type(value).__name__}")


def _fixed(value: float) -> str:
    # Up to two decimals, without the six-significant-digit truncation of :g on large totals.
    return f"{value:.2f}".rstrip("0").rstrip(".")


def _optional(value: float | int | None, suffix: str = "") -> str:
    if value is None:
        return "unavailable"
    rendered = str(value) if isinstance(value, int) else _fixed(value)
    return f"{rendered}{suffix}"


def _value_text(value: float | None, unit: str | None, duration: bool) -> str:
    if value is None:
        return "unavailable"
    if duration:
        return _duration(value)
    return _optional(value, f" {unit}" if unit and unit != "score" else "")


def _date_text(value: date | None) -> str:
    return value.isoformat() if value is not None else "unknown date"


def _aggregate_text(item: MetricAggregate, *, duration: bool = False) -> str:
    total = len(item.values) + len(item.missing_source_ids)
    coverage = f"[{item.rule.value}, {len(item.values)}/{total}]"
    if item.value is None:
        return f"unavailable {coverage}"
    rendered = _duration(item.value) if duration else _optional(item.value, f" {item.unit}" if item.unit else "")
    return f"{rendered} {coverage}"
