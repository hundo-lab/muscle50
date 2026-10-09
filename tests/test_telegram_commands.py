"""Telegram bot grammar: each message maps to one exact CLI argv, or to the help / a usage reply.

Pure domain tests; no I/O. The bot-own reply texts (Korean, gate 1 D4) are pinned here.
"""

from __future__ import annotations

import urllib.request
from datetime import date, datetime

import pytest

from muscle50.domain.telegram_commands import (
    DAILY_PROGRESS_TEXT,
    GARMIN_LOGIN_TEXT,
    HELP_TEXT,
    MIGRATION_STATUS_UNKNOWN_TEXT,
    CliInvocation,
    UsageReason,
    UsageReply,
    empty_output_text,
    parse_bot_message,
    pending_migration_text,
    stale_text,
    undo_line,
    unexpected_error_text,
    usage_reply_text,
    usage_text,
)

TODAY = date(2026, 10, 6)
BOT = "muscle50_example_bot"


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(urllib.request, "urlopen", lambda *args, **kwargs: pytest.fail("no network in tests"))


def parse(text: str | None) -> CliInvocation | UsageReply:
    return parse_bot_message(text, bot_username=BOT, today=TODAY)


@pytest.mark.parametrize(
    ("text", "argv", "migrates", "is_daily", "adds_undo"),
    [
        ("/today", ("recommend", "--date", "2026-10-06", "--json"), False, False, False),
        ("/today full", ("recommend", "--date", "2026-10-06"), False, False, False),
        ("/status", ("nutrition", "status", "--json"), True, False, False),
        ("/status full", ("nutrition", "status"), True, False, False),
        ("/unknown", ("recommend", "--date", "2026-10-06", "--json"), False, False, False),
        ("/refresh 24610155225", ("garmin", "refresh", "24610155225"), True, False, False),
        ("/refresh 1", ("garmin", "refresh", "1"), True, False, False),
        ("/refresh", ("recommend", "--date", "2026-10-06", "--json"), True, False, False),
        ("/day", ("nutrition", "day"), True, False, False),
        ("/day 2026-10-05", ("nutrition", "day", "--date", "2026-10-05"), True, False, False),
        ("/day 2026-13-40", ("nutrition", "day", "--date", "2026-13-40"), True, False, False),  # the CLI validates
        ("/show 2026-10-06-lunch-1", ("nutrition", "meal", "show", "2026-10-06-lunch-1"), True, False, False),
        ("/void 2026-10-06-snack-1", ("nutrition", "meal", "void", "2026-10-06-snack-1"), True, False, False),
        (
            "/void 2026-10-06-snack-1   중복  기록 ",
            ("nutrition", "meal", "void", "2026-10-06-snack-1", "--reason=중복  기록"),
            True,
            False,
            False,
        ),
        ("/inbody", ("inbody", "trend"), False, False, False),
        ("/daily", ("daily", "--json"), True, True, False),
        ("/daily full", ("daily",), True, True, False),
        (
            "/log lunch 닭가슴살 150 g, 햇반 1 pack",
            ("nutrition", "log", "--meal", "lunch", "--item", "닭가슴살", "150", "g", "--item", "햇반", "1", "pack"),
            True,
            False,
            True,
        ),
        (
            "/log lunch+ 바나나 1 count",
            ("nutrition", "log", "--meal", "lunch", "--item", "바나나", "1", "count", "--additional"),
            True,
            False,
            True,
        ),
        (
            "/log dinner 현미   햇반 1 pack,chicken-breast 0.5 g",
            (
                "nutrition",
                "log",
                "--meal",
                "dinner",
                "--item",
                "현미 햇반",
                "1",
                "pack",
                "--item",
                "chicken-breast",
                "0.5",
                "g",
            ),
            True,
            False,
            True,
        ),
        # Quantity and unit values are the CLI's to validate (its `오류:` text comes back unchanged).
        (
            "/log snack x abc cup",
            ("nutrition", "log", "--meal", "snack", "--item", "x", "abc", "cup"),
            True,
            False,
            True,
        ),
        (f"/status@{BOT}", ("nutrition", "status", "--json"), True, False, False),
        ("/status@MUSCLE50_Example_Bot", ("nutrition", "status", "--json"), True, False, False),
        ("  /today  ", ("recommend", "--date", "2026-10-06", "--json"), False, False, False),
    ],
)
def test_commands_map_to_exact_cli_argv(
    text: str, argv: tuple[str, ...], migrates: bool, is_daily: bool, adds_undo: bool
) -> None:
    result = parse(text)
    assert isinstance(result, CliInvocation)
    assert result.argv == argv
    assert (result.migrates, result.is_daily, result.adds_undo) == (migrates, is_daily, adds_undo)


