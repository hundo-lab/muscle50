"""SQLite migration and activity repository."""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from importlib.resources import files
from pathlib import Path

from muscle50.domain.activity import (
    NORMALIZER_VERSION,
    ActivityMetric,
    ActivityType,
    NormalizedActivity,
    StrengthSet,
)
from muscle50.domain.normalization import strength_set_metrics
from muscle50.domain.swimming import GarminSource, NormalizedSwimActivity, SwimDistance, SwimLap, SwimLength
from muscle50.infrastructure.raw_store import RawArtifact


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
