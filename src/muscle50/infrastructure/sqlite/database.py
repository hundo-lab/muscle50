"""SQLite migration and activity repository."""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib.resources import files
from pathlib import Path
from typing import Any

from muscle50.domain.activity import (
    NORMALIZER_VERSION,
    ActivityMetric,
    ActivityType,
    NormalizedActivity,
    StrengthSet,
)
from muscle50.domain.normalization import strength_set_metrics
from muscle50.domain.recovery import DailyRecovery
from muscle50.domain.swimming import GarminSource, NormalizedSwimActivity, SwimDistance, SwimLap, SwimLength
from muscle50.infrastructure.raw_store import ActivityCapture, RawArtifact, RecoveryCapture


@dataclass(frozen=True)
class MetricUpsertCounts:
    inserted: int
    updated: int
    unchanged: int


class ActivityRepository:
    def __init__(self, database_path: Path):
        self._database_path = database_path

    def migrate(self) -> None:
        with self._connect() as connection:
            # executescript commits any pending transaction before it runs. The migration
            # therefore owns its BEGIN/COMMIT and uses idempotent DDL so an interrupted
            # legacy/partial schema can be completed safely on the next startup.
            migrations = files("muscle50.infrastructure.sqlite.migrations")
            for migration in sorted(
                (item for item in migrations.iterdir() if item.name.endswith(".sql")),
                key=lambda item: item.name,
            ):
                connection.executescript(migration.read_text(encoding="utf-8"))

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
            strength_set_rows = connection.execute(
                "SELECT * FROM strength_sets WHERE activity_id = ? ORDER BY sequence",
                (row["id"],),
            ).fetchall()
            swim_detail = _swim_detail_from_connection(connection, int(row["id"]))
        return _activity_from_rows(row, metric_rows, strength_set_rows, swim_detail)

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
                _insert_strength_sets(connection, activity_pk, activity.strength_sets)
                if activity.swim_detail is not None:
                    _insert_swim_detail(connection, activity_pk, activity.swim_detail)
        except sqlite3.IntegrityError:
            existing = self.find(activity.source_activity_id)
            if existing is not None:
                return existing, False
            raise
        return activity, True

    def record_refresh_capture(self, capture: ActivityCapture) -> None:
        """Register fetched RAW in its own transaction before normalization/persistence."""
        if not capture.artifacts:
            raise ValueError("at least one activity RAW artifact is required")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            _register_activity_capture(connection, capture, _now())

    def refresh(self, activity: NormalizedActivity, capture: ActivityCapture) -> NormalizedActivity:
        """Atomically replace an existing activity's canonical normalized representation."""
        if activity.source_activity_id != capture.source_activity_id:
            raise ValueError("activity ID does not match RAW capture activity ID")
        now = _now()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            capture_row = connection.execute(
                "SELECT id FROM activity_raw_captures WHERE id = ? AND source_activity_id = ?",
                (capture.capture_id, capture.source_activity_id),
            ).fetchone()
            if capture_row is None:
                raise ValueError("activity RAW capture is not registered")
            row = connection.execute(
                "SELECT id FROM activities WHERE provider = 'garmin' AND source_activity_id = ?",
                (activity.source_activity_id,),
            ).fetchone()
            if row is None:
                raise ValueError(f"activity is not stored: {activity.source_activity_id}")
            activity_id = int(row["id"])
            connection.execute(
                """
                UPDATE activities SET
                    source_type_key = ?, canonical_type = ?, name = ?, started_at_utc = ?,
                    started_at_local = ?, timezone_name = ?, elapsed_seconds = ?,
                    moving_seconds = ?, distance_meters = ?, calories_kcal = ?,
                    average_hr_bpm = ?, max_hr_bpm = ?, elevation_gain_meters = ?,
                    normalizer_version = ?
                WHERE id = ?
                """,
                (
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
                    activity.normalizer_version,
                    activity_id,
                ),
            )
            connection.execute("DELETE FROM activity_metrics WHERE activity_id = ?", (activity_id,))
            connection.execute("DELETE FROM strength_sets WHERE activity_id = ?", (activity_id,))
            connection.execute("DELETE FROM swim_activities WHERE activity_id = ?", (activity_id,))
            for metric in activity.metrics:
                numeric, text = _metric_values(metric)
                connection.execute(
                    """
                    INSERT INTO activity_metrics (
                        activity_id, metric_key, numeric_value, text_value, unit, source_path
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (activity_id, metric.key, numeric, text, metric.unit, metric.source_path),
                )
            _insert_strength_sets(connection, activity_id, activity.strength_sets)
            if activity.swim_detail is not None:
                _insert_swim_detail(connection, activity_id, activity.swim_detail)
            connection.execute(
                """
                INSERT INTO activity_refresh_state (activity_id, current_capture_id, refreshed_at_utc)
                VALUES (?, ?, ?)
                ON CONFLICT(activity_id) DO UPDATE SET
                    current_capture_id = excluded.current_capture_id,
                    refreshed_at_utc = excluded.refreshed_at_utc
                """,
                (activity_id, capture.capture_id, now),
            )
        return activity

    def find_current_refresh_capture(self, source_activity_id: str) -> ActivityCapture | None:
        with self._connect() as connection:
            capture_row = connection.execute(
                """
                SELECT capture.*
                FROM activities AS activity
                JOIN activity_refresh_state AS state ON state.activity_id = activity.id
                JOIN activity_raw_captures AS capture ON capture.id = state.current_capture_id
                WHERE activity.provider = 'garmin' AND activity.source_activity_id = ?
                """,
                (source_activity_id,),
            ).fetchone()
            if capture_row is None:
                return None
            artifact_rows = connection.execute(
                "SELECT * FROM activity_raw_capture_artifacts WHERE capture_id = ? ORDER BY artifact_kind",
                (capture_row["id"],),
            ).fetchall()
        return ActivityCapture(
            capture_id=capture_row["id"],
            source_activity_id=capture_row["source_activity_id"],
            manifest_relative_path=capture_row["manifest_relative_path"],
            artifacts=tuple(
                RawArtifact(
                    kind=row["artifact_kind"],
                    relative_path=row["relative_path"],
                    content_type=row["content_type"],
                    sha256=row["sha256"],
                    byte_size=row["byte_size"],
                )
                for row in artifact_rows
            ),
        )

    def save_strength_sets(self, source_activity_id: str, strength_sets: tuple[StrengthSet, ...]) -> None:
        """Idempotently add normalized sets to an activity already stored in the database."""
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT id FROM activities WHERE provider = 'garmin' AND source_activity_id = ?",
                (source_activity_id,),
            ).fetchone()
            if row is None:
                raise ValueError(f"activity is not stored: {source_activity_id}")
            activity_id = int(row["id"])
            _insert_strength_sets(connection, activity_id, strength_sets, ignore_existing=True)
            connection.execute(
                "DELETE FROM activity_metrics WHERE activity_id = ? AND metric_key IN ('set_count', 'rep_count')",
                (activity_id,),
            )
            for metric in strength_set_metrics(strength_sets):
                numeric, text = _metric_values(metric)
                connection.execute(
                    """
                    INSERT INTO activity_metrics (
                        activity_id, metric_key, numeric_value, text_value, unit, source_path
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (activity_id, metric.key, numeric, text, metric.unit, metric.source_path),
                )
            connection.execute(
                "UPDATE activities SET normalizer_version = ? WHERE id = ?",
                (NORMALIZER_VERSION, activity_id),
            )

    def save_swim_detail(self, source_activity_id: str, swim_detail: NormalizedSwimActivity) -> None:
        """Idempotently add normalized pool-swimming details to a stored activity."""
        if swim_detail.source_activity_id != source_activity_id:
            raise ValueError("swim detail activity ID does not match the stored activity")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT id, canonical_type, source_type_key
                FROM activities
                WHERE provider = 'garmin' AND source_activity_id = ?
                """,
                (source_activity_id,),
            ).fetchone()
            if row is None:
                raise ValueError(f"activity is not stored: {source_activity_id}")
            if row["canonical_type"] != ActivityType.SWIMMING.value or row["source_type_key"] != "lap_swimming":
                raise ValueError("swim details can only be stored for Garmin pool-swimming activities")
            if swim_detail.source_type_key != row["source_type_key"]:
                raise ValueError("swim detail type does not match the stored activity")
            _insert_swim_detail(connection, int(row["id"]), swim_detail, ignore_existing=True)

    def list_source_activity_ids(self) -> tuple[str, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT source_activity_id FROM activities WHERE provider = 'garmin' ORDER BY source_activity_id"
            ).fetchall()
        return tuple(row["source_activity_id"] for row in rows)

    def upsert_activity_metrics(
        self,
        source_activity_id: str,
        metrics: tuple[ActivityMetric, ...],
        allowed_keys: frozenset[str],
        *,
        write: bool = True,
    ) -> MetricUpsertCounts:
        """Insert or update only allow-listed metric keys; every other row is left untouched.

        Never deletes metrics and never touches the parent activity row. With
        ``write=False`` the same comparison runs inside a transaction that is rolled back.
        """
        disallowed = {metric.key for metric in metrics} - allowed_keys
        if disallowed:
            raise ValueError(f"metric keys are not allowed for this upsert: {sorted(disallowed)}")
        if len({metric.key for metric in metrics}) != len(metrics):
            raise ValueError("duplicate metric keys in one upsert")
        inserted = updated = unchanged = 0
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT id FROM activities WHERE provider = 'garmin' AND source_activity_id = ?",
                (source_activity_id,),
            ).fetchone()
            if row is None:
                raise ValueError(f"activity is not stored: {source_activity_id}")
            activity_id = int(row["id"])
            for metric in metrics:
                numeric, text = _metric_values(metric)
                existing = connection.execute(
                    """
                    SELECT numeric_value, text_value, unit, source_path
                    FROM activity_metrics WHERE activity_id = ? AND metric_key = ?
                    """,
                    (activity_id, metric.key),
                ).fetchone()
                if existing is None:
                    inserted += 1
                    if write:
                        connection.execute(
                            """
                            INSERT INTO activity_metrics (
                                activity_id, metric_key, numeric_value, text_value, unit, source_path
                            ) VALUES (?, ?, ?, ?, ?, ?)
                            """,
                            (activity_id, metric.key, numeric, text, metric.unit, metric.source_path),
                        )
                elif (
                    existing["numeric_value"],
                    existing["text_value"],
                    existing["unit"],
                    existing["source_path"],
                ) == (numeric, text, metric.unit, metric.source_path):
                    unchanged += 1
                else:
                    updated += 1
                    if write:
                        connection.execute(
                            """
                            UPDATE activity_metrics
                            SET numeric_value = ?, text_value = ?, unit = ?, source_path = ?
                            WHERE activity_id = ? AND metric_key = ?
                            """,
                            (numeric, text, metric.unit, metric.source_path, activity_id, metric.key),
                        )
            if not write:
                connection.rollback()
        return MetricUpsertCounts(inserted, updated, unchanged)

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


class DailyRecoveryRepository:
    def __init__(self, database_path: Path):
        self._database_path = database_path

    def migrate(self) -> None:
        ActivityRepository(self._database_path).migrate()

    def find(self, calendar_date: str) -> DailyRecovery | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM daily_recovery WHERE provider = 'garmin' AND calendar_date = ?",
                (calendar_date,),
            ).fetchone()
        return _recovery_from_row(row) if row is not None else None

    def list_calendar_dates(self) -> tuple[str, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT calendar_date FROM daily_recovery WHERE provider = 'garmin' ORDER BY calendar_date"
            ).fetchall()
        return tuple(row["calendar_date"] for row in rows)

    def find_source_capture(self, calendar_date: str) -> RecoveryCapture | None:
        with self._connect() as connection:
            capture_row = connection.execute(
                """
                SELECT capture.*
                FROM daily_recovery AS recovery
                JOIN recovery_raw_captures AS capture
                  ON capture.id = recovery.primary_raw_capture_id
                WHERE recovery.provider = 'garmin' AND recovery.calendar_date = ?
                """,
                (calendar_date,),
            ).fetchone()
            if capture_row is None:
                return None
            artifact_rows = connection.execute(
                "SELECT * FROM recovery_raw_artifacts WHERE capture_id = ? ORDER BY artifact_kind",
                (capture_row["id"],),
            ).fetchall()
        return RecoveryCapture(
            capture_id=capture_row["id"],
            requested_date=capture_row["requested_date"],
            manifest_relative_path=capture_row["manifest_relative_path"],
            artifacts=tuple(
                RawArtifact(
                    kind=row["artifact_kind"],
                    relative_path=row["relative_path"],
                    content_type=row["content_type"],
                    sha256=row["sha256"],
                    byte_size=row["byte_size"],
                )
                for row in artifact_rows
            ),
        )

    def save(
        self,
        recovery: DailyRecovery,
        capture: RecoveryCapture,
    ) -> tuple[DailyRecovery, bool, bool]:
        if not capture.artifacts:
            raise ValueError("at least one recovery RAW artifact is required")
        if recovery.calendar_date != capture.requested_date:
            raise ValueError("recovery date does not match RAW capture date")
        now = _now()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._register_capture(connection, capture, now)
            existing = connection.execute(
                "SELECT * FROM daily_recovery WHERE provider = 'garmin' AND calendar_date = ?",
                (recovery.calendar_date,),
            ).fetchone()
            if existing is not None and existing["primary_raw_capture_id"] == capture.capture_id:
                stored_recovery = _recovery_from_row(existing)
                if stored_recovery == recovery:
                    return stored_recovery, False, False

            parameters = _recovery_parameters(recovery, capture.capture_id, now)
            if existing is None:
                connection.execute(_RECOVERY_INSERT_SQL, parameters)
                return recovery, True, False
            connection.execute(_RECOVERY_UPDATE_SQL, parameters)
            return recovery, False, True

    @staticmethod
    def _register_capture(connection: sqlite3.Connection, capture: RecoveryCapture, now: str) -> None:
        connection.execute(
            """
            INSERT OR IGNORE INTO recovery_raw_captures (
                id, provider, requested_date, manifest_relative_path, captured_at_utc
            ) VALUES (?, 'garmin', ?, ?, ?)
            """,
            (capture.capture_id, capture.requested_date, capture.manifest_relative_path, now),
        )
        stored_capture = connection.execute(
            "SELECT * FROM recovery_raw_captures WHERE id = ?",
            (capture.capture_id,),
        ).fetchone()
        if stored_capture is None or any(
            (
                stored_capture["provider"] != "garmin",
                stored_capture["requested_date"] != capture.requested_date,
                stored_capture["manifest_relative_path"] != capture.manifest_relative_path,
            )
        ):
            raise RuntimeError("stored recovery capture metadata does not match the files")

        for artifact in capture.artifacts:
            connection.execute(
                """
                INSERT OR IGNORE INTO recovery_raw_artifacts (
                    capture_id, artifact_kind, relative_path, content_type, sha256, byte_size
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    capture.capture_id,
                    artifact.kind,
                    artifact.relative_path,
                    artifact.content_type,
                    artifact.sha256,
                    artifact.byte_size,
                ),
            )
            stored_artifact = connection.execute(
                "SELECT * FROM recovery_raw_artifacts WHERE relative_path = ?",
                (artifact.relative_path,),
            ).fetchone()
            if stored_artifact is None or any(
                (
                    stored_artifact["capture_id"] != capture.capture_id,
                    stored_artifact["artifact_kind"] != artifact.kind,
                    stored_artifact["content_type"] != artifact.content_type,
                    stored_artifact["sha256"] != artifact.sha256,
                    stored_artifact["byte_size"] != artifact.byte_size,
                )
            ):
                raise RuntimeError("stored recovery RAW artifact metadata does not match the file")

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


