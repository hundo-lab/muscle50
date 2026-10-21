"""Bring one day's Garmin data up to date and plan it by composing the existing use cases.

Stages, in order:

1. ``garmin_login``: one authenticated connector shared by every Garmin stage.
2. ``activities``: ``IngestGarminActivityRange`` over the sync range.
3. ``load_metrics``: ``BackfillActivityLoadMetrics`` (RAW-only, idempotent).
4. ``recovery``: ``SyncGarminRecovery.execute_range`` over the sync range (full and sync modes).
5. ``recommendation``: ``BuildTrainingRecommendation`` for D (full mode only), plus the
   optional nutrition context for D from ``BuildNutritionContext`` (not a stage: it never
   changes the plan or the outcome, and unreadable nutrition is reported, not failed).

The sync range ends on D. It starts on D-1 by default, on the catch-up start when `daily`
passes a ``DailyCatchUp`` plan (Daily Catch-up v1: between D-7 and D-1), or on an explicit
``sync_from`` (`garmin sync --from/--to`, ``DailyMode.SYNC``).

No Garmin normalization, persistence, recovery or recommendation rule lives here; each stage
is the existing use case, so its idempotency and RAW snapshot semantics are unchanged.

Sync coverage (optional ``coverage`` recorder) is written right after the activities stage and
right after the recovery stage, so before the recommendation reads the database. A failed
coverage write is a warning on that stage; it never changes the stage status.

Failure policy: the three sync stages are independent, so one failing stage does not stop the
others from preserving valid work. A stage that cannot run because its input is missing is
``not_run``. The recommendation is built only when every earlier stage is ``ok``; otherwise it
is ``not_run`` and nothing is fabricated in its place. Only the known per-stage error families
are caught: anything else (for example a local data-integrity error that the range ingest
deliberately lets propagate) aborts the whole command.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, replace
from datetime import date, timedelta
from enum import StrEnum
from typing import Protocol

from muscle50.application.backfill_activity_load_metrics import ActivityLoadBackfillResult
from muscle50.application.imported_load_metrics import check_imported_load_metrics
from muscle50.application.ingest_activity import ActivitySyncError
from muscle50.application.ingest_activity_range import RangeIngestResult
from muscle50.application.nutrition_recommendation import NutritionContext
from muscle50.application.sync_coverage import CoverageRecordResult, coverage_not_recorded_message
from muscle50.application.sync_garmin_recovery import RecoveryRangeOutcome, RecoveryRangeSyncResult
from muscle50.domain.exercise_taxonomy import MuscleGroup
from muscle50.domain.normalization import NormalizationError
from muscle50.domain.recovery_normalization import RecoveryNormalizationError
from muscle50.domain.strength_recommendation import StrengthFocus
from muscle50.domain.swim_normalization import SwimNormalizationError
from muscle50.domain.sync_catch_up import DailyCatchUp
from muscle50.domain.training_recommendation import TrainingRecommendation
from muscle50.infrastructure.garmin.client import GarminConnector, GarminConnectorError, GarminRecoveryConnector
from muscle50.infrastructure.raw_store import RawStoreError
from muscle50.infrastructure.sqlite.analytics_reader import AnalyticsDatabaseError

STAGE_GARMIN_LOGIN = "garmin_login"
STAGE_ACTIVITIES = "activities"
STAGE_LOAD_METRICS = "load_metrics"
STAGE_RECOVERY = "recovery"
STAGE_RECOMMENDATION = "recommendation"

# Errors a sync stage reports as its own failure; the same families the standalone commands catch.
_SYNC_STAGE_ERRORS = (
    ActivitySyncError,
    GarminConnectorError,
    NormalizationError,
    RawStoreError,
    RecoveryNormalizationError,
    SwimNormalizationError,
    sqlite3.Error,
)
_RECOMMENDATION_ERRORS = (AnalyticsDatabaseError, sqlite3.Error)


class DailyMode(StrEnum):
    FULL = "full"
    """Activities, load metrics, recovery, then today's recommendation."""
    AFTER_WORKOUT = "after_workout"
    """Activities and load metrics only: no recovery sync, no recommendation."""
    SYNC = "sync"
    """`garmin sync`: activities, load metrics and recovery over an explicit range; no recommendation."""


class StageStatus(StrEnum):
    OK = "ok"
    FAILED = "failed"
    NOT_RUN = "not_run"
    """Could not run: an earlier stage it depends on failed."""
    SKIPPED = "skipped"
    """Not part of the requested mode."""


class DailyGarminConnector(GarminConnector, GarminRecoveryConnector, Protocol):
    """One authenticated Garmin session serving both activity and recovery stages."""


class ActivityRangeIngest(Protocol):
    def execute(self, from_date: date, to_date: date) -> RangeIngestResult: ...


class LoadMetricBackfill(Protocol):
    def execute(self, *, dry_run: bool = False) -> ActivityLoadBackfillResult: ...


class RecoveryRangeSync(Protocol):
    def execute_range(self, from_date: date, to_date: date) -> RecoveryRangeSyncResult: ...


