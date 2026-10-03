"""muscle50 command-line interface."""

from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Sequence
from datetime import UTC, date, datetime, time, timezone, tzinfo
from decimal import Decimal
from pathlib import Path

from muscle50.application.backfill_activity_load_metrics import BackfillActivityLoadMetrics
from muscle50.application.daily_sync import DailyMode, RunDailySync, daily_sync_start
from muscle50.application.inbody_source import InBodySourceError
from muscle50.application.ingest_activity import ActivitySyncError
from muscle50.application.ingest_activity_range import IngestGarminActivityRange, InvalidDateRangeError
from muscle50.application.nutrition_logging import (
    CATALOG_SOURCE_TYPES,
    AddFood,
    AddFoodFact,
    AddMealItems,
    ListFoods,
    LogMeal,
    MealEntryItem,
    NewFood,
    NewFoodFact,
    NutritionLoggingError,
    RemoveMealItem,
    ReplaceMealItem,
    ShowDailyIntake,
    ShowFood,
    ShowMeal,
    offset_name,
)
from muscle50.application.nutrition_recommendation import BuildNutritionContext
from muscle50.application.nutrition_targets import (
    SetNutritionTarget,
    ShowDailyNutritionStatus,
    ShowNutritionTargets,
)
from muscle50.application.recommend_training import BuildTrainingRecommendation
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
from muscle50.application.training_snapshot import BuildTrainingSnapshot
from muscle50.config import AppPaths, ConfigurationError
from muscle50.domain.analytics import DEFAULT_LOOKBACK_DAYS, MAX_LOOKBACK_DAYS, InvalidSnapshotWindowError
from muscle50.domain.exercise_taxonomy import MuscleGroup
from muscle50.domain.inbody_normalization import InBodyNormalizationError
from muscle50.domain.normalization import NormalizationError, activity_id_from
from muscle50.domain.nutrition import Accuracy, MealType, NutrientField, NutritionValue, QuantityUnit
from muscle50.domain.nutrition_targets import ExactTarget, NutrientTarget, NutritionTargetError, RangeTarget
from muscle50.domain.recovery_normalization import RecoveryNormalizationError, validate_calendar_date
from muscle50.domain.strength_recommendation import StrengthFocus
from muscle50.domain.swim_normalization import SwimNormalizationError
from muscle50.infrastructure.decimal_text import decimal_from_text
from muscle50.infrastructure.garmin.client import GarminConnectorError, PythonGarminConnector
from muscle50.infrastructure.inbody.raw_store import InBodyRawStore
from muscle50.infrastructure.inbody.samsung_health import SamsungHealthInBodySource
from muscle50.infrastructure.nutrition_target_store import JsonNutritionTargetRepository
from muscle50.infrastructure.raw_store import RawStore, RawStoreError, RecoveryRawStore
from muscle50.infrastructure.sqlite.analytics_reader import AnalyticsDatabaseError, SqliteAnalyticsReader
from muscle50.infrastructure.sqlite.body_composition import SqliteBodyCompositionRepository
from muscle50.infrastructure.sqlite.database import ActivityRepository, DailyRecoveryRepository
from muscle50.infrastructure.sqlite.nutrition_reader import SqliteNutritionReader
from muscle50.infrastructure.sqlite.nutrition_repository import SqliteFoodNutritionRepository, SqliteMealRepository
from muscle50.presentation.nutrition_terminal import (
    render_daily_intake,
    render_daily_intake_json,
    render_edited_meal,
    render_food,
    render_food_json,
    render_food_list,
    render_food_list_json,
    render_logged_meal,
    render_logged_meal_json,
    render_meal,
    render_nutrition_status,
    render_nutrition_status_json,
    render_targets,
    render_targets_json,
)
from muscle50.presentation.terminal import (
    render_activity_load_backfill_result,
    render_daily_sync,
    render_daily_sync_json,
    render_range_result,
    render_recovery_range_result,
    render_recovery_renormalize_result,
    render_recovery_sync_result,
    render_refresh_result,
    render_sync_result,
    render_training_recommendation,
    render_training_recommendation_json,
    render_training_snapshot,
    render_training_snapshot_json,
)

