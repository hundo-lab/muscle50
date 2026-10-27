"""Text and JSON for the training goal, the sleep thresholds and the goal-mode sections (ASCII only).

Body-composition values are never printed here (user decision D1, 2026-10-26): the goal section of
recommend/daily shows rates (%/week), flags and dates only. User-entered goal values (a target body
fat %, a target weight, an SMM floor) are the user's own settings and are shown as entered.
"""

from __future__ import annotations

import json
from datetime import date
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Any

from muscle50.domain.aerobic_guide import (
    CHOICE_EVIDENCE,
    EAT_LESS_STEP_KCAL,
    GUIDELINE_MINIMUM_MINUTES,
    MAINTENANCE_WEEKS,
    NOISE_EVIDENCE,
    PLATEAU_MIN_INTERVALS,
    RUN_LONGER_THRESHOLD_PERCENT,
    STUDIED_RANGE_END_MINUTES,
    WITHIN_WEEK_WEIGHT_NOISE_PERCENT,
    AerobicMinutes,
    PlateauCheck,
    PlateauOption,
    RunLengthCheck,
    RunLengthReport,
)
from muscle50.domain.goal_mode import (
    DEFICIT_LIMIT_KCAL,
    GOAL_MODE_VERSION,
    PROTEIN_G_PER_KG_FAT_FREE_MASS,
    RUN_LEGS_GAP_HOURS,
    CutNutritionReference,
    CutProgressionChange,
    GoalModeReport,
    RunLegsPair,
    percent_text,
)
from muscle50.domain.recovery_assessment import SleepThresholds
from muscle50.domain.strength_recommendation import (
    LOAD_STEP_SMALLEST_AVAILABLE_DIRECTION_UNKNOWN,
    ProgressionAction,
    kg_text,
)
from muscle50.domain.training_goal import GoalMode, SleepThresholdSetting, TrainingGoal
from muscle50.infrastructure.decimal_text import decimal_to_text
from muscle50.infrastructure.training_goal_store import goal_payload, sleep_payload

GOAL_VERSION = 1
SLEEP_THRESHOLDS_VERSION = 1
GOAL_FILE_TEXT = "config\\training_goal.json"
SLEEP_FILE_TEXT = "config\\sleep_thresholds.json"
EVIDENCE_LOSS_TEXT = "0.5-1.0 %/week"
NO_GOAL_TEXT = "No training goal set. recommend and daily use the default rules (gain)."


def _dumps(payload: dict[str, Any]) -> str:
    return json.dumps(payload, indent=2, ensure_ascii=True)


# --- goal set / show / unset -----------------------------------------------------------------


def render_goal(goal: TrainingGoal | None) -> str:
    if goal is None:
        return NO_GOAL_TEXT
    lines = [
        f"Training goal ({GOAL_FILE_TEXT}, user setting):",
        f"  mode: {goal.mode.value}",
        f"  {goal_target_text(goal)}",
        "  skeletal muscle mass floor: "
        + (
            f"{decimal_to_text(goal.min_skeletal_muscle_mass_kg)} kg"
            if goal.min_skeletal_muscle_mass_kg is not None
            else "not set"
        ),
    ]
    if goal.mode is GoalMode.CUT:
        lines.append(f"  weekly loss target: {weekly_loss_text(goal)} (evidence range {EVIDENCE_LOSS_TEXT} [MAINT-05])")
        if goal.plateau_weeks is not None:
            lines.append(
                f"  plateau check: {plateau_setting_text(goal)} (user setting [design]; no evidence-based "
                "definition [PLAT-01])"
            )
        lines.append(
            "  effects: progression keeps load and reps (maintain_load [MAINT-02]); goal lines in recommend/daily;"
        )
        lines.append("  cut references in nutrition status. Nutrition targets and the training plan are not changed.")
    else:
        lines.append("  effects: progression unchanged (the default gain rules); goal lines in recommend/daily.")
        lines.append("  Nutrition targets and the training plan are not changed.")
    return "\n".join(lines)


def render_goal_json(goal: TrainingGoal | None) -> str:
    return _dumps({"goal_version": GOAL_VERSION, "goal": goal_payload(goal) if goal is not None else None})


def render_goal_removed(removed: bool) -> str:
    if removed:
        return "Training goal removed. recommend and daily use the default rules (gain)."
    return f"{NO_GOAL_TEXT} Nothing changed."


def render_goal_removed_json(removed: bool) -> str:
    return _dumps({"goal_version": GOAL_VERSION, "goal": None, "removed": removed})


