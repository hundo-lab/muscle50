from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from muscle50.application.renormalize_garmin_recovery import RenormalizeGarminRecovery
from muscle50.application.sync_garmin_recovery import SyncGarminRecovery
from muscle50.cli import main
from muscle50.domain.recovery import RECOVERY_NORMALIZER_VERSION
from muscle50.infrastructure.garmin.client import GarminRawRecovery, PythonGarminConnector
from muscle50.infrastructure.raw_store import RecoveryRawStore
from muscle50.infrastructure.sqlite.database import DailyRecoveryRepository
from muscle50.presentation.terminal import render_recovery_renormalize_result


def _observed_payloads(
    calendar_date: str, phrase: str | None = "RECOVERY_2", hrv: float | None = 62.0
) -> dict[str, Any]:
    """Synthetic payloads in the stored real endpoint shapes."""
    return {
        "sleep": {
            "dailySleepDTO": {"calendarDate": calendar_date, "sleepTimeSeconds": 20580},
            "avgOvernightHrv": hrv,
            "hrvStatus": "BALANCED",
        },
        "hrv": {"hrvSummary": {"calendarDate": calendar_date, "lastNightAvg": 62}},
        "daily_stats": {"calendarDate": calendar_date, "bodyBatteryHighestValue": 93, "averageStressLevel": 28},
        "training_status": {
            "mostRecentTrainingStatus": {
                "latestTrainingStatusData": {
                    "900": {
                        "calendarDate": calendar_date,
                        "trainingStatus": 5,
                        "trainingStatusFeedbackPhrase": phrase,
                        "primaryTrainingDevice": True,
                    }
                }
            }
        },
    }


class NoCallConnector:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.payloads: dict[str, dict[str, Any]] = {}

    def fetch_raw_recovery(self, calendar_date: str) -> GarminRawRecovery:
        self.calls.append(calendar_date)
        return GarminRawRecovery(calendar_date, self.payloads[calendar_date], ())


def _root(tmp_path: Path) -> Path:
    return tmp_path / "private-muscle50"


def _db(root: Path) -> Path:
    return root / "db" / "muscle50.sqlite3"


def _raw_store(root: Path) -> RecoveryRawStore:
    return RecoveryRawStore(root / "raw" / "garmin" / "recovery", root, root / "tmp")


def _seed(root: Path, payloads_by_date: dict[str, dict[str, Any]]) -> NoCallConnector:
    """Sync dates, then rewrite rows as the version-1 normalizer stored them."""
    repository = DailyRecoveryRepository(_db(root))
    repository.migrate()
    connector = NoCallConnector()
    connector.payloads = payloads_by_date
    use_case = SyncGarminRecovery(connector, repository, _raw_store(root))
    for calendar_date in payloads_by_date:
        use_case.execute(calendar_date)
    with sqlite3.connect(_db(root)) as connection:
        connection.execute(
            "UPDATE daily_recovery SET sleep_avg_hrv_ms = NULL, training_status_key = NULL, normalizer_version = 1"
        )
    return connector


def _rows(root: Path) -> list[tuple[Any, ...]]:
    with sqlite3.connect(_db(root)) as connection:
        return [tuple(row) for row in connection.execute("SELECT * FROM daily_recovery ORDER BY calendar_date")]


def _capture_state(root: Path) -> tuple[Any, ...]:
    with sqlite3.connect(_db(root)) as connection:
        captures = connection.execute("SELECT * FROM recovery_raw_captures ORDER BY id").fetchall()
        artifacts = connection.execute("SELECT * FROM recovery_raw_artifacts ORDER BY relative_path").fetchall()
    files = {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted((root / "raw").rglob("*"))
        if path.is_file()
    }
    return captures, artifacts, files


def _use_case(root: Path) -> RenormalizeGarminRecovery:
    return RenormalizeGarminRecovery(DailyRecoveryRepository(_db(root)), _raw_store(root))