class TrainingRecommender(Protocol):
    def execute(
        self,
        as_of: date,
        avoid_muscles: Iterable[MuscleGroup] = (),
        requested_focus: StrengthFocus | None = None,
    ) -> TrainingRecommendation: ...


class NutritionContextBuilder(Protocol):
    def execute(self, as_of: date, training: TrainingRecommendation) -> NutritionContext: ...


class SyncCoverageRecorder(Protocol):
    def activities(self, result: RangeIngestResult) -> CoverageRecordResult: ...

    def recovery(self, outcomes: Sequence[RecoveryRangeOutcome]) -> CoverageRecordResult: ...


@dataclass(frozen=True)
class StageReport:
    stage: str
    status: StageStatus
    error: str | None = None
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class DailySyncResult:
    as_of: date
    mode: DailyMode
    sync_from: date
    """First day of the activity and recovery sync range (D-1 unless caught up or given)."""
    stages: tuple[StageReport, ...]
    activities: RangeIngestResult | None
    load_metrics: ActivityLoadBackfillResult | None
    recovery: RecoveryRangeSyncResult | None
    recommendation: TrainingRecommendation | None
    nutrition: NutritionContext | None = None
    """Nutrition context for the recommended date; only present with a recommendation."""
    catch_up: DailyCatchUp | None = None
    """Daily Catch-up v1: the plan, only when the range starts before D-1 (otherwise None)."""

    @property
    def failed_stages(self) -> tuple[str, ...]:
        return tuple(item.stage for item in self.stages if item.status is StageStatus.FAILED)

    @property
    def ok(self) -> bool:
        return not any(item.status in (StageStatus.FAILED, StageStatus.NOT_RUN) for item in self.stages)


def daily_sync_start(as_of: date) -> date:
    """D-1: yesterday's late activities and yesterday's end-of-day recovery belong to today's plan."""
    return as_of - timedelta(days=1)


def _sync_start(as_of: date, mode: DailyMode, sync_from: date | None, catch_up: DailyCatchUp | None) -> date:
    if sync_from is not None and catch_up is not None:
        raise ValueError("pass either sync_from or catch_up, not both")
    if mode is DailyMode.SYNC and sync_from is None:
        raise ValueError("sync mode needs an explicit sync_from")
    if sync_from is not None:
        if sync_from > as_of:
            raise ValueError("sync_from is after the last day of the range")
        return sync_from
    if catch_up is not None:
        if catch_up.as_of != as_of:
            raise ValueError("the catch-up plan is for another day")
        return catch_up.start
    return daily_sync_start(as_of)