def goal_target_text(goal: TrainingGoal) -> str:
    if goal.target_body_fat_percent is not None:
        target = f"target body fat: {decimal_to_text(goal.target_body_fat_percent)} %"
    elif goal.target_weight_kg is not None:
        target = f"target weight: {decimal_to_text(goal.target_weight_kg)} kg"
    else:
        return "target: not set"
    return f"{target} by {goal.target_date.isoformat()}" if goal.target_date is not None else target


def plateau_setting_text(goal: TrainingGoal) -> str:
    """``3 weeks below 0.3 %/week loss, at least 2 InBody intervals`` (the threshold is the --weekly-loss MIN)."""
    rate = goal.weekly_loss_percent
    below = decimal_to_text(rate.minimum) if rate is not None else "unknown"
    return f"{goal.plateau_weeks} weeks below {below} %/week loss, at least {PLATEAU_MIN_INTERVALS} InBody intervals"


def weekly_loss_text(goal: TrainingGoal) -> str:
    rate = goal.weekly_loss_percent
    if rate is None:
        return "not set"
    return f"{decimal_to_text(rate.minimum)}-{decimal_to_text(rate.maximum)} %/week"


# --- settings sleep --------------------------------------------------------------------------


def render_sleep_thresholds(setting: SleepThresholdSetting) -> str:
    thresholds = setting.thresholds
    source = "default" if setting.source == "default" else f"{SLEEP_FILE_TEXT}, user setting"
    return "\n".join(
        (
            f"Sleep thresholds of the training recovery rules ({source}):",
            f"  hold below: {hours_text(thresholds.short_sleep_seconds)} h of sleep "
            f"({thresholds.short_sleep_seconds} s)",
            f"  reduce below: {hours_text(thresholds.very_short_sleep_seconds)} h of sleep "
            f"({thresholds.very_short_sleep_seconds} s)",
            f"  hold below sleep score: {thresholds.low_sleep_score}",
            "  These are design choices, not evidence [design; SLEEP-05: the evidence gives only the health",
            "  target of 7 h or more per night]. recommend and daily show nights under 7 h only with a goal set.",
        )
    )


def render_sleep_thresholds_json(setting: SleepThresholdSetting) -> str:
    return _dumps({"sleep_thresholds_version": SLEEP_THRESHOLDS_VERSION, **sleep_rules_payload(setting)})


def render_sleep_reset(removed: bool) -> str:
    if removed:
        return "Sleep thresholds reset to the defaults."
    return "Sleep thresholds were already the defaults. Nothing changed."


def sleep_rules_payload(setting: SleepThresholdSetting) -> dict[str, Any]:
    return {**sleep_payload(setting.thresholds), "source": setting.source, "evidence": ["design", "SLEEP-05"]}


def sleep_rules_text(setting: SleepThresholdSetting) -> str:
    thresholds: SleepThresholds = setting.thresholds
    return (
        f"hold < {hours_text(thresholds.short_sleep_seconds)} h, reduce < "
        f"{hours_text(thresholds.very_short_sleep_seconds)} h, score < {thresholds.low_sleep_score} "
        f"({'default' if setting.source == 'default' else 'user setting'}; not evidence-based, SLEEP-05)"
    )


def hours_text(seconds: int) -> str:
    """Seconds as hours, up to two decimals (whole-second settings are exact at 0.01 h or show rounded)."""
    hours = (Decimal(seconds) / Decimal(3600)).quantize(Decimal("0.01")).normalize()
    return format(hours, "f")


# --- the goal section of recommend / daily ---------------------------------------------------

_FLAG_TEXT = {
    "faster_than_evidence": "loss faster than 1.0 %/week: may not favour keeping muscle [MAINT-05]",
    "outside_user_target": "outside your target range [design: user setting]",
    "gaining": "weight went up during a cut [design]",
}


