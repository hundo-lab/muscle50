"""Text and JSON for Garmin sync coverage (Sync Coverage v1).

ASCII only (cp949 consoles). JSON uses ``indent=2, ensure_ascii=True`` and a fixed key order.
The recommendation window carries no timestamps or command names, so repeated ``daily`` and
``recommend`` runs over the same stored data stay byte-identical.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import date, timedelta
from typing import Any

from muscle50.application.sync_coverage import RecoveryCoverageBackfillResult, SyncCoverageReport
from muscle50.domain.sync_coverage import (
    CoverageDay,
    CoverageReportDay,
    CoverageSource,
    CoverageStatus,
    RecordedCoverage,
    SyncCoverageWindow,
)

_DATE_COLUMN = 12
_ACTIVITIES_COLUMN = 30
_RECORDED_BY = (
    "Recorded by: garmin activities --from/--to, garmin recovery, daily. Not recorded: garmin latest, garmin refresh."
)
_NO_TABLE = "Sync coverage is not recorded in this database yet (the next Garmin sync command creates it)."


def render_sync_coverage(report: SyncCoverageReport) -> str:
    lines = [
        f"Garmin sync coverage {report.start.isoformat()}..{report.end.isoformat()} (latest recorded result per date)",
        "date".ljust(_DATE_COLUMN) + _column("activities") + "recovery",
    ]
    for day in report.days:
        lines.append(
            day.calendar_date.isoformat().ljust(_DATE_COLUMN)
            + _column(_activities_text(day))
            + _recovery_text(day.recovery)
        )
    activities = [_status(day.activities) for day in report.days]
    recovery = [_status(day.recovery) for day in report.days]
    backfilled = sum(
        1
        for day in report.days
        if day.recovery is not None
        and day.recovery.entry.status is CoverageStatus.SYNCED
        and day.recovery.entry.source is CoverageSource.RAW_BACKFILL
    )
    lines.append(f"activities: {_activity_counts(activities)}; recovery: {_recovery_counts(recovery, backfilled)}")
    lines.append(_RECORDED_BY)
    if not report.table_present:
        lines.append(_NO_TABLE)
    return "\n".join(lines)


def render_sync_coverage_json(report: SyncCoverageReport) -> str:
    payload = {
        "from": report.start.isoformat(),
        "to": report.end.isoformat(),
        "coverage_table_present": report.table_present,
        "days": [
            {
                "date": day.calendar_date.isoformat(),
                "activities": {
                    "status": _status(day.activities).value,
                    "stored_activities": day.stored_activities,
                    "failed_activity_ids": list(day.activities.entry.failed_activity_ids) if day.activities else [],
                    **_provenance(day.activities),
                },
                "recovery": {
                    "status": _status(day.recovery).value,
                    "missing_endpoints": list(day.recovery.entry.missing_endpoints) if day.recovery else [],
                    **_provenance(day.recovery),
                },
            }
            for day in report.days
        ],
    }
    return json.dumps(payload, indent=2, ensure_ascii=True)


def render_recovery_coverage_backfill(result: RecoveryCoverageBackfillResult) -> str:
    state = "dry run, nothing written" if result.dry_run else None
    lines = [
        "Recovery coverage backfill from stored RAW" + (f" ({state})" if state else " complete"),
        f"Recovery dates with an accepted RAW capture: {result.recovery_dates}",
        f"Already recorded (left unchanged): {result.already_recorded}",
        f"Added as synced (backfilled from RAW): {len(result.added_synced)}",
        f"Added as partial (backfilled from RAW): {len(result.added_partial)}",
    ]
    lines.extend(
        f"Partial: {item.calendar_date.isoformat()} (missing: {', '.join(item.missing_endpoints)})"
        for item in result.added_partial
    )
    return "\n".join(lines)


def sync_coverage_payload(window: SyncCoverageWindow) -> dict[str, Any]:
    """The ``data_freshness.sync_coverage`` JSON value of a recommendation."""
    return {
        "from": window.start.isoformat(),
        "to": window.end.isoformat(),
        "days": [
            {
                "date": day.calendar_date.isoformat(),
                "activities": day.activities.value,
                "stored_activities": day.stored_activities,
                "recovery": day.recovery.value,
                "recovery_source": day.recovery_source.value if day.recovery_source is not None else None,
            }
            for day in window.days
        ],
    }


def sync_coverage_freshness_lines(window: SyncCoverageWindow) -> list[str]:
    """Two `== Data freshness ==` lines separating "synced, no activity" from "not synced"."""
    days = window.days
    backfilled = sum(
        1
        for day in days
        if day.recovery is CoverageStatus.SYNCED and day.recovery_source is CoverageSource.RAW_BACKFILL
    )
    empty = [day for day in days if day.stored_activities == 0]
    return [
        f"  sync coverage {window.start.isoformat()}..{window.end.isoformat()}: "
        f"activities {_activity_counts([day.activities for day in days])} days; "
        f"recovery {_recovery_counts([day.recovery for day in days], backfilled)} days",
        "  days with no stored activity: "
        f"synced, no activity: {_date_runs(_dates(empty, CoverageStatus.SYNCED))}; "
        f"sync failed: {_date_runs(_dates(empty, CoverageStatus.FAILED))}; "
        f"not synced: {_date_runs(_dates(empty, CoverageStatus.NOT_SYNCED))}",
    ]


def _column(text: str) -> str:
    # Padded to the column width, and always at least one space before the next column.
    return text.ljust(_ACTIVITIES_COLUMN - 1) + " "


def _status(record: RecordedCoverage | None) -> CoverageStatus:
    return record.entry.status if record is not None else CoverageStatus.NOT_SYNCED


def _activities_text(day: CoverageReportDay) -> str:
    record = day.activities
    stored = day.stored_activities
    if record is None:
        return f"not synced ({stored} stored)" if stored else "not synced"
    if record.entry.status is CoverageStatus.FAILED:
        return f"failed ({len(record.entry.failed_activity_ids)} failed, {stored} stored)"
    return f"{record.entry.status.value} ({stored} stored)"


def _recovery_text(record: RecordedCoverage | None) -> str:
    if record is None:
        return "not synced"
    entry = record.entry
    details = []
    if entry.status is CoverageStatus.PARTIAL:
        count = len(entry.missing_endpoints)
        details.append(f"{count} endpoint{'' if count == 1 else 's'} failed")
    if entry.source is CoverageSource.RAW_BACKFILL:
        details.append("backfilled from RAW")
    return entry.status.value + (f" ({', '.join(details)})" if details else "")


def _provenance(record: RecordedCoverage | None) -> dict[str, str | None]:
    return {
        "source": record.entry.source.value if record is not None else None,
        "command": record.command if record is not None else None,
        "synced_at_utc": record.synced_at_utc if record is not None else None,
    }


def _activity_counts(statuses: Sequence[CoverageStatus]) -> str:
    return (
        f"synced {statuses.count(CoverageStatus.SYNCED)}, failed {statuses.count(CoverageStatus.FAILED)}, "
        f"not synced {statuses.count(CoverageStatus.NOT_SYNCED)}"
    )


def _recovery_counts(statuses: Sequence[CoverageStatus], backfilled: int) -> str:
    from_raw = f" ({backfilled} backfilled from RAW)" if backfilled else ""
    return (
        f"synced {statuses.count(CoverageStatus.SYNCED)}{from_raw}, partial {statuses.count(CoverageStatus.PARTIAL)}, "
        f"failed {statuses.count(CoverageStatus.FAILED)}, not synced {statuses.count(CoverageStatus.NOT_SYNCED)}"
    )


def _dates(days: Sequence[CoverageDay], status: CoverageStatus) -> list[date]:
    return [day.calendar_date for day in days if day.activities is status]


def _date_runs(dates: Sequence[date]) -> str:
    """Ascending dates with consecutive days joined as ``A..B``; ``none`` when empty."""
    runs: list[tuple[date, date]] = []
    for day in dates:
        if runs and day == runs[-1][1] + timedelta(days=1):
            runs[-1] = (runs[-1][0], day)
        else:
            runs.append((day, day))
    if not runs:
        return "none"
    return ", ".join(
        start.isoformat() if start == end else f"{start.isoformat()}..{end.isoformat()}" for start, end in runs
    )
