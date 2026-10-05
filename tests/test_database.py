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
    "strength_sets",
    "swim_activities",
    "swim_laps",
    "swim_lengths",
    "nutrition_meals",
    "nutrition_meal_items",
    "nutrition_food_profiles",
    "nutrition_food_profile_aliases",
    "nutrition_facts",
    "nutrition_meal_item_removals",
    "nutrition_meal_revisions",
    "nutrition_meal_voids",
    "nutrition_meal_merged_items",
    "sync_coverage",
    "recovery_raw_captures",
    "recovery_raw_artifacts",
    "daily_recovery",
    "activity_raw_captures",
    "activity_raw_capture_artifacts",
    "activity_refresh_state",
    "inbody_raw_artifacts",
    "body_composition_measurements",
    "body_composition_source_identities",
    "body_composition_raw_artifact_links",
    "body_composition_provenance",
    "body_composition_segmental_metrics",
    "body_composition_metrics",
}
EXPECTED_VERSIONS = [(1,), (2,), (3,), (4,), (5,), (6,), (7,), (8,), (9,), (10,)]

MIGRATIONS_DIR = (
    Path(__file__).parents[1] / "src" / "muscle50" / "infrastructure" / "sqlite" / "migrations"
)


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
    assert versions == EXPECTED_VERSIONS


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
    assert versions == EXPECTED_VERSIONS


def test_first_migration_is_safe_under_concurrent_startup(tmp_path: Path) -> None:
    database_path = tmp_path / "concurrent.sqlite3"

    with ThreadPoolExecutor(max_workers=4) as executor:
        list(executor.map(lambda _: ActivityRepository(database_path).migrate(), range(4)))

    with sqlite3.connect(database_path) as connection:
        versions = connection.execute("SELECT version FROM schema_migrations").fetchall()
    assert versions == EXPECTED_VERSIONS


def test_strength_sets_migration_upgrades_existing_database(tmp_path: Path) -> None:
    database_path = tmp_path / "existing.sqlite3"
    initial_migration = MIGRATIONS_DIR / "001_initial.sql"
    with sqlite3.connect(database_path) as connection:
        connection.executescript(initial_migration.read_text(encoding="utf-8"))

    ActivityRepository(database_path).migrate()

    with sqlite3.connect(database_path) as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(strength_sets)")}
        versions = connection.execute("SELECT version FROM schema_migrations ORDER BY version").fetchall()
    assert {
        "activity_id",
        "sequence",
        "source_exercise_key",
        "display_exercise_name",
        "set_type",
        "reps",
        "source_weight",
        "source_weight_unit",
        "normalized_weight_kg",
        "duration_seconds",
    } <= columns
    assert versions == EXPECTED_VERSIONS