def goal_mode_lines(report: GoalModeReport) -> list[str]:
    """The goal section (only with a goal set); every line carries an evidence ID or ``design``.

    Indented continuation lines belong to the tagged line above them.
    """
    goal = report.goal
    cut = goal.mode is GoalMode.CUT
    target = _target_description(goal)
    parts = [
        f"{target} by {goal.target_date.isoformat()}" if goal.target_date is not None else target,
        f"SMM floor {decimal_to_text(goal.min_skeletal_muscle_mass_kg)} kg"
        if goal.min_skeletal_muscle_mass_kg is not None
        else "no SMM floor",
    ]
    if cut:
        parts.append(f"weekly loss {weekly_loss_text(goal)}")
    lines = [f"== Goal: {goal.mode.value} (user setting) ==", f"  Target [design: user setting]: {'; '.join(parts)}"]

    if cut:
        lines.append(
            "  Progression [MAINT-02, MAINT-06; optional PROG-03]: keep load and reps; the increase is optional"
        )
        lines.extend(
            f"    {change.label} [maintain_load]: keep {_load_reps(change.load_kg, change.target_reps)} "
            f"(optional: {_optional_text(change)})"
            for change in report.progression
        )
        if not report.progression:
            lines.append("    no load or rep increase was planned today, so nothing changed")
    else:
        lines.append("  Progression [design]: unchanged (the default gain rules)")

    sets = report.weekly_sets
    lines.append(
        f"  Weekly sets below {sets.threshold}, {sets.from_date.isoformat()}..{sets.to_date.isoformat()} "
        f"(primary 1, secondary {sets.secondary_weight:g}) [VOL-04; counting VOL-02]:"
    )
    below = ", ".join(f"{item.muscle} {item.fractional_sets:g}" for item in sets.muscles if item.below_threshold)
    excluded = [
        f"{count} {kind}" for count, kind in ((sets.unknown_sets, "UNKNOWN"), (sets.no_rule_sets, "no-rule")) if count
    ]
    note = f" (lower bounds: {' and '.join(excluded)} sets not counted)" if excluded else ""
    lines.append(f"    {below or 'none'}{note}")
    uncountable = [item.muscle for item in sets.muscles if not item.countable]
    if uncountable:
        lines.append(f"    not countable (no taxonomy rule trains them): {', '.join(uncountable)}")

    lines.extend(_weight_lines(report))
    lines.append(_smm_line(report))
    lines.append(_progress_line(report))

    run_legs = report.run_legs
    lines.append(
        f"  Same-day run and legs under {run_legs.gap_threshold_hours} h, {run_legs.from_date.isoformat()}.."
        f"{run_legs.to_date.isoformat()} [design; CONC-03, CONC-04]:"
    )
    listed = [pair for pair in run_legs.pairs if pair.under_threshold is not False]
    lines.extend(f"    {_pair_text(pair)}" for pair in listed)
    if not listed:
        lines.append("    none")

    sleep = report.sleep
    lines.append(
        f"  Nights under {sleep.threshold_hours} h, {sleep.from_date.isoformat()}..{sleep.to_date.isoformat()}: "
        f"{sleep.nights_under} of {sleep.nights_with_data} with sleep data, {sleep.nights_without_data} without "
        "[SLEEP-05, display only]"
    )
    lines.append(f"    training sleep rules [design]: {sleep_rules_text(sleep.rules)}")
    lines.extend(_aerobic_lines(report.aerobic_minutes))
    lines.extend(_run_length_lines(report.run_length))
    if report.plateau is not None:
        lines.extend(_plateau_lines(report.plateau, goal))
    return lines


