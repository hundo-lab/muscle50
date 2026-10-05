"""Strictly read-only SQLite access for analytics.

Unlike the write repositories, this reader never migrates, never creates the database or
its directory, never changes the journal mode, and opens the file with ``mode=ro`` plus
``PRAGMA query_only``. All reads for one snapshot run inside a single read transaction so
activities and recovery rows come from one consistent database state.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from muscle50.domain.activity import NormalizedActivity
from muscle50.domain.recovery import DailyRecovery
from muscle50.domain.sync_coverage import (
    PROVIDER_GARMIN,
    CoverageKind,
    CoverageSource,
    CoverageStatus,
    RecordedCoverage,
    SyncCoverageData,
    SyncCoverageEntry,
)
from muscle50.infrastructure.sqlite.database import (
    _activity_from_rows,
    _recovery_from_row,
    _swim_detail_from_connection,
)

# Analytics reads activity-load metrics, swim detail, recovery, and refresh-era columns.
MINIMUM_SCHEMA_VERSION = 7


class AnalyticsDatabaseError(RuntimeError):
    """Raised when the canonical database cannot be read for analytics."""


@dataclass(frozen=True)
class TrainingData:
    activities: tuple[NormalizedActivity, ...]
    undated_source_activity_ids: tuple[str, ...]
    recoveries: tuple[DailyRecovery, ...]
    sync_coverage: tuple[RecordedCoverage, ...] = ()
    """Recorded sync coverage in the range; empty on a database from before migration 10."""


class SqliteAnalyticsReader:
    def __init__(self, database_path: Path):
        self._database_path = database_path

    def load(self, start: date, end: date) -> TrainingData:
        """Load canonical Garmin activities and recovery rows for an inclusive local-date range."""
        with self._read_transaction() as connection:
            activity_rows = connection.execute(
                """
                SELECT * FROM activities
                WHERE provider = 'garmin'
                  AND substr(started_at_local, 1, 10) BETWEEN ? AND ?
                ORDER BY started_at_local, source_activity_id
                """,
                (start.isoformat(), end.isoformat()),
            ).fetchall()
            activities = tuple(_load_activity(connection, row) for row in activity_rows)
            undated = tuple(
                row["source_activity_id"]
                for row in connection.execute(
                    """
                    SELECT source_activity_id FROM activities
                    WHERE provider = 'garmin' AND (started_at_local IS NULL OR started_at_local = '')
                    ORDER BY source_activity_id
                    """
                ).fetchall()
            )
            recoveries = tuple(
                _recovery_from_row(row)
                for row in connection.execute(
                    """
                    SELECT * FROM daily_recovery
                    WHERE provider = 'garmin' AND calendar_date BETWEEN ? AND ?
                    ORDER BY calendar_date
                    """,
                    (start.isoformat(), end.isoformat()),
                ).fetchall()
            )
            coverage = _sync_coverage_rows(connection, start, end) or ()
        return TrainingData(activities, undated, recoveries, coverage)

    def load_sync_coverage(self, start: date, end: date) -> SyncCoverageData:
        """Recorded coverage and stored-activity counts per local date for an inclusive range."""
        with self._read_transaction() as connection:
            records = _sync_coverage_rows(connection, start, end)
            stored = {
                date.fromisoformat(row["day"]): int(row["stored"])
                for row in connection.execute(
                    """
                    SELECT substr(started_at_local, 1, 10) AS day, COUNT(*) AS stored FROM activities
                    WHERE provider = 'garmin'
                      AND substr(started_at_local, 1, 10) BETWEEN ? AND ?
                    GROUP BY day
                    """,
                    (start.isoformat(), end.isoformat()),
                ).fetchall()
            }
        return SyncCoverageData(records or (), stored, table_present=records is not None)

    @contextmanager
    def _read_transaction(self) -> Iterator[sqlite3.Connection]:
        path = self._database_path
        if not path.is_file():
            # mode=ro would refuse to create it anyway; fail before SQLite is involved.
            raise AnalyticsDatabaseError(f"muscle50 database not found: {path}")
        try:
            connection = sqlite3.connect(
                f"{path.resolve().as_uri()}?mode=ro",
                uri=True,
                timeout=5,
                isolation_level=None,
            )
        except sqlite3.Error as exc:
            raise AnalyticsDatabaseError(f"cannot open muscle50 database read-only: {exc}") from exc
        try:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA query_only = ON")
            connection.execute("BEGIN")
            _require_schema(connection)
            yield connection
        except sqlite3.Error as exc:
            raise AnalyticsDatabaseError(f"cannot read muscle50 database: {exc}") from exc
        finally:
            if connection.in_transaction:
                connection.rollback()
            connection.close()


def _require_schema(connection: sqlite3.Connection) -> None:
    has_table = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'schema_migrations'"
    ).fetchone()
    version = connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0] if has_table else None
    if version is None or version < MINIMUM_SCHEMA_VERSION:
        raise AnalyticsDatabaseError(
            f"muscle50 database schema version {version} is older than {MINIMUM_SCHEMA_VERSION}; "
            "run any Garmin sync command once to migrate it"
        )


def _sync_coverage_rows(connection: sqlite3.Connection, start: date, end: date) -> tuple[RecordedCoverage, ...] | None:
    """None on a database from before the coverage migration (a read-only reader never migrates)."""
    has_table = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'sync_coverage'"
    ).fetchone()
    if has_table is None:
        return None
    rows = connection.execute(
        """
        SELECT * FROM sync_coverage
        WHERE provider = ? AND calendar_date BETWEEN ? AND ?
        ORDER BY calendar_date, data_kind
        """,
        (PROVIDER_GARMIN, start.isoformat(), end.isoformat()),
    ).fetchall()
    return tuple(
        RecordedCoverage(
            SyncCoverageEntry(
                CoverageKind(row["data_kind"]),
                date.fromisoformat(row["calendar_date"]),
                CoverageStatus(row["status"]),
                CoverageSource(row["source"]),
                missing_endpoints=_split(row["missing_endpoints"]),
                failed_activity_ids=_split(row["failed_activity_ids"]),
            ),
            row["command"],
            row["synced_at_utc"],
        )
        for row in rows
    )


def _split(value: str | None) -> tuple[str, ...]:
    return tuple(value.split(",")) if value else ()


def _load_activity(connection: sqlite3.Connection, row: sqlite3.Row) -> NormalizedActivity:
    activity_id = int(row["id"])
    metric_rows = connection.execute(
        "SELECT * FROM activity_metrics WHERE activity_id = ? ORDER BY metric_key",
        (activity_id,),
    ).fetchall()
    strength_set_rows = connection.execute(
        "SELECT * FROM strength_sets WHERE activity_id = ? ORDER BY sequence",
        (activity_id,),
    ).fetchall()
    return _activity_from_rows(
        row,
        metric_rows,
        strength_set_rows,
        _swim_detail_from_connection(connection, activity_id),
    )
