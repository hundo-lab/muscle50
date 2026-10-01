"""Bring one day's Garmin data up to date and plan it by composing the existing use cases.

Stages, in order:

1. ``garmin_login``: one authenticated connector shared by every Garmin stage.
2. ``activities``: ``IngestGarminActivityRange`` over D-1..D.
3. ``load_metrics``: ``BackfillActivityLoadMetrics`` (RAW-only, idempotent).
4. ``recovery``: ``SyncGarminRecovery.execute_range`` over D-1..D (full mode only).
5. ``recommendation``: ``BuildTrainingRecommendation`` for D (full mode only).

No Garmin normalization, persistence, recovery or recommendation rule lives here; each stage
is the existing use case, so its idempotency and RAW snapshot semantics are unchanged.

Failure policy: the three sync stages are independent, so one failing stage does not stop the
others from preserving valid work. A stage that cannot run because its input is missing is
``not_run``. The recommendation is built only when every earlier stage is ``ok``; otherwise it
is ``not_run`` and nothing is fabricated in its place. Only the known per-stage error families
are caught: anything else (for example a local data-integrity error that the range ingest
deliberately lets propagate) aborts the whole command.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import date, timedelta
from enum import StrEnum
from typing import Protocol

from muscle50.application.backfill_activity_load_metrics import ActivityLoadBackfillResult
from muscle50.application.ingest_activity import ActivitySyncError
from muscle50.application.ingest_activity_range import RangeIngestResult
from muscle50.application.sync_garmin_recovery import RecoveryRangeSyncResult
from muscle50.domain.exercise_taxonomy import MuscleGroup
from muscle50.domain.normalization import NormalizationError
from muscle50.domain.recovery_normalization import RecoveryNormalizationError
from muscle50.domain.strength_recommendation import StrengthFocus
from muscle50.domain.swim_normalization import SwimNormalizationError
from muscle50.domain.training_recommendation import TrainingRecommendation
from muscle50.infrastructure.garmin.client import GarminConnector, GarminConnectorError, GarminRecoveryConnector
from muscle50.infrastructure.raw_store import RawStoreError
from muscle50.infrastructure.sqlite.analytics_reader import AnalyticsDatabaseError

STAGE_GARMIN_LOGIN = "garmin_login"
STAGE_ACTIVITIES = "activities"
STAGE_LOAD_METRICS = "load_metrics"
STAGE_RECOVERY = "recovery"
STAGE_RECOMMENDATION = "recommendation"
# Stages after-workout mode runs; the rest are skipped in that mode.
_IMPORT_STAGES = frozenset({STAGE_ACTIVITIES, STAGE_LOAD_METRICS})

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
    """First day of the activity and recovery sync range (D-1)."""
    stages: tuple[StageReport, ...]
    activities: RangeIngestResult | None
    load_metrics: ActivityLoadBackfillResult | None
    recovery: RecoveryRangeSyncResult | None
    recommendation: TrainingRecommendation | None

    @property
    def failed_stages(self) -> tuple[str, ...]:
        return tuple(item.stage for item in self.stages if item.status is StageStatus.FAILED)

    @property
    def ok(self) -> bool:
        return not any(item.status in (StageStatus.FAILED, StageStatus.NOT_RUN) for item in self.stages)


def daily_sync_start(as_of: date) -> date:
    """D-1: yesterday's late activities and yesterday's end-of-day recovery belong to today's plan."""
    return as_of - timedelta(days=1)


class RunDailySync:
    def __init__(
        self,
        connect: Callable[[], DailyGarminConnector],
        activity_ingest: Callable[[DailyGarminConnector], ActivityRangeIngest],
        load_metric_backfill: LoadMetricBackfill,
        recovery_sync: Callable[[DailyGarminConnector], RecoveryRangeSync],
        recommender: TrainingRecommender,
    ):
        self._connect = connect
        self._activity_ingest = activity_ingest
        self._load_metric_backfill = load_metric_backfill
        self._recovery_sync = recovery_sync
        self._recommender = recommender

    def execute(
        self,
        as_of: date,
        mode: DailyMode = DailyMode.FULL,
        avoid_muscles: Iterable[MuscleGroup] = (),
        requested_focus: StrengthFocus | None = None,
    ) -> DailySyncResult:
        start = daily_sync_start(as_of)
        full = mode is DailyMode.FULL
        stages: list[StageReport] = []

        try:
            connector = self._connect()
        except GarminConnectorError as exc:
            stages.append(StageReport(STAGE_GARMIN_LOGIN, StageStatus.FAILED, str(exc)))
            stages.extend(
                StageReport(stage, StageStatus.NOT_RUN if full or stage in _IMPORT_STAGES else StageStatus.SKIPPED)
                for stage in (STAGE_ACTIVITIES, STAGE_LOAD_METRICS, STAGE_RECOVERY, STAGE_RECOMMENDATION)
            )
            return DailySyncResult(as_of, mode, start, tuple(stages), None, None, None, None)
        stages.append(StageReport(STAGE_GARMIN_LOGIN, StageStatus.OK))

        activities, report = self._activities(connector, start, as_of)
        stages.append(report)
        load_metrics, report = self._load_metrics(activities)
        stages.append(report)

        recovery: RecoveryRangeSyncResult | None = None
        if full:
            recovery, report = self._recovery(connector, start, as_of)
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

        return DailySyncResult(as_of, mode, start, tuple(stages), activities, load_metrics, recovery, recommendation)

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
        unusable = set(result.missing_raw) | set(result.unreadable_raw)
        new_gaps = sorted(imported & unusable)
        if new_gaps:
            return result, StageReport(
                STAGE_LOAD_METRICS,
                StageStatus.FAILED,
                f"no readable RAW summary for activities imported in this run: {', '.join(new_gaps)}",
            )
        warnings: list[str] = []
        older_gaps = sorted(unusable - imported)
        if older_gaps:
            warnings.append(
                f"{len(older_gaps)} previously stored activities have no readable RAW summary "
                f"(not from this run): {', '.join(older_gaps)}"
            )
        new_malformed = sorted({item.source_activity_id for item in result.malformed_values} & imported)
        if new_malformed:
            warnings.append(
                f"malformed load-metric values in activities imported in this run: {', '.join(new_malformed)}"
            )
        return result, StageReport(STAGE_LOAD_METRICS, StageStatus.OK, warnings=tuple(warnings))

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
