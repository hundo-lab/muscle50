"""Synthetic strength sessions and wrist heart-rate series for set-timing tests. No real account data.

A session is described row by row; an ACTIVE row may carry ``hidden_s``: the real work started that
many seconds before the (late) button press, inside the preceding REST. The heart-rate generator is
piecewise linear: a flat base, a rise from ``work start + lag`` to ``work end + lag``, then a fall back
to the base.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from analytics_builders import activity

from muscle50.domain.activity import ActivityType, NormalizedActivity, StrengthSet
from muscle50.domain.strength_set_timing import HeartRateSample
from muscle50.infrastructure.raw_store import RawArtifact
from muscle50.infrastructure.sqlite.database import ActivityRepository

EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
SESSION_START = datetime(2026, 3, 12, 1, 0, 0, tzinfo=UTC)
START_MS = (SESSION_START - EPOCH) // timedelta(milliseconds=1)
LAG_MS = 8_000
BASE_BPM = 91.25


def garmin_time(at_ms: int) -> str:
    """Garmin's set ``startTime`` shape: naive UTC with one decimal, e.g. 2026-03-12T01:00:00.0."""
    moment = EPOCH + timedelta(milliseconds=at_ms)
    return moment.strftime("%Y-%m-%dT%H:%M:%S") + f".{moment.microsecond // 100_000}"


@dataclass(frozen=True)
class Active:
    reps: int | None
    seconds: float | None
    category: str | None = "BENCH_PRESS"
    name: str | None = None
    hidden_s: float = 0.0
    lag_ms: int | None = None
    rise_per_s: float = 2.0
    cap: float | None = None


@dataclass(frozen=True)
class Rest:
    seconds: float | None


@dataclass(frozen=True)
class Work:
    start_ms: int
    end_ms: int
    lag_ms: int
    rise_per_s: float
    cap: float | None


@dataclass
class Session:
    sets: tuple[StrengthSet, ...]
    works: list[Work] = field(default_factory=list)
    press_ms: dict[int, int] = field(default_factory=dict)
    """Recorded start (button press) per sequence."""

    @property
    def end_ms(self) -> int:
        return max(work.end_ms + work.lag_ms for work in self.works) + 60_000 if self.works else START_MS


def timed_set(
    sequence: int,
    *,
    set_type: str = "ACTIVE",
    category: str | None = "BENCH_PRESS",
    name: str | None = None,
    reps: int | None = 10,
    seconds: float | None = 20.0,
    started_at: str | None = None,
    weight_kg: float | None = 50.0,
) -> StrengthSet:
    key = name or category
    return StrengthSet(
        sequence=sequence,
        source_message_index=sequence,
        source_exercise_category=category,
        source_exercise_name=name,
        source_exercise_key=key,
        display_exercise_name=key.replace("_", " ").title() if key else None,
        source_exercise_probability=None,
        set_type=set_type,
        reps=reps if set_type == "ACTIVE" else None,
        source_weight=weight_kg * 1000 if weight_kg is not None and set_type == "ACTIVE" else None,
        source_weight_unit="g" if weight_kg is not None and set_type == "ACTIVE" else None,
        normalized_weight_kg=weight_kg if set_type == "ACTIVE" else None,
        duration_seconds=seconds,
        started_at=started_at,
        workout_step_index=None,
    )


def build_session(rows: Sequence[Active | Rest], start_ms: int = START_MS) -> Session:
    """Sets with whole-second start times (Garmin's resolution) and the true work intervals."""
    sets: list[StrengthSet] = []
    session = Session(())
    at = start_ms
    for sequence, row in enumerate(rows, start=1):
        if isinstance(row, Rest):
            sets.append(
                timed_set(sequence, set_type="REST", category=None, seconds=row.seconds, started_at=garmin_time(at))
            )
            duration = row.seconds or 0.0
        else:
            sets.append(
                timed_set(
                    sequence,
                    category=row.category,
                    name=row.name,
                    reps=row.reps,
                    seconds=row.seconds,
                    started_at=garmin_time(at),
                )
            )
            duration = row.seconds or 0.0
            session.press_ms[sequence] = at
            session.works.append(
                Work(
                    start_ms=at - round(row.hidden_s * 1000),
                    end_ms=at + round(duration * 1000),
                    lag_ms=LAG_MS if row.lag_ms is None else row.lag_ms,
                    rise_per_s=row.rise_per_s,
                    cap=row.cap,
                )
            )
        at += round(duration) * 1000
    session.sets = tuple(sets)
    return session