def goal_mode_payload(report: GoalModeReport) -> dict[str, Any]:
    """The trailing ``goal_mode`` key: rates, flags, dates and the user's own settings; no measured kg."""
    sets = report.weekly_sets
    change = report.weight_change
    evidence_range = change.evidence_range
    floor = report.smm_floor
    progress = report.goal_progress
    run_legs = report.run_legs
    sleep = report.sleep
    return {
        "goal_mode_version": GOAL_MODE_VERSION,
        "goal": {**goal_payload(report.goal), "source": "user_setting", "evidence": ["design"]},
        "progression": [
            {
                "label": item.label,
                "action": ProgressionAction.MAINTAIN_LOAD.value,
                "load_kg": item.load_kg,
                "target_reps": item.target_reps,
                "optional": {
                    "action": item.optional_action.value,
                    "load_kg": item.optional_load_kg,
                    "load_increase_from_kg": item.optional_load_increase_from_kg,
                    "load_step": item.optional_load_step,
                    "target_reps": item.optional_target_reps,
                },
                "evidence": list(item.evidence),
            }
            for item in report.progression
        ],
        "weekly_sets": {
            "from": sets.from_date.isoformat(),
            "to": sets.to_date.isoformat(),
            "threshold": sets.threshold,
            "secondary_weight": sets.secondary_weight,
            "evidence": list(sets.evidence),
            "unknown_sets": sets.unknown_sets,
            "no_rule_sets": sets.no_rule_sets,
            "lower_bound": sets.lower_bound,
            "muscles": [
                {
                    "muscle": item.muscle,
                    "direct_sets": item.direct_sets,
                    "indirect_sets": item.indirect_sets,
                    "fractional_sets": item.fractional_sets,
                    "below_threshold": item.below_threshold,
                    "countable": item.countable,
                }
                for item in sets.muscles
            ],
        },
        "weight_change": {
            "status": change.status,
            "from_date": _iso(change.from_date),
            "to_date": _iso(change.to_date),
            "days": change.days,
            "percent_per_week": percent_text(change.percent_per_week),
            "flags": list(change.flags),
            "evidence_range_percent_per_week": None
            if evidence_range is None
            else {
                "minimum": decimal_to_text(evidence_range.minimum),
                "maximum": decimal_to_text(evidence_range.maximum),
            },
            "latest_measurement_date": _iso(change.latest_measurement_date),
            "days_since_latest_measurement": change.days_since_latest_measurement,
            "evidence": list(change.evidence),
            "reason": change.reason,
        },
        "smm_floor": {
            "status": floor.status,
            "measurement_date": _iso(floor.measurement_date),
            "floor_kg": decimal_to_text(floor.floor_kg) if floor.floor_kg is not None else None,
            "evidence": list(floor.evidence),
        },
        "goal_progress": {
            "status": progress.status,
            "required_percent_per_week": percent_text(progress.required_percent_per_week),
            "actual_percent_per_week": percent_text(progress.actual_percent_per_week),
            "measurement_date": _iso(progress.measurement_date),
            "evidence": list(progress.evidence),
            "assumption": progress.assumption,
            "reason": progress.reason,
        },
        "run_legs": {
            "from": run_legs.from_date.isoformat(),
            "to": run_legs.to_date.isoformat(),
            "gap_threshold_hours": run_legs.gap_threshold_hours,
            "evidence": list(run_legs.evidence),
            "pairs": [
                {
                    "date": pair.local_date.isoformat(),
                    "run_activity_id": pair.run_activity_id,
                    "strength_activity_id": pair.strength_activity_id,
                    "run_start_local_time": pair.run_local_time,
                    "strength_start_local_time": pair.strength_local_time,
                    "gap_minutes": pair.gap_minutes,
                    "under_threshold": pair.under_threshold,
                    "order": pair.order,
                    "advice": pair.advice,
                    "advice_evidence": list(pair.advice_evidence),
                }
                for pair in run_legs.pairs
            ],
        },
        "sleep": {
            "from": sleep.from_date.isoformat(),
            "to": sleep.to_date.isoformat(),
            "threshold_hours": sleep.threshold_hours,
            "nights_under": sleep.nights_under,
            "nights_with_data": sleep.nights_with_data,
            "nights_without_data": sleep.nights_without_data,
            "display_only": True,
            "evidence": list(sleep.evidence),
            "training_rules": sleep_rules_payload(sleep.rules),
        },
        "aerobic_minutes": _aerobic_payload(report.aerobic_minutes),
        "run_length": _run_length_payload(report.run_length),
        "plateau": _plateau_payload(report.plateau) if report.plateau is not None else None,
    }


def _target_description(goal: TrainingGoal) -> str:
    if goal.target_body_fat_percent is not None:
        return f"body fat {decimal_to_text(goal.target_body_fat_percent)} %"
    if goal.target_weight_kg is not None:
        return f"weight {decimal_to_text(goal.target_weight_kg)} kg"
    return "no body fat or weight target"


def _load_reps(load: float | None, reps: int | None) -> str:
    return f"{kg_text(load) if load is not None else 'no load'} x {reps if reps is not None else '-'}"


def _optional_text(change: CutProgressionChange) -> str:
    reps = change.optional_target_reps if change.optional_target_reps is not None else "-"
    if change.optional_load_kg is not None:
        return _load_reps(change.optional_load_kg, change.optional_target_reps)
    source = change.optional_load_increase_from_kg
    if source is None:
        return f"{reps} reps"
    if change.optional_load_step == LOAD_STEP_SMALLEST_AVAILABLE_DIRECTION_UNKNOWN:
        return f"one smallest available step from {kg_text(source)} x {reps}"
    return f"next available step above {kg_text(source)} x {reps}"


def _weight_lines(report: GoalModeReport) -> list[str]:
    change = report.weight_change
    latest = change.latest_measurement_date
    since = f"latest InBody {latest.isoformat()}, {change.days_since_latest_measurement} d ago" if latest else ""
    if change.status != "known" or change.from_date is None or change.to_date is None:
        detail = f"{change.reason}; {since}" if since else f"{change.reason}"
        lines = [f"  Weight change: unknown ({detail}) [MAINT-05; design]"]
    else:
        lines = [
            f"  Weight change {change.from_date.isoformat()} -> {change.to_date.isoformat()} ({change.days} d; "
            f"{since}): {percent_text(change.percent_per_week)} %/week [MAINT-05; design: >= 7 d apart]"
        ]
    evidence_range = change.evidence_range
    if evidence_range is not None:
        rate = report.goal.weekly_loss_percent
        target = (
            f"your target {decimal_to_text(rate.minimum)}-{decimal_to_text(rate.maximum)} (user setting)"
            if rate is not None
            else "your target not set"
        )
        lines.append(
            f"    evidence {decimal_to_text(evidence_range.minimum)}-{decimal_to_text(evidence_range.maximum)} "
            f"[MAINT-05]; {target}"
        )
    lines.extend(f"    -> {_FLAG_TEXT[flag]}" for flag in change.flags)
    return lines


