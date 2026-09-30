"""Pure Garmin recovery-to-muscle50 normalization."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from datetime import date
from typing import Any

from muscle50.domain.recovery import DailyRecovery

# Garmin training status keys look like PRODUCTIVE or NO_STATUS. The feedback phrase
# appends a message-variant number (RECOVERY_2) that changes within one status period.
_TRAINING_STATUS_KEY = re.compile(r"[A-Z]+(?:_[A-Z]+)*")
_TRAINING_STATUS_PHRASE = re.compile(r"(?P<key>[A-Z]+(?:_[A-Z]+)*)(?:_\d+)?")


class RecoveryNormalizationError(ValueError):
    """Raised when a recovery date or payload cannot be normalized safely."""


def validate_calendar_date(value: str) -> str:
    try:
        parsed = date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise RecoveryNormalizationError("날짜는 YYYY-MM-DD 형식이어야 합니다.") from exc
    if parsed.isoformat() != value:
        raise RecoveryNormalizationError("날짜는 YYYY-MM-DD 형식이어야 합니다.")
    return value


def normalize_recovery(calendar_date: str, payloads: Mapping[str, Any]) -> DailyRecovery:
    requested_date = validate_calendar_date(calendar_date)
    sleep = _mapping(payloads.get("sleep"))
    sleep_daily = _mapping(sleep.get("dailySleepDTO"))
    sleep_scores = _mapping(sleep_daily.get("sleepScores"))
    sleep_overall = _mapping(sleep_scores.get("overall"))
    hrv = _mapping(payloads.get("hrv"))
    hrv_summary = _mapping(hrv.get("hrvSummary"))
    stats = _mapping(payloads.get("daily_stats"))
    readiness = _morning_readiness(payloads.get("training_readiness"))

    return DailyRecovery(
        calendar_date=requested_date,
        sleep_seconds=_as_int(sleep_daily.get("sleepTimeSeconds")),
        deep_sleep_seconds=_as_int(sleep_daily.get("deepSleepSeconds")),
        light_sleep_seconds=_as_int(sleep_daily.get("lightSleepSeconds")),
        rem_sleep_seconds=_as_int(sleep_daily.get("remSleepSeconds")),
        awake_sleep_seconds=_as_int(sleep_daily.get("awakeSleepSeconds")),
        sleep_start_gmt_ms=_as_int(sleep_daily.get("sleepStartTimestampGMT")),
        sleep_end_gmt_ms=_as_int(sleep_daily.get("sleepEndTimestampGMT")),
        sleep_score=_as_int(sleep_overall.get("value")),
        sleep_avg_hrv_ms=_first_float(sleep_daily.get("avgSleepHRV"), sleep.get("avgOvernightHrv")),
        hrv_last_night_avg_ms=_as_float(hrv_summary.get("lastNightAvg")),
        hrv_weekly_avg_ms=_as_float(hrv_summary.get("weeklyAvg")),
        hrv_status=_as_str(hrv_summary.get("status")),
        resting_heart_rate_bpm=_resting_heart_rate(payloads.get("resting_heart_rate"), requested_date),
        body_battery_high=_as_int(stats.get("bodyBatteryHighestValue")),
        body_battery_low=_as_int(stats.get("bodyBatteryLowestValue")),
        stress_average=_as_nonnegative_int(stats.get("averageStressLevel")),
        training_readiness_score=_as_int(readiness.get("score")),
        training_readiness_level=_as_str(readiness.get("level")),
        recovery_time_minutes=_as_int(readiness.get("recoveryTime")),
        recovery_time_change_phrase=_as_str(readiness.get("recoveryTimeChangePhrase")),
        training_status_key=_training_status(payloads.get("training_status")),
        respiration_avg_brpm=_as_float(sleep_daily.get("averageRespirationValue")),
    )


def recovery_date_warnings(calendar_date: str, payloads: Mapping[str, Any]) -> tuple[str, ...]:
    requested_date = validate_calendar_date(calendar_date)
    candidates = {
        "sleep": _nested_value(payloads.get("sleep"), "dailySleepDTO", "calendarDate"),
        "hrv": _nested_value(payloads.get("hrv"), "hrvSummary", "calendarDate"),
        "daily stats": _mapping(payloads.get("daily_stats")).get("calendarDate"),
        "stress": _mapping(payloads.get("stress")).get("calendarDate"),
        "respiration": _mapping(payloads.get("respiration")).get("calendarDate"),
    }
    warnings = [
        f"{label} 응답 날짜({value})가 요청 날짜({requested_date})와 다릅니다."
        for label, value in candidates.items()
        if isinstance(value, str) and value != requested_date
    ]
    for endpoint in ("resting_heart_rate", "body_battery", "training_readiness"):
        values = _calendar_dates(payloads.get(endpoint))
        unexpected = values - {requested_date}
        if unexpected:
            rendered = ", ".join(sorted(unexpected))
            warnings.append(f"{endpoint} 응답 날짜({rendered})가 요청 날짜({requested_date})와 다릅니다.")
    return tuple(warnings)


def _morning_readiness(value: Any) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    rows = _mapping_sequence(value)
    if not rows:
        return {}
    return next((row for row in rows if row.get("inputContext") == "AFTER_WAKEUP_RESET"), rows[0])


def _resting_heart_rate(value: Any, calendar_date: str) -> float | None:
    rows = _mapping_sequence(value)
    row = next((item for item in rows if item.get("calendarDate") == calendar_date), None)
    if row is None and len(rows) == 1:
        row = rows[0]
    return _as_float(row.get("value")) if row is not None else None


def _training_status(value: Any) -> str | None:
    """One unambiguous Garmin training status key, e.g. ``PRODUCTIVE``.

    Supports an explicit string ``trainingStatusKey``/``trainingStatus`` and the observed
    ``latestTrainingStatusData`` shape, where ``trainingStatus`` is a numeric code and the
    key is the prefix of ``trainingStatusFeedbackPhrase``. The numeric code is never used.
    """
    candidates: set[str] = set()

    def visit(item: Any) -> None:
        if isinstance(item, Mapping):
            candidate = _status_key(item.get("trainingStatusKey")) or _status_key(item.get("trainingStatus"))
            if candidate is None:
                candidate = _status_phrase_key(item.get("trainingStatusFeedbackPhrase"))
            if candidate is not None:
                candidates.add(candidate)
            for key, nested in item.items():
                if key not in {"trainingStatus", "trainingStatusKey", "trainingStatusFeedbackPhrase"}:
                    visit(nested)
        elif isinstance(item, Sequence) and not isinstance(item, (str, bytes)):
            for nested in item:
                visit(nested)

    visit(value)
    return next(iter(candidates)) if len(candidates) == 1 else None


def _status_key(value: Any) -> str | None:
    text = _as_str(value)
    return text if text is not None and _TRAINING_STATUS_KEY.fullmatch(text) else None


def _status_phrase_key(value: Any) -> str | None:
    text = _as_str(value)
    match = _TRAINING_STATUS_PHRASE.fullmatch(text) if text is not None else None
    return match.group("key") if match is not None else None


def _calendar_dates(value: Any) -> set[str]:
    keys = {"calendarDate", "date"}
    return {
        item[key]
        for item in _mapping_sequence(value)
        for key in keys
        if isinstance(item.get(key), str)
    }


def _nested_value(value: Any, *keys: str) -> Any:
    current = value
    for key in keys:
        current = _mapping(current).get(key)
    return current


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _mapping_sequence(value: Any) -> list[Mapping[str, Any]]:
    if isinstance(value, Mapping):
        return [value]
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _as_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _first_float(*values: Any) -> float | None:
    for value in values:
        numeric = _as_float(value)
        if numeric is not None:
            return numeric
    return None


def _as_int(value: Any) -> int | None:
    numeric = _as_float(value)
    return int(numeric) if numeric is not None and numeric.is_integer() else None


def _as_nonnegative_int(value: Any) -> int | None:
    numeric = _as_int(value)
    return numeric if numeric is not None and numeric >= 0 else None


def _as_str(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None
