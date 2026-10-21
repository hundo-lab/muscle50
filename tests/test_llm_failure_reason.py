"""Telegram LLM v2.5 failure reasons: the pure classifier over synthetic CLI results (never the real `claude` or
`codex`). Covers AC1 (classification part) of docs/specs/telegram-llm-failures-and-meals.md."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from test_telegram_llm_argv import PROMPT, FakeRunner, _provider, _request, claude_ok

from muscle50.domain.llm_failure import FailureReason, failure_text, reason_of, usage_fallback_note
from muscle50.domain.llm_settings import DEFAULT_SETTINGS, LlmSettings, ProviderName
from muscle50.infrastructure.llm import failure_reason as module
from muscle50.infrastructure.llm.failure_reason import TAIL_CHARS, classify
from muscle50.infrastructure.llm.process import ProcessResult

CLAUDE = ProviderName.CLAUDE
CODEX = ProviderName.CODEX
SENTINEL = "SENTINEL-cli-text-7c1d"


def _settings(**overrides: Any) -> LlmSettings:
    return replace(DEFAULT_SETTINGS, **overrides)


def _events(*events: dict[str, Any]) -> bytes:
    return "\n".join(json.dumps(event) for event in events).encode()


def claude_error(text: str, *, exit_code: int = 1, status: int | None = None) -> ProcessResult:
    result = {"type": "result", "subtype": "success", "is_error": True, "result": text, "api_error_status": status}
    return ProcessResult(exit_code, _events({"type": "system", "subtype": "init"}, result), b"", False)


def codex_error(stderr: str, *, prompt: str = PROMPT) -> ProcessResult:
    # Codex echoes the prompt on stderr before its own lines (live check 2026-10-21).
    echoed = f"OpenAI Codex v0.160.0\n--------\nuser\n{prompt}\n\nwarning: Code Mode is unavailable\n{stderr}\n"
    return ProcessResult(1, b"", echoed.encode(), False)


# --- the classifier ---------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "reason"),
    [
        ("Claude AI usage limit reached|1760000000", FailureReason.USAGE_LIMIT),
        ("You've hit your limit · resets 5pm (Asia/Seoul)", FailureReason.USAGE_LIMIT),
        ("5-hour limit reached ∙ resets 3pm", FailureReason.USAGE_LIMIT),
        ("Not logged in · Please run /login", FailureReason.LOGIN),
        ("OAuth token has expired. Please obtain a new token", FailureReason.LOGIN),
        ("Invalid API key · Fix external API key", FailureReason.LOGIN),
        ("API Error: Connection error.", FailureReason.NETWORK),
        ("API Error: getaddrinfo ENOTFOUND api.anthropic.com", FailureReason.NETWORK),
        ("something else went wrong", FailureReason.OTHER),
    ],
)
def test_claude_error_results_are_classified(text: str, reason: FailureReason) -> None:
    result = claude_error(text)
    assert classify(CLAUDE, result, result_text=text) is reason


@pytest.mark.parametrize(
    ("status", "reason"),
    [(429, FailureReason.USAGE_LIMIT), (401, FailureReason.LOGIN), (403, FailureReason.LOGIN), (500, None)],
)
def test_claude_api_status_decides_before_the_text(status: int, reason: FailureReason | None) -> None:
    result = claude_error("API Error")
    assert classify(CLAUDE, result, result_text="API Error", api_status=status) is (reason or FailureReason.OTHER)


@pytest.mark.parametrize(
    ("stderr", "reason"),
    [
        ("ERROR: You've hit your usage limit. Upgrade to Pro or try again at 3:05 PM.", FailureReason.USAGE_LIMIT),
        (
            "ERROR: unexpected status 401 Unauthorized: Missing bearer or basic authentication in header",
            FailureReason.LOGIN,
        ),
        ("ERROR: workspace routing discovery failed", FailureReason.NETWORK),
        ("ERROR: stream disconnected before completion: error sending request for url", FailureReason.NETWORK),
        ("ERROR: failed to connect (os error 10061)", FailureReason.NETWORK),
        ("ERROR: 연결할 수 없습니다. (os error 10060)", FailureReason.NETWORK),
        ("ERROR: something new", FailureReason.OTHER),
    ],
)
def test_codex_stderr_lines_are_classified(stderr: str, reason: FailureReason) -> None:
    assert classify(CODEX, codex_error(stderr), prompt=PROMPT) is reason


def test_a_specific_final_error_beats_the_generic_retry_lines() -> None:
    stderr = "ERROR: Reconnecting... 1/5 (error sending request for url)\nERROR: You've hit your usage limit."
    assert classify(CODEX, codex_error(stderr), prompt=PROMPT) is FailureReason.USAGE_LIMIT


def test_the_echoed_prompt_never_decides_the_reason() -> None:
    # The user's own words (in the echoed prompt) name a limit, a login and a DNS problem: none of it counts.
    prompt = "[메시지]\nerror: usage limit quota /login dns connection refused"
    assert classify(CODEX, codex_error("ERROR: something new", prompt=prompt), prompt=prompt) is FailureReason.OTHER
    # Codex lines without the word "error" are not read either (the answer block, the banner).
    quiet = ProcessResult(1, b"", b"codex\nusage limit quota\n", False)
    assert classify(CODEX, quiet, prompt="x") is FailureReason.OTHER


def test_only_the_tail_of_stderr_is_read() -> None:
    old = "ERROR: usage limit\n" + "ERROR: padding line\n" * (TAIL_CHARS // 10)
    assert classify(CODEX, codex_error(old), prompt=PROMPT) is FailureReason.OTHER
    assert classify(CLAUDE, ProcessResult(1, b"", old.encode(), False)) is FailureReason.OTHER


def test_a_timeout_is_a_timeout_unless_the_cli_was_still_retrying_its_connection() -> None:
    timed_out = ProcessResult(None, b"", b"connection refused", True)
    assert classify(CLAUDE, timed_out) is FailureReason.TIMEOUT
    # Live check 2026-10-21: Claude behind an unreachable proxy keeps `system/api_retry` (no HTTP status) until the
    # time limit.
    assert classify(CLAUDE, timed_out, retrying=True, retry_status=None) is FailureReason.NETWORK
    assert classify(CLAUDE, timed_out, retrying=True, retry_status=429) is FailureReason.USAGE_LIMIT
    assert classify(CLAUDE, timed_out, retrying=True, retry_status=401) is FailureReason.LOGIN
    assert classify(CLAUDE, ProcessResult(None, b"", b"", True), retrying=True, retry_status=529) is (
        FailureReason.TIMEOUT
    )


def test_the_classifier_returns_only_the_enum_and_keeps_no_text() -> None:
    result = classify(CODEX, codex_error(f"ERROR: {SENTINEL} usage limit"), prompt=PROMPT)
    assert result is FailureReason.USAGE_LIMIT and type(result) is FailureReason
    assert SENTINEL not in repr(vars(module))  # nothing cached at module level


def test_reason_of_maps_outcomes() -> None:
    assert reason_of("ok", None) is None
    assert reason_of("timeout", None) is FailureReason.TIMEOUT
    assert reason_of("timeout", FailureReason.NETWORK) is FailureReason.NETWORK
    assert reason_of("not_found", None) is FailureReason.NOT_FOUND
    assert reason_of("executable_not_supported", None) is FailureReason.NOT_FOUND
    assert reason_of("bad_output", None) is FailureReason.OTHER
    assert reason_of("failed", FailureReason.LOGIN) is FailureReason.LOGIN


def test_failure_texts_are_fixed() -> None:
    assert failure_text(FailureReason.USAGE_LIMIT, CLAUDE, other_tried=False) == (
        "Claude 사용 한도에 걸려 해석하지 못했습니다. 잠시 뒤 다시 보내거나 /llm codex 로 바꾸세요."
    )
    assert failure_text(FailureReason.USAGE_LIMIT, CODEX, other_tried=True) == (
        "Codex 사용 한도에 걸려 해석하지 못했습니다. 한도가 풀린 뒤 다시 보내세요."
    )
    assert failure_text(FailureReason.TIMEOUT, CODEX, other_tried=False) == (
        "Codex가 시간 안에 답하지 않아 해석하지 못했습니다. 다시 보내거나 /log 로 보내세요."
    )
    assert failure_text(FailureReason.OTHER, CLAUDE, other_tried=False) is None
    assert usage_fallback_note(CLAUDE, CODEX) == "(Claude 사용 한도라 이번에는 codex(OpenAI)로 처리했습니다.)"
    assert usage_fallback_note(CODEX, CLAUDE) == "(Codex 사용 한도라 이번에는 claude(Anthropic)로 처리했습니다.)"


# --- the provider ----------------------------------------------------------------------------------------


def test_claude_exit_1_is_still_parsed_for_the_reason_and_the_outcome_is_unchanged(tmp_path: Path) -> None:
    runner = FakeRunner(claude_error("Not logged in · Please run /login"))
    provider, logs, _made = _provider(runner, tmp_path)
    result = provider.call(_request(), CLAUDE)
    assert (result.outcome, result.failure_reason, result.retried) == ("failed", FailureReason.LOGIN, False)
    assert logs == ["llm claude: failed (exit 1) after 0 s (haiku); reason login"]


def test_a_plain_text_usage_limit_result_is_not_a_format_failure(tmp_path: Path) -> None:
    plain = {"type": "result", "subtype": "success", "is_error": False, "result": "You've hit your limit"}
    runner = FakeRunner(ProcessResult(0, _events(plain), b"", False), claude_ok())
    provider, _logs, _made = _provider(runner, tmp_path, settings=_settings(fallback_on_usage_limit=False))
    result = provider.call(_request(), CLAUDE)
    assert (result.outcome, result.failure_reason, result.retried) == ("bad_output", FailureReason.USAGE_LIMIT, False)
    assert len(runner.calls) == 1  # no Sonnet retry of a usage limit
    # A long plain-text answer is the model's own text: still a format failure, retried once.
    long = {**plain, "result": "x" * 600 + " usage limit"}
    runner = FakeRunner(ProcessResult(0, _events(long), b"", False), claude_ok())
    provider, _logs, _made = _provider(runner, tmp_path / "long", settings=_settings(fallback_on_usage_limit=False))
    assert provider.call(_request(), CLAUDE).retried is True


def test_codex_failure_reason_from_stderr_and_the_cli_text_is_never_logged(tmp_path: Path) -> None:
    runner = FakeRunner(codex_error(f"ERROR: unexpected status 401 Unauthorized {SENTINEL}"))
    provider, logs, _made = _provider(runner, tmp_path)
    result = provider.call(_request(), CODEX)
    assert result.failure_reason is FailureReason.LOGIN
    assert logs == ["llm codex: failed (exit 1) after 0 s (gpt-6.1-sol); reason login"]
    assert SENTINEL not in repr(result)
