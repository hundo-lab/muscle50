from __future__ import annotations

from typing import Any

import pytest
from garminconnect import GarminConnectAuthenticationError

from muscle50.infrastructure.garmin.client import GarminConnectorError, PythonGarminConnector


class FakeRecoveryApi:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[str, ...]]] = []

    def _record(self, name: str, *args: str) -> None:
        self.calls.append((name, args))

    def get_sleep_data(self, cdate: str) -> dict[str, Any]:
        self._record("get_sleep_data", cdate)
        return {"dailySleepDTO": {"calendarDate": cdate}}

    def get_stats(self, cdate: str) -> dict[str, Any]:
        self._record("get_stats", cdate)
        return {"calendarDate": cdate}

    def get_hrv_data(self, cdate: str) -> None:
        self._record("get_hrv_data", cdate)
        return None

    def get_rhr_daily(self, start: str, end: str) -> list[dict[str, Any]]:
        self._record("get_rhr_daily", start, end)
        return []

    def get_body_battery(self, start: str, end: str) -> list[dict[str, Any]]:
        self._record("get_body_battery", start, end)
        return []

    def get_all_day_stress(self, cdate: str) -> dict[str, Any]:
        self._record("get_all_day_stress", cdate)
        return {"calendarDate": cdate}

    def get_training_readiness(self, cdate: str) -> list[dict[str, Any]]:
        self._record("get_training_readiness", cdate)
        return []

    def get_training_status(self, cdate: str) -> dict[str, Any]:
        self._record("get_training_status", cdate)
        return {}

    def get_respiration_data(self, cdate: str) -> dict[str, Any]:
        self._record("get_respiration_data", cdate)
        return {"calendarDate": cdate}


def test_connector_fetches_all_daily_recovery_endpoints() -> None:
    api = FakeRecoveryApi()

    raw = PythonGarminConnector(api).fetch_raw_recovery("2026-09-15")

    assert raw.requested_date == "2026-09-15"
    assert raw.payloads["hrv"] is None
    assert raw.payloads["training_status"] == {}
    assert [name for name, _ in api.calls] == [
        "get_sleep_data",
        "get_stats",
        "get_hrv_data",
        "get_rhr_daily",
        "get_body_battery",
        "get_all_day_stress",
        "get_training_readiness",
        "get_training_status",
        "get_respiration_data",
    ]


def test_endpoint_failure_is_isolated_and_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    api = FakeRecoveryApi()
    monkeypatch.setattr(api, "get_body_battery", lambda start, end: 1 / 0)

    raw = PythonGarminConnector(api).fetch_raw_recovery("2026-09-15")

    assert raw.payloads["sleep"] == {"dailySleepDTO": {"calendarDate": "2026-09-15"}}
    assert "body_battery" not in raw.payloads
    assert "Body Battery 원본을 가져오지 못했습니다." in raw.warnings


def test_malformed_optional_payload_is_isolated(monkeypatch: pytest.MonkeyPatch) -> None:
    api = FakeRecoveryApi()
    monkeypatch.setattr(api, "get_training_status", lambda cdate: "malformed")

    raw = PythonGarminConnector(api).fetch_raw_recovery("2026-09-15")

    assert "training_status" not in raw.payloads
    assert "training status 원본을 가져오지 못했습니다." in raw.warnings


def test_no_data_null_responses_are_preserved(monkeypatch: pytest.MonkeyPatch) -> None:
    api = FakeRecoveryApi()
    endpoint_names = (
        "get_sleep_data",
        "get_stats",
        "get_hrv_data",
        "get_rhr_daily",
        "get_body_battery",
        "get_all_day_stress",
        "get_training_readiness",
        "get_training_status",
        "get_respiration_data",
    )
    for name in endpoint_names:
        monkeypatch.setattr(api, name, lambda *_args: None)

    raw = PythonGarminConnector(api).fetch_raw_recovery("2026-09-15")

    assert set(raw.payloads) == {
        "sleep",
        "daily_stats",
        "hrv",
        "resting_heart_rate",
        "body_battery",
        "stress",
        "training_readiness",
        "training_status",
        "respiration",
    }
    assert all(value is None for value in raw.payloads.values())
    assert raw.warnings == ()


def test_authentication_failure_aborts_recovery_fetch(monkeypatch: pytest.MonkeyPatch) -> None:
    api = FakeRecoveryApi()

    def fail_authentication(cdate: str) -> None:
        raise GarminConnectAuthenticationError("expired")

    monkeypatch.setattr(api, "get_sleep_data", fail_authentication)

    with pytest.raises(GarminConnectorError, match="인증"):
        PythonGarminConnector(api).fetch_raw_recovery("2026-09-15")


def test_all_endpoint_failures_abort_instead_of_saving_empty_success(monkeypatch: pytest.MonkeyPatch) -> None:
    api = FakeRecoveryApi()

    def unavailable(*_args: str) -> None:
        raise ConnectionError("offline")

    for name in (
        "get_sleep_data",
        "get_stats",
        "get_hrv_data",
        "get_rhr_daily",
        "get_body_battery",
        "get_all_day_stress",
        "get_training_readiness",
        "get_training_status",
        "get_respiration_data",
    ):
        monkeypatch.setattr(api, name, unavailable)

    with pytest.raises(GarminConnectorError, match="하나도"):
        PythonGarminConnector(api).fetch_raw_recovery("2026-09-15")
