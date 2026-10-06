"""Strictly read-only SQLite access to stored InBody measurements (`inbody trend`).

Like the analytics reader, this never migrates, never creates the database or its directory,
never changes the journal mode, and opens the file with ``mode=ro`` plus ``PRAGMA query_only``
inside one read transaction. The write repository (``body_composition.py``) is not used because
its connection creates the directory and switches the database to WAL.

The InBody table is detected by name rather than by migration version: an early 006/007 number
collision once ran the InBody DDL without a version marker.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from muscle50.domain.body_composition_trend import StoredBodyComposition

MEASUREMENT_TABLE = "body_composition_measurements"


class BodyCompositionReadError(RuntimeError):
    """Raised when stored InBody measurements cannot be read."""


class SqliteBodyCompositionReader:
    def __init__(self, database_path: Path):
        self._database_path = database_path

    def load_measurements(self) -> tuple[StoredBodyComposition, ...]:
        with self._read_transaction() as connection:
            has_table = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (MEASUREMENT_TABLE,)
            ).fetchone()
            if has_table is None:
                raise BodyCompositionReadError(
                    f"muscle50 database has no InBody measurement table ({MEASUREMENT_TABLE}, added by migration 7); "
                    'run any muscle50 command that writes, for example "muscle50 nutrition food list", '
                    "once to migrate it"
                )
            rows = connection.execute(
                """
                SELECT id, measured_at, weight_kg, skeletal_muscle_mass_kg, body_fat_mass_kg, body_fat_percent
                FROM body_composition_measurements
                WHERE provider = 'inbody'
                ORDER BY id
                """
            ).fetchall()
        return tuple(
            StoredBodyComposition(
                row_id=int(row["id"]),
                measured_at=str(row["measured_at"]),
                weight_kg=_optional_float(row["weight_kg"]),
                skeletal_muscle_mass_kg=_optional_float(row["skeletal_muscle_mass_kg"]),
                body_fat_mass_kg=_optional_float(row["body_fat_mass_kg"]),
                body_fat_percent=_optional_float(row["body_fat_percent"]),
            )
            for row in rows
        )

    @contextmanager
    def _read_transaction(self) -> Iterator[sqlite3.Connection]:
        path = self._database_path
        if not path.is_file():
            # mode=ro would refuse to create it anyway; fail before SQLite is involved.
            raise BodyCompositionReadError(f"muscle50 database not found: {path}")
        try:
            connection = sqlite3.connect(
                f"{path.resolve().as_uri()}?mode=ro",
                uri=True,
                timeout=5,
                isolation_level=None,
            )
        except sqlite3.Error as exc:
            raise BodyCompositionReadError(f"cannot open muscle50 database read-only: {exc}") from exc
        try:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA query_only = ON")
            connection.execute("BEGIN")
            yield connection
        except sqlite3.Error as exc:
            raise BodyCompositionReadError(f"cannot read InBody measurements: {exc}") from exc
        finally:
            if connection.in_transaction:
                connection.rollback()
            connection.close()


def _optional_float(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, int | float):
        return float(value)
    raise BodyCompositionReadError(f"cannot read InBody measurements: non-numeric stored value {value!r}")
