"""Ingest every Garmin activity within a bounded, inclusive local calendar-date range."""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from typing import Any, Literal

from muscle50.application.ingest_activity import ActivitySyncError, IngestGarminActivity
from muscle50.domain.normalization import (
    NormalizationError,
    activity_id_from,
    local_date_from,
    source_type_from,
)
from muscle50.infrastructure.garmin.client import GarminConnector, GarminConnectorError
from muscle50.infrastructure.raw_store import RawStore, RawStoreError
from muscle50.infrastructure.sqlite.database import ActivityRepository

_PAGE_SIZE = 20
_MAX_PAGES = 50

# Deliberately excludes bare RuntimeError/ValueError: those are raised only when a
# stored Strength/Swim detail disagrees with a fresh local-RAW re-normalization during
# backfill (see database.py's `_insert_strength_sets`/`_insert_swim_detail` with
# ignore_existing=True). That is a local-data-integrity bug, not an ordinary per-activity
# failure, so it is allowed to propagate and abort the whole range rather than being
# silently recorded as one more "failed" outcome.
_KNOWN_INGEST_ERRORS = (ActivitySyncError, GarminConnectorError, NormalizationError, RawStoreError, sqlite3.Error)


class InvalidDateRangeError(ValueError):
    """Raised when the requested Garmin activity range is invalid."""


@dataclass(frozen=True)
class RangeIngestOutcome:
    source_activity_id: str
    source_type_key: str
    status: Literal["inserted", "skipped", "failed"]
    error: str | None = None
    warnings: tuple[str, ...] = ()
    """Optional Garmin endpoint warnings (for example missing exercise sets) for an inserted activity."""


@dataclass(frozen=True)
class RangeIngestResult:
    from_date: date
    to_date: date
    discovered_count: int
    outcomes: tuple[RangeIngestOutcome, ...]
    undated_count: int = 0  # Garmin list entries with no parseable start date/id; excluded, not guessed.
    page_limit_reached: bool = False

    @property
    def inserted_count(self) -> int:
        return sum(1 for outcome in self.outcomes if outcome.status == "inserted")

    @property
    def skipped_count(self) -> int:
        return sum(1 for outcome in self.outcomes if outcome.status == "skipped")

    @property
    def failed_count(self) -> int:
        return sum(1 for outcome in self.outcomes if outcome.status == "failed")


class IngestGarminActivityRange:
    """Discovers activities in a date range and ingests each through the canonical path.

    Discovery pages through the Garmin activity list newest-first and stops as soon as a
    page contains an activity older than `from_date`, so a range near "now" never has to
    walk a whole account's history. Each discovered activity is ingested in isolation: one
    activity failing does not roll back or block any other activity in the range.
    """

    def __init__(self, connector: GarminConnector, repository: ActivityRepository, raw_store: RawStore):
        self._connector = connector
        self._ingest = IngestGarminActivity(connector, repository, raw_store)

    def execute(self, from_date: date, to_date: date) -> RangeIngestResult:
        if from_date > to_date:
            raise InvalidDateRangeError("from_date는 to_date보다 이후일 수 없습니다.")

        candidates, undated_count, page_limit_reached = self._discover(from_date, to_date)
        outcomes: list[RangeIngestOutcome] = []
        for summary in candidates:
            outcomes.append(self._ingest_one(summary))

        return RangeIngestResult(
            from_date=from_date,
            to_date=to_date,
            discovered_count=len(candidates),
            outcomes=tuple(outcomes),
            undated_count=undated_count,
            page_limit_reached=page_limit_reached,
        )

    def _ingest_one(self, summary: Mapping[str, Any]) -> RangeIngestOutcome:
        activity_id = activity_id_from(summary)
        source_type_key = source_type_from(summary)
        try:
            result = self._ingest.execute(summary)
        except _KNOWN_INGEST_ERRORS as exc:
            return RangeIngestOutcome(activity_id, source_type_key, "failed", str(exc))
        status: Literal["inserted", "skipped"] = "inserted" if result.created else "skipped"
        return RangeIngestOutcome(
            result.activity.source_activity_id, result.activity.source_type_key, status, warnings=result.warnings
        )

    def _discover(self, from_date: date, to_date: date) -> tuple[list[Mapping[str, Any]], int, bool]:
        seen_ids: set[str] = set()
        candidates: dict[str, Mapping[str, Any]] = {}
        undated_count = 0
        start = 0
        page_limit_reached = False

        for _page_index in range(_MAX_PAGES):
            page = self._connector.list_activities(start, _PAGE_SIZE)
            if not page:
                break
            page_covers_older_activity = False
            for item in page:
                activity_date = local_date_from(item)
                if activity_date is None:
                    undated_count += 1
                    continue
                if activity_date > to_date:
                    continue
                if activity_date < from_date:
                    page_covers_older_activity = True
                    continue
                try:
                    activity_id = activity_id_from(item)
                except NormalizationError:
                    undated_count += 1
                    continue
                if activity_id not in seen_ids:
                    seen_ids.add(activity_id)
                    candidates[activity_id] = item
            if page_covers_older_activity:
                break
            start += _PAGE_SIZE
        else:
            page_limit_reached = True

        ordered = sorted(
            candidates.values(),
            key=lambda item: (local_date_from(item) or from_date, int(activity_id_from(item))),
        )
        return ordered, undated_count, page_limit_reached
