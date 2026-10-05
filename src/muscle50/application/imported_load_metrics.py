"""Fill activity-load metrics after an ingest, with `daily`'s load_metrics judgement.

`check_imported_load_metrics` is the single rule shared by `daily`'s load_metrics stage and
`garmin latest`/`garmin activities`: a stored-this-run activity without a readable initial
RAW summary is a failure; an older activity's RAW gap and a malformed value in an activity
stored this run are warnings. The fill itself is the unchanged RAW-only, idempotent
`BackfillActivityLoadMetrics`; nothing here contacts Garmin or writes RAW/activity rows.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Set as AbstractSet
from dataclasses import dataclass
from typing import Protocol

from muscle50.application.backfill_activity_load_metrics import ActivityLoadBackfillResult
from muscle50.infrastructure.raw_store import RawStoreError


@dataclass(frozen=True)
class LoadMetricCheck:
    error: str | None
    """The failure text, or None; a failure carries no warnings."""
    warnings: tuple[str, ...] = ()


def check_imported_load_metrics(result: ActivityLoadBackfillResult, imported: AbstractSet[str]) -> LoadMetricCheck:
    """Judge a backfill result against the activity IDs newly stored by this run."""
    unusable = set(result.missing_raw) | set(result.unreadable_raw)
    new_gaps = sorted(imported & unusable)
    if new_gaps:
        return LoadMetricCheck(f"no readable RAW summary for activities imported in this run: {', '.join(new_gaps)}")
    warnings: list[str] = []
    older_gaps = sorted(unusable - imported)
    if older_gaps:
        warnings.append(
            f"{len(older_gaps)} previously stored activities have no readable RAW summary "
            f"(not from this run): {', '.join(older_gaps)}"
        )
    new_malformed = sorted({item.source_activity_id for item in result.malformed_values} & imported)
    if new_malformed:
        warnings.append(f"malformed load-metric values in activities imported in this run: {', '.join(new_malformed)}")
    return LoadMetricCheck(None, tuple(warnings))


class LoadMetricBackfill(Protocol):
    def execute(self, *, dry_run: bool = False) -> ActivityLoadBackfillResult: ...


@dataclass(frozen=True)
class ImportedLoadMetricsResult:
    backfill: ActivityLoadBackfillResult | None
    """None only when the backfill itself raised."""
    error: str | None
    warnings: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return self.error is None


class FillImportedLoadMetrics:
    """`daily`'s load_metrics stage for the single-purpose ingest commands."""

    def __init__(self, backfill: LoadMetricBackfill) -> None:
        self._backfill = backfill

    def execute(self, imported: AbstractSet[str]) -> ImportedLoadMetricsResult:
        try:
            result = self._backfill.execute()
        except (RawStoreError, sqlite3.Error) as exc:
            return ImportedLoadMetricsResult(None, str(exc))
        check = check_imported_load_metrics(result, imported)
        return ImportedLoadMetricsResult(result, check.error, check.warnings)
