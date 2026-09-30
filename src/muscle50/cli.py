"""muscle50 command-line interface."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from datetime import date
from pathlib import Path

from muscle50.application.backfill_activity_load_metrics import BackfillActivityLoadMetrics
from muscle50.application.inbody_source import InBodySourceError
from muscle50.application.ingest_activity import ActivitySyncError
from muscle50.application.ingest_activity_range import IngestGarminActivityRange, InvalidDateRangeError
from muscle50.application.refresh_garmin_activity import (
    ActivityNotFoundError,
    ActivityRefreshError,
    RefreshGarminActivity,
)
from muscle50.application.renormalize_garmin_recovery import RenormalizeGarminRecovery
from muscle50.application.sync_garmin_recovery import (
    RECOVERY_ENDPOINTS_PER_DATE,
    InvalidRecoveryRangeError,
    SyncGarminRecovery,
    recovery_range_dates,
)
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
    render_activity_load_backfill_result,
    render_range_result,
    render_recovery_range_result,
    render_recovery_renormalize_result,
    render_recovery_sync_result,
    render_refresh_result,
    render_sync_result,
)

# Longer recovery ranges need --yes because each date costs several Garmin requests.
_RECOVERY_UNCONFIRMED_MAX_DAYS = 7


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="muscle50")
    commands = parser.add_subparsers(dest="command", required=True)
    garmin = commands.add_parser("garmin", help="Garmin Connect commands")
    garmin_commands = garmin.add_subparsers(dest="garmin_command", required=True)
    garmin_commands.add_parser("latest", help="Sync the latest Garmin activity")
    activities = garmin_commands.add_parser("activities", help="Ingest Garmin activities within a date range")
    activities.add_argument("--from", dest="from_date", required=True, metavar="YYYY-MM-DD")
    activities.add_argument("--to", dest="to_date", required=True, metavar="YYYY-MM-DD")
    recovery = garmin_commands.add_parser(
        "recovery", help="Sync Garmin recovery data for one date or an inclusive --from/--to range"
    )
    recovery.add_argument("date", nargs="?", help="Garmin calendar date in YYYY-MM-DD format")
    recovery.add_argument("--from", dest="from_date", metavar="YYYY-MM-DD")
    recovery.add_argument("--to", dest="to_date", metavar="YYYY-MM-DD")
    recovery.add_argument(
        "--yes",
        action="store_true",
        help=f"confirm a range longer than {_RECOVERY_UNCONFIRMED_MAX_DAYS} days "
        f"(about {RECOVERY_ENDPOINTS_PER_DATE} Garmin requests per date)",
    )
    refresh = garmin_commands.add_parser("refresh", help="Refresh one existing Garmin activity")
    refresh.add_argument("activity_id", help="Garmin activity ID")
    backfill = garmin_commands.add_parser(
        "backfill-load-metrics",
        help="Backfill activity-load metrics from already-stored Garmin RAW summaries (no Garmin API calls)",
    )
    backfill.add_argument("--dry-run", action="store_true", help="report changes without writing")
    renormalize = garmin_commands.add_parser(
        "recovery-renormalize",
        help="Re-normalize stored recovery rows from their accepted RAW capture (no Garmin API calls)",
    )
    renormalize.add_argument("--dry-run", action="store_true", help="report changes without writing")
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
        if args.from_date is None and args.to_date is None:
            if args.date is None:
                print("오류: 날짜 또는 --from/--to 범위가 필요합니다.", file=sys.stderr)
                return 1
            return _garmin_recovery(args.date)
        return _garmin_recovery_range(args.date, args.from_date, args.to_date, confirmed=args.yes)
    if args.command == "garmin" and args.garmin_command == "refresh":
        return _garmin_refresh(args.activity_id)
    if args.command == "garmin" and args.garmin_command == "backfill-load-metrics":
        return _garmin_backfill_load_metrics(dry_run=args.dry_run)
    if args.command == "garmin" and args.garmin_command == "recovery-renormalize":
        return _garmin_recovery_renormalize(dry_run=args.dry_run)
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


def _garmin_recovery_range(
    single_date: str | None,
    from_text: str | None,
    to_text: str | None,
    *,
    confirmed: bool,
) -> int:
    # Every check here runs before authentication so a bad request costs no Garmin calls.
    if single_date is not None:
        print("오류: 날짜 인자와 --from/--to는 함께 사용할 수 없습니다.", file=sys.stderr)
        return 1
    if from_text is None or to_text is None:
        print("오류: 범위 sync에는 --from과 --to가 모두 필요합니다.", file=sys.stderr)
        return 1
    try:
        from_date = date.fromisoformat(validate_calendar_date(from_text))
        to_date = date.fromisoformat(validate_calendar_date(to_text))
        dates = recovery_range_dates(from_date, to_date)
    except (InvalidRecoveryRangeError, RecoveryNormalizationError) as exc:
        print(f"오류: {exc}", file=sys.stderr)
        return 1
    estimated_calls = len(dates) * RECOVERY_ENDPOINTS_PER_DATE
    if len(dates) > _RECOVERY_UNCONFIRMED_MAX_DAYS and not confirmed:
        print(
            f"오류: {len(dates)}일 범위는 Garmin 요청 약 {estimated_calls}회가 필요합니다. "
            "계속하려면 --yes를 추가하세요.",
            file=sys.stderr,
        )
        return 1

    try:
        paths = AppPaths.from_environment()
        paths.ensure_directories()
        repository = DailyRecoveryRepository(paths.database_path)
        repository.migrate()
        print(f"Recovery {len(dates)}일 순차 sync (Garmin 요청 약 {estimated_calls}회)", file=sys.stderr)
        connector = PythonGarminConnector.authenticate(paths.auth_dir)
        use_case = SyncGarminRecovery(
            connector,
            repository,
            RecoveryRawStore(paths.recovery_raw_dir, paths.root, paths.tmp_dir),
        )
        result = use_case.execute_range(from_date, to_date)
        print(render_recovery_range_result(result))
        if not result.complete:
            print("일부 날짜가 저장되지 않았습니다. 같은 명령을 다시 실행해도 안전합니다.", file=sys.stderr)
            return 1
        return 0
    except (ConfigurationError, GarminConnectorError) as exc:
        print(f"오류: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\n취소되었습니다.", file=sys.stderr)
        return 130


def _garmin_backfill_load_metrics(*, dry_run: bool) -> int:
    # Deliberately never authenticates or builds a Garmin connector.
    try:
        paths = AppPaths.from_environment()
        paths.ensure_directories()
        repository = ActivityRepository(paths.database_path)
        repository.migrate()
        use_case = BackfillActivityLoadMetrics(repository, RawStore(paths.raw_dir, paths.root, paths.tmp_dir))
        print(render_activity_load_backfill_result(use_case.execute(dry_run=dry_run)))
        return 0
    except ConfigurationError as exc:
        print(f"오류: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\n취소되었습니다.", file=sys.stderr)
        return 130


def _garmin_recovery_renormalize(*, dry_run: bool) -> int:
    # Deliberately never authenticates or builds a Garmin connector.
    try:
        paths = AppPaths.from_environment()
        paths.ensure_directories()
        repository = DailyRecoveryRepository(paths.database_path)
        repository.migrate()
        use_case = RenormalizeGarminRecovery(
            repository,
            RecoveryRawStore(paths.recovery_raw_dir, paths.root, paths.tmp_dir),
        )
        result = use_case.execute(dry_run=dry_run)
        print(render_recovery_renormalize_result(result))
        return 1 if result.failures else 0
    except ConfigurationError as exc:
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
