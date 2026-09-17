"""Sync Garmin recovery and daily-health data for one explicit date."""

from __future__ import annotations

from dataclasses import dataclass, replace

from muscle50.domain.recovery import DailyRecovery
from muscle50.domain.recovery_normalization import (
    normalize_recovery,
    recovery_date_warnings,
    validate_calendar_date,
)
from muscle50.infrastructure.garmin.client import GarminRecoveryConnector
from muscle50.infrastructure.raw_store import RecoveryRawStore
from muscle50.infrastructure.sqlite.database import DailyRecoveryRepository


@dataclass(frozen=True)
class RecoverySyncResult:
    recovery: DailyRecovery
    created: bool
    updated: bool
    warnings: tuple[str, ...] = ()


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
        return RecoverySyncResult(saved, created, updated, raw.warnings)
