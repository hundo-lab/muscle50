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


def _observed_training_status(*entries: dict[str, Any]) -> dict[str, Any]:
    """The stored real get_training_status shape (synthetic device IDs)."""
    return {
        "userId": 1,
        "mostRecentVO2Max": None,
        "mostRecentTrainingLoadBalance": None,
        "heatAltitudeAcclimationDTO": None,
        "mostRecentTrainingStatus": {
            "userId": 1,
            "lastPrimarySyncDate": "2026-09-28",
            "showSelector": False,
            "recordedDevices": [{"deviceId": 900 + index, "deviceName": "Synthetic"} for index in range(len(entries))],
            "latestTrainingStatusData": {
                str(900 + index): {
                    "calendarDate": "2026-09-28",
                    "deviceId": 900 + index,
                    "primaryTrainingDevice": index == 0,
                    "sinceDate": "2026-09-26",
                    "trainingPaused": False,
                    "acuteTrainingLoadDTO": {"acwrStatus": "OPTIMAL", "acwrStatusFeedback": "FEEDBACK_2"},
                    **entry,
                }
                for index, entry in enumerate(entries)
            },
        },
    }


@pytest.mark.parametrize(
    ("entry", "expected"),
    [
        ({"trainingStatus": 5, "trainingStatusFeedbackPhrase": "RECOVERY_2"}, "RECOVERY"),
        ({"trainingStatus": 7, "trainingStatusFeedbackPhrase": "PRODUCTIVE_6"}, "PRODUCTIVE"),
        ({"trainingStatus": 4, "trainingStatusFeedbackPhrase": "MAINTAINING_1"}, "MAINTAINING"),
        ({"trainingStatus": 0, "trainingStatusFeedbackPhrase": "NO_STATUS"}, "NO_STATUS"),
    ],
)
def test_observed_nested_training_status_uses_phrase_key_not_numeric_code(entry: dict[str, Any], expected: str) -> None:
    payloads = {**_payloads(), "training_status": _observed_training_status(entry)}

    assert normalize_recovery("2026-09-28", payloads).training_status_key == expected


@pytest.mark.parametrize(
    "entry",
    [
        {"trainingStatus": 5},
        {"trainingStatus": 5, "trainingStatusFeedbackPhrase": None},
        {"trainingStatus": 5, "trainingStatusFeedbackPhrase": ""},
        {"trainingStatus": 5, "trainingStatusFeedbackPhrase": "recovery_2"},
        {"trainingStatus": 5, "trainingStatusFeedbackPhrase": "RECOVERY_2_EXTRA"},
        {"trainingStatus": "5"},
        {"trainingStatus": None, "trainingStatusFeedbackPhrase": 5},
    ],
)
def test_numeric_missing_or_malformed_training_status_is_not_claimed(entry: dict[str, Any]) -> None:
    payloads = {**_payloads(), "training_status": _observed_training_status(entry)}

    assert normalize_recovery("2026-09-28", payloads).training_status_key is None


def test_explicit_string_training_status_wins_over_feedback_phrase() -> None:
    entry = {"trainingStatus": "PRODUCTIVE", "trainingStatusFeedbackPhrase": "RECOVERY_2"}
    payloads = {**_payloads(), "training_status": _observed_training_status(entry)}

    assert normalize_recovery("2026-09-28", payloads).training_status_key == "PRODUCTIVE"


def test_multi_device_phrase_statuses_follow_the_ambiguity_rule() -> None:
    same = _observed_training_status(
        {"trainingStatus": 5, "trainingStatusFeedbackPhrase": "RECOVERY_1"},
        {"trainingStatus": 5, "trainingStatusFeedbackPhrase": "RECOVERY_2"},
    )
    different = _observed_training_status(
        {"trainingStatus": 5, "trainingStatusFeedbackPhrase": "RECOVERY_2"},
        {"trainingStatus": 7, "trainingStatusFeedbackPhrase": "PRODUCTIVE_1"},
    )

    assert normalize_recovery("2026-09-28", {"training_status": same}).training_status_key == "RECOVERY"
    assert normalize_recovery("2026-09-28", {"training_status": different}).training_status_key is None


def test_observed_top_level_overnight_hrv_populates_sleep_hrv() -> None:
    payloads = _payloads()
    del payloads["sleep"]["dailySleepDTO"]["avgSleepHRV"]
    payloads["sleep"]["avgOvernightHrv"] = 62.0

    assert normalize_recovery("2026-09-15", payloads).sleep_avg_hrv_ms == 62.0


def test_daily_sleep_dto_hrv_keeps_precedence_over_overnight_hrv() -> None:
    payloads = _payloads()
    payloads["sleep"]["avgOvernightHrv"] = 62.0

    assert normalize_recovery("2026-09-15", payloads).sleep_avg_hrv_ms == 52.5


@pytest.mark.parametrize(
    ("daily_value", "overnight_value", "expected"),
    [
        (None, None, None),
        (None, "not-a-number", None),
        (None, True, None),
        ("bad", 61.0, 61.0),
        (None, 0, 0.0),
    ],
)
def test_sleep_hrv_missing_null_and_malformed_values(
    daily_value: Any, overnight_value: Any, expected: float | None
) -> None:
    payloads = _payloads()
    payloads["sleep"]["dailySleepDTO"]["avgSleepHRV"] = daily_value
    payloads["sleep"]["avgOvernightHrv"] = overnight_value

    assert normalize_recovery("2026-09-15", payloads).sleep_avg_hrv_ms == expected


def test_observed_no_sleep_day_leaves_sleep_hrv_empty() -> None:
    payloads = {
        "sleep": {"dailySleepDTO": {"calendarDate": "2026-09-13", "sleepTimeSeconds": None}, "avgOvernightHrv": None}
    }

    recovery = normalize_recovery("2026-09-13", payloads)

    assert recovery.sleep_avg_hrv_ms is None
    assert recovery.sleep_seconds is None
