from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from muscle50.application.sync_garmin_recovery import SyncGarminRecovery
from muscle50.infrastructure.garmin.client import GarminRawRecovery
from muscle50.infrastructure.raw_store import RecoveryRawStore
from muscle50.infrastructure.sqlite.database import DailyRecoveryRepository
from muscle50.presentation.terminal import render_recovery_sync_result


def _payloads(body_battery_high: int = 90) -> dict[str, Any]:
    return {
        "sleep": {
            "dailySleepDTO": {
                "calendarDate": "2026-09-15",
                "sleepTimeSeconds": 27000,
                "sleepScores": {"overall": {"value": 81}},
                "averageRespirationValue": 13.2,
            }
        },
        "daily_stats": {
            "calendarDate": "2026-09-15",
            "bodyBatteryHighestValue": body_battery_high,
            "bodyBatteryLowestValue": 25,
            "averageStressLevel": 29,
        },
        "hrv": {"hrvSummary": {"calendarDate": "2026-09-15", "lastNightAvg": 48}},
        "resting_heart_rate": [{"calendarDate": "2026-09-15", "value": 49}],
        "body_battery": [{"date": "2026-09-15", "charged": 65}],
        "stress": {"calendarDate": "2026-09-15"},
        "training_readiness": [
            {
                "calendarDate": "2026-09-15",
                "score": 76,
                "level": "HIGH",
                "recoveryTime": 120,
                "inputContext": "AFTER_WAKEUP_RESET",
            }
        ],
        "training_status": {"trainingStatus": "MAINTAINING"},
        "respiration": {"calendarDate": "2026-09-15"},
    }


class FakeRecoveryConnector:
    def __init__(self, payloads: dict[str, Any], warnings: tuple[str, ...] = ()):
        self.payloads = payloads
        self.warnings = warnings
        self.calls = 0

    def fetch_raw_recovery(self, calendar_date: str) -> GarminRawRecovery:
        self.calls += 1
        return GarminRawRecovery(calendar_date, self.payloads, self.warnings)


def _use_case(root: Path, connector: FakeRecoveryConnector) -> SyncGarminRecovery:
    repository = DailyRecoveryRepository(root / "db" / "muscle50.sqlite3")
    repository.migrate()
    return SyncGarminRecovery(
        connector,
        repository,
        RecoveryRawStore(root / "raw" / "garmin" / "recovery", root, root / "tmp"),
    )


def test_repeated_sync_is_unchanged_and_changed_payload_updates_daily_row(tmp_path: Path) -> None:
    root = tmp_path / "private-muscle50"
    connector = FakeRecoveryConnector(_payloads())
    use_case = _use_case(root, connector)

    first = use_case.execute("2026-09-15")
    second = use_case.execute("2026-09-15")
    connector.payloads = _payloads(body_battery_high=96)
    third = use_case.execute("2026-09-15")

    assert (first.created, first.updated) == (True, False)
    assert (second.created, second.updated) == (False, False)
    assert (third.created, third.updated) == (False, True)
    assert third.recovery.body_battery_high == 96
    assert connector.calls == 3

    database_path = root / "db" / "muscle50.sqlite3"
    repository = DailyRecoveryRepository(database_path)
    with sqlite3.connect(database_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM daily_recovery").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM recovery_raw_captures").fetchone()[0] == 2
        assert connection.execute("SELECT COUNT(*) FROM recovery_raw_artifacts").fetchone()[0] == 18
        assert connection.execute("SELECT body_battery_high FROM daily_recovery").fetchone()[0] == 96

    assert repository.find("2026-09-15") == third.recovery
    latest_capture = repository.find_source_capture("2026-09-15")
    assert latest_capture is not None
    assert latest_capture.requested_date == "2026-09-15"
    assert {artifact.kind for artifact in latest_capture.artifacts} == set(_payloads())
    assert (root / latest_capture.manifest_relative_path).is_file()

    manifests = list((root / "raw" / "garmin" / "recovery" / "2026-09-15").glob("*/manifest.json"))
    assert len(manifests) == 2
    assert all(json.loads(path.read_text(encoding="utf-8"))["requested_date"] == "2026-09-15" for path in manifests)
    output = render_recovery_sync_result(third)
    assert "recovery 갱신 완료" in output
    assert "Recovery — 2026-09-15" in output
    assert "Training Readiness: 76 (HIGH)" in output
    assert "Training Status: MAINTAINING" in output


def test_partial_response_saves_available_metric_and_diagnostic(tmp_path: Path) -> None:
    root = tmp_path / "private-muscle50"
    connector = FakeRecoveryConnector(
        {"sleep": {"dailySleepDTO": {"calendarDate": "2026-09-15", "sleepTimeSeconds": 25200}}},
        ("Body Battery 원본을 가져오지 못했습니다.",),
    )

    result = _use_case(root, connector).execute("2026-09-15")

    assert result.created is True
    assert result.recovery.sleep_seconds == 25200
    assert result.recovery.body_battery_high is None
    assert result.warnings == ("Body Battery 원본을 가져오지 못했습니다.",)
    capture = DailyRecoveryRepository(root / "db" / "muscle50.sqlite3").find_source_capture("2026-09-15")
    assert capture is not None
    assert [artifact.kind for artifact in capture.artifacts] == ["sleep"]
    manifest = json.loads((root / capture.manifest_relative_path).read_text(encoding="utf-8"))
    assert manifest["warnings"] == ["Body Battery 원본을 가져오지 못했습니다."]


def test_same_raw_capture_can_refresh_an_outdated_normalized_row(tmp_path: Path) -> None:
    root = tmp_path / "private-muscle50"
    connector = FakeRecoveryConnector(_payloads())
    use_case = _use_case(root, connector)
    use_case.execute("2026-09-15")
    database_path = root / "db" / "muscle50.sqlite3"
    with sqlite3.connect(database_path) as connection:
        connection.execute("UPDATE daily_recovery SET normalizer_version = 0")

    refreshed = use_case.execute("2026-09-15")

    assert (refreshed.created, refreshed.updated) == (False, True)
    assert refreshed.recovery.normalizer_version == 1
    with sqlite3.connect(database_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM recovery_raw_captures").fetchone()[0] == 1
        assert connection.execute("SELECT normalizer_version FROM daily_recovery").fetchone()[0] == 1


def test_no_data_date_stores_null_raw_payloads_without_inventing_zeroes(tmp_path: Path) -> None:
    root = tmp_path / "private-muscle50"
    payloads = {kind: None for kind in _payloads()}

    result = _use_case(root, FakeRecoveryConnector(payloads)).execute("2026-09-15")

    assert result.created is True
    assert result.recovery.sleep_seconds is None
    assert result.recovery.training_readiness_score is None
    capture = DailyRecoveryRepository(root / "db" / "muscle50.sqlite3").find_source_capture("2026-09-15")
    assert capture is not None
    assert len(capture.artifacts) == 9
    for artifact in capture.artifacts:
        assert (root / artifact.relative_path).read_text(encoding="utf-8") == "null\n"
    output = render_recovery_sync_result(result)
    assert "Sleep: unavailable" in output
    assert "Training Status: unavailable" in output
