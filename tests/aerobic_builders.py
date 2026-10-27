"""Synthetic runs, swims, controls and InBody weights for the Aerobic Guide tests (synthetic values only).

The CLI scenario is dated 2026-11-20 (D). Aerobic minutes cover D-7..D-1 = 2026-11-13..2026-11-19:
run 30003 (11-14, 100 + 40 min) and run 30001 (11-19, 40 + 20 min) give moderate 140 + vigorous 60 = 200;
swim 30002 (11-15) has no intensity minutes (45 min moving), so the total is a lower bound. The walk,
strength session and ``other`` activity are not counted. Run 30001 (12.5 km) is 25 % longer than the
longest run in its 30 days (29990, 10 km on 11-02); run 30003 (8 km) is within. The InBody weights
92.4 -> 92.2 -> 92.1 kg, 14 days apart, lose -0.11 and -0.05 %/week: both below a 0.3 %/week MIN.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from analytics_builders import activity, load_metrics, strength_set
from goal_mode_builders import save
from inbody_trend_builders import measurement, save_measurements

from muscle50.domain.activity import ActivityType, NormalizedActivity
from muscle50.infrastructure.sqlite.database import ActivityRepository

AS_OF = "2026-11-20"
CUT_PLATEAU_GOAL = (
    "goal",
    "set",
    "--mode",
    "cut",
    "--target-body-fat",
    "18",
    "--by",
    "2027-02-28",
    "--min-smm",
    "41",
    "--weekly-loss",
    "0.3",
    "0.5",
    "--plateau-weeks",
    "3",
)
PLATEAU_WEIGHTS = (
    measurement("aero-1", "2026-10-23T08:00:00+09:00", weight=92.4, smm=40.2, bfm=21.3, pbf=23.1),
    measurement("aero-2", "2026-11-06T08:00:00+09:00", weight=92.2, smm=40.1, bfm=21.2, pbf=23.0),
    measurement("aero-3", "2026-11-20T08:00:00+09:00", weight=92.1, smm=40.1, bfm=21.1, pbf=22.9),
)
# Measured values that must never appear in recommend/daily (D1).
MEASURED_TEXTS = ("92.4", "92.2", "92.1", "40.2", "40.1", "21.3", "21.2", "21.1", "71.0")


def minutes(moderate: float | None, vigorous: float | None) -> tuple[Any, ...]:
    """The ten load metrics (1.0 each) with these intensity minutes; None omits a metric."""
    return load_metrics(moderate_intensity_minutes=moderate, vigorous_intensity_minutes=vigorous)


def run(
    source_id: str,
    local: str | None,
    distance: float | None,
    *,
    moderate: float | None = None,
    vigorous: float | None = None,
    moving: float | None = 1800.0,
    **overrides: Any,
) -> NormalizedActivity:
    return activity(
        source_id,
        local,
        ActivityType.RUNNING,
        distance_meters=distance,
        moving_seconds=moving,
        metrics=minutes(moderate, vigorous),
        **overrides,
    )


def swim(
    source_id: str,
    local: str,
    *,
    moderate: float | None = None,
    vigorous: float | None = None,
    moving: float | None = 2700.0,
    elapsed: float | None = 3000.0,
) -> NormalizedActivity:
    return activity(
        source_id,
        local,
        ActivityType.SWIMMING,
        distance_meters=1500.0,
        moving_seconds=moving,
        elapsed_seconds=elapsed,
        metrics=minutes(moderate, vigorous),
    )


def other(source_id: str, local: str, kind: ActivityType) -> NormalizedActivity:
    extra: dict[str, Any] = {}
    if kind is ActivityType.STRENGTH:
        extra["strength_sets"] = (strength_set(1),)
    return activity(source_id, local, kind, distance_meters=3000.0, metrics=minutes(30.0, 30.0), **extra)


def scenario_activities() -> tuple[NormalizedActivity, ...]:
    return (
        run("29990", "2026-11-02T07:00:00", 10000.0, moderate=50.0, vigorous=10.0),
        run("30003", "2026-11-14T07:00:00", 8000.0, moderate=100.0, vigorous=40.0, moving=2880.0),
        swim("30002", "2026-11-15T19:00:00"),
        run("30001", "2026-11-19T07:00:00", 12500.0, moderate=40.0, vigorous=20.0, moving=3720.0),
        other("30004", "2026-11-16T12:00:00", ActivityType.WALKING),
        other("30005", "2026-11-17T18:00:00", ActivityType.STRENGTH),
        other("30006", "2026-11-18T18:00:00", ActivityType.OTHER),
    )


def build_database(root: Path, *, with_activities: bool = True, with_inbody: bool = True) -> Path:
    path = root / "db" / "muscle50.sqlite3"
    ActivityRepository(path).migrate()
    if with_activities:
        for item in scenario_activities():
            save(path, item)
    if with_inbody:
        save_measurements(path, PLATEAU_WEIGHTS)
    return path
