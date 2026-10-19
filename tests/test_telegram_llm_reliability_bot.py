"""Telegram LLM v2.4 end to end (AC2, AC3, AC6, AC7, AC8 of docs/specs/telegram-llm-reliability.md): the photo
failure wording, photos in the chat memory, the 4-hour menu proposal, short Korean `/ok` summaries and the sync
hint. `muscle50 telegram run` with a fake Bot API and a fake LLM provider (never the real `claude`/`codex`, never the
network), a temporary MUSCLE50_HOME and synthetic foods only.
"""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
import test_telegram_bot as v1
import test_telegram_llm_bot as bot
import test_telegram_llm_meals_bot as meals
from test_telegram_llm_corrections_bot import STEW_MENU, show_menu
from test_telegram_llm_domain import interpretation

import muscle50.cli as cli
from muscle50.application.telegram_bot import IncomingMessage, IncomingUpdate
from muscle50.domain.telegram_llm import MENU_PROPOSAL_TTL_S
from muscle50.domain.telegram_llm_prompt import PROPOSAL_EXPIRED_TEXT, SYNC_HINT_TEXT, menu_expired_text
from muscle50.infrastructure.telegram.cli_runner import InProcessCliRunner

home = bot.home  # the autouse fixture of the bot tests: temporary MUSCLE50_HOME, fake clock, no network, no real sleep
_isolated = v1.sleeps

FOUR_HOURS = 4 * 3600


def at(delta: timedelta, update_id: int, words: str, monkeypatch: pytest.MonkeyPatch) -> IncomingUpdate:
    """A text message ``delta`` after the fixed clock; the bot's clock moves with it."""
    later = bot.NOW + delta
    monkeypatch.setattr(cli, "_now", lambda: later)
    return IncomingUpdate(update_id, IncomingMessage(bot.ALLOWED, words, int(later.timestamp())))


def state(home: Path) -> list[dict[str, Any]]:
    return meals.state_proposals(home)


# --- AC6: menu proposals are valid for 4 hours, meal proposals for 60 minutes -----------------------------