def _smm_line(report: GoalModeReport) -> str:
    floor = report.smm_floor
    if floor.status == "not_set" or floor.floor_kg is None:
        return "  SMM floor: not set [design: user setting]"
    limit = f"your {decimal_to_text(floor.floor_kg)} kg floor"
    if floor.status == "unknown" or floor.measurement_date is None:
        return f"  SMM: unknown against {limit} (no InBody skeletal muscle mass) [design: user setting]"
    where = "below" if floor.status == "below" else "at or above"
    return f"  SMM: {where} {limit} (InBody {floor.measurement_date.isoformat()}) [design: user setting]"


def _progress_line(report: GoalModeReport) -> str:
    progress = report.goal_progress
    goal = report.goal
    tag = "[design: fat-free mass assumed constant]" if progress.assumption else "[design]"
    target = _target_description(goal)
    if progress.status == "known" and goal.target_date is not None:
        actual = percent_text(progress.actual_percent_per_week) or "unknown"
        text = (
            f"needs {percent_text(progress.required_percent_per_week)} %/week to reach {target} by "
            f"{goal.target_date.isoformat()}; actual {actual} %/week"
        )
    elif progress.status == "reached" and progress.measurement_date is not None:
        text = f"{target} reached (InBody {progress.measurement_date.isoformat()})"
    else:
        text = f"{progress.status.replace('_', ' ')} ({progress.reason})"
    return f"  Goal progress {tag}: {text}"


def _pair_text(pair: RunLegsPair) -> str:
    run = f"run {pair.run_local_time or 'time unknown'}"
    legs = f"legs {pair.strength_local_time or 'time unknown'}"
    day = pair.local_date.isoformat()
    if pair.gap_minutes is None:
        return f"{day}: {run}, {legs} (gap unknown: a start time has no time zone)"
    gap = _gap_text(pair.gap_minutes)
    if pair.order == "legs_first":
        return f"{day}: {legs}, {run} ({gap} apart)"
    if pair.advice == "lift_first":
        return f"{day}: {run}, {legs} ({gap} apart): lift first next time [CONC-05]"
    return f"{day}: {run}, {legs} ({gap} apart)"


def _gap_text(minutes: int) -> str:
    if minutes < 60:
        return f"{minutes} min"
    hours, rest = divmod(minutes, 60)
    return f"{hours} h" if rest == 0 else f"{hours} h {rest} min"


# --- aerobic guide (Aerobic Guide v1, display only) --------------------------------------------

# FATEX-02: 300 is the end of the studied range; the wording never presents it as a point past which
# the benefit is gone.
_REFERENCE_TEXT = (
    f"    reference marks: {GUIDELINE_MINIMUM_MINUTES} min/week, the guideline minimum (or 75 vigorous) [EXL-03]; "
    f"{STUDIED_RANGE_END_MINUTES} min/week, the end of the studied range [FATEX-02]"
)
_NO_PREVIOUS_TEXT = "no earlier run with a distance in its 30 days"
# A fixed display order, not a ranking (PLAT-06).
_OPTION_TEXT = {
    "check_meal_logging": (
        "a) check that meals are logged completely (missed meals, general-meal estimates, weekends) [PLAT-04]"
    ),
    "eat_less": (
        f"b) eat {EAT_LESS_STEP_KCAL[0]}-{EAT_LESS_STEP_KCAL[1]} kcal/day less; keep the deficit at or under about "
        f"{DEFICIT_LIMIT_KCAL} kcal/day (muscle50 cannot measure it) [design: goals.md step; PRO-04]"
    ),
    "keep_intake_add_activity": (
        "c) keep intake, add activity: the same deficit gave the same fat loss, but extra eating can offset part of "
        f"it [FATEX-05, FATEX-04]; watch run length and the {RUN_LEGS_GAP_HOURS} h run/legs gap [RUNPROG-03, CONC-04]"
    ),
    "maintenance_week": (
        "d) one maintenance week: weight may rise from glycogen and water, and the deadline moves by a week [PLAT-05]"
    ),
}


