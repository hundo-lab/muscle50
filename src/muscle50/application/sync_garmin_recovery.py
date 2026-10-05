"""Sync Garmin recovery and daily-health data for one explicit date or an inclusive range."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, replace
from datetime import date, timedelta
from typing import Literal

from muscle50.domain.recovery import DailyRecovery
from muscle50.domain.recovery_normalization import (
    RecoveryNormalizationError,
    normalize_recovery,
    recovery_date_warnings,
    validate_calendar_date,
)
from muscle50.infrastructure.garmin.client import (
    GarminAuthenticationError,
    GarminConnectorError,
    GarminRecoveryConnector,
)
from muscle50.infrastructure.raw_store import RawStoreError, RecoveryRawStore
from muscle50.infrastructure.sqlite.database import DailyRecoveryRepository

# Hard ceiling for one range run; each date costs one request per recovery endpoint.
MAX_RECOVERY_RANGE_DAYS = 31
RECOVERY_ENDPOINTS_PER_DATE = 9
# The recovery endpoint kinds, in PythonGarminConnector.fetch_raw_recovery order. A kind missing
# from a fetched recovery is an endpoint call that failed (a "no data" answer is stored as null).
RECOVERY_ENDPOINT_KINDS = (
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
# A run of consecutive whole-date failures usually means throttling or an outage, so the
# range stops instead of spending the remaining request budget on the same failure.
MAX_CONSECUTIVE_DATE_FAILURES = 3

# Per-date failures that leave the other dates independent. Authentication is handled
# separately because every later date in the run would fail the same way.
_KNOWN_DATE_ERRORS = (GarminConnectorError, RawStoreError, RecoveryNormalizationError, sqlite3.Error)


class InvalidRecoveryRangeError(ValueError):
    """Raised when a requested recovery date range is invalid."""


@dataclass(frozen=True)
class RecoverySyncResult:
    recovery: DailyRecovery
    created: bool
    updated: bool
    warnings: tuple[str, ...] = ()
    missing_endpoints: tuple[str, ...] = ()
    """Endpoint kinds whose call failed for this date, in RECOVERY_ENDPOINT_KINDS order."""


@dataclass(frozen=True)
class RecoveryRangeOutcome:
    calendar_date: str
    status: Literal["created", "updated", "unchanged", "failed", "not_attempted"]
    result: RecoverySyncResult | None = None
    error: str | None = None
    authentication_failed: bool = False
    """The date failed because Garmin rejected the session, so it was never really attempted."""


@dataclass(frozen=True)
class RecoveryRangeSyncResult:
    from_date: date
    to_date: date
    outcomes: tuple[RecoveryRangeOutcome, ...]
    aborted_reason: str | None = None

    def count(self, status: str) -> int:
        return sum(1 for outcome in self.outcomes if outcome.status == status)

    @property
    def complete(self) -> bool:
        return all(outcome.status in {"created", "updated", "unchanged"} for outcome in self.outcomes)


def recovery_range_dates(from_date: date, to_date: date) -> tuple[str, ...]:
    """Inclusive calendar dates in ascending order."""
    if from_date > to_date:
        raise InvalidRecoveryRangeError("--from은 --to보다 이후일 수 없습니다.")
    day_count = (to_date - from_date).days + 1
    if day_count > MAX_RECOVERY_RANGE_DAYS:
        raise InvalidRecoveryRangeError(
            f"recovery 범위는 최대 {MAX_RECOVERY_RANGE_DAYS}일입니다 (요청: {day_count}일)."
        )
    return tuple((from_date + timedelta(days=offset)).isoformat() for offset in range(day_count))


class SyncGarminRecovery:
    def __init__(
        self,
        connector: GarminRecoveryConnector,
        repository: DailyRecoveryRepository,
        raw_store: RecoveryRawStore,
    ):
        self._connector = connector
        self._repository = repository
        self._raw_store = raw_store

    def execute(self, calendar_date: str) -> RecoverySyncResult:
        requested_date = validate_calendar_date(calendar_date)
        raw = self._connector.fetch_raw_recovery(requested_date)
        date_warnings = recovery_date_warnings(requested_date, raw.payloads)
        raw = replace(raw, warnings=raw.warnings + date_warnings)
        capture = self._raw_store.preserve(raw)
        recovery = normalize_recovery(requested_date, raw.payloads)
        saved, created, updated = self._repository.save(recovery, capture)
        missing = tuple(kind for kind in RECOVERY_ENDPOINT_KINDS if kind not in raw.payloads)
        return RecoverySyncResult(saved, created, updated, raw.warnings, missing)

    def execute_range(self, from_date: date, to_date: date) -> RecoveryRangeSyncResult:
        """Sync each date sequentially; one date's failure does not roll back another date."""
        dates = recovery_range_dates(from_date, to_date)
        outcomes: list[RecoveryRangeOutcome] = []
        aborted_reason: str | None = None
        consecutive_failures = 0
        for calendar_date in dates:
            if aborted_reason is not None:
                outcomes.append(RecoveryRangeOutcome(calendar_date, "not_attempted"))
                continue
            try:
                result = self.execute(calendar_date)
            except GarminAuthenticationError as exc:
                outcomes.append(
                    RecoveryRangeOutcome(calendar_date, "failed", error=str(exc), authentication_failed=True)
                )
                aborted_reason = str(exc)
                continue
            except _KNOWN_DATE_ERRORS as exc:
                outcomes.append(RecoveryRangeOutcome(calendar_date, "failed", error=str(exc)))
                consecutive_failures += 1
                if consecutive_failures >= MAX_CONSECUTIVE_DATE_FAILURES:
                    aborted_reason = f"{consecutive_failures}개 날짜가 연속으로 실패해 중단했습니다."
                continue
            consecutive_failures = 0
            status: Literal["created", "updated", "unchanged"] = (
                "created" if result.created else "updated" if result.updated else "unchanged"
            )
            outcomes.append(RecoveryRangeOutcome(calendar_date, status, result=result))
        return RecoveryRangeSyncResult(from_date, to_date, tuple(outcomes), aborted_reason)
