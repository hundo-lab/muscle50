"""Telegram `/sync` and the `/daily` gap line (Daily Catch-up v1, AC4-AC6 of docs/specs/daily-catch-up.md).

The grammar and texts, then `muscle50 telegram run` through `cli.main` with a fake Bot API and a fake Garmin
account (no network, no Garmin login), a temporary MUSCLE50_HOME and synthetic values only. Confirmations live in
the bot's memory, so an offer and its `/sync_ok_` are sent in one run, as successive `getUpdates` batches.
"""

from __future__ import annotations

import copy
import html
import json
import re
import sqlite3
import urllib.request
from collections.abc import Callable, Sequence
from datetime import UTC, date, datetime, timedelta, timezone, tzinfo
from pathlib import Path
from typing import Any

import pytest
import sync_coverage_builders as builders
from test_telegram_bot import FakeTelegramApi

import muscle50.cli as cli
from muscle50.application.sync_garmin_recovery import MAX_RECOVERY_RANGE_DAYS, RECOVERY_ENDPOINTS_PER_DATE
from muscle50.application.telegram_bot import IncomingMessage, IncomingUpdate, SummaryUnavailableError
from muscle50.cli import main
from muscle50.domain.sync_catch_up import GARMIN_SYNC_UNCONFIRMED_MAX_DAYS
from muscle50.domain.telegram_commands import (
    CliInvocation,
    ReplyKind,
    UsageReason,
    UsageReply,
    parse_bot_message,
    usage_reply_text,
    usage_text,
)
from muscle50.domain.telegram_sync import (
    SYNC_CONFIRM_INVALID_TEXT,
    SYNC_CONFIRM_TTL_S,
    SYNC_MAX_DAYS,
    SYNC_REQUESTS_PER_DAY,
    SYNC_UNCONFIRMED_MAX_DAYS,
    BotRefusal,
    SyncConfirm,
    SyncConfirmNeeded,
    SyncRange,
    sync_command_text,
    sync_login_text,
    sync_progress_text,
    sync_summary_failed_text,
)
from muscle50.infrastructure.garmin.client import GarminConnectorError, PythonGarminConnector
from muscle50.infrastructure.sqlite.database import ActivityRepository
from muscle50.presentation.telegram_format import Code
from muscle50.presentation.telegram_summary import TelegramSummaries, daily_summary, sync_summary

KST = timezone(timedelta(hours=9))
TODAY = date(2026, 10, 21)
NOW = datetime(2026, 10, 21, 12, 0, tzinfo=KST)
NOW_TS = int(NOW.timestamp())
TOKEN = "123456789:AAFakeSyntheticToken_ab-cd"
ALLOWED = 111
OTHER = 222
BOT = "muscle50_example_bot"


# --- grammar and texts (pure) --------------------------------------------------------------------------------


def parse(text: str) -> Any:
    return parse_bot_message(text, bot_username=BOT, today=TODAY)


def test_the_limits_mirror_the_cli() -> None:
    assert SYNC_REQUESTS_PER_DAY == RECOVERY_ENDPOINTS_PER_DATE
    assert SYNC_MAX_DAYS == MAX_RECOVERY_RANGE_DAYS == 31
    assert SYNC_UNCONFIRMED_MAX_DAYS == GARMIN_SYNC_UNCONFIRMED_MAX_DAYS == 7
    assert SYNC_CONFIRM_TTL_S == 600


@pytest.mark.parametrize(
    "text",
    ["/sync 10-15 10-18", "/sync 2026-10-15 2026-10-18", "/sync 10-15 2026-10-18", f"/sync@{BOT} 10-15 10-18"],
)
def test_up_to_seven_days_is_one_garmin_sync_invocation(text: str) -> None:
    requested = SyncRange(date(2026, 10, 15), date(2026, 10, 18))
    assert parse(text) == CliInvocation(
        "sync",
        ("garmin", "sync", "--from", "2026-10-15", "--to", "2026-10-18", "--json"),
        True,
        False,
        False,
        ReplyKind.SYNC_SUMMARY,
        progress_text=sync_progress_text(requested, TODAY),
        login_text=sync_login_text(requested),
    )