def test_only_recommend_and_inbody_trend_are_exempt_from_the_migration_check() -> None:
    # Every `nutrition` handler and `daily` call migrate() in the CLI; recommend and inbody trend never do.
    migrating = {
        text: parse(text)
        for text in ("/today", "/status", "/day", "/show a", "/void a", "/log lunch a 1 g", "/inbody", "/daily")
    }
    assert {text for text, result in migrating.items() if isinstance(result, CliInvocation) and result.migrates} == {
        "/status",
        "/day",
        "/show a",
        "/void a",
        "/log lunch a 1 g",
        "/daily",
    }


@pytest.mark.parametrize(
    ("text", "reason", "command"),
    [
        (None, UsageReason.NOT_A_COMMAND, None),
        ("", UsageReason.NOT_A_COMMAND, None),
        ("hello", UsageReason.NOT_A_COMMAND, None),
        ("today", UsageReason.NOT_A_COMMAND, None),
        ("/foo", UsageReason.UNKNOWN_COMMAND, "/foo"),
        ("/Status", UsageReason.UNKNOWN_COMMAND, "/Status"),
        ("/stat", UsageReason.UNKNOWN_COMMAND, "/stat"),
        ("/status@other_bot", UsageReason.UNKNOWN_COMMAND, "/status@other_bot"),
        ("/help", UsageReason.HELP, "help"),
        ("/start", UsageReason.HELP, "start"),
        (f"/help@{BOT}", UsageReason.HELP, "help"),
        ("/help me", UsageReason.MALFORMED, "help"),
        ("/log", UsageReason.MALFORMED, "log"),
        ("/log lunch", UsageReason.MALFORMED, "log"),
        ("/log brunch x 1 g", UsageReason.MALFORMED, "log"),
        ("/log Lunch x 1 g", UsageReason.MALFORMED, "log"),
        ("/log lunch++ x 1 g", UsageReason.MALFORMED, "log"),
        ("/log lunch 150 g", UsageReason.MALFORMED, "log"),
        ("/log lunch a 1 g,", UsageReason.MALFORMED, "log"),
        ("/log lunch a 1 g,, b 1 g", UsageReason.MALFORMED, "log"),
        ("/log lunch a -1 g", UsageReason.MALFORMED, "log"),
        ("/log lunch --json 1 g", UsageReason.MALFORMED, "log"),
        ("/show", UsageReason.MALFORMED, "show"),
        ("/show a b", UsageReason.MALFORMED, "show"),
        ("/show --json", UsageReason.MALFORMED, "show"),
        ("/void", UsageReason.MALFORMED, "void"),
        ("/void --json", UsageReason.MALFORMED, "void"),
        ("/void a --reason x", UsageReason.MALFORMED, "void"),
        ("/day a b", UsageReason.MALFORMED, "day"),
        ("/day --json", UsageReason.MALFORMED, "day"),
        ("/status now", UsageReason.MALFORMED, "status"),
        ("/today 2026-10-05", UsageReason.MALFORMED, "today"),
        ("/inbody --json", UsageReason.MALFORMED, "inbody"),
        ("/daily --after-workout", UsageReason.MALFORMED, "daily"),
    ],
)
def test_everything_else_gets_help_or_usage(text: str | None, reason: UsageReason, command: str | None) -> None:
    assert parse(text) == UsageReply(reason, command)


HELP_LINES = [
    "muscle50 명령:",
    "/today [full] - 오늘 운동 추천 요약(full: 전체 리포트)",
    "/status [full] - 오늘 영양 상태 요약, 목표 대비(full: 전체)",
    "/day [YYYY-MM-DD] - 그날 식사와 합계(기본: 오늘)",
    "/log <meal>[+] <food> <qty> <unit>[, <food> <qty> <unit> ...] - 식사 기록",
    "     meal: breakfast, lunch, dinner, snack, other. 끝에 +를 붙이면 같은 종류 식사를 하나 더 기록",
    "     메뉴·영양값을 모르는 식사: <food> <qty> <unit> 대신 일반식 [메모] (예: /log lunch 일반식 구내식당)",
    "/void <meal_id> [이유] - 기록한 식사 취소(void)",
    "/show <meal_id> - 기록한 식사 하나 보기",
    "/inbody - InBody 체성분 추세",
    "/daily [full] - Garmin 동기화 후 오늘 계획 요약(시간이 걸림, full: 전체 리포트)",
    "/unknown - Garmin UNKNOWN 세트가 있는 최근 운동(링크와 /refresh)",
    "/refresh - UNKNOWN 세트가 있는 최근 운동을 모두 다시 받기(한 번에 10개까지)",
    "/refresh <activity_id> - Garmin에서 고친 운동 하나를 다시 받기",
    "/help - 이 목록",
]


