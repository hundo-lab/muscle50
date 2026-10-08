"""Telegram Refresh All UNKNOWN v1.2 end to end: bare `/refresh` through `telegram run` and `cli.main`.

No network (`urllib.request.urlopen` fails the test), no Garmin login (a fake connector per activity
behind one patched `authenticate`), a temporary MUSCLE50_HOME and synthetic values only. Covers
AC1-AC6 of docs/specs/telegram-refresh-unknown.md: each target is exactly one `garmin refresh <id>`,
the empty list, the cap, failures and the consecutive-failure stop, the Garmin login stop, the
pending-migration refusal, Ctrl+C, the remaining count (never 0 when unknown) and determinism.
"""

from __future__ import annotations

import html
import sqlite3
import urllib.request
from collections.abc import Callable, Sequence
from datetime import date, timedelta, tzinfo
from pathlib import Path
from typing import Any

import pytest
from test_refresh_activity import MutableConnector
from test_telegram_bot import FakeTelegramApi
from test_telegram_mobile import (
    ALLOWED,
    KST,
    NOW,
    RECOMMEND_JSON,
    START_LINE,
    STOPPED,
    TODAY,
    TOKEN,
    _business_rows,
    _cli,
    _database,
    _json,
    _main_calls,
    _pre,
    _session,
    _tables,
    _tree,
    _update,
)

import muscle50.cli as cli
from muscle50.application.ingest_activity import IngestGarminActivity
from muscle50.config import AppPaths
from muscle50.domain.telegram_commands import (
    REFRESH_ALL_TARGETS_FAILED_TEXT,
    pending_migration_text,
    refresh_all_empty_text,
    refresh_all_progress_text,
    refresh_login_text,
    unexpected_error_text,
)
from muscle50.infrastructure.garmin.client import GarminConnectorError, GarminRawActivity, PythonGarminConnector
from muscle50.infrastructure.raw_store import RawStore
from muscle50.infrastructure.sqlite.database import ActivityRepository
from muscle50.infrastructure.telegram.state_store import JsonHandledUpdateStore

FETCH_FAILED = "Garmin activity 원본 조회에 실패했습니다."


def _fail_network(*args: object, **kwargs: object) -> object:
    pytest.fail("no network in tests")


@pytest.fixture(autouse=True)
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "home"
    monkeypatch.setenv("MUSCLE50_HOME", str(root))
    monkeypatch.setattr(urllib.request, "urlopen", _fail_network)
    monkeypatch.setattr(
        PythonGarminConnector, "authenticate", lambda *args, **kwargs: pytest.fail("must not use Garmin")
    )

    def fixed_timezone(day: date) -> tzinfo:
        return KST

    monkeypatch.setattr(cli, "_local_timezone", fixed_timezone)
    monkeypatch.setattr(cli, "_today", lambda: TODAY)
    monkeypatch.setattr(cli, "_now", lambda: NOW)
    monkeypatch.setattr(cli, "_telegram_sleep", lambda seconds: None)
    _write_config(root)
    return root


@pytest.fixture
def sleeps(home: Path, monkeypatch: pytest.MonkeyPatch) -> list[float]:
    calls: list[float] = []
    monkeypatch.setattr(cli, "_telegram_sleep", calls.append)
    return calls


def _write_config(root: Path) -> None:
    config = root / "config" / "telegram.json"
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(f'{{"bot_token": "{TOKEN}", "allowed_chat_ids": [{ALLOWED}]}}', encoding="utf-8")


# --- a fake Garmin account with one MutableConnector per activity ---------------------------------------------


class FleetConnector:
    def __init__(self) -> None:
        self.connectors: dict[str, MutableConnector] = {}
        self.failing: dict[str, BaseException] = {}
        self.calls: list[str] = []

    def fetch_raw_activity(self, activity_id: str, source_type_key: str) -> GarminRawActivity:
        self.calls.append(activity_id)
        failure = self.failing.get(activity_id)
        if failure is not None:
            raise failure
        return self.connectors[activity_id].fetch_raw_activity(activity_id, source_type_key)

    def fix(self, activity_id: str, *categories: str) -> None:
        """The user renamed the exercises in Garmin Connect: the next fetch returns ``categories``."""
        connector = self.connectors[activity_id]
        connector.exercise_sets = _sets(activity_id, *categories)
        connector.version = 2


