"""Telegram Mobile Replies v1.1 end to end: `telegram run` through `cli.main` with a fake Bot API.

No network (`urllib.request.urlopen` fails the test), no Garmin login (fake connectors only), a
temporary MUSCLE50_HOME and synthetic values only. Covers AC1-AC7 of docs/specs/telegram-mobile.md:
the default summaries of `/today`, `/status`, `/daily` and `/unknown` against the same command's
JSON, the byte-identical `full` replies, `/daily` failures and the single sync per message, the
UNKNOWN items, `/refresh` (rows, counts and every refusal), the grammar, and the read-only reader.
"""

from __future__ import annotations

import hashlib
import html
import json
import re
import sqlite3
import urllib.request
from collections.abc import Callable, Sequence
from datetime import date, datetime, timedelta, timezone, tzinfo
from pathlib import Path
from typing import Any

import pytest
import sync_coverage_builders as builders
from analytics_builders import activity, strength_set
from test_refresh_activity import MutableConnector
from test_telegram_bot import BROWN_RICE, CHICKEN, RICE, FakeTelegramApi

import muscle50.cli as cli
from muscle50.application.activity_unknown_sets import CountActivityUnknownSets
from muscle50.application.ingest_activity import IngestGarminActivity
from muscle50.application.telegram_bot import IncomingMessage, IncomingUpdate
from muscle50.cli import main
from muscle50.config import AppPaths
from muscle50.domain.activity import ActivityType, NormalizedActivity
from muscle50.domain.telegram_commands import (
    DAILY_PROGRESS_TEXT,
    CliInvocation,
    ReplyKind,
    UsageReason,
    UsageReply,
    daily_summary_failed_text,
    parse_bot_message,
    pending_migration_text,
    refresh_login_text,
    refresh_progress_text,
    summary_failed_text,
    usage_text,
)
from muscle50.infrastructure.garmin.client import GarminConnectorError, PythonGarminConnector
from muscle50.infrastructure.raw_store import RawArtifact, RawStore
from muscle50.infrastructure.sqlite.analytics_reader import SqliteAnalyticsReader
from muscle50.infrastructure.sqlite.database import ActivityRepository
from muscle50.presentation.telegram_format import telegram_messages
from muscle50.presentation.telegram_summary import TelegramSummaries

KST = timezone(timedelta(hours=9))
TODAY = date(2026, 10, 7)
NOW = datetime(2026, 10, 7, 12, 0, tzinfo=KST)
NOW_TS = int(NOW.timestamp())
TOKEN = "123456789:AAFakeSyntheticToken_ab-cd"
ALLOWED = 111
BOT = "muscle50_example_bot"
START_LINE = "telegram run: bot @muscle50_example_bot is polling for 1 allowed chat. Press Ctrl+C to stop."
STOPPED = "\n취소되었습니다.\n"
GARMIN = "https://connect.garmin.com/modern/activity/"
UNKNOWN_ID = "7001"
RECOMMEND_JSON = ("recommend", "--date", TODAY.isoformat(), "--json")


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
    config = root / "config" / "telegram.json"
    config.parent.mkdir(parents=True)
    config.write_text(json.dumps({"bot_token": TOKEN, "allowed_chat_ids": [ALLOWED]}), encoding="utf-8")
    return root


def _update(update_id: int, text: str | None) -> IncomingUpdate:
    return IncomingUpdate(update_id, IncomingMessage(ALLOWED, text, NOW_TS))


def _session(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], *texts: str, first_id: int = 1
) -> tuple[list[str], str]:
    """One `telegram run` handling ``texts`` as updates first_id.. in order; the sent HTML and the console."""
    fake = FakeTelegramApi([_update(index, text) for index, text in enumerate(texts, start=first_id)])
    monkeypatch.setattr(cli, "_telegram_api", lambda token: fake)
    code = main(["telegram", "run"])
    captured = capsys.readouterr()
    assert (code, captured.out) == (130, "")
    assert all(chat_id == ALLOWED for chat_id, _ in fake.sent)
    return [message for _, message in fake.sent], captured.err


def _plain(message: str) -> str:
    return html.unescape(re.sub(r'</?pre>|</?code>|<a href="[^"]*">|</a>', "", message))


def _pre(text: str) -> str:
    return f"<pre>{html.escape(text, quote=False)}</pre>"