def test_seven_days_is_the_last_range_without_a_confirmation() -> None:
    assert isinstance(parse("/sync 10-15 10-21"), CliInvocation)
    assert parse("/sync 10-14 10-21") == SyncConfirmNeeded(SyncRange(date(2026, 10, 14), TODAY))
    assert parse("/sync 09-21 10-21") == SyncConfirmNeeded(SyncRange(date(2026, 9, 21), TODAY))


@pytest.mark.parametrize(
    "text",
    [
        "/sync",
        "/sync 10-15",
        "/sync 10-15 10-18 10-19",
        "/sync -x 10-18",
        "/sync 10-15 --yes",
        "/sync 2026/10/15 10-18",
        "/sync 1-05 10-18",
        "/sync 10-15 오늘",
        "/sync_ok_a41c now",
    ],
)
def test_other_shapes_get_the_usage(text: str) -> None:
    assert parse(text) == UsageReply(UsageReason.MALFORMED, "sync")


@pytest.mark.parametrize(
    ("text", "refusal"),
    [
        ("/sync 02-30 10-18", "오류: 없는 날짜입니다: 02-30. 날짜는 YYYY-MM-DD 또는 MM-DD(올해)로 씁니다."),
        ("/sync 2026-13-01 10-18", "오류: 없는 날짜입니다: 2026-13-01. 날짜는 YYYY-MM-DD 또는 MM-DD(올해)로 씁니다."),
        ("/sync 10-18 10-09", "오류: 시작 날짜(2026-10-18)가 끝 날짜(2026-10-09)보다 늦습니다."),
        (
            "/sync 10-20 10-25",
            "오류: 끝 날짜(2026-10-25)가 오늘(2026-10-21) 이후입니다. 작년 날짜는 YYYY-MM-DD로 쓰세요.",
        ),
        ("/sync 09-12 10-21", "오류: 한 번에 최대 31일까지 받을 수 있습니다(요청: 40일). 기간을 나눠 보내세요."),
    ],
)
def test_refusals_are_exact(text: str, refusal: str) -> None:
    assert parse(text) == BotRefusal(refusal)


def test_confirmation_commands() -> None:
    assert parse("/sync_ok_a41c") == SyncConfirm("a41c")
    assert parse(f"/sync_ok_a41c@{BOT}") == SyncConfirm("a41c")
    assert parse("/sync_ok_A41C") == UsageReply(UsageReason.UNKNOWN_COMMAND, "/sync_ok_A41C")
    assert parse("/sync_ok_a41") == UsageReply(UsageReason.UNKNOWN_COMMAND, "/sync_ok_a41")
    assert parse("/sync_ok_a41c@other_bot") == UsageReply(UsageReason.UNKNOWN_COMMAND, "/sync_ok_a41c@other_bot")


def test_the_usage_and_texts_are_pinned() -> None:
    assert usage_text("sync") == (
        "사용법: /sync <시작> <끝>\n"
        "날짜는 YYYY-MM-DD 또는 MM-DD(올해)입니다. 끝은 오늘까지, 한 번에 최대 31일. 7일을 넘으면 확인 명령"
        "(/sync_ok_…)을 한 번 더 누릅니다. 운동·회복만 받고 추천은 만들지 않습니다.\n"
        "예: /sync 10-09 10-18"
    )
    assert usage_reply_text(UsageReply(UsageReason.MALFORMED, "sync")) == usage_text("sync")
    short = SyncRange(date(2026, 10, 15), date(2026, 10, 18))
    long = SyncRange(date(2026, 10, 9), date(2026, 10, 18))
    assert sync_progress_text(short, TODAY) == (
        "동기화 실행 중: 10-15 ~ 10-18 (4일, Garmin 요청 약 36회). 끝나면 결과를 보냅니다."
    )
    assert sync_login_text(short) == (
        "오류: Garmin에 다시 로그인해야 합니다. PC 터미널에서 muscle50 garmin sync --from 2026-10-15 "
        "--to 2026-10-18를 한 번 실행하세요(로그인한 뒤 그대로 받습니다)."
    )
    assert sync_login_text(long) == (
        "오류: Garmin에 다시 로그인해야 합니다. PC 터미널에서 muscle50 garmin sync --from 2026-10-09 "
        "--to 2026-10-18 --yes를 한 번 실행하세요(로그인한 뒤 그대로 받습니다)."
    )
    assert SYNC_CONFIRM_INVALID_TEXT == (
        "오류: 이 확인 명령은 없거나, 10분이 지났거나, 이미 쓰였습니다. 다시 받으려면 /sync 시작 끝을 보내세요."
    )
    assert sync_summary_failed_text(1) == (
        "오류: 동기화는 끝났지만 결과를 요약하지 못했습니다 (exit 1). 받은 날짜는 PC에서 muscle50 garmin coverage로 "
        "확인하세요."
    )