def _aerobic_lines(aerobic: AerobicMinutes) -> list[str]:
    head = (
        f"  Aerobic minutes {aerobic.from_date.isoformat()}..{aerobic.to_date.isoformat()} "
        f"({', '.join(aerobic.activity_types)}): "
    )
    if aerobic.status == "none_stored":
        return [f"{head}none stored (may be unsynced, not a confirmed rest week) [EXL-03; design]", _REFERENCE_TEXT]
    if aerobic.status == "unknown":
        return [
            f"{head}unknown (no counted activity has intensity minutes) [EXL-03; design]",
            _REFERENCE_TEXT,
            f"    {_without_intensity_text(aerobic)} [design]",
        ]
    lines = [
        f"{head}moderate {_minutes(aerobic.moderate_minutes)} + vigorous {_minutes(aerobic.vigorous_minutes)} = "
        f"{_minutes(aerobic.total_minutes)} min [EXL-03; design: Garmin intensity minutes, vigorous not doubled]",
        _REFERENCE_TEXT,
    ]
    if aerobic.status == "lower_bound":
        parts = []
        if aerobic.without_intensity_count:
            parts.append(_without_intensity_text(aerobic, " not counted"))
        if aerobic.partial_intensity_count:
            count = aerobic.partial_intensity_count
            parts.append(
                f"{count} {_plural(count, 'activity has', 'activities have')} only one of moderate and vigorous stored"
            )
        lines.append(f"    lower bound: {'; '.join(parts)} [design]")
    return lines


def _without_intensity_text(aerobic: AerobicMinutes, suffix: str = "") -> str:
    count = aerobic.without_intensity_count
    text = f"{count} {_plural(count, 'activity', 'activities')} without intensity minutes{suffix}"
    details = []
    if aerobic.without_intensity_duration_minutes is not None:
        details.append(f"duration {aerobic.without_intensity_duration_minutes} min, intensity unknown")
    if aerobic.without_duration_count:
        details.append(f"{aerobic.without_duration_count} without a duration either")
    return f"{text} ({'; '.join(details)})" if details else text


def _run_length_lines(report: RunLengthReport) -> list[str]:
    lines = [
        f"  Run length vs the longest run in the {report.previous_days} days before it, "
        f"{report.from_date.isoformat()}..{report.to_date.isoformat()} "
        "[RUNPROG-03: observational link with overuse injury; notice only]:"
    ]
    flagged = [run for run in report.runs if run.status == "longer_than_threshold"]
    lines.extend(f"    {_run_text(run)}" for run in flagged)
    if not report.runs:
        lines.append("    no run stored in this window")
    elif not flagged:
        compared = sum(1 for run in report.runs if run.status == "within")
        skipped = sum(1 for run in report.runs if run.status == "no_previous_run")
        no_distance = sum(1 for run in report.runs if run.status == "no_distance")
        parts = []
        if compared:
            parts.append(f"{compared} {_plural(compared, 'run', 'runs')} compared")
        if skipped:
            parts.append(f"{skipped} skipped: {_NO_PREVIOUS_TEXT}")
        if no_distance:
            parts.append(f"{no_distance} without a distance, not judged")
        lines.append(f"    none more than {report.threshold_percent} % longer ({'; '.join(parts)})")
    return lines


def _run_text(run: RunLengthCheck) -> str:
    assert run.distance_meters is not None and run.longest_previous_meters is not None
    assert run.longest_previous_date is not None and run.increase_percent is not None
    where = run.longest_previous_date.isoformat()
    if run.baseline_lower_bound:
        count = run.previous_without_distance
        where += f"; {count} earlier {_plural(count, 'run', 'runs')} had no distance, so the longest may be longer"
    return (
        f"{run.local_date.isoformat()} {run.source_activity_id}: {_km(run.distance_meters)} km, "
        f"{format(run.increase_percent, 'f')} % longer than {_km(run.longest_previous_meters)} km ({where})"
    )