def test_a_menu_proposal_is_stored_for_four_hours_and_a_meal_proposal_for_one(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    show_menu(monkeypatch, capsys, home)
    (menu,) = state(home)
    assert menu["kind"] == "menu" and menu["expires_unix"] - menu["created_unix"] == FOUR_HOURS == MENU_PROPOSAL_TTL_S
    bot._session(monkeypatch, capsys, bot.FakeProvider(), bot.text(2, "/eat_7f3a_1"))
    meal = state(home)[-1]
    assert meal["kind"] == "meal" and meal["expires_unix"] - meal["created_unix"] == 3600


def test_eat_works_at_3_hours_59_minutes_and_is_refused_at_4_hours(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    show_menu(monkeypatch, capsys, home)
    update = at(timedelta(hours=3, minutes=59), 2, "/eat_7f3a_1", monkeypatch)
    replies, _err, _fake = bot._session(monkeypatch, capsys, bot.FakeProvider(), update)
    assert replies[0].startswith("이렇게 기록할까요?")
    update = at(timedelta(hours=4), 3, "/eat_7f3a_2", monkeypatch)
    replies, _err, _fake = bot._session(monkeypatch, capsys, bot.FakeProvider(), update)
    assert replies == ["이 메뉴 제안은 유효 시간(4시간)이 지났습니다. 메뉴 사진을 다시 보내거나 다시 물어봐 주세요."]
    assert replies == [menu_expired_text(FOUR_HOURS)]


def test_the_one_second_edge_is_pinned_on_both_sides(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    # At exactly 4 h the menu is still offered to the LLM by name (`<=`), while `/eat_` is already expired
    # (`now >= expires_unix`). One second earlier both work.
    show_menu(monkeypatch, capsys, home)
    provider = bot.FakeProvider(bot.meal(bot._item("얼큰순살감자탕", None, None, kind="general", memo="x")))
    update = at(timedelta(hours=4), 2, "얼큰순살감자탕 먹었어", monkeypatch)
    bot._session(monkeypatch, capsys, provider, update)
    assert "<최근 메뉴>\n" in provider.requests[0][0].prompt
    update = at(timedelta(hours=4), 3, "/eat_7f3a_1", monkeypatch)
    replies, _err, _fake = bot._session(monkeypatch, capsys, bot.FakeProvider(), update)
    assert replies == [menu_expired_text(FOUR_HOURS)]
    update = at(timedelta(hours=4) - timedelta(seconds=1), 4, "/eat_7f3a_1", monkeypatch)
    replies, _err, _fake = bot._session(monkeypatch, capsys, bot.FakeProvider(), update)
    assert replies[0].startswith("이렇게 기록할까요?")


def test_a_meal_proposal_still_expires_at_sixty_minutes_with_its_own_text(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    show_menu(monkeypatch, capsys, home)
    bot._session(monkeypatch, capsys, bot.FakeProvider(), bot.text(2, "/eat_7f3a_1"))
    update = at(timedelta(minutes=61), 3, "/ok_91c0", monkeypatch)
    replies, _err, _fake = bot._session(monkeypatch, capsys, bot.FakeProvider(), update)
    assert replies == [PROPOSAL_EXPIRED_TEXT]


def test_a_menu_from_a_v2_3_state_file_keeps_its_sixty_minutes_and_says_so(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    show_menu(monkeypatch, capsys, home)
    path = home / "config" / "telegram_llm_state.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    document["proposals"][0]["expires_unix"] = document["proposals"][0]["created_unix"] + 3600
    path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8", newline="\n")
    update = at(timedelta(minutes=90), 2, "/eat_7f3a_1", monkeypatch)
    replies, _err, _fake = bot._session(monkeypatch, capsys, bot.FakeProvider(), update)
    assert replies == [menu_expired_text(3600)]
    assert "(60분)" in replies[0]
    # the same old menu is still a recent menu: it is offered by name for 4 hours
    provider = bot.FakeProvider(bot.meal(bot._item("얼큰순살감자탕", None, None, kind="general", memo="x")))
    bot._session(monkeypatch, capsys, provider, at(timedelta(minutes=91), 3, "얼큰순살감자탕 먹었어", monkeypatch))
    assert "<최근 메뉴>\n" in provider.requests[0][0].prompt


def test_the_menu_fixture_is_the_one_the_corrections_tests_use() -> None:
    assert STEW_MENU["photo_kind"] == "menu_capture"


# --- AC8: "동기화 해줘" gets the /daily and /refresh hint and nothing runs ---------------------------------

SYNC_REQUEST = interpretation(
    intent="sync_request", items=[], tense="none", meal_type=None, memory_summary="동기화 요청"
)
SYNC_REPLY = "동기화는 /daily 로 합니다. 운동 하나만 다시 받으려면 /refresh 를 쓰세요.\n/daily\n/refresh"


def test_a_sync_request_gets_the_hint_and_runs_and_stores_nothing(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    bot._catalog(capsys)
    bot._llm_config(home)
    before = bot._tables(home)

    def no_cli(self: object, argv: object) -> object:
        pytest.fail("a sync request must not run any CLI command")

    monkeypatch.setattr(InProcessCliRunner, "run", no_cli)
    provider = bot.FakeProvider(SYNC_REQUEST)
    replies, _err, fake = bot._session(monkeypatch, capsys, provider, bot.text(1, "동기화 해줘"))
    assert replies == [SYNC_REPLY] and SYNC_HINT_TEXT in replies[0]
    assert fake.sent[0][1].endswith("</pre>\n/daily\n/refresh")  # tappable command lines after the body
    assert bot._tables(home) == before
    assert not (home / "config" / "telegram_llm_state.json").exists()  # no proposal
    (entry,) = bot._history(home)
    assert (entry["intent"], entry["reply"]) == ("sync_request", SYNC_REPLY) and entry["proposal"] is None
    assert "동기화 안내" in bot._session(monkeypatch, capsys, bot.FakeProvider(), bot.text(2, "/history"))[0][0]


def test_the_prompts_carry_the_sync_rules(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    bot._catalog(capsys)
    bot._llm_config(home)
    provider = bot.FakeProvider(SYNC_REQUEST)
    bot._session(monkeypatch, capsys, provider, bot.text(1, "동기화 해줘"))
    assert "sync_request(" in provider.requests[0][0].prompt
    from muscle50.domain.telegram_llm_prompt import TASKS, PromptTask

    assert "/daily 로 동기화하라고 안내합니다" in TASKS[PromptTask.ANSWER]
