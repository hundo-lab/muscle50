"""Plan where `daily` starts (Daily Catch-up v1) from the recorded sync coverage.

Read-only: the coverage source is the `mode=ro` analytics reader. `AnalyticsDatabaseError`
propagates; `daily` then falls back to D-1 and the Telegram LLM hint shows no gap.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, timedelta, tzinfo

from muscle50.application.sync_coverage import SyncCoverageSource
from muscle50.domain.sync_catch_up import CATCH_UP_LOOKBACK_DAYS, DailyCatchUp, plan_catch_up


class PlanDailyCatchUp:
    def __init__(self, source: SyncCoverageSource) -> None:
        self._source = source

    def execute(self, as_of: date, *, activities_only: bool, local_timezone: Callable[[date], tzinfo]) -> DailyCatchUp:
        data = self._source.load_sync_coverage(
            as_of - timedelta(days=CATCH_UP_LOOKBACK_DAYS), as_of - timedelta(days=1)
        )
        return plan_catch_up(as_of, data.records, activities_only=activities_only, local_timezone=local_timezone)