def _plateau_lines(plateau: PlateauCheck, goal: TrainingGoal) -> list[str]:
    if plateau.status == "not_set" or plateau.below_loss_percent is None:
        return [
            "  Plateau check: not set (goal set ... --plateau-weeks N; there is no evidence-based plateau "
            "definition) [design; PLAT-01]"
        ]
    head = (
        f"  Plateau check [design: user setting, {plateau.weeks} weeks below "
        f"{decimal_to_text(plateau.below_loss_percent)} %/week loss, >= {PLATEAU_MIN_INTERVALS} InBody intervals]: "
    )
    if plateau.status == "unknown":
        return [f"{head}unknown ({plateau.reason})"]
    if plateau.status == "insufficient_measurements":
        return [f"{head}insufficient InBody data ({plateau.reason} [PLAT-02])"]
    oldest_first = tuple(reversed(plateau.intervals))
    dates = " -> ".join(
        [oldest_first[0].from_date.isoformat(), *(interval.to_date.isoformat() for interval in oldest_first)]
    )
    rates = ", ".join(percent_text(interval.percent_per_week) or "" for interval in oldest_first)
    lines = [
        f"{head}{'met' if plateau.status == 'met' else 'not met'}",
        f"    InBody {dates} ({plateau.span_days} d): {rates} %/week [PLAT-01, PLAT-02]",
    ]
    if plateau.status == "met":
        lines.append(
            # Both values side by side; muscle50 makes no comparison between them.
            f"    note: weight moves about {decimal_to_text(WITHIN_WEEK_WEIGHT_NOISE_PERCENT)} % within a week "
            f"[PLAT-02]; your target is {weekly_loss_text(goal)} (user setting); compare same-device, "
            "same-condition InBody only [PLAT-02]"
        )
        lines.append(
            "    options, no ranking (fixed display order) [PLAT-06]; your preference and what you can keep up are "
            "valid reasons to choose [FATEX-07]:"
        )
        lines.extend(f"      {_OPTION_TEXT[option.code]}" for option in plateau.options)
    return lines


def _aerobic_payload(aerobic: AerobicMinutes) -> dict[str, Any]:
    return {
        "from": aerobic.from_date.isoformat(),
        "to": aerobic.to_date.isoformat(),
        "activity_types": list(aerobic.activity_types),
        "status": aerobic.status,
        "moderate_minutes": aerobic.moderate_minutes,
        "vigorous_minutes": aerobic.vigorous_minutes,
        "total_minutes": aerobic.total_minutes,
        "vigorous_counted_as": "minutes",
        "activities": [
            {
                "source_activity_id": item.source_activity_id,
                "date": item.local_date.isoformat(),
                "type": item.activity_type,
                "moderate_minutes": item.moderate_minutes,
                "vigorous_minutes": item.vigorous_minutes,
                "duration_minutes": item.duration_minutes,
            }
            for item in aerobic.activities
        ],
        "without_intensity_minutes": {
            "activity_count": aerobic.without_intensity_count,
            "duration_minutes": aerobic.without_intensity_duration_minutes,
            "without_duration": aerobic.without_duration_count,
            "one_metric_only_count": aerobic.partial_intensity_count,
        },
        "reference_minutes_per_week": [
            {"minutes": GUIDELINE_MINIMUM_MINUTES, "meaning": "guideline_minimum", "evidence": ["EXL-03"]},
            {"minutes": STUDIED_RANGE_END_MINUTES, "meaning": "end_of_studied_range", "evidence": ["FATEX-02"]},
        ],
        "evidence": list(aerobic.evidence),
    }


def _run_length_payload(report: RunLengthReport) -> dict[str, Any]:
    return {
        "from": report.from_date.isoformat(),
        "to": report.to_date.isoformat(),
        "previous_days": report.previous_days,
        "threshold_percent": report.threshold_percent,
        "basis": "distance",
        "notice_only": True,
        "evidence": list(report.evidence),
        "runs": [
            {
                "source_activity_id": run.source_activity_id,
                "date": run.local_date.isoformat(),
                "distance_meters": run.distance_meters,
                "longest_previous_meters": run.longest_previous_meters,
                "longest_previous_activity_id": run.longest_previous_activity_id,
                "longest_previous_date": _iso(run.longest_previous_date),
                "previous_without_distance": run.previous_without_distance,
                "baseline_lower_bound": run.baseline_lower_bound,
                "increase_percent": format(run.increase_percent, "f") if run.increase_percent is not None else None,
                "status": run.status,
            }
            for run in report.runs
        ],
    }


def _plateau_payload(plateau: PlateauCheck) -> dict[str, Any]:
    below = plateau.below_loss_percent
    return {
        "status": plateau.status,
        "weeks": plateau.weeks,
        "below_loss_percent_per_week": decimal_to_text(below) if below is not None else None,
        "source": "user_setting" if plateau.weeks is not None else None,
        "min_intervals": PLATEAU_MIN_INTERVALS,
        "intervals": [
            {
                "from_date": interval.from_date.isoformat(),
                "to_date": interval.to_date.isoformat(),
                "days": interval.days,
                "percent_per_week": percent_text(interval.percent_per_week),
            }
            for interval in plateau.intervals
        ],
        "span_days": plateau.span_days,
        "latest_measurement_date": _iso(plateau.latest_measurement_date),
        "days_since_latest_measurement": plateau.days_since_latest_measurement,
        "reason": plateau.reason,
        "evidence": list(plateau.evidence),
        "noise": {
            "within_week_weight_percent": decimal_to_text(WITHIN_WEEK_WEIGHT_NOISE_PERCENT),
            "evidence": list(NOISE_EVIDENCE),
        },
        "options_ranked": False,
        "choice_evidence": list(CHOICE_EVIDENCE),
        "options": [_option_payload(option) for option in plateau.options],
    }


