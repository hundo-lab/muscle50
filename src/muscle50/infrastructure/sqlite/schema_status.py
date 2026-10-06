"""Which migrations in this code a database has not applied yet, read without changing anything.

`migrate()` applies every migration file it finds at call time, and a long-running process (the
Telegram bot) keeps running while new code is integrated. The bot asks this module before each
command whose CLI handler migrates, and refuses instead of applying a migration nobody backed up.
The database is opened with ``mode=ro`` plus ``PRAGMA query_only``, like the read-only readers.
"""

from __future__ import annotations

import re
import sqlite3
from importlib.resources import files
from pathlib import Path

_MIGRATION_FILE = re.compile(r"([0-9]{3})_.*\.sql")


def code_migration_versions() -> tuple[int, ...]:
    """The migration numbers in this code, listed now (the same files `migrate()` would run)."""
    migrations = files("muscle50.infrastructure.sqlite.migrations")
    versions = (_MIGRATION_FILE.fullmatch(item.name) for item in migrations.iterdir())
    return tuple(sorted(int(match.group(1)) for match in versions if match is not None))


def pending_migrations(database_path: Path) -> tuple[int, ...] | None:
    """Code migrations the database lacks: ``()`` when there is no database file yet (the CLI creates
    it), ``None`` when the database exists but its applied migrations cannot be read."""
    if not database_path.exists():
        return ()
    if not database_path.is_file():
        return None
    try:
        connection = sqlite3.connect(
            f"{database_path.resolve().as_uri()}?mode=ro", uri=True, timeout=5, isolation_level=None
        )
        try:
            connection.execute("PRAGMA query_only = ON")
            has_table = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'schema_migrations'"
            ).fetchone()
            if has_table is None:
                return None
            applied = {row[0] for row in connection.execute("SELECT version FROM schema_migrations")}
        finally:
            connection.close()
    except sqlite3.Error:
        return None
    return tuple(version for version in code_migration_versions() if version not in applied)