def test_nutrition_migration_upgrades_existing_001_002_database(tmp_path: Path) -> None:
    database_path = tmp_path / "existing-001-002.sqlite3"
    with sqlite3.connect(database_path) as connection:
        for migration_name in ("001_initial.sql", "002_strength_sets.sql"):
            connection.executescript((MIGRATIONS_DIR / migration_name).read_text(encoding="utf-8"))
        existing_versions = connection.execute(
            "SELECT version, applied_at_utc FROM schema_migrations ORDER BY version"
        ).fetchall()

    ActivityRepository(database_path).migrate()

    with sqlite3.connect(database_path) as connection:
        versions = connection.execute(
            "SELECT version, applied_at_utc FROM schema_migrations ORDER BY version"
        ).fetchall()
        nutrition_tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name LIKE 'nutrition_%'"
            )
        }
    assert versions[:2] == existing_versions
    assert [row[0] for row in versions] == [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
    assert nutrition_tables == {
        "nutrition_meals",
        "nutrition_meal_items",
        "nutrition_food_profiles",
        "nutrition_food_profile_aliases",
        "nutrition_facts",
        "nutrition_meal_item_removals",
        "nutrition_meal_revisions",
        "nutrition_meal_voids",
        "nutrition_meal_merged_items",
    }


def test_swim_migration_upgrades_existing_001_through_003_database(tmp_path: Path) -> None:
    database_path = tmp_path / "existing-001-003.sqlite3"
    with sqlite3.connect(database_path) as connection:
        for migration_name in ("001_initial.sql", "002_strength_sets.sql", "003_nutrition.sql"):
            connection.executescript((MIGRATIONS_DIR / migration_name).read_text(encoding="utf-8"))
        existing_versions = connection.execute(
            "SELECT version, applied_at_utc FROM schema_migrations ORDER BY version"
        ).fetchall()

    ActivityRepository(database_path).migrate()

    with sqlite3.connect(database_path) as connection:
        versions = connection.execute(
            "SELECT version, applied_at_utc FROM schema_migrations ORDER BY version"
        ).fetchall()
        swim_tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name LIKE 'swim_%'"
            )
        }
        lap_foreign_keys = connection.execute("PRAGMA foreign_key_list(swim_laps)").fetchall()
        length_foreign_keys = connection.execute("PRAGMA foreign_key_list(swim_lengths)").fetchall()
    assert versions[:3] == existing_versions
    assert [row[0] for row in versions] == [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
    assert swim_tables == {"swim_activities", "swim_laps", "swim_lengths"}
    assert any(row[2] == "swim_activities" for row in lap_foreign_keys)
    assert any(row[2] == "swim_laps" for row in length_foreign_keys)


def test_recovery_migration_upgrades_existing_001_through_004_database(tmp_path: Path) -> None:
    database_path = tmp_path / "existing-001-004.sqlite3"
    migration_names = (
        "001_initial.sql",
        "002_strength_sets.sql",
        "003_nutrition.sql",
        "004_swim_details.sql",
    )
    with sqlite3.connect(database_path) as connection:
        for migration_name in migration_names:
            connection.executescript((MIGRATIONS_DIR / migration_name).read_text(encoding="utf-8"))
        existing_versions = connection.execute(
            "SELECT version, applied_at_utc FROM schema_migrations ORDER BY version"
        ).fetchall()

    ActivityRepository(database_path).migrate()

    with sqlite3.connect(database_path) as connection:
        versions = connection.execute(
            "SELECT version, applied_at_utc FROM schema_migrations ORDER BY version"
        ).fetchall()
        recovery_tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name LIKE '%recovery%'"
            )
        }
        daily_columns = {row[1] for row in connection.execute("PRAGMA table_info(daily_recovery)")}
        recovery_foreign_keys = connection.execute("PRAGMA foreign_key_list(daily_recovery)").fetchall()

    assert versions[:4] == existing_versions
    assert [row[0] for row in versions] == [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
    assert recovery_tables == {"recovery_raw_captures", "recovery_raw_artifacts", "daily_recovery"}
    assert {
        "calendar_date",
        "sleep_seconds",
        "hrv_last_night_avg_ms",
        "training_readiness_score",
        "primary_raw_capture_id",
        "updated_at_utc",
    } <= daily_columns
    assert any(row[2] == "recovery_raw_captures" for row in recovery_foreign_keys)


def test_inbody_migration_upgrades_existing_001_through_005_database(tmp_path: Path) -> None:
    database_path = tmp_path / "existing-001-005.sqlite3"
    migration_names = (
        "001_initial.sql",
        "002_strength_sets.sql",
        "003_nutrition.sql",
        "004_swim_details.sql",
        "005_daily_recovery.sql",
    )
    with sqlite3.connect(database_path) as connection:
        for migration_name in migration_names:
            connection.executescript((MIGRATIONS_DIR / migration_name).read_text(encoding="utf-8"))
        existing_versions = connection.execute(
            "SELECT version, applied_at_utc FROM schema_migrations ORDER BY version"
        ).fetchall()

    ActivityRepository(database_path).migrate()

    with sqlite3.connect(database_path) as connection:
        versions = connection.execute(
            "SELECT version, applied_at_utc FROM schema_migrations ORDER BY version"
        ).fetchall()
        inbody_tables = {
            row[0]
            for row in connection.execute(
                """
                SELECT name FROM sqlite_master
                WHERE type = 'table'
                  AND (name LIKE 'inbody_%' OR name LIKE 'body_composition_%')
                """
            )
        }

    assert versions[:5] == existing_versions
    assert [row[0] for row in versions] == [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
    assert inbody_tables == {
        "inbody_raw_artifacts",
        "body_composition_measurements",
        "body_composition_source_identities",
        "body_composition_raw_artifact_links",
        "body_composition_provenance",
        "body_composition_segmental_metrics",
        "body_composition_metrics",
    }


def test_numbered_migrations_can_be_reapplied_without_duplicate_versions(tmp_path: Path) -> None:
    database_path = tmp_path / "repeated.sqlite3"
    repository = ActivityRepository(database_path)

    repository.migrate()
    with sqlite3.connect(database_path) as connection:
        first_versions = connection.execute(
            "SELECT version, applied_at_utc FROM schema_migrations ORDER BY version"
        ).fetchall()

    repository.migrate()

    with sqlite3.connect(database_path) as connection:
        repeated_versions = connection.execute(
            "SELECT version, applied_at_utc FROM schema_migrations ORDER BY version"
        ).fetchall()
    assert repeated_versions == first_versions
    assert [row[0] for row in repeated_versions] == [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]


def test_activity_refresh_migration_upgrades_existing_001_through_005_database(tmp_path: Path) -> None:
    database_path = tmp_path / "existing-001-005.sqlite3"
    with sqlite3.connect(database_path) as connection:
        for migration_name in (
            "001_initial.sql",
            "002_strength_sets.sql",
            "003_nutrition.sql",
            "004_swim_details.sql",
            "005_daily_recovery.sql",
        ):
            connection.executescript((MIGRATIONS_DIR / migration_name).read_text(encoding="utf-8"))

    ActivityRepository(database_path).migrate()

    with sqlite3.connect(database_path) as connection:
        versions = connection.execute("SELECT version FROM schema_migrations ORDER BY version").fetchall()
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name LIKE 'activity_%'"
            )
        }
    assert versions == EXPECTED_VERSIONS
    assert {"activity_raw_captures", "activity_raw_capture_artifacts", "activity_refresh_state"} <= tables
