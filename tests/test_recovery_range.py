from __future__ import annotations

import json
import sqlite3
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pytest

from muscle50.application.sync_garmin_recovery import (
    MAX_RECOVERY_RANGE_DAYS,
    InvalidRecoveryRangeError,
    SyncGarminRecovery,
    recovery_range_dates,
)
from muscle50.cli import build_parser, main
from muscle50.infrastructure.garmin.client import (
    GarminAuthenticationError,
    GarminConnectorError,
    GarminRawRecovery,
    PythonGarminConnector,
)
from muscle50.infrastructure.raw_store import RecoveryRawStore
from muscle50.infrastructure.sqlite.database import DailyRecoveryRepository
from muscle50.presentation.terminal import render_recovery_range_result


def _payloads(calendar_date: str, body_battery_high: int = 90) -> dict[str, Any]:
    return {
        "sleep": {"dailySleepDTO": {"calendarDate": calendar_date, "sleepTimeSeconds": 27000}},
        "daily_stats": {
            "calendarDate": calendar_date,
            "bodyBatteryHighestValue": body_battery_high,
            "bodyBatteryLowestValue": 25,
        },
        "hrv": {"hrvSummary": {"calendarDate": calendar_date, "lastNightAvg": 48}},
    }


class DatedRecoveryConnector:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.failures: dict[str, Exception] = {}
        self.body_battery_high: dict[str, int] = {}

    def fetch_raw_recovery(self, calendar_date: str) -> GarminRawRecovery:
        self.calls.append(calendar_date)
        failure = self.failures.get(calendar_date)
        if failure is not None:
            raise failure
        payloads = _payloads(calendar_date, self.body_battery_high.get(calendar_date, 90))
        return GarminRawRecovery(calendar_date, payloads, ())


def _root(tmp_path: Path) -> Path:
    return tmp_path / "private-muscle50"


def _use_case(root: Path, connector: DatedRecoveryConnector) -> SyncGarminRecovery:
    repository = DailyRecoveryRepository(root / "db" / "muscle50.sqlite3")
    repository.migrate()
    return SyncGarminRecovery(
        connector,
        repository,
        RecoveryRawStore(root / "raw" / "garmin" / "recovery", root, root / "tmp"),
    )


def _rows(root: Path) -> list[tuple[str, int, str]]:
    with sqlite3.connect(root / "db" / "muscle50.sqlite3") as connection:
        return [
            tuple(row)
            for row in connection.execute(
                "SELECT calendar_date, body_battery_high, primary_raw_capture_id FROM daily_recovery ORDER BY 1"
            )
        ]


def _capture_count(root: Path) -> int:
    with sqlite3.connect(root / "db" / "muscle50.sqlite3") as connection:
        return int(connection.execute("SELECT COUNT(*) FROM recovery_raw_captures").fetchone()[0])


def test_range_dates_are_inclusive_and_ascending() -> None:
    assert recovery_range_dates(date(2026, 8, 30), date(2026, 9, 2)) == (
        "2026-08-30",
        "2026-08-31",
        "2026-09-01",
        "2026-09-02",
    )
    assert recovery_range_dates(date(2026, 9, 1), date(2026, 9, 1)) == ("2026-09-01",)


def test_reversed_and_oversized_ranges_are_rejected() -> None:
    with pytest.raises(InvalidRecoveryRangeError):
        recovery_range_dates(date(2026, 9, 2), date(2026, 9, 1))
    with pytest.raises(InvalidRecoveryRangeError):
        recovery_range_dates(date(2026, 1, 1), date(2026, 1, 1) + timedelta(days=MAX_RECOVERY_RANGE_DAYS))
    longest = recovery_range_dates(date(2026, 1, 1), date(2026, 1, 1) + timedelta(days=MAX_RECOVERY_RANGE_DAYS - 1))
    assert len(longest) == MAX_RECOVERY_RANGE_DAYS


def test_reversed_range_makes_no_garmin_call(tmp_path: Path) -> None:
    connector = DatedRecoveryConnector()

    with pytest.raises(InvalidRecoveryRangeError):
        _use_case(_root(tmp_path), connector).execute_range(date(2026, 9, 2), date(2026, 9, 1))

    assert connector.calls == []