def _payload(activity_id: str, day: date, type_key: str = "strength_training") -> dict[str, Any]:
    return {
        "activityId": int(activity_id),
        "activityName": f"Synthetic {type_key} {activity_id}",
        "activityTypeDTO": {"typeKey": type_key},
        "duration": 1200,
        "distance": 500.0,
        "startTimeLocal": f"{day.isoformat()} 18:00:00",
        "startTimeGMT": f"{day.isoformat()} 09:00:00",
    }


def _sets(activity_id: str, *categories: str) -> dict[str, Any]:
    exercise_sets = []
    for index, category in enumerate(categories):
        exercise = {"category": category, "probability": 0} if category == "UNKNOWN" else {"category": category}
        active = {"messageIndex": 2 * index, "setType": "ACTIVE", "repetitionCount": 10, "weight": 60000}
        exercise_sets += [
            {**active, "exercises": [exercise]},
            {"messageIndex": 2 * index + 1, "setType": "REST", "duration": 45},
        ]
    return {"activityId": int(activity_id), "exerciseSets": exercise_sets}


def _import(fleet: FleetConnector, activity_id: str, day: date, *categories: str, type_key: str = "") -> None:
    """Stores the activity in the current MUSCLE50_HOME as `garmin latest` would."""
    payload = _payload(activity_id, day, type_key or "strength_training")
    connector = MutableConnector(payload, exercise_sets=_sets(activity_id, *categories) if categories else None)
    paths = AppPaths.from_environment()
    paths.ensure_directories()
    repository = ActivityRepository(paths.database_path)
    repository.migrate()
    IngestGarminActivity(connector, repository, RawStore(paths.raw_dir, paths.root, paths.tmp_dir)).execute(payload)
    fleet.connectors[activity_id] = connector


def _fillers(fleet: FleetConnector) -> None:
    """Never targets: today's session, one 15 days old, a swim, and a strength session without UNKNOWN."""
    _import(fleet, "9100", TODAY, "UNKNOWN", "UNKNOWN")
    _import(fleet, "9101", TODAY - timedelta(days=15), "UNKNOWN")
    _import(fleet, "9102", TODAY - timedelta(days=3), type_key="lap_swimming")
    _import(fleet, "9103", TODAY - timedelta(days=4), "BENCH_PRESS", "BENCH_PRESS")


def _three_targets() -> FleetConnector:
    """10-05 fixed in Garmin (2 -> 0), 10-02 partly fixed (3 -> 1), 09-23 not changed (1 -> 1)."""
    fleet = FleetConnector()
    _fillers(fleet)
    _import(fleet, "8001", TODAY - timedelta(days=2), "BENCH_PRESS", "UNKNOWN", "UNKNOWN")
    _import(fleet, "8002", TODAY - timedelta(days=5), "UNKNOWN", "UNKNOWN", "UNKNOWN")
    _import(fleet, "8003", TODAY - timedelta(days=14), "UNKNOWN")
    fleet.fix("8001", "BENCH_PRESS", "BENCH_PRESS", "BENCH_PRESS")
    fleet.fix("8002", "BENCH_PRESS", "BENCH_PRESS", "UNKNOWN")
    return fleet


def _use_fleet(monkeypatch: pytest.MonkeyPatch, fleet: FleetConnector) -> list[Path]:
    calls: list[Path] = []

    def authenticate(auth_dir: Path, *args: Any, **kwargs: Any) -> FleetConnector:
        calls.append(auth_dir)
        return fleet

    monkeypatch.setattr(PythonGarminConnector, "authenticate", authenticate)
    return calls


def _reply(pre: Sequence[str], *tail: str) -> str:
    """A result reply: the `<pre>` body, then each tail line as plain (escaped) text."""
    return _pre("\n".join(pre)) + "".join(f"\n{html.escape(line, quote=False)}" for line in tail)


def _rows_of(database: Path, activity_id: str) -> dict[str, list[tuple[Any, ...]]]:
    rows = _business_rows(database)
    return {
        "strength_sets": [row for row in rows["strength_sets"] if row[0] == activity_id],
        "captures": [row for row in rows["captures"] if row[1] == activity_id],
    }


def _console(*lines: str) -> str:
    return "\n".join([START_LINE, *lines]) + ("\n" + STOPPED)


def _remove_migration_marker(database: Path, version: int) -> None:
    connection = sqlite3.connect(database)
    try:
        connection.execute("DELETE FROM schema_migrations WHERE version = ?", (version,))
        connection.commit()
    finally:
        connection.close()


