"""Re-normalize stored Garmin recovery rows from their accepted RAW capture only.

This use case has no Garmin connector dependency. For each stored date it reads the
artifacts of the capture the row already points to (verifying recorded size and sha256),
normalizes them with the current normalizer, and saves against that same capture. It never
creates a RAW capture, so capture history and RAW files stay byte-identical.
"""

from __future__ import annotations

import sqlite3
from collections import Counter
from dataclasses import dataclass, fields

from muscle50.domain.recovery import DailyRecovery
from muscle50.domain.recovery_normalization import RecoveryNormalizationError, normalize_recovery
from muscle50.infrastructure.raw_store import RawStoreError, RecoveryRawStore
from muscle50.infrastructure.sqlite.database import DailyRecoveryRepository

_KNOWN_DATE_ERRORS = (RawStoreError, RecoveryNormalizationError, sqlite3.Error)


@dataclass(frozen=True)
class RecoveryRenormalizeFailure:
    calendar_date: str
    error: str


@dataclass(frozen=True)
class RecoveryRenormalizeResult:
    dry_run: bool
    dates_examined: int
    dates_updated: tuple[str, ...]
    dates_unchanged: tuple[str, ...]
    failures: tuple[RecoveryRenormalizeFailure, ...]
    # How many dates changed each DailyRecovery field (normalizer_version included).
    field_changes: dict[str, int]


class RenormalizeGarminRecovery:
    def __init__(self, repository: DailyRecoveryRepository, raw_store: RecoveryRawStore):
        self._repository = repository
        self._raw_store = raw_store

    def execute(self, *, dry_run: bool = False) -> RecoveryRenormalizeResult:
        dates = self._repository.list_calendar_dates()
        updated: list[str] = []
        unchanged: list[str] = []
        failures: list[RecoveryRenormalizeFailure] = []
        field_changes: Counter[str] = Counter()
        for calendar_date in dates:
            try:
                stored = self._repository.find(calendar_date)
                capture = self._repository.find_source_capture(calendar_date)
                if stored is None or capture is None:
                    raise RawStoreError("accepted recovery RAW capture가 없습니다.")
                recovery = normalize_recovery(calendar_date, self._raw_store.load_capture_payloads(capture))
                changed_fields = _changed_fields(stored, recovery)
                if changed_fields and not dry_run:
                    _saved, _created, was_updated = self._repository.save(recovery, capture)
                    if not was_updated:
                        raise RuntimeError(f"recovery row was not updated: {calendar_date}")
            except _KNOWN_DATE_ERRORS as exc:
                failures.append(RecoveryRenormalizeFailure(calendar_date, str(exc)))
                continue
            field_changes.update(changed_fields)
            (updated if changed_fields else unchanged).append(calendar_date)
        return RecoveryRenormalizeResult(
            dry_run=dry_run,
            dates_examined=len(dates),
            dates_updated=tuple(updated),
            dates_unchanged=tuple(unchanged),
            failures=tuple(failures),
            field_changes=dict(sorted(field_changes.items())),
        )


def _changed_fields(stored: DailyRecovery, recovery: DailyRecovery) -> tuple[str, ...]:
    return tuple(
        field.name for field in fields(DailyRecovery) if getattr(stored, field.name) != getattr(recovery, field.name)
    )
