"""Boundary around the unofficial python-garminconnect API."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from getpass import getpass
from pathlib import Path
from typing import Any, Protocol


class GarminConnectorError(RuntimeError):
    """A safe-to-display Garmin connector failure."""


class GarminAuthenticationError(GarminConnectorError):
    """Garmin rejected the session; later requests in the same run cannot succeed."""


@dataclass(frozen=True)
class GarminRawActivity:
    summary: Mapping[str, Any]
    activity: Mapping[str, Any]
    details: Mapping[str, Any]
    splits: Mapping[str, Any] | None
    exercise_sets: Mapping[str, Any] | None
    original_archive: bytes | None
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class GarminRawRecovery:
    requested_date: str
    payloads: Mapping[str, Any]
    warnings: tuple[str, ...]


class GarminConnector(Protocol):
    def latest_summary(self) -> Mapping[str, Any] | None: ...

    def list_activities(self, start: int, limit: int) -> Sequence[Mapping[str, Any]]: ...

    def fetch_raw_activity(self, activity_id: str, source_type_key: str) -> GarminRawActivity: ...


class GarminRecoveryConnector(Protocol):
    def fetch_raw_recovery(self, calendar_date: str) -> GarminRawRecovery: ...


class PythonGarminConnector:
    """Thin adapter that prevents third-party response shapes leaking into the app."""

    def __init__(self, api: Any):
        self._api = api

    @classmethod
    def authenticate(
        cls,
        token_dir: Path,
        input_fn: Callable[[str], str] = input,
        password_fn: Callable[[str], str] = getpass,
    ) -> PythonGarminConnector:
        try:
            from garminconnect import (
                Garmin,
                GarminConnectAuthenticationError,
                GarminConnectConnectionError,
                GarminConnectTooManyRequestsError,
            )
        except ImportError as exc:  # pragma: no cover - packaging protects this path
            raise GarminConnectorError("garminconnect 패키지가 설치되지 않았습니다.") from exc

        token_dir.mkdir(parents=True, exist_ok=True)
        token_path = str(token_dir)
        if any(token_dir.iterdir()):
            try:
                api = Garmin()
                api.login(token_path)
                return cls(api)
            except GarminConnectAuthenticationError:
                pass
            except GarminConnectTooManyRequestsError as exc:
                raise GarminConnectorError("Garmin 로그인 요청이 제한되었습니다. 잠시 후 재시도하세요.") from exc
            except GarminConnectConnectionError as exc:
                raise GarminConnectorError("저장된 Garmin 로그인 확인 중 연결에 실패했습니다.") from exc

        email = input_fn("Garmin email: ").strip()
        password = password_fn("Garmin password: ")
        if not email or not password:
            raise GarminConnectorError("Garmin 이메일과 비밀번호가 필요합니다.")
        try:
            api = Garmin(
                email=email,
                password=password,
                prompt_mfa=lambda: input_fn("Garmin MFA code: ").strip(),
            )
            api.login(token_path)
            return cls(api)
        except GarminConnectTooManyRequestsError as exc:
            raise GarminConnectorError("Garmin 로그인 요청이 제한되었습니다. 잠시 후 재시도하세요.") from exc
        except GarminConnectAuthenticationError as exc:
            raise GarminConnectorError("Garmin 인증에 실패했습니다.") from exc
        except GarminConnectConnectionError as exc:
            raise GarminConnectorError("Garmin Connect에 연결할 수 없습니다.") from exc

    def latest_summary(self) -> Mapping[str, Any] | None:
        activities = self.list_activities(0, 1)
        return activities[0] if activities else None

    def list_activities(self, start: int, limit: int) -> tuple[Mapping[str, Any], ...]:
        try:
            activities = self._api.get_activities(start, limit)
        except Exception as exc:
            raise GarminConnectorError("Garmin activity 목록 조회에 실패했습니다.") from exc
        return _activity_list_from(activities)

    def fetch_raw_activity(self, activity_id: str, source_type_key: str) -> GarminRawActivity:
        warnings: list[str] = []
        try:
            activity = self._api.get_activity(activity_id)
            details = self._api.get_activity_details(activity_id)
        except Exception as exc:
            raise GarminConnectorError("Garmin activity 원본 조회에 실패했습니다.") from exc

        splits = self._optional_call(lambda: self._api.get_activity_splits(activity_id), "splits", warnings)
        activity_mapping = _mapping_or_error(activity)
        fetched_source_type = _source_type_key(activity_mapping) or source_type_key
        exercise_sets = None
        if fetched_source_type == "strength_training":
            exercise_sets = self._optional_call(
                lambda: self._api.get_activity_exercise_sets(activity_id),
                "exercise sets",
                warnings,
            )
        original = self._download_original(activity_id, warnings)
        return GarminRawActivity(
            summary={},
            activity=activity_mapping,
            details=_mapping_or_error(details),
            splits=splits,
            exercise_sets=exercise_sets,
            original_archive=original,
            warnings=tuple(warnings),
        )

    def fetch_raw_recovery(self, calendar_date: str) -> GarminRawRecovery:
        warnings: list[str] = []
        payloads: dict[str, Any] = {}
        calls: tuple[tuple[str, str, Callable[[], Any], Callable[[Any], Any]], ...] = (
            ("sleep", "sleep", lambda: self._api.get_sleep_data(calendar_date), _mapping_or_none),
            ("daily_stats", "daily stats", lambda: self._api.get_stats(calendar_date), _mapping_or_none),
            ("hrv", "HRV", lambda: self._api.get_hrv_data(calendar_date), _mapping_or_none),
            (
                "resting_heart_rate",
                "resting heart rate",
                lambda: self._api.get_rhr_daily(calendar_date, calendar_date),
                _mapping_list_or_none,
            ),
            (
                "body_battery",
                "Body Battery",
                lambda: self._api.get_body_battery(calendar_date, calendar_date),
                _mapping_list_or_none,
            ),
            ("stress", "stress", lambda: self._api.get_all_day_stress(calendar_date), _mapping_or_none),
            (
                "training_readiness",
                "training readiness",
                lambda: self._api.get_training_readiness(calendar_date),
                _mapping_or_mapping_list_or_none,
            ),
            (
                "training_status",
                "training status",
                lambda: self._api.get_training_status(calendar_date),
                _mapping_or_none,
            ),
            (
                "respiration",
                "respiration",
                lambda: self._api.get_respiration_data(calendar_date),
                _mapping_or_none,
            ),
        )
        for key, label, call, validator in calls:
            fetched = self._optional_recovery_call(call, label, validator, warnings)
            if fetched is not _MISSING:
                payloads[key] = fetched
        if not payloads:
            raise GarminConnectorError("Garmin recovery 원본을 하나도 가져오지 못했습니다.")
        return GarminRawRecovery(calendar_date, payloads, tuple(warnings))

    def _download_original(self, activity_id: str, warnings: list[str]) -> bytes | None:
        try:
            from garminconnect import Garmin

            result = self._api.download_activity(activity_id, dl_fmt=Garmin.ActivityDownloadFormat.ORIGINAL)
            return result if isinstance(result, bytes) else bytes(result)
        except Exception:
            warnings.append("original archive를 다운로드하지 못했습니다.")
            return None

    @staticmethod
    def _optional_call(call: Callable[[], Any], label: str, warnings: list[str]) -> Mapping[str, Any] | None:
        try:
            return _mapping_or_error(call())
        except Exception:
            warnings.append(f"{label} 원본을 가져오지 못했습니다.")
            return None

    @staticmethod
    def _optional_recovery_call(
        call: Callable[[], Any],
        label: str,
        validator: Callable[[Any], Any],
        warnings: list[str],
    ) -> Any:
        try:
            return validator(call())
        except Exception as exc:
            if _is_authentication_error(exc):
                raise GarminAuthenticationError("Garmin recovery 인증에 실패했습니다.") from exc
            warnings.append(f"{label} 원본을 가져오지 못했습니다.")
            return _MISSING


def _mapping_or_error(value: Any) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise GarminConnectorError("Garmin activity 응답 형식이 올바르지 않습니다.")
    return value


def _activity_list_from(value: Any) -> tuple[Mapping[str, Any], ...]:
    if not value:
        return ()
    if isinstance(value, list):
        if all(isinstance(item, Mapping) for item in value):
            return tuple(value)
        raise GarminConnectorError("Garmin activity 목록 응답 형식이 올바르지 않습니다.")
    if isinstance(value, Mapping):
        activity_list = value.get("activityList")
        if isinstance(activity_list, list) and all(isinstance(item, Mapping) for item in activity_list):
            return tuple(activity_list)
    raise GarminConnectorError("Garmin activity 목록 응답 형식이 올바르지 않습니다.")


def _mapping_or_none(value: Any) -> Mapping[str, Any] | None:
    return None if value is None else _mapping_or_error(value)


def _mapping_list_or_none(value: Any) -> list[Mapping[str, Any]] | None:
    if value is None:
        return None
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise GarminConnectorError("Garmin recovery 응답 형식이 올바르지 않습니다.")
    if not all(isinstance(item, Mapping) for item in value):
        raise GarminConnectorError("Garmin recovery 응답 형식이 올바르지 않습니다.")
    return list(value)


def _mapping_or_mapping_list_or_none(value: Any) -> Mapping[str, Any] | list[Mapping[str, Any]] | None:
    if value is None or isinstance(value, Mapping):
        return value
    return _mapping_list_or_none(value)


def _is_authentication_error(exc: Exception) -> bool:
    try:
        from garminconnect import GarminConnectAuthenticationError
    except ImportError:  # pragma: no cover - packaging protects this path
        return False
    return isinstance(exc, GarminConnectAuthenticationError)


_MISSING = object()


def _source_type_key(activity: Mapping[str, Any]) -> str | None:
    for field in ("activityType", "activityTypeDTO"):
        activity_type = activity.get(field)
        if isinstance(activity_type, Mapping):
            value = activity_type.get("typeKey")
            if isinstance(value, str) and value.strip():
                return value.strip().lower()
    value = activity.get("activityTypeKey")
    return value.strip().lower() if isinstance(value, str) and value.strip() else None
