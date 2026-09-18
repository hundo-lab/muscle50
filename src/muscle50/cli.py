"""muscle50 command-line interface."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from datetime import date
from pathlib import Path

from muscle50.application.inbody_source import InBodySourceError
from muscle50.application.ingest_activity import ActivitySyncError
from muscle50.application.ingest_activity_range import IngestGarminActivityRange, InvalidDateRangeError
from muscle50.application.refresh_garmin_activity import (
    ActivityNotFoundError,
    ActivityRefreshError,
    RefreshGarminActivity,
)
from muscle50.application.sync_garmin_recovery import SyncGarminRecovery
from muscle50.application.sync_inbody import SyncInBody, SyncInBodyResult
from muscle50.application.sync_latest_garmin import NoActivitiesError, SyncLatestGarminActivity
from muscle50.config import AppPaths, ConfigurationError
from muscle50.domain.inbody_normalization import InBodyNormalizationError
from muscle50.domain.normalization import NormalizationError, activity_id_from
from muscle50.domain.recovery_normalization import RecoveryNormalizationError, validate_calendar_date
from muscle50.domain.swim_normalization import SwimNormalizationError
from muscle50.infrastructure.garmin.client import GarminConnectorError, PythonGarminConnector
from muscle50.infrastructure.inbody.raw_store import InBodyRawStore
from muscle50.infrastructure.inbody.samsung_health import SamsungHealthInBodySource
from muscle50.infrastructure.raw_store import RawStore, RawStoreError, RecoveryRawStore
from muscle50.infrastructure.sqlite.body_composition import SqliteBodyCompositionRepository
from muscle50.infrastructure.sqlite.database import ActivityRepository, DailyRecoveryRepository
from muscle50.presentation.terminal import (
    render_range_result,
    render_recovery_sync_result,
    render_refresh_result,
    render_sync_result,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="muscle50")
    commands = parser.add_subparsers(dest="command", required=True)
    garmin = commands.add_parser("garmin", help="Garmin Connect commands")
    garmin_commands = garmin.add_subparsers(dest="garmin_command", required=True)
    garmin_commands.add_parser("latest", help="Sync the latest Garmin activity")
    activities = garmin_commands.add_parser("activities", help="Ingest Garmin activities within a date range")
    activities.add_argument("--from", dest="from_date", required=True, metavar="YYYY-MM-DD")
    activities.add_argument("--to", dest="to_date", required=True, metavar="YYYY-MM-DD")
    recovery = garmin_commands.add_parser("recovery", help="Sync Garmin recovery data for one date")
    recovery.add_argument("date", help="Garmin calendar date in YYYY-MM-DD format")
    refresh = garmin_commands.add_parser("refresh", help="Refresh one existing Garmin activity")
    refresh.add_argument("activity_id", help="Garmin activity ID")
    inbody = commands.add_parser("inbody", help="InBody body-composition commands")
    inbody_commands = inbody.add_subparsers(dest="inbody_command", required=True)
    inbody_sync = inbody_commands.add_parser("sync", help="Import a Samsung Health companion export")
    inbody_sync.add_argument("--file", type=Path, required=True, help="versioned Samsung Health export JSON")
    inbody_sync.add_argument(
        "--show-values",
        action="store_true",
        help="explicitly print normalized health values; disabled by default",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "garmin" and args.garmin_command == "latest":
        return _garmin_latest()
    if args.command == "garmin" and args.garmin_command == "activities":
        return _garmin_activities(args.from_date, args.to_date)
    if args.command == "garmin" and args.garmin_command == "recovery":
        return _garmin_recovery(args.date)
    if args.command == "garmin" and args.garmin_command == "refresh":
        return _garmin_refresh(args.activity_id)
    if args.command == "inbody" and args.inbody_command == "sync":
        return _inbody_sync(args.file, show_values=args.show_values)
    return 2


def _garmin_latest() -> int:
    try:
        paths = AppPaths.from_environment()
        paths.ensure_directories()
        repository = ActivityRepository(paths.database_path)
        repository.migrate()
        connector = PythonGarminConnector.authenticate(paths.auth_dir)
        use_case = SyncLatestGarminActivity(
            connector,
            repository,
            RawStore(paths.raw_dir, paths.root, paths.tmp_dir),
        )
        print(render_sync_result(use_case.execute()))
        return 0
    except (
        ActivitySyncError,
        ConfigurationError,
        GarminConnectorError,
        NoActivitiesError,
        NormalizationError,
        RawStoreError,
        SwimNormalizationError,
    ) as exc:
        print(f"오류: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\n취소되었습니다.", file=sys.stderr)
        return 130


def _garmin_activities(from_date_text: str, to_date_text: str) -> int:
    try:
        from_date = date.fromisoformat(from_date_text)
        to_date = date.fromisoformat(to_date_text)
    except ValueError:
        print("오류: --from/--to는 YYYY-MM-DD 형식이어야 합니다.", file=sys.stderr)
        return 1
    if from_date > to_date:
        print("오류: --from은 --to보다 이후일 수 없습니다.", file=sys.stderr)
        return 1

    try:
        paths = AppPaths.from_environment()
        paths.ensure_directories()
        repository = ActivityRepository(paths.database_path)
        repository.migrate()
        connector = PythonGarminConnector.authenticate(paths.auth_dir)
        use_case = IngestGarminActivityRange(
            connector,
            repository,
            RawStore(paths.raw_dir, paths.root, paths.tmp_dir),
        )
        print(render_range_result(use_case.execute(from_date, to_date)))
        return 0
    except (
        ActivitySyncError,
        ConfigurationError,
        GarminConnectorError,
        InvalidDateRangeError,
        NormalizationError,
        RawStoreError,
    ) as exc:
        print(f"오류: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\n취소되었습니다.", file=sys.stderr)
        return 130


def _garmin_recovery(calendar_date: str) -> int:
    try:
        calendar_date = validate_calendar_date(calendar_date)
        paths = AppPaths.from_environment()
        paths.ensure_directories()
        repository = DailyRecoveryRepository(paths.database_path)
        repository.migrate()
        connector = PythonGarminConnector.authenticate(paths.auth_dir)
        use_case = SyncGarminRecovery(
            connector,
            repository,
            RecoveryRawStore(paths.recovery_raw_dir, paths.root, paths.tmp_dir),
        )
        print(render_recovery_sync_result(use_case.execute(calendar_date)))
        return 0
    except (
        ConfigurationError,
        GarminConnectorError,
        RawStoreError,
        RecoveryNormalizationError,
    ) as exc:
        print(f"오류: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\n취소되었습니다.", file=sys.stderr)
        return 130


def _garmin_refresh(source_activity_id: str) -> int:
    try:
        source_activity_id = activity_id_from({"activityId": source_activity_id})
        paths = AppPaths.from_environment()
        paths.ensure_directories()
        repository = ActivityRepository(paths.database_path)
        repository.migrate()
        if repository.find(source_activity_id) is None:
            raise ActivityNotFoundError(f"local Garmin activity not found: {source_activity_id}")
        connector = PythonGarminConnector.authenticate(paths.auth_dir)
        use_case = RefreshGarminActivity(
            connector,
            repository,
            RawStore(paths.raw_dir, paths.root, paths.tmp_dir),
        )
        print(render_refresh_result(use_case.execute(source_activity_id)))
        return 0
    except (
        ActivityRefreshError,
        ConfigurationError,
        GarminConnectorError,
        NormalizationError,
        RawStoreError,
        SwimNormalizationError,
    ) as exc:
        print(f"오류: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\n취소했습니다.", file=sys.stderr)
        return 130


def _inbody_sync(payload_path: Path, *, show_values: bool) -> int:
    try:
        paths = AppPaths.from_environment()
        paths.ensure_directories()
        repository = SqliteBodyCompositionRepository(paths.database_path)
        repository.migrate()
        result = SyncInBody(
            SamsungHealthInBodySource(payload_path.expanduser()),
            repository,
            InBodyRawStore(paths.inbody_raw_dir, paths.root, paths.tmp_dir),
        ).execute(refresh_existing=True)
        print(_render_inbody_result(result, show_values=show_values))
        if result.changed_count:
            print(
                "A known Samsung UID had different RAW content; normalized data was not overwritten.",
                file=sys.stderr,
            )
            return 2
        return 0
    except (ConfigurationError, InBodyNormalizationError, InBodySourceError, OSError) as exc:
        print(f"InBody sync failed: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nInBody sync cancelled.", file=sys.stderr)
        return 130


def _render_inbody_result(result: SyncInBodyResult, *, show_values: bool) -> str:
    lines = [
        "Source: Samsung Health / InBody",
        f"Records discovered: {result.listed_count}",
        f"Inserted: {result.created_count}",
        f"Already existing: {result.existing_count}",
        f"Changed RAW conflicts: {result.changed_count}",
        f"RAW list snapshot stored: {result.list_snapshot.relative_path}",
        f"Normalized measurements available: {len(result.items)}",
    ]
    if show_values:
        for index, item in enumerate(result.items, start=1):
            measurement = item.measurement
            lines.append(
                f"Record {index} values: weight_kg={measurement.weight_kg!r} "
                f"smm_kg={measurement.skeletal_muscle_mass_kg!r} "
                f"bfm_kg={measurement.body_fat_mass_kg!r} "
                f"pbf={measurement.body_fat_percent!r} bmi={measurement.bmi!r} "
                f"tbw_l={measurement.total_body_water_l!r} "
                f"bmr_kcal_per_day={measurement.basal_metabolic_rate_kcal_per_day!r}"
            )
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