def test_bot_reply_texts_are_pinned() -> None:
    assert HELP_TEXT.split("\n") == HELP_LINES
    assert usage_reply_text(UsageReply(UsageReason.HELP, "start")) == HELP_TEXT
    assert usage_reply_text(UsageReply(UsageReason.UNKNOWN_COMMAND, "/foo")) == (
        "모르는 명령입니다: /foo\n\n" + HELP_TEXT
    )
    assert usage_reply_text(UsageReply(UsageReason.NOT_A_COMMAND, None)) == "명령이 아닙니다.\n\n" + HELP_TEXT
    assert usage_reply_text(UsageReply(UsageReason.MALFORMED, "log")) == usage_text("log")
    assert usage_text("log") == (
        "사용법: /log <meal>[+] <food> <qty> <unit>[, <food> <qty> <unit> ...]\n"
        "meal은 breakfast, lunch, dinner, snack, other 중 하나이고, 끝에 +를 붙이면 같은 종류 식사를 하나 더 "
        "기록합니다. 각 item은 쉼표로 나누고, 마지막 두 단어가 수량과 단위입니다. "
        "메뉴·영양값을 모르는 식사는 item 자리에 일반식 [메모]를 씁니다(수량·단위 없음, 영양값은 unknown).\n"
        "예: /log lunch 닭가슴살 150 g, 햇반 1 pack"
    )
    assert usage_text("show") == "사용법: /show <meal_id>\n예: /show 2026-10-06-lunch-1"
    assert usage_text("void") == "사용법: /void <meal_id> [이유]\n예: /void 2026-10-06-snack-1 중복 기록"
    assert usage_text("day") == "사용법: /day [YYYY-MM-DD]\n예: /day 2026-10-05"
    assert usage_text("status") == "사용법: /status [full]\n예: /status full"
    assert undo_line("2026-10-06-lunch-1") == "취소: /void 2026-10-06-lunch-1"
    assert DAILY_PROGRESS_TEXT == (
        "daily 실행 중: 어제와 오늘의 Garmin 동기화 후 오늘 계획을 만듭니다. 끝나면 결과를 보냅니다."
    )
    assert GARMIN_LOGIN_TEXT == (
        "오류: Garmin에 다시 로그인해야 합니다. "
        "PC 터미널에서 muscle50 daily를 한 번 실행해 로그인한 뒤 /daily를 다시 보내세요."
    )
    assert MIGRATION_STATUS_UNKNOWN_TEXT == (
        "오류: DB의 migration 상태를 읽을 수 없어 실행하지 않았습니다. bot은 migration을 적용하지 않습니다. "
        "PC 터미널에서 DB를 확인하세요."
    )
    assert pending_migration_text((11, 12)) == (
        "오류: DB에 아직 적용하지 않은 migration 011, 012이 있습니다. bot은 migration을 적용하지 않습니다. "
        "DB를 백업한 뒤 PC 터미널에서 muscle50 명령 하나로 적용하고 다시 보내세요."
    )
    assert empty_output_text(1) == "오류: 명령이 아무것도 출력하지 않았습니다 (exit 1)."
    assert unexpected_error_text("RuntimeError") == (
        "오류: 예상하지 못한 오류로 명령을 마치지 못했습니다 (RuntimeError). telegram run 콘솔을 확인하세요."
    )

    assert stale_text(datetime(2026, 10, 6, 7, 12, 59)) == (
        "실행하지 않음: 이 메시지는 bot이 시작되기 전(2026-10-06 07:12)에 보낸 것입니다. 아직 필요하면 다시 보내세요."
    )


def test_every_known_command_has_a_usage_line() -> None:
    for command in ("today", "status", "day", "log", "void", "show", "inbody", "daily", "help", "start"):
        assert usage_text(command).startswith(f"사용법: /{command}")