def test_renormalizes_only_mapping_fields_from_accepted_raw_without_new_captures(tmp_path: Path) -> None:
    root = _root(tmp_path)
    connector = _seed(
        root,
        {
            "2026-09-27": _observed_payloads("2026-09-27"),
            "2026-09-28": _observed_payloads("2026-09-28", phrase="PRODUCTIVE_6", hrv=None),
        },
    )
    calls_before = list(connector.calls)
    captures_before = _capture_state(root)
    rows_before = {row[2]: row for row in _rows(root)}

    result = _use_case(root).execute()

    assert connector.calls == calls_before
    assert _capture_state(root) == captures_before
    assert result.dates_updated == ("2026-09-27", "2026-09-28")
    assert result.failures == ()
    assert result.field_changes == {"normalizer_version": 2, "sleep_avg_hrv_ms": 1, "training_status_key": 2}
    repository = DailyRecoveryRepository(_db(root))
    first = repository.find("2026-09-27")
    second = repository.find("2026-09-28")
    assert first is not None and second is not None
    assert (first.training_status_key, first.sleep_avg_hrv_ms) == ("RECOVERY", 62.0)
    assert (second.training_status_key, second.sleep_avg_hrv_ms) == ("PRODUCTIVE", None)
    assert first.normalizer_version == second.normalizer_version == RECOVERY_NORMALIZER_VERSION
    for row in _rows(root):
        before = rows_before[row[2]]
        # id, provider, date, and imported_at never change; capture pointer is unchanged.
        assert (row[0], row[1], row[2]) == (before[0], before[1], before[2])
    with sqlite3.connect(_db(root)) as connection:
        pointers = connection.execute(
            "SELECT recovery.primary_raw_capture_id = capture.id FROM daily_recovery AS recovery "
            "JOIN recovery_raw_captures AS capture ON capture.requested_date = recovery.calendar_date"
        ).fetchall()
    assert pointers == [(1,), (1,)]


def test_second_renormalization_is_idempotent(tmp_path: Path) -> None:
    root = _root(tmp_path)
    _seed(root, {"2026-09-28": _observed_payloads("2026-09-28")})
    use_case = _use_case(root)
    use_case.execute()
    after_first = (_rows(root), _capture_state(root))

    second = use_case.execute()

    assert second.dates_updated == ()
    assert second.dates_unchanged == ("2026-09-28",)
    assert second.field_changes == {}
    assert (_rows(root), _capture_state(root)) == after_first


def test_dry_run_reports_the_same_changes_and_writes_nothing(tmp_path: Path) -> None:
    root = _root(tmp_path)
    _seed(root, {"2026-09-28": _observed_payloads("2026-09-28")})
    before = (_rows(root), _capture_state(root))
    use_case = _use_case(root)

    dry = use_case.execute(dry_run=True)

    assert (_rows(root), _capture_state(root)) == before
    real = use_case.execute()
    assert (dry.dates_updated, dry.field_changes) == (real.dates_updated, real.field_changes)
    assert "dry run" in render_recovery_renormalize_result(dry)


def test_tampered_raw_is_reported_and_leaves_that_row_untouched(tmp_path: Path) -> None:
    root = _root(tmp_path)
    _seed(
        root,
        {"2026-09-27": _observed_payloads("2026-09-27"), "2026-09-28": _observed_payloads("2026-09-28")},
    )
    capture = DailyRecoveryRepository(_db(root)).find_source_capture("2026-09-27")
    assert capture is not None
    tampered = next(artifact for artifact in capture.artifacts if artifact.kind == "training_status")
    (root / tampered.relative_path).write_text('{"tampered": true}\n', encoding="utf-8")
    row_before = next(row for row in _rows(root) if row[2] == "2026-09-27")

    result = _use_case(root).execute()

    assert [failure.calendar_date for failure in result.failures] == ["2026-09-27"]
    assert "hash" in result.failures[0].error
    assert result.dates_updated == ("2026-09-28",)
    assert next(row for row in _rows(root) if row[2] == "2026-09-27") == row_before


def test_cli_renormalize_never_authenticates(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    root = _root(tmp_path)
    _seed(root, {"2026-09-28": _observed_payloads("2026-09-28")})
    monkeypatch.setenv("MUSCLE50_HOME", str(root))
    monkeypatch.setattr(
        PythonGarminConnector,
        "authenticate",
        lambda auth_dir: pytest.fail("re-normalization must not authenticate with Garmin"),
    )

    assert main(["garmin", "recovery-renormalize", "--dry-run"]) == 0
    assert "Dates updated: 1" in capsys.readouterr().out
    assert main(["garmin", "recovery-renormalize"]) == 0
    assert "Field changed: training_status_key (1 dates)" in capsys.readouterr().out
    assert main(["garmin", "recovery-renormalize"]) == 0
    assert "Dates unchanged: 1" in capsys.readouterr().out
