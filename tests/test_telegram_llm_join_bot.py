"""Telegram LLM v2.5 end to end: adding to a recorded meal (`join_existing`, `/new_`, `/add_`). A fake Bot API and a
fake LLM provider only, a temporary MUSCLE50_HOME and synthetic foods. Covers AC4 of
docs/specs/telegram-llm-failures-and-meals.md.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import test_telegram_llm_bot as bot
from test_telegram_llm_meals_bot import dishes, item, state_proposals

from muscle50.domain.nutrition import MealType
from muscle50.domain.telegram_llm import LlmOutputError, parse_interpretation
from muscle50.domain.telegram_llm_prompt import PROPOSAL_WRONG_KIND_TEXT, join_new_label, join_none_text

home = bot.home  # the autouse fixture of the bot tests: temporary MUSCLE50_HOME, fake clock, no network
BREAKFAST_1 = "2026-10-06-breakfast-1"
BREAKFAST_2 = "2026-10-06-breakfast-2"
SWEET_POTATO = "고구마 1개"


def _record_breakfast(capsys: pytest.CaptureFixture[str], *argv: str) -> None:
    items = argv or ("--item", "banana", "1", "count")
    bot._ok(capsys, "nutrition", "log", "--date", "2026-10-06", "--meal", "breakfast", *items)


def _meal(capsys: pytest.CaptureFixture[str], meal_id: str) -> dict[str, Any]:
    document: dict[str, Any] = json.loads(bot._ok(capsys, "nutrition", "meal", "show", meal_id, "--json"))
    return document


def _day_meal_ids(capsys: pytest.CaptureFixture[str]) -> list[str]:
    document = json.loads(bot._ok(capsys, "nutrition", "day", "--date", "2026-10-06", "--json"))
    return [meal["meal_id"] for meal in document["meals"]]


def _join_breakfast(**fields: Any) -> dict[str, Any]:
    return bot.meal(item(SWEET_POTATO, None, join_existing=True, **fields), meal_type="breakfast")


def _prepare(capsys: pytest.CaptureFixture[str], home: Path, *breakfasts: int) -> None:
    bot._catalog(capsys)
    bot._llm_config(home)
    for number in breakfasts:
        _record_breakfast(capsys, "--item", "banana", "1", "count", *(("--additional",) if number > 1 else ()))


def test_join_adds_to_the_one_recorded_meal_and_keeps_its_id(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    _prepare(capsys, home, 1)
    before = bot._tables(home)
    replies, _err, _fake = bot._session(
        monkeypatch, capsys, bot.FakeProvider(_join_breakfast()), bot.text(1, "아침에 고구마도 먹었어 하나에 같이")
    )
    lines = replies[0].split("\n")
    assert lines[0] == f"기존 아침 {BREAKFAST_1}(바나나 (banana) 1 count)에 추가할까요? (10-06)"
    assert lines[-1] == (
        "추가: /ok_7f3a   일반식만 추가(값 없이): /plain_7f3a   새 아침으로 따로: /new_7f3a   취소: /no_7f3a"
    )
    assert not any("하나 더 기록합니다" in line for line in lines)
    assert bot._tables(home) == before  # nothing before /ok
    (proposal,) = state_proposals(home)
    assert proposal["argv_ok"][:4] == ["nutrition", "meal", "add-item", BREAKFAST_1]
    assert (proposal["join_meal_id"], proposal["alt_action"]) == (BREAKFAST_1, "new")
    assert proposal["argv_alt"][:2] == ["nutrition", "log"] and proposal["argv_alt"][-1] == "--additional"
    replies, _err, _fake = bot._session(monkeypatch, capsys, bot.FakeProvider(), bot.text(2, "/ok_7f3a"))
    assert BREAKFAST_1 in replies[0] and "취소: /void" not in replies[0]
    assert _day_meal_ids(capsys) == [BREAKFAST_1]
    assert len(_meal(capsys, BREAKFAST_1)["items"]) == 2
    confirm = bot._history(home)[-1]
    assert (confirm["kind"], confirm["result"]) == ("confirm", {"exit_code": 0, "meal_id": BREAKFAST_1})


def test_new_records_a_separate_meal_instead(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    _prepare(capsys, home, 1)
    bot._session(monkeypatch, capsys, bot.FakeProvider(_join_breakfast()), bot.text(1, "아침 고구마 같이"))
    replies, _err, _fake = bot._session(monkeypatch, capsys, bot.FakeProvider(), bot.text(2, "/new_7f3a"))
    assert _day_meal_ids(capsys) == [BREAKFAST_1, BREAKFAST_2]
    assert len(_meal(capsys, BREAKFAST_1)["items"]) == 1
    assert BREAKFAST_2 in replies[0]
    replies, _err, _fake = bot._session(monkeypatch, capsys, bot.FakeProvider(), bot.text(3, "/ok_7f3a"))
    assert replies == ["이미 처리한 제안입니다. /day로 확인하세요."]  # one choice only


def test_plain_join_adds_the_item_without_values(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    _prepare(capsys, home, 1)
    bot._session(monkeypatch, capsys, bot.FakeProvider(_join_breakfast()), bot.text(1, "아침 고구마 같이"))
    bot._session(monkeypatch, capsys, bot.FakeProvider(), bot.text(2, "/plain_7f3a"))
    items = _meal(capsys, BREAKFAST_1)["items"]
    assert len(items) == 2 and _day_meal_ids(capsys) == [BREAKFAST_1]
    assert "general_estimate" not in json.dumps(items[1]) or items[1].get("general_estimate") is None


@pytest.mark.parametrize("command", ["/ok_7f3a", "/plain_7f3a"])
def test_a_voided_target_is_refused_nothing_is_written_and_the_proposal_stays_open(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path, command: str
) -> None:
    _prepare(capsys, home, 1)
    bot._session(monkeypatch, capsys, bot.FakeProvider(_join_breakfast()), bot.text(1, "아침 고구마 같이"))
    bot._ok(capsys, "nutrition", "meal", "void", BREAKFAST_1, "--reason", "synthetic")
    before = bot._tables(home)
    replies, _err, _fake = bot._session(monkeypatch, capsys, bot.FakeProvider(), bot.text(2, command))
    assert replies == [
        f"오류: 기존 아침 {BREAKFAST_1}이 없거나 취소(void)되어 추가하지 않았습니다. 새 끼니로 기록하려면 /new_7f3a"
    ]
    assert bot._tables(home) == before
    assert state_proposals(home)[0]["state"] == "open"
    bot._session(monkeypatch, capsys, bot.FakeProvider(), bot.text(3, "/new_7f3a"))
    assert BREAKFAST_2 in _day_meal_ids(capsys)


def test_no_recorded_meal_records_a_new_one_and_says_why(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    _prepare(capsys, home)
    replies, _err, _fake = bot._session(
        monkeypatch, capsys, bot.FakeProvider(_join_breakfast()), bot.text(1, "아침 고구마 같이")
    )
    lines = replies[0].split("\n")
    assert lines[:2] == ["기존 아침이 없어 새로 기록합니다.", "이렇게 기록할까요? (아침, 10-06)"]
    assert lines[-1] == "기록: /ok_7f3a   일반식만 기록(값 없이): /plain_7f3a   취소: /no_7f3a"
    (proposal,) = state_proposals(home)
    assert proposal["argv_ok"][:2] == ["nutrition", "log"] and proposal["alt_action"] == ""


def test_two_recorded_meals_are_never_guessed_between(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    _prepare(capsys, home, 1, 2)
    replies, _err, _fake = bot._session(
        monkeypatch, capsys, bot.FakeProvider(_join_breakfast()), bot.text(1, "아침 고구마 같이")
    )
    lines = replies[0].split("\n")
    assert lines[0] == (
        f"같은 날 아침이 여러 개({BREAKFAST_1}, {BREAKFAST_2})라 어디에 더할지 정하지 않았습니다. 하나 더 기록합니다."
    )
    assert lines[-1] == "기록: /ok_7f3a   일반식만 기록(값 없이): /plain_7f3a   취소: /no_7f3a"
    assert state_proposals(home)[0]["argv_ok"][-1] == "--additional"


def test_a_mixed_meal_does_not_join(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    _prepare(capsys, home, 1)
    mixed = bot.meal(
        item(SWEET_POTATO, None, join_existing=True), item("두유 1팩", None, join_existing=False), meal_type="breakfast"
    )
    replies, _err, _fake = bot._session(monkeypatch, capsys, bot.FakeProvider(mixed), bot.text(1, "아침"))
    assert replies[0].split("\n")[-1].endswith("기존 아침에 추가: /add_7f3a   취소: /no_7f3a")


def test_without_join_words_add_offers_the_recorded_meal(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    _prepare(capsys, home, 1)
    plain_breakfast = bot.meal(item(SWEET_POTATO, None), meal_type="breakfast")
    replies, _err, _fake = bot._session(monkeypatch, capsys, bot.FakeProvider(plain_breakfast), bot.text(1, "아침"))
    lines = replies[0].split("\n")
    assert lines[0] == f"이미 기록된 아침({BREAKFAST_1})이 있어 하나 더 기록합니다."
    assert lines[-1] == (
        "기록: /ok_7f3a   일반식만 기록(값 없이): /plain_7f3a   기존 아침에 추가: /add_7f3a   취소: /no_7f3a"
    )
    replies, _err, _fake = bot._session(monkeypatch, capsys, bot.FakeProvider(), bot.text(2, "/add_7f3a"))
    assert _day_meal_ids(capsys) == [BREAKFAST_1] and len(_meal(capsys, BREAKFAST_1)["items"]) == 2


def test_add_to_a_voided_meal_is_refused_with_the_new_meal_hint(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    _prepare(capsys, home, 1)
    plain_breakfast = bot.meal(item(SWEET_POTATO, None), meal_type="breakfast")
    bot._session(monkeypatch, capsys, bot.FakeProvider(plain_breakfast), bot.text(1, "아침"))
    bot._ok(capsys, "nutrition", "meal", "void", BREAKFAST_1, "--reason", "synthetic")
    before = bot._tables(home)
    replies, _err, _fake = bot._session(monkeypatch, capsys, bot.FakeProvider(), bot.text(2, "/add_7f3a"))
    assert replies == [
        f"오류: 기존 아침 {BREAKFAST_1}이 없거나 취소(void)되어 추가하지 않았습니다. 하나 더 기록하려면 /ok_7f3a"
    ]
    assert bot._tables(home) == before and state_proposals(home)[0]["state"] == "open"


def test_an_overlapping_join_shows_the_notice_and_no_fix(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    _prepare(capsys, home, 1)
    banana = bot.meal(bot._item("바나나", 1, "count", join_existing=True), meal_type="breakfast")
    replies, _err, _fake = bot._session(monkeypatch, capsys, bot.FakeProvider(banana), bot.text(1, "바나나 같이"))
    lines = replies[0].split("\n")
    assert lines[0] == f"오늘 아침({BREAKFAST_1})에 이미 같은 음식이 있습니다: 바나나"
    assert lines[1].startswith(f"기존 아침 {BREAKFAST_1}(")
    assert "/fix_" not in replies[0] and lines[-1].startswith("추가: /ok_7f3a")


def test_new_and_add_are_refused_where_they_do_not_apply(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    _prepare(capsys, home)
    replies, _err, _fake = bot._session(
        monkeypatch,
        capsys,
        bot.FakeProvider(bot.LUNCH_MEAL),
        bot.text(1, "점심"),
        bot.text(2, "/new_7f3a"),
        bot.text(3, "/add_7f3a"),
    )
    assert replies[1:] == [PROPOSAL_WRONG_KIND_TEXT, PROPOSAL_WRONG_KIND_TEXT]
    assert state_proposals(home)[0]["state"] == "open"


def test_multi_meal_joins_per_meal(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    _prepare(capsys, home, 1)
    document = dishes(item(SWEET_POTATO, "breakfast", join_existing=True), item("김밥 1줄", "lunch"))
    replies, _err, _fake = bot._session(monkeypatch, capsys, bot.FakeProvider(document), bot.text(1, "아침 같이"))
    lines = replies[0].split("\n")
    assert lines[0] == "이렇게 기록할까요? (10-06, 2끼)"
    assert f"아침: 기존 {BREAKFAST_1}에 추가" in lines and "점심" in lines
    assert lines[-1] == (
        "기록: /ok_7f3a   값 없이 일반식만 기록: /plain_7f3a   새 끼니로 따로: /new_7f3a   취소: /no_7f3a"
    )
    meals = state_proposals(home)[0]["meals"]
    assert (meals[0]["join_meal_id"], meals[1]["join_meal_id"]) == (BREAKFAST_1, None)
    bot._session(monkeypatch, capsys, bot.FakeProvider(), bot.text(2, "/ok_7f3a"))
    assert _day_meal_ids(capsys) == [BREAKFAST_1, "2026-10-06-lunch-1"]
    assert len(_meal(capsys, BREAKFAST_1)["items"]) == 2
    result = bot._history(home)[-1]["result"]
    assert result["meal_ids"] == [BREAKFAST_1, "2026-10-06-lunch-1"]


def test_multi_meal_new_records_every_meal_as_a_new_one(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    _prepare(capsys, home, 1)
    document = dishes(item(SWEET_POTATO, "breakfast", join_existing=True), item("김밥 1줄", "lunch"))
    bot._session(monkeypatch, capsys, bot.FakeProvider(document), bot.text(1, "아침 같이"))
    bot._session(monkeypatch, capsys, bot.FakeProvider(), bot.text(2, "/new_7f3a"))
    assert _day_meal_ids(capsys) == [BREAKFAST_1, BREAKFAST_2, "2026-10-06-lunch-1"]


def test_a_multi_meal_join_target_gone_is_refused(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    _prepare(capsys, home, 1)
    document = dishes(item(SWEET_POTATO, "breakfast", join_existing=True), item("김밥 1줄", "lunch"))
    bot._session(monkeypatch, capsys, bot.FakeProvider(document), bot.text(1, "아침 같이"))
    bot._ok(capsys, "nutrition", "meal", "void", BREAKFAST_1, "--reason", "synthetic")
    before = bot._tables(home)
    replies, _err, _fake = bot._session(monkeypatch, capsys, bot.FakeProvider(), bot.text(2, "/ok_7f3a"))
    assert replies[0].startswith(f"오류: 기존 아침 {BREAKFAST_1}이 없거나")
    assert bot._tables(home) == before


# --- pure parts ------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("value", ["yes", 1, None])
def test_join_existing_must_be_a_boolean(value: object) -> None:
    document = _join_breakfast()
    document["items"][0]["join_existing"] = value
    with pytest.raises(LlmOutputError):
        parse_interpretation(document)
    del document["items"][0]["join_existing"]
    with pytest.raises(LlmOutputError):
        parse_interpretation(document)
    assert parse_interpretation(_join_breakfast()).items[0].join_existing is True


def test_join_texts_use_the_right_particles() -> None:
    assert join_none_text(MealType.OTHER) == "기존 기타가 없어 새로 기록합니다."
    assert join_none_text(MealType.LUNCH) == "기존 점심이 없어 새로 기록합니다."
    assert join_new_label(MealType.BREAKFAST) == "새 아침으로 따로"
    assert join_new_label(MealType.OTHER) == "새 기타로 따로"
