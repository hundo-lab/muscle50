"""Telegram LLM v2.2 web search and photos end to end (AC5, AC7, AC11): which LLM calls offer the search tool and
the catalog list, photo proposals that link catalog foods next to visual estimates, the history record and its
renderers. Fake Bot API and fake LLM provider; the real CLIs are never run. Synthetic values only."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
import test_telegram_bot as v1
import test_telegram_llm_bot as bot
from test_telegram_llm_domain import NULL_ESTIMATE, interpretation
from test_telegram_llm_recheck_bot import SearchingProvider

from muscle50.domain.telegram_llm import history_entry
from muscle50.domain.telegram_llm_prompt import FIXED_RULES, fixed_rules_web
from muscle50.infrastructure.telegram.history_log import JsonlHistoryLog
from muscle50.presentation.telegram_llm_replies import history_text, render_telegram_history

home = bot.home  # the autouse fixture of the bot tests: temporary MUSCLE50_HOME, fake clock, no network
GOOD = {**NULL_ESTIMATE, "kcal_min": 650, "kcal_max": 950, "protein_min": 25, "protein_max": 40}
LUNCH = interpretation(
    items=[bot._item("국밥", None, None, kind="general", memo="국밥", estimate=GOOD)], meal_type="lunch"
)


def prompt_of(provider: bot.FakeProvider, index: int = 0) -> str:
    return provider.requests[index][0].prompt


# --- which calls offer the tool and carry the catalog ------------------------------------------------------


def test_the_default_config_offers_the_tool_to_a_text_interpret_call(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    bot._catalog(capsys)
    bot._llm_config(home)
    provider = bot.FakeProvider(LUNCH)
    bot._session(monkeypatch, capsys, provider, bot.text(1, "점심 국밥"))
    request = provider.requests[0][0]
    assert request.web_search is True and request.pin is None
    assert fixed_rules_web(3) in request.prompt and FIXED_RULES not in request.prompt
    assert "11. 웹 검색은 한 메시지에 최대 3번만 합니다." in request.prompt
    assert "<카탈로그>\n형식: ID | 이름 | 별칭 | 등록 단위\n" in request.prompt


def test_web_search_off_uses_the_search_free_fixed_rules_and_keeps_the_catalog_list(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    bot._catalog(capsys)
    bot._llm_config(home, {"web_search": False})
    provider = bot.FakeProvider(LUNCH)
    bot._session(monkeypatch, capsys, provider, bot.text(1, "점심 국밥"))
    request = provider.requests[0][0]
    assert request.web_search is False
    assert FIXED_RULES in request.prompt and "WebSearch" not in request.prompt
    assert "<카탈로그>" in request.prompt  # the catalog list is sent whether or not search is on


def test_the_search_limit_in_the_prompt_comes_from_the_config(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    bot._llm_config(home, {"web_search_max": 5})
    provider = bot.FakeProvider(LUNCH)
    bot._session(monkeypatch, capsys, provider, bot.text(1, "점심 국밥"))
    assert fixed_rules_web(5) in prompt_of(provider) and "최대 5번" in prompt_of(provider)


@pytest.mark.parametrize(
    ("config", "messages", "expected"),
    [
        ({"provider": "codex"}, ["점심 국밥"], False),
        ({"provider": "codex", "fallback_provider": "claude"}, ["점심 국밥"], True),
        ({}, ["/llm codex", "점심 국밥"], False),  # the chat override counts, not the file
        ({"provider": "codex"}, ["/llm claude", "점심 국밥"], True),
        ({"fallback_provider": "codex"}, ["점심 국밥"], True),
    ],
)
def test_the_tool_is_offered_only_when_claude_can_answer(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    home: Path,
    config: dict[str, Any],
    messages: list[str],
    expected: bool,
) -> None:
    bot._llm_config(home, config)
    provider = bot.FakeProvider(LUNCH)
    bot._session(monkeypatch, capsys, provider, *(bot.text(n, m) for n, m in enumerate(messages, start=1)))
    request = provider.requests[0][0]
    assert request.web_search is expected
    assert ("WebSearch" in request.prompt) is expected


def test_answer_and_suggest_calls_never_offer_the_tool_or_the_catalog(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    v1._seed_reads(capsys, home)
    bot._llm_config(home)
    suggest = interpretation(intent="menu_suggest", items=[], meal_type="lunch", tense="none")
    answer = {"answer": "오늘 계획은 /today에 있어요.", "memory_summary": ""}
    suggestions = {
        "lead": "",
        "suggestions": [
            {
                "name": "포케",
                "category": "delivery",
                "description": "",
                "estimate": {**NULL_ESTIMATE, "kcal_min": 500, "kcal_max": 700, "protein_min": 30, "protein_max": 40},
                "note": "",
            }
        ],
        "memory_summary": "",
    }
    provider = bot.FakeProvider(bot._question("training"), answer, suggest, suggestions)
    bot._session(monkeypatch, capsys, provider, bot.text(1, "오늘 뭐 운동해?"), bot.text(2, "점심 뭐 먹지?"))
    assert [request.schema.value for request, _chosen in provider.requests] == [
        "interpret",
        "answer",
        "interpret",
        "suggest",
    ]
    assert [request.web_search for request, _chosen in provider.requests] == [True, False, True, False]
    for index in (1, 3):
        assert "WebSearch" not in prompt_of(provider, index) and "<카탈로그>" not in prompt_of(provider, index)


# --- photos (AC11) --------------------------------------------------------------------------------------------------


def photo_meal(*items: dict[str, Any], **fields: Any) -> dict[str, Any]:
    return interpretation(items=list(items), meal_type="dinner", photo_kind="meal_photo", **fields)


def test_a_photo_call_carries_the_catalog_and_offers_the_tool_on_the_photo_model(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    bot._catalog(capsys)
    bot._llm_config(home)
    provider = bot.FakeProvider(photo_meal(bot._item("제육", None, None, kind="general", memo="제육", estimate=GOOD)))
    bot._session(monkeypatch, capsys, provider, bot.photo(1, "저녁"))
    request = provider.requests[0][0]
    assert request.photo == bot.PHOTO and request.web_search is True
    assert "<카탈로그>\n형식: ID | 이름 | 별칭 | 등록 단위\n" in request.prompt
    assert "chicken-breast | 닭가슴살 | - | g, pack" in request.prompt
    assert "12. 상표, 식당, 제품 이름의 음식이나 사진에서 읽을 수 있는 제품명" in request.prompt


def test_a_photo_with_search_off_has_no_tool_but_keeps_the_catalog(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    bot._catalog(capsys)
    bot._llm_config(home, {"web_search": False})
    provider = bot.FakeProvider(photo_meal(bot._item("제육", None, None, kind="general", memo="제육", estimate=GOOD)))
    bot._session(monkeypatch, capsys, provider, bot.photo(1, "저녁"))
    request = provider.requests[0][0]
    assert request.web_search is False and "WebSearch" not in request.prompt and "<카탈로그>" in request.prompt


def test_a_photo_proposal_links_a_catalog_food_next_to_a_visual_estimate(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    bot._catalog(capsys)
    bot._llm_config(home)
    document = photo_meal(
        bot._item("즉석밥", 1, "pack", food_id="hetbahn-210", quantity_estimated=True),
        bot._item(
            "제육볶음",
            None,
            None,
            kind="general",
            memo="제육볶음",
            estimate=GOOD,
            assumption="식당 이름이 보이지 않아 일반 제육으로 추정",
            source="namu.wiki",
        ),
    )
    provider = SearchingProvider([1], document)
    replies, _err, _fake = bot._session(monkeypatch, capsys, provider, bot.photo(1, "저녁"))
    assert replies == [
        "\n".join(
            [
                "이렇게 기록할까요? (저녁, 10-06, 사진 추정)",
                '1. 햇반 (hetbahn-210) 1 pack ← "즉석밥" (수량 추정)',
                "2. 일반식 (메모: 제육볶음)",
                "   추정: kcal 650~950, 단백질 25~40 g (estimated)",
                "   가정: 식당 이름이 보이지 않아 일반 제육으로 추정",
                "   출처: namu.wiki",
                "웹 검색 1회",
                "기록: /ok_7f3a   일반식만 기록(값 없이): /plain_7f3a   취소: /no_7f3a",
            ]
        )
    ]
    (proposal,) = json.loads((home / "config" / "telegram_llm_state.json").read_text(encoding="utf-8"))["proposals"]
    argv = proposal["argv_ok"]
    assert argv[6:10] == ["--item", "hetbahn-210", "1", "pack"]
    assert argv[10:13] == [
        "--general",
        "--general-note=제육볶음",
        "--general-estimate=visual_estimate:kcal=650-950,protein=25-40",
    ]
    digest = hashlib.sha256(bot.PHOTO).hexdigest()[:12]
    note = "출처: namu.wiki; 가정: 식당 이름이 보이지 않아 일반 제육으로 추정"
    expected = f"telegram-llm photo sha256:{digest} (claude sonnet); {note[:44]}"  # about 45 characters are left
    reference = argv[13]
    assert reference == f"--general-estimate-ref={expected}" and len(expected) <= 100
    bot._session(monkeypatch, capsys, bot.FakeProvider(), bot.text(2, "/ok_7f3a"))
    meal = json.loads(bot._ok(capsys, "nutrition", "meal", "show", "2026-10-06-dinner-1", "--json"))
    rice, pork = meal["items"]
    assert rice["nutrients"]["calories_kcal"]["value"] == "315"  # the catalog fact
    assert pork["nutrients"]["calories_kcal"]["source_type"] == "visual_estimate"
    stored = pork["facts"][0]["source_reference"]
    assert stored == expected
    assert "://" not in stored


def test_a_photo_with_several_meals_keeps_the_photo_label(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    bot._catalog(capsys)
    bot._llm_config(home)
    dish = bot._item("제육", None, None, kind="general", memo="제육", estimate=GOOD)
    document = interpretation(
        items=[{**dish, "meal_type": "lunch"}, {**dish, "meal_type": "dinner"}],
        meal_type=None,
        photo_kind="meal_photo",
    )
    replies, _err, _fake = bot._session(monkeypatch, capsys, bot.FakeProvider(document), bot.photo(1, "점심 저녁"))
    assert replies[0].splitlines()[0] == "이렇게 기록할까요? (10-06, 2끼, 사진 추정)"
    assert replies[0].splitlines()[1] == "점심" and "저녁" in replies[0].splitlines()


def test_a_menu_capture_may_search_and_its_reply_is_unchanged(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    bot._llm_config(home)
    provider = SearchingProvider([2], bot.MENU)
    replies, _err, _fake = bot._session(monkeypatch, capsys, provider, bot.photo(1, "점심 메뉴"))
    assert provider.requests[0][0].web_search is True and len(provider.requests) == 1
    assert replies[0].startswith("오늘 점심 메뉴예요.") and "웹 검색" not in replies[0]
    assert bot._history(home)[0]["web_searches"] == 2


# --- history (AC7) ---------------------------------------------------------------------------------------------------


def test_the_history_line_has_the_search_count_and_no_query_or_page(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    bot._catalog(capsys)
    bot._llm_config(home)
    provider = SearchingProvider([2, None], LUNCH)
    bot._session(monkeypatch, capsys, provider, bot.text(1, "점심 국밥"))
    bot._session(monkeypatch, capsys, bot.FakeProvider(), bot.text(2, "/ok_7f3a"))
    meal_entry, confirm = bot._history(home)
    assert meal_entry["web_searches"] == 2 and meal_entry["recheck"] is None
    assert confirm["web_searches"] is None and confirm["recheck"] is None
    assert len(meal_entry) == 22  # v2.5 adds failure_reason and retry_of


def test_without_a_search_attempt_the_count_is_null(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    bot._llm_config(home)
    bot._session(monkeypatch, capsys, bot.FakeProvider(LUNCH), bot.text(1, "점심 국밥"))
    assert bot._history(home)[0]["web_searches"] is None


def entry_with(**fields: Any) -> dict[str, Any]:
    base: dict[str, Any] = {"update_id": 9, "at": "2026-10-13T12:40:11+09:00", "chat_id": 111, "kind": "text"}
    return history_entry(**{**base, **fields})


def test_renderers_append_the_search_and_recheck_tails_only_when_present() -> None:
    plain = entry_with(intent="meal_log", provider="claude", model="haiku", provider_result="ok", text="국밥")
    searched = {**plain, "web_searches": 2}
    fixed = {**searched, "recheck": {"reasons": ["macros_vs_kcal"], "outcome": "fixed"}}
    zero = {**plain, "web_searches": 0}
    assert render_telegram_history([plain]) == render_telegram_history([{**plain, "web_searches": None}])
    assert "web=" not in render_telegram_history([plain]) and "recheck=" not in render_telegram_history([plain])
    assert render_telegram_history([searched]).splitlines()[0].endswith("ok web=2")
    assert render_telegram_history([zero]).splitlines()[0].endswith("ok web=0")
    assert render_telegram_history([fixed]).splitlines()[0].endswith("ok web=2 recheck=fixed")
    assert history_text([plain]) == history_text([zero])
    assert " · 웹 검색 2회" in history_text([searched]) and "재확인" not in history_text([searched])
    head = history_text([fixed]).splitlines()[0]
    assert head.endswith("claude haiku · 웹 검색 2회 · 재확인(고침)")
    for outcome, label in (("still_inconsistent", "남음"), ("reask_failed", "실패")):
        shown = {**plain, "recheck": {"reasons": [], "outcome": outcome}}
        assert history_text([shown]).splitlines()[0].endswith(f"재확인({label})")
        assert render_telegram_history([shown]).splitlines()[0].endswith(f"recheck={outcome}")


def test_the_renderers_print_the_recorded_meals_of_a_multi_meal_confirm() -> None:
    ok = entry_with(
        kind="confirm",
        text="/ok_7f3a",
        proposal="7f3a",
        reply="Recorded",
        result={"exit_code": 0, "meal_id": "a-1", "meal_ids": ["a-1", "b-1"], "failed": None, "not_run": []},
    )
    partial = entry_with(
        kind="confirm",
        text="/ok_7f3a",
        proposal="7f3a",
        reply="x",
        result={"exit_code": 1, "meal_id": "a-1", "meal_ids": ["a-1"], "failed": "lunch", "not_run": ["dinner"]},
    )
    none = entry_with(
        kind="confirm",
        text="/ok_7f3a",
        proposal="7f3a",
        reply="x",
        result={"exit_code": 1, "meal_id": None, "meal_ids": [], "failed": "breakfast", "not_run": ["lunch"]},
    )
    assert "결과: 기록 a-1, b-1" in history_text([ok]) and "exit=0 meals=a-1,b-1" in render_telegram_history([ok])
    assert "결과: 일부 기록 a-1 (실패: 점심)" in history_text([partial])
    assert "exit=1 meals=a-1" in render_telegram_history([partial])
    assert "결과: 실패 (exit 1)" in history_text([none]) and "exit=1" in render_telegram_history([none])
    assert "exit None" not in history_text([ok, partial, none])
    # the single-meal result shape renders as before
    single = entry_with(kind="confirm", text="/ok_7f3a", result={"exit_code": 0, "meal_id": "a-1"})
    assert "결과: 기록 a-1" in history_text([single]) and "exit=0 meal=a-1" in render_telegram_history([single])


def test_a_new_line_with_a_recheck_object_round_trips_through_the_history_log(tmp_path: Path) -> None:
    log = JsonlHistoryLog(tmp_path / "history")
    entry = entry_with(web_searches=3, recheck={"reasons": ["range_too_wide", "macros_vs_kcal"], "outcome": "fixed"})
    log.append(entry)
    (read,) = log.read(last=5)
    assert read == entry and len(read) == 22  # v2.5: 22 keys


def test_the_startup_line_names_the_web_search_setting(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    bot._llm_config(home)
    _replies, err, _fake = bot._session(monkeypatch, capsys, bot.FakeProvider(), bot.text(1, "/help"))
    assert "timeout 90 s, web search on (max 3, 150 s); claude (" in err
    bot._llm_config(home, {"web_search": False, "timeout_seconds": 60})
    _replies, err, _fake = bot._session(monkeypatch, capsys, bot.FakeProvider(), bot.text(2, "/help"))
    assert "timeout 60 s, web search off; claude (" in err
