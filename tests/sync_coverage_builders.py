"""Synthetic databases and fake Garmin accounts shared by the sync-coverage tests and goldens.

The recommend database is the `tests/test_recommend_cli.py` ``database`` fixture and the daily
account is `tests/test_daily_sync.py` ``_account()``, copied verbatim so the goldens in
``tests/fixtures/sync_coverage_golden/`` describe exactly those inputs. Synthetic values only.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import date, timedelta, timezone
from pathlib import Path
from typing import Any

from analytics_builders import activity, recovery, strength_set, swim_detail, uniform_lap

from muscle50.domain.activity import ActivityType, NormalizedActivity
from muscle50.infrastructure.garmin.client import (
    GarminAuthenticationError,
    GarminConnectorError,
    GarminRawActivity,
    GarminRawRecovery,
)
from muscle50.infrastructure.raw_store import RawArtifact, RecoveryCapture
from muscle50.infrastructure.sqlite.database import ActivityRepository, DailyRecoveryRepository

GOLDEN_DIR = Path(__file__).parent / "fixtures" / "sync_coverage_golden"
KST = timezone(timedelta(hours=9))
RECOMMEND_DATE = "2026-03-16"
DAILY_TODAY = date(2026, 10, 2)
# Every recovery endpoint kind, in PythonGarminConnector.fetch_raw_recovery order.
ALL_RECOVERY_KINDS = (
    "sleep",
    "daily_stats",
    "hrv",
    "resting_heart_rate",
    "body_battery",
    "stress",
    "training_readiness",
    "training_status",
    "respiration",
)


def golden(name: str) -> str:
    return (GOLDEN_DIR / name).read_bytes().decode("utf-8")


# --- the test_recommend_cli database -------------------------------------------------------


def _save(database: Path, item: NormalizedActivity) -> None:
    artifact = RawArtifact("activity", f"raw/{item.source_activity_id}/activity.json", "application/json", "0" * 64, 2)
    ActivityRepository(database).save(item, (artifact,))


def save_recovery(database: Path, calendar_date: str, kinds: Sequence[str] = ("sleep",), **overrides: object) -> None:
    """A recovery row whose accepted capture has the given RAW artifact kinds (default: sleep only)."""
    capture = RecoveryCapture(
        capture_id=f"capture-{calendar_date}",
        requested_date=calendar_date,
        manifest_relative_path=f"recovery/{calendar_date}/manifest.json",
        artifacts=tuple(
            RawArtifact(kind, f"recovery/{calendar_date}/{kind}.json", "application/json", "0" * 64, 2)
            for kind in kinds
        ),
    )
    DailyRecoveryRepository(database).save(recovery(calendar_date, **overrides), capture)


def _bench(source_id: str, day: str, *, unknown: bool = False) -> NormalizedActivity:
    sets = [strength_set(index, reps=10, weight_kg=50.0) for index in range(1, 4)]
    if unknown:
        sets.append(strength_set(4, category="UNKNOWN", reps=8, weight_kg=40.0))
    return activity(source_id, f"{day}T12:00:00", ActivityType.STRENGTH, strength_sets=tuple(sets))


def fill_recommend_database(path: Path) -> None:
    """The test_recommend_cli rows on an already-migrated database."""
    _save(path, _bench("8001", "2026-03-10", unknown=True))
    _save(path, _bench("8002", "2026-03-13"))
    _save(path, _bench("8003", "2026-03-16"))  # same day as the requested date
    _save(
        path,
        activity(
            "8100",
            "2026-03-16T06:00:00",
            ActivityType.SWIMMING,
            distance_meters=400.0,
            swim_detail=swim_detail("8100", (uniform_lap(0, 16, 25.0, 30.0),)),
        ),
    )
    save_recovery(path, "2026-03-15")
    save_recovery(path, "2026-03-16", sleep_seconds=None)


def build_recommend_database(root: Path) -> Path:
    """`<root>/db/muscle50.sqlite3`, migrated by every migration file, with the test_recommend_cli rows."""
    path = root / "db" / "muscle50.sqlite3"
    ActivityRepository(path).migrate()
    fill_recommend_database(path)
    return path


# Synthetic targets set with `nutrition target set` for the "with targets" goldens.
TARGET_COMMANDS = (
    ("nutrition", "target", "set", "protein", "--exact", "120"),
    ("nutrition", "target", "set", "carbs", "--range", "150", "220"),
)


# --- the test_daily_sync fake account --------------------------------------------------------


def summary(activity_id: int, type_key: str, local_date: str, local_time: str, **extra: Any) -> dict[str, Any]:
    return {
        "activityId": activity_id,
        "activityName": f"Synthetic Activity {activity_id}",
        "activityType": {"typeKey": type_key},
        "startTimeLocal": f"{local_date} {local_time}",
        "startTimeGMT": f"{local_date} {local_time}",
        "duration": 1800.0,
        "distance": 0.0,
        **extra,
    }


def _strength_sets() -> dict[str, Any]:
    data: object = json.loads((Path(__file__).parent / "fixtures" / "synthetic_strength_sets.json").read_text("utf-8"))
    assert isinstance(data, dict)
    return data


def recovery_payloads(calendar_date: str, kinds: Sequence[str] = ("sleep", "daily_stats", "hrv")) -> dict[str, Any]:
    """Synthetic payloads; the default three kinds are the test_daily_sync account's."""
    known: dict[str, Any] = {
        "sleep": {"dailySleepDTO": {"calendarDate": calendar_date, "sleepTimeSeconds": 27000}},
        "daily_stats": {"calendarDate": calendar_date, "bodyBatteryHighestValue": 90, "bodyBatteryLowestValue": 25},
        "hrv": {"hrvSummary": {"calendarDate": calendar_date, "lastNightAvg": 48}},
    }
    # The other endpoints answered "no data" (null), which is a successful call, not a failure.
    return {kind: known.get(kind) for kind in kinds}