# Longer recovery ranges need --yes because each date costs several Garmin requests.
_RECOVERY_UNCONFIRMED_MAX_DAYS = 7

_UNITS_TEXT = ", ".join(unit.value for unit in QuantityUnit)
_UNKNOWN_NUTRIENT = "unknown"
_TIME_PATTERN = re.compile(r"[0-2][0-9]:[0-5][0-9]\Z")
# Same nutrient names as the `food add` flags.
_TARGET_NUTRIENTS: dict[str, NutrientField] = {
    "kcal": NutrientField.CALORIES_KCAL,
    "protein": NutrientField.PROTEIN_G,
    "carbs": NutrientField.CARBOHYDRATE_G,
    "fat": NutrientField.FAT_G,
}


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
    analytics = commands.add_parser("analytics", help="Read-only analytics over stored canonical data")
    analytics_commands = analytics.add_subparsers(dest="analytics_command", required=True)
    snapshot = analytics_commands.add_parser(
        "snapshot",
        help="Rolling training snapshot ending on --date (reads the database read-only; no Garmin calls)",
    )
    snapshot.add_argument("--date", dest="as_of", required=True, metavar="YYYY-MM-DD", help="last day of the window")
    snapshot.add_argument(
        "--days",
        type=int,
        default=DEFAULT_LOOKBACK_DAYS,
        help=f"inclusive lookback window in days (1-{MAX_LOOKBACK_DAYS}, default {DEFAULT_LOOKBACK_DAYS})",
    )
    snapshot.add_argument("--json", action="store_true", help="print the full snapshot with provenance as JSON")
    recommend = commands.add_parser(
        "recommend",
        help="Deterministic strength and next-swim recommendation for --date "
        "(reads the database read-only; no Garmin calls)",
    )
    recommend.add_argument("--date", dest="as_of", required=True, metavar="YYYY-MM-DD", help="day to plan for")
    recommend.add_argument(
        "--avoid",
        action="append",
        default=[],
        choices=[muscle.value for muscle in MuscleGroup],
        metavar="MUSCLE",
        help="muscle group to leave out today (for example pain); repeatable. "
        f"Choices: {', '.join(muscle.value for muscle in MuscleGroup)}",
    )
    recommend.add_argument(
        "--focus",
        choices=[focus.value for focus in StrengthFocus],
        metavar="FOCUS",
        help="train this focus today instead of the automatic choice; recovery, swim overlap and --avoid "
        f"still apply. Choices: {', '.join(focus.value for focus in StrengthFocus)}",
    )
    recommend.add_argument("--json", action="store_true", help="print the full recommendation with evidence as JSON")
    daily = commands.add_parser(
        "daily",
        help="Sync yesterday-to-today Garmin activities, load metrics and recovery, then recommend the day "
        "(one command for the normal daily workflow)",
    )
    daily.add_argument(
        "--date", dest="as_of", metavar="YYYY-MM-DD", help="day to sync and plan (default: today on this computer)"
    )
    daily.add_argument(
        "--after-workout",
        action="store_true",
        help="only import activities and fill load metrics (no recovery sync, no recommendation)",
    )
    daily.add_argument(
        "--avoid",
        action="append",
        default=[],
        choices=[muscle.value for muscle in MuscleGroup],
        metavar="MUSCLE",
        help="same as recommend --avoid; repeatable",
    )
    daily.add_argument(
        "--focus",
        choices=[focus.value for focus in StrengthFocus],
        metavar="FOCUS",
        help=f"same as recommend --focus. Choices: {', '.join(focus.value for focus in StrengthFocus)}",
    )
    daily.add_argument("--json", action="store_true", help="print stage results and the recommendation as JSON")
    _add_nutrition_parser(commands)
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