def test_mm_dd_only_inside_todays_year() -> None:
    assert sync_command_text(date(2026, 10, 9), date(2026, 10, 13), TODAY) == "/sync 10-09 10-13"
    january = date(2027, 1, 3)
    assert sync_command_text(date(2026, 12, 28), date(2027, 1, 2), january) == "/sync 2026-12-28 2027-01-02"
    assert sync_progress_text(SyncRange(date(2026, 12, 28), date(2027, 1, 2)), january).startswith(
        "동기화 실행 중: 2026-12-28 ~ 2027-01-02 (6일,"
    )


# --- summaries of `garmin sync --json` -------------------------------------------------------------------------


def _sync_document(**changes: Any) -> dict[str, Any]:
    document: dict[str, Any] = {
        "as_of": "2026-10-18",
        "mode": "sync",
        "sync_from": "2026-10-09",
        "ok": True,
        "failed_stages": [],
        "stages": [
            {"stage": name, "status": "ok", "error": None, "warnings": []}
            for name in ("garmin_login", "activities", "load_metrics", "recovery")
        ]
        + [{"stage": "recommendation", "status": "skipped", "error": None, "warnings": []}],
        "activities": {
            "from": "2026-10-09",
            "to": "2026-10-18",
            "discovered": 10,
            "inserted": 10,
            "already_stored": 0,
            "failed": 0,
            "undated": 0,
            "page_limit_reached": False,
            "outcomes": [],
        },
        "load_metrics": None,
        "recovery": {
            "from": "2026-10-09",
            "to": "2026-10-18",
            "aborted_reason": None,
            "outcomes": [
                {"calendar_date": f"2026-10-{day:02d}", "status": "created", "error": None, "warnings": []}
                for day in range(9, 19)
            ],
        },
        "recommendation": None,
    }
    document.update(changes)
    return document


def _lines(reply: Any) -> list[str]:
    return str(reply.plain_text()).split("\n")


def test_an_ok_sync_summary() -> None:
    assert _lines(sync_summary(_sync_document())) == [
        "동기화했습니다: 10-09 ~ 10-18",
        "운동 새로 저장 10건 · 회복 새로 저장 10일 · 실패 없음",
        "오늘 추천: /daily",
    ]
    assert TelegramSummaries().summary(ReplyKind.SYNC_SUMMARY, _sync_document()) == [
        "<pre>동기화했습니다: 10-09 ~ 10-18\n운동 새로 저장 10건 · 회복 새로 저장 10일 · 실패 없음</pre>\n"
        "오늘 추천: /daily"
    ]


def test_updated_days_and_warnings_are_shown() -> None:
    document = _sync_document()
    document["recovery"]["outcomes"][0]["status"] = "updated"
    document["recovery"]["outcomes"][1]["status"] = "unchanged"
    document["stages"][3]["warnings"] = ["2026-10-09: hrv endpoint unavailable"]
    assert _lines(sync_summary(document)) == [
        "동기화했습니다: 10-09 ~ 10-18",
        "운동 새로 저장 10건 · 회복 새로 저장 8일 (갱신 1일) · 실패 없음",
        "경고(recovery): 2026-10-09: hrv endpoint unavailable",
        "오늘 추천: /daily",
    ]