class RunDailySync:
    def __init__(
        self,
        connect: Callable[[], DailyGarminConnector],
        activity_ingest: Callable[[DailyGarminConnector], ActivityRangeIngest],
        load_metric_backfill: LoadMetricBackfill,
        recovery_sync: Callable[[DailyGarminConnector], RecoveryRangeSync],
        recommender: TrainingRecommender,
        nutrition: NutritionContextBuilder | None = None,
        coverage: SyncCoverageRecorder | None = None,
    ):
        self._connect = connect
        self._activity_ingest = activity_ingest
        self._load_metric_backfill = load_metric_backfill
        self._recovery_sync = recovery_sync
        self._recommender = recommender
        self._nutrition = nutrition
        self._coverage = coverage

    def execute(
        self,
        as_of: date,
        mode: DailyMode = DailyMode.FULL,
        avoid_muscles: Iterable[MuscleGroup] = (),
        requested_focus: StrengthFocus | None = None,
        *,
        sync_from: date | None = None,
        catch_up: DailyCatchUp | None = None,
    ) -> DailySyncResult:
        start = _sync_start(as_of, mode, sync_from, catch_up)
        reported = catch_up if catch_up is not None and catch_up.reported else None
        syncs_recovery = mode in (DailyMode.FULL, DailyMode.SYNC)
        full = mode is DailyMode.FULL
        stages: list[StageReport] = []

        try:
            connector = self._connect()
        except GarminConnectorError as exc:
            stages.append(StageReport(STAGE_GARMIN_LOGIN, StageStatus.FAILED, str(exc)))
            runs = {STAGE_RECOVERY: syncs_recovery, STAGE_RECOMMENDATION: full}
            stages.extend(
                StageReport(stage, StageStatus.NOT_RUN if runs.get(stage, True) else StageStatus.SKIPPED)
                for stage in (STAGE_ACTIVITIES, STAGE_LOAD_METRICS, STAGE_RECOVERY, STAGE_RECOMMENDATION)
            )
            return DailySyncResult(as_of, mode, start, tuple(stages), None, None, None, None, catch_up=reported)
        stages.append(StageReport(STAGE_GARMIN_LOGIN, StageStatus.OK))

        activities, report = self._activities(connector, start, as_of)
        if activities is not None and self._coverage is not None:
            report = _with_coverage_warning(report, self._coverage.activities(activities))
        stages.append(report)
        load_metrics, report = self._load_metrics(activities)
        stages.append(report)

        recovery: RecoveryRangeSyncResult | None = None
        if syncs_recovery:
            recovery, report = self._recovery(connector, start, as_of)
            if recovery is not None and self._coverage is not None:
                report = _with_coverage_warning(report, self._coverage.recovery(recovery.outcomes))
            stages.append(report)
        else:
            stages.append(StageReport(STAGE_RECOVERY, StageStatus.SKIPPED))

        recommendation: TrainingRecommendation | None = None
        if not full:
            stages.append(StageReport(STAGE_RECOMMENDATION, StageStatus.SKIPPED))
        elif any(item.status is not StageStatus.OK for item in stages):
            # Never plan on data a failed stage may have left incomplete.
            stages.append(StageReport(STAGE_RECOMMENDATION, StageStatus.NOT_RUN))
        else:
            try:
                recommendation = self._recommender.execute(as_of, avoid_muscles, requested_focus)
            except _RECOMMENDATION_ERRORS as exc:
                stages.append(StageReport(STAGE_RECOMMENDATION, StageStatus.FAILED, str(exc)))
            else:
                stages.append(StageReport(STAGE_RECOMMENDATION, StageStatus.OK))

        nutrition: NutritionContext | None = None
        if recommendation is not None and self._nutrition is not None:
            nutrition = self._nutrition.execute(as_of, recommendation)
        return DailySyncResult(
            as_of,
            mode,
            start,
            tuple(stages),
            activities,
            load_metrics,
            recovery,
            recommendation,
            nutrition,
            catch_up=reported,
        )

    def _activities(
        self, connector: DailyGarminConnector, start: date, as_of: date
    ) -> tuple[RangeIngestResult | None, StageReport]:
        try:
            result = self._activity_ingest(connector).execute(start, as_of)
        except _SYNC_STAGE_ERRORS as exc:
            return None, StageReport(STAGE_ACTIVITIES, StageStatus.FAILED, str(exc))
        problems = [
            f"activity {item.source_activity_id} ({item.source_type_key}) failed: {item.error}"
            for item in result.outcomes
            if item.status == "failed"
        ]
        if result.page_limit_reached:
            problems.append("activity list page limit reached; the range may be incomplete")
        if problems:
            return result, StageReport(STAGE_ACTIVITIES, StageStatus.FAILED, "; ".join(problems))
        # An activity stored despite an optional endpoint failure (for example no exercise sets) is skipped
        # by later range runs, so the warning names the explicit repair.
        warnings = [
            f"activity {item.source_activity_id} ({item.source_type_key}) imported with Garmin warning: {warning}; "
            f"to re-fetch it: muscle50 garmin refresh {item.source_activity_id}"
            for item in result.outcomes
            for warning in item.warnings
        ]
        if result.undated_count:
            warnings.append(
                f"{result.undated_count} listed activities had no readable start date or ID and were not imported"
            )
        return result, StageReport(STAGE_ACTIVITIES, StageStatus.OK, warnings=tuple(warnings))

    def _load_metrics(
        self, activities: RangeIngestResult | None
    ) -> tuple[ActivityLoadBackfillResult | None, StageReport]:
        if activities is None:
            return None, StageReport(STAGE_LOAD_METRICS, StageStatus.NOT_RUN)
        try:
            result = self._load_metric_backfill.execute()
        except _SYNC_STAGE_ERRORS as exc:
            return None, StageReport(STAGE_LOAD_METRICS, StageStatus.FAILED, str(exc))
        imported = {item.source_activity_id for item in activities.outcomes if item.status == "inserted"}
        check = check_imported_load_metrics(result, imported)
        if check.error is not None:
            return result, StageReport(STAGE_LOAD_METRICS, StageStatus.FAILED, check.error)
        return result, StageReport(STAGE_LOAD_METRICS, StageStatus.OK, warnings=check.warnings)

    def _recovery(
        self, connector: DailyGarminConnector, start: date, as_of: date
    ) -> tuple[RecoveryRangeSyncResult | None, StageReport]:
        try:
            result = self._recovery_sync(connector).execute_range(start, as_of)
        except _SYNC_STAGE_ERRORS as exc:
            return None, StageReport(STAGE_RECOVERY, StageStatus.FAILED, str(exc))
        # Per-endpoint warnings stay warnings, exactly as in `garmin recovery --from/--to`.
        warnings = tuple(
            f"{item.calendar_date}: {warning}"
            for item in result.outcomes
            if item.result is not None
            for warning in item.result.warnings
        )
        if not result.complete:
            problems = [
                f"{item.calendar_date} {item.status}" + (f": {item.error}" if item.error else "")
                for item in result.outcomes
                if item.status in ("failed", "not_attempted")
            ]
            if result.aborted_reason:
                problems.append(f"aborted: {result.aborted_reason}")
            return result, StageReport(STAGE_RECOVERY, StageStatus.FAILED, "; ".join(problems), warnings)
        return result, StageReport(STAGE_RECOVERY, StageStatus.OK, warnings=warnings)


def _with_coverage_warning(report: StageReport, recorded: CoverageRecordResult) -> StageReport:
    if recorded.error is None:
        return report
    return replace(report, warnings=(*report.warnings, coverage_not_recorded_message(recorded.error)))