def test_one_day_range_matches_single_date_sync(tmp_path: Path) -> None:
    range_root = tmp_path / "range" / "private-muscle50"
    single_root = tmp_path / "single" / "private-muscle50"

    result = _use_case(range_root, DatedRecoveryConnector()).execute_range(date(2026, 9, 15), date(2026, 9, 15))
    single = _use_case(single_root, DatedRecoveryConnector()).execute("2026-09-15")

    assert [(item.calendar_date, item.status) for item in result.outcomes] == [("2026-09-15", "created")]
    assert result.complete
    ranged = result.outcomes[0].result
    assert ranged is not None
    assert ranged.recovery == single.recovery
    assert _rows(range_root) == _rows(single_root)


def test_multi_day_range_preserves_raw_provenance_per_date(tmp_path: Path) -> None:
    root = _root(tmp_path)
    connector = DatedRecoveryConnector()

    result = _use_case(root, connector).execute_range(date(2026, 8, 31), date(2026, 9, 2))

    assert connector.calls == ["2026-08-31", "2026-09-01", "2026-09-02"]
    assert [item.status for item in result.outcomes] == ["created"] * 3
    assert [row[0] for row in _rows(root)] == ["2026-08-31", "2026-09-01", "2026-09-02"]
    repository = DailyRecoveryRepository(root / "db" / "muscle50.sqlite3")
    for calendar_date in connector.calls:
        capture = repository.find_source_capture(calendar_date)
        assert capture is not None and capture.requested_date == calendar_date
        manifest = root / capture.manifest_relative_path
        assert manifest.parent.parent.name == calendar_date
        assert json.loads(manifest.read_text(encoding="utf-8"))["requested_date"] == calendar_date
        for artifact in capture.artifacts:
            payload = json.loads((root / artifact.relative_path).read_text(encoding="utf-8"))
            assert calendar_date in json.dumps(payload)


def test_repeated_range_sync_is_deterministic(tmp_path: Path) -> None:
    root = _root(tmp_path)
    connector = DatedRecoveryConnector()
    use_case = _use_case(root, connector)
    use_case.execute_range(date(2026, 9, 1), date(2026, 9, 3))
    rows, captures = _rows(root), _capture_count(root)

    second = use_case.execute_range(date(2026, 9, 1), date(2026, 9, 3))

    assert [item.status for item in second.outcomes] == ["unchanged"] * 3
    assert (_rows(root), _capture_count(root)) == (rows, captures)

    connector.body_battery_high["2026-09-02"] = 97
    third = use_case.execute_range(date(2026, 9, 1), date(2026, 9, 3))
    assert [item.status for item in third.outcomes] == ["unchanged", "updated", "unchanged"]
    assert [row[1] for row in _rows(root)] == [90, 97, 90]


def test_partial_failure_is_isolated_reported_and_recoverable(tmp_path: Path) -> None:
    root = _root(tmp_path)
    connector = DatedRecoveryConnector()
    connector.failures["2026-09-02"] = GarminConnectorError("Garmin recovery 원본을 하나도 가져오지 못했습니다.")
    use_case = _use_case(root, connector)

    result = use_case.execute_range(date(2026, 9, 1), date(2026, 9, 3))

    assert [(item.calendar_date, item.status) for item in result.outcomes] == [
        ("2026-09-01", "created"),
        ("2026-09-02", "failed"),
        ("2026-09-03", "created"),
    ]
    assert not result.complete
    assert result.aborted_reason is None
    assert [row[0] for row in _rows(root)] == ["2026-09-01", "2026-09-03"]
    output = render_recovery_range_result(result)
    assert "실패: 1일" in output
    assert "실패: 2026-09-02" in output
    output.encode("cp949")

    del connector.failures["2026-09-02"]
    retry = use_case.execute_range(date(2026, 9, 1), date(2026, 9, 3))
    assert [item.status for item in retry.outcomes] == ["unchanged", "created", "unchanged"]
    assert retry.complete