def test_a_failed_sync_summary_lists_the_failed_dates_and_activities() -> None:
    document = _sync_document(ok=False, failed_stages=["activities", "recovery"])
    outcomes = document["recovery"]["outcomes"]
    outcomes[3]["status"], outcomes[3]["error"] = "failed", "boom"
    outcomes[4]["status"] = "failed"
    outcomes[5]["status"] = "not_attempted"
    outcomes[6:] = [dict(item, status="not_attempted") for item in outcomes[6:]]
    document["activities"]["outcomes"] = [
        {"source_activity_id": "9001", "source_type_key": "running", "status": "failed", "error": "x", "warnings": []}
    ]
    document["stages"][1].update(status="failed", error="activity 9001 (running) failed: x")
    document["stages"][3].update(status="failed", error="2026-10-12 failed: boom; aborted: 3 failures")
    reply = sync_summary(document)
    assert _lines(reply) == [
        "동기화 일부 실패: 10-09 ~ 10-18 (activities, recovery 단계)",
        "운동 새로 저장 10건 · 회복 새로 저장 3일 · 실패: 운동 9001, 10-12, 10-13, 10-14(받지 않음), "
        "10-15(받지 않음), 10-16(받지 않음), 10-17(받지 않음), 10-18(받지 않음)",
        "  activities: activity 9001 (running) failed: x",
        "  recovery: 2026-10-12 failed: boom; aborted: 3 failures",
        "이미 받은 데이터는 저장되어 있습니다. 다시 받기: /sync 10-09 10-18",
    ]
    assert reply.rich[-1][-1][-1] == Code("/sync 10-09 10-18")


def test_unknown_counts_are_never_zero() -> None:
    document = _sync_document(ok=False, failed_stages=["garmin_login"], activities=None, recovery=None)
    document["stages"][0].update(status="failed", error="Garmin 인증에 실패했습니다.")
    assert _lines(sync_summary(document))[:3] == [
        "동기화 일부 실패: 10-09 ~ 10-18 (garmin_login 단계)",
        "운동 새로 저장 알 수 없음 · 회복 새로 저장 알 수 없음 · 실패 없음",
        "  garmin_login: Garmin 인증에 실패했습니다.",
    ]


@pytest.mark.parametrize("change", [{"mode": "full"}, {"as_of": "10-18"}, {"ok": 1}, {"recovery": {"outcomes": 3}}])
def test_an_unexpected_document_is_a_summary_error(change: dict[str, Any]) -> None:
    with pytest.raises(SummaryUnavailableError):
        TelegramSummaries().summary(ReplyKind.SYNC_SUMMARY, _sync_document(**change))


def test_the_offer_is_a_body_and_a_plain_command_line() -> None:
    assert TelegramSummaries().confirm_offer("10일 & 더", "/sync_ok_a41c") == [
        "<pre>10일 &amp; 더</pre>\n/sync_ok_a41c"
    ]


# --- AC6: the `/daily` summary names `/sync` only when daily left days out -------------------------------------


def _daily_golden() -> dict[str, Any]:
    document: dict[str, Any] = json.loads(builders.golden("daily_2026-10-02.json"))
    return document


def test_daily_summary_without_catch_up_is_unchanged() -> None:
    document = _daily_golden()
    assert "catch_up" not in document
    reply = daily_summary(document)
    assert "이어 받기" not in reply.plain_text() and "/sync" not in reply.plain_text()


def test_daily_summary_with_a_catch_up_inside_the_limit() -> None:
    plain = daily_summary(_daily_golden())
    document = _daily_golden()
    document["catch_up"] = {"from": "2026-09-28", "limit_days": 7, "last_synced": "2026-09-27", "older_unsynced": None}
    reply = daily_summary(document)
    head, rest = plain.pre.split("\n", 1)
    assert reply.pre == f"{head}\n이어 받기: 09-28부터 (마지막 동기화 09-27)\n{rest}"
    assert reply.rich == plain.rich


