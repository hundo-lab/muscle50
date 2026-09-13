"""muscle50 command-line interface."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from muscle50.application.sync_latest_garmin import (
    ActivitySyncError,
    NoActivitiesError,
    SyncLatestGarminActivity,
)
from muscle50.config import AppPaths, ConfigurationError
from muscle50.domain.normalization import NormalizationError
from muscle50.infrastructure.garmin.client import GarminConnectorError, PythonGarminConnector
from muscle50.infrastructure.raw_store import RawStore, RawStoreError
from muscle50.infrastructure.sqlite.database import ActivityRepository
from muscle50.presentation.terminal import render_sync_result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="muscle50")
    commands = parser.add_subparsers(dest="command", required=True)
    garmin = commands.add_parser("garmin", help="Garmin Connect activity commands")
    garmin_commands = garmin.add_subparsers(dest="garmin_command", required=True)
    garmin_commands.add_parser("latest", help="Sync the latest Garmin activity")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "garmin" and args.garmin_command == "latest":
        return _garmin_latest()
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


if __name__ == "__main__":
    raise SystemExit(main())