def _option_payload(option: PlateauOption) -> dict[str, Any]:
    payload: dict[str, Any] = {"code": option.code}
    if option.code == "eat_less":
        payload["step_kcal_per_day"] = {"minimum": EAT_LESS_STEP_KCAL[0], "maximum": EAT_LESS_STEP_KCAL[1]}
        payload["step_source"] = "docs/goals.md"
        payload["deficit_limit_kcal_per_day"] = DEFICIT_LIMIT_KCAL
        payload["deficit_measurable"] = False
    elif option.code == "keep_intake_add_activity":
        payload["run_length_threshold_percent"] = RUN_LONGER_THRESHOLD_PERCENT
        payload["run_legs_gap_hours"] = RUN_LEGS_GAP_HOURS
    elif option.code == "maintenance_week":
        payload["weeks"] = MAINTENANCE_WEEKS
    payload["evidence"] = list(option.evidence)
    return payload


def _minutes(value: float | None) -> str:
    return f"{value:g}" if value is not None else "unknown"


def _km(meters: float) -> str:
    """Meters as km at 0.01 (HALF_EVEN), without trailing zeros (``12.5``, ``10``)."""
    kilometers = (Decimal(repr(meters)) / Decimal(1000)).quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)
    return format(kilometers.normalize(), "f")


def _plural(count: int, one: str, many: str) -> str:
    return one if count == 1 else many


def _iso(value: date | None) -> str | None:
    return value.isoformat() if value is not None else None


# --- the cut reference of `nutrition status` -------------------------------------------------

GOAL_REFERENCE_VERSION = 1


def goal_reference_lines(reference: CutNutritionReference) -> list[str]:
    """Appended to `nutrition status` in cut mode only. The protein grams are the one derived amount
    shown (D1): they are what the user needs to act on; fat-free mass itself is not printed."""
    if reference.status == "unavailable":
        return [f"Goal reference: unavailable ({reference.reason}); nutrition targets are not changed."]
    low, high = PROTEIN_G_PER_KG_FAT_FREE_MASS
    ratio = f"{decimal_to_text(low)}-{decimal_to_text(high)} g/kg fat-free mass"
    lines = ["Cut goal reference (nutrition targets are not changed):"]
    if reference.protein_min_g is not None and reference.protein_max_g is not None and reference.measurement_date:
        lines.extend(
            (
                f"  Protein [PRO-05]: {ratio} = {decimal_to_text(reference.protein_min_g)}-"
                f"{decimal_to_text(reference.protein_max_g)} g/day",
                "    (fat-free mass = weight - body fat mass, InBody "
                f"{reference.measurement_date.isoformat()} [design])",
            )
        )
    else:
        lines.append(f"  Protein [PRO-05]: {ratio} = unknown ({reference.reason})")
    lines.append(
        f"  Energy deficit [PRO-04]: keep it at or under about {DEFICIT_LIMIT_KCAL} kcal/day; muscle50 cannot "
        "measure it (maintenance kcal unknown)"
    )
    return lines


def goal_reference_payload(reference: CutNutritionReference) -> dict[str, Any]:
    low, high = PROTEIN_G_PER_KG_FAT_FREE_MASS
    unavailable = reference.status == "unavailable"
    return {
        "goal_reference_version": GOAL_REFERENCE_VERSION,
        "status": reference.status,
        "mode": None if unavailable else GoalMode.CUT.value,
        "protein": None
        if unavailable
        else {
            "g_per_kg_fat_free_mass": {"minimum": decimal_to_text(low), "maximum": decimal_to_text(high)},
            "min_g": decimal_to_text(reference.protein_min_g) if reference.protein_min_g is not None else None,
            "max_g": decimal_to_text(reference.protein_max_g) if reference.protein_max_g is not None else None,
            "measurement_date": _iso(reference.measurement_date),
            "evidence": ["PRO-05", "design"],
        },
        "energy_deficit": None
        if unavailable
        else {"limit_kcal_per_day": DEFICIT_LIMIT_KCAL, "measurable": False, "evidence": ["PRO-04"]},
        "targets_changed": False,
        "reason": reference.reason,
    }
