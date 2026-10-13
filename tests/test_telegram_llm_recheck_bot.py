"""Telegram LLM v2.2 numeric re-check end to end (AC12): one corrective re-ask, the `(값 확인 필요)` marker, the
history record and the console lines. Fake Bot API and fake LLM provider; temporary MUSCLE50_HOME; synthetic only."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
import test_telegram_llm_bot as bot
from test_telegram_llm_domain import NULL_ESTIMATE, interpretation

from muscle50.application.llm_provider import LlmAttempt, LlmCallResult, LlmRequest, RunPin
from muscle50.domain.llm_settings import ProviderName
from muscle50.domain.telegram_llm_check import RECHECK_INTRO

home = bot.home  # the autouse fixture of the bot tests: temporary MUSCLE50_HOME, fake clock, no network
MESSAGE = "점심 국밥 먹었어"
WIDE = {**NULL_ESTIMATE, "kcal_min": 100, "kcal_max": 900, "protein_min": 25, "protein_max": 40}
GOOD = {**NULL_ESTIMATE, "kcal_min": 650, "kcal_max": 950, "protein_min": 25, "protein_max": 40}
REASK_LINE = "llm interpret recheck: range_too_wide x1; asking again (sonnet)"


def dish(estimate: dict[str, Any], **fields: Any) -> dict[str, Any]:
    return bot._item("국밥", None, None, kind="general", memo="국밥", estimate=estimate, **fields)


def doc(*items: dict[str, Any], **fields: Any) -> dict[str, Any]:
    return interpretation(items=list(items), meal_type="lunch", **fields)


class SearchingProvider(bot.FakeProvider):
    """The bot tests' fake, with a scripted web search count on each call's attempt."""

    def __init__(self, searches: list[int | None], *responses: Any) -> None:
        super().__init__(*responses)
        self.searches = list(searches)

    def call(self, request: LlmRequest, provider: ProviderName) -> LlmCallResult:
        result = super().call(request, provider)
        count = self.searches.pop(0)
        return replace(result, attempts=tuple(replace(attempt, web_searches=count) for attempt in result.attempts))


def run(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    home: Path,
    provider: bot.FakeProvider,
    *messages: str,
    config: dict[str, Any] | None = None,
) -> tuple[list[str], str]:
    bot._catalog(capsys)
    bot._llm_config(home, config)
    replies, err, _fake = bot._session(
        monkeypatch, capsys, provider, *(bot.text(number, body) for number, body in enumerate(messages, start=1))
    )
    return replies, err


def recheck_of(home: Path) -> Any:
    return bot._history(home)[0]["recheck"]


# --- no failing check: nothing changes ------------------------------------------------------------------------------


def test_a_passing_estimate_makes_one_call_and_no_recheck_section(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    provider = bot.FakeProvider(doc(dish(GOOD)))
    replies, err = run(monkeypatch, capsys, home, provider, MESSAGE)
    assert len(provider.requests) == 1 and "[재확인]" not in provider.requests[0][0].prompt
    assert provider.requests[0][0].pin is None
    assert "(값 확인 필요)" not in replies[0] and "recheck" not in err
    entry = bot._history(home)[0]
    assert entry["recheck"] is None and "interpret_first" not in entry["llm_output"]


def test_linked_catalog_items_and_menu_captures_are_not_checked(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    # a catalog food's estimate is only a fallback: even an absurd one is ignored when the item is linked
    linked = bot._item("닭가슴살", 1, "pack", estimate=WIDE)
    provider = bot.FakeProvider(doc(linked))
    replies, _err = run(monkeypatch, capsys, home, provider, MESSAGE)
    assert len(provider.requests) == 1 and "1. 닭가슴살 (chicken-breast) 1 pack" in replies[0]
    menu = bot.MENU
    wide_menu = json.loads(json.dumps(menu))
    wide_menu["menu"]["items"][0]["estimate"] = WIDE
    provider = bot.FakeProvider(wide_menu)
    bot._session(monkeypatch, capsys, provider, bot.photo(2, "점심 메뉴"))
    assert len(provider.requests) == 1


# --- a fixed answer -------------------------------------------------------------------------------------------------


def test_one_reask_with_a_machine_note_fixes_the_answer(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    first, second = doc(dish(WIDE)), doc(dish(GOOD), memory_summary="고친 요약")
    provider = SearchingProvider([2, 1], first, second)
    replies, err = run(monkeypatch, capsys, home, provider, MESSAGE)
    assert len(provider.requests) == 2
    (request_1, _), (request_2, chosen) = provider.requests
    assert request_1.pin is None and request_2.pin == RunPin("sonnet") and chosen is ProviderName.CLAUDE
    note_section = request_2.prompt.split("[재확인]\n")[1].split("\n\n[메시지]")[0]
    assert note_section == f"{RECHECK_INTRO}\n- items[1]: range_too_wide (kcal 100-900)"
    prompt = request_2.prompt
    assert prompt.index("\n\n[데이터]\n") < prompt.index("\n\n[재확인]\n") < prompt.index("\n\n[메시지]\n")
    assert "[재확인]" not in request_1.prompt
    assert (
        request_2.prompt.replace(f"[재확인]\n{note_section}\n\n", "") == request_1.prompt
    )  # otherwise the same prompt
    assert "국밥" not in note_section and MESSAGE not in note_section
    assert replies == [
        "\n".join(
            [
                "이렇게 기록할까요? (점심, 10-06)",
                "1. 일반식 (메모: 국밥)",
                "   추정: kcal 650~950, 단백질 25~40 g (estimated)",
                "웹 검색 3회",
                "기록: /ok_7f3a   일반식만 기록(값 없이): /plain_7f3a   취소: /no_7f3a",
            ]
        )
    ]
    lines = err.split("\n")
    assert REASK_LINE in lines and "llm interpret recheck: fixed" in lines
    entry = bot._history(home)[0]
    assert entry["recheck"] == {"reasons": ["range_too_wide"], "outcome": "fixed"}
    assert entry["web_searches"] == 3  # both interpret calls
    assert entry["llm_output"]["interpret_first"]["items"][0]["estimate"]["kcal_min"] == 100
    assert entry["llm_output"]["interpret"]["items"][0]["estimate"]["kcal_min"] == 650
    assert (entry["provider"], entry["model"], entry["retried"], len(entry["attempts"])) == (
        "claude",
        "sonnet",
        False,
        1,
    )


def test_the_pin_is_the_answering_providers_retry_model_else_its_own_model(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    provider = bot.FakeProvider(doc(dish(WIDE)), doc(dish(GOOD)))
    run(monkeypatch, capsys, home, provider, MESSAGE, config={"claude": {"retry_model": "opus"}})
    assert provider.requests[1][0].pin == RunPin("opus")


def test_without_a_retry_model_the_answering_model_is_pinned(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    provider = bot.FakeProvider(doc(dish(WIDE)), doc(dish(GOOD)))
    _replies, err = run(monkeypatch, capsys, home, provider, MESSAGE, config={"claude": {"retry_model": None}})
    assert provider.requests[1][0].pin == RunPin("sonnet")  # the fake answers as sonnet
    assert "asking again (sonnet)" in err


def test_the_reask_goes_to_the_provider_that_answered(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    provider = bot.FakeProvider(doc(dish(WIDE)), doc(dish(GOOD)))
    run(monkeypatch, capsys, home, provider, "/llm codex", MESSAGE)
    assert [chosen for _request, chosen in provider.requests] == [ProviderName.CODEX, ProviderName.CODEX]
    assert provider.requests[1][0].pin == RunPin("sonnet")  # codex has no retry model: its own model


class RetriedProvider(bot.FakeProvider):
    """Answers like the real provider after a format failure: the first attempt was bad output, the retry was ok."""

    def call(self, request: LlmRequest, provider: ProviderName) -> LlmCallResult:
        result = super().call(request, provider)
        first = LlmAttempt(provider, "haiku", "bad_output", 1.0)
        return replace(result, attempts=(first, replace(result.attempts[0], retry=True)))


def test_a_format_failure_retry_is_not_a_recheck(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    provider = RetriedProvider(doc(dish(GOOD)))
    run(monkeypatch, capsys, home, provider, MESSAGE)
    entry = bot._history(home)[0]
    assert (entry["retried"], len(entry["attempts"]), entry["recheck"]) == (True, 2, None)
    assert len(provider.requests) == 1 and provider.requests[0][0].pin is None


# --- still inconsistent or a failed re-ask ----------------------------------------------------------------------------


def test_a_second_inconsistent_answer_is_shown_with_a_marker_and_never_asked_again(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    both = doc(dish(WIDE, assumption="국밥 한 그릇 기준"))
    provider = bot.FakeProvider(both, both)
    replies, err = run(monkeypatch, capsys, home, provider, MESSAGE)
    assert len(provider.requests) == 2  # exactly one re-ask, never a second
    assert replies[0].split("\n")[1:6] == [
        "1. 일반식 (메모: 국밥)",
        "   추정: kcal 100~900, 단백질 25~40 g (estimated) (값 확인 필요)",
        "   값 확인 필요: 범위가 너무 넓음",
        "   가정: 국밥 한 그릇 기준",
        "기록: /ok_7f3a   일반식만 기록(값 없이): /plain_7f3a   취소: /no_7f3a",
    ]
    assert "llm interpret recheck: still inconsistent; shown with a marker" in err.split("\n")
    assert recheck_of(home) == {"reasons": ["range_too_wide"], "outcome": "still_inconsistent"}
    # /ok stores the estimate with a trace; /plain stores no values
    bot._session(monkeypatch, capsys, bot.FakeProvider(), bot.text(2, "/ok_7f3a"))
    stored = json.loads(bot._ok(capsys, "nutrition", "meal", "show", "2026-10-06-lunch-1", "--json"))
    assert stored["items"][0]["facts"][0]["source_reference"] == (
        "telegram-llm text (claude sonnet); 값 확인 필요; 가정: 국밥 한 그릇 기준"
    )


def test_plain_after_a_marked_proposal_stores_no_values(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    both = doc(dish(WIDE))
    run(monkeypatch, capsys, home, bot.FakeProvider(both, both), MESSAGE)
    bot._session(monkeypatch, capsys, bot.FakeProvider(), bot.text(2, "/plain_7f3a"))
    stored = json.loads(bot._ok(capsys, "nutrition", "meal", "show", "2026-10-06-lunch-1", "--json"))
    assert stored["items"][0]["facts"] == [] and stored["items"][0]["note"] == "국밥"


@pytest.mark.parametrize(
    ("second", "detail"),
    [
        ("timeout", "timeout"),
        ("failed", "failed"),
        ("bad_output", "bad output"),
        (doc(dish(GOOD), intent="question"), "unusable answer"),
        (doc(dish(GOOD), tense="planned"), "unusable answer"),
        (doc(dish(GOOD), date_expression="other"), "unusable answer"),
        (doc(), "unusable answer"),
    ],
)
def test_a_failed_or_unusable_reask_keeps_the_first_answer_with_a_marker(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    home: Path,
    second: Any,
    detail: str,
) -> None:
    provider = bot.FakeProvider(doc(dish(WIDE)), second)
    replies, err = run(monkeypatch, capsys, home, provider, MESSAGE)
    assert len(provider.requests) == 2
    assert "   추정: kcal 100~900, 단백질 25~40 g (estimated) (값 확인 필요)" in replies[0]
    assert f"llm interpret recheck: re-ask failed ({detail}); shown with a marker" in err.split("\n")
    entry = bot._history(home)[0]
    assert entry["recheck"] == {"reasons": ["range_too_wide"], "outcome": "reask_failed"}
    assert entry["llm_output"]["interpret"]["items"][0]["estimate"]["kcal_min"] == 100
    assert "interpret_first" not in entry["llm_output"]


def test_a_still_inconsistent_answer_replaces_the_first_and_its_codes_are_marked(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    point = {**NULL_ESTIMATE, "kcal_min": 700, "kcal_max": 700, "protein_min": 25, "protein_max": 40}
    provider = bot.FakeProvider(doc(dish(WIDE)), doc(dish(point)))
    replies, _err = run(monkeypatch, capsys, home, provider, MESSAGE)
    assert "   추정: kcal 700, 단백질 25~40 g (estimated) (값 확인 필요)" in replies[0]
    assert "   값 확인 필요: 범위가 아니라 한 값임" in replies[0]
    entry = bot._history(home)[0]
    assert entry["recheck"] == {"reasons": ["range_too_wide"], "outcome": "still_inconsistent"}
    assert entry["llm_output"]["interpret_first"]["items"][0]["estimate"]["kcal_min"] == 100


def test_an_assumption_with_a_foreign_number_triggers_the_reask_and_every_marker_keeps_its_item(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    bad = dish(GOOD, assumption="한 그릇 약 777 kcal로 추정")
    fine = bot._item("김치", None, None, kind="general", memo="김치", estimate=GOOD)
    provider = bot.FakeProvider(doc(fine, bad), doc(fine, bad))
    replies, err = run(monkeypatch, capsys, home, provider, MESSAGE)
    lines = replies[0].split("\n")
    assert lines[1:3] == ["1. 일반식 (메모: 김치)", "   추정: kcal 650~950, 단백질 25~40 g (estimated)"]
    assert lines[3] == "2. 일반식 (메모: 국밥)"
    assert lines[4].endswith("(값 확인 필요)") and lines[5] == "   값 확인 필요: 가정에 쓴 숫자가 수량·추정값과 다름"
    assert lines[6] == "   가정: 한 그릇 약 777 kcal로 추정"  # shown as is
    assert "llm interpret recheck: assumption_number x1; asking again (sonnet)" in err.split("\n")
    note = provider.requests[1][0].prompt.split("[재확인]\n")[1].split("\n\n[메시지]")[0]
    assert note.endswith("- items[2]: assumption_number (1 numbers)")


def test_the_reask_counts_one_extra_run_and_a_second_message_starts_fresh(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    provider = bot.FakeProvider(doc(dish(WIDE)), doc(dish(GOOD)), doc(dish(GOOD)))
    replies, _err = run(monkeypatch, capsys, home, provider, MESSAGE, "국밥 또")
    assert len(replies) == 2 and len(provider.requests) == 3
    assert [bool(request.pin) for request, _chosen in provider.requests] == [False, True, False]


# --- photos ---------------------------------------------------------------------------------------------------------


def test_a_photo_meal_is_rechecked_with_the_photo_again(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    bot._catalog(capsys)
    bot._llm_config(home)
    first = doc(dish(WIDE), photo_kind="meal_photo")
    second = doc(dish(GOOD), photo_kind="meal_photo")
    provider = bot.FakeProvider(first, second)
    replies, _err, _fake = bot._session(monkeypatch, capsys, provider, bot.photo(1, "점심"))
    assert [request.photo for request, _chosen in provider.requests] == [bot.PHOTO, bot.PHOTO]
    assert provider.requests[1][0].pin == RunPin("sonnet")
    assert "추정: kcal 650~950" in replies[0] and "사진 추정" in replies[0]
    assert bot._history(home)[0]["recheck"]["outcome"] == "fixed"
