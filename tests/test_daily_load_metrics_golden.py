"""Golden output of `daily`'s load_metrics stage (auto-load-metrics AC5).

These tests pin the exact `daily --after-workout` text and JSON for the load-metric
failure/warning rule. They import only symbols that existed before the rule was extracted
into `application/imported_load_metrics.py`, so the same file runs green against the code
before and after that refactor: the rule's strings, order and joins must not change.
The expected bytes were captured on the code before the refactor.
Synthetic activities only; a fake Garmin session and a temporary home, never production.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import date
from pathlib import Path
from typing import Any

import pytest

import muscle50.cli as cli
from muscle50.cli import main
from muscle50.infrastructure.garmin.client import GarminRawActivity, PythonGarminConnector
from muscle50.infrastructure.raw_store import RawStore

TODAY = date(2026, 10, 2)
SEED_DATE = "2026-09-29"


def _summary(activity_id: int, local_date: str, **extra: Any) -> dict[str, Any]:
    return {
        "activityId": activity_id,
        "activityName": f"Synthetic Activity {activity_id}",
        "activityType": {"typeKey": "running"},
        "startTimeLocal": f"{local_date} 07:00:00",
        "startTimeGMT": f"{local_date} 07:00:00",
        "duration": 1800.0,
        "distance": 5000.0,
        **extra,
    }


class FakeGarmin:
    """Activity endpoints only (after-workout mode never syncs recovery), newest first."""

    def __init__(self, summaries: Sequence[Mapping[str, Any]]):
        self._summaries = list(summaries)

    def latest_summary(self) -> Mapping[str, Any] | None:
        raise AssertionError("daily must use the range ingestion, not latest")

    def list_activities(self, start: int, limit: int) -> Sequence[Mapping[str, Any]]:
        return self._summaries[start : start + limit]

    def fetch_raw_activity(self, activity_id: str, source_type_key: str) -> GarminRawActivity:
        return GarminRawActivity(
            summary={},
            activity={"activityId": int(activity_id)},
            details={"activityId": int(activity_id), "metricDescriptors": []},
            splits={"lapDTOs": []},
            exercise_sets=None,
            original_archive=b"synthetic-original-archive",
            warnings=(),
        )

    def fetch_raw_recovery(self, calendar_date: str) -> Any:
        raise AssertionError("after-workout mode must not sync recovery")


ACCOUNT = FakeGarmin(
    [
        _summary(300, "2026-10-02", activityTrainingLoad=55.5, aerobicTrainingEffect=2.4),
        _summary(222, "2026-10-01", activityTrainingLoad=40.0, moderateIntensityMinutes=12),
        _summary(101, SEED_DATE, activityTrainingLoad=20.0),
        _summary(100, SEED_DATE, activityTrainingLoad=30.0),
    ]
)

MALFORMED_ACCOUNT = FakeGarmin(
    [
        _summary(300, "2026-10-02", activityTrainingLoad=55.5, aerobicTrainingEffect="2.5"),
        _summary(222, "2026-10-01", activityTrainingLoad=40.0, anaerobicTrainingEffect=True),
        _summary(100, SEED_DATE, activityTrainingLoad="30"),  # malformed, but not from the checked run
    ]
)


def _home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str, garmin: FakeGarmin) -> Path:
    root = tmp_path / name
    monkeypatch.setenv("MUSCLE50_HOME", str(root))
    monkeypatch.setattr(cli, "_today", lambda: TODAY)
    monkeypatch.setattr(PythonGarminConnector, "authenticate", lambda *_args, **_kwargs: garmin)
    return root


def _summary_path(root: Path, activity_id: str) -> Path:
    return root / "raw" / "garmin" / "activities" / activity_id / "summary.json"


def _run(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, str]:
    code = main(list(argv))
    return code, capsys.readouterr().out


def _seed_older_activities(capsys: pytest.CaptureFixture[str]) -> None:
    code, _ = _run(capsys, "daily", "--after-workout", "--date", SEED_DATE)
    assert code == 0


def _text(load_lines: Sequence[str], tail: str) -> str:
    lines = [
        "muscle50 daily for 2026-10-02 (after-workout)",
        "Stages:",
        "  garmin_login: ok",
        "  activities: ok (2026-10-01..2026-10-02: found 2, new 2, already stored 0, failed 0)",
        *load_lines,
        "  recovery: skipped",
        "  recommendation: skipped",
        tail,
    ]
    return "\n".join(lines) + "\n"


def _json(load_stage: dict[str, Any], load_metrics: dict[str, Any]) -> str:
    def stage(name: str, status: str) -> dict[str, Any]:
        return {"stage": name, "status": status, "error": None, "warnings": []}

    def outcome(activity_id: str) -> dict[str, Any]:
        return {
            "source_activity_id": activity_id,
            "source_type_key": "running",
            "status": "inserted",
            "error": None,
            "warnings": [],
        }

    ok = load_stage["status"] == "ok"
    document = {
        "as_of": "2026-10-02",
        "mode": "after_workout",
        "sync_from": "2026-10-01",
        "ok": ok,
        "failed_stages": [] if ok else ["load_metrics"],
        "stages": [
            stage("garmin_login", "ok"),
            stage("activities", "ok"),
            {"stage": "load_metrics", **load_stage},
            stage("recovery", "skipped"),
            stage("recommendation", "skipped"),
        ],
        "activities": {
            "from": "2026-10-01",
            "to": "2026-10-02",
            "discovered": 2,
            "inserted": 2,
            "already_stored": 0,
            "failed": 0,
            "undated": 0,
            "page_limit_reached": False,
            "outcomes": [outcome("222"), outcome("300")],
        },
        "load_metrics": load_metrics,
        "recovery": None,
        "recommendation": None,
    }
    return json.dumps(document, indent=2) + "\n"


IMPORTED = "Imported. The next `muscle50 daily` will count this workout."

OLDER_GAP_TEXT = _text(
    [
        "  load_metrics: ok (metric rows inserted 4, updated 0, unchanged 0)",
        "    warning: 2 previously stored activities have no readable RAW summary (not from this run): 100, 101",
    ],
    IMPORTED,
)
OLDER_GAP_JSON = _json(
    {
        "status": "ok",
        "error": None,
        "warnings": ["2 previously stored activities have no readable RAW summary (not from this run): 100, 101"],
    },
    {
        "activities_examined": 4,
        "metric_rows_inserted": 4,
        "metric_rows_updated": 0,
        "metric_rows_unchanged": 0,
        "missing_raw": ["100"],
        "unreadable_raw": ["101"],
        "malformed_values": 0,
        "skipped_values": 16,
    },
)


@pytest.mark.parametrize("as_json", [False, True])
def test_older_raw_gaps_are_a_warning_and_new_activities_still_fill(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], as_json: bool
) -> None:
    root = _home(tmp_path, monkeypatch, "home", ACCOUNT)
    _seed_older_activities(capsys)
    _summary_path(root, "100").unlink()  # missing
    _summary_path(root, "101").write_bytes(b"{not json")  # unreadable

    code, output = _run(capsys, "daily", "--after-workout", *(["--json"] if as_json else []))

    assert code == 0
    assert output == (OLDER_GAP_JSON if as_json else OLDER_GAP_TEXT)


BOTH_WARNINGS_TEXT = _text(
    [
        "  load_metrics: ok (metric rows inserted 2, updated 0, unchanged 0)",
        "    warning: 1 previously stored activities have no readable RAW summary (not from this run): 100",
        "    warning: malformed load-metric values in activities imported in this run: 222, 300",
    ],
    IMPORTED,
)
BOTH_WARNINGS_JSON = _json(
    {
        "status": "ok",
        "error": None,
        "warnings": [
            "1 previously stored activities have no readable RAW summary (not from this run): 100",
            "malformed load-metric values in activities imported in this run: 222, 300",
        ],
    },
    {
        "activities_examined": 3,
        "metric_rows_inserted": 2,
        "metric_rows_updated": 0,
        "metric_rows_unchanged": 0,
        "missing_raw": ["100"],
        "unreadable_raw": [],
        "malformed_values": 2,
        "skipped_values": 16,
    },
)


@pytest.mark.parametrize("as_json", [False, True])
def test_both_warnings_keep_their_order_and_older_malformed_values_are_not_reported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], as_json: bool
) -> None:
    root = _home(tmp_path, monkeypatch, "home", MALFORMED_ACCOUNT)
    _seed_older_activities(capsys)
    _summary_path(root, "100").unlink()

    code, output = _run(capsys, "daily", "--after-workout", *(["--json"] if as_json else []))

    assert code == 0
    assert output == (BOTH_WARNINGS_JSON if as_json else BOTH_WARNINGS_TEXT)


NEW_GAP_TEXT = _text(
    [
        "  load_metrics: failed (metric rows inserted 0, updated 0, unchanged 1)",
        "    error: no readable RAW summary for activities imported in this run: 222, 300",
    ],
    "FAILED stages: load_metrics. Data already synced is kept; rerunning the same command is safe.",
)
NEW_GAP_JSON = _json(
    {
        "status": "failed",
        "error": "no readable RAW summary for activities imported in this run: 222, 300",
        "warnings": [],
    },
    {
        "activities_examined": 4,
        "metric_rows_inserted": 0,
        "metric_rows_updated": 0,
        "metric_rows_unchanged": 1,
        "missing_raw": ["100", "222", "300"],
        "unreadable_raw": [],
        "malformed_values": 0,
        "skipped_values": 9,
    },
)


@pytest.mark.parametrize("as_json", [False, True])
def test_a_new_activity_without_its_raw_summary_fails_the_stage_without_warnings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], as_json: bool
) -> None:
    root = _home(tmp_path, monkeypatch, "home", ACCOUNT)
    _seed_older_activities(capsys)
    _summary_path(root, "100").unlink()  # an older gap too: a failed stage reports no warnings
    original_preserve = RawStore.preserve

    def preserve_then_lose_summary(self: RawStore, activity_id: str, raw: GarminRawActivity) -> Any:
        artifacts = original_preserve(self, activity_id, raw)
        if activity_id in {"222", "300"}:
            _summary_path(root, activity_id).unlink()
        return artifacts

    monkeypatch.setattr(RawStore, "preserve", preserve_then_lose_summary)

    code, output = _run(capsys, "daily", "--after-workout", *(["--json"] if as_json else []))

    assert code == 1
    assert output == (NEW_GAP_JSON if as_json else NEW_GAP_TEXT)
