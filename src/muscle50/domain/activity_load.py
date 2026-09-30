"""Canonical activity-load metric contract for Garmin activity-list summaries.

These metrics are read only from the flat activity-list summary shape preserved as the
initial ``summary.json``. They are deliberately not part of ``normalize_activity`` so the
validated refresh path (detail-endpoint shape) keeps writing exactly what it wrote before;
refresh carries existing metric keys it does not produce forward unchanged.

Values are copied verbatim. Range, sign, and physiological plausibility checks belong to
the future Analytics quality layer, so only structurally unusable values are rejected.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from muscle50.domain.activity import ActivityMetric


@dataclass(frozen=True)
class ActivityLoadMetricSpec:
    source_key: str
    metric_key: str
    unit: str


ACTIVITY_LOAD_METRICS: tuple[ActivityLoadMetricSpec, ...] = (
    # Garmin training load score; unitless, so labelled like the existing avg_swolf score.
    ActivityLoadMetricSpec("activityTrainingLoad", "training_load", "score"),
    # Garmin training effect on its 0-5 scale; unitless score.
    ActivityLoadMetricSpec("aerobicTrainingEffect", "aerobic_training_effect", "score"),
    ActivityLoadMetricSpec("anaerobicTrainingEffect", "anaerobic_training_effect", "score"),
    ActivityLoadMetricSpec("hrTimeInZone_1", "hr_time_in_zone_1_seconds", "s"),
    ActivityLoadMetricSpec("hrTimeInZone_2", "hr_time_in_zone_2_seconds", "s"),
    ActivityLoadMetricSpec("hrTimeInZone_3", "hr_time_in_zone_3_seconds", "s"),
    ActivityLoadMetricSpec("hrTimeInZone_4", "hr_time_in_zone_4_seconds", "s"),
    ActivityLoadMetricSpec("hrTimeInZone_5", "hr_time_in_zone_5_seconds", "s"),
    ActivityLoadMetricSpec("moderateIntensityMinutes", "moderate_intensity_minutes", "min"),
    ActivityLoadMetricSpec("vigorousIntensityMinutes", "vigorous_intensity_minutes", "min"),
)

ACTIVITY_LOAD_METRIC_KEYS: frozenset[str] = frozenset(spec.metric_key for spec in ACTIVITY_LOAD_METRICS)


@dataclass(frozen=True)
class ActivityLoadValueIssue:
    source_key: str
    metric_key: str
    kind: Literal["missing", "null", "malformed"]


@dataclass(frozen=True)
class ActivityLoadExtraction:
    metrics: tuple[ActivityMetric, ...]
    issues: tuple[ActivityLoadValueIssue, ...]


def extract_activity_load_metrics(summary: Mapping[str, Any]) -> ActivityLoadExtraction:
    """Map a flat Garmin activity-list summary onto the canonical load metric keys."""
    metrics: list[ActivityMetric] = []
    issues: list[ActivityLoadValueIssue] = []
    for spec in ACTIVITY_LOAD_METRICS:
        if spec.source_key not in summary:
            issues.append(ActivityLoadValueIssue(spec.source_key, spec.metric_key, "missing"))
            continue
        value = summary[spec.source_key]
        if value is None:
            issues.append(ActivityLoadValueIssue(spec.source_key, spec.metric_key, "null"))
            continue
        numeric = _json_number(value)
        if numeric is None:
            issues.append(ActivityLoadValueIssue(spec.source_key, spec.metric_key, "malformed"))
            continue
        metrics.append(ActivityMetric(spec.metric_key, numeric, spec.unit, spec.source_key))
    return ActivityLoadExtraction(tuple(metrics), tuple(issues))


def _json_number(value: Any) -> float | None:
    # JSON numbers only: numeric strings, booleans, and non-finite floats are not
    # silently coerced into a canonical measurement.
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    numeric = float(value)
    return numeric if math.isfinite(numeric) else None
