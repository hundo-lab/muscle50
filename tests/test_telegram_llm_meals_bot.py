"""Telegram LLM v2.2 end to end: multi-meal proposals, linking by the LLM's catalog ID, estimates and their
provenance, and the `/ok` sequence (one `nutrition log` per meal). `muscle50 telegram run` with a fake Bot API and
a fake LLM provider (never the real `claude`/`codex`, never the network), a temporary MUSCLE50_HOME and synthetic
foods only. Covers AC1-AC4, AC6 and AC11 of docs/specs/telegram-llm-meal-estimates.md."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest
import test_telegram_bot as v1
import test_telegram_llm_bot as bot
from test_telegram_llm_domain import NULL_ESTIMATE, interpretation

import muscle50.cli as cli
from muscle50.domain.telegram_commands import pending_migration_text
from muscle50.domain.telegram_llm import LlmState, Proposal, ProposalKind, ProposalState
from muscle50.domain.telegram_llm_prompt import PROPOSAL_NO_PLAIN_TEXT, PROPOSAL_USED_TEXT
from muscle50.infrastructure.sqlite.food_catalog_reader import SqliteFoodCatalogReader
from muscle50.infrastructure.sqlite.schema_status import code_migration_versions
from muscle50.infrastructure.telegram.llm_state_store import JsonLlmStateStore

home = bot.home  # the autouse fixture of the bot tests: temporary MUSCLE50_HOME, fake clock, no network
STATE = "telegram_llm_state.json"


def est(kcal: tuple[int, int], protein: tuple[int, int], **more: float) -> dict[str, Any]:
    return {
        **NULL_ESTIMATE,
        "kcal_min": kcal[0],
        "kcal_max": kcal[1],
        "protein_min": protein[0],
        "protein_max": protein[1],
        **more,
    }


def item(food: str, meal: str | None, **fields: Any) -> dict[str, Any]:
    """A general item (kind general) unless ``fields`` say otherwise."""
    return bot._item(food, None, None, kind="general", memo=food, meal_type=meal, **fields)


def catalog_item(
    food: str, meal: str | None, quantity: float | None, unit: str | None, **fields: Any
) -> dict[str, Any]:
    return bot._item(food, quantity, unit, meal_type=meal, **fields)


def dishes(*items: dict[str, Any], **fields: Any) -> dict[str, Any]:
    """A meal_log document whose meals are named on the items (the top-level meal_type is null)."""
    return interpretation(items=list(items), meal_type=None, **fields)


# The real-message shape: breakfast (two catalog foods, one linked by the LLM's ID), lunch and dinner (general).
THREE_MEALS = dishes(
    catalog_item("닭가슴살", "breakfast", 2, "pack"),
    catalog_item("즉석밥", "breakfast", 1, "pack", food_id="hetbahn-210"),
    item(
        "소고기활전복 미역국",
        "lunch",
        estimate=est((650, 950), (35, 55)),
        assumption="보돌미역 메뉴를 못 찾아 일반 소고기전복미역국 정식으로 추정",
        source="namu.wiki",
    ),
    item("김밥 2.5줄", "dinner", estimate=est((800, 1150), (25, 40))),
    item("오뎅국 1그릇", "dinner", estimate=est((150, 300), (10, 20))),
)
THREE_MEALS_PROPOSAL = "\n".join(
    [
        "이렇게 기록할까요? (10-06, 3끼)",
        "아침",
        "  1. 닭가슴살 (chicken-breast) 2 pack",
        '  2. 햇반 (hetbahn-210) 1 pack ← "즉석밥"',
        "점심",
        "  1. 일반식 (메모: 소고기활전복 미역국)",
        "     추정: kcal 650~950, 단백질 35~55 g (estimated)",
        "     가정: 보돌미역 메뉴를 못 찾아 일반 소고기전복미역국 정식으로 추정",
        "     출처: namu.wiki",
        "저녁",
        "  1. 일반식 (메모: 김밥 2.5줄)",
        "     추정: kcal 800~1150, 단백질 25~40 g (estimated)",
        "  2. 일반식 (메모: 오뎅국 1그릇)",
        "     추정: kcal 150~300, 단백질 10~20 g (estimated)",
        "기록: /ok_7f3a   값 없이 일반식만 기록: /plain_7f3a   취소: /no_7f3a",
    ]
)
MESSAGE = "오늘 아침 닭가슴살 2팩 즉석밥 1개, 점심 소고기활전복 미역국, 저녁 김밥 두줄 반 오뎅국 1개"


def state_proposals(home: Path) -> list[dict[str, Any]]:
    document = json.loads((home / "config" / STATE).read_text(encoding="utf-8"))
    return list(document["proposals"])


def meal_tables(root: Path) -> dict[str, list[tuple[Any, ...]]]:
    return {name: rows for name, rows in bot._tables(root).items() if name.startswith("nutrition")}


def propose(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    home: Path,
    document: dict[str, Any],
    *,
    prepared: bool = False,
    update_id: int = 1,
) -> tuple[list[str], bot.FakeProvider]:
    if not prepared:
        bot._catalog(capsys)
        bot._llm_config(home)
    provider = bot.FakeProvider(document)
    replies, _err, _fake = bot._session(monkeypatch, capsys, provider, bot.text(update_id, MESSAGE))
    return replies, provider


# --- AC1, AC2: one proposal, nothing written before /ok, one nutrition log per meal --------------------------------


def test_three_meals_in_one_sentence_make_one_proposal_and_write_nothing(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    bot._catalog(capsys)
    bot._llm_config(home)
    before = meal_tables(home)
    replies, _provider = propose(monkeypatch, capsys, home, THREE_MEALS, prepared=True)
    assert replies == [THREE_MEALS_PROPOSAL]
    assert meal_tables(home) == before  # nothing is written before /ok
    (proposal,) = state_proposals(home)
    assert proposal["argv_ok"] == [] and proposal["argv_plain"] == []
    assert [meal["meal_type"] for meal in proposal["meals"]] == ["breakfast", "lunch", "dinner"]
    head = ["nutrition", "log", "--date", "2026-10-06", "--meal"]
    reference = "--general-estimate-ref=telegram-llm text (claude sonnet)"
    assert proposal["meals"][0]["argv_ok"] == [
        *head,
        "breakfast",
        *("--item", "chicken-breast", "2", "pack", "--item", "hetbahn-210", "1", "pack"),
    ]
    assert proposal["meals"][0]["argv_plain"] == []  # no estimate in this meal
    lunch = proposal["meals"][1]["argv_ok"]
    assert lunch[:9] == [
        *head,
        "lunch",
        *("--general", "--general-note=소고기활전복 미역국"),
        "--general-estimate=language_estimate:kcal=650-950,protein=35-55",
    ]
    assert (
        len(lunch) == 10
        and lunch[9].startswith(f"{reference}; 출처: namu.wiki; 가정: 보돌미역")
        and len(lunch[9]) <= 117
    )
    assert proposal["meals"][2]["argv_ok"][:6] == [*head, "dinner"]
    assert proposal["meals"][2]["argv_ok"].count("--general") == 2
    assert proposal["meals"][2]["argv_plain"][6:] == [
        *("--general", "--general-note=김밥 2.5줄", "--general", "--general-note=오뎅국 1그릇")
    ]


def test_ok_runs_one_nutrition_log_per_meal_and_the_rows_equal_the_cli(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path, tmp_path: Path
) -> None:
    replies, _provider = propose(monkeypatch, capsys, home, THREE_MEALS)
    (proposal,) = state_proposals(home)
    replies, err, _fake = bot._session(monkeypatch, capsys, bot.FakeProvider(), bot.text(2, "/ok_7f3a"))
    assert len(replies) == 1
    reply = replies[0]
    for meal_id in ("2026-10-06-breakfast-1", "2026-10-06-lunch-1", "2026-10-06-dinner-1"):
        assert f"Recorded meal {meal_id}." in reply and f"취소: /void {meal_id}" in reply
    assert reply.index("breakfast-1") < reply.index("lunch-1") < reply.index("dinner-1")
    assert reply.count("\n\n") >= 3 and "오늘 누적:" in reply and reply.split("\n\n")[-1].startswith("오늘 누적:")
    assert "chat 111: proposal 7f3a confirmed (3 meals)" in err
    after = meal_tables(home)
    # the same three argvs typed in the CLI on a twin home give the same rows
    twin = tmp_path / "twin"
    monkeypatch.setenv("MUSCLE50_HOME", str(twin))
    bot._catalog(capsys)
    for meal in proposal["meals"]:
        bot._ok(capsys, *meal["argv_ok"])
    twin_rows = meal_tables(twin)
    assert after["nutrition_meals"] == twin_rows["nutrition_meals"]
    assert after["nutrition_meal_items"] == twin_rows["nutrition_meal_items"]
    assert after["nutrition_facts"] == twin_rows["nutrition_facts"]
    # a repeated /ok says used and records nothing more
    monkeypatch.setenv("MUSCLE50_HOME", str(home))
    replies, _err, _fake = bot._session(monkeypatch, capsys, bot.FakeProvider(), bot.text(3, "/ok_7f3a"))
    assert replies == [PROPOSAL_USED_TEXT] and meal_tables(home) == after


def test_estimates_are_stored_as_language_estimates_with_the_provenance_note(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    propose(monkeypatch, capsys, home, THREE_MEALS)
    bot._session(monkeypatch, capsys, bot.FakeProvider(), bot.text(2, "/ok_7f3a"))
    lunch = json.loads(bot._ok(capsys, "nutrition", "meal", "show", "2026-10-06-lunch-1", "--json"))
    fact = lunch["items"][0]["facts"][0]
    assert lunch["items"][0]["nutrients"]["calories_kcal"]["source_type"] == "language_estimate"
    assert (
        lunch["items"][0]["nutrients"]["calories_kcal"]["minimum"],
        lunch["items"][0]["nutrients"]["calories_kcal"]["maximum"],
    ) == ("650", "950")
    nutrients = lunch["items"][0]["nutrients"]
    assert nutrients["carbohydrate_g"] is None and nutrients["fat_g"] is None  # unknown, never 0
    reference = fact["source_reference"]
    assert reference.startswith("telegram-llm text (claude sonnet); 출처: namu.wiki; 가정: ") and len(reference) <= 100
    assert "://" not in reference and "www." not in reference
    day = bot._ok(capsys, "nutrition", "day")
    assert "Estimated: kcal, protein include values from facts marked estimated." in day
    dinner = json.loads(bot._ok(capsys, "nutrition", "meal", "show", "2026-10-06-dinner-1", "--json"))
    assert [entry["note"] for entry in dinner["items"]] == ["김밥 2.5줄", "오뎅국 1그릇"]
    assert all(
        entry["facts"][0]["source_reference"] == "telegram-llm text (claude sonnet)" for entry in dinner["items"]
    )


def test_plain_records_every_meal_without_values(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    propose(monkeypatch, capsys, home, THREE_MEALS)
    replies, _err, _fake = bot._session(monkeypatch, capsys, bot.FakeProvider(), bot.text(2, "/plain_7f3a"))
    assert "2026-10-06-breakfast-1" in replies[0] and "2026-10-06-dinner-1" in replies[0]
    lunch = json.loads(bot._ok(capsys, "nutrition", "meal", "show", "2026-10-06-lunch-1", "--json"))
    assert lunch["items"][0]["facts"] == [] and lunch["items"][0]["note"] == "소고기활전복 미역국"
    breakfast = json.loads(bot._ok(capsys, "nutrition", "meal", "show", "2026-10-06-breakfast-1", "--json"))
    assert [
        entry["food_profile_id"] if "food_profile_id" in entry else entry["food_id"] for entry in breakfast["items"]
    ] == [
        "chicken-breast",
        "hetbahn-210",
    ]
    history = bot._history(home)[-1]
    assert history["kind"] == "plain" and history["result"]["exit_code"] == 0


def test_plain_is_not_offered_when_no_meal_has_an_estimate(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    document = dishes(catalog_item("닭가슴살", "breakfast", 1, "pack"), catalog_item("사과", "lunch", 1, "count"))
    replies, _provider = propose(monkeypatch, capsys, home, document)
    assert "plain" not in replies[0] and replies[0].splitlines()[0] == "이렇게 기록할까요? (10-06, 2끼)"
    replies, _err, _fake = bot._session(monkeypatch, capsys, bot.FakeProvider(), bot.text(2, "/plain_7f3a"))
    assert replies == [PROPOSAL_NO_PLAIN_TEXT.format(token="7f3a")]
    assert not any(row for name, rows in meal_tables(home).items() if name == "nutrition_meals" for row in rows)


def test_a_meal_without_estimates_runs_its_ok_argv_under_plain(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    document = dishes(catalog_item("닭가슴살", "breakfast", 1, "pack"), item("국밥", "lunch"))
    propose(monkeypatch, capsys, home, document)
    bot._session(monkeypatch, capsys, bot.FakeProvider(), bot.text(2, "/plain_7f3a"))
    breakfast = json.loads(bot._ok(capsys, "nutrition", "meal", "show", "2026-10-06-breakfast-1", "--json"))
    assert breakfast["items"][0]["nutrients"]["calories_kcal"]["value"] == "165"


# --- AC2: a failing meal stops the sequence -----------------------------------------------------------------------


def test_a_failing_second_meal_keeps_the_first_and_does_not_run_the_third(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    propose(monkeypatch, capsys, home, THREE_MEALS)
    # a same-type lunch typed after the proposal makes the proposal's lunch command fail (no --additional)
    bot._session(monkeypatch, capsys, bot.FakeProvider(), bot.text(2, "/log lunch 닭가슴살 100 g"))
    replies, err, _fake = bot._session(monkeypatch, capsys, bot.FakeProvider(), bot.text(3, "/ok_7f3a"))
    (reply,) = replies
    head, failure = reply.split("실패: 점심 - ")
    assert head.startswith("Recorded meal 2026-10-06-breakfast-1.")
    assert head.removesuffix("\n\n").endswith("취소: /void 2026-10-06-breakfast-1")
    assert failure.startswith("오류:")
    assert "\n실행하지 않음: 저녁\n남은 끼니는 다시 보내거나 /log로 기록하세요.\n오늘 누적:" in failure
    assert "2026-10-06-dinner" not in reply
    rows = bot._tables(home)["nutrition_meals"]
    assert sorted(row[0] for row in rows) == ["2026-10-06-breakfast-1", "2026-10-06-lunch-1"]
    assert "chat 111: /ok 2/3 -> exit 1" in err
    replies, _err, _fake = bot._session(monkeypatch, capsys, bot.FakeProvider(), bot.text(4, "/ok_7f3a"))
    assert replies == [PROPOSAL_USED_TEXT]
    entry = bot._history(home)[-2]
    assert entry["kind"] == "confirm" and entry["result"] == {
        "exit_code": 1,
        "meal_id": "2026-10-06-breakfast-1",
        "meal_ids": ["2026-10-06-breakfast-1"],
        "failed": "lunch",
        "not_run": ["dinner"],
    }


def test_a_failing_first_meal_runs_nothing_else_and_shows_no_totals(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    propose(monkeypatch, capsys, home, THREE_MEALS)
    bot._session(monkeypatch, capsys, bot.FakeProvider(), bot.text(2, "/log breakfast 사과 1 count"))
    before = meal_tables(home)
    replies, _err, _fake = bot._session(monkeypatch, capsys, bot.FakeProvider(), bot.text(3, "/ok_7f3a"))
    assert replies[0].startswith("실패: 아침 - 오류:") and "실행하지 않음: 점심, 저녁" in replies[0]
    assert "오늘 누적" not in replies[0] and meal_tables(home) == before
    result = bot._history(home)[-1]["result"]
    assert (result["meal_id"], result["meal_ids"], result["failed"], result["not_run"]) == (
        None,
        [],
        "breakfast",
        ["lunch", "dinner"],
    )


def test_pending_migration_refuses_a_multi_meal_ok_without_consuming_it(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    propose(monkeypatch, capsys, home, THREE_MEALS)
    latest = code_migration_versions()[-1]
    v1._drop_migration_marker(v1._database(home), latest)
    before = meal_tables(home)
    replies, _err, _fake = bot._session(monkeypatch, capsys, bot.FakeProvider(), bot.text(2, "/ok_7f3a"))
    assert replies == [pending_migration_text((latest,))] and meal_tables(home) == before
    assert state_proposals(home)[0]["state"] == "open"


def test_an_unexpected_exception_stops_the_sequence(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    propose(monkeypatch, capsys, home, THREE_MEALS)
    original = cli._nutrition
    calls: list[int] = []

    def flaky(args: Any) -> int:
        if args.nutrition_command == "log":
            calls.append(1)
            if len(calls) == 2:
                raise RuntimeError("boom")
        return original(args)

    monkeypatch.setattr(cli, "_nutrition", flaky)
    replies, err, _fake = bot._session(monkeypatch, capsys, bot.FakeProvider(), bot.text(2, "/ok_7f3a"))
    (reply,) = replies
    assert "Recorded meal 2026-10-06-breakfast-1." in reply
    assert "실패: 점심 - " in reply and "RuntimeError" in reply and "실행하지 않음: 저녁" in reply
    assert len(calls) == 2 and "chat 111: /ok 2/3 failed with RuntimeError" in err
    assert sorted(row[0] for row in bot._tables(home)["nutrition_meals"]) == ["2026-10-06-breakfast-1"]


def test_ctrl_c_in_the_sequence_stops_the_bot_and_the_rest_never_runs(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    propose(monkeypatch, capsys, home, THREE_MEALS)
    original = cli._nutrition
    calls: list[int] = []

    def interrupted(args: Any) -> int:
        if args.nutrition_command == "log":
            calls.append(1)
            if len(calls) == 2:
                raise KeyboardInterrupt
        return original(args)

    monkeypatch.setattr(cli, "_nutrition", interrupted)
    fake = bot.FakeApi([bot.text(2, "/ok_7f3a"), bot.text(3, "/help")])
    bot._install(monkeypatch, bot.FakeProvider())
    v1._install(monkeypatch, fake)
    assert cli.main(["telegram", "run"]) == 130
    err = capsys.readouterr().err
    assert fake.sent == [] and len(calls) == 2
    assert "chat 111: /ok interrupted by Ctrl+C; it will not be run again" in err.split("\n")
    assert v1._state(home)["handled_update_ids"] == [1, 2]
    assert sorted(row[0] for row in bot._tables(home)["nutrition_meals"]) == ["2026-10-06-breakfast-1"]


# --- grouping ------------------------------------------------------------------------------------------------------


def test_a_single_meal_message_keeps_the_v2_proposal_and_argv(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    # the meal named on the items, or only at the top level: the same proposal as v2 (RunConfirmed, argv_ok)
    typed = dishes(
        catalog_item("닭가슴살", "lunch", 1, "pack"), catalog_item("햇반", "lunch", 1, "pack", quantity_estimated=True)
    )
    replies, _provider = propose(monkeypatch, capsys, home, typed)
    assert replies == [bot.LUNCH_PROPOSAL]
    proposal = state_proposals(home)[0]
    assert tuple(proposal["argv_ok"]) == bot.LUNCH_ARGV and proposal["meals"] == []
    assert proposal["meal_type"] == "lunch"


def test_the_same_meal_named_twice_is_one_meal(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    document = dishes(
        item("과자", "snack"), item("국밥", "dinner"), item("커피", "snack"), catalog_item("사과", "dinner", 1, "count")
    )
    replies, _provider = propose(monkeypatch, capsys, home, document)
    assert replies[0].splitlines()[0] == "이렇게 기록할까요? (10-06, 2끼)"
    proposal = state_proposals(home)[0]
    assert [meal["meal_type"] for meal in proposal["meals"]] == ["dinner", "snack"]
    snack = proposal["meals"][1]["argv_ok"]
    assert snack.count("--general") == 2 and "--general-note=과자" in snack and "--general-note=커피" in snack


def test_a_message_without_a_meal_word_is_one_meal_by_the_time_of_day(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    document = dishes(item("국밥", None), item("김치", None))
    replies, _provider = propose(monkeypatch, capsys, home, document)
    assert replies[0].splitlines()[:2] == ["이렇게 기록할까요? (점심, 10-06)", "(끼니: 지금 시각 기준)"]
    assert state_proposals(home)[0]["meals"] == []


def test_a_meal_word_item_is_left_out_and_the_rest_is_kept(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    document = dishes(item("점심", "lunch"), item("국밥", "lunch"), item("저녁식사", "dinner"))
    bot._catalog(capsys)
    bot._llm_config(home)
    replies, err, _fake = bot._session(monkeypatch, capsys, bot.FakeProvider(document), bot.text(1, MESSAGE))
    assert replies[0].splitlines()[:3] == [
        "이렇게 기록할까요? (점심, 10-06)",
        "1. 일반식 (메모: 국밥)",
        "   추정: kcal 300~400, 단백질 10~20 g (estimated)",
    ]
    assert "chat 111: 2 meal-word items left out" in err


def test_each_meal_decides_its_own_additional_flag(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    bot._catalog(capsys)
    bot._llm_config(home)
    bot._session(monkeypatch, capsys, bot.FakeProvider(), bot.text(1, "/log lunch 닭가슴살 100 g"))
    replies, _provider = propose(monkeypatch, capsys, home, THREE_MEALS, prepared=True, update_id=2)
    assert "점심\n  이미 기록된 점심(2026-10-06-lunch-1)이 있어 하나 더 기록합니다." in replies[0]
    meals = {meal["meal_type"]: meal["argv_ok"] for meal in state_proposals(home)[0]["meals"]}
    assert meals["lunch"][-1] == "--additional" and "--additional" not in meals["breakfast"]
    bot._session(monkeypatch, capsys, bot.FakeProvider(), bot.text(3, "/ok_7f3a"))
    assert "2026-10-06-lunch-2" in {row[0] for row in bot._tables(home)["nutrition_meals"]}


# --- linking (AC3) -------------------------------------------------------------------------------------------------


def single(*items: dict[str, Any]) -> dict[str, Any]:
    return dishes(*items)


def reply_of(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path, *items: dict[str, Any]
) -> list[str]:
    replies, _provider = propose(monkeypatch, capsys, home, single(*items))
    return replies[0].splitlines()


def test_an_llm_id_links_when_the_words_match_nothing_and_shows_the_catalog_name(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    lines = reply_of(monkeypatch, capsys, home, catalog_item("즉석밥", "lunch", 1, "pack", food_id="hetbahn-210"))
    assert lines[1] == '1. 햇반 (hetbahn-210) 1 pack ← "즉석밥"'
    argv = state_proposals(home)[0]["argv_ok"]
    assert argv[6:] == ["--item", "hetbahn-210", "1", "pack"]


@pytest.mark.parametrize(
    ("food_id", "reason"),
    [
        (None, "카탈로그에 없음"),
        ("no-such-food", "고른 음식 ID가 카탈로그에 없음"),
        ("general-meal", "고른 음식 ID가 카탈로그에 없음"),
        ("일반식", "고른 음식 ID가 카탈로그에 없음"),
    ],
)
def test_an_unknown_or_reserved_llm_id_becomes_a_general_estimate_with_a_reason(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    home: Path,
    food_id: str | None,
    reason: str,
) -> None:
    lines = reply_of(monkeypatch, capsys, home, catalog_item("즉석밥", "lunch", 1, "pack", food_id=food_id))
    assert lines[1] == f"1. 일반식 (메모: 즉석밥 1 pack) - {reason}"
    assert lines[2] == "   추정: kcal 300~400, 단백질 10~20 g (estimated)"


def test_exact_lookup_of_the_users_words_wins_over_the_llm_id(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    lines = reply_of(monkeypatch, capsys, home, catalog_item("햇반", "lunch", 1, "pack", food_id="banana"))
    assert lines[1] == "1. 햇반 (hetbahn-210) 1 pack"  # linked by the user's own word: no arrow
    assert state_proposals(home)[0]["argv_ok"][6:] == ["--item", "hetbahn-210", "1", "pack"]


def test_an_ambiguous_exact_match_is_never_overridden_by_the_llm_id(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    lines = reply_of(monkeypatch, capsys, home, catalog_item("apple", "lunch", 1, "count", food_id="banana"))
    assert lines[1] == "1. 일반식 (메모: apple 1 count) - 이름이 여러 음식에 맞음"


def test_an_llm_id_without_an_amount_or_with_an_unregistered_unit_is_a_general_estimate(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    lines = reply_of(
        monkeypatch,
        capsys,
        home,
        catalog_item("즉석밥", "lunch", None, None, food_id="hetbahn-210"),
        catalog_item("즉석밥", "lunch", 200, "g", food_id="hetbahn-210"),
    )
    assert lines[1] == "1. 일반식 (메모: 즉석밥) - 수량·단위를 말하지 않음"
    assert lines[3] == "2. 일반식 (메모: 즉석밥 200 g) - 이 음식은 pack 기준 값만 있습니다(단위 변환 없음)"
    assert lines[5] == "   등록: muscle50 nutrition food fact add hetbahn-210 --per 1 g ... --new-unit"


def test_the_catalog_estimate_is_only_a_fallback_and_is_not_stored_for_a_linked_item(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    propose(monkeypatch, capsys, home, single(catalog_item("닭가슴살", "lunch", 1, "pack")))
    bot._session(monkeypatch, capsys, bot.FakeProvider(), bot.text(2, "/ok_7f3a"))
    meal = json.loads(bot._ok(capsys, "nutrition", "meal", "show", "2026-10-06-lunch-1", "--json"))
    assert meal["items"][0]["nutrients"]["calories_kcal"]["value"] == "165"
    assert meal["items"][0]["nutrients"]["calories_kcal"]["source_type"] == "nutrition_label"


# --- the catalog list in the prompt ---------------------------------------------------------------------------------


def test_the_interpret_prompt_carries_the_catalog_list_and_no_general_meal(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    _replies, provider = propose(monkeypatch, capsys, home, single(item("국밥", "lunch")))
    prompt = provider.requests[0][0].prompt
    assert "[데이터]\n<카탈로그>\n형식: ID | 이름 | 별칭 | 등록 단위\n" in prompt
    assert "chicken-breast | 닭가슴살 | - | g, pack" in prompt
    assert "hetbahn-210 | 햇반 | - | pack" in prompt
    assert "banana | 바나나 | apple | count" in prompt
    assert "general-meal" not in prompt and "일반식" not in prompt.split("<카탈로그>")[1].split("[메시지]")[0]
    assert prompt.index("[데이터]") < prompt.index("[메시지]")


def test_an_empty_catalog_sends_no_data_section(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    bot._llm_config(home)
    provider = bot.FakeProvider(single(item("국밥", "lunch")))
    bot._session(monkeypatch, capsys, provider, bot.text(1, MESSAGE))
    assert "\n\n[데이터]\n" not in provider.requests[0][0].prompt


def test_a_catalog_read_error_still_runs_the_call_without_the_list(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    bot._catalog(capsys)
    bot._llm_config(home)

    def broken(self: SqliteFoodCatalogReader) -> Any:
        raise RuntimeError("cannot read")

    monkeypatch.setattr(SqliteFoodCatalogReader, "list_all", broken)
    provider = bot.FakeProvider(single(catalog_item("햇반", "lunch", 1, "pack")))
    replies, err, _fake = bot._session(monkeypatch, capsys, provider, bot.text(1, MESSAGE))
    assert "\n\n[데이터]\n" not in provider.requests[0][0].prompt
    assert "chat 111: catalog list not read (RuntimeError)" in err
    assert "1. 햇반 (hetbahn-210) 1 pack" in replies[0]  # exact lookup still works


def test_a_cut_catalog_list_is_logged_with_counts_only(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    bot._catalog(capsys)
    bot._llm_config(home)
    connection = sqlite3.connect(v1._database(home))
    with connection:
        for number in range(130):
            connection.execute(
                "INSERT INTO nutrition_food_profiles (profile_id, name) VALUES (?, ?)",
                (f"x{number:03d}", f"음식{number}"),
            )
    connection.close()
    # profiles with no fact have no registered unit and are not listed: the catalog is not cut
    provider = bot.FakeProvider(single(item("국밥", "lunch")))
    _replies, err, _fake = bot._session(monkeypatch, capsys, provider, bot.text(1, MESSAGE))
    assert "catalog list cut" not in err and "x000" not in provider.requests[0][0].prompt


# --- state file ----------------------------------------------------------------------------------------------------


def test_a_v21_state_file_without_meals_still_loads_and_a_multi_proposal_round_trips(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    propose(monkeypatch, capsys, home, THREE_MEALS)
    path = home / "config" / STATE
    document = json.loads(path.read_text(encoding="utf-8"))
    store = JsonLlmStateStore(path)
    state = store.load()
    assert len(state.proposals[0].meals) == 3 and state.proposals[0].plain_available
    for proposal in document["proposals"]:
        del proposal["meals"]
    path.write_text(json.dumps(document), encoding="utf-8", newline="\n")
    old = store.load()
    assert old.proposals[0].meals == () and not old.proposals[0].plain_available
    store.save(LlmState(None, (Proposal("1a2b", 1, ProposalKind.MEAL, 1, 2, ProposalState.OPEN),)))
    assert json.loads(path.read_text(encoding="utf-8"))["proposals"][0]["meals"] == []


def test_reply_against_the_stored_argv_uses_the_proposals_day(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    document = dishes(item("국밥", "lunch"), item("김치찌개", "dinner"), date_expression="yesterday")
    replies, _provider = propose(monkeypatch, capsys, home, document)
    assert replies[0].startswith("이렇게 기록할까요? (10-05, 2끼)")
    bot._session(monkeypatch, capsys, bot.FakeProvider(), bot.text(2, "/ok_7f3a"))
    assert {row[0] for row in bot._tables(home)["nutrition_meals"]} == {"2026-10-05-lunch-1", "2026-10-05-dinner-1"}
