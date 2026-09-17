"""Normalized Garmin recovery and daily-health values."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DailyRecovery:
    """Garmin's night-ending and same-day recovery values for one calendar date.

    Sleep and HRV describe the night ending on ``calendar_date``. The remaining
    values describe that calendar day. Values are copied from Garmin rollups; this
    type does not calculate a proprietary recovery score.
    """

    calendar_date: str
    sleep_seconds: int | None
    deep_sleep_seconds: int | None
    light_sleep_seconds: int | None
    rem_sleep_seconds: int | None
    awake_sleep_seconds: int | None
    sleep_start_gmt_ms: int | None
    sleep_end_gmt_ms: int | None
    sleep_score: int | None
    sleep_avg_hrv_ms: float | None
    hrv_last_night_avg_ms: float | None
    hrv_weekly_avg_ms: float | None
    hrv_status: str | None
    resting_heart_rate_bpm: float | None
    body_battery_high: int | None
    body_battery_low: int | None
    stress_average: int | None
    training_readiness_score: int | None
    training_readiness_level: str | None
    recovery_time_minutes: int | None
    recovery_time_change_phrase: str | None
    training_status_key: str | None
    respiration_avg_brpm: float | None
    normalizer_version: int = 1