# --- AC1 --------------------------------------------------------------------------------------------------------


def test_refresh_all_refreshes_each_target_in_json_order(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    home: Path,
    tmp_path: Path,
    sleeps: list[float],
) -> None:
    # The same data refreshed with three separate CLI runs, in a separate home.
    cli_home = tmp_path / "cli-home"
    monkeypatch.setenv("MUSCLE50_HOME", str(cli_home))
    _use_fleet(monkeypatch, _three_targets())
    for activity_id in ("8001", "8002", "8003"):
        code, _, err = _cli(capsys, "garmin", "refresh", activity_id)
        assert code == 0, err

    monkeypatch.setenv("MUSCLE50_HOME", str(home))
    fleet = _three_targets()
    document = _json(capsys, *RECOMMEND_JSON)
    assert [notice["source_activity_id"] for notice in document["strength"]["unknown_notices"]] == [
        "8001",
        "8002",
        "8003",
    ]
    authentications = _use_fleet(monkeypatch, fleet)
    main_calls = _main_calls(monkeypatch)

    sent, err = _session(monkeypatch, capsys, "/refresh")

    assert sent == [
        _pre(refresh_all_progress_text(3, 3)),
        _reply(
            [
                "refresh 완료: 3개 중 3개 받음",
                "• 10-05 8001: UNKNOWN 2 → 0세트",
                "• 10-02 8002: UNKNOWN 3 → 1세트 (아직 남음)",
                "• 09-23 8003: UNKNOWN 1 → 1세트 (변화 없음)",
            ],
            "남은 UNKNOWN: 2개 운동 · /unknown",
        ),
    ]
    assert refresh_all_progress_text(3, 3) == (
        "refresh 실행 중: UNKNOWN이 있는 운동 3개를 Garmin에서 차례로 다시 받습니다. 끝나면 결과를 보냅니다."
    )
    # JSON order, one `garmin refresh <id>` each, never a filler; the list is read again at the end.
    assert fleet.calls == ["8001", "8002", "8003"]
    assert main_calls == [
        list(RECOMMEND_JSON),
        ["garmin", "refresh", "8001"],
        ["garmin", "refresh", "8002"],
        ["garmin", "refresh", "8003"],
        list(RECOMMEND_JSON),
    ]
    assert len(authentications) == 3  # one authenticate per activity (gate 1, A1)
    assert sleeps == [2, 2]  # between activities, not before the first or after the last
    assert _business_rows(_database(home)) == _business_rows(_database(cli_home))
    assert _business_rows(_database(home))["captures"] == [("garmin", "8001"), ("garmin", "8002"), ("garmin", "8003")]
    remaining = _json(capsys, *RECOMMEND_JSON)["strength"]["unknown_notices"]
    assert [notice["source_activity_id"] for notice in remaining] == ["8002", "8003"]
    assert err == _console(
        "chat 111: /refresh targets -> exit 0",
        "chat 111: /refresh all: 3 activities (cap 10)",
        "chat 111: /refresh all 1/3 -> exit 0",
        "chat 111: /refresh all 2/3 -> exit 0",
        "chat 111: /refresh all 3/3 -> exit 0",
        "chat 111: /refresh remaining -> exit 0",
    )