class FakeGarmin:
    """One fake session for both activity and recovery endpoints, newest activity first."""

    def __init__(
        self,
        summaries: Sequence[Mapping[str, Any]],
        *,
        fail_activity_ids: frozenset[str] = frozenset(),
        recovery_kinds: Sequence[str] = ("sleep", "daily_stats", "hrv"),
        recovery_kinds_by_date: Mapping[str, Sequence[str]] | None = None,
        recovery_failures: Mapping[str, Exception] | None = None,
        list_error: Exception | None = None,
    ):
        self._summaries = list(summaries)
        self._fail_activity_ids = fail_activity_ids
        self._recovery_kinds = tuple(recovery_kinds)
        self._recovery_kinds_by_date = dict(recovery_kinds_by_date or {})
        self._recovery_failures = dict(recovery_failures or {})
        self._list_error = list_error
        self.list_calls: list[tuple[int, int]] = []
        self.activity_calls: list[str] = []
        self.recovery_calls: list[str] = []

    def latest_summary(self) -> Mapping[str, Any] | None:
        raise AssertionError("range commands must not use latest")

    def list_activities(self, start: int, limit: int) -> Sequence[Mapping[str, Any]]:
        self.list_calls.append((start, limit))
        if self._list_error is not None:
            raise self._list_error
        return self._summaries[start : start + limit]

    def fetch_raw_activity(self, activity_id: str, source_type_key: str) -> GarminRawActivity:
        self.activity_calls.append(activity_id)
        if activity_id in self._fail_activity_ids:
            raise GarminConnectorError("synthetic activity failure")
        return GarminRawActivity(
            summary={},
            activity={"activityId": int(activity_id)},
            details={"activityId": int(activity_id), "metricDescriptors": []},
            splits={"lapDTOs": []},
            exercise_sets=_strength_sets() if source_type_key == "strength_training" else None,
            original_archive=b"synthetic-original-archive",
            warnings=(),
        )

    def fetch_raw_recovery(self, calendar_date: str) -> GarminRawRecovery:
        self.recovery_calls.append(calendar_date)
        failure = self._recovery_failures.get(calendar_date)
        if failure is not None:
            raise failure
        kinds = self._recovery_kinds_by_date.get(calendar_date, self._recovery_kinds)
        return GarminRawRecovery(calendar_date, recovery_payloads(calendar_date, kinds), ())


def daily_account(**kwargs: Any) -> FakeGarmin:
    """The test_daily_sync account: activities on 2026-10-02 and 2026-10-01, one older run."""
    return FakeGarmin(
        [
            summary(300, "running", "2026-10-02", "07:00:00", activityTrainingLoad=55.5, aerobicTrainingEffect=2.4),
            summary(222, "strength_training", "2026-10-01", "18:00:00", activityTrainingLoad=40.0),
            summary(100, "running", "2026-09-29", "07:00:00", activityTrainingLoad=30.0),  # before D-1
        ],
        **kwargs,
    )


AUTH_FAILURE = GarminAuthenticationError("Garmin recovery 인증에 실패했습니다.")
