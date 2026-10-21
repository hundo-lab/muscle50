"""Telegram LLM v2.5: the coach knows the bot's commands and the last 14 days of Garmin sync coverage. Pure functions
and the bot with a fake Bot API and a fake provider (never the real `claude`/`codex`), a temporary MUSCLE50_HOME and
synthetic values. Covers AC6 of docs/specs/telegram-llm-failures-and-meals.md.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pytest
import test_telegram_llm_bot as bot
from test_telegram_llm_domain import interpretation

from muscle50.domain.llm_number_guard import allowed_numbers, unknown_numbers
from muscle50.domain.telegram_commands import help_text
from muscle50.domain.telegram_llm_context import (
    NO_GAPS_TEXT,
    NO_TABLE_TEXT,
    command_lines,
    coverage_range,
    coverage_summary,
    known_commands,
)
from muscle50.domain.telegram_llm_prompt import TASKS, PromptTask, build_prompt

home = bot.home  # the autouse fixture of the bot tests: temporary MUSCLE50_HOME, fake clock, no network
TODAY = date(2026, 10, 21)


def _day(day: date, activities: str = "synced", recovery: str = "synced", stored: int = 1) -> dict[str, Any]:
    return {
        "date": day.isoformat(),
        "activities": {"status": activities, "stored_activities": stored, "failed_activity_ids": []},
        "recovery": {"status": recovery, "missing_endpoints": []},
    }


def _coverage(overrides: dict[int, dict[str, Any]] | None = None, *, present: bool = True) -> dict[str, Any]:
    start, _end = coverage_range(TODAY)
    days = []
    for offset in range(14):
        day = start + timedelta(days=offset)
        days.append((overrides or {}).get(day.day, _day(day)))
    return {"from": start.isoformat(), "to": TODAY.isoformat(), "coverage_table_present": present, "days": days}


# --- the coverage summary ---------------------------------------------------------------------------------


def test_no_gap_gives_exactly_no_missing_days() -> None:
    lines = coverage_summary(_coverage(), TODAY).split("\n")
    assert lines == ["기간 10-08~10-21 (14일, 오늘 포함)", NO_GAPS_TEXT, "오늘: 운동 동기화됨, 회복 동기화됨"]
    assert lines[1] == "빠진 날 없음"


def test_gaps_are_grouped_and_synced_without_training_is_its_own_line() -> None:
    overrides = {day: _day(date(2026, 10, day), "not_synced", "not_synced") for day in range(9, 19)}
    overrides[19] = _day(date(2026, 10, 19), stored=0)
    overrides[20] = _day(date(2026, 10, 20), recovery="partial")
    overrides[21] = _day(TODAY, "not_synced", "not_synced")
    assert coverage_summary(_coverage(overrides), TODAY).split("\n") == [
        "기간 10-08~10-21 (14일, 오늘 포함)",
        "운동 동기화 안 됨: 10-09~10-18",
        "회복 동기화 안 됨: 10-09~10-18 · 회복 일부만: 10-20",
        "동기화했고 운동 없음: 10-19",
        "오늘: 운동 동기화 안 됨, 회복 동기화 안 됨",
    ]


def test_failed_days_and_days_missing_from_the_document_are_not_synced_or_failed() -> None:
    document = _coverage({10: _day(date(2026, 10, 10), "failed", "failed")})
    document["days"] = [day for day in document["days"] if day["date"] != "2026-10-12"]
    lines = coverage_summary(document, TODAY).split("\n")
    assert lines[1] == "운동 동기화 안 됨: 10-12 · 운동 동기화 실패: 10-10"
    assert lines[2] == "회복 동기화 안 됨: 10-12 · 회복 동기화 실패: 10-10"


def test_no_coverage_table_is_unknown_never_no_missing_days() -> None:
    assert coverage_summary(_coverage(present=False), TODAY) == NO_TABLE_TEXT
    assert NO_GAPS_TEXT not in NO_TABLE_TEXT and "알 수 없음" in NO_TABLE_TEXT


def test_a_document_of_another_shape_raises() -> None:
    with pytest.raises((KeyError, TypeError, ValueError)):
        coverage_summary({"days": []}, TODAY)
    with pytest.raises((KeyError, TypeError, ValueError)):
        coverage_summary({"coverage_table_present": True, "days": [{"date": "x"}]}, TODAY)


# --- commands -----------------------------------------------------------------------------------------------


def test_known_commands_come_from_the_help_text_and_answers_get_tappable_lines() -> None:
    known = known_commands(help_text(True))
    assert known[:3] == ("/today", "/status", "/day")
    assert known.count("/refresh") == 1 and "/history" in known
    answer = (
        "동기화는 /daily 로 합니다. 하나만 다시 받으려면 /refresh 를 쓰세요. /daily 는 시간이 걸립니다. /madeup 은 없음"
    )
    assert command_lines(answer, known) == ("/daily", "/refresh")
    many = " ".join(["/today", "/status", "/day", "/log", "/void", "/show"])
    assert command_lines(many, known) == ("/today", "/status", "/day", "/log")


def test_the_answer_prompt_has_the_commands_after_the_task_and_other_prompts_do_not() -> None:
    common: dict[str, Any] = {
        "persona_name": "머슬",
        "persona_tone": "짧게",
        "coach_guide": None,
        "memory": None,
        "data": [("동기화 상태", "빠진 날 없음")],
        "message": "동기화 명령어 뭐야?",
        "has_photo": False,
    }
    answer = build_prompt(PromptTask.ANSWER, commands="/daily - 동기화", **common)
    assert f"{TASKS[PromptTask.ANSWER]}\n\n[bot 명령]\n/daily - 동기화\n\n[데이터]" in answer
    for task in (PromptTask.INTERPRET, PromptTask.SUGGEST):
        assert "[bot 명령]" not in build_prompt(task, **common)
    assert build_prompt(PromptTask.ANSWER, **common) == answer.replace("[bot 명령]\n/daily - 동기화\n\n", "")


def test_the_help_digits_are_not_numbers_an_answer_may_use() -> None:
    allowed = allowed_numbers(["빠진 날 없음"])
    assert unknown_numbers("한 번에 10개까지 다시 받습니다", allowed)  # `10` is only in the help text


# --- the bot -------------------------------------------------------------------------------------------------


def _question(*topics: str) -> dict[str, Any]:
    return interpretation(intent="question", items=[], question_topics=list(topics), tense="none")


def _answer(text: str) -> dict[str, Any]:
    return {"answer": text, "memory_summary": ""}


def test_a_training_question_gets_the_commands_and_the_sync_state(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    bot._catalog(capsys)  # creates and migrates the database (no Garmin data: nothing is synced)
    bot._llm_config(home)
    provider = bot.FakeProvider(
        _question("training"), _answer("10-06은 동기화되지 않았습니다. /daily 로 동기화하세요.")
    )
    replies, err, _fake = bot._session(monkeypatch, capsys, provider, bot.text(1, "오늘 운동 뭐야?"))
    prompt = provider.requests[1][0].prompt
    assert f"[bot 명령]\n{help_text(True)}\n\n" in prompt
    assert "<동기화 상태>\n기간 09-23~10-06 (14일, 오늘 포함)\n운동 동기화 안 됨: 09-23~10-05" in prompt
    assert "동기화 안 된 날을 운동이나 회복 기록이 없는 날이라고 말하지 않고" in prompt
    assert replies == ["10-06은 동기화되지 않았습니다. /daily 로 동기화하세요.\n(근거: /today)"]  # no command lines
    assert "garmin read" not in err


def test_a_bot_question_answers_with_tappable_commands(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    bot._catalog(capsys)
    bot._llm_config(home)
    answer = "운동·회복 받아오기는 /daily 입니다. 운동 하나만 다시 받으려면 /refresh 를 쓰세요."
    provider = bot.FakeProvider(_question("bot"), _answer(answer))
    replies, _err, _fake = bot._session(monkeypatch, capsys, provider, bot.text(1, "동기화 명령어 뭐야?"))
    assert replies == [f"{answer}\n(근거: /help)\n/daily\n/refresh"]
    assert "<동기화 상태>\n기간 09-23~10-06" in provider.requests[1][0].prompt


def test_a_bot_question_whose_answer_fails_the_number_guard_gets_the_help(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    bot._llm_config(home)  # no database: the coverage read fails and the block is left out
    provider = bot.FakeProvider(_question("bot"), _answer("/refresh 는 한 번에 10개까지 받습니다."))
    replies, err, _fake = bot._session(monkeypatch, capsys, provider, bot.text(1, "명령어 뭐야?"))
    assert replies == [help_text(True)]
    assert "<동기화 상태>\n" not in provider.requests[1][0].prompt  # the data block (the rule names it too)
    assert "numbers outside the data" in err
