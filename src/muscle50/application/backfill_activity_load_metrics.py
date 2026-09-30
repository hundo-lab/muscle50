"""Backfill canonical activity-load metrics from already-preserved Garmin RAW summaries.

This use case has no Garmin connector dependency, so it cannot call the Garmin API or the
refresh path. It reads each stored activity's initial flat ``summary.json`` and writes only
the ``ACTIVITY_LOAD_METRIC_KEYS`` rows of ``activity_metrics``. RAW files, parent activity
rows, strength sets, swim rows, and every other metric are never written.
"""

from __future__ import annotations

from dataclasses import dataclass

from muscle50.domain.activity_load import (
    ACTIVITY_LOAD_METRIC_KEYS,
    ActivityLoadValueIssue,
    extract_activity_load_metrics,
)
from muscle50.infrastructure.raw_store import RawStore, RawStoreError
from muscle50.infrastructure.sqlite.database import ActivityRepository


@dataclass(frozen=True)
class ActivityLoadValueReport:
    source_activity_id: str
    issue: ActivityLoadValueIssue


@dataclass(frozen=True)
class ActivityLoadBackfillResult:
    dry_run: bool
    activities_examined: int
    raw_summaries_found: int
    activities_changed: int
    metrics_inserted: int
    metrics_updated: int
    metrics_unchanged: int
    missing_raw: tuple[str, ...]
    unreadable_raw: tuple[str, ...]
    malformed_values: tuple[ActivityLoadValueReport, ...]
    skipped_values: tuple[ActivityLoadValueReport, ...]

    @property
    def canonical_changes(self) -> int:
        return self.metrics_inserted + self.metrics_updated


class BackfillActivityLoadMetrics:
    def __init__(self, repository: ActivityRepository, raw_store: RawStore):
        self._repository = repository
        self._raw_store = raw_store

    def execute(self, *, dry_run: bool = False) -> ActivityLoadBackfillResult:
        activity_ids = self._repository.list_source_activity_ids()
        raw_found = changed = inserted = updated = unchanged = 0
        missing_raw: list[str] = []
        unreadable_raw: list[str] = []
        malformed: list[ActivityLoadValueReport] = []
        skipped: list[ActivityLoadValueReport] = []

        for activity_id in activity_ids:
            try:
                summary = self._raw_store.load_initial_summary(activity_id)
            except RawStoreError:
                unreadable_raw.append(activity_id)
                continue
            if summary is None:
                missing_raw.append(activity_id)
                continue
            raw_found += 1

            extraction = extract_activity_load_metrics(summary)
            for issue in extraction.issues:
                report = ActivityLoadValueReport(activity_id, issue)
                (malformed if issue.kind == "malformed" else skipped).append(report)
            if not extraction.metrics:
                continue

            counts = self._repository.upsert_activity_metrics(
                activity_id,
                extraction.metrics,
                ACTIVITY_LOAD_METRIC_KEYS,
                write=not dry_run,
            )
            inserted += counts.inserted
            updated += counts.updated
            unchanged += counts.unchanged
            if counts.inserted or counts.updated:
                changed += 1

        return ActivityLoadBackfillResult(
            dry_run=dry_run,
            activities_examined=len(activity_ids),
            raw_summaries_found=raw_found,
            activities_changed=changed,
            metrics_inserted=inserted,
            metrics_updated=updated,
            metrics_unchanged=unchanged,
            missing_raw=tuple(missing_raw),
            unreadable_raw=tuple(unreadable_raw),
            malformed_values=tuple(malformed),
            skipped_values=tuple(skipped),
        )
