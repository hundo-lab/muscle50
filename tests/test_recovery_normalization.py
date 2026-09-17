from __future__ import annotations

from typing import Any

import pytest

from muscle50.domain.recovery_normalization import (
    RecoveryNormalizationError,
    normalize_recovery,
    recovery_date_warnings,
    validate_calendar_date,
)


def _payloads() -> dict[str, Any]:
    return {
        "sleep": {
            "dailySleepDTO": {
                "calendarDate": "2026-09-15",
                "sleepTimeSeconds": 28800,
                "deepSleepSeconds": 4200,
                "lightSleepSeconds": 16500,
                "remSleepSeconds": 6300,
                "awakeSleepSeconds": 1800,
                "sleepStartTimestampGMT": 1789412400000,
                "sleepEndTimestampGMT": 1789441200000,
                "avgSleepHRV": 52.5,
                "averageRespirationValue": 13.4,
                "sleepScores": {"overall": {"value": 84}},
            }
        },
        "hrv": {
            "hrvSummary": {
                "calendarDate": "2026-09-15",
                "lastNightAvg": 51,
                "weeklyAvg": 49,
                "status": "BALANCED",
            }
        },
        "resting_heart_rate": [{"calendarDate": "2026-09-15", "value": 47}],
        "daily_stats": {
            "calendarDate": "2026-09-15",
            "bodyBatteryHighestValue": 92,
            "bodyBatteryLowestValue": 31,
            "averageStressLevel": 24,
        },
        "body_battery": [{"date": "2026-09-15", "charged": 61}],
        "stress": {"calendarDate": "2026-09-15", "stressValuesArray": []},
        "training_readiness": [
            {"calendarDate": "2026-09-15", "score": 43, "inputContext": "DAILY"},
            {
                "calendarDate": "2026-09-15",
                "score": 79,
                "level": "HIGH",
                "recoveryTime": 360,
                "recoveryTimeChangePhrase": "DECREASED",
                "inputContext": "AFTER_WAKEUP_RESET",
            },
        ],
        "training_status": {
            "deviceMap": {"123": {"mostRecentTrainingStatus": {"trainingStatus": "PRODUCTIVE"}}}
        },
        "respiration": {"calendarDate": "2026-09-15", "avgWakingRespirationValue": 14},
    }


def test_normalizes_supported_daily_rollups_without_deriving_values() -> None:
    recovery = normalize_recovery("2026-09-15", _payloads())

    assert recovery.sleep_seconds == 28800
    assert recovery.deep_sleep_seconds == 4200
    assert recovery.light_sleep_seconds == 16500
    assert recovery.rem_sleep_seconds == 6300
    assert recovery.awake_sleep_seconds == 1800
    assert recovery.sleep_start_gmt_ms == 1789412400000
    assert recovery.sleep_end_gmt_ms == 1789441200000
    assert recovery.sleep_score == 84
    assert recovery.sleep_avg_hrv_ms == 52.5
    assert recovery.hrv_last_night_avg_ms == 51
    assert recovery.hrv_weekly_avg_ms == 49
    assert recovery.hrv_status == "BALANCED"
    assert recovery.resting_heart_rate_bpm == 47
    assert recovery.body_battery_high == 92
    assert recovery.body_battery_low == 31
    assert recovery.stress_average == 24
    assert recovery.training_readiness_score == 79
    assert recovery.training_readiness_level == "HIGH"
    assert recovery.recovery_time_minutes == 360
    assert recovery.recovery_time_change_phrase == "DECREASED"
    assert recovery.training_status_key == "PRODUCTIVE"
    assert recovery.respiration_avg_brpm == 13.4


@pytest.mark.parametrize(
    "payloads",
    [
        {},
        {"sleep": None, "hrv": None, "daily_stats": None},
        {"sleep": {}, "hrv": {}, "daily_stats": {}},
        {"sleep": {"dailySleepDTO": {}}, "daily_stats": {"averageStressLevel": -1}},
        {"sleep": "malformed", "training_readiness": 42, "training_status": []},
    ],
)
def test_missing_null_empty_and_unsupported_values_remain_none(payloads: dict[str, Any]) -> None:
    recovery = normalize_recovery("2026-09-15", payloads)

    assert recovery.sleep_seconds is None
    assert recovery.hrv_last_night_avg_ms is None
    assert recovery.body_battery_high is None
    assert recovery.stress_average is None
    assert recovery.training_readiness_score is None
    assert recovery.training_status_key is None


def test_ambiguous_training_status_is_not_claimed() -> None:
    payloads = _payloads()
    payloads["training_status"] = [
        {"trainingStatus": "PRODUCTIVE"},
        {"trainingStatus": "RECOVERY"},
    ]

    assert normalize_recovery("2026-09-15", payloads).training_status_key is None


def test_response_date_mismatches_become_warnings() -> None:
    payloads = _payloads()
    payloads["sleep"]["dailySleepDTO"]["calendarDate"] = "2026-09-14"
    payloads["resting_heart_rate"] = [{"calendarDate": "2026-09-14", "value": 47}]

    warnings = recovery_date_warnings("2026-09-15", payloads)

    assert any("sleep 응답 날짜" in warning for warning in warnings)
    assert any("resting_heart_rate 응답 날짜" in warning for warning in warnings)


@pytest.mark.parametrize("value", ["2026-9-1", "2026-02-30", "not-a-date", ""])
def test_invalid_calendar_date_is_rejected(value: str) -> None:
    with pytest.raises(RecoveryNormalizationError):
        validate_calendar_date(value)
