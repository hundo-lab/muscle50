"""Synthetic runs, legs sessions and InBody rows for the Training Goal Mode tests (synthetic values only).

Built on the recommend golden database (``sync_coverage_builders.build_recommend_database``) so the
no-goal outputs can be compared with the goldens byte for byte.
"""

from __future__ import annotations

from pathlib import Path

from analytics_builders import activity, strength_set
from inbody_trend_builders import measurement, save_measurements

from muscle50.domain.activity import ActivityType, NormalizedActivity
from muscle50.infrastructure.raw_store import RawArtifact
from muscle50.infrastructure.sqlite.database import ActivityRepository

CUT_GOAL = (
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
)
GAIN_GOAL = ("goal", "set", "--mode", "gain", "--min-smm", "35")

# 80.0 -> 78.0 kg over 28 days is exactly -0.625 %/week (displayed -0.62, HALF_EVEN); fat-free mass on
# the latest date is 78.0 - 15.0 = 63.0 kg (PRO-05: 144.9 -> 145 g and 195.3 -> 195 g).
INBODY_ROWS = (
    measurement("goal-1", "2026-02-16T08:00:00+09:00", weight=80.0, smm=36.0, bfm=16.0, pbf=20.0),
    measurement("goal-2", "2026-03-16T07:30:00+09:00", weight=78.0, smm=35.9, bfm=15.0, pbf=19.2),
)


def save(database: Path, item: NormalizedActivity) -> None:
    artifact = RawArtifact("activity", f"raw/{item.source_activity_id}/activity.json", "application/json", "0" * 64, 2)
    ActivityRepository(database).save(item, (artifact,))


def run(source_id: str, local: str, utc: str | None) -> NormalizedActivity:
    return activity(source_id, local, ActivityType.RUNNING, started_at_utc=utc, distance_meters=5000.0)


def legs(
    source_id: str, local: str, utc: str | None, *, sets: int = 3, category: str = "SQUAT", weight_kg: float = 60.0
) -> NormalizedActivity:
    return activity(
        source_id,
        local,
        ActivityType.STRENGTH,
        started_at_utc=utc,
        strength_sets=tuple(
            strength_set(index, category=category, reps=10, weight_kg=weight_kg) for index in range(1, sets + 1)
        ),
    )


def add_run_and_legs(database: Path) -> None:
    """A run at 07:00 and a squat session at 08:00 local (KST) on 2026-03-12."""
    save(database, run("9001", "2026-03-12T07:00:00", "2026-03-11T22:00:00+00:00"))
    save(database, legs("9002", "2026-03-12T08:00:00", "2026-03-11T23:00:00+00:00"))


def add_inbody(database: Path) -> None:
    save_measurements(database, INBODY_ROWS)
