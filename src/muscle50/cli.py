"""muscle50 command-line interface."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from datetime import date

from muscle50.application.ingest_activity import ActivitySyncError
from muscle50.application.ingest_activity_range import IngestGarminActivityRange, InvalidDateRangeError
from muscle50.application.sync_garmin_recovery import SyncGarminRecovery
from muscle50.application.sync_latest_garmin import NoActivitiesError, SyncLatestGarminActivity
from muscle50.config import AppPaths, ConfigurationError
from muscle50.domain.normalization import NormalizationError
from muscle50.domain.recovery_normalization import RecoveryNormalizationError, validate_calendar_date
from muscle50.infrastructure.garmin.client import GarminConnectorError, PythonGarminConnector
from muscle50.infrastructure.raw_store import RawStore, RawStoreError, RecoveryRawStore
from muscle50.infrastructure.sqlite.database import ActivityRepository, DailyRecoveryRepository
from muscle50.presentation.terminal import render_range_result, render_recovery_sync_result, render_sync_result


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
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "garmin" and args.garmin_command == "latest":
        return _garmin_latest()
    if args.command == "garmin" and args.garmin_command == "activities":
        return _garmin_activities(args.from_date, args.to_date)
    if args.command == "garmin" and args.garmin_command == "recovery":
        return _garmin_recovery(args.date)
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


if __name__ == "__main__":
    raise SystemExit(main())
