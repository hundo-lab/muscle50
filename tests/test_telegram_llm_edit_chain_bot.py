"""Telegram LLM v2.5: corrections of an open meal proposal keep the earlier ones (the chain of edit requests) and run
on the stronger retry model. A fake Bot API and a fake LLM provider only, a temporary MUSCLE50_HOME and synthetic
foods. Covers AC5 of docs/specs/telegram-llm-failures-and-meals.md.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import test_telegram_llm_bot as bot
from test_telegram_llm_domain import interpretation
from test_telegram_llm_meals_bot import item, state_proposals

from muscle50.domain.telegram_llm import (
    EDIT_REQUEST_TEXT_MAX,
    EDIT_REQUESTS_MAX,
    Proposal,
    ProposalKind,
    ProposalState,
    edit_requests_after,
)
from muscle50.domain.telegram_llm_corrections import open_proposal_block
from muscle50.infrastructure.telegram.llm_state_store import JsonLlmStateStore

home = bot.home  # the autouse fixture of the bot tests: temporary MUSCLE50_HOME, fake clock, no network
FIRST_EDIT = "햇반 빼고 김치도 추가해줘"
SECOND_EDIT = "멕시코 타코도 반개"


def _corrected(*items: dict[str, object]) -> dict[str, object]:
    return bot.meal(*items, refers_to="open_proposal")


def test_a_second_correction_sees_the_first_and_runs_on_the_strong_model(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    bot._catalog(capsys)
    bot._llm_config(home)
    chicken = bot._item("닭가슴살", 1, "pack")
    provider = bot.FakeProvider(
        bot.LUNCH_MEAL,
        _corrected(chicken, item("김치", None)),
        _corrected(chicken, item("김치", None), item("타코 반개", None)),
    )
    replies, _err, _fake = bot._session(
        monkeypatch, capsys, provider, bot.text(1, "점심"), bot.text(2, FIRST_EDIT), bot.text(3, SECOND_EDIT)
    )
    assert [request.strong_model for request, _provider in provider.requests] == [False, True, True]
    first_edit_prompt = provider.requests[1][0].prompt
    assert "앞선 수정 요청(오래된 것부터)" not in first_edit_prompt  # the first correction has no earlier one
    second_edit_prompt = provider.requests[2][0].prompt
    assert f"앞선 수정 요청(오래된 것부터):\n- {FIRST_EDIT}\n" in second_edit_prompt
    assert "앞선 수정을 되돌리지 않습니다" in second_edit_prompt  # the interpret rule
    proposals = state_proposals(home)
    assert [proposal["state"] for proposal in proposals] == ["cancelled", "cancelled", "open"]
    assert [proposal["edit_requests"] for proposal in proposals] == [[], [FIRST_EDIT], [FIRST_EDIT, SECOND_EDIT]]
    assert "이전 제안(/ok_91c0)은 취소했습니다." in replies[2]


def test_a_photo_never_asks_for_the_strong_model(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    bot._catalog(capsys)
    bot._llm_config(home, {"keep_photos": False})
    photo_meal = interpretation(photo_kind="meal_photo", items=[item("김밥", "lunch")], meal_type=None)
    provider = bot.FakeProvider(bot.LUNCH_MEAL, photo_meal)
    bot._session(monkeypatch, capsys, provider, bot.text(1, "점심"), bot.photo(2, "저녁"))
    assert [request.strong_model for request, _provider in provider.requests] == [False, False]


def test_the_chain_is_clipped_and_capped() -> None:
    chain: tuple[str, ...] = ()
    for number in range(EDIT_REQUESTS_MAX + 2):
        chain = edit_requests_after(chain, f"고침 {number}\n  줄바꿈")
    assert len(chain) == EDIT_REQUESTS_MAX and chain[0] == "고침 2 줄바꿈" and chain[-1] == "고침 6 줄바꿈"
    assert edit_requests_after((), "가" * 200) == ("가" * EDIT_REQUEST_TEXT_MAX,)
    assert edit_requests_after(("a",), "   ") == ("a",)


def test_the_open_proposal_block_lists_the_chain() -> None:
    proposal = Proposal(
        "7f3a",
        111,
        ProposalKind.MEAL,
        0,
        1,
        ProposalState.OPEN,
        outline=("1. 일반식 (메모: 김치)",),
        edit_requests=("햇반 빼고", "타코 반개"),
    )
    assert open_proposal_block(proposal).split("\n")[-3:] == [
        "앞선 수정 요청(오래된 것부터):",
        "- 햇반 빼고",
        "- 타코 반개",
    ]


def test_a_state_file_from_v2_4_still_loads(tmp_path: Path) -> None:
    path = tmp_path / "telegram_llm_state.json"
    old = {
        "token": "7f3a",
        "chat_id": 111,
        "kind": "meal",
        "created_unix": 1,
        "expires_unix": 2,
        "state": "open",
        "argv_ok": ["nutrition", "log"],
        "argv_plain": [],
        "choices": [],
        "meal_type": "lunch",
        "day": "2026-10-06",
        "source": None,
        "reference": None,
        "meal_id": None,
        "label": "",
        "meals": [{"meal_type": "lunch", "argv_ok": ["nutrition", "log"], "argv_plain": []}],
        "outline": ["1. 일반식"],
        "fix_argv": [],
        "fix_change": "",
    }
    document = {"schema_version": 1, "provider_override": None, "proposals": [old]}
    path.write_text(json.dumps(document), encoding="utf-8", newline="\n")
    (proposal,) = JsonLlmStateStore(path).load().proposals
    assert (proposal.edit_requests, proposal.join_meal_id, proposal.argv_alt, proposal.alt_action) == ((), None, (), "")
    assert (proposal.retry_text, proposal.retry_file_ids, proposal.received_unix) == (None, (), 0)
    assert proposal.meals[0].join_meal_id is None and proposal.meals[0].argv_new == ()
