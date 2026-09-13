"""SQLite migration and activity repository."""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from importlib.resources import files
from pathlib import Path

from muscle50.domain.activity import ActivityMetric, ActivityType, NormalizedActivity
from muscle50.infrastructure.raw_store import RawArtifact


class ActivityRepository:
    def __init__(self, database_path: Path):
        self._database_path = database_path

    def migrate(self) -> None:
        with self._connect() as connection:
            # executescript commits any pending transaction before it runs. The migration
            # therefore owns its BEGIN/COMMIT and uses idempotent DDL so an interrupted
            # legacy/partial schema can be completed safely on the next startup.
            migration = (
                files("muscle50.infrastructure.sqlite.migrations")
                .joinpath("001_initial.sql")
                .read_text(encoding="utf-8")
            )
            connection.executescript(migration)

    def find(self, source_activity_id: str) -> NormalizedActivity | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM activities WHERE provider = 'garmin' AND source_activity_id = ?",
                (source_activity_id,),
            ).fetchone()
            if row is None:
                return None
            metric_rows = connection.execute(
                "SELECT * FROM activity_metrics WHERE activity_id = ? ORDER BY metric_key",
                (row["id"],),
            ).fetchall()
        return _activity_from_rows(row, metric_rows)

    def save(self, activity: NormalizedActivity, artifacts: tuple[RawArtifact, ...]) -> tuple[NormalizedActivity, bool]:
        if not artifacts:
            raise ValueError("at least one raw artifact is required")
        now = _now()
        try:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                artifact_ids: dict[str, int] = {}
                for artifact in artifacts:
                    connection.execute(
                        """
                        INSERT OR IGNORE INTO raw_artifacts (
                            provider, source_activity_id, artifact_kind, relative_path,
                            content_type, sha256, byte_size, fetched_at_utc
                        ) VALUES ('garmin', ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            activity.source_activity_id,
                            artifact.kind,
                            artifact.relative_path,
                            artifact.content_type,
                            artifact.sha256,
                            artifact.byte_size,
                            now,
                        ),
                    )
                    stored = connection.execute(
                        "SELECT * FROM raw_artifacts WHERE relative_path = ?",
                        (artifact.relative_path,),
                    ).fetchone()
                    if stored is None or any(
                        (
                            stored["provider"] != "garmin",
                            stored["source_activity_id"] != activity.source_activity_id,
                            stored["artifact_kind"] != artifact.kind,
                            stored["sha256"] != artifact.sha256,
                            stored["byte_size"] != artifact.byte_size,
                        )
                    ):
                        raise RuntimeError("stored RAW artifact metadata does not match the file")
                    artifact_ids[artifact.kind] = int(stored["id"])
                primary_id = artifact_ids.get("activity", next(iter(artifact_ids.values())))
                cursor = connection.execute(
                    """
                    INSERT INTO activities (
                        provider, source_activity_id, source_type_key, canonical_type, name,
                        started_at_utc, started_at_local, timezone_name, elapsed_seconds,
                        moving_seconds, distance_meters, calories_kcal, average_hr_bpm,
                        max_hr_bpm, elevation_gain_meters, primary_raw_artifact_id,
                        normalizer_version, imported_at_utc
                    ) VALUES ('garmin', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        activity.source_activity_id,
                        activity.source_type_key,
                        activity.canonical_type.value,
                        activity.name,
                        activity.started_at_utc,
                        activity.started_at_local,
                        activity.timezone_name,
                        activity.elapsed_seconds,
                        activity.moving_seconds,
                        activity.distance_meters,
                        activity.calories_kcal,
                        activity.average_hr_bpm,
                        activity.max_hr_bpm,
                        activity.elevation_gain_meters,
                        primary_id,
                        activity.normalizer_version,
                        now,
                    ),
                )
                if cursor.lastrowid is None:
                    raise RuntimeError("SQLite did not return an activity ID")
                activity_pk = cursor.lastrowid
                for metric in activity.metrics:
                    numeric, text = _metric_values(metric)
                    connection.execute(
                        """
                        INSERT INTO activity_metrics (
                            activity_id, metric_key, numeric_value, text_value, unit, source_path
                        ) VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (activity_pk, metric.key, numeric, text, metric.unit, metric.source_path),
                    )
        except sqlite3.IntegrityError:
            existing = self.find(activity.source_activity_id)
            if existing is not None:
                return existing, False
            raise
        return activity, True

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        self._database_path.parent.mkdir(parents=True, exist_ok=True)
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


def _metric_values(metric: ActivityMetric) -> tuple[float | None, str | None]:
    if isinstance(metric.value, str):
        return None, metric.value
    return float(metric.value), None


def _activity_from_rows(row: sqlite3.Row, metric_rows: list[sqlite3.Row]) -> NormalizedActivity:
    metrics = tuple(
        ActivityMetric(
            key=item["metric_key"],
            value=item["numeric_value"] if item["numeric_value"] is not None else item["text_value"],
            unit=item["unit"],
            source_path=item["source_path"],
        )
        for item in metric_rows
    )
    return NormalizedActivity(
        source_activity_id=row["source_activity_id"],
        source_type_key=row["source_type_key"],
        canonical_type=ActivityType(row["canonical_type"]),
        name=row["name"],
        started_at_utc=row["started_at_utc"],
        started_at_local=row["started_at_local"],
        timezone_name=row["timezone_name"],
        elapsed_seconds=row["elapsed_seconds"],
        moving_seconds=row["moving_seconds"],
        distance_meters=row["distance_meters"],
        calories_kcal=row["calories_kcal"],
        average_hr_bpm=row["average_hr_bpm"],
        max_hr_bpm=row["max_hr_bpm"],
        elevation_gain_meters=row["elevation_gain_meters"],
        metrics=metrics,
        normalizer_version=row["normalizer_version"],
    )


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _enable_wal(connection: sqlite3.Connection) -> None:
    # Concurrent first starts can race while SQLite creates the database/WAL files.
    # Some Windows SQLite builds return SQLITE_BUSY here without honoring busy_timeout.
    for attempt in range(5):
        try:
            connection.execute("PRAGMA journal_mode = WAL")
            return
        except sqlite3.OperationalError as exc:
            if "locked" not in str(exc).lower() or attempt == 4:
                raise
            time.sleep(0.05 * (attempt + 1))
