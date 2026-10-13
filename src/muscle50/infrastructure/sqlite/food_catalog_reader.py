"""Strictly read-only food catalog lookups (`get`, `search`) for the Telegram LLM proposals.

Like `SqliteNutritionReader`: ``mode=ro`` plus ``PRAGMA query_only``, no migration, no directory, database
or WAL file created. Profiles are decoded by the repository's own loader and found by the same exact
name/alias query, so a proposal resolves a food exactly as `nutrition log` would. A missing database or
one from before migration 3 has no foods.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from muscle50.domain.nutrition import FoodNutritionProfile
from muscle50.infrastructure.sqlite.nutrition_repository import _load_profile


class FoodCatalogReadError(RuntimeError):
    """The catalog exists but cannot be read without writing."""


class SqliteFoodCatalogReader:
    def __init__(self, database_path: Path) -> None:
        self._database_path = database_path

    def get(self, profile_id: str) -> FoodNutritionProfile | None:
        with self._read() as connection:
            if connection is None:
                return None
            return _load_profile(connection, profile_id)

    def list_all(self) -> tuple[FoodNutritionProfile, ...]:
        """Every food (reserved general meal included), ordered by ID; none when there is no database or table."""
        with self._read() as connection:
            if connection is None:
                return ()
            rows = connection.execute("SELECT profile_id FROM nutrition_food_profiles ORDER BY profile_id").fetchall()
            profiles = []
            for row in rows:
                profile = _load_profile(connection, row["profile_id"])
                if profile is not None:
                    profiles.append(profile)
            return tuple(profiles)

    def search(self, name_or_alias: str) -> tuple[FoodNutritionProfile, ...]:
        with self._read() as connection:
            if connection is None:
                return ()
            rows = connection.execute(
                """
                SELECT DISTINCT p.profile_id FROM nutrition_food_profiles p
                LEFT JOIN nutrition_food_profile_aliases a ON a.profile_id = p.profile_id
                WHERE LOWER(p.name) = LOWER(?) OR LOWER(a.alias) = LOWER(?)
                ORDER BY p.profile_id
                """,
                (name_or_alias, name_or_alias),
            ).fetchall()
            profiles = []
            for row in rows:
                profile = _load_profile(connection, row["profile_id"])
                if profile is not None:
                    profiles.append(profile)
            return tuple(profiles)

    @contextmanager
    def _read(self) -> Iterator[sqlite3.Connection | None]:
        path = self._database_path
        if not path.is_file():
            yield None
            return
        try:
            connection = sqlite3.connect(
                f"{path.resolve().as_uri()}?mode=ro", uri=True, timeout=5, isolation_level=None
            )
        except sqlite3.Error as exc:
            raise FoodCatalogReadError(f"cannot open the food catalog read-only ({type(exc).__name__})") from exc
        try:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA query_only = ON")
            connection.execute("BEGIN")
            has_table = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'nutrition_food_profiles'"
            ).fetchone()
            yield connection if has_table is not None else None
        except sqlite3.Error as exc:
            raise FoodCatalogReadError(f"cannot read the food catalog ({type(exc).__name__})") from exc
        finally:
            if connection.in_transaction:
                connection.rollback()
            connection.close()
