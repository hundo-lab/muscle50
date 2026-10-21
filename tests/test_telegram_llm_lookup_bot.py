"""Telegram LLM v2.5 "search only on Claude": Codex reads first and never searches; an item that wants a lookup
(`lookup_wanted`) sends the message once more to Claude with web search. A fake Bot API and fake providers or fake
CLI runners only (never the real `claude`/`codex`), a temporary MUSCLE50_HOME and synthetic foods.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import test_telegram_bot as v1
import test_telegram_llm_bot as bot
import test_telegram_llm_failures_bot as failures
from test_llm_failure_reason import claude_error, codex_error
from test_telegram_llm_argv import CLAUDE_EXE, FakeRunner, claude_ok, codex_ok
from test_telegram_llm_domain import interpretation
from test_telegram_llm_meals_bot import item
from test_telegram_llm_recheck_bot import GOOD, WIDE, dish, doc

import muscle50.cli as cli
from muscle50.application.llm_provider import LlmAttempt, LlmCallResult, LlmRequest, SchemaName
from muscle50.domain.llm_failure import FailureReason
from muscle50.domain.llm_settings import LlmSettings, ProviderName
from muscle50.domain.telegram_llm import LlmOutputError, check_history_entry, parse_interpretation
from muscle50.infrastructure.llm.argv import claude_argv
from muscle50.infrastructure.llm.executables import ResolvedExecutable
from muscle50.infrastructure.llm.provider import TEMP_PREFIX, CliLlmProvider, load_schema
from muscle50.presentation.telegram_llm_replies import render_telegram_history

home = bot.home  # the autouse fixture of the bot tests: temporary MUSCLE50_HOME, fake clock, no network
CODEX = ProviderName.CODEX
CLAUDE = ProviderName.CLAUDE
BIG_MAC = "맥도날드 빅맥 세트"
CODEX_MEAL = bot.meal(item(BIG_MAC, None, lookup_wanted=True), memory_summary="codex")
CLAUDE_MEAL = bot.meal(item(BIG_MAC, None, lookup_wanted=True, source="맥도날드"), memory_summary="claude")
HOME_MEAL = bot.meal(item("밥 한공기 계란말이", None), memory_summary="codex")


class LookupProvider(bot.FakeProvider):
    """The next scripted answer per call: a document, or `(outcome, reason)` for a failure. Records searches when the
    tool was offered, and the model each provider would use."""

    def __init__(self, *responses: Any, searches: int = 2) -> None:
        super().__init__(*responses)
        self.searches = searches

    def call(self, request: LlmRequest, provider: ProviderName) -> LlmCallResult:
        self.requests.append((request, provider))
        response = self.responses.pop(0)
        model = request.pin.model if request.pin is not None else ("gpt-6.1-sol" if provider is CODEX else "haiku")
        searches = self.searches if request.web_search else None
        if isinstance(response, tuple):
            outcome, reason = response
            attempt = LlmAttempt(provider, model, outcome, 1.0, web_searches=searches, reason=reason)
            return LlmCallResult(provider, model, outcome, None, 1.0, False, (attempt,))
        attempt = LlmAttempt(provider, model, "ok", 1.0, web_searches=searches)
        return LlmCallResult(provider, model, "ok", request.validate(response), 1.0, False, (attempt,))


def _config(root: Path, document: dict[str, Any] | None = None) -> None:
    (root / "config" / "telegram_llm.json").write_text(json.dumps(document or {}), encoding="utf-8", newline="\n")


def _proposal(home: Path) -> dict[str, Any]:
    document = json.loads((home / "config" / "telegram_llm_state.json").read_text(encoding="utf-8"))
    proposal: dict[str, Any] = document["proposals"][-1]
    return proposal


def test_no_item_wants_a_lookup_so_codex_answers_alone(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    _config(home)
    provider = LookupProvider(HOME_MEAL)
    replies, err, _fake = bot._session(monkeypatch, capsys, provider, bot.text(1, "점심 밥 한공기 계란말이"))
    assert [(chosen, request.web_search) for request, chosen in provider.requests] == [(CODEX, False)]
    assert "웹 검색" not in replies[0] and "lookup" not in err
    assert bot._history(home)[0]["web_searches"] is None


def test_an_item_that_wants_a_lookup_is_read_again_by_claude_with_search(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    _config(home)
    provider = LookupProvider(CODEX_MEAL, CLAUDE_MEAL)
    replies, err, _fake = bot._session(monkeypatch, capsys, provider, bot.text(1, f"점심 {BIG_MAC} 먹었어"))
    (codex, first), (claude, second) = ((r, p) for r, p in provider.requests)
    assert (first, second) == (CODEX, CLAUDE)
    assert (codex.web_search, claude.web_search) == (False, True)
    assert claude.pin is not None and claude.pin.model == "haiku"  # Claude's text model, one run
    assert claude.prompt.replace("\n", " ") != codex.prompt.replace("\n", " ")  # the web fixed rules
    assert "WebSearch" in claude.prompt and "WebSearch" not in codex.prompt
    lines = replies[0].split("\n")
    assert "웹 검색 2회 (Claude)" in lines and "   출처: 맥도날드" in lines
    assert "telegram-llm text (claude haiku)" in json.dumps(_proposal(home)["argv_ok"], ensure_ascii=False)
    entry = bot._history(home)[0]
    assert (entry["provider"], entry["model"], entry["provider_result"], entry["web_searches"]) == (
        "claude",
        "haiku",
        "ok",
        2,
    )
    assert entry["attempts"] == [
        {"provider": "codex", "model": "gpt-6.1-sol", "outcome": "ok", "retry": False},
        {"provider": "claude", "model": "haiku", "outcome": "ok", "retry": False, "lookup": True},
    ]
    assert check_history_entry(entry) is entry
    assert "codex/gpt-6.1-sol ok -> lookup claude/haiku ok web=2" in render_telegram_history([entry])
    assert f"chat {bot.ALLOWED}: llm lookup on claude (haiku)" in err


def test_a_lookup_with_no_search_still_says_claude_answered(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    _config(home)
    provider = LookupProvider(CODEX_MEAL, CLAUDE_MEAL, searches=0)
    replies, _err, _fake = bot._session(monkeypatch, capsys, provider, bot.text(1, BIG_MAC))
    assert "웹 검색 0회 (Claude)" in replies[0].split("\n")


def test_a_failed_lookup_keeps_the_codex_answer_with_a_note(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    _config(home)
    provider = LookupProvider(CODEX_MEAL, ("failed", FailureReason.USAGE_LIMIT))
    replies, err, _fake = bot._session(monkeypatch, capsys, provider, bot.text(1, BIG_MAC))
    assert len(provider.requests) == 2  # no third call
    lines = replies[0].split("\n")
    assert lines[0] == "이렇게 기록할까요? (점심, 10-06)"
    assert lines[-2] == "(웹 검색은 하지 못했습니다: 사용 한도)"  # the last body line, above the commands
    assert not any(line.startswith("웹 검색 ") for line in lines)
    assert "telegram-llm text (codex gpt-6.1-sol)" in json.dumps(_proposal(home)["argv_ok"], ensure_ascii=False)
    entry = bot._history(home)[0]
    assert (entry["provider"], entry["provider_result"], entry["failure_reason"]) == ("codex", "ok", None)
    assert [attempt.get("lookup", False) for attempt in entry["attempts"]] == [False, True]
    assert "Claude 사용 한도라" not in replies[0]  # not the usage-limit fallback note
    assert "llm lookup failed (usage_limit); kept the codex answer" in err


def test_web_search_off_never_looks_up(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    _config(home, {"web_search": False})
    provider = LookupProvider(CODEX_MEAL)
    bot._session(monkeypatch, capsys, provider, bot.text(1, BIG_MAC))
    assert [chosen for _request, chosen in provider.requests] == [CODEX]


def test_without_claude_there_is_no_lookup(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    _config(home)

    def resolve(provider: ProviderName, configured: str | None) -> ResolvedExecutable:
        if provider is CLAUDE:
            return ResolvedExecutable(provider, None, "not_found")
        return ResolvedExecutable(provider, r"C:\Tools\codex.exe", None)

    monkeypatch.setattr(cli, "_resolve_llm_executable", resolve)
    provider = LookupProvider(CODEX_MEAL)
    bot._session(monkeypatch, capsys, provider, bot.text(1, BIG_MAC))
    assert [chosen for _request, chosen in provider.requests] == [CODEX]


def test_an_explicit_claude_provider_ignores_lookup_wanted(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    _config(home, {"provider": "claude"})
    provider = LookupProvider(CLAUDE_MEAL)
    replies, _err, _fake = bot._session(monkeypatch, capsys, provider, bot.text(1, BIG_MAC))
    assert [(chosen, request.web_search) for request, chosen in provider.requests] == [(CLAUDE, True)]
    assert "웹 검색 2회" in replies[0].split("\n")  # v2.4 line, no `(Claude)`


def test_a_question_never_looks_up(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    _config(home)
    question = interpretation(
        intent="question", items=[item(BIG_MAC, None, lookup_wanted=True)], question_topics=[], tense="none"
    )
    provider = LookupProvider(question)
    bot._session(monkeypatch, capsys, provider, bot.text(1, "빅맥 칼로리?"))
    assert [chosen for _request, chosen in provider.requests] == [CODEX]


def test_a_photo_lookup_sends_the_photo_again_on_claude_s_photo_model(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    _config(home, {"keep_photos": False})
    photo_codex = {**CODEX_MEAL, "photo_kind": "meal_photo"}
    photo_claude = {**CLAUDE_MEAL, "photo_kind": "meal_photo"}
    provider = LookupProvider(photo_codex, photo_claude)
    replies, _err, _fake = bot._session(monkeypatch, capsys, provider, bot.photo(1, "점심"))
    (_codex, _first), (claude, second) = provider.requests
    assert second is CLAUDE and claude.photo == bot.PHOTO and claude.pin is not None
    assert claude.pin.model == "sonnet"
    assert "웹 검색 2회 (Claude)" in replies[0].split("\n")


def test_llm_and_startup_lines_name_the_claude_lookup(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    _config(home)
    replies, err, _fake = bot._session(monkeypatch, capsys, LookupProvider(), bot.text(1, "/llm"))
    assert replies[0].split("\n")[0].endswith("시간 상한 90초 · 웹 검색: Claude(필요할 때만)")
    assert "usage-limit fallback on, timeout 90 s, web search via claude when needed (max 3, 150 s);" in err
    _config(home, {"web_search": False})
    replies, err, _fake = bot._session(monkeypatch, capsys, LookupProvider(), bot.text(2, "/llm"))
    assert replies[0].split("\n")[0].endswith("시간 상한 90초") and "web search off" in err
    _config(home, {"provider": "claude"})
    replies, err, _fake = bot._session(monkeypatch, capsys, LookupProvider(), bot.text(3, "/llm"))
    assert "웹 검색: Claude" not in replies[0] and "web search on (max 3, 150 s)" in err


def test_the_lookup_runs_the_pinned_claude_web_argv(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path, tmp_path: Path
) -> None:
    _config(home)
    runner = FakeRunner(codex_ok(CODEX_MEAL), claude_ok(CLAUDE_MEAL))
    counter = iter(range(10))

    def make_temp_dir() -> str:
        path = tmp_path / "llm-temp" / f"{TEMP_PREFIX}{next(counter)}"
        path.mkdir(parents=True)
        return str(path)

    def factory(settings: LlmSettings, executables: Any, log: Callable[[str], None]) -> CliLlmProvider:
        return CliLlmProvider(
            settings, executables, runner, log=log, environ={"PATH": "x"}, make_temp_dir=make_temp_dir
        )

    monkeypatch.setattr(cli, "_llm_provider", factory)
    fake = bot.FakeApi([bot.text(1, BIG_MAC)])
    v1._install(monkeypatch, fake)
    assert cli.main(["telegram", "run"]) == 130
    capsys.readouterr()
    codex_run, claude_run = runner.calls
    assert codex_run.argv[1] == "exec" and 'web_search="disabled"' in codex_run.argv
    assert claude_run.argv == claude_argv(CLAUDE_EXE, "haiku", load_schema(SchemaName.INTERPRET), web_search=True)
    assert claude_run.timeout_s == 150


def test_a_failed_codex_read_never_looks_up(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    _config(home, {"fallback_on_usage_limit": False})
    runner = FakeRunner(codex_error("ERROR: workspace routing discovery failed"))
    monkeypatch.setattr(
        cli,
        "_llm_provider",
        lambda settings, executables, log: CliLlmProvider(settings, executables, runner, log=log, environ={}),
    )
    fake = bot.FakeApi([bot.text(1, BIG_MAC)])
    v1._install(monkeypatch, fake)
    assert cli.main(["telegram", "run"]) == 130
    capsys.readouterr()
    assert len(runner.calls) == 1


def test_lookup_wanted_is_a_required_boolean_and_the_schema_lists_it() -> None:
    schema = load_schema(SchemaName.INTERPRET)
    item_schema = schema["properties"]["items"]["items"]
    assert "lookup_wanted" in item_schema["required"]
    assert item_schema["properties"]["lookup_wanted"]["type"] == "boolean"
    document = interpretation(items=[item(BIG_MAC, None, lookup_wanted=True)])
    assert parse_interpretation(document).items[0].lookup_wanted is True
    for broken in ("yes", 1, None):
        with pytest.raises(LlmOutputError, match="lookup_wanted must be a boolean"):
            parse_interpretation(interpretation(items=[item(BIG_MAC, None, lookup_wanted=broken)]))
    missing = interpretation(items=[item(BIG_MAC, None)])
    del missing["items"][0]["lookup_wanted"]
    with pytest.raises(LlmOutputError):
        parse_interpretation(missing)


def test_the_history_reads_back_a_lookup_attempt_only_when_its_flag_is_true(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    _config(home)
    bot._session(monkeypatch, capsys, LookupProvider(CODEX_MEAL, CLAUDE_MEAL), bot.text(1, BIG_MAC))
    entry = bot._history(home)[0]
    assert check_history_entry(entry) is entry
    for wrong in (False, 1, "true"):
        broken = json.loads(json.dumps(entry))
        broken["attempts"][1]["lookup"] = wrong
        with pytest.raises(ValueError, match="not a version 1 history entry"):
            check_history_entry(broken)


def test_the_recheck_after_a_lookup_asks_claude_again_with_the_web_rules(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    _config(home)
    wide = doc(dish(WIDE, lookup_wanted=True))
    provider = LookupProvider(wide, wide, doc(dish(GOOD, lookup_wanted=True)))
    bot._session(monkeypatch, capsys, provider, bot.text(1, "점심 국밥 먹었어"))
    assert [(chosen, request.web_search) for request, chosen in provider.requests] == [
        (CODEX, False),
        (CLAUDE, True),
        (CLAUDE, True),
    ]
    reask = provider.requests[2][0]
    assert reask.pin is not None and reask.pin.model == "sonnet"  # Claude's retry model
    assert bot._history(home)[0]["recheck"] == {"reasons": ["range_too_wide"], "outcome": "fixed"}


def test_a_codex_answer_after_a_claude_usage_limit_is_not_looked_up(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    _config(home, {"provider": "claude"})
    clock = failures._start()
    runner = FakeRunner(claude_error("Claude AI usage limit reached|1760000000"), codex_ok(CODEX_MEAL))
    replies, _err, _fake = failures._run(monkeypatch, capsys, runner, clock, [failures._text(1, BIG_MAC, clock)])
    assert len(runner.calls) == 2  # Claude (limited), then Codex; never Claude again
    lines = replies[0].split("\n")
    assert "(Claude 사용 한도라 이번에는 codex(OpenAI)로 처리했습니다.)" in lines
    assert not any(line.startswith("(웹 검색은") or line.startswith("웹 검색") for line in lines)
