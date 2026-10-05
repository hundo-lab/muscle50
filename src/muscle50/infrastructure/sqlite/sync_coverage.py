"""SQLite writes for Garmin sync coverage (migration 010, table ``sync_coverage``).

Latest-state, like ``daily_recovery``: a sync replaces a date's row; the recovery RAW backfill
only inserts where no row exists. Each call is one ``BEGIN IMMEDIATE`` transaction, so a call
records all of its dates or none of them.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import UTC, date, datetime
from pathlib import Path

from muscle50.application.sync_coverage import RecoveryBackfillCandidate, RecoveryBackfillCandidates
from muscle50.domain.sync_coverage import PROVIDER_GARMIN, RecordedCoverage, SyncCoverageEntry
from muscle50.infrastructure.sqlite.database import _enable_wal

_UPSERT_SQL = """
INSERT INTO sync_coverage (
    provider, data_kind, calendar_date, status, source, command,
    missing_endpoints, failed_activity_ids, synced_at_utc
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT (provider, data_kind, calendar_date) DO UPDATE SET
    status = excluded.status,
    source = excluded.source,
    command = excluded.command,
    missing_endpoints = excluded.missing_endpoints,
    failed_activity_ids = excluded.failed_activity_ids,
    synced_at_utc = excluded.synced_at_utc
"""

_INSERT_IF_ABSENT_SQL = """
INSERT INTO sync_coverage (
    provider, data_kind, calendar_date, status, source, command,
    missing_endpoints, failed_activity_ids, synced_at_utc
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT (provider, data_kind, calendar_date) DO NOTHING
"""


class SqliteSyncCoverageRepository:
    def __init__(self, database_path: Path):
        self._database_path = database_path

    def record(self, entries: Sequence[SyncCoverageEntry], *, command: str) -> None:
        now = _now()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            for entry in entries:
                connection.execute(_UPSERT_SQL, _parameters(entry, command, now))

    def recovery_backfill_candidates(self) -> RecoveryBackfillCandidates:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT recovery.calendar_date, capture.captured_at_utc,
                       EXISTS (
                           SELECT 1 FROM sync_coverage AS coverage
                           WHERE coverage.provider = recovery.provider
                             AND coverage.data_kind = 'recovery'
                             AND coverage.calendar_date = recovery.calendar_date
                       ) AS recorded
                FROM daily_recovery AS recovery
                JOIN recovery_raw_captures AS capture ON capture.id = recovery.primary_raw_capture_id
                WHERE recovery.provider = ?
                ORDER BY recovery.calendar_date
                """,
                (PROVIDER_GARMIN,),
            ).fetchall()
            kinds: dict[str, set[str]] = {}
            for row in connection.execute(
                """
                SELECT recovery.calendar_date, artifact.artifact_kind
                FROM daily_recovery AS recovery
                JOIN recovery_raw_artifacts AS artifact ON artifact.capture_id = recovery.primary_raw_capture_id
                WHERE recovery.provider = ?
                """,
                (PROVIDER_GARMIN,),
            ):
                kinds.setdefault(row["calendar_date"], set()).add(row["artifact_kind"])
        return RecoveryBackfillCandidates(
            recovery_dates=len(rows),
            already_recorded=sum(1 for row in rows if row["recorded"]),
            candidates=tuple(
                RecoveryBackfillCandidate(
                    date.fromisoformat(row["calendar_date"]),
                    frozenset(kinds.get(row["calendar_date"], ())),
                    row["captured_at_utc"],
                )
                for row in rows
                if not row["recorded"]
            ),
        )

    def insert_backfill(self, records: Sequence[RecordedCoverage]) -> tuple[date, ...]:
        inserted: list[date] = []
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            for record in records:
                cursor = connection.execute(
                    _INSERT_IF_ABSENT_SQL, _parameters(record.entry, record.command, record.synced_at_utc)
                )
                if cursor.rowcount == 1:
                    inserted.append(record.entry.calendar_date)
        return tuple(inserted)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self._database_path, timeout=5, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        _enable_wal(connection)
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()


def _parameters(entry: SyncCoverageEntry, command: str, synced_at_utc: str) -> tuple[str | None, ...]:
    return (
        PROVIDER_GARMIN,
        entry.kind.value,
        entry.calendar_date.isoformat(),
        entry.status.value,
        entry.source.value,
        command,
        ",".join(entry.missing_endpoints) or None,
        ",".join(entry.failed_activity_ids) or None,
        synced_at_utc,
    )


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds")
