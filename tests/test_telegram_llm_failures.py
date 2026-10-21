"""Telegram LLM v2.5 provider rules: attempts carry their failure reason, a usage limit goes once to the other provider
(`fallback_on_usage_limit`), the config key, and `strong_model` for open-proposal edits. Fake runners only (never the
real `claude` or `codex`). Covers AC3 and part of AC1/AC5 of docs/specs/telegram-llm-failures-and-meals.md."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from test_llm_failure_reason import claude_error, codex_error
from test_telegram_llm_argv import FAILED, FakeRunner, _provider, _request, claude_ok, codex_ok

from muscle50.application.llm_provider import LlmRequest, RunPin, SchemaName
from muscle50.domain.llm_failure import FailureReason
from muscle50.domain.llm_settings import DEFAULT_SETTINGS, LlmSettings, ProviderName, ProviderSettings
from muscle50.infrastructure.telegram.llm_config_file import LlmConfigError, load_llm_settings

CLAUDE = ProviderName.CLAUDE
CODEX = ProviderName.CODEX
CLAUDE_LIMIT = claude_error("You've hit your limit · resets 5pm", exit_code=0)
CODEX_LIMIT = codex_error("ERROR: You've hit your usage limit. Try again at 3:05 PM.")
SECRET = "sk-synthetic-should-never-be-echoed"


def _settings(**overrides: Any) -> LlmSettings:
    return replace(DEFAULT_SETTINGS, **overrides)


def _model(argv: tuple[str, ...], flag: str) -> str | None:
    return argv[argv.index(flag) + 1] if flag in argv else None


def test_a_claude_usage_limit_goes_once_to_codex(tmp_path: Path) -> None:
    runner = FakeRunner(CLAUDE_LIMIT, codex_ok())
    provider, logs, _made = _provider(runner, tmp_path)
    result = provider.call(_request(), CLAUDE)
    assert (result.outcome, result.provider, result.used_fallback, result.retried) == ("ok", CODEX, True, False)
    assert [(item.provider, item.reason) for item in result.attempts] == [
        (CLAUDE, FailureReason.USAGE_LIMIT),
        (CODEX, None),
    ]
    assert result.usage_limited is CLAUDE
    assert logs[1] == "llm claude: bad output after 0 s (haiku); reason usage_limit; trying fallback codex"


def test_a_codex_usage_limit_goes_once_to_claude(tmp_path: Path) -> None:
    runner = FakeRunner(CODEX_LIMIT, claude_ok())
    provider, logs, _made = _provider(runner, tmp_path)
    result = provider.call(_request(), CODEX)
    assert (result.outcome, result.provider, result.usage_limited) == ("ok", CLAUDE, CODEX)
    assert logs[1] == "llm codex: failed (exit 1) after 0 s (gpt-6.1-sol); reason usage_limit; trying fallback claude"
    assert _model(runner.calls[1].argv, "--model") == "haiku"


def test_with_the_switch_off_a_usage_limit_does_not_go_on(tmp_path: Path) -> None:
    runner = FakeRunner(CODEX_LIMIT)
    provider, logs, _made = _provider(runner, tmp_path, settings=_settings(fallback_on_usage_limit=False))
    result = provider.call(_request(), CODEX)
    assert (result.outcome, result.failure_reason, result.other_tried) == ("failed", FailureReason.USAGE_LIMIT, False)
    assert len(runner.calls) == 1 and len(logs) == 1


def test_other_failures_do_not_go_on_without_a_fallback_provider(tmp_path: Path) -> None:
    runner = FakeRunner(FAILED)
    provider, _logs, _made = _provider(runner, tmp_path)
    result = provider.call(_request(), CODEX)
    assert (result.outcome, result.failure_reason, len(runner.calls)) == ("failed", FailureReason.OTHER, 1)


def test_the_usage_limit_fallback_never_adds_a_third_run_of_another_provider(tmp_path: Path) -> None:
    # The configured fallback provider is already the other one: the order is unchanged (at most 4 runs in all).
    runner = FakeRunner(CODEX_LIMIT, CLAUDE_LIMIT)
    provider, _logs, _made = _provider(runner, tmp_path, settings=_settings(fallback_provider=CLAUDE))
    result = provider.call(_request(), CODEX)
    assert [item.provider for item in result.attempts] == [CODEX, CLAUDE]
    assert (result.failure_reason, result.other_tried, result.usage_limited) == (FailureReason.USAGE_LIMIT, True, None)


def test_a_fallback_provider_usage_limit_does_not_bounce_back(tmp_path: Path) -> None:
    runner = FakeRunner(FAILED, CLAUDE_LIMIT)
    provider, _logs, _made = _provider(runner, tmp_path, settings=_settings(fallback_provider=CLAUDE))
    result = provider.call(_request(), CODEX)
    assert len(runner.calls) == 2 and result.provider is CLAUDE


def test_a_pinned_re_ask_never_falls_back(tmp_path: Path) -> None:
    runner = FakeRunner(CODEX_LIMIT)
    provider, _logs, _made = _provider(runner, tmp_path)
    request = replace(_request(), pin=RunPin("gpt-6.1-sol"))
    result = provider.call(request, CODEX)
    assert (result.outcome, result.used_fallback, len(runner.calls)) == ("failed", False, 1)
    assert result.failure_reason is FailureReason.USAGE_LIMIT


def test_strong_model_starts_on_the_retry_model_and_is_a_no_op_without_one(tmp_path: Path) -> None:
    runner = FakeRunner(claude_ok(), codex_ok())
    provider, _logs, _made = _provider(runner, tmp_path)
    strong = LlmRequest("p", SchemaName.ANSWER, None, lambda document: document, strong_model=True)
    assert provider.call(strong, CLAUDE).model == "sonnet"
    assert _model(runner.calls[0].argv, "--model") == "sonnet"
    assert provider.call(strong, CODEX).model == "gpt-6.1-sol"  # Codex has no retry model by default
    assert _model(runner.calls[1].argv, "-m") == "gpt-6.1-sol"


def test_strong_model_does_not_retry_on_the_same_model(tmp_path: Path) -> None:
    bad = claude_error("x", exit_code=0)
    bad = replace(bad, stdout=json.dumps({"type": "result", "subtype": "success", "result": "not json"}).encode())
    runner = FakeRunner(bad)
    provider, _logs, _made = _provider(runner, tmp_path, settings=_settings(provider=CLAUDE))
    strong = LlmRequest("p", SchemaName.ANSWER, None, lambda document: document, strong_model=True)
    result = provider.call(strong, CLAUDE)
    assert (result.outcome, result.retried, len(runner.calls)) == ("bad_output", False, 1)


# --- config ----------------------------------------------------------------------------------------------


def _write(path: Path, document: Any) -> Path:
    path.write_text(json.dumps(document), encoding="utf-8", newline="\n")
    return path


def test_fallback_on_usage_limit_defaults_on_and_can_be_turned_off(tmp_path: Path) -> None:
    on = load_llm_settings(_write(tmp_path / "a.json", {}))
    off = load_llm_settings(_write(tmp_path / "b.json", {"fallback_on_usage_limit": False}))
    assert on is not None and on.fallback_on_usage_limit is True
    assert off is not None and off.fallback_on_usage_limit is False


@pytest.mark.parametrize("value", ["yes", 1, None, [SECRET], SECRET])
def test_a_bad_fallback_on_usage_limit_is_refused_without_echoing_it(tmp_path: Path, value: Any) -> None:
    with pytest.raises(LlmConfigError) as caught:
        load_llm_settings(_write(tmp_path / "c.json", {"fallback_on_usage_limit": value}))
    assert "fallback_on_usage_limit must be true or false" in str(caught.value)
    assert SECRET not in str(caught.value)


def test_empty_config_is_codex_with_gpt_6_1_sol() -> None:
    # v2.5: default provider is codex (user decision 2026-10-21).
    assert DEFAULT_SETTINGS.provider is CODEX
    assert DEFAULT_SETTINGS.codex == ProviderSettings("gpt-6.1-sol", None, "gpt-6.1-sol", None)
    assert DEFAULT_SETTINGS.claude == ProviderSettings("haiku", None, "sonnet", "sonnet")
