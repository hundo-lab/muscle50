"""`muscle50 garmin sync --from --to [--yes] [--json]` (Daily Catch-up v1): one login, the daily sync stages over
an explicit range, no recommendation. Fake Garmin only, a temporary MUSCLE50_HOME, synthetic values.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pytest
import sync_coverage_builders as builders

import muscle50.cli as cli
from muscle50.application.sync_garmin_recovery import MAX_RECOVERY_RANGE_DAYS, RECOVERY_ENDPOINTS_PER_DATE
from muscle50.cli import main
from muscle50.domain.sync_catch_up import GARMIN_SYNC_UNCONFIRMED_MAX_DAYS
from muscle50.infrastructure.garmin.client import GarminConnectorError, PythonGarminConnector

TODAY = date(2026, 10, 2)


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "home"
    monkeypatch.setenv("MUSCLE50_HOME", str(root))
    monkeypatch.setattr(cli, "_today", lambda: TODAY)
    monkeypatch.setattr(cli, "_local_timezone", lambda day: builders.KST)
    return root


def _use(monkeypatch: pytest.MonkeyPatch, garmin: builders.FakeGarmin) -> list[Path]:
    logins: list[Path] = []

    def authenticate(auth_dir: Path, **_kwargs: Any) -> builders.FakeGarmin:
        logins.append(auth_dir)
        return garmin

    monkeypatch.setattr(PythonGarminConnector, "authenticate", authenticate)
    return logins


def _run(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, str, str]:
    code = main(list(argv))
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def _dates(start: date, end: date) -> list[str]:
    return [(start + timedelta(days=offset)).isoformat() for offset in range((end - start).days + 1)]


def _coverage(root: Path) -> list[tuple[str, str, str, str]]:
    with sqlite3.connect(root / "db" / "muscle50.sqlite3") as connection:
        return list(
            connection.execute(
                "SELECT data_kind, calendar_date, status, command FROM sync_coverage ORDER BY data_kind, calendar_date"
            )
        )


def test_the_constants_mirror_garmin_recovery() -> None:
    assert GARMIN_SYNC_UNCONFIRMED_MAX_DAYS == cli._RECOVERY_UNCONFIRMED_MAX_DAYS == 7
    assert (MAX_RECOVERY_RANGE_DAYS, RECOVERY_ENDPOINTS_PER_DATE) == (31, 9)


def test_garmin_sync_text_runs_every_sync_stage_with_one_login(
    home: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    garmin = builders.daily_account()
    logins = _use(monkeypatch, garmin)

    code, out, err = _run(capsys, "garmin", "sync", "--from", "2026-09-28", "--to", "2026-10-02")

    assert code == 0, err
    assert err == "muscle50 garmin sync 2026-09-28..2026-10-02 (5 days, about 45 recovery requests)\n"
    assert len(logins) == 1
    assert garmin.recovery_calls == _dates(date(2026, 9, 28), TODAY)
    assert sorted(garmin.activity_calls) == ["100", "222", "300"]
    assert out.split("\n") == [
        "muscle50 garmin sync 2026-09-28..2026-10-02",
        "Stages:",
        "  garmin_login: ok",
        "  activities: ok (2026-09-28..2026-10-02: found 3, new 3, already stored 0, failed 0)",
        "  load_metrics: ok (metric rows inserted 4, updated 0, unchanged 0)",
        "  recovery: ok (2026-09-28..2026-10-02: created 5, updated 0, unchanged 0, failed 0, not attempted 0)",
        "  recommendation: skipped",
        "Synced. No recommendation was built; plan today with: muscle50 daily",
        "",
    ]
    assert out.isascii()
    days = _dates(date(2026, 9, 28), TODAY)
    # The account answers three of the nine recovery endpoints, so recovery is partial (as for `daily`).
    assert _coverage(home) == [
        *(("activities", day, "synced", "garmin sync") for day in days),
        *(("recovery", day, "partial", "garmin sync") for day in days),
    ]


def test_garmin_sync_json_is_the_daily_document_without_a_recommendation(
    home: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _use(monkeypatch, builders.daily_account())

    code, out, err = _run(capsys, "garmin", "sync", "--from", "2026-10-01", "--to", "2026-10-02", "--json")

    assert code == 0, err
    document = json.loads(out)
    assert out == json.dumps(document, indent=2) + "\n"
    assert out.isascii()
    assert list(document) == [
        "as_of",
        "mode",
        "sync_from",
        "ok",
        "failed_stages",
        "stages",
        "activities",
        "load_metrics",
        "recovery",
        "recommendation",
    ]
    assert (document["as_of"], document["mode"], document["sync_from"], document["ok"]) == (
        "2026-10-02",
        "sync",
        "2026-10-01",
        True,
    )
    assert [(stage["stage"], stage["status"]) for stage in document["stages"]] == [
        ("garmin_login", "ok"),
        ("activities", "ok"),
        ("load_metrics", "ok"),
        ("recovery", "ok"),
        ("recommendation", "skipped"),
    ]
    assert document["recommendation"] is None
    assert document["activities"]["inserted"] == 2


def test_more_than_seven_days_needs_yes(
    home: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    garmin = builders.daily_account()
    _use(monkeypatch, garmin)
    code, out, err = _run(capsys, "garmin", "sync", "--from", "2026-09-23", "--to", "2026-10-02", "--yes", "--json")
    assert code == 0, err
    assert err == "muscle50 garmin sync 2026-09-23..2026-10-02 (10 days, about 90 recovery requests)\n"
    assert garmin.recovery_calls == _dates(date(2026, 9, 23), TODAY)
    assert json.loads(out)["sync_from"] == "2026-09-23"


@pytest.mark.parametrize(
    ("argv", "message"),
    [
        (("--from", "2026-9-28", "--to", "2026-10-02"), "오류: --from/--to는 YYYY-MM-DD 형식이어야 합니다."),
        (("--from", "2026-09-28", "--to", "2026-02-30"), "오류: --from/--to는 YYYY-MM-DD 형식이어야 합니다."),
        (("--from", "2026-10-02", "--to", "2026-09-28"), "오류: --from은 --to보다 이후일 수 없습니다."),
        (("--from", "2026-09-28", "--to", "2026-10-03"), "오류: --to는 오늘(2026-10-02) 이후일 수 없습니다."),
        (("--from", "2026-08-24", "--to", "2026-10-02", "--yes"), "오류: 범위는 최대 31일입니다 (요청: 40일)."),
        (
            ("--from", "2026-09-23", "--to", "2026-10-02"),
            "오류: 10일 범위는 Garmin 요청 약 90회가 필요합니다. 계속하려면 --yes를 추가하세요.",
        ),
    ],
)
def test_refusals_happen_before_any_directory_or_login(
    home: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    argv: tuple[str, ...],
    message: str,
) -> None:
    monkeypatch.setattr(
        PythonGarminConnector, "authenticate", lambda *args, **kwargs: pytest.fail("refused requests never log in")
    )
    code, out, err = _run(capsys, "garmin", "sync", *argv)
    assert (code, out, err) == (1, "", message + "\n")
    assert not home.exists()


def test_the_longest_ranges_are_accepted(
    home: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    garmin = builders.daily_account()
    _use(monkeypatch, garmin)
    code, _, err = _run(capsys, "garmin", "sync", "--from", "2026-09-26", "--to", "2026-10-02", "--json")
    assert code == 0, err  # 7 days: no --yes
    code, _, err = _run(capsys, "garmin", "sync", "--from", "2026-09-02", "--to", "2026-10-02", "--yes", "--json")
    assert code == 0, err  # 31 days with --yes
    assert len(garmin.recovery_calls) == 7 + 31


def test_a_failed_stage_exits_one_and_says_so(
    home: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    failure = GarminConnectorError("synthetic recovery failure")
    _use(monkeypatch, builders.daily_account(recovery_failures={"2026-10-01": failure}))

    code, out, _ = _run(capsys, "garmin", "sync", "--from", "2026-10-01", "--to", "2026-10-02")

    assert code == 1
    lines = out.split("\n")
    assert (
        "  recovery: failed (2026-10-01..2026-10-02: created 1, updated 0, unchanged 0, failed 1, not attempted 0)"
        in (lines)
    )
    assert lines[-2] == "FAILED stages: recovery. Data already synced is kept; rerunning the same command is safe."
    assert "recommendation: skipped" in out


def test_a_login_failure_is_a_failed_stage(
    home: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def refused(*args: object, **kwargs: object) -> object:
        raise GarminConnectorError("Garmin 인증에 실패했습니다.")

    monkeypatch.setattr(PythonGarminConnector, "authenticate", refused)
    code, out, _ = _run(capsys, "garmin", "sync", "--from", "2026-10-01", "--to", "2026-10-02", "--json")
    document = json.loads(out)
    assert (code, document["failed_stages"]) == (1, ["garmin_login"])
    assert [stage["status"] for stage in document["stages"]] == ["failed", "not_run", "not_run", "not_run", "skipped"]


def test_a_login_prompt_without_input_propagates(
    home: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # The Telegram bot turns this EOFError into its login reply (as for `daily`).
    def prompt(*args: object, **kwargs: object) -> object:
        raise EOFError

    monkeypatch.setattr(PythonGarminConnector, "authenticate", prompt)
    with pytest.raises(EOFError):
        main(["garmin", "sync", "--from", "2026-10-01", "--to", "2026-10-02"])