def test_daily_summary_with_older_unsynced_days_adds_the_sync_command() -> None:
    plain = daily_summary(_daily_golden())
    document = _daily_golden()
    document["catch_up"] = {
        "from": "2026-09-25",
        "limit_days": 7,
        "last_synced": None,
        "older_unsynced": {"from": "2026-09-12", "to": "2026-09-24"},
    }
    reply = daily_summary(document)
    head, rest = plain.pre.split("\n", 1)
    assert reply.pre == f"{head}\n이어 받기: 09-25부터 (최근 31일에 모두 동기화된 날 없음)\n{rest}"
    gap = (
        (
            (
                "아직 동기화되지 않은 날: 09-12 ~ 09-24 (daily는 7일 전까지만 받습니다). 받기: ",
                Code("/sync 09-12 09-24"),
            ),
        ),
    )
    assert reply.rich == (*gap, *plain.rich)


def test_a_failed_daily_keeps_the_catch_up_lines() -> None:
    document = _daily_golden()
    document.update(ok=False, failed_stages=["recovery"], recommendation=None)
    document["stages"][3].update(status="failed", error="boom")
    plain = daily_summary(copy.deepcopy(document))
    document["catch_up"] = {
        "from": "2026-09-25",
        "limit_days": 7,
        "last_synced": "2026-09-19",
        "older_unsynced": {"from": "2026-09-20", "to": "2026-09-24"},
    }
    reply = daily_summary(document)
    assert reply.pre.split("\n")[:3] == [
        "daily 10-02: 실패 (recovery 단계)",
        "이어 받기: 09-25부터 (마지막 동기화 09-19)",
        "  recovery: boom",
    ]
    assert reply.rich[0] == (
        ("아직 동기화되지 않은 날: 09-20 ~ 09-24 (daily는 7일 전까지만 받습니다). 받기: ", Code("/sync 09-20 09-24")),
    )
    assert reply.rich[1:] == plain.rich


# --- the bot end to end -------------------------------------------------------------------------------------------


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "home"
    monkeypatch.setenv("MUSCLE50_HOME", str(root))
    monkeypatch.setattr(urllib.request, "urlopen", lambda *args, **kwargs: pytest.fail("no network in tests"))
    monkeypatch.setattr(
        PythonGarminConnector, "authenticate", lambda *args, **kwargs: pytest.fail("must not use Garmin")
    )

    def fixed_timezone(day: date) -> tzinfo:
        return KST

    monkeypatch.setattr(cli, "_local_timezone", fixed_timezone)
    monkeypatch.setattr(cli, "_today", lambda: TODAY)
    monkeypatch.setattr(cli, "_now", lambda: NOW)
    monkeypatch.setattr(cli, "_telegram_sleep", lambda seconds: None)
    tokens = iter(["a41c", "b52d", "c63e", "d74f"])
    monkeypatch.setattr(cli, "_new_proposal_token", lambda: next(tokens))
    config = root / "config" / "telegram.json"
    config.parent.mkdir(parents=True)
    config.write_text(json.dumps({"bot_token": TOKEN, "allowed_chat_ids": [ALLOWED, OTHER]}), encoding="utf-8")
    ActivityRepository(root / "db" / "muscle50.sqlite3").migrate()
    return root


Step = tuple[float, Sequence[tuple[int, str]]]
"""Seconds after NOW when the batch arrives, and its (chat, text) messages."""