def _add_nutrition_parser(commands: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    nutrition = commands.add_parser(
        "nutrition", help="Personal food catalog, structured meal logging, daily intake, targets and daily status"
    )
    nutrition_commands = nutrition.add_subparsers(dest="nutrition_command", required=True)
    food = nutrition_commands.add_parser("food", help="Personal food catalog")
    food_commands = food.add_subparsers(dest="food_command", required=True)
    add = food_commands.add_parser(
        "add",
        help="Add a food with explicitly supplied nutrition for a reference quantity (nothing is looked up or guessed)",
    )
    add.add_argument(
        "--id", dest="food_id", required=True, help="stable food ID used when logging, e.g. chicken-breast"
    )
    add.add_argument("--name", required=True, help="display name, e.g. 닭가슴살")
    _add_fact_arguments(add, "food add")
    add.add_argument("--alias", action="append", default=[], help="another unique name for this food; repeatable")
    add.add_argument("--json", action="store_true", help="print the stored food as JSON")
    fact = food_commands.add_parser("fact", help="Nutrition fact versions of an existing food")
    fact_commands = fact.add_subparsers(dest="fact_command", required=True)
    fact_add = fact_commands.add_parser(
        "add",
        help=(
            "Append a new nutrition fact version to an existing food; it replaces the current fact for meals "
            "logged from now on (older facts and already logged meals are kept unchanged)"
        ),
    )
    fact_add.add_argument("food_id", help="existing food ID, e.g. chicken-breast")
    _add_fact_arguments(fact_add, "food fact add")
    fact_add.add_argument("--json", action="store_true", help="print the stored food as JSON")
    food_list = food_commands.add_parser("list", help="List catalog foods and their active nutrition facts")
    food_list.add_argument("--json", action="store_true", help="print as JSON")
    show = food_commands.add_parser("show", help="Show one food with its full nutrition fact history")
    show.add_argument("food_id", help="food ID")
    show.add_argument("--json", action="store_true", help="print as JSON")
    log = nutrition_commands.add_parser("log", help="Record one meal made of catalog foods")
    log.add_argument("--meal", required=True, choices=[meal.value for meal in MealType], help="meal type")
    log.add_argument("--date", dest="as_of", metavar="YYYY-MM-DD", help="meal date (default: today on this computer)")
    log.add_argument("--time", dest="eaten_time", metavar="HH:MM", help="local time eaten (optional)")
    log.add_argument(
        "--item",
        nargs=3,
        action="append",
        required=True,
        metavar=("FOOD_ID", "QTY", "UNIT"),
        help="one catalog food and the amount eaten, in a unit the food has nutrition for; repeatable",
    )
    log.add_argument(
        "--additional",
        action="store_true",
        help="record another meal of the same type on the same date (otherwise refused to prevent double entry)",
    )
    log.add_argument("--json", action="store_true", help="print the recorded meal as JSON")
    meal = nutrition_commands.add_parser(
        "meal", help="Show or correct the items of a logged meal (the meal ID never changes)"
    )
    meal_commands = meal.add_subparsers(dest="meal_command", required=True)
    meal_show = meal_commands.add_parser("show", help="Show one logged meal with its items and their fact versions")
    meal_show.add_argument("meal_id", help="meal ID as printed by `nutrition log`/`nutrition day`")
    meal_show.add_argument("--json", action="store_true", help="print as JSON with exact decimal strings")
    add_item = meal_commands.add_parser(
        "add-item",
        help="Add catalog foods to a logged meal, with the foods' current nutrition facts (all or nothing)",
    )
    add_item.add_argument("meal_id", help="meal ID, e.g. 2026-10-02-breakfast-1")
    add_item.add_argument(
        "--item",
        nargs=3,
        action="append",
        required=True,
        metavar=("FOOD_ID", "QTY", "UNIT"),
        help="one catalog food and the amount eaten, as in `nutrition log`; repeatable",
    )
    add_item.add_argument("--json", action="store_true", help="print the edited meal as JSON")
    remove_item = meal_commands.add_parser(
        "remove-item", help="Remove one item from a logged meal (the last item cannot be removed)"
    )
    remove_item.add_argument("meal_id", help="meal ID, e.g. 2026-10-02-breakfast-1")
    _add_item_number_argument(remove_item, "item to remove")
    remove_item.add_argument("--json", action="store_true", help="print the edited meal as JSON")
    replace_item = meal_commands.add_parser(
        "replace-item",
        help="Replace one item of a logged meal with a new catalog item in one step (both happen or neither)",
    )
    replace_item.add_argument("meal_id", help="meal ID, e.g. 2026-10-02-breakfast-1")
    _add_item_number_argument(replace_item, "item to replace")
    replace_item.add_argument(
        "--item",
        nargs=3,
        required=True,
        metavar=("FOOD_ID", "QTY", "UNIT"),
        help="the catalog food and amount that replace it, as in `nutrition log`",
    )
    replace_item.add_argument("--json", action="store_true", help="print the edited meal as JSON")
    day = nutrition_commands.add_parser("day", help="Meals, per-meal totals and daily consumed totals for a date")
    day.add_argument("--date", dest="as_of", metavar="YYYY-MM-DD", help="date (default: today on this computer)")
    day.add_argument("--json", action="store_true", help="print as JSON with exact decimal strings")
    target = nutrition_commands.add_parser("target", help="Daily nutrition targets you set explicitly")
    target_commands = target.add_subparsers(dest="target_command", required=True)
    target_set = target_commands.add_parser(
        "set", help="Set one nutrient's daily target to an exact value or an inclusive range, or unset it"
    )
    target_set.add_argument("nutrient", choices=list(_TARGET_NUTRIENTS), help="kcal, or protein/carbs/fat in g")
    target_value = target_set.add_mutually_exclusive_group(required=True)
    target_value.add_argument("--exact", metavar="N", help="one target value, e.g. --exact 80")
    target_value.add_argument(
        "--range", nargs=2, metavar=("MIN", "MAX"), help="inclusive range, MIN <= MAX, e.g. --range 170 180"
    )
    target_value.add_argument("--unset", action="store_true", help="remove the target (unset is not 0)")
    target_set.add_argument("--json", action="store_true", help="print all targets as JSON")
    target_show = target_commands.add_parser("show", help="Show the configured daily targets")
    target_show.add_argument("--json", action="store_true", help="print as JSON")
    status = nutrition_commands.add_parser(
        "status", help="Logged intake for a date compared with the configured daily targets"
    )
    status.add_argument("--date", dest="as_of", metavar="YYYY-MM-DD", help="date (default: today on this computer)")
    status.add_argument("--json", action="store_true", help="print as JSON with exact decimal strings")


def _add_item_number_argument(parser: argparse.ArgumentParser, what: str) -> None:
    parser.add_argument(
        "--item-number",
        required=True,
        type=int,
        metavar="N",
        help=f"{what}: its number as listed by `nutrition meal show` / `nutrition day`",
    )


def _add_fact_arguments(parser: argparse.ArgumentParser, command: str) -> None:
    """The nutrition fact flags shared by `food add` and `food fact add`."""
    parser.add_argument(
        "--per",
        nargs=2,
        required=True,
        metavar=("QTY", "UNIT"),
        help=f"reference quantity the values describe, e.g. --per 100 g. Units: {_UNITS_TEXT}",
    )
    for flag, label in (
        ("--kcal", "energy in kcal"),
        ("--protein", "protein in g"),
        ("--carbs", "carbohydrate in g"),
        ("--fat", "fat in g"),
    ):
        parser.add_argument(
            flag,
            required=True,
            metavar="N|unknown",
            help=f"{label} for the reference quantity; '{_UNKNOWN_NUTRIENT}' records it as missing (never as 0)",
        )
    parser.add_argument(
        "--source",
        required=True,
        choices=[source.value for source in CATALOG_SOURCE_TYPES],
        help="where the numbers came from",
    )
    parser.add_argument(
        "--accuracy", required=True, choices=[accuracy.value for accuracy in Accuracy], help="exact or estimated"
    )
    parser.add_argument(
        "--source-ref",
        default=f"entered with muscle50 nutrition {command}",
        help="free-text reference, e.g. 'package label 2026-10'",
    )


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
    if args.command == "analytics" and args.analytics_command == "snapshot":
        return _analytics_snapshot(args.as_of, args.days, as_json=args.json)
    if args.command == "recommend":
        return _recommend(
            args.as_of,
            [MuscleGroup(item) for item in args.avoid],
            StrengthFocus(args.focus) if args.focus else None,
            as_json=args.json,
        )
    if args.command == "daily":
        return _daily(
            args.as_of,
            [MuscleGroup(item) for item in args.avoid],
            StrengthFocus(args.focus) if args.focus else None,
            after_workout=args.after_workout,
            as_json=args.json,
        )
    if args.command == "inbody" and args.inbody_command == "sync":
        return _inbody_sync(args.file, show_values=args.show_values)
    if args.command == "nutrition":
        return _nutrition(args)
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


def _analytics_snapshot(as_of_text: str, lookback_days: int, *, as_json: bool) -> int:
    # Deliberately read-only: no ensure_directories(), no migrate(), no Garmin connector.
    try:
        as_of = date.fromisoformat(validate_calendar_date(as_of_text))
    except RecoveryNormalizationError:
        print("오류: --date는 YYYY-MM-DD 형식이어야 합니다.", file=sys.stderr)
        return 1
    try:
        paths = AppPaths.from_environment()
        snapshot = BuildTrainingSnapshot(SqliteAnalyticsReader(paths.database_path)).execute(as_of, lookback_days)
        print(render_training_snapshot_json(snapshot) if as_json else render_training_snapshot(snapshot))
        return 0
    except (AnalyticsDatabaseError, ConfigurationError, InvalidSnapshotWindowError) as exc:
        print(f"오류: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\n취소되었습니다.", file=sys.stderr)
        return 130


def _recommend(as_of_text: str, avoid: list[MuscleGroup], focus: StrengthFocus | None, *, as_json: bool) -> int:
    # Deliberately read-only: no ensure_directories(), no migrate(), no Garmin connector.
    try:
        as_of = date.fromisoformat(validate_calendar_date(as_of_text))
    except RecoveryNormalizationError:
        print("오류: --date는 YYYY-MM-DD 형식이어야 합니다.", file=sys.stderr)
        return 1
    try:
        paths = AppPaths.from_environment()
        recommendation = BuildTrainingRecommendation(SqliteAnalyticsReader(paths.database_path)).execute(
            as_of, avoid, focus
        )
        # Built after the plan and from it; nutrition never changes the training recommendation.
        nutrition = _nutrition_context(paths).execute(as_of, recommendation)
        print(
            render_training_recommendation_json(recommendation, nutrition)
            if as_json
            else render_training_recommendation(recommendation, nutrition)
        )
        return 0
    except (AnalyticsDatabaseError, ConfigurationError) as exc:
        print(f"오류: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\n취소되었습니다.", file=sys.stderr)
        return 130


def _today() -> date:
    """This computer's calendar date (the same local-date convention Garmin activities use)."""
    return date.today()


def _prompt_on_stderr(prompt: str) -> str:
    # Keeps stdout to the result alone (the --json document) if Garmin asks for a fresh login.
    print(prompt, end="", file=sys.stderr, flush=True)
    return input()


def _daily(
    as_of_text: str | None,
    avoid: list[MuscleGroup],
    focus: StrengthFocus | None,
    *,
    after_workout: bool,
    as_json: bool,
) -> int:
    # Every check here runs before authentication so a bad request costs no Garmin calls.
    if after_workout and (avoid or focus is not None):
        print("오류: --after-workout은 추천을 만들지 않으므로 --focus/--avoid와 함께 쓸 수 없습니다.", file=sys.stderr)
        return 1
    if as_of_text is None:
        as_of = _today()
    else:
        try:
            as_of = date.fromisoformat(validate_calendar_date(as_of_text))
        except RecoveryNormalizationError:
            print("오류: --date는 YYYY-MM-DD 형식이어야 합니다.", file=sys.stderr)
            return 1
    mode = DailyMode.AFTER_WORKOUT if after_workout else DailyMode.FULL

    try:
        paths = AppPaths.from_environment()
        paths.ensure_directories()
        activity_repository = ActivityRepository(paths.database_path)
        activity_repository.migrate()
        recovery_repository = DailyRecoveryRepository(paths.database_path)
        recovery_repository.migrate()
        raw_store = RawStore(paths.raw_dir, paths.root, paths.tmp_dir)
        recovery_raw_store = RecoveryRawStore(paths.recovery_raw_dir, paths.root, paths.tmp_dir)
        use_case = RunDailySync(
            connect=lambda: PythonGarminConnector.authenticate(paths.auth_dir, input_fn=_prompt_on_stderr),
            activity_ingest=lambda connector: IngestGarminActivityRange(connector, activity_repository, raw_store),
            load_metric_backfill=BackfillActivityLoadMetrics(activity_repository, raw_store),
            recovery_sync=lambda connector: SyncGarminRecovery(connector, recovery_repository, recovery_raw_store),
            # A read-only reader built exactly as `recommend` builds it; it reads after the sync stages write.
            recommender=BuildTrainingRecommendation(SqliteAnalyticsReader(paths.database_path)),
            nutrition=_nutrition_context(paths),
        )
        print(
            f"muscle50 daily {as_of.isoformat()}: syncing {daily_sync_start(as_of).isoformat()}..{as_of.isoformat()}",
            file=sys.stderr,
        )
        result = use_case.execute(as_of, mode, avoid, focus)
        print(render_daily_sync_json(result) if as_json else render_daily_sync(result))
        return 0 if result.ok else 1
    except ConfigurationError as exc:
        print(f"오류: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\n취소되었습니다.", file=sys.stderr)
        return 130


def _nutrition_context(paths: AppPaths) -> BuildNutritionContext:
    """`nutrition status` for the plan's date, read-only: no migration, no database or config file created."""
    status = ShowDailyNutritionStatus(
        SqliteNutritionReader(paths.database_path), JsonNutritionTargetRepository(paths.nutrition_targets_path)
    )
    return BuildNutritionContext(status, _local_timezone)


def _local_timezone(day: date) -> tzinfo:
    """This computer's UTC offset on ``day`` as a fixed offset (no IANA zone lookup)."""
    offset = datetime.combine(day, time(12)).astimezone().utcoffset()
    return timezone(offset) if offset is not None else UTC


def _nutrition(args: argparse.Namespace) -> int:
    try:
        paths = AppPaths.from_environment()
        paths.ensure_directories()
        foods = SqliteFoodNutritionRepository(paths.database_path)
        foods.migrate()
        meals = SqliteMealRepository(paths.database_path)
        if args.nutrition_command == "food" and args.food_command == "add":
            profile = AddFood(foods, clock=lambda: datetime.now().astimezone()).execute(_new_food(args))
            print(
                render_food_json(profile) if args.json else f"Added food {profile.profile_id}.\n{render_food(profile)}"
            )
            return 0
        if args.nutrition_command == "food" and args.food_command == "fact" and args.fact_command == "add":
            added = AddFoodFact(foods, clock=lambda: datetime.now().astimezone()).execute(_new_food_fact(args))
            print(
                render_food_json(added.profile)
                if args.json
                else (
                    f"Added fact {added.fact.fact_id} to {added.profile.profile_id}; it replaces "
                    f"{added.superseded_fact_id} for meals logged from now on.\n"
                    "Meals already logged keep the facts they were logged with.\n"
                    f"{render_food(added.profile)}"
                )
            )
            return 0
        if args.nutrition_command == "food" and args.food_command == "list":
            profiles = ListFoods(foods).execute()
            print(render_food_list_json(profiles) if args.json else render_food_list(profiles))
            return 0
        if args.nutrition_command == "food" and args.food_command == "show":
            profile = ShowFood(foods).execute(args.food_id)
            print(render_food_json(profile) if args.json else render_food(profile))
            return 0
        if args.nutrition_command == "log":
            day = _nutrition_date(args.as_of)
            meal = LogMeal(meals, foods).execute(
                day,
                MealType(args.meal),
                tuple(_meal_entry(index, raw) for index, raw in enumerate(args.item, start=1)),
                timezone=_local_timezone(day),
                eaten_time=_eaten_time(args.eaten_time),
                additional=args.additional,
            )
            print(render_logged_meal_json(meal) if args.json else render_logged_meal(meal))
            return 0
        if args.nutrition_command == "meal":
            return _nutrition_meal(args, meals, foods)
        if args.nutrition_command == "day":
            day = _nutrition_date(args.as_of)
            zone = _local_timezone(day)
            intake = ShowDailyIntake(meals).execute(day, zone, timezone_name=offset_name(zone, day))
            print(render_daily_intake_json(intake) if args.json else render_daily_intake(intake))
            return 0
        targets = JsonNutritionTargetRepository(paths.nutrition_targets_path)
        if args.nutrition_command == "target" and args.target_command == "set":
            nutrient = _TARGET_NUTRIENTS[args.nutrient]
            stored = SetNutritionTarget(targets).execute(nutrient, _target(args))
            if args.json:
                print(render_targets_json(stored))
            else:
                state = "unset" if stored.get(nutrient) is None else "set"
                print(f"{args.nutrient} target {state}.\n{render_targets(stored)}")
            return 0
        if args.nutrition_command == "target" and args.target_command == "show":
            configured = ShowNutritionTargets(targets).execute()
            print(render_targets_json(configured) if args.json else render_targets(configured))
            return 0
        if args.nutrition_command == "status":
            day = _nutrition_date(args.as_of)
            zone = _local_timezone(day)
            status = ShowDailyNutritionStatus(meals, targets).execute(day, zone, timezone_name=offset_name(zone, day))
            print(render_nutrition_status_json(status) if args.json else render_nutrition_status(status))
            return 0
        return 2
    except (ConfigurationError, NutritionLoggingError, NutritionTargetError) as exc:
        print(f"오류: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\n취소되었습니다.", file=sys.stderr)
        return 130


def _nutrition_meal(args: argparse.Namespace, meals: SqliteMealRepository, foods: SqliteFoodNutritionRepository) -> int:
    if args.meal_command == "show":
        intake = ShowMeal(meals).execute(args.meal_id)
        print(render_logged_meal_json(intake) if args.json else render_meal(intake))
        return 0
    if args.meal_command == "add-item":
        entries = tuple(_meal_entry(index, raw) for index, raw in enumerate(args.item, start=1))
        intake = AddMealItems(meals, foods).execute(args.meal_id, entries)
        added = intake.meal.items[-len(entries) :]
        word = "item" if len(added) == 1 else "items"
        headline = f"Added {word} {', '.join(str(item.sequence) for item in added)} to meal {intake.meal.meal_id}."
    elif args.meal_command == "remove-item":
        intake = RemoveMealItem(meals, clock=lambda: datetime.now().astimezone()).execute(
            args.meal_id, args.item_number
        )
        headline = f"Removed item {args.item_number} from meal {intake.meal.meal_id}."
    elif args.meal_command == "replace-item":
        intake = ReplaceMealItem(meals, foods, clock=lambda: datetime.now().astimezone()).execute(
            args.meal_id, args.item_number, _meal_entry(1, args.item)
        )
        new_number = intake.meal.items[-1].sequence
        headline = f"Replaced item {args.item_number} of meal {intake.meal.meal_id} with item {new_number}."
    else:
        return 2
    print(render_logged_meal_json(intake) if args.json else render_edited_meal(intake, headline))
    return 0


def _nutrition_date(text: str | None) -> date:
    if text is None:
        return _today()
    try:
        return date.fromisoformat(validate_calendar_date(text))
    except RecoveryNormalizationError as exc:
        raise NutritionLoggingError("--date는 YYYY-MM-DD 형식이어야 합니다.") from exc


def _eaten_time(text: str | None) -> time | None:
    if text is None:
        return None
    try:
        if _TIME_PATTERN.fullmatch(text) is None:
            raise ValueError(text)
        return time.fromisoformat(text)
    except ValueError as exc:
        raise NutritionLoggingError(f"--time must be HH:MM (24-hour), got {text!r}") from exc


def _decimal_argument(text: str, what: str) -> Decimal:
    try:
        return decimal_from_text(text)
    except ValueError as exc:
        raise NutritionLoggingError(
            f"{what} must be a plain non-negative number like 200 or 1.5, got {text!r}"
        ) from exc


def _positive_quantity(text: str, what: str) -> Decimal:
    value = _decimal_argument(text, what)
    if value == 0:
        raise NutritionLoggingError(f"{what} must be greater than 0")
    return value


def _unit(text: str, what: str) -> QuantityUnit:
    try:
        return QuantityUnit(text)
    except ValueError as exc:
        raise NutritionLoggingError(f"{what} unit {text!r} is not supported; use one of: {_UNITS_TEXT}") from exc


def _nutrient(text: str, flag: str) -> Decimal | None:
    return None if text == _UNKNOWN_NUTRIENT else _decimal_argument(text, flag)


def _new_food(args: argparse.Namespace) -> NewFood:
    fact = _new_food_fact(args)
    return NewFood(
        food_id=fact.food_id,
        name=args.name,
        basis_quantity=fact.basis_quantity,
        basis_unit=fact.basis_unit,
        values=fact.values,
        source_type=fact.source_type,
        accuracy=fact.accuracy,
        source_reference=fact.source_reference,
        aliases=tuple(args.alias),
    )


def _new_food_fact(args: argparse.Namespace) -> NewFoodFact:
    quantity_text, unit_text = args.per
    return NewFoodFact(
        food_id=args.food_id,
        basis_quantity=_positive_quantity(quantity_text, "--per quantity"),
        basis_unit=_unit(unit_text, "--per"),
        values=NutritionValue(
            calories_kcal=_nutrient(args.kcal, "--kcal"),
            protein_g=_nutrient(args.protein, "--protein"),
            carbohydrate_g=_nutrient(args.carbs, "--carbs"),
            fat_g=_nutrient(args.fat, "--fat"),
        ),
        source_type=next(source for source in CATALOG_SOURCE_TYPES if source.value == args.source),
        accuracy=Accuracy(args.accuracy),
        source_reference=args.source_ref,
    )


def _target(args: argparse.Namespace) -> NutrientTarget | None:
    if args.unset:
        return None
    if args.range is not None:
        minimum_text, maximum_text = args.range
        return RangeTarget(_target_value(minimum_text, "--range MIN"), _target_value(maximum_text, "--range MAX"))
    return ExactTarget(_target_value(args.exact, "--exact"))


def _target_value(text: str, what: str) -> Decimal:
    value = _decimal_argument(text, what)
    if value == 0:
        raise NutritionTargetError(f"{what} must be greater than 0 (to remove a target use --unset)")
    return value


def _meal_entry(index: int, raw: list[str]) -> MealEntryItem:
    food_id, quantity_text, unit_text = raw
    what = f"--item {index}"
    return MealEntryItem(food_id, _positive_quantity(quantity_text, f"{what} quantity"), _unit(unit_text, what))


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
