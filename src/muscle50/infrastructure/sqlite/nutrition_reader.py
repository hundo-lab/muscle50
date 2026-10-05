"""Strictly read-only access to logged meals, for read-only commands such as ``recommend``.

``SqliteMealRepository`` creates the database directory, the database and the WAL journal on
first use; this reader does none of that. Like the analytics reader it opens the file with
``mode=ro`` plus ``PRAGMA query_only``, never migrates, and reads one day inside a single read
transaction. Meals are decoded by the repository's own row loader, so both see the same meals.
Meals are listed by the same query too: voided meals are left out and edited meals are placed by
their effective date and time (migration 9; a database without it is read exactly as before).
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from muscle50.domain.nutrition import Meal
from muscle50.infrastructure.sqlite.nutrition_repository import (
    _load_meal,
    _meal_ids_eaten_between,
    _require_aware,
    _utc_sort_key,
)

# Nutrition meal, item and fact tables arrive with migration 3.
MINIMUM_SCHEMA_VERSION = 3


class NutritionReadError(RuntimeError):
    """Raised when logged meals cannot be read without writing to the database."""


class SqliteNutritionReader:
    def __init__(self, database_path: Path):
        self._database_path = database_path

    def list_eaten_between(self, start_inclusive: datetime, end_exclusive: datetime) -> tuple[Meal, ...]:
        _require_aware(start_inclusive, "start_inclusive")
        _require_aware(end_exclusive, "end_exclusive")
        with self._read_transaction() as connection:
            meal_ids = _meal_ids_eaten_between(connection, _utc_sort_key(start_inclusive), _utc_sort_key(end_exclusive))
            meals: list[Meal] = []
            for meal_id in meal_ids:
                try:
                    meal = _load_meal(connection, meal_id)
                except ValueError as exc:
                    raise NutritionReadError(f"stored meal {meal_id!r} cannot be read: {exc}") from exc
                if meal is None:
                    raise NutritionReadError(f"meal {meal_id!r} disappeared during listing")
                meals.append(meal)
        return tuple(meals)

    @contextmanager
    def _read_transaction(self) -> Iterator[sqlite3.Connection]:
        path = self._database_path
        if not path.is_file():
            raise NutritionReadError(f"muscle50 database not found: {path}")
        try:
            connection = sqlite3.connect(
                f"{path.resolve().as_uri()}?mode=ro", uri=True, timeout=5, isolation_level=None
            )
        except sqlite3.Error as exc:
            raise NutritionReadError(f"cannot open muscle50 database read-only: {exc}") from exc
        try:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA query_only = ON")
            connection.execute("BEGIN")
            _require_schema(connection)
            yield connection
        except sqlite3.Error as exc:
            raise NutritionReadError(f"cannot read nutrition data: {exc}") from exc
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
        raise NutritionReadError(
            f"muscle50 database schema version {version} has no nutrition tables (needs {MINIMUM_SCHEMA_VERSION})"
        )