class TimedApi(FakeTelegramApi):
    """A fake Bot API whose batches arrive at given times: the bot's clock (`cli._now`) moves with them."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, steps: Sequence[Step], hooks: dict[int, Callable[[], None]]):
        self._monkeypatch = monkeypatch
        self._times = [offset for offset, _ in steps]
        self._hooks = hooks
        self._served = 0
        batches = []
        update_id = 1
        for offset, messages in steps:
            batch = []
            for chat, text in messages:
                batch.append(IncomingUpdate(update_id, IncomingMessage(chat, text, NOW_TS + int(offset))))
                update_id += 1
            batches.append(batch)
        super().__init__(*batches)

    def get_updates(self, offset: int | None, timeout_s: int) -> tuple[IncomingUpdate, ...]:
        if self._served < len(self._times):
            later = NOW + timedelta(seconds=self._times[self._served])
            self._monkeypatch.setattr(cli, "_now", lambda: later)
            hook = self._hooks.get(self._served)
            if hook is not None:
                hook()
            self._served += 1
        return super().get_updates(offset, timeout_s)


def _session(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    *steps: Step,
    hooks: dict[int, Callable[[], None]] | None = None,
) -> tuple[list[tuple[int, str]], str]:
    fake = TimedApi(monkeypatch, steps, hooks or {})
    monkeypatch.setattr(cli, "_telegram_api", lambda token: fake)
    code = main(["telegram", "run"])
    captured = capsys.readouterr()
    assert (code, captured.out) == (130, "")
    return fake.sent, captured.err


def _texts(*messages: str, chat: int = ALLOWED) -> Step:
    return (0, [(chat, text) for text in messages])


def _plain(message: str) -> str:
    return html.unescape(re.sub(r"</?pre>|</?code>", "", message))


def _pre(text: str) -> str:
    return f"<pre>{html.escape(text, quote=False)}</pre>"


def _main_calls(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    calls: list[list[str]] = []

    def spy(argv: Sequence[str] | None = None) -> int:
        calls.append(list(argv or ()))
        return main(argv)

    monkeypatch.setattr(cli, "main", spy)
    return calls


def _garmin(monkeypatch: pytest.MonkeyPatch, **kwargs: Any) -> tuple[builders.FakeGarmin, list[Path]]:
    garmin = builders.FakeGarmin(
        [builders.summary(500, "running", "2026-10-16", "07:00:00", activityTrainingLoad=50.0)],
        recovery_kinds=builders.ALL_RECOVERY_KINDS,
        **kwargs,
    )
    logins: list[Path] = []

    def authenticate(auth_dir: Path, **_kwargs: Any) -> builders.FakeGarmin:
        logins.append(auth_dir)
        return garmin

    monkeypatch.setattr(PythonGarminConnector, "authenticate", authenticate)
    return garmin, logins


def _dates(start: date, end: date) -> list[str]:
    return [(start + timedelta(days=offset)).isoformat() for offset in range((end - start).days + 1)]


def _coverage_commands(root: Path) -> set[str]:
    with sqlite3.connect(root / "db" / "muscle50.sqlite3") as connection:
        return {row[0] for row in connection.execute("SELECT DISTINCT command FROM sync_coverage")}


SYNC_ARGV = ["garmin", "sync", "--from", "2026-10-15", "--to", "2026-10-18", "--json"]
LONG_ARGV = ["garmin", "sync", "--from", "2026-10-09", "--to", "2026-10-18", "--yes", "--json"]
OFFER = "<pre>10일(10-09 ~ 10-18), Garmin 요청 약 90회입니다. 받아오려면 누르세요(10분 유효):</pre>\n/sync_ok_a41c"
LONG_PROGRESS = _pre("동기화 실행 중: 10-09 ~ 10-18 (10일, Garmin 요청 약 90회). 끝나면 결과를 보냅니다.")
LONG_SUMMARY = (
    "<pre>동기화했습니다: 10-09 ~ 10-18\n운동 새로 저장 1건 · 회복 새로 저장 10일 · 실패 없음</pre>\n오늘 추천: /daily"
)


def test_ac4_up_to_seven_days_runs_at_once(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    garmin, logins = _garmin(monkeypatch)
    calls = _main_calls(monkeypatch)

    sent, err = _session(monkeypatch, capsys, _texts("/sync 10-15 10-18"))

    assert [message for _, message in sent] == [
        _pre("동기화 실행 중: 10-15 ~ 10-18 (4일, Garmin 요청 약 36회). 끝나면 결과를 보냅니다."),
        "<pre>동기화했습니다: 10-15 ~ 10-18\n운동 새로 저장 1건 · 회복 새로 저장 4일 · 실패 없음</pre>\n"
        "오늘 추천: /daily",
    ]
    assert calls == [SYNC_ARGV]  # garmin sync only: no recommendation is built
    assert len(logins) == 1
    assert garmin.recovery_calls == _dates(date(2026, 10, 15), date(2026, 10, 18))
    assert garmin.activity_calls == ["500"]
    assert _coverage_commands(home) == {"garmin sync"}
    assert "chat 111: /sync -> exit 0" in err.split("\n")


def test_ac4_a_longer_range_runs_once_after_its_confirmation(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    garmin, logins = _garmin(monkeypatch)
    calls = _main_calls(monkeypatch)

    sent, err = _session(
        monkeypatch,
        capsys,
        _texts("/sync 10-09 10-18"),
        (30, [(ALLOWED, "/sync_ok_a41c")]),
        (60, [(ALLOWED, "/sync_ok_a41c")]),
    )

    assert [message for _, message in sent] == [OFFER, LONG_PROGRESS, LONG_SUMMARY, _pre(SYNC_CONFIRM_INVALID_TEXT)]
    assert calls == [LONG_ARGV]
    assert len(logins) == 1
    assert garmin.recovery_calls == _dates(date(2026, 10, 9), date(2026, 10, 18))
    assert "chat 111: /sync 10 days offered for confirmation" in err.split("\n")


@pytest.mark.parametrize(
    ("seconds", "runs"), [(SYNC_CONFIRM_TTL_S - 1, True), (SYNC_CONFIRM_TTL_S, False), (601, False)]
)
def test_ac5_an_offer_expires_after_ten_minutes(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path, seconds: int, runs: bool
) -> None:
    if runs:
        _garmin(monkeypatch)
    calls = _main_calls(monkeypatch)

    sent, _ = _session(monkeypatch, capsys, _texts("/sync 10-09 10-18"), (seconds, [(ALLOWED, "/sync_ok_a41c")]))

    if runs:
        assert [message for _, message in sent] == [OFFER, LONG_PROGRESS, LONG_SUMMARY]
        assert calls == [LONG_ARGV]
    else:  # the home fixture makes any Garmin login fail the test
        assert [message for _, message in sent] == [OFFER, _pre(SYNC_CONFIRM_INVALID_TEXT)]
        assert calls == []


def test_ac5_a_token_from_another_allowed_chat_is_refused_and_kept_for_its_own(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    _garmin(monkeypatch)
    calls = _main_calls(monkeypatch)

    sent, _ = _session(
        monkeypatch,
        capsys,
        _texts("/sync 10-09 10-18"),
        (10, [(OTHER, "/sync_ok_a41c")]),
        (20, [(ALLOWED, "/sync_ok_a41c")]),
    )

    assert sent == [
        (ALLOWED, OFFER),
        (OTHER, _pre(SYNC_CONFIRM_INVALID_TEXT)),
        (ALLOWED, LONG_PROGRESS),
        (ALLOWED, LONG_SUMMARY),
    ]
    assert calls == [LONG_ARGV]


def test_a_new_offer_replaces_the_chat_s_earlier_one(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    _garmin(monkeypatch)
    calls = _main_calls(monkeypatch)

    sent, _ = _session(
        monkeypatch, capsys, _texts("/sync 10-01 10-10", "/sync 10-09 10-18", "/sync_ok_a41c", "/sync_ok_b52d")
    )

    messages = [message for _, message in sent]
    assert messages[0].endswith("\n/sync_ok_a41c") and messages[1] == OFFER.replace("a41c", "b52d")
    assert messages[2:] == [_pre(SYNC_CONFIRM_INVALID_TEXT), LONG_PROGRESS, LONG_SUMMARY]
    assert calls == [LONG_ARGV]


def test_a_pending_migration_keeps_the_token(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    _garmin(monkeypatch)
    calls = _main_calls(monkeypatch)
    pending: list[tuple[int, ...]] = [(99,)]
    monkeypatch.setattr(cli, "pending_migrations", lambda path: pending[0])

    def applied() -> None:
        pending[0] = ()

    sent, _ = _session(
        monkeypatch,
        capsys,
        _texts("/sync 10-09 10-18", "/sync_ok_a41c"),
        (30, [(ALLOWED, "/sync_ok_a41c")]),
        hooks={1: applied},
    )

    messages = [message for _, message in sent]
    assert messages[0] == OFFER
    assert _plain(messages[1]).startswith("오류: DB에 아직 적용하지 않은 migration 099이 있습니다.")
    assert messages[2:] == [LONG_PROGRESS, LONG_SUMMARY]
    assert calls == [LONG_ARGV]


@pytest.mark.parametrize(
    "text",
    ["/sync 02-30 10-18", "/sync 09-12 10-21", "/sync 10-20 10-25", "/sync 10-18 10-09", "/sync_ok_ffff", "/sync"],
)
def test_ac5_refusals_never_call_garmin_or_the_cli(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path, text: str
) -> None:
    calls = _main_calls(monkeypatch)
    before = (home / "db" / "muscle50.sqlite3").read_bytes()

    sent, _ = _session(monkeypatch, capsys, _texts(text))

    expected = parse(text)
    if isinstance(expected, BotRefusal):
        reply = expected.text
    elif isinstance(expected, SyncConfirm):
        reply = SYNC_CONFIRM_INVALID_TEXT
    else:
        reply = usage_text("sync")
    assert [message for _, message in sent] == [_pre(reply)]
    assert calls == []
    assert (home / "db" / "muscle50.sqlite3").read_bytes() == before


def test_a_garmin_login_need_gets_the_terminal_command(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    def prompt(*args: object, **kwargs: object) -> object:
        raise EOFError

    monkeypatch.setattr(PythonGarminConnector, "authenticate", prompt)

    sent, err = _session(monkeypatch, capsys, _texts("/sync 10-15 10-18", "/sync 10-09 10-18", "/sync_ok_a41c"))

    short = SyncRange(date(2026, 10, 15), date(2026, 10, 18))
    long = SyncRange(date(2026, 10, 9), date(2026, 10, 18))
    assert [message for _, message in sent] == [
        _pre(sync_progress_text(short, TODAY)),
        _pre(sync_login_text(short)),
        OFFER,
        LONG_PROGRESS,
        _pre(sync_login_text(long)),
    ]
    assert "chat 111: /sync needs a Garmin login in a terminal" in err.split("\n")


def test_a_failed_stage_gets_the_failure_summary(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    _garmin(monkeypatch, recovery_failures={"2026-10-16": GarminConnectorError("synthetic <failure>")})

    sent, err = _session(monkeypatch, capsys, _texts("/sync 10-15 10-18"))

    assert len(sent) == 2
    lines = _plain(sent[1][1]).split("\n")
    assert lines[:2] == [
        "동기화 일부 실패: 10-15 ~ 10-18 (recovery 단계)",
        "운동 새로 저장 1건 · 회복 새로 저장 3일 · 실패: 10-16",
    ]
    assert lines[2].startswith("  recovery: 2026-10-16 failed: synthetic <failure>")
    assert lines[-1] == "이미 받은 데이터는 저장되어 있습니다. 다시 받기: /sync 10-15 10-18"
    assert "&lt;failure&gt;" in sent[1][1] and "<code>/sync 10-15 10-18</code>" in sent[1][1]
    assert "chat 111: /sync -> exit 1" in err.split("\n")


def test_the_daily_reply_names_sync_only_when_days_are_left_out(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    # Last complete day 10-08 (written on 10-09 KST): `daily` takes 10-14..10-21, 10-09..10-13 are left out.
    with sqlite3.connect(home / "db" / "muscle50.sqlite3") as connection:
        for kind in ("activities", "recovery"):
            connection.execute(
                "INSERT INTO sync_coverage (provider, data_kind, calendar_date, status, source, command, "
                "synced_at_utc) VALUES ('garmin', ?, '2026-10-08', 'synced', 'sync', 'daily', ?)",
                (kind, datetime(2026, 10, 8, 16, 0, tzinfo=UTC).isoformat()),
            )
    garmin, _ = _garmin(monkeypatch)

    sent, _ = _session(monkeypatch, capsys, _texts("/daily"))

    assert garmin.recovery_calls == _dates(date(2026, 10, 14), TODAY)
    lines = _plain(sent[1][1]).split("\n")
    assert lines[:2] == [
        "daily 10-21: 동기화 완료 (새 운동 1, 회복 8일 갱신)",
        "이어 받기: 10-14부터 (마지막 동기화 10-08)",
    ]
    assert (
        "아직 동기화되지 않은 날: 10-09 ~ 10-13 (daily는 7일 전까지만 받습니다). 받기: <code>/sync 10-09 10-13</code>"
        in sent[1][1]
    )