def _register_activity_capture(
    connection: sqlite3.Connection,
    capture: ActivityCapture,
    now: str,
) -> None:
    connection.execute(
        """
        INSERT OR IGNORE INTO activity_raw_captures (
            id, provider, source_activity_id, manifest_relative_path, captured_at_utc
        ) VALUES (?, 'garmin', ?, ?, ?)
        """,
        (capture.capture_id, capture.source_activity_id, capture.manifest_relative_path, now),
    )
    stored_capture = connection.execute(
        "SELECT * FROM activity_raw_captures WHERE id = ?",
        (capture.capture_id,),
    ).fetchone()
    if stored_capture is None or any(
        (
            stored_capture["provider"] != "garmin",
            stored_capture["source_activity_id"] != capture.source_activity_id,
            stored_capture["manifest_relative_path"] != capture.manifest_relative_path,
        )
    ):
        raise RuntimeError("stored activity capture metadata does not match the files")
    for artifact in capture.artifacts:
        connection.execute(
            """
            INSERT OR IGNORE INTO activity_raw_capture_artifacts (
                capture_id, artifact_kind, relative_path, content_type, sha256, byte_size
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                capture.capture_id,
                artifact.kind,
                artifact.relative_path,
                artifact.content_type,
                artifact.sha256,
                artifact.byte_size,
            ),
        )
        stored = connection.execute(
            "SELECT * FROM activity_raw_capture_artifacts WHERE relative_path = ?",
            (artifact.relative_path,),
        ).fetchone()
        if stored is None or any(
            (
                stored["capture_id"] != capture.capture_id,
                stored["artifact_kind"] != artifact.kind,
                stored["content_type"] != artifact.content_type,
                stored["sha256"] != artifact.sha256,
                stored["byte_size"] != artifact.byte_size,
            )
        ):
            raise RuntimeError("stored activity RAW artifact metadata does not match the file")


def _activity_from_rows(
    row: sqlite3.Row,
    metric_rows: list[sqlite3.Row],
    strength_set_rows: list[sqlite3.Row],
    swim_detail: NormalizedSwimActivity | None,
) -> NormalizedActivity:
    metrics = tuple(
        ActivityMetric(
            key=item["metric_key"],
            value=item["numeric_value"] if item["numeric_value"] is not None else item["text_value"],
            unit=item["unit"],
            source_path=item["source_path"],
        )
        for item in metric_rows
    )
    strength_sets = tuple(
        StrengthSet(
            sequence=item["sequence"],
            source_message_index=item["source_message_index"],
            source_exercise_category=item["source_exercise_category"],
            source_exercise_name=item["source_exercise_name"],
            source_exercise_key=item["source_exercise_key"],
            display_exercise_name=item["display_exercise_name"],
            source_exercise_probability=item["source_exercise_probability"],
            set_type=item["set_type"],
            reps=item["reps"],
            source_weight=item["source_weight"],
            source_weight_unit=item["source_weight_unit"],
            normalized_weight_kg=item["normalized_weight_kg"],
            duration_seconds=item["duration_seconds"],
            started_at=item["started_at"],
            workout_step_index=item["workout_step_index"],
        )
        for item in strength_set_rows
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
        strength_sets=strength_sets,
        swim_detail=swim_detail,
        normalizer_version=row["normalizer_version"],
    )


def _swim_detail_from_connection(
    connection: sqlite3.Connection,
    activity_id: int,
) -> NormalizedSwimActivity | None:
    swim_row = connection.execute(
        "SELECT * FROM swim_activities WHERE activity_id = ?",
        (activity_id,),
    ).fetchone()
    if swim_row is None:
        return None

    lap_rows = connection.execute(
        "SELECT * FROM swim_laps WHERE activity_id = ? ORDER BY sequence",
        (activity_id,),
    ).fetchall()
    laps: list[SwimLap] = []
    for lap_row in lap_rows:
        length_rows = connection.execute(
            "SELECT * FROM swim_lengths WHERE swim_lap_id = ? ORDER BY sequence_in_lap",
            (lap_row["id"],),
        ).fetchall()
        lengths = tuple(_swim_length_from_row(item) for item in length_rows)
        laps.append(_swim_lap_from_row(lap_row, lengths))

    return NormalizedSwimActivity(
        source_activity_id=connection.execute(
            "SELECT source_activity_id FROM activities WHERE id = ?",
            (activity_id,),
        ).fetchone()[0],
        source_type_key=swim_row["source_type_key"],
        pool_length_meters=swim_row["pool_length_meters"],
        source_pool_length=swim_row["source_pool_length"],
        source_pool_length_unit=swim_row["source_pool_length_unit"],
        source_active_length_count=swim_row["source_active_length_count"],
        splits_available=bool(swim_row["splits_available"]),
        laps=tuple(laps),
        source=GarminSource(
            path=swim_row["garmin_source_path"],
            fields_json=swim_row["garmin_source_json"],
        ),
        normalizer_version=swim_row["normalizer_version"],
    )


def _swim_lap_from_row(row: sqlite3.Row, lengths: tuple[SwimLength, ...]) -> SwimLap:
    return SwimLap(
        sequence=row["sequence"],
        source_lap_index=row["source_lap_index"],
        source_message_index=row["source_message_index"],
        start_time_utc=row["start_time_utc"],
        intensity_type=row["intensity_type"],
        stroke_type=row["stroke_type"],
        distance=SwimDistance(row["garmin_distance_meters"], row["corrected_distance_meters"]),
        duration_seconds=row["duration_seconds"],
        moving_seconds=row["moving_seconds"],
        elapsed_seconds=row["elapsed_seconds"],
        rest_duration_seconds=row["garmin_rest_duration_seconds"],
        average_speed_mps=row["average_speed_mps"],
        active_length_count=row["active_length_count"],
        total_length_count=row["total_length_count"],
        stroke_count=row["stroke_count"],
        swolf=row["swolf"],
        average_hr_bpm=row["average_hr_bpm"],
        max_hr_bpm=row["max_hr_bpm"],
        lengths=lengths,
        source=GarminSource(path=row["garmin_source_path"], fields_json=row["garmin_source_json"]),
    )


def _swim_length_from_row(row: sqlite3.Row) -> SwimLength:
    return SwimLength(
        sequence=row["sequence"],
        sequence_in_lap=row["sequence_in_lap"],
        source_message_index=row["source_message_index"],
        start_time_utc=row["start_time_utc"],
        length_type=row["length_type"],
        stroke_type=row["stroke_type"],
        distance=SwimDistance(row["garmin_distance_meters"], row["corrected_distance_meters"]),
        duration_seconds=row["duration_seconds"],
        moving_seconds=row["moving_seconds"],
        elapsed_seconds=row["elapsed_seconds"],
        rest_duration_seconds=row["garmin_rest_duration_seconds"],
        average_speed_mps=row["average_speed_mps"],
        stroke_count=row["stroke_count"],
        swolf=row["swolf"],
        average_hr_bpm=row["average_hr_bpm"],
        max_hr_bpm=row["max_hr_bpm"],
        source=GarminSource(path=row["garmin_source_path"], fields_json=row["garmin_source_json"]),
    )


def _insert_swim_detail(
    connection: sqlite3.Connection,
    activity_id: int,
    swim_detail: NormalizedSwimActivity,
    *,
    ignore_existing: bool = False,
) -> None:
    statement = """
        INSERT INTO swim_activities (
            activity_id, source_type_key, pool_length_meters, source_pool_length,
            source_pool_length_unit, source_active_length_count, splits_available,
            garmin_source_path, garmin_source_json, normalizer_version
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """
    if ignore_existing:
        statement += " ON CONFLICT(activity_id) DO NOTHING"
    cursor = connection.execute(
        statement,
        (
            activity_id,
            swim_detail.source_type_key,
            swim_detail.pool_length_meters,
            swim_detail.source_pool_length,
            swim_detail.source_pool_length_unit,
            swim_detail.source_active_length_count,
            int(swim_detail.splits_available),
            swim_detail.source.path,
            swim_detail.source.fields_json,
            swim_detail.normalizer_version,
        ),
    )
    if ignore_existing and cursor.rowcount == 0:
        stored = _swim_detail_from_connection(connection, activity_id)
        if stored != swim_detail:
            raise RuntimeError("stored swim detail does not match the local RAW normalization")
        return

    for lap in swim_detail.laps:
        lap_cursor = connection.execute(
            """
            INSERT INTO swim_laps (
                activity_id, sequence, source_lap_index, source_message_index,
                start_time_utc, intensity_type, stroke_type, garmin_distance_meters,
                corrected_distance_meters, duration_seconds, moving_seconds,
                elapsed_seconds, garmin_rest_duration_seconds, average_speed_mps,
                active_length_count, total_length_count, stroke_count, swolf,
                average_hr_bpm, max_hr_bpm, garmin_source_path, garmin_source_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                activity_id,
                lap.sequence,
                lap.source_lap_index,
                lap.source_message_index,
                lap.start_time_utc,
                lap.intensity_type,
                lap.stroke_type,
                lap.distance.garmin_meters,
                lap.distance.corrected_meters,
                lap.duration_seconds,
                lap.moving_seconds,
                lap.elapsed_seconds,
                lap.rest_duration_seconds,
                lap.average_speed_mps,
                lap.active_length_count,
                lap.total_length_count,
                lap.stroke_count,
                lap.swolf,
                lap.average_hr_bpm,
                lap.max_hr_bpm,
                lap.source.path,
                lap.source.fields_json,
            ),
        )
        if lap_cursor.lastrowid is None:
            raise RuntimeError("SQLite did not return a swim lap ID")
        for length in lap.lengths:
            connection.execute(
                """
                INSERT INTO swim_lengths (
                    swim_lap_id, sequence, sequence_in_lap, source_message_index,
                    start_time_utc, length_type, stroke_type, garmin_distance_meters,
                    corrected_distance_meters, duration_seconds, moving_seconds,
                    elapsed_seconds, garmin_rest_duration_seconds, average_speed_mps,
                    stroke_count, swolf, average_hr_bpm, max_hr_bpm,
                    garmin_source_path, garmin_source_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    lap_cursor.lastrowid,
                    length.sequence,
                    length.sequence_in_lap,
                    length.source_message_index,
                    length.start_time_utc,
                    length.length_type,
                    length.stroke_type,
                    length.distance.garmin_meters,
                    length.distance.corrected_meters,
                    length.duration_seconds,
                    length.moving_seconds,
                    length.elapsed_seconds,
                    length.rest_duration_seconds,
                    length.average_speed_mps,
                    length.stroke_count,
                    length.swolf,
                    length.average_hr_bpm,
                    length.max_hr_bpm,
                    length.source.path,
                    length.source.fields_json,
                ),
            )


def _insert_strength_sets(
    connection: sqlite3.Connection,
    activity_id: int,
    strength_sets: tuple[StrengthSet, ...],
    *,
    ignore_existing: bool = False,
) -> None:
    for strength_set in strength_sets:
        values = _strength_set_values(activity_id, strength_set)
        statement = """
            INSERT INTO strength_sets (
                activity_id, sequence, source_message_index, source_exercise_category,
                source_exercise_name, source_exercise_key, display_exercise_name,
                source_exercise_probability, set_type, reps, source_weight,
                source_weight_unit, normalized_weight_kg, duration_seconds, started_at,
                workout_step_index
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        if ignore_existing:
            statement += " ON CONFLICT(activity_id, sequence) DO NOTHING"
        cursor = connection.execute(statement, values)
        if ignore_existing and cursor.rowcount == 0:
            stored = connection.execute(
                """
                SELECT activity_id, sequence, source_message_index, source_exercise_category,
                       source_exercise_name, source_exercise_key, display_exercise_name,
                       source_exercise_probability, set_type, reps, source_weight,
                       source_weight_unit, normalized_weight_kg, duration_seconds, started_at,
                       workout_step_index
                FROM strength_sets
                WHERE activity_id = ? AND sequence = ?
                """,
                (activity_id, strength_set.sequence),
            ).fetchone()
            if stored is None or tuple(stored) != values:
                raise RuntimeError("stored strength set does not match the local RAW normalization")


def _strength_set_values(activity_id: int, strength_set: StrengthSet) -> tuple[object, ...]:
    return (
        activity_id,
        strength_set.sequence,
        strength_set.source_message_index,
        strength_set.source_exercise_category,
        strength_set.source_exercise_name,
        strength_set.source_exercise_key,
        strength_set.display_exercise_name,
        strength_set.source_exercise_probability,
        strength_set.set_type,
        strength_set.reps,
        strength_set.source_weight,
        strength_set.source_weight_unit,
        strength_set.normalized_weight_kg,
        strength_set.duration_seconds,
        strength_set.started_at,
        strength_set.workout_step_index,
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


def _recovery_from_row(row: sqlite3.Row) -> DailyRecovery:
    return DailyRecovery(
        calendar_date=row["calendar_date"],
        sleep_seconds=row["sleep_seconds"],
        deep_sleep_seconds=row["deep_sleep_seconds"],
        light_sleep_seconds=row["light_sleep_seconds"],
        rem_sleep_seconds=row["rem_sleep_seconds"],
        awake_sleep_seconds=row["awake_sleep_seconds"],
        sleep_start_gmt_ms=row["sleep_start_gmt_ms"],
        sleep_end_gmt_ms=row["sleep_end_gmt_ms"],
        sleep_score=row["sleep_score"],
        sleep_avg_hrv_ms=row["sleep_avg_hrv_ms"],
        hrv_last_night_avg_ms=row["hrv_last_night_avg_ms"],
        hrv_weekly_avg_ms=row["hrv_weekly_avg_ms"],
        hrv_status=row["hrv_status"],
        resting_heart_rate_bpm=row["resting_heart_rate_bpm"],
        body_battery_high=row["body_battery_high"],
        body_battery_low=row["body_battery_low"],
        stress_average=row["stress_average"],
        training_readiness_score=row["training_readiness_score"],
        training_readiness_level=row["training_readiness_level"],
        recovery_time_minutes=row["recovery_time_minutes"],
        recovery_time_change_phrase=row["recovery_time_change_phrase"],
        training_status_key=row["training_status_key"],
        respiration_avg_brpm=row["respiration_avg_brpm"],
        normalizer_version=row["normalizer_version"],
    )


def _recovery_parameters(recovery: DailyRecovery, capture_id: str, now: str) -> dict[str, Any]:
    parameters = {
        name: getattr(recovery, name)
        for name in (
            "calendar_date",
            "sleep_seconds",
            "deep_sleep_seconds",
            "light_sleep_seconds",
            "rem_sleep_seconds",
            "awake_sleep_seconds",
            "sleep_start_gmt_ms",
            "sleep_end_gmt_ms",
            "sleep_score",
            "sleep_avg_hrv_ms",
            "hrv_last_night_avg_ms",
            "hrv_weekly_avg_ms",
            "hrv_status",
            "resting_heart_rate_bpm",
            "body_battery_high",
            "body_battery_low",
            "stress_average",
            "training_readiness_score",
            "training_readiness_level",
            "recovery_time_minutes",
            "recovery_time_change_phrase",
            "training_status_key",
            "respiration_avg_brpm",
            "normalizer_version",
        )
    }
    parameters.update(capture_id=capture_id, now=now)
    return parameters


_RECOVERY_COLUMNS = """
    calendar_date, sleep_seconds, deep_sleep_seconds, light_sleep_seconds,
    rem_sleep_seconds, awake_sleep_seconds, sleep_start_gmt_ms, sleep_end_gmt_ms,
    sleep_score, sleep_avg_hrv_ms, hrv_last_night_avg_ms, hrv_weekly_avg_ms,
    hrv_status, resting_heart_rate_bpm, body_battery_high, body_battery_low,
    stress_average, training_readiness_score, training_readiness_level,
    recovery_time_minutes, recovery_time_change_phrase, training_status_key,
    respiration_avg_brpm, normalizer_version
"""

_RECOVERY_VALUE_PARAMETERS = """
    :calendar_date, :sleep_seconds, :deep_sleep_seconds, :light_sleep_seconds,
    :rem_sleep_seconds, :awake_sleep_seconds, :sleep_start_gmt_ms, :sleep_end_gmt_ms,
    :sleep_score, :sleep_avg_hrv_ms, :hrv_last_night_avg_ms, :hrv_weekly_avg_ms,
    :hrv_status, :resting_heart_rate_bpm, :body_battery_high, :body_battery_low,
    :stress_average, :training_readiness_score, :training_readiness_level,
    :recovery_time_minutes, :recovery_time_change_phrase, :training_status_key,
    :respiration_avg_brpm, :normalizer_version
"""

_RECOVERY_INSERT_SQL = f"""
    INSERT INTO daily_recovery (
        provider, {_RECOVERY_COLUMNS}, primary_raw_capture_id, imported_at_utc, updated_at_utc
    ) VALUES (
        'garmin', {_RECOVERY_VALUE_PARAMETERS}, :capture_id, :now, :now
    )
"""

_RECOVERY_UPDATE_SQL = """
    UPDATE daily_recovery SET
        sleep_seconds = :sleep_seconds,
        deep_sleep_seconds = :deep_sleep_seconds,
        light_sleep_seconds = :light_sleep_seconds,
        rem_sleep_seconds = :rem_sleep_seconds,
        awake_sleep_seconds = :awake_sleep_seconds,
        sleep_start_gmt_ms = :sleep_start_gmt_ms,
        sleep_end_gmt_ms = :sleep_end_gmt_ms,
        sleep_score = :sleep_score,
        sleep_avg_hrv_ms = :sleep_avg_hrv_ms,
        hrv_last_night_avg_ms = :hrv_last_night_avg_ms,
        hrv_weekly_avg_ms = :hrv_weekly_avg_ms,
        hrv_status = :hrv_status,
        resting_heart_rate_bpm = :resting_heart_rate_bpm,
        body_battery_high = :body_battery_high,
        body_battery_low = :body_battery_low,
        stress_average = :stress_average,
        training_readiness_score = :training_readiness_score,
        training_readiness_level = :training_readiness_level,
        recovery_time_minutes = :recovery_time_minutes,
        recovery_time_change_phrase = :recovery_time_change_phrase,
        training_status_key = :training_status_key,
        respiration_avg_brpm = :respiration_avg_brpm,
        primary_raw_capture_id = :capture_id,
        normalizer_version = :normalizer_version,
        updated_at_utc = :now
    WHERE provider = 'garmin' AND calendar_date = :calendar_date
"""
