from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from muscle50.infrastructure.sqlite.database import ActivityRepository

EXPECTED_TABLES = {
    "schema_migrations",
    "sync_runs",
    "raw_artifacts",
    "activities",
    "activity_metrics",
    "activity_corrections",
}


def test_migration_recovers_when_only_version_table_and_marker_remain(tmp_path: Path) -> None:
    database_path = tmp_path / "partial.sqlite3"
    with sqlite3.connect(database_path) as connection:
        connection.execute("CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, applied_at_utc TEXT NOT NULL)")
        connection.execute("INSERT INTO schema_migrations(version, applied_at_utc) VALUES (1, 'interrupted')")

    ActivityRepository(database_path).migrate()

    with sqlite3.connect(database_path) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
            )
        }
        versions = connection.execute("SELECT version FROM schema_migrations").fetchall()
    assert tables == EXPECTED_TABLES
    assert versions == [(1,)]


def test_migration_completes_partial_ddl_without_version_marker(tmp_path: Path) -> None:
    database_path = tmp_path / "partial-ddl.sqlite3"
    with sqlite3.connect(database_path) as connection:
        connection.execute("CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, applied_at_utc TEXT NOT NULL)")
        connection.execute(
            """
            CREATE TABLE sync_runs (
                id INTEGER PRIMARY KEY,
                provider TEXT NOT NULL,
                command TEXT NOT NULL,
                status TEXT NOT NULL CHECK (
                    status IN ('running', 'succeeded', 'skipped', 'failed')
                ),
                source_activity_id TEXT,
                error_code TEXT,
                started_at_utc TEXT NOT NULL,
                finished_at_utc TEXT
            )
            """
        )

    ActivityRepository(database_path).migrate()

    with sqlite3.connect(database_path) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
            )
        }
        versions = connection.execute("SELECT version FROM schema_migrations").fetchall()
    assert tables == EXPECTED_TABLES
    assert versions == [(1,)]


def test_first_migration_is_safe_under_concurrent_startup(tmp_path: Path) -> None:
    database_path = tmp_path / "concurrent.sqlite3"

    with ThreadPoolExecutor(max_workers=4) as executor:
        list(executor.map(lambda _: ActivityRepository(database_path).migrate(), range(4)))

    with sqlite3.connect(database_path) as connection:
        versions = connection.execute("SELECT version FROM schema_migrations").fetchall()
    assert versions == [(1,)]