def heart_rate_samples(
    session: Session,
    *,
    step_ms: int = 1000,
    fall_per_s: float = 2.0,
    clock_shift_ms: int = 0,
    drop: Callable[[int], bool] | None = None,
    override: Callable[[int], float | None] | None = None,
) -> list[HeartRateSample]:
    """A piecewise-linear wrist series over the session; ``drop`` removes samples (gaps)."""
    samples: list[HeartRateSample] = []
    for at in range(START_MS - 60_000, session.end_ms + 1, step_ms):
        if drop is not None and drop(at):
            continue
        value = override(at) if override is not None else None
        if value is None:
            value = BASE_BPM + max((_bump(work, at, fall_per_s) for work in session.works), default=0.0)
        samples.append(HeartRateSample(at + clock_shift_ms, value))
    return samples


def _bump(work: Work, at: int, fall_per_s: float) -> float:
    rise_start = work.start_ms + work.lag_ms
    rise_end = work.end_ms + work.lag_ms
    peak = work.rise_per_s * (rise_end - rise_start) / 1000
    if work.cap is not None:
        peak = min(peak, work.cap)
    if at < rise_start:
        return 0.0
    if at <= rise_end:
        value = work.rise_per_s * (at - rise_start) / 1000
        return min(value, work.cap) if work.cap is not None else value
    return max(0.0, peak - fall_per_s * (at - rise_end) / 1000)


def details_payload(
    samples: Iterable[HeartRateSample],
    *,
    order: Sequence[str] = ("sumDuration", "directTimestamp", "directHeartRate"),
    cells: Callable[[HeartRateSample], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """A Garmin ``details.json`` shape; ``order`` sets the descriptor order and so the column order."""
    descriptors = [{"metricsIndex": index, "key": key, "unit": {"key": "synthetic"}} for index, key in enumerate(order)]
    rows = []
    for position, sample in enumerate(samples):
        values: dict[str, Any] = {
            "sumDuration": float(position),
            "directTimestamp": float(sample.at_ms),
            "directHeartRate": sample.bpm,
        }
        if cells is not None:
            values.update(cells(sample))
        rows.append({"metrics": [values.get(key) for key in order]})
    return {"activityId": 1, "metricDescriptors": list(reversed(descriptors)), "activityDetailMetrics": rows}


def strength_activity(source_id: str, session: Session, local_start: str = "2026-03-12T10:00:00") -> NormalizedActivity:
    return activity(source_id, local_start, ActivityType.STRENGTH, strength_sets=session.sets)


def json_bytes(payload: object) -> bytes:
    return (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")


def raw_artifact(home: Path, source_id: str, kind: str, name: str, content: bytes, subdir: str = "") -> RawArtifact:
    """Write one RAW file under ``home`` (as RawStore lays it out) and describe it."""
    relative = f"raw/garmin/activities/{source_id}/{subdir}{name}"
    path = home / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return RawArtifact(kind, relative, "application/json", hashlib.sha256(content).hexdigest(), len(content))


def save_with_details(
    home: Path,
    item: NormalizedActivity,
    details: object | None,
) -> RawArtifact | None:
    """Store an activity with an ``activity`` artifact and, when given, a ``details`` artifact."""
    source_id = item.source_activity_id
    artifacts = [raw_artifact(home, source_id, "activity", "activity.json", json_bytes({"activityId": source_id}))]
    details_artifact = None
    if details is not None:
        details_artifact = raw_artifact(home, source_id, "details", "details.json", json_bytes(details))
        artifacts.append(details_artifact)
    repository = ActivityRepository(home / "db" / "muscle50.sqlite3")
    repository.migrate()
    repository.save(item, tuple(artifacts))
    return details_artifact