def _cli(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, str, str]:
    code = main(list(argv))
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def _ok(capsys: pytest.CaptureFixture[str], *argv: str) -> str:
    code, out, err = _cli(capsys, *argv)
    assert code == 0, err
    return out


def _database(root: Path) -> Path:
    return root / "db" / "muscle50.sqlite3"


def _tables(database: Path) -> dict[str, list[tuple[Any, ...]]]:
    connection = sqlite3.connect(database)
    try:
        names = [
            row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name")
        ]
        return {name: sorted(connection.execute(f"SELECT * FROM {name}").fetchall(), key=repr) for name in names}
    finally:
        connection.close()


def _tree(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _save(database: Path, item: NormalizedActivity) -> None:
    artifact = RawArtifact("activity", f"raw/{item.source_activity_id}/activity.json", "application/json", "0" * 64, 2)
    ActivityRepository(database).save(item, (artifact,))


def _bench(source_id: str, day: str, *, unknown_sets: int = 0) -> NormalizedActivity:
    sets = [strength_set(index, reps=10, weight_kg=50.0) for index in range(1, 4)]
    sets += [strength_set(4 + index, category="UNKNOWN", reps=8, weight_kg=40.0) for index in range(unknown_sets)]
    return activity(source_id, f"{day}T18:00:00", ActivityType.STRENGTH, strength_sets=tuple(sets))


def _seed(capsys: pytest.CaptureFixture[str], root: Path, *, unknown: bool = True) -> None:
    """Strength history (one session with UNKNOWN sets), recovery rows, a protein target and today's lunch."""
    database = _database(root)
    ActivityRepository(database).migrate()
    _save(database, _bench(UNKNOWN_ID, "2026-10-05", unknown_sets=2 if unknown else 0))
    _save(database, _bench("7002", "2026-10-02"))
    builders.save_recovery(database, "2026-10-06")
    builders.save_recovery(database, "2026-10-07", sleep_seconds=None)
    for food in (CHICKEN, RICE, BROWN_RICE):
        _ok(capsys, "nutrition", "food", "add", *food)
    _ok(capsys, "nutrition", "target", "set", "protein", "--exact", "120")
    _ok(capsys, "nutrition", "log", "--meal", "lunch", "--item", "닭가슴살", "150", "g", "--item", "햇반", "1", "pack")


def _json(capsys: pytest.CaptureFixture[str], *argv: str) -> Any:
    return json.loads(_ok(capsys, *argv))


def _main_calls(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    calls: list[list[str]] = []

    def spy(argv: Sequence[str] | None = None) -> int:
        calls.append(list(argv or ()))
        return main(argv)

    monkeypatch.setattr(cli, "main", spy)
    return calls


# --- grammar and pinned texts ----------------------------------------------------------------------------------


def _parse(text: str) -> CliInvocation | UsageReply:
    return parse_bot_message(text, bot_username=BOT, today=TODAY)


@pytest.mark.parametrize(
    ("text", "reply", "is_daily", "activity_id"),
    [
        ("/today", ReplyKind.TODAY_SUMMARY, False, None),
        ("/today full", ReplyKind.TEXT, False, None),
        ("/status", ReplyKind.STATUS_SUMMARY, False, None),
        ("/status full", ReplyKind.TEXT, False, None),
        ("/daily", ReplyKind.DAILY_SUMMARY, True, None),
        ("/daily full", ReplyKind.TEXT, True, None),
        ("/unknown", ReplyKind.UNKNOWN_LIST, False, None),
        (f"/unknown@{BOT}", ReplyKind.UNKNOWN_LIST, False, None),
        ("/refresh 24610155225", ReplyKind.REFRESH, False, "24610155225"),
        ("/refresh 99999999999999999999", ReplyKind.REFRESH, False, "99999999999999999999"),
        ("/refresh", ReplyKind.REFRESH_ALL, False, None),
        ("/day", ReplyKind.TEXT, False, None),
        ("/inbody", ReplyKind.TEXT, False, None),
    ],
)
def test_reply_kind_of_each_command(text: str, reply: ReplyKind, is_daily: bool, activity_id: str | None) -> None:
    result = _parse(text)
    assert isinstance(result, CliInvocation)
    assert (result.reply, result.is_daily, result.activity_id) == (reply, is_daily, activity_id)


@pytest.mark.parametrize(
    ("text", "command"),
    [
        ("/today x", "today"),
        ("/today FULL", "today"),
        ("/today full x", "today"),
        ("/today 2026-10-05", "today"),
        ("/status now", "status"),
        ("/status full full", "status"),
        ("/daily Full", "daily"),
        ("/daily --json", "daily"),
        ("/unknown x", "unknown"),
        ("/unknown full", "unknown"),
        ("/refresh abc", "refresh"),
        ("/refresh 0", "refresh"),
        ("/refresh 0123", "refresh"),
        ("/refresh 1 2", "refresh"),
        ("/refresh -5", "refresh"),
        ("/refresh 12.5", "refresh"),
        ("/refresh ١٢٣", "refresh"),  # Arabic-Indic digits: int() would accept them
        ("/refresh 1٢٣", "refresh"),  # an ASCII first digit, then Arabic-Indic ones (`\d` would match)
        ("/refresh ２２２", "refresh"),  # fullwidth digits
        ("/refresh 123456789012345678901", "refresh"),  # 21 digits
        ("/refresh_222", None),
    ],
)
def test_malformed_new_commands_get_the_usage(text: str, command: str | None) -> None:
    expected = (
        UsageReply(UsageReason.MALFORMED, command)
        if command is not None
        else UsageReply(UsageReason.UNKNOWN_COMMAND, text)  # no one-tap alias (gate 1, decision 1)
    )
    assert _parse(text) == expected


def test_migration_check_covers_refresh_but_not_unknown() -> None:
    migrating = {text: _parse(text) for text in ("/refresh 1", "/unknown", "/today", "/status", "/daily")}
    assert {text for text, result in migrating.items() if isinstance(result, CliInvocation) and result.migrates} == {
        "/refresh 1",
        "/status",
        "/daily",
    }


def test_new_bot_texts_are_pinned() -> None:
    assert usage_text("today") == "사용법: /today [full]\n예: /today"
    assert usage_text("daily") == "사용법: /daily [full]\n예: /daily"
    assert usage_text("unknown") == "사용법: /unknown\n예: /unknown"
    assert usage_text("refresh") == (
        "사용법: /refresh [activity_id]\n"
        "Garmin Connect에서 운동 이름을 고친 뒤 보냅니다. 인자가 없으면 UNKNOWN 세트가 있는 최근 운동을 모두"
        "(한 번에 10개까지), activity_id(숫자)를 주면 그 운동 하나만 다시 받습니다.\n"
        "예: /refresh 24610155225"
    )
    assert refresh_progress_text("24610155225") == (
        "refresh 실행 중: Garmin에서 운동 24610155225를 다시 받습니다. 끝나면 결과를 보냅니다."
    )
    assert refresh_login_text("24610155225") == (
        "오류: Garmin에 다시 로그인해야 합니다. PC 터미널에서 muscle50 garmin refresh 24610155225를 한 번 "
        "실행하세요(로그인한 뒤 그대로 refresh됩니다)."
    )
    assert summary_failed_text("today") == "오류: 결과를 요약하지 못했습니다. 전체: /today full"
    assert summary_failed_text("unknown") == "오류: 결과를 요약하지 못했습니다. 전체: /today full"
    assert summary_failed_text("status") == "오류: 결과를 요약하지 못했습니다. 전체: /status full"
    assert daily_summary_failed_text(1) == (
        "오류: daily는 끝났지만 결과를 요약하지 못했습니다 (exit 1). 저장된 데이터로 본 전체 계획: /today full"
    )


# --- AC1/AC5: summaries equal the summary of the same command's JSON ---------------------------------------


def test_today_status_unknown_summaries_match_cli_json(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    _seed(capsys, home)
    recommendation = _json(capsys, *RECOMMEND_JSON)
    status = _json(capsys, "nutrition", "status", "--json")
    calls = _main_calls(monkeypatch)

    sent, err = _session(monkeypatch, capsys, "/today", "/status", "/unknown")

    summaries = TelegramSummaries()
    assert sent == [
        *summaries.summary(ReplyKind.TODAY_SUMMARY, recommendation),
        *summaries.summary(ReplyKind.STATUS_SUMMARY, status),
        *summaries.summary(ReplyKind.UNKNOWN_LIST, recommendation),
    ]
    assert len(sent) == 3  # one message each
    # One CLI run per message, and the JSON form (never the text report parsed).
    assert calls == [list(RECOMMEND_JSON), ["nutrition", "status", "--json"], list(RECOMMEND_JSON)]
    assert err == "\n".join(
        [START_LINE, "chat 111: /today -> exit 0", "chat 111: /status -> exit 0", "chat 111: /unknown -> exit 0"]
    ) + ("\n" + STOPPED)

    today = _plain(sent[0]).split("\n")
    notice = recommendation["strength"]["unknown_notices"][0]
    assert (notice["source_activity_id"], notice["local_date"], notice["unknown_set_count"]) == (
        UNKNOWN_ID,
        "2026-10-05",
        2,
    )
    assert today[0] == "오늘 추천 10-07"
    assert "회복: normal (readiness MODERATE 60, HRV BALANCED, 오늘 수면 기록 없음)" in today
    assert today[-5:-2] == [
        "확인 필요: Garmin UNKNOWN 세트",
        f"• 10-05 근력 2세트: {GARMIN}{UNKNOWN_ID}",
        f"  고친 뒤: /refresh {UNKNOWN_ID}",
    ]
    assert today[-2] == "모두 다시 받기: /refresh"
    assert f'<a href="{GARMIN}{UNKNOWN_ID}">{GARMIN}{UNKNOWN_ID}</a>' in sent[0]
    assert f"<code>/refresh {UNKNOWN_ID}</code>" in sent[0]
    protein = status["nutrients"]["protein_g"]
    assert _plain(sent[1]).split("\n") == [
        f"영양 10-07 (UTC{status['timezone']}): 식사 {status['meal_count']}끼, {status['item_count']}개",
        f"kcal {status['nutrients']['calories_kcal']['consumed']} / 목표 없음 (no_target)",
        f"단백질 {protein['consumed']} g / 목표 {protein['target']['value']} g "
        f"({protein['status']}, {protein['remaining']} g 남음)",
        f"탄수화물 {status['nutrients']['carbohydrate_g']['consumed']} g / 목표 없음 (no_target)",
        f"지방 {status['nutrients']['fat_g']['known_subtotal']} g 이상 (값 없는 항목 1개) / 목표 없음 (no_target)",
        "전체: /status full",
    ]
    assert _plain(sent[2]).split("\n")[:2] == [
        "Garmin UNKNOWN 세트가 있는 운동 1개 (최근 14일, 오늘 운동 제외)",
        f"• 10-05 근력 2세트 (세트 4, 5): {GARMIN}{UNKNOWN_ID}",
    ]


def test_without_unknown_sets_there_is_no_section_and_unknown_says_none(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    _seed(capsys, home, unknown=False)
    sent, _ = _session(monkeypatch, capsys, "/today", "/unknown")
    assert "UNKNOWN" not in _plain(sent[0]) and "/refresh" not in sent[0]
    assert sent[1] == _pre("Garmin UNKNOWN 세트가 있는 운동 없음 (최근 14일, 오늘 운동 제외)")


def test_summaries_are_byte_identical_across_sessions(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    _seed(capsys, home)
    first, _ = _session(monkeypatch, capsys, "/today", "/status", "/unknown")
    second, _ = _session(monkeypatch, capsys, "/today", "/status", "/unknown", first_id=4)
    assert first == second


# --- AC2: full is byte-identical to v1 ----------------------------------------------------------------------


def test_full_variants_are_byte_identical_to_v1(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    _seed(capsys, home)

    def refused(*args: object, **kwargs: object) -> object:
        raise GarminConnectorError("Garmin 인증에 실패했습니다.")

    monkeypatch.setattr(PythonGarminConnector, "authenticate", refused)
    today = _ok(capsys, "recommend", "--date", TODAY.isoformat())
    status = _ok(capsys, "nutrition", "status")
    code, daily, _ = _cli(capsys, "daily")
    assert code == 1

    sent, err = _session(monkeypatch, capsys, "/today full", "/status full", "/daily full")

    assert sent == [
        *telegram_messages(today.removesuffix("\n")),
        *telegram_messages(status.removesuffix("\n")),
        _pre(DAILY_PROGRESS_TEXT),
        *telegram_messages(daily.removesuffix("\n")),
    ]
    assert "chat 111: /daily -> exit 1" in err.split("\n")


# --- AC4: /daily -----------------------------------------------------------------------------------------------


def _use_garmin(monkeypatch: pytest.MonkeyPatch, garmin: Any) -> list[Path]:
    calls: list[Path] = []

    def authenticate(auth_dir: Path, **kwargs: Any) -> Any:
        calls.append(auth_dir)
        return garmin

    monkeypatch.setattr(PythonGarminConnector, "authenticate", authenticate)
    return calls


def test_daily_failed_stage_shows_the_cli_error_and_no_plan(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    _seed(capsys, home)
    failure = GarminConnectorError("synthetic recovery <failure> & more")
    calls = _use_garmin(monkeypatch, builders.FakeGarmin([], recovery_failures={"2026-10-06": failure}))
    main_calls = _main_calls(monkeypatch)

    sent, err = _session(monkeypatch, capsys, "/daily")

    assert len(calls) == 1  # one Garmin login: one sync for one message
    assert main_calls == [["daily", "--json"]]
    code, out, _ = _cli(capsys, "daily", "--json")
    document = json.loads(out)
    assert (code, document["ok"], document["failed_stages"]) == (1, False, ["recovery"])
    error = next(stage["error"] for stage in document["stages"] if stage["stage"] == "recovery")
    assert "synthetic recovery <failure> & more" in error
    assert sent == [_pre(DAILY_PROGRESS_TEXT), *TelegramSummaries().summary(ReplyKind.DAILY_SUMMARY, document)]
    warnings = [f"  경고({stage['stage']}): {item}" for stage in document["stages"] for item in stage["warnings"]]
    assert warnings  # the load-metrics stage warns about the seeded rows without RAW: relayed verbatim
    assert _plain(sent[1]).split("\n") == [
        "daily 10-07: 실패 (recovery 단계)",
        f"  recovery: {error}",
        *warnings,
        "추천은 만들지 않았습니다. 이미 받은 데이터는 저장되어 있습니다.",
        "저장된 데이터로 본 계획: /today · 다시 동기화: /daily",
    ]
    assert "&lt;failure&gt; &amp; more" in sent[1]
    assert "chat 111: /daily -> exit 1" in err.split("\n")


def test_daily_login_failure_is_a_failed_garmin_login_stage(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    _seed(capsys, home)
    calls: list[object] = []

    def refused(*args: object, **kwargs: object) -> object:
        calls.append(args)
        raise GarminConnectorError("Garmin 인증에 실패했습니다.")

    monkeypatch.setattr(PythonGarminConnector, "authenticate", refused)
    sent, _ = _session(monkeypatch, capsys, "/daily")
    assert len(calls) == 1
    assert sent[0] == _pre(DAILY_PROGRESS_TEXT)
    lines = _plain(sent[1]).split("\n")
    assert lines[:2] == ["daily 10-07: 실패 (garmin_login 단계)", "  garmin_login: Garmin 인증에 실패했습니다."]
    assert lines[-1] == "저장된 데이터로 본 계획: /today · 다시 동기화: /daily"
    assert "근력" not in _plain(sent[1])


def test_daily_success_summary_has_the_unknown_items(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path, tmp_path: Path
) -> None:
    _seed(capsys, home)
    calls = _use_garmin(monkeypatch, builders.FakeGarmin([]))
    sent, err = _session(monkeypatch, capsys, "/daily")
    assert len(calls) == 1
    assert sent[0] == _pre(DAILY_PROGRESS_TEXT)
    assert len(sent) == 2
    lines = _plain(sent[1]).split("\n")
    assert lines[0] == "daily 10-07: 동기화 완료 (새 운동 0, 회복 2일 갱신)"
    assert lines[-5:] == [
        "확인 필요: Garmin UNKNOWN 세트",
        f"• 10-05 근력 2세트: {GARMIN}{UNKNOWN_ID}",
        f"  고친 뒤: /refresh {UNKNOWN_ID}",
        "모두 다시 받기: /refresh",
        lines[-1],
    ]
    assert lines[-1].startswith("기타 알림 ") and lines[-1].endswith("건 · 전체: /today full")
    assert "chat 111: /daily -> exit 0" in err.split("\n")
    # The same summary as a separate home's `daily --json` with the same data and the same fake account.
    monkeypatch.setenv("MUSCLE50_HOME", str(tmp_path / "cli-home"))
    _seed(capsys, tmp_path / "cli-home")
    document = _json(capsys, "daily", "--json")
    assert sent[1:] == TelegramSummaries().summary(ReplyKind.DAILY_SUMMARY, document)


# --- fallbacks -----------------------------------------------------------------------------------------------


def _prints(text: str, code: int = 0) -> Callable[..., int]:
    def fake(*args: object, **kwargs: object) -> int:
        print(text)
        return code

    return fake


def test_non_json_stdout_is_relayed_as_text(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cli, "_recommend", _prints("plain <text> & more"))
    sent, err = _session(monkeypatch, capsys, "/today")
    assert sent == [_pre("plain <text> & more")]
    assert "chat 111: /today reply was not JSON; relayed as text" in err.split("\n")


def test_unexpected_json_shape_points_to_the_full_text(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cli, "_recommend", _prints('{"as_of": "2026-10-07"}'))
    monkeypatch.setattr(cli, "_daily", _prints('{"as_of": "2026-10-07", "ok": true, "stages": []}', code=0))
    status = cli._nutrition

    def broken_status(args: Any) -> int:
        if args.nutrition_command == "status":
            print("[]")
            return 0
        return status(args)

    monkeypatch.setattr(cli, "_nutrition", broken_status)
    sent, err = _session(monkeypatch, capsys, "/today", "/unknown", "/status", "/daily")
    assert sent == [
        _pre(summary_failed_text("today")),
        _pre(summary_failed_text("unknown")),
        _pre(summary_failed_text("status")),
        _pre(DAILY_PROGRESS_TEXT),
        _pre(daily_summary_failed_text(0)),
    ]
    lines = err.split("\n")
    assert "chat 111: /today summary failed (KeyError)" in lines
    assert "chat 111: /status summary failed (TypeError)" in lines
    assert "chat 111: /daily summary failed (KeyError)" in lines


def test_cli_error_without_stdout_is_relayed_as_in_v1(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    code, out, err = _cli(capsys, *RECOMMEND_JSON)  # no database yet
    assert (code, out) == (1, "")
    sent, _ = _session(monkeypatch, capsys, "/today", "/unknown")
    assert sent == [_pre(err.removesuffix("\n"))] * 2


# --- AC6: /refresh ---------------------------------------------------------------------------------------------


def _strength_payload() -> dict[str, Any]:
    return {
        "activityId": 222,
        "activityName": "Synthetic Strength",
        "activityTypeDTO": {"typeKey": "strength_training"},
        "duration": 1200,
        "startTimeLocal": "2026-10-05 18:00:00",
        "startTimeGMT": "2026-10-05 09:00:00",
    }


def _sets(*categories: str) -> dict[str, Any]:
    exercise_sets = []
    for index, category in enumerate(categories):
        exercise = {"category": category, "probability": 0} if category == "UNKNOWN" else {"category": category}
        active = {"messageIndex": 2 * index, "setType": "ACTIVE", "repetitionCount": 10, "weight": 60000}
        exercise_sets += [
            {**active, "exercises": [exercise]},
            {"messageIndex": 2 * index + 1, "setType": "REST", "duration": 45},
        ]
    return {"activityId": 222, "exerciseSets": exercise_sets}


def _imported(capsys: pytest.CaptureFixture[str], payload: dict[str, Any], exercise_sets: Any) -> MutableConnector:
    """Imports ``payload`` into the current MUSCLE50_HOME as `garmin latest` would; returns the connector."""
    connector = MutableConnector(payload, exercise_sets=exercise_sets)
    paths = AppPaths.from_environment()
    paths.ensure_directories()
    repository = ActivityRepository(paths.database_path)
    repository.migrate()
    IngestGarminActivity(connector, repository, RawStore(paths.raw_dir, paths.root, paths.tmp_dir)).execute(payload)
    return connector


def _use_connector(monkeypatch: pytest.MonkeyPatch, connector: MutableConnector) -> list[Path]:
    calls: list[Path] = []

    def authenticate(auth_dir: Path, *args: Any, **kwargs: Any) -> MutableConnector:
        calls.append(auth_dir)
        return connector

    monkeypatch.setattr(PythonGarminConnector, "authenticate", authenticate)
    return calls


def _business_rows(database: Path) -> dict[str, list[tuple[Any, ...]]]:
    connection = sqlite3.connect(database)
    try:
        return {
            "strength_sets": connection.execute(
                "SELECT a.source_activity_id, s.sequence, s.source_exercise_category, s.source_exercise_name, "
                "s.set_type, s.reps, s.normalized_weight_kg FROM strength_sets s "
                "JOIN activities a ON a.id = s.activity_id ORDER BY a.source_activity_id, s.sequence"
            ).fetchall(),
            "captures": connection.execute(
                "SELECT provider, source_activity_id FROM activity_raw_captures ORDER BY source_activity_id"
            ).fetchall(),
        }
    finally:
        connection.close()


def test_refresh_stores_the_cli_rows_and_reports_unknown_before_and_after(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path, tmp_path: Path
) -> None:
    cli_home = tmp_path / "cli-home"
    monkeypatch.setenv("MUSCLE50_HOME", str(cli_home))
    cli_connector = _imported(capsys, _strength_payload(), _sets("BENCH_PRESS", "UNKNOWN"))
    cli_connector.exercise_sets = _sets("BENCH_PRESS", "BENCH_PRESS")
    cli_connector.version = 2
    _use_connector(monkeypatch, cli_connector)
    cli_text = _ok(capsys, "garmin", "refresh", "222")

    monkeypatch.setenv("MUSCLE50_HOME", str(home))
    connector = _imported(capsys, _strength_payload(), _sets("BENCH_PRESS", "UNKNOWN"))
    assert CountActivityUnknownSets(SqliteAnalyticsReader(_database(home))).execute("222") is not None
    connector.exercise_sets = _sets("BENCH_PRESS", "BENCH_PRESS")
    connector.version = 2
    calls = _use_connector(monkeypatch, connector)

    sent, err = _session(monkeypatch, capsys, "/refresh 222")

    assert len(calls) == 1
    assert sent == [_pre(refresh_progress_text("222")), _pre("refresh 222 완료: 10-05 근력, UNKNOWN 1 → 0세트")]
    assert _business_rows(_database(home)) == _business_rows(_database(cli_home))
    assert _business_rows(_database(home))["captures"] == [("garmin", "222")]  # the refresh capture
    assert cli_text.startswith("Garmin activity refresh complete\n")
    assert err == "\n".join([START_LINE, "chat 111: /refresh -> exit 0"]) + ("\n" + STOPPED)


def test_refresh_with_remaining_unknown_and_endpoint_warnings(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    connector = _imported(capsys, _strength_payload(), _sets("UNKNOWN", "UNKNOWN", "UNKNOWN"))
    connector.exercise_sets = _sets("BENCH_PRESS", "UNKNOWN", "UNKNOWN")
    connector.version = 2
    connector.warnings = ("synthetic endpoint warning",)
    _use_connector(monkeypatch, connector)
    sent, _ = _session(monkeypatch, capsys, "/refresh 222")
    assert sent[1] == _pre(
        "refresh 222 완료: 10-05 근력, UNKNOWN 3 → 2세트\n"
        "아직 UNKNOWN 2세트: Garmin Connect에서 고친 뒤 /refresh 222를 다시 보내세요.\n"
        "경고: synthetic endpoint warning"
    )


def test_refresh_without_counts_or_of_a_non_strength_activity_is_the_cli_headline(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    running = {
        "activityId": 333,
        "activityName": "Synthetic Run",
        "activityTypeDTO": {"typeKey": "running"},
        "duration": 1800,
        "startTimeLocal": "2026-10-05 07:00:00",
    }
    run_connector = _imported(capsys, running, None)
    _use_connector(monkeypatch, run_connector)
    sent, _ = _session(monkeypatch, capsys, "/refresh 333")
    assert sent == [_pre(refresh_progress_text("333")), _pre("Garmin activity refresh complete")]

    strength = _imported(capsys, _strength_payload(), _sets("UNKNOWN"))
    _use_connector(monkeypatch, strength)
    monkeypatch.setattr(cli, "_telegram_unknown_sets", lambda paths, activity_id: None)
    sent, _ = _session(monkeypatch, capsys, "/refresh 222", first_id=2)
    assert sent[1] == _pre("Garmin activity refresh complete")

    def broken(paths: AppPaths, activity_id: str) -> None:
        raise RuntimeError("synthetic")

    monkeypatch.setattr(cli, "_telegram_unknown_sets", broken)
    sent, err = _session(monkeypatch, capsys, "/refresh 222", first_id=3)
    assert sent[1] == _pre("Garmin activity refresh complete")
    assert err.split("\n").count("chat 111: /refresh could not count UNKNOWN sets (RuntimeError)") == 2


MALFORMED_REFRESH = ["/refresh abc", "/refresh 0", "/refresh 1 2", "/refresh -5", "/refresh ١٢٣"]


def test_malformed_refresh_gets_the_usage_and_touches_nothing(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    _imported(capsys, _strength_payload(), _sets("UNKNOWN"))
    before = {path: digest for path, digest in _tree(home).items() if not path.startswith("config/")}
    monkeypatch.setattr(cli, "_telegram_unknown_sets", lambda *args: pytest.fail("no count for a malformed id"))
    sent, _ = _session(monkeypatch, capsys, *MALFORMED_REFRESH)
    assert sent == [_pre(usage_text("refresh"))] * len(MALFORMED_REFRESH)
    assert {path: digest for path, digest in _tree(home).items() if not path.startswith("config/")} == before


def test_refresh_of_an_activity_that_is_not_stored_relays_the_cli_refusal(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    _imported(capsys, _strength_payload(), _sets("UNKNOWN"))
    before = _tables(_database(home))
    sent, err = _session(monkeypatch, capsys, "/refresh 999")
    assert sent == [_pre(refresh_progress_text("999")), _pre("오류: local Garmin activity not found: 999")]
    assert _tables(_database(home)) == before
    assert "chat 111: /refresh -> exit 1" in err.split("\n")


def test_refresh_is_refused_while_a_migration_is_pending(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    _imported(capsys, _strength_payload(), _sets("UNKNOWN"))
    connection = sqlite3.connect(_database(home))
    connection.execute("DELETE FROM schema_migrations WHERE version = 10")
    connection.commit()
    connection.close()
    before = _tables(_database(home))
    sent, _ = _session(monkeypatch, capsys, "/refresh 222")
    assert sent == [_pre(pending_migration_text((10,)))]  # no progress message: nothing ran
    assert _tables(_database(home)) == before


def test_refresh_needing_a_garmin_login_writes_nothing(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    _imported(capsys, _strength_payload(), _sets("UNKNOWN"))

    def interactive(auth_dir: Path, input_fn: Callable[[str], str] = input, **kwargs: object) -> object:
        input_fn("Garmin email: ")  # `garmin refresh` passes no input_fn: the real input() on an empty stdin
        raise AssertionError("input must raise EOFError: the bot has no keyboard")

    monkeypatch.setattr(PythonGarminConnector, "authenticate", interactive)
    before = _tables(_database(home))
    raw_before = {path: digest for path, digest in _tree(home).items() if path.startswith("raw/")}
    sent, err = _session(monkeypatch, capsys, "/refresh 222")
    assert sent == [_pre(refresh_progress_text("222")), _pre(refresh_login_text("222"))]
    assert "chat 111: /refresh needs a Garmin login in a terminal" in err.split("\n")
    assert _tables(_database(home)) == before
    assert {path: digest for path, digest in _tree(home).items() if path.startswith("raw/")} == raw_before


# --- the read-only reader and the count ---------------------------------------------------------------------


def test_reader_and_count_are_read_only_and_match_the_recommendation(
    capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    _seed(capsys, home)
    recommendation = _json(capsys, *RECOMMEND_JSON)
    before = _tree(home)
    reader = SqliteAnalyticsReader(_database(home))
    assert reader.load_activity("999") is None
    counts = CountActivityUnknownSets(reader).execute(UNKNOWN_ID)
    assert counts is not None
    notice = recommendation["strength"]["unknown_notices"][0]
    assert notice["source_activity_id"] == counts.source_activity_id == UNKNOWN_ID
    assert counts.unknown_set_count == notice["unknown_set_count"] == 2
    assert list(counts.set_sequences) == notice["set_sequences"]
    assert (counts.local_date, counts.is_strength) == (date(2026, 10, 5), True)
    other = CountActivityUnknownSets(reader).execute("7002")
    assert other is not None and (other.unknown_set_count, other.set_sequences) == (0, ())
    assert _tree(home) == before


def test_count_on_a_home_without_a_database_is_none(home: Path) -> None:
    paths = AppPaths.from_environment()
    assert cli._telegram_unknown_sets(paths, "222") is None
    assert not (home / "db").exists()