def test_authentication_failure_stops_remaining_dates(tmp_path: Path) -> None:
    connector = DatedRecoveryConnector()
    connector.failures["2026-09-02"] = GarminAuthenticationError("Garmin recovery 인증에 실패했습니다.")

    result = _use_case(_root(tmp_path), connector).execute_range(date(2026, 9, 1), date(2026, 9, 4))

    assert connector.calls == ["2026-09-01", "2026-09-02"]
    assert [item.status for item in result.outcomes] == ["created", "failed", "not_attempted", "not_attempted"]
    assert result.aborted_reason is not None
    assert "미시도: 2일" in render_recovery_range_result(result)


def test_consecutive_failures_stop_the_range(tmp_path: Path) -> None:
    connector = DatedRecoveryConnector()
    for day in ("2026-09-01", "2026-09-02", "2026-09-03"):
        connector.failures[day] = GarminConnectorError("throttled")

    result = _use_case(_root(tmp_path), connector).execute_range(date(2026, 9, 1), date(2026, 9, 6))

    assert connector.calls == ["2026-09-01", "2026-09-02", "2026-09-03"]
    assert [item.status for item in result.outcomes].count("not_attempted") == 3


def test_cli_single_date_positional_is_unchanged() -> None:
    args = build_parser().parse_args(["garmin", "recovery", "2026-09-15"])

    assert args.date == "2026-09-15"
    assert (args.from_date, args.to_date, args.yes) == (None, None, False)


def test_cli_parses_recovery_range() -> None:
    args = build_parser().parse_args(["garmin", "recovery", "--from", "2026-09-01", "--to", "2026-09-28", "--yes"])

    assert args.date is None
    assert (args.from_date, args.to_date, args.yes) == ("2026-09-01", "2026-09-28", True)


@pytest.mark.parametrize(
    ("argv", "message"),
    [
        (["garmin", "recovery"], "--from/--to"),
        (["garmin", "recovery", "--from", "2026-09-01"], "--from과 --to"),
        (["garmin", "recovery", "2026-09-01", "--from", "2026-09-01", "--to", "2026-09-02"], "함께"),
        (["garmin", "recovery", "--from", "2026-09-03", "--to", "2026-09-01"], "이후일 수 없습니다"),
        (["garmin", "recovery", "--from", "2026-9-1", "--to", "2026-09-02"], "YYYY-MM-DD"),
        (["garmin", "recovery", "--from", "2026-09-01", "--to", "2026-09-08"], "--yes"),
        (["garmin", "recovery", "--from", "2026-08-01", "--to", "2026-09-28", "--yes"], "최대 31일"),
    ],
)
def test_cli_rejects_invalid_recovery_ranges_before_authentication(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    argv: list[str],
    message: str,
) -> None:
    monkeypatch.setenv("MUSCLE50_HOME", str(tmp_path / "private-muscle50"))
    monkeypatch.setattr(
        PythonGarminConnector,
        "authenticate",
        lambda auth_dir: pytest.fail("authentication must not be attempted"),
    )

    assert main(argv) == 1
    assert message in capsys.readouterr().err


def test_cli_range_reports_partial_failure_with_nonzero_exit(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    root = _root(tmp_path)
    monkeypatch.setenv("MUSCLE50_HOME", str(root))
    connector = DatedRecoveryConnector()
    connector.failures["2026-09-02"] = GarminConnectorError("synthetic failure")
    monkeypatch.setattr(PythonGarminConnector, "authenticate", lambda auth_dir: connector)

    exit_code = main(["garmin", "recovery", "--from", "2026-09-01", "--to", "2026-09-03"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "신규 저장: 2일" in captured.out
    assert "실패: 2026-09-02" in captured.out
    assert "Garmin 요청 약 27회" in captured.err
    assert connector.calls == ["2026-09-01", "2026-09-02", "2026-09-03"]

    del connector.failures["2026-09-02"]
    assert main(["garmin", "recovery", "--from", "2026-09-01", "--to", "2026-09-03"]) == 0
    assert "변경 없음: 2일" in capsys.readouterr().out


def test_cli_confirmed_long_range_runs(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("MUSCLE50_HOME", str(_root(tmp_path)))
    connector = DatedRecoveryConnector()
    monkeypatch.setattr(PythonGarminConnector, "authenticate", lambda auth_dir: connector)

    assert main(["garmin", "recovery", "--from", "2026-09-01", "--to", "2026-09-28", "--yes"]) == 0

    assert len(connector.calls) == 28
    assert "신규 저장: 28일" in capsys.readouterr().out
