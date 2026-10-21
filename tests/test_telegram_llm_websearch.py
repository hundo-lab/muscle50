"""Telegram LLM v2.2 web search: the Claude argv variant, the provider (flag, timeout, count, pinned re-ask),
the three config keys and the startup line. Never runs the real `claude` or `codex`; the stream is synthetic."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from test_telegram_llm_argv import (
    CLAUDE_EXE,
    CODEX_EXE,
    DOCUMENT,
    FAILED,
    PROMPT,
    TIMED_OUT,
    FakeRunner,
    _provider,
    claude_ok,
    codex_ok,
)

from muscle50.application.llm_provider import LlmAttempt, LlmCallResult, LlmRequest, RunPin, SchemaName
from muscle50.cli import _web_search_text
from muscle50.domain.llm_settings import DEFAULT_SETTINGS, ProviderName, ProviderSettings
from muscle50.infrastructure.llm.argv import (
    CLAUDE_ISOLATION_ARGV,
    CLAUDE_SYSTEM_PROMPT,
    CLAUDE_SYSTEM_PROMPT_WEB,
    CLAUDE_WEB_ISOLATION_ARGV,
    claude_argv,
)
from muscle50.infrastructure.llm.process import ProcessResult
from muscle50.infrastructure.llm.provider import count_web_searches, load_schema
from muscle50.infrastructure.telegram.llm_config_file import LlmConfigError, load_llm_settings

QUERY = "SENTINEL-QUERY-bodol-miyeok"
PAGE = "SENTINEL-PAGE-BODY"


def _search_block(block_id: str, *, name: str = "WebSearch", kind: str = "tool_use") -> dict[str, Any]:
    return {"type": kind, "id": block_id, "name": name, "input": {"query": QUERY}}


def _stream(*blocks: dict[str, Any], document: Any = DOCUMENT, finish: bool = True) -> ProcessResult:
    events: list[dict[str, Any]] = [
        {"type": "system", "subtype": "init", "tools": ["WebSearch", "StructuredOutput"], "mcp_servers": []}
    ]
    for block in blocks:
        events.append({"type": "assistant", "message": {"role": "assistant", "content": [block]}})
        events.append(
            {
                "type": "user",
                "message": {
                    "role": "user",
                    "content": [{"type": "tool_result", "tool_use_id": block["id"], "content": PAGE}],
                },
            }
        )
    if finish:
        events.append(
            {
                "type": "result",
                "subtype": "success",
                "is_error": False,
                "result": json.dumps(document),
                "structured_output": document,
            }
        )
        return ProcessResult(0, "\n".join(json.dumps(event) for event in events).encode(), b"", False)
    return ProcessResult(None, "\n".join(json.dumps(event) for event in events).encode(), b"", True)


def _request(
    *,
    web: bool = True,
    photo: bytes | None = None,
    pin: RunPin | None = None,
    validate: Any = lambda document: document,
) -> LlmRequest:
    return LlmRequest(PROMPT, SchemaName.ANSWER, photo, validate, web_search=web, pin=pin)


# --- argv ----------------------------------------------------------------------------------------------------


def test_the_web_argv_only_replaces_the_empty_tools_value_and_adds_allowed_tools() -> None:
    tools = CLAUDE_ISOLATION_ARGV.index("--tools")
    derived = (
        *CLAUDE_ISOLATION_ARGV[:tools],
        "--tools",
        "WebSearch",
        "--allowedTools",
        "WebSearch",
        *CLAUDE_ISOLATION_ARGV[tools + 2 :],
    )
    assert derived == CLAUDE_WEB_ISOLATION_ARGV
    assert CLAUDE_ISOLATION_ARGV[tools : tools + 2] == ("--tools", "")  # the non-web argv is untouched
    assert "--bare" not in CLAUDE_WEB_ISOLATION_ARGV
    assert CLAUDE_SYSTEM_PROMPT_WEB.isascii() and CLAUDE_SYSTEM_PROMPT_WEB != CLAUDE_SYSTEM_PROMPT


def test_claude_argv_web_variant_and_default() -> None:
    schema = load_schema(SchemaName.INTERPRET)
    compact = json.dumps(schema, separators=(",", ":"), ensure_ascii=True)
    web = claude_argv("claude.exe", "haiku", schema, web_search=True)
    assert web == (
        "claude.exe",
        *CLAUDE_WEB_ISOLATION_ARGV,
        "--model",
        "haiku",
        "--system-prompt",
        CLAUDE_SYSTEM_PROMPT_WEB,
        "--json-schema",
        compact,
    )
    assert web[-4] == "--system-prompt" and web[-3] == CLAUDE_SYSTEM_PROMPT_WEB
    plain = claude_argv("claude.exe", "haiku", schema)
    assert plain == claude_argv("claude.exe", "haiku", schema, web_search=False)
    assert plain[1 : 1 + len(CLAUDE_ISOLATION_ARGV)] == CLAUDE_ISOLATION_ARGV and "WebSearch" not in plain


# --- provider ------------------------------------------------------------------------------------------------


def test_a_web_request_uses_the_web_argv_and_the_search_timeout(tmp_path: Path) -> None:
    runner = FakeRunner(_stream(_search_block("t1"), _search_block("t2")))
    provider, logs, _made = _provider(runner, tmp_path)
    result = provider.call(_request(), ProviderName.CLAUDE)
    assert (result.outcome, result.document, result.web_searches) == ("ok", DOCUMENT, 2)
    call = runner.calls[0]
    assert call.argv == claude_argv(CLAUDE_EXE, "haiku", load_schema(SchemaName.ANSWER), web_search=True)
    assert call.timeout_s == DEFAULT_SETTINGS.web_search_timeout_seconds == 150
    assert call.cwd_files == []
    assert logs == ["llm claude: ok after 0 s (haiku, web search 2)"]
    assert QUERY not in "".join(logs) and PAGE not in "".join(logs)
    assert QUERY not in repr(result) and PAGE not in repr(result)  # only the count is kept


def test_a_request_without_the_flag_keeps_the_old_argv_and_timeout(tmp_path: Path) -> None:
    runner = FakeRunner(claude_ok())
    provider, logs, _made = _provider(runner, tmp_path)
    result = provider.call(_request(web=False), ProviderName.CLAUDE)
    call = runner.calls[0]
    assert call.argv == claude_argv(CLAUDE_EXE, "haiku", load_schema(SchemaName.ANSWER))
    assert "WebSearch" not in call.argv and call.timeout_s == 90
    assert result.web_searches is None and result.attempts[0].web_searches is None
    assert logs == ["llm claude: ok after 0 s (haiku)"]


def test_an_offered_but_unused_tool_is_zero_not_none_and_leaves_the_log_line_alone(tmp_path: Path) -> None:
    runner = FakeRunner(_stream())
    provider, logs, _made = _provider(runner, tmp_path)
    result = provider.call(_request(), ProviderName.CLAUDE)
    assert result.web_searches == 0 and result.attempts[0].web_searches == 0
    assert logs == ["llm claude: ok after 0 s (haiku)"]


def test_codex_never_searches_even_when_the_request_asks(tmp_path: Path) -> None:
    runner = FakeRunner(codex_ok())
    provider, _logs, _made = _provider(runner, tmp_path)
    result = provider.call(_request(photo=b"\xff\xd8\xff\xe0x"), ProviderName.CODEX)
    call = runner.calls[0]
    assert call.argv[0] == CODEX_EXE and 'web_search="disabled"' in call.argv and "WebSearch" not in call.argv
    assert call.timeout_s == 90
    assert result.web_searches is None


def test_a_web_photo_keeps_the_image_block_in_stdin_and_the_search_timeout(tmp_path: Path) -> None:
    runner = FakeRunner(_stream(_search_block("t1")))
    provider, _logs, _made = _provider(runner, tmp_path)
    provider.call(_request(photo=b"\xff\xd8\xff\xe0x"), ProviderName.CLAUDE)
    call = runner.calls[0]
    assert call.stdin is not None
    content = json.loads(call.stdin.decode("ascii"))["message"]["content"]
    assert [block["type"] for block in content] == ["text", "image"]
    assert call.timeout_s == 150 and call.cwd_files == []


def test_distinct_tool_ids_are_counted_once_and_other_tools_are_not_counted() -> None:
    result = _stream(
        _search_block("a"),
        _search_block("a"),
        _search_block("b", name="web_search", kind="server_tool_use"),
        _search_block("c", name="StructuredOutput"),
        _search_block("d", name="WebFetch"),
    )
    assert count_web_searches(result.stdout) == 2
    assert count_web_searches(b"not json\n{}\n[]\n") == 0
    assert count_web_searches(b"") == 0


def test_the_count_survives_a_timeout_and_its_partial_stdout(tmp_path: Path) -> None:
    runner = FakeRunner(_stream(_search_block("t1"), finish=False))
    provider, logs, _made = _provider(runner, tmp_path)
    result = provider.call(_request(), ProviderName.CLAUDE)
    assert (result.outcome, result.web_searches) == ("timeout", 1)
    assert logs == ["llm claude: timeout after 0 s (haiku, web search 1)"]


def test_a_use_above_the_limit_is_logged_without_text(tmp_path: Path) -> None:
    blocks = [_search_block(f"t{number}") for number in range(4)]
    runner = FakeRunner(_stream(*blocks))
    provider, logs, _made = _provider(runner, tmp_path)
    result = provider.call(_request(), ProviderName.CLAUDE)
    assert result.web_searches == 4
    assert logs == [
        "llm claude: ok after 0 s (haiku, web search 4)",
        "llm claude: web search used 4, above the limit 3",
    ]


def test_the_search_timeout_comes_from_the_settings(tmp_path: Path) -> None:
    settings = replace(DEFAULT_SETTINGS, web_search_timeout_seconds=40, timeout_seconds=20)
    runner = FakeRunner(_stream(), claude_ok())
    provider, _logs, _made = _provider(runner, tmp_path, settings=settings)
    provider.call(_request(), ProviderName.CLAUDE)
    provider.call(_request(web=False), ProviderName.CLAUDE)
    assert [call.timeout_s for call in runner.calls] == [40, 20]


def test_the_format_retry_keeps_the_tool_and_sums_the_searches(tmp_path: Path) -> None:
    def reject_first(document: Any) -> Any:
        if document == {"first": True}:
            raise ValueError("bad")
        return document

    runner = FakeRunner(
        _stream(_search_block("a"), document={"first": True}), _stream(_search_block("b"), _search_block("c"))
    )
    provider, logs, _made = _provider(runner, tmp_path)
    result = provider.call(_request(validate=reject_first), ProviderName.CLAUDE)
    assert result.outcome == "ok" and result.retried
    assert [call.argv[:6] for call in runner.calls] == [runner.calls[0].argv[:6]] * 2
    assert all("WebSearch" in call.argv for call in runner.calls)
    assert [attempt.web_searches for attempt in result.attempts] == [1, 2]
    assert result.web_searches == 3
    assert logs[0] == "llm claude: bad output after 0 s (haiku, web search 1)"
    assert logs[1] == "llm claude: ok after 0 s (sonnet, retry, web search 2)"


# --- the pinned re-ask -----------------------------------------------------------------------------------------


def test_a_pinned_request_runs_once_on_the_pinned_model_without_retry_or_fallback(tmp_path: Path) -> None:
    settings = replace(DEFAULT_SETTINGS, fallback_provider=ProviderName.CODEX)
    runner = FakeRunner(_stream(document={"bad": 1}))

    def reject(document: Any) -> Any:
        raise ValueError("bad")

    provider, logs, _made = _provider(runner, tmp_path, settings=settings)
    result = provider.call(_request(pin=RunPin("sonnet"), validate=reject), ProviderName.CLAUDE)
    assert (result.outcome, result.provider, result.model, result.used_fallback) == (
        "bad_output",
        ProviderName.CLAUDE,
        "sonnet",
        False,
    )
    assert len(runner.calls) == 1 and "sonnet" in runner.calls[0].argv and "haiku" not in runner.calls[0].argv
    assert [attempt.retry for attempt in result.attempts] == [False]
    assert logs == ["llm claude: bad output after 0 s (sonnet)"]


def test_a_pinned_request_that_fails_does_not_try_the_fallback(tmp_path: Path) -> None:
    settings = replace(DEFAULT_SETTINGS, fallback_provider=ProviderName.CODEX)
    runner = FakeRunner(FAILED)
    provider, _logs, _made = _provider(runner, tmp_path, settings=settings)
    result = provider.call(_request(pin=RunPin("sonnet")), ProviderName.CLAUDE)
    assert (result.outcome, len(runner.calls)) == ("failed", 1)


def test_a_pinned_codex_request_uses_codex_with_the_pinned_model(tmp_path: Path) -> None:
    settings = replace(DEFAULT_SETTINGS, codex=ProviderSettings("gpt-5", None, None, "gpt-5.5"))
    runner = FakeRunner(codex_ok())
    provider, _logs, _made = _provider(runner, tmp_path, settings=settings)
    result = provider.call(_request(pin=RunPin("gpt-5.5")), ProviderName.CODEX)
    argv = runner.calls[0].argv
    assert result.ok and argv[argv.index("-m") + 1] == "gpt-5.5" and len(runner.calls) == 1


def test_pinned_run_that_times_out_is_one_timeout(tmp_path: Path) -> None:
    runner = FakeRunner(TIMED_OUT)
    provider, _logs, _made = _provider(runner, tmp_path)
    assert provider.call(_request(pin=RunPin(None)), ProviderName.CLAUDE).outcome == "timeout"
    assert "--model" not in runner.calls[0].argv


def test_call_result_web_searches_property() -> None:
    def attempt(searches: int | None) -> LlmAttempt:
        return LlmAttempt(ProviderName.CLAUDE, "haiku", "ok", 1.0, web_searches=searches)

    def result(*attempts: LlmAttempt) -> LlmCallResult:
        return LlmCallResult(ProviderName.CLAUDE, "haiku", "ok", None, 1.0, False, attempts)

    assert result().web_searches is None
    assert result(attempt(None), attempt(None)).web_searches is None
    assert result(attempt(None), attempt(0)).web_searches == 0
    assert result(attempt(2), attempt(1)).web_searches == 3


# --- config --------------------------------------------------------------------------------------------------


def _config(tmp_path: Path, document: Any) -> Path:
    path = tmp_path / "telegram_llm.json"
    path.write_text(json.dumps(document), encoding="utf-8", newline="\n")
    return path


def test_web_search_defaults_and_an_old_file_without_the_keys(tmp_path: Path) -> None:
    assert (DEFAULT_SETTINGS.web_search, DEFAULT_SETTINGS.web_search_max) == (True, 3)
    assert DEFAULT_SETTINGS.web_search_timeout_seconds == 150
    assert load_llm_settings(_config(tmp_path, {})) == DEFAULT_SETTINGS
    old = {"provider": "claude", "timeout_seconds": 60, "keep_photos": False, "persona": {"name": "코치"}}
    settings = load_llm_settings(_config(tmp_path, old))
    assert settings is not None
    assert (settings.web_search, settings.web_search_max, settings.web_search_timeout_seconds) == (True, 3, 150)
    assert settings.timeout_seconds == 60


def test_web_search_keys_are_read(tmp_path: Path) -> None:
    document = {"web_search": False, "web_search_max": 10, "web_search_timeout_seconds": 600}
    settings = load_llm_settings(_config(tmp_path, document))
    assert settings is not None
    assert (settings.web_search, settings.web_search_max, settings.web_search_timeout_seconds) == (False, 10, 600)
    low = load_llm_settings(_config(tmp_path, {"web_search_max": 1, "web_search_timeout_seconds": 10}))
    assert low is not None and (low.web_search_max, low.web_search_timeout_seconds) == (1, 10)


@pytest.mark.parametrize(
    ("document", "key"),
    [
        ({"web_search": "yes"}, "web_search"),
        ({"web_search": 1}, "web_search"),
        ({"web_search_max": 0}, "web_search_max"),
        ({"web_search_max": 11}, "web_search_max"),
        ({"web_search_max": True}, "web_search_max"),
        ({"web_search_max": 2.5}, "web_search_max"),
        ({"web_search_max": "3"}, "web_search_max"),
        ({"web_search_timeout_seconds": 9}, "web_search_timeout_seconds"),
        ({"web_search_timeout_seconds": 601}, "web_search_timeout_seconds"),
        ({"web_search_timeout_seconds": "150"}, "web_search_timeout_seconds"),
        ({"web_search_timeout_seconds": False}, "web_search_timeout_seconds"),
    ],
)
def test_bad_web_search_values_are_refused_without_echoing_the_value(
    tmp_path: Path, document: dict[str, Any], key: str
) -> None:
    value = next(iter(document.values()))
    with pytest.raises(LlmConfigError) as caught:
        load_llm_settings(_config(tmp_path, document))
    message = str(caught.value)
    assert key in message
    if isinstance(value, str):
        assert f"'{value}'" not in message and f'"{value}"' not in message


def test_unknown_web_key_is_named_without_its_value(tmp_path: Path) -> None:
    with pytest.raises(LlmConfigError) as caught:
        load_llm_settings(_config(tmp_path, {"web_searches": "SENTINEL-VALUE"}))
    assert "web_searches" in str(caught.value) and "SENTINEL-VALUE" not in str(caught.value)


def test_the_startup_line_names_the_web_search_setting() -> None:
    # v2.5: the default provider is codex (user decision 2026-10-21), and Codex never searches; only a Claude lookup
    # does (user decision W3 "search only on Claude"). An explicit Claude provider keeps the v2.2 text.
    claude = replace(DEFAULT_SETTINGS, provider=ProviderName.CLAUDE)
    assert _web_search_text(DEFAULT_SETTINGS) == "web search via claude when needed (max 3, 150 s)"
    assert _web_search_text(claude) == "web search on (max 3, 150 s)"
    assert _web_search_text(replace(DEFAULT_SETTINGS, web_search=False)) == "web search off"
    assert _web_search_text(replace(claude, web_search=False)) == "web search off"
    assert _web_search_text(replace(claude, web_search_max=5, web_search_timeout_seconds=200)) == (
        "web search on (max 5, 200 s)"
    )