def test_same_data_same_bytes(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    replies = []
    for name in ("first", "second"):
        root = tmp_path / name
        monkeypatch.setenv("MUSCLE50_HOME", str(root))
        _write_config(root)
        _use_fleet(monkeypatch, _three_targets())
        sent, _ = _session(monkeypatch, capsys, "/refresh")
        replies.append(sent)
    assert replies[0] == replies[1]
    assert len(replies[0]) == 2


# --- AC2 --------------------------------------------------------------------------------------------------------


def test_empty_list_calls_no_garmin(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path, sleeps: list[float]
) -> None:
    _fillers(FleetConnector())
    before = _tables(_database(home))
    main_calls = _main_calls(monkeypatch)
    sent, err = _session(monkeypatch, capsys, "/refresh")
    assert sent == [_pre(refresh_all_empty_text())]
    assert refresh_all_empty_text() == (
        "UNKNOWN 세트가 있는 운동이 없습니다 (최근 14일, 오늘 운동 제외). 다시 받을 것이 없습니다."
    )
    assert main_calls == [list(RECOMMEND_JSON)]  # `authenticate` fails the test if it is called
    assert sleeps == []
    assert _tables(_database(home)) == before
    assert err == _console("chat 111: /refresh targets -> exit 0", "chat 111: /refresh all: no UNKNOWN activities")


# --- AC3 --------------------------------------------------------------------------------------------------------


def test_cap_takes_the_newest_ten_and_reports_the_rest(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path, sleeps: list[float]
) -> None:
    fleet = FleetConnector()
    ids = [f"{8100 + offset}" for offset in range(1, 12)]  # 8101 is the newest (yesterday), 8111 the oldest
    for offset, activity_id in enumerate(ids, start=1):
        _import(fleet, activity_id, TODAY - timedelta(days=offset), "UNKNOWN")
        fleet.fix(activity_id, "BENCH_PRESS")
    oldest = _rows_of(_database(home), "8111")
    authentications = _use_fleet(monkeypatch, fleet)

    sent, err = _session(monkeypatch, capsys, "/refresh")

    assert fleet.calls == ids[:10]
    assert len(authentications) == 10
    assert sleeps == [2] * 9
    assert sent[0] == _pre(refresh_all_progress_text(10, 11))
    assert refresh_all_progress_text(10, 11) == (
        "refresh 실행 중: UNKNOWN이 있는 운동 11개 중 최근 10개를 Garmin에서 차례로 다시 받습니다(한 번에 10개까지). "
        "끝나면 결과를 보냅니다."
    )
    items = [
        f"• {(TODAY - timedelta(days=offset)).isoformat()[5:]} {activity_id}: UNKNOWN 1 → 0세트"
        for offset, activity_id in enumerate(ids[:10], start=1)
    ]
    assert sent[1:] == [
        _reply(
            ["refresh 완료: 10개 중 10개 받음", *items],
            "나머지 1개는 받지 않았습니다(한 번에 10개까지). 다시 받기: /refresh · 목록: /unknown",
            "남은 UNKNOWN: 1개 운동 · /unknown",
        )
    ]
    assert _rows_of(_database(home), "8111") == oldest
    assert "chat 111: /refresh all: 10 of 11 activities (cap 10)" in err.split("\n")


# --- AC4 --------------------------------------------------------------------------------------------------------


def test_one_failure_continues_and_shows_the_cli_error(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    fleet = _three_targets()
    fleet.failing["8002"] = GarminConnectorError(FETCH_FAILED)
    failed_before = _rows_of(_database(home), "8002")
    _use_fleet(monkeypatch, fleet)

    sent, err = _session(monkeypatch, capsys, "/refresh")

    assert fleet.calls == ["8001", "8002", "8003"]
    assert sent[1] == _reply(
        [
            "refresh 완료: 3개 중 2개 받음, 1개 실패",
            "• 10-05 8001: UNKNOWN 2 → 0세트",
            "• 10-02 8002: 실패",
            f"  오류: {FETCH_FAILED}",
            "• 09-23 8003: UNKNOWN 1 → 1세트 (변화 없음)",
        ],
        "남은 UNKNOWN: 2개 운동 · /unknown",
    )
    assert _rows_of(_database(home), "8002") == failed_before
    assert "chat 111: /refresh all 2/3 -> exit 1" in err.split("\n")
    # The failure line is the CLI's own error for the same activity, verbatim.
    code, out, cli_err = _cli(capsys, "garmin", "refresh", "8002")
    assert (code, out, cli_err) == (1, "", f"오류: {FETCH_FAILED}\n")


def test_three_consecutive_failures_stop_the_run(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path, sleeps: list[float]
) -> None:
    fleet = FleetConnector()
    ids = ["8201", "8202", "8203", "8204", "8205"]
    for offset, activity_id in enumerate(ids, start=1):
        _import(fleet, activity_id, TODAY - timedelta(days=offset), "UNKNOWN")
        fleet.fix(activity_id, "BENCH_PRESS")
    for activity_id in ids[:3]:
        fleet.failing[activity_id] = GarminConnectorError(FETCH_FAILED)
    _use_fleet(monkeypatch, fleet)

    sent, err = _session(monkeypatch, capsys, "/refresh")

    assert fleet.calls == ids[:3]
    assert sleeps == [2, 2]
    assert sent[1] == _reply(
        [
            "refresh 중단: 5개 중 0개 받음, 3개 실패, 2개 받지 않음 (연속 3번 실패)",
            "• 10-06 8201: 실패",
            f"  오류: {FETCH_FAILED}",
            "• 10-05 8202: 실패",
            f"  오류: {FETCH_FAILED}",
            "• 10-04 8203: 실패",
            f"  오류: {FETCH_FAILED}",
            "• 10-03 8204: 받지 않음",
            "• 10-02 8205: 받지 않음",
        ],
        "Garmin 쪽 제한이나 장애일 수 있습니다. 잠시 뒤 다시 받기: /refresh",
        "남은 UNKNOWN: 5개 운동 · /unknown",
    )
    assert "chat 111: /refresh all stopped after 3 consecutive failures" in err.split("\n")

    # A success in between resets the count: fail, ok, fail, fail, ok runs to the end.
    fleet.calls.clear()
    fleet.failing = {activity_id: GarminConnectorError(FETCH_FAILED) for activity_id in ("8201", "8203", "8204")}
    sent, err = _session(monkeypatch, capsys, "/refresh", first_id=2)
    assert fleet.calls == ids
    assert sent[1].split("\n")[0] == "<pre>refresh 완료: 5개 중 2개 받음, 3개 실패"
    assert "stopped after" not in err


# --- AC5 --------------------------------------------------------------------------------------------------------


def _interactive_after(monkeypatch: pytest.MonkeyPatch, fleet: FleetConnector, successes: int) -> list[int]:
    """An `authenticate` that answers ``successes`` times, then asks for a login on the bot's empty stdin."""
    calls: list[int] = []

    def authenticate(auth_dir: Path, input_fn: Callable[[str], str] = input, **kwargs: object) -> object:
        calls.append(len(calls))
        if len(calls) <= successes:
            return fleet
        input_fn("Garmin email: ")  # `garmin refresh` passes no input_fn: the real input() on an empty stdin
        raise AssertionError("input must raise EOFError: the bot has no keyboard")

    monkeypatch.setattr(PythonGarminConnector, "authenticate", authenticate)
    return calls


def test_login_needed_stops_at_the_first_activity(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path, sleeps: list[float]
) -> None:
    fleet = _three_targets()
    calls = _interactive_after(monkeypatch, fleet, 0)
    before = _tables(_database(home))
    raw_before = {path: digest for path, digest in _tree(home).items() if path.startswith("raw/")}

    sent, err = _session(monkeypatch, capsys, "/refresh")

    assert sent == [
        _pre(refresh_all_progress_text(3, 3)),
        _reply(
            [
                "refresh 중단: 3개 중 0개 받음, 3개 받지 않음 (Garmin 로그인 필요)",
                "• 10-05 8001: 받지 않음",
                "• 10-02 8002: 받지 않음",
                "• 09-23 8003: 받지 않음",
                refresh_login_text("8001"),
            ],
            "로그인한 뒤 나머지 다시 받기: /refresh",
            "남은 UNKNOWN: 3개 운동 · /unknown",
        ),
    ]
    assert len(calls) == 1 and fleet.calls == [] and sleeps == []
    assert _tables(_database(home)) == before
    assert {path: digest for path, digest in _tree(home).items() if path.startswith("raw/")} == raw_before
    assert "chat 111: /refresh all needs a Garmin login in a terminal" in err.split("\n")


def test_login_needed_midway_keeps_the_first_refresh(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    fleet = _three_targets()
    _interactive_after(monkeypatch, fleet, 1)

    sent, _ = _session(monkeypatch, capsys, "/refresh")

    assert sent[1] == _reply(
        [
            "refresh 중단: 3개 중 1개 받음, 2개 받지 않음 (Garmin 로그인 필요)",
            "• 10-05 8001: UNKNOWN 2 → 0세트",
            "• 10-02 8002: 받지 않음",
            "• 09-23 8003: 받지 않음",
            refresh_login_text("8002"),
        ],
        "로그인한 뒤 나머지 다시 받기: /refresh",
        "남은 UNKNOWN: 2개 운동 · /unknown",
    )
    assert fleet.calls == ["8001"]
    assert _business_rows(_database(home))["captures"] == [("garmin", "8001")]


# --- AC6 --------------------------------------------------------------------------------------------------------


def test_pending_migration_refuses_before_anything(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    _three_targets()
    _remove_migration_marker(_database(home), 10)
    before = _tables(_database(home))
    main_calls = _main_calls(monkeypatch)
    sent, err = _session(monkeypatch, capsys, "/refresh")
    assert sent == [_pre(pending_migration_text((10,)))]  # no list read, no progress message
    assert main_calls == []
    assert _tables(_database(home)) == before
    assert err == _console("chat 111: /refresh not run (migration 010 not applied)")


# --- Ctrl+C, unexpected errors, at most once ---------------------------------------------------------------------


def test_ctrl_c_stops_without_a_reply_and_is_not_rerun(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    fleet = _three_targets()
    fleet.failing["8002"] = KeyboardInterrupt()  # `garmin refresh` exits 130
    _use_fleet(monkeypatch, fleet)
    sent, err = _session(monkeypatch, capsys, "/refresh")
    assert sent == [_pre(refresh_all_progress_text(3, 3))]
    assert fleet.calls == ["8001", "8002"]
    assert _business_rows(_database(home))["captures"] == [("garmin", "8001")]  # the first one stays stored
    assert err == _console(
        "chat 111: /refresh targets -> exit 0",
        "chat 111: /refresh all: 3 activities (cap 10)",
        "chat 111: /refresh all 1/3 -> exit 0",
        "chat 111: /refresh interrupted by Ctrl+C; it will not be run again",
    )

    main_calls = _main_calls(monkeypatch)
    sent, _ = _session(monkeypatch, capsys, "/refresh")  # the same update id after a restart
    assert sent == [] and main_calls == []


def test_ctrl_c_during_the_pause_stops_the_run(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    fleet = _three_targets()
    _use_fleet(monkeypatch, fleet)

    def interrupted(seconds: float) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(cli, "_telegram_sleep", interrupted)
    sent, err = _session(monkeypatch, capsys, "/refresh")
    assert sent == [_pre(refresh_all_progress_text(3, 3))]
    assert fleet.calls == ["8001"]
    assert "chat 111: /refresh interrupted by Ctrl+C; it will not be run again" in err.split("\n")


def test_unexpected_exception_stops_the_run(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    fleet = _three_targets()
    _use_fleet(monkeypatch, fleet)
    refresh = cli._garmin_refresh

    def crashing(activity_id: str) -> int:
        if activity_id == "8002":
            raise RuntimeError("synthetic local failure")
        return refresh(activity_id)

    monkeypatch.setattr(cli, "_garmin_refresh", crashing)
    sent, err = _session(monkeypatch, capsys, "/refresh")
    assert sent[1] == _reply(
        [
            "refresh 중단: 3개 중 1개 받음, 1개 실패, 1개 받지 않음 (예상하지 못한 오류)",
            "• 10-05 8001: UNKNOWN 2 → 0세트",
            "• 10-02 8002: 실패",
            "• 09-23 8003: 받지 않음",
            unexpected_error_text("RuntimeError"),
        ],
        "남은 UNKNOWN: 2개 운동 · /unknown",
    )
    assert fleet.calls == ["8001"]
    lines = err.split("\n")
    assert "chat 111: /refresh all failed with RuntimeError" in lines
    assert "RuntimeError: synthetic local failure" in lines


def test_bulk_run_is_one_handled_update(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    fleet = _three_targets()
    _use_fleet(monkeypatch, fleet)
    store = JsonHandledUpdateStore(AppPaths.from_environment().telegram_state_path)
    seen: list[tuple[int, ...]] = []
    main = cli.main

    def spy(argv: Sequence[str] | None = None) -> int:
        handled = store.load()
        seen.append(handled.update_ids if handled is not None else ())
        return main(argv)

    monkeypatch.setattr(cli, "main", spy)
    fake = FakeTelegramApi([_update(7, "/refresh")])
    monkeypatch.setattr(cli, "_telegram_api", lambda token: fake)
    assert main(["telegram", "run"]) == 130
    capsys.readouterr()
    assert seen == [(7,)] * 5  # saved before the first CLI run, and only once for the whole run
    handled = store.load()
    assert handled is not None and handled.update_ids == (7,)


# --- the item lines and the remaining count ----------------------------------------------------------------------


def test_counts_unavailable_use_the_cli_headline_and_warnings_are_kept(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fleet = FleetConnector()
    _import(fleet, "8301", TODAY - timedelta(days=2), "UNKNOWN")
    fleet.fix("8301", "BENCH_PRESS")
    fleet.connectors["8301"].warnings = ("synthetic endpoint warning",)
    _use_fleet(monkeypatch, fleet)
    monkeypatch.setattr(cli, "_telegram_unknown_sets", lambda paths, activity_id: None)
    sent, _ = _session(monkeypatch, capsys, "/refresh")
    assert sent[1] == _reply(
        [
            "refresh 완료: 1개 중 1개 받음",
            "• 10-05 8301: Garmin activity refresh complete",
            "  경고: synthetic endpoint warning",
        ],
        "남은 UNKNOWN 운동 없음 (최근 14일, 오늘 운동 제외)",
    )


def _second_recommend(monkeypatch: pytest.MonkeyPatch, replacement: Callable[[], int]) -> None:
    recommend = cli._recommend
    calls: list[int] = []

    def wrapped(*args: Any, **kwargs: Any) -> int:
        calls.append(1)
        return replacement() if len(calls) == 2 else recommend(*args, **kwargs)

    monkeypatch.setattr(cli, "_recommend", wrapped)


def _prints(text: str, code: int) -> Callable[[], int]:
    def replacement() -> int:
        print(text)
        return code

    return replacement


def _raises() -> int:
    raise RuntimeError("synthetic")


@pytest.mark.parametrize(
    ("replacement", "log"),
    [
        (_prints("plain text", 0), "chat 111: /refresh remaining count unknown (JSONDecodeError)"),
        (_prints('{"strength": {}}', 0), "chat 111: /refresh remaining count unknown (SummaryUnavailableError)"),
        (lambda: 1, "chat 111: /refresh remaining count unknown (JSONDecodeError)"),
        (_raises, "chat 111: /refresh remaining failed with RuntimeError"),
    ],
    ids=["not-json", "shape", "no-output", "exception"],
)
def test_remaining_is_unknown_not_zero_when_the_final_list_fails(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], replacement: Callable[[], int], log: str
) -> None:
    fleet = FleetConnector()
    _import(fleet, "8401", TODAY - timedelta(days=2), "UNKNOWN")
    fleet.fix("8401", "BENCH_PRESS")
    _use_fleet(monkeypatch, fleet)
    _second_recommend(monkeypatch, replacement)
    sent, err = _session(monkeypatch, capsys, "/refresh")
    assert sent[1] == _reply(
        ["refresh 완료: 1개 중 1개 받음", "• 10-05 8401: UNKNOWN 1 → 0세트"], "남은 UNKNOWN: 알 수 없음 · /unknown"
    )
    assert log in err.split("\n")


def test_target_list_failures_never_touch_garmin(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    code, out, no_database = _cli(capsys, *RECOMMEND_JSON)
    assert (code, out) == (1, "") and no_database.startswith("오류: ")
    main_calls = _main_calls(monkeypatch)
    sent, _ = _session(monkeypatch, capsys, "/refresh")
    assert sent == [_pre(no_database.removesuffix("\n"))]
    assert main_calls == [list(RECOMMEND_JSON)]

    def run(stdout: str, first_id: int) -> tuple[list[str], str]:
        monkeypatch.setattr(cli, "_recommend", lambda *args, **kwargs: _prints(stdout, 0)())
        return _session(monkeypatch, capsys, "/refresh", first_id=first_id)

    sent, err = run("plain <text> & more", 2)
    assert sent == [_pre("plain <text> & more")]
    assert "chat 111: /refresh reply was not JSON; relayed as text" in err.split("\n")

    for first_id, document in enumerate(
        [
            '{"as_of": "2026-10-07"}',
            '{"strength": {"unknown_notices": [{"source_activity_id": "x1", "local_date": "2026-10-05", '
            '"unknown_set_count": 1}]}}',
            '{"strength": {"unknown_notices": [{"source_activity_id": "8001", "local_date": "2026-10-05", '
            '"unknown_set_count": true}]}}',
        ],
        start=3,
    ):
        sent, err = run(document, first_id)
        assert sent == [_pre(REFRESH_ALL_TARGETS_FAILED_TEXT)]
        assert any(line.startswith("chat 111: /refresh summary failed (") for line in err.split("\n"))
    assert REFRESH_ALL_TARGETS_FAILED_TEXT == (
        "오류: UNKNOWN 목록을 읽지 못해 아무것도 다시 받지 않았습니다. 전체: /today full"
    )
    # `authenticate` fails the test if called; no run reached `garmin refresh`.
    assert all(call[:2] != ["garmin", "refresh"] for call in main_calls)
