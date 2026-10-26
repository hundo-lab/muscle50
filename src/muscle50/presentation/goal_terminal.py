"""Text and JSON for the training goal, the sleep thresholds and the goal-mode sections (ASCII only).

Body-composition values are never printed here (user decision D1, 2026-10-26): the goal section of
recommend/daily shows rates (%/week), flags and dates only. User-entered goal values (a target body
fat %, a target weight, an SMM floor) are the user's own settings and are shown as entered.
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

from muscle50.domain.recovery_assessment import SleepThresholds
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
