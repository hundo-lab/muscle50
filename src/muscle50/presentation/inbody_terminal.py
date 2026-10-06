"""Text and JSON for the InBody body-composition trend (InBody Body Composition Trend v1).

ASCII only (cp949 consoles). JSON uses ``indent=2, ensure_ascii=True``, a fixed key order and
values as 0.1 decimal strings, so the same stored rows give byte-identical output. Missing values
are ``unknown`` in text and ``null`` in JSON, never 0.
"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from typing import Any

from muscle50.domain.body_composition_trend import (
    METRICS,
    BodyCompositionTrend,
    GoalProgress,
    OverallChange,
    TrendMetric,
)
from muscle50.infrastructure.decimal_text import decimal_to_text

TREND_VERSION = 1
_LABELS = {
    TrendMetric.WEIGHT_KG: "weight",
    TrendMetric.SKELETAL_MUSCLE_MASS_KG: "SMM",
    TrendMetric.BODY_FAT_MASS_KG: "body fat",
    TrendMetric.BODY_FAT_PERCENT: "PBF",
}
_UNITS = {
    TrendMetric.WEIGHT_KG: "kg",
    TrendMetric.SKELETAL_MUSCLE_MASS_KG: "kg",
    TrendMetric.BODY_FAT_MASS_KG: "kg",
    TrendMetric.BODY_FAT_PERCENT: "%",
}
_LABEL_COLUMN = 10


def render_body_composition_trend(trend: BodyCompositionTrend) -> str:
    if not trend.measurements:
        scope = _range_phrase(trend)
        return "No InBody measurements stored." if scope is None else f"No InBody measurements stored in {scope}."
    dates = trend.dates
    count = len(trend.measurements)
    span = dates[0].isoformat() if len(dates) == 1 else f"{dates[0].isoformat()} to {dates[-1].isoformat()}"
    lines = [
        f"InBody body composition trend: {_plural(count, 'measurement')} on {_plural(len(dates), 'date')} ({span})"
    ]
    scope = _range_phrase(trend)
    if scope is not None:
        lines.append(f"Range: {scope}")
    lines.append("Values are stored InBody results rounded to 0.1. Missing values are shown as unknown.")

    lines += ["", "Measurements:"]
    for item in trend.measurements:
        values = "  ".join(f"{_LABELS[metric]} {_amount(item.value(metric), metric)}" for metric in METRICS)
        lines.append(f"  {item.local_date.isoformat()} {item.local_time.strftime('%H:%M')}  {values}")

    if trend.conflicts:
        lines += ["", "Same-date conflicts (left out of the trend):"]
        for conflict in trend.conflicts:
            values = ", ".join(_amount(value, conflict.metric) for value in conflict.values)
            lines.append(f"  {conflict.local_date.isoformat()} {_LABELS[conflict.metric]}: {values}")

    lines += ["", "Between measurements:"]
    if not trend.intervals:
        lines.append("  none (fewer than 2 measurement dates)")
    for interval in trend.intervals:
        changes = ", ".join(
            f"{_LABELS[metric]} {_signed_amount(interval.change(metric), metric)}" for metric in METRICS
        )
        lines.append(
            f"  {interval.from_date.isoformat()} -> {interval.to_date.isoformat()} ({interval.days} d): {changes}"
        )

    lines += ["", "First to last:"]
    lines += [f"  {_LABELS[overall.metric].ljust(_LABEL_COLUMN)}{_overall_text(overall)}" for overall in trend.overall]

    goal = trend.goal
    lines += ["", "Goal (skeletal muscle mass, from training goals):"]
    if goal.latest is None or goal.latest_date is None:
        lines.append(f"  milestone {_kg(goal.milestone.target)}: unknown (no skeletal muscle mass value)")
        lines.append(f"  long-term {_kg(goal.long_term.target)}: unknown")
    else:
        latest = f"latest {_kg(goal.latest)} ({goal.latest_date.isoformat()})"
        lines.append(f"  milestone {_kg(goal.milestone.target)}: {latest}, {_progress_text(goal.milestone)}")
        lines.append(f"  long-term {_kg(goal.long_term.target)}: {_progress_text(goal.long_term)}")

    if trend.last_measurement_date is not None and trend.days_since_last_measurement is not None:
        lines += [
            "",
            f"Last measurement: {trend.last_measurement_date.isoformat()}, "
            f"{_days_relative(trend.days_since_last_measurement)} {trend.reference_date.isoformat()}",
        ]
    return "\n".join(lines)


def render_body_composition_trend_json(trend: BodyCompositionTrend) -> str:
    return json.dumps(_payload(trend), indent=2, ensure_ascii=True)


def _payload(trend: BodyCompositionTrend) -> dict[str, Any]:
    goal = trend.goal
    return {
        "trend_version": TREND_VERSION,
        "from": _date(trend.from_date),
        "to": _date(trend.to_date),
        "reference_date": trend.reference_date.isoformat(),
        "measurement_count": len(trend.measurements),
        "measurements": [
            {
                "measured_at": item.measured_at,
                "local_date": item.local_date.isoformat(),
                **{metric.value: _decimal(item.value(metric)) for metric in METRICS},
            }
            for item in trend.measurements
        ],
        "intervals": [
            {
                "from_date": interval.from_date.isoformat(),
                "to_date": interval.to_date.isoformat(),
                "days": interval.days,
                "changes": {metric.value: _decimal(interval.change(metric)) for metric in METRICS},
            }
            for interval in trend.intervals
        ],
        "overall": {
            overall.metric.value: {
                "from_date": _date(overall.from_date),
                "to_date": _date(overall.to_date),
                "days": overall.days,
                "change": _decimal(overall.change),
                "per_28_days": _decimal(overall.per_28_days),
            }
            for overall in trend.overall
        },
        "goal": {
            "metric": TrendMetric.SKELETAL_MUSCLE_MASS_KG.value,
            "latest": _decimal(goal.latest),
            "latest_date": _date(goal.latest_date),
            "milestone": _progress_payload(goal.milestone),
            "long_term": _progress_payload(goal.long_term),
        },
        "conflicts": [
            {
                "local_date": conflict.local_date.isoformat(),
                "metric": conflict.metric.value,
                "values": [decimal_to_text(value) for value in conflict.values],
            }
            for conflict in trend.conflicts
        ],
        "last_measurement_date": _date(trend.last_measurement_date),
        "days_since_last_measurement": trend.days_since_last_measurement,
    }


def _progress_payload(progress: GoalProgress) -> dict[str, Any]:
    return {
        "target": decimal_to_text(progress.target),
        "remaining": _decimal(progress.remaining),
        "reached": progress.reached,
    }


def _range_phrase(trend: BodyCompositionTrend) -> str | None:
    start, end = trend.from_date, trend.to_date
    if start is not None and end is not None:
        return f"local dates between {start.isoformat()} and {end.isoformat()} (inclusive)"
    if start is not None:
        return f"local dates on or after {start.isoformat()}"
    if end is not None:
        return f"local dates on or before {end.isoformat()}"
    return None


def _overall_text(overall: OverallChange) -> str:
    unit = _UNITS[overall.metric]
    if overall.from_date is None or overall.to_date is None or overall.days is None:
        return "unknown (no usable values)"
    if overall.change is None:
        return f"unknown (one date with a value: {overall.from_date.isoformat()})"
    text = (
        f"{_signed(overall.change)} {unit} over {overall.days} d "
        f"({overall.from_date.isoformat()} -> {overall.to_date.isoformat()}), "
    )
    if overall.per_28_days is None:
        return text + "per 28 d not computed (under 28 d)"
    return text + f"{_signed(overall.per_28_days)} {unit} per 28 d"


def _progress_text(progress: GoalProgress) -> str:
    if progress.reached:
        return "reached"
    if progress.remaining is None:
        return "unknown"
    return f"{_kg(progress.remaining)} to go"


def _days_relative(days: int) -> str:
    # Negative only without --to and a stored date after this computer's today.
    word = "day" if abs(days) == 1 else "days"
    return f"{days} {word} before" if days >= 0 else f"{-days} {word} after"


def _plural(count: int, noun: str) -> str:
    return f"{count} {noun}" if count == 1 else f"{count} {noun}s"


def _amount(value: Decimal | None, metric: TrendMetric) -> str:
    return "unknown" if value is None else f"{decimal_to_text(value)} {_UNITS[metric]}"


def _signed_amount(value: Decimal | None, metric: TrendMetric) -> str:
    return "unknown" if value is None else f"{_signed(value)} {_UNITS[metric]}"


def _signed(value: Decimal) -> str:
    # Zero has no sign ("0.0"); a signed zero would suggest a direction that is not there.
    text = decimal_to_text(value)
    return f"+{text}" if value > 0 else text


def _kg(value: Decimal) -> str:
    return f"{decimal_to_text(value)} kg"


def _decimal(value: Decimal | None) -> str | None:
    return decimal_to_text(value) if value is not None else None


def _date(value: date | None) -> str | None:
    return value.isoformat() if value is not None else None
