from __future__ import annotations

from typing import Any

import garminconnect
import pytest

from muscle50.infrastructure.garmin.client import PythonGarminConnector


class FakeApi:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...]]] = []

    def get_activities(self, start: int, limit: int) -> list[dict[str, Any]]:
        self.calls.append(("get_activities", (start, limit)))
        return [{"activityId": 321, "activityType": {"typeKey": "running"}}]

    def get_activity(self, activity_id: str) -> dict[str, Any]:
        self.calls.append(("get_activity", (activity_id,)))
        return {"activityId": int(activity_id)}

    def get_activity_details(self, activity_id: str) -> dict[str, Any]:
        self.calls.append(("get_activity_details", (activity_id,)))
        return {"activityId": int(activity_id), "details": []}

    def get_activity_splits(self, activity_id: str) -> dict[str, Any]:
        self.calls.append(("get_activity_splits", (activity_id,)))
        return {"lapDTOs": []}


def test_connector_fetches_one_latest_activity_and_raw_endpoints(monkeypatch: Any) -> None:
    api = FakeApi()
    connector = PythonGarminConnector(api)
    monkeypatch.setattr(connector, "_download_original", lambda activity_id, warnings: b"archive")

    summary = connector.latest_summary()
    raw = connector.fetch_raw_activity("321", "running")

    assert summary is not None and summary["activityId"] == 321
    assert api.calls[0] == ("get_activities", (0, 1))
    assert [name for name, _ in api.calls] == [
        "get_activities",
        "get_activity",
        "get_activity_details",
        "get_activity_splits",
    ]
    assert raw.original_archive == b"archive"
    assert raw.exercise_sets is None


def test_connector_treats_optional_endpoint_failure_as_warning(monkeypatch: Any) -> None:
    api = FakeApi()
    connector = PythonGarminConnector(api)
    monkeypatch.setattr(api, "get_activity_splits", lambda activity_id: 1 / 0)
    monkeypatch.setattr(connector, "_download_original", lambda activity_id, warnings: None)

    raw = connector.fetch_raw_activity("321", "running")

    assert raw.splits is None
    assert "splits 원본을 가져오지 못했습니다." in raw.warnings


def test_connector_accepts_wrapped_activity_list(monkeypatch: Any) -> None:
    api = FakeApi()
    monkeypatch.setattr(
        api,
        "get_activities",
        lambda start, limit: {"activityList": [{"activityId": 654}]},
    )

    summary = PythonGarminConnector(api).latest_summary()

    assert summary is not None and summary["activityId"] == 654


def test_cardio_activity_does_not_request_strength_sets(monkeypatch: Any) -> None:
    api = FakeApi()
    connector = PythonGarminConnector(api)
    monkeypatch.setattr(connector, "_download_original", lambda activity_id, warnings: None)

    raw = connector.fetch_raw_activity("321", "cardio_training")

    assert raw.exercise_sets is None
    assert all(name != "get_activity_exercise_sets" for name, _ in api.calls)


def test_authentication_prompts_without_tokens_and_saves_to_private_path(monkeypatch: Any, tmp_path: Any) -> None:
    observed: dict[str, Any] = {}

    class FakeGarmin:
        def __init__(self, **kwargs: Any):
            observed["kwargs"] = kwargs

        def login(self, tokenstore: str) -> None:
            observed["tokenstore"] = tokenstore
            observed["mfa"] = observed["kwargs"]["prompt_mfa"]()

    token_dir = tmp_path / "auth" / "garmin"
    answers = iter(["synthetic@example.invalid", "123456"])
    monkeypatch.setattr(garminconnect, "Garmin", FakeGarmin)

    PythonGarminConnector.authenticate(
        token_dir,
        input_fn=lambda prompt: next(answers),
        password_fn=lambda prompt: "synthetic-password",
    )

    assert observed["kwargs"]["email"] == "synthetic@example.invalid"
    assert observed["kwargs"]["password"] == "synthetic-password"
    assert observed["mfa"] == "123456"
    assert observed["tokenstore"] == str(token_dir)


def test_authentication_reuses_tokens_without_requesting_credentials(monkeypatch: Any, tmp_path: Any) -> None:
    observed: dict[str, Any] = {}

    class FakeGarmin:
        def __init__(self, **kwargs: Any):
            observed["kwargs"] = kwargs

        def login(self, tokenstore: str) -> None:
            observed["tokenstore"] = tokenstore

    token_dir = tmp_path / "auth" / "garmin"
    token_dir.mkdir(parents=True)
    (token_dir / "synthetic-token-marker.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(garminconnect, "Garmin", FakeGarmin)

    PythonGarminConnector.authenticate(
        token_dir,
        input_fn=lambda prompt: pytest.fail("credential input must not be called"),
        password_fn=lambda prompt: pytest.fail("password input must not be called"),
    )

    assert observed["kwargs"] == {}
    assert observed["tokenstore"] == str(token_dir)
