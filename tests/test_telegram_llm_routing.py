"""Telegram LLM model routing: light text model, stronger photo model, one retry after a format failure, the
`/llm` first line and the two new history keys. Fake runners only (never the real `claude` or `codex`, never the
network), a temporary MUSCLE50_HOME and synthetic values. Covers AC1-AC10 of docs/specs/telegram-llm-model-routing.md.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
import test_telegram_bot as v1
import test_telegram_llm_argv as argv_tests
import test_telegram_llm_bot as bot
from test_telegram_llm_argv import (
    CLAUDE_EXE,
    CODEX_EXE,
    FAILED,
    PHOTO,
    TIMED_OUT,
    FakeRunner,
    _executables,
    _provider,
    _request,
    claude_ok,
    codex_ok,
)
from test_telegram_llm_domain import interpretation

import muscle50.cli as cli
from muscle50.application.llm_provider import LlmAttempt, LlmCallResult, LlmRequest, SchemaName
from muscle50.cli import main
from muscle50.domain.llm_failure import FailureReason, retry_line
from muscle50.domain.llm_settings import DEFAULT_SETTINGS, LlmSettings, ProviderName, ProviderSettings
from muscle50.domain.telegram_llm import (
    HISTORY_KEYS,
    HISTORY_KEYS_V1,
    HISTORY_KEYS_V21,
    HISTORY_KEYS_V22,
    ProposalKind,
    check_history_entry,
    history_entry,
)
from muscle50.domain.telegram_llm_prompt import PROVIDER_FAILED_TEXT
from muscle50.infrastructure.llm.argv import CLAUDE_SYSTEM_PROMPT, claude_argv, codex_argv
from muscle50.infrastructure.llm.executables import ResolvedExecutable
from muscle50.infrastructure.llm.process import ProcessResult
from muscle50.infrastructure.llm.provider import TEMP_PREFIX, CliLlmProvider, load_schema
from muscle50.infrastructure.telegram.history_log import JsonlHistoryLog
from muscle50.infrastructure.telegram.llm_config_file import LlmConfigError, load_llm_settings
from muscle50.infrastructure.telegram.llm_state_store import JsonLlmStateStore
from muscle50.presentation.telegram_llm_replies import history_text, render_telegram_history

home = bot.home  # the autouse fixture of the bot tests: temporary MUSCLE50_HOME, fake clock, no network
CLAUDE = ProviderName.CLAUDE
CODEX = ProviderName.CODEX
SECRET = "sk-synthetic-secret-value"
BAD_CODEX = ProcessResult(0, b"", b"", False)  # exit 0 but no last.json: a format failure


def claude_text(text: str | None) -> ProcessResult:
    """A successful Claude result event whose `result` is not usable JSON (a format failure)."""
    event = {"type": "result", "subtype": "success", "is_error": False, "result": text}
    return ProcessResult(0, json.dumps(event).encode(), b"", False)


def claude_event(**fields: Any) -> ProcessResult:
    return ProcessResult(0, json.dumps({"type": "result", **fields}).encode(), b"", False)


def _model(argv: tuple[str, ...], flag: str = "--model") -> str | None:
    return argv[argv.index(flag) + 1] if flag in argv else None


def _settings(**overrides: Any) -> LlmSettings:
    return replace(DEFAULT_SETTINGS, **overrides)


def _proposals(root: Path) -> tuple[Any, ...]:
    return JsonLlmStateStore(root / "config" / "telegram_llm_state.json").load().proposals


def _write_config(path: Path, document: Any) -> Path:
    path.write_text(json.dumps(document), encoding="utf-8", newline="\n")
    return path


# --- settings (AC1, AC2, AC8) ----------------------------------------------------------------------------


def test_defaults_are_haiku_text_sonnet_photo_sonnet_retry_and_codex_gpt_6_1_sol() -> None:
    assert DEFAULT_SETTINGS.claude == ProviderSettings("haiku", None, "sonnet", "sonnet")
    # v2.5: default provider is codex (user decision 2026-10-21); its models are the Sonnet-class `gpt-6.1-sol`
    # for text and photos, no retry model.
    assert DEFAULT_SETTINGS.provider is CODEX
    assert DEFAULT_SETTINGS.codex == ProviderSettings("gpt-6.1-sol", None, "gpt-6.1-sol", None)


def test_empty_file_gives_the_defaults_and_a_v2_file_takes_defaults_for_the_new_keys(tmp_path: Path) -> None:
    assert load_llm_settings(_write_config(tmp_path / "a.json", {})) == DEFAULT_SETTINGS
    v2 = load_llm_settings(_write_config(tmp_path / "b.json", {"claude": {"model": "sonnet", "executable": None}}))
    assert v2 is not None and v2.claude == ProviderSettings("sonnet", None, "sonnet", "sonnet")
    # D5: an explicit `model` does not change the photo or retry default.
    opus = load_llm_settings(_write_config(tmp_path / "c.json", {"claude": {"model": "opus"}}))
    assert opus is not None and opus.claude == ProviderSettings("opus", None, "sonnet", "sonnet")
    assert opus.codex == ProviderSettings("gpt-6.1-sol", None, "gpt-6.1-sol", None)  # v2.5 Codex defaults


def test_new_keys_can_be_set_or_null(tmp_path: Path) -> None:
    document = {
        "claude": {"model": "haiku", "photo_model": None, "retry_model": None},
        "codex": {"model": "gpt-5.5", "photo_model": "gpt-5.5-photo", "retry_model": "gpt-5.5-pro"},
    }
    settings = load_llm_settings(_write_config(tmp_path / "c.json", document))
    assert settings is not None
    assert settings.claude == ProviderSettings("haiku", None, None, None)
    assert settings.codex == ProviderSettings("gpt-5.5", None, "gpt-5.5-photo", "gpt-5.5-pro")


@pytest.mark.parametrize(
    ("document", "key"),
    [
        ({"claude": {"photo_model": SECRET + " x"}}, "claude.photo_model"),
        ({"claude": {"retry_model": 5}}, "claude.retry_model"),
        ({"codex": {"retry_model": "a b"}}, "codex.retry_model"),
        ({"codex": {"photo_model": ["x"]}}, "codex.photo_model"),
        ({"claude": {"x": SECRET}}, "unknown key in claude"),
        ({"claude": {"model": SECRET + " "}}, "claude.model"),
    ],
)
def test_bad_new_keys_are_refused_without_echoing_the_value(tmp_path: Path, document: Any, key: str) -> None:
    with pytest.raises(LlmConfigError) as caught:
        load_llm_settings(_write_config(tmp_path / "c.json", document))
    assert key in str(caught.value) and SECRET not in str(caught.value)


def test_model_selection_is_pure() -> None:
    both = ProviderSettings("haiku", None, "sonnet", "opus")
    assert (both.model_for(photo=False), both.model_for(photo=True)) == ("haiku", "sonnet")
    plain = ProviderSettings("haiku", None)
    assert (plain.model_for(photo=False), plain.model_for(photo=True)) == ("haiku", "haiku")
    unset = ProviderSettings(None, None)
    assert (unset.model_for(photo=False), unset.model_for(photo=True)) == (None, None)
    assert both.retry_after("haiku") == "opus" and both.retry_after(None) == "opus"
    assert both.retry_after("opus") is None  # the same model would not help
    assert plain.retry_after("haiku") is None
    assert ProviderSettings(None, None, None, "x").retry_after(None) == "x"


def test_request_and_result_helpers() -> None:
    assert _request().has_photo is False and _request(PHOTO).has_photo is True
    plain = LlmAttempt(CLAUDE, "haiku", "ok", 1.0)
    rerun = LlmAttempt(CLAUDE, "sonnet", "ok", 1.0, retry=True)
    assert LlmCallResult(CLAUDE, "haiku", "ok", None, 1.0, False, (plain,)).retried is False
    assert LlmCallResult(CLAUDE, "sonnet", "ok", None, 2.0, False, (plain, rerun)).retried is True
    assert LlmCallResult(CLAUDE, "haiku", "ok", None, 1.0, False).retried is False


# --- the provider: model per message kind (AC1, AC2, AC6, AC9) --------------------------------------------


def test_text_runs_on_haiku_and_a_photo_on_sonnet_with_the_pinned_argv(tmp_path: Path) -> None:
    runner = FakeRunner(claude_ok(), claude_ok())
    provider, _logs, _made = _provider(runner, tmp_path)
    provider.call(_request(), CLAUDE)
    provider.call(_request(PHOTO), CLAUDE)
    schema = load_schema(SchemaName.ANSWER)
    assert runner.calls[0].argv == claude_argv(CLAUDE_EXE, "haiku", schema)
    assert runner.calls[1].argv == claude_argv(CLAUDE_EXE, "sonnet", schema)


def test_photo_model_null_makes_photos_use_the_model(tmp_path: Path) -> None:
    settings = _settings(claude=ProviderSettings("opus", None, None, None))
    runner = FakeRunner(claude_ok(), claude_ok())
    provider, _logs, _made = _provider(runner, tmp_path, settings=settings)
    provider.call(_request(), CLAUDE)
    provider.call(_request(PHOTO), CLAUDE)
    assert [_model(call.argv) for call in runner.calls] == ["opus", "opus"]


def test_model_null_omits_the_model_option(tmp_path: Path) -> None:
    settings = _settings(claude=ProviderSettings(None, None, None, None))
    runner = FakeRunner(claude_ok())
    provider, _logs, _made = _provider(runner, tmp_path, settings=settings)
    provider.call(_request(), CLAUDE)
    assert "--model" not in runner.calls[0].argv


def test_codex_uses_m_per_message_kind_and_none_omits_it(tmp_path: Path) -> None:
    settings = _settings(codex=ProviderSettings("gpt-text", None, "gpt-photo", None))
    runner = FakeRunner(codex_ok(), codex_ok())
    provider, _logs, _made = _provider(runner, tmp_path, settings=settings)
    provider.call(_request(), CODEX)
    provider.call(_request(PHOTO), CODEX)
    assert [_model(call.argv, "-m") for call in runner.calls] == ["gpt-text", "gpt-photo"]
    plain = FakeRunner(codex_ok())
    unset = _settings(codex=ProviderSettings(None, None))  # v2.5: the default Codex model is no longer None
    provider, _logs, _made = _provider(plain, tmp_path / "plain", settings=unset)
    provider.call(_request(PHOTO), CODEX)
    assert "-m" not in plain.calls[0].argv


def test_codex_retry_keeps_the_photo_and_the_isolation_argv(tmp_path: Path) -> None:
    settings = _settings(codex=ProviderSettings("mini", None, None, "big"))
    runner = FakeRunner(BAD_CODEX, codex_ok())
    provider, _logs, made = _provider(runner, tmp_path, settings=settings)
    result = provider.call(_request(PHOTO), CODEX)
    assert (result.outcome, result.model, result.retried) == ("ok", "big", True)
    assert [_model(call.argv, "-m") for call in runner.calls] == ["mini", "big"]
    second = runner.calls[1]
    work, io = made[1] / "work", made[1] / "io"
    assert second.cwd_files == ["photo.jpg"] and second.stdin == argv_tests.PROMPT.encode("utf-8")
    assert second.argv == codex_argv(
        CODEX_EXE,
        "big",
        schema_path=io / "schema.json",
        output_path=io / "last.json",
        work_dir=work,
        photo_path=work / "photo.jpg",
    )
    assert second.argv[-3:] == ("-", "-i", str(work / "photo.jpg"))


# --- the retry loop (AC3, AC4, AC5) ------------------------------------------------------------------------


def test_format_failure_is_rerun_once_on_the_retry_model(tmp_path: Path) -> None:
    runner = FakeRunner(claude_text("not json"), claude_ok())
    provider, logs, made = _provider(runner, tmp_path)
    result = provider.call(_request(), CLAUDE)
    assert (result.outcome, result.model, result.provider, result.document) == (
        "ok",
        "sonnet",
        CLAUDE,
        argv_tests.DOCUMENT,
    )
    assert (result.retried, result.used_fallback, len(runner.calls)) == (True, False, 2)
    assert [_model(call.argv) for call in runner.calls] == ["haiku", "sonnet"]
    schema = load_schema(SchemaName.ANSWER)  # AC9: both runs use exactly the pinned argv, only the model differs
    assert [call.argv for call in runner.calls] == [
        claude_argv(CLAUDE_EXE, "haiku", schema),
        claude_argv(CLAUDE_EXE, "sonnet", schema),
    ]
    assert result.attempts == (
        LlmAttempt(CLAUDE, "haiku", "bad_output", 0.0, 0, False, reason=FailureReason.OTHER),  # v2.5 reason
        LlmAttempt(CLAUDE, "sonnet", "ok", 0.0, 0, True),
    )
    assert logs == ["llm claude: bad output after 0 s (haiku)", "llm claude: ok after 0 s (sonnet, retry)"]
    # The same input: same prompt on stdin, own fresh temp folder per run, all removed.
    assert runner.calls[0].stdin == runner.calls[1].stdin
    assert [call.cwd for call in runner.calls] == [made[0] / "work", made[1] / "work"]
    assert len(made) == 2 and not any(path.exists() for path in made)


def test_a_failed_retry_is_not_retried_again(tmp_path: Path) -> None:
    runner = FakeRunner(claude_text("not json"), claude_text("still not json"))
    provider, logs, made = _provider(runner, tmp_path)
    result = provider.call(_request(), CLAUDE)
    assert (result.outcome, result.document, result.model, result.retried) == ("bad_output", None, "sonnet", True)
    assert len(runner.calls) == 2 and len(made) == 2 and not any(path.exists() for path in made)
    assert logs[1] == "llm claude: bad output after 0 s (sonnet, retry)"


def test_seconds_are_the_sum_of_all_runs(tmp_path: Path) -> None:
    ticks = iter([0.0, 3.0, 3.0, 8.0])
    runner = FakeRunner(claude_text("x"), claude_ok())
    provider, _logs, _made = _provider(runner, tmp_path)
    provider._clock = lambda: next(ticks)
    result = provider.call(_request(), CLAUDE)
    assert result.seconds == 8.0 and [attempt.seconds for attempt in result.attempts] == [3.0, 5.0]


def test_photos_do_not_retry_under_the_defaults(tmp_path: Path) -> None:
    runner = FakeRunner(claude_text("not json"), claude_ok())
    provider, _logs, _made = _provider(runner, tmp_path)
    result = provider.call(_request(PHOTO), CLAUDE)  # photo model sonnet == retry model sonnet
    assert (result.outcome, result.retried, len(runner.calls)) == ("bad_output", False, 1)


@pytest.mark.parametrize(
    "claude_settings",
    [ProviderSettings("sonnet", None, None, "sonnet"), ProviderSettings("haiku", None, "sonnet", None)],
    ids=["retry equals the model", "retry is null"],
)
def test_no_retry_when_the_retry_model_is_the_same_or_null(tmp_path: Path, claude_settings: ProviderSettings) -> None:
    model = claude_settings.model_for(photo=False)
    runner = FakeRunner(claude_text("not json"), claude_ok())
    provider, _logs, _made = _provider(runner, tmp_path, settings=_settings(claude=claude_settings))
    result = provider.call(_request(), CLAUDE)
    assert (result.outcome, result.retried, len(runner.calls)) == ("bad_output", False, 1)
    assert _model(runner.calls[0].argv) == model


class _RejectFirst:
    """A validator that rejects the first document and accepts the next (a schema or range failure)."""

    def __init__(self) -> None:
        self.seen = 0

    def __call__(self, document: Any) -> Any:
        self.seen += 1
        if self.seen == 1:
            raise ValueError("out of range")
        return document


@pytest.mark.parametrize(
    ("first", "reject_first"),
    [(claude_text("not json"), False), (claude_text(None), False), (claude_ok(), True)],
    ids=["result is not json", "result is not a string", "validator rejects"],
)
def test_claude_format_failures_retry(tmp_path: Path, first: ProcessResult, reject_first: bool) -> None:
    runner = FakeRunner(first, claude_ok())
    provider, _logs, _made = _provider(runner, tmp_path)
    request = _request(validate=_RejectFirst()) if reject_first else _request()
    result = provider.call(request, CLAUDE)
    assert (result.outcome, result.retried, len(runner.calls)) == ("ok", True, 2)


def test_codex_without_a_usable_last_json_retries(tmp_path: Path) -> None:
    settings = _settings(codex=ProviderSettings("mini", None, None, "big"))
    runner = FakeRunner(BAD_CODEX, codex_ok())
    provider, _logs, _made = _provider(runner, tmp_path, settings=settings)
    result = provider.call(_request(), CODEX)
    assert (result.outcome, result.model, result.retried, len(runner.calls)) == ("ok", "big", True, 2)


@pytest.mark.parametrize(
    "response",
    [
        FAILED,
        TIMED_OUT,
        claude_event(subtype="error_max_turns"),
        claude_event(subtype="success", is_error=True, result="usage limit reached"),
        ProcessResult(0, b"not json\n", b"", False),
    ],
    ids=["failed", "timeout", "error_max_turns", "is_error", "no result event"],
)
def test_cli_errors_and_other_outcomes_are_never_retried(tmp_path: Path, response: ProcessResult) -> None:
    runner = FakeRunner(response, claude_ok())
    # v2.5: a usage limit goes to the other provider by default (`fallback_on_usage_limit`); off here, so this test
    # still pins that no CLI error is retried on the same provider.
    settings = _settings(fallback_on_usage_limit=False)
    provider, logs, _made = _provider(runner, tmp_path, settings=settings)
    result = provider.call(_request(), CLAUDE)
    assert result.outcome != "ok" and result.retried is False and len(runner.calls) == 1
    assert len(logs) == 1


@pytest.mark.parametrize(
    "failure",
    [
        ResolvedExecutable(CLAUDE, None, "not_found"),
        ResolvedExecutable(CLAUDE, None, "executable_not_supported"),
    ],
    ids=["not found", "not an exe"],
)
def test_unrunnable_executables_are_never_retried(tmp_path: Path, failure: ResolvedExecutable) -> None:
    runner = FakeRunner(claude_ok())
    provider, _logs, _made = _provider(runner, tmp_path, executables=_executables(claude=failure))
    result = provider.call(_request(), CLAUDE)
    assert (result.outcome, len(runner.calls), result.retried) == (failure.failure, 0, False)


@pytest.mark.parametrize("response", [FAILED, TIMED_OUT], ids=["failed", "timeout"])
def test_a_failed_first_run_goes_to_the_fallback_without_a_retry(tmp_path: Path, response: ProcessResult) -> None:
    runner = FakeRunner(response, codex_ok())
    provider, logs, _made = _provider(runner, tmp_path, settings=_settings(fallback_provider=CODEX))
    result = provider.call(_request(), CLAUDE)
    assert (result.provider, result.used_fallback, result.retried, len(runner.calls)) == (CODEX, True, False, 2)
    assert logs[-1] == "llm codex: ok after 0 s (gpt-6.1-sol)"  # v2.5 Codex default model


def test_the_fallback_provider_follows_a_failed_retry_and_runs_at_most_four_times(tmp_path: Path) -> None:
    settings = _settings(fallback_provider=CODEX, codex=ProviderSettings("mini", None, None, "big"))
    runner = FakeRunner(claude_text("x"), claude_text("y"), BAD_CODEX, BAD_CODEX)
    provider, logs, made = _provider(runner, tmp_path, settings=settings)
    result = provider.call(_request(), CLAUDE)
    assert (result.outcome, result.provider, result.model, result.used_fallback) == ("bad_output", CODEX, "big", True)
    assert [(a.provider, a.model, a.retry) for a in result.attempts] == [
        (CLAUDE, "haiku", False),
        (CLAUDE, "sonnet", True),
        (CODEX, "mini", False),
        (CODEX, "big", True),
    ]
    assert len(runner.calls) == 4 and len(made) == 4 and not any(path.exists() for path in made)
    assert "llm claude: bad output after 0 s (sonnet, retry); trying fallback codex" in logs


def test_a_timeout_on_the_retry_goes_to_the_fallback(tmp_path: Path) -> None:
    runner = FakeRunner(claude_text("x"), TIMED_OUT, codex_ok())
    provider, logs, _made = _provider(runner, tmp_path, settings=_settings(fallback_provider=CODEX))
    result = provider.call(_request(), CLAUDE)
    assert (result.outcome, result.provider, result.used_fallback) == ("ok", CODEX, True)
    assert logs == [
        "llm claude: bad output after 0 s (haiku)",
        "llm claude: timeout after 0 s (sonnet, retry)",
        "llm claude: timeout after 0 s (sonnet, retry); trying fallback codex",
        "llm codex: ok after 0 s (gpt-6.1-sol)",  # v2.5 Codex default model
    ]


def test_console_lines_are_ascii_without_message_text(tmp_path: Path) -> None:
    runner = FakeRunner(claude_text("secret answer"), FAILED)
    provider, logs, _made = _provider(runner, tmp_path)
    provider.call(_request(), CLAUDE)
    assert logs == ["llm claude: bad output after 0 s (haiku)", "llm claude: failed (exit 1) after 0 s (sonnet, retry)"]
    joined = "".join(logs)
    assert joined.isascii() and "secret" not in joined and "닭가슴살" not in joined and "login" not in joined


def test_every_run_gets_the_full_timeout(tmp_path: Path) -> None:
    runner = FakeRunner(claude_text("x"), claude_ok())
    provider, _logs, _made = _provider(runner, tmp_path, settings=_settings(timeout_seconds=45))
    provider.call(_request(), CLAUDE)
    assert [call.timeout_s for call in runner.calls] == [45, 45]


# --- the bot with the real provider and a fake runner (AC1, AC3) -------------------------------------------


def _real_session(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    runner: FakeRunner,
    tmp_path: Path,
    *updates: Any,
) -> tuple[list[str], str, Any]:
    fake = bot.FakeApi(list(updates))
    counter = iter(range(100))

    def make_temp_dir() -> str:
        path = tmp_path / "llm-temp" / f"{TEMP_PREFIX}{next(counter)}"
        path.mkdir(parents=True)
        return str(path)

    def factory(settings: LlmSettings, executables: Any, log: Any) -> CliLlmProvider:
        return CliLlmProvider(
            settings,
            executables,
            runner,
            log=log,
            environ={"PATH": "x"},
            make_temp_dir=make_temp_dir,
            clock=lambda: 0.0,
        )

    monkeypatch.setattr(cli, "_llm_provider", factory)
    v1._install(monkeypatch, fake)
    code = main(["telegram", "run"])
    captured = capsys.readouterr()
    assert code == 130, captured.err
    assert captured.out == ""
    assert not list((tmp_path / "llm-temp").glob("*"))  # every run's temp folder was removed
    return [bot._plain(message) for _, message in fake.sent], captured.err, fake


def test_bot_text_uses_haiku_and_a_photo_sonnet(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path, tmp_path: Path
) -> None:
    bot._llm_config(home, {"keep_photos": False})
    chat = interpretation(intent="chat", items=[], reply="네.")
    runner = FakeRunner(claude_ok(chat), claude_ok(bot._photo_meal()))
    replies, _err, _fake = _real_session(
        monkeypatch, capsys, runner, tmp_path, bot.text(1, "안녕"), bot.photo(2, "저녁")
    )
    assert replies[0] == "네." and "제육볶음 정식" in replies[1]
    assert [_model(call.argv) for call in runner.calls] == ["haiku", "sonnet"]
    assert [entry["model"] for entry in bot._history(home)] == ["haiku", "sonnet"]
    assert [entry["retried"] for entry in bot._history(home)] == [False, False]


def test_bot_bad_output_then_a_good_meal_gives_the_normal_proposal(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path, tmp_path: Path
) -> None:
    bot._catalog(capsys)
    bot._llm_config(home)
    runner = FakeRunner(claude_text("not json"), claude_ok(bot.LUNCH_MEAL))
    replies, err, _fake = _real_session(monkeypatch, capsys, runner, tmp_path, bot.text(1, "점심에 닭가슴살이랑 햇반"))
    assert replies == [bot.LUNCH_PROPOSAL]
    assert [_model(call.argv) for call in runner.calls] == ["haiku", "sonnet"]
    entry = bot._history(home)[0]
    assert (entry["provider"], entry["model"], entry["provider_result"], entry["retried"]) == (
        "claude",
        "sonnet",
        "ok",
        True,
    )
    assert entry["attempts"] == [
        {"provider": "claude", "model": "haiku", "outcome": "bad_output", "retry": False},
        {"provider": "claude", "model": "sonnet", "outcome": "ok", "retry": True},
    ]
    assert list(entry) == list(HISTORY_KEYS)
    assert "llm claude: bad output after 0 s (haiku)" in err and "llm claude: ok after 0 s (sonnet, retry)" in err
    assert "닭가슴살" not in err


def test_bot_two_format_failures_write_nothing_and_say_so(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path, tmp_path: Path
) -> None:
    bot._catalog(capsys)
    bot._llm_config(home)
    before = bot._tables(home)
    runner = FakeRunner(claude_text("x"), claude_text("y"))
    replies, _err, _fake = _real_session(monkeypatch, capsys, runner, tmp_path, bot.text(1, "점심"))
    assert replies == [f"{PROVIDER_FAILED_TEXT}\n{retry_line('7f3a')}"]  # v2.5: the one-tap retry
    assert bot._tables(home) == before
    assert [proposal.kind for proposal in _proposals(home)] == [ProposalKind.RETRY]
    entry = bot._history(home)[0]
    assert (entry["provider_result"], entry["retried"], len(entry["attempts"])) == ("bad_output", True, 2)


def test_bot_photo_failing_twice_offers_the_plain_general_meal(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path, tmp_path: Path
) -> None:
    bot._llm_config(home, {"keep_photos": False, "claude": {"photo_model": "opus"}})
    runner = FakeRunner(claude_text("x"), claude_text("y"))
    # v2.4: the plain general meal is offered only when the caption says it was eaten (the twin below has no caption).
    replies, _err, _fake = _real_session(monkeypatch, capsys, runner, tmp_path, bot.photo(1, "점심 먹었어"))
    assert replies == [
        "\n".join(
            [
                "사진을 해석하지 못했습니다. 일반식으로만 기록할까요? (점심, 10-06)",
                "(끼니: 지금 시각 기준)",
                "1. 일반식",
                "기록: /ok_7f3a   취소: /no_7f3a",
            ]
        )
    ]
    assert [_model(call.argv) for call in runner.calls] == ["opus", "sonnet"]


def test_bot_photo_failing_twice_without_a_clear_caption_offers_nothing(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path, tmp_path: Path
) -> None:
    bot._llm_config(home, {"keep_photos": False, "claude": {"photo_model": "opus"}})
    runner = FakeRunner(claude_text("x"), claude_text("y"))
    replies, _err, _fake = _real_session(monkeypatch, capsys, runner, tmp_path, bot.photo(1))
    assert replies == [
        '사진을 해석하지 못했습니다. 사진에 "메뉴" 또는 "먹음"이라고 적어 다시 보내 주세요.\n' + retry_line("7f3a")
    ]
    assert [_model(call.argv) for call in runner.calls] == ["opus", "sonnet"]
    assert [proposal.kind for proposal in _proposals(home)] == [ProposalKind.RETRY]  # no meal is offered


def test_a_two_call_message_records_only_the_last_call(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path, tmp_path: Path
) -> None:
    v1._seed_reads(capsys, home)
    bot._llm_config(home)
    answer = {"answer": "오늘 계획은 /today에 있어요.", "memory_summary": ""}
    runner = FakeRunner(claude_text("x"), claude_ok(bot._question("training")), claude_ok(answer))
    replies, _err, _fake = _real_session(monkeypatch, capsys, runner, tmp_path, bot.text(1, "오늘 뭐 운동해?"))
    assert replies == ["오늘 계획은 /today에 있어요.\n(근거: /today)"]
    assert [_model(call.argv) for call in runner.calls] == ["haiku", "sonnet", "haiku"]
    entry = bot._history(home)[0]
    # D2-A: the history describes the answer call; the retry of the interpret call is in the console log only.
    assert (entry["model"], entry["retried"]) == ("haiku", False)
    assert entry["attempts"] == [{"provider": "claude", "model": "haiku", "outcome": "ok", "retry": False}]


def test_a_confirm_entry_has_null_routing_keys(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    bot._catalog(capsys)
    bot._llm_config(home)
    bot._session(monkeypatch, capsys, bot.FakeProvider(bot.LUNCH_MEAL), bot.text(1, "점심"))
    bot._session(monkeypatch, capsys, bot.FakeProvider(), bot.text(2, "/ok_7f3a"))
    meal_entry, confirm = bot._history(home)
    assert list(confirm) == list(HISTORY_KEYS) and confirm["kind"] == "confirm"
    assert (confirm["retried"], confirm["attempts"]) == (None, None)
    assert (meal_entry["retried"], len(meal_entry["attempts"])) == (False, 1)


# --- /llm (AC7) -------------------------------------------------------------------------------------------------


def _llm_line(provider: str, text: str, photo: str, retry: str, fallback: str, timeout: int) -> str:
    return (
        f"LLM: {provider} · 글 {text} · 사진 {photo} · 형식 실패 시 재시도: {retry} · "
        f"대체 제공자: {fallback} · 시간 상한 {timeout}초"
    )


DEFAULT_LINE = (
    "LLM: claude · 글 haiku · 사진 sonnet · 형식 실패 시 재시도: sonnet (글만) · 대체 제공자: 없음 · 시간 상한 90초"
)


@pytest.mark.parametrize(
    ("config", "expected"),
    [
        ({}, DEFAULT_LINE),
        (
            {"provider": "codex"},  # v2.5 Codex default models
            _llm_line("codex", "gpt-6.1-sol", "gpt-6.1-sol", "없음", "없음", 90),
        ),
        (
            {"claude": {"model": "sonnet"}},
            _llm_line("claude", "sonnet", "sonnet", "없음", "없음", 90),
        ),
        (
            {"claude": {"retry_model": None}},
            _llm_line("claude", "haiku", "sonnet", "없음", "없음", 90),
        ),
        (
            {"claude": {"retry_model": "haiku"}},
            _llm_line("claude", "haiku", "sonnet", "haiku (사진만)", "없음", 90),
        ),
        (
            {"claude": {"photo_model": "opus"}},
            _llm_line("claude", "haiku", "opus", "sonnet", "없음", 90),
        ),
        (
            {"claude": {"model": None}},
            _llm_line("claude", "기본", "sonnet", "sonnet (글만)", "없음", 90),
        ),
        (
            {"fallback_provider": "codex", "timeout_seconds": 30},
            _llm_line("claude", "haiku", "sonnet", "sonnet (글만)", "codex", 30),
        ),
    ],
    ids=["defaults", "codex", "v2 equivalent", "retry null", "photo-only retry", "both", "model null", "fallback"],
)
def test_llm_first_line_shows_the_effective_models(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    home: Path,
    config: dict[str, Any],
    expected: str,
) -> None:
    bot._llm_config(home, config)
    replies, _err, _fake = bot._session(monkeypatch, capsys, bot.FakeProvider(), bot.text(1, "/llm"))
    first, second = replies[0].split("\n")
    assert first == expected
    other = "claude" if config.get("provider") == "codex" else "codex"
    assert second == f"바꾸기: /llm {other} · 설정 파일로 되돌리기: /llm default"


def test_llm_with_an_override_describes_the_active_provider_and_the_other_lines_are_unchanged(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    bot._llm_config(home, {"codex": {"model": "gpt-5.5"}})
    replies, _err, _fake = bot._session(
        monkeypatch,
        capsys,
        bot.FakeProvider(),
        bot.text(1, "/llm codex"),
        bot.text(2, "/llm"),
        bot.text(3, "/llm default"),
        bot.text(4, "/llm gemini"),
    )
    assert replies[0] == "다음 메시지부터 codex(OpenAI)로 보냅니다. 메시지와 사진이 OpenAI로 전송됩니다."
    assert replies[1] == (
        # v2.5: `photo_model` keeps its own default (gpt-6.1-sol) when only `model` is set, as for Claude.
        "LLM: codex · 글 gpt-5.5 · 사진 gpt-6.1-sol · 형식 실패 시 재시도: 없음 · 대체 제공자: 없음 · 시간 상한 90초\n"
        "(채팅에서 바꿈, 설정 파일: claude)"
    )
    assert replies[2] == "설정 파일의 제공자로 되돌렸습니다: claude(Anthropic)."
    assert replies[3].startswith("사용법: /llm")


# --- history keys and rendering (AC7) --------------------------------------------------------------------------


def test_history_key_shapes_are_16_18_20_and_22() -> None:
    assert len(HISTORY_KEYS_V1) == 16
    assert (*HISTORY_KEYS_V1, "retried", "attempts") == HISTORY_KEYS_V21 and len(HISTORY_KEYS_V21) == 18
    assert (*HISTORY_KEYS_V21, "web_searches", "recheck") == HISTORY_KEYS_V22 and len(HISTORY_KEYS_V22) == 20
    # v2.5 adds the failure reason and the retry token at the end.
    assert (*HISTORY_KEYS_V22, "failure_reason", "retry_of") == HISTORY_KEYS and len(HISTORY_KEYS) == 22
    entry = history_entry(update_id=1, at="2026-10-13T12:00:00+09:00", chat_id=1, kind="plain")
    assert list(entry) == list(HISTORY_KEYS)
    assert (entry["retried"], entry["attempts"], entry["web_searches"], entry["recheck"]) == (None,) * 4


def test_check_history_entry_accepts_all_three_shapes_and_rejects_others() -> None:
    new = history_entry(update_id=1, at="2026-10-13T12:00:00+09:00", chat_id=1, kind="text", text="a")
    v21 = {key: new[key] for key in HISTORY_KEYS_V21}
    old = {key: new[key] for key in HISTORY_KEYS_V1}
    assert check_history_entry(old) is old and check_history_entry(v21) is v21 and check_history_entry(new) is new
    attempt = {"provider": "claude", "model": "haiku", "outcome": "ok", "retry": False}
    assert check_history_entry({**new, "retried": True, "attempts": [attempt, {**attempt, "retry": True}]})
    searched = {**new, "web_searches": 2, "recheck": {"reasons": ["macros_vs_kcal"], "outcome": "fixed"}}
    assert check_history_entry(searched) is searched
    assert check_history_entry({**new, "web_searches": 0, "recheck": {"reasons": [], "outcome": "reask_failed"}})
    bad = [
        {**new, "extra": 1},
        {key: value for key, value in new.items() if key != "attempts"},
        {key: value for key, value in new.items() if key != "recheck"},
        {**new, "retried": "yes"},
        {**new, "attempts": "x"},
        {**new, "attempts": [{"provider": "claude"}]},
        {**new, "attempts": [{**attempt, "retry": "no"}]},
        {**new, "attempts": [[1, 2]]},
        {**new, "web_searches": -1},
        {**new, "web_searches": True},
        {**new, "web_searches": "2"},
        {**new, "web_searches": 1.5},
        {**new, "recheck": "fixed"},
        {**new, "recheck": {"reasons": [], "outcome": "maybe"}},
        {**new, "recheck": {"reasons": ["made_up"], "outcome": "fixed"}},
        {**new, "recheck": {"reasons": "macros_vs_kcal", "outcome": "fixed"}},
        {**new, "recheck": {"outcome": "fixed", "reasons": []}},
        {**new, "recheck": {"reasons": [], "outcome": "fixed", "extra": 1}},
    ]
    for document in bad:
        with pytest.raises(ValueError):
            check_history_entry(document)


def _entry(**fields: Any) -> dict[str, Any]:
    base: dict[str, Any] = {"update_id": 5601, "at": "2026-10-13T12:40:11+09:00", "chat_id": 111, "kind": "text"}
    return history_entry(**{**base, **fields})


def _attempts(*items: tuple[str, str | None, str, bool]) -> list[dict[str, Any]]:
    return [{"provider": p, "model": m, "outcome": o, "retry": r} for p, m, o, r in items]


def test_history_text_shows_retry_and_fallback_chains_and_leaves_plain_entries_alone() -> None:
    plain = _entry(intent="chat", provider="claude", model="sonnet", provider_result="ok", reply="a")
    plain_one = _entry(
        intent="chat",
        provider="claude",
        model="sonnet",
        provider_result="ok",
        reply="a",
        retried=False,
        attempts=_attempts(("claude", "sonnet", "ok", False)),
    )
    retried = _entry(
        intent="meal_log",
        provider="claude",
        model="sonnet",
        provider_result="ok",
        proposal="7f3a",
        retried=True,
        attempts=_attempts(("claude", "haiku", "bad_output", False), ("claude", "sonnet", "ok", True)),
    )
    fallback = _entry(
        intent="chat",
        provider="codex",
        model=None,
        provider_result="ok",
        retried=False,
        attempts=_attempts(("claude", "sonnet", "timeout", False), ("codex", None, "ok", False)),
    )
    lines = render_telegram_history([plain, plain_one, retried, fallback]).split("\n")
    heads = [line for line in lines if not line.startswith(" ")]
    assert heads == [
        "2026-10-13 12:40 +09:00 chat 111 text intent=chat claude/sonnet ok",
        "2026-10-13 12:40 +09:00 chat 111 text intent=chat claude/sonnet ok",
        MEAL_RETRY_HEAD,
        "2026-10-13 12:40 +09:00 chat 111 text intent=chat claude/sonnet timeout -> fallback codex/default ok",
    ]
    assert render_telegram_history([plain]) == render_telegram_history([plain_one])
    korean = history_text([plain, retried, fallback])
    assert "claude sonnet\n" in korean.split("\n\n")[0] + "\n"
    assert "식사 기록 · claude sonnet (재시도, 처음 haiku 형식 실패)\n" in korean.split("\n\n")[1] + "\n"
    assert korean.split("\n\n")[2].split("\n")[0].endswith("codex 기본")
    assert "재시도" not in history_text([plain, plain_one, fallback])


MEAL_RETRY_HEAD = (
    "2026-10-13 12:40 +09:00 chat 111 text intent=meal_log "
    "claude/haiku bad_output -> retry claude/sonnet ok proposal=7f3a"
)
OLD_LINE = (
    '{"v": 1, "update_id": 5512, "at": "2026-10-12T21:00:00+09:00", "chat_id": 111, "kind": "text", '
    '"text": "\\uc548\\ub155", "caption": null, "photo": null, "intent": "chat", "provider": "claude", '
    '"model": "sonnet", "provider_result": "ok", "llm_output": null, "reply": "\\ubc18\\uac00\\uc6cc\\uc694.", '
    '"proposal": null, "result": null}'
)


def test_old_16_key_lines_are_read_and_printed_as_stored(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], home: Path
) -> None:
    directory = home / "telegram" / "history"
    directory.mkdir(parents=True)
    (directory / "2026-10.jsonl").write_text(OLD_LINE + "\n", encoding="utf-8", newline="\n")
    new = _entry(
        update_id=5601,
        intent="meal_log",
        provider="claude",
        model="sonnet",
        provider_result="ok",
        reply="이렇게 기록할까요?",
        proposal="7f3a",
        retried=True,
        attempts=_attempts(("claude", "haiku", "bad_output", False), ("claude", "sonnet", "ok", True)),
    )
    JsonlHistoryLog(directory).append(new)

    code, out, err = v1._cli(capsys, "telegram", "history", "--json")
    assert (code, err) == (0, "")
    entries = json.loads(out)["entries"]
    assert entries[0] == json.loads(OLD_LINE) and list(entries[0]) == list(HISTORY_KEYS_V1)
    assert entries[1] == new and list(entries[1]) == list(HISTORY_KEYS)
    assert out == json.dumps({"entries": [json.loads(OLD_LINE), new]}, indent=2, ensure_ascii=True) + "\n"

    code, out, err = v1._cli(capsys, "telegram", "history")
    assert (code, err) == (0, "") and out.split("\n") == [
        "2026-10-12 21:00 +09:00 chat 111 text intent=chat claude/sonnet ok",
        "  user: 안녕",
        "  bot: 반가워요.",
        MEAL_RETRY_HEAD,
        "  user: ",
        "  bot: 이렇게 기록할까요?",
        "",
    ]

    bot._llm_config(home)
    replies, _err, _fake = bot._session(monkeypatch, capsys, bot.FakeProvider(), bot.text(1, "/history"))
    assert replies[0].startswith("10-12 21:00 문장 · 잡담 · claude sonnet\n나: 안녕\nbot: 반가워요.")
    assert "claude sonnet (재시도, 처음 haiku 형식 실패)" in replies[0]


def test_the_isolation_argv_is_unchanged_by_the_retry(tmp_path: Path) -> None:
    runner = FakeRunner(claude_text("x"), claude_ok())
    provider, _logs, _made = _provider(runner, tmp_path)
    provider.call(_request(), CLAUDE)
    for call in runner.calls:
        assert call.argv[: len(argv_tests.EXPECTED_CLAUDE) + 1] == (CLAUDE_EXE, *argv_tests.EXPECTED_CLAUDE)
        assert call.argv[-4] == "--system-prompt" and call.argv[-3] == CLAUDE_SYSTEM_PROMPT
        assert call.stdin is not None and call.env == {"PATH": "x"}


def test_request_type_is_reused_unchanged() -> None:
    # v2.2 added two optional fields at the end (web_search, pin), v2.4 one more (extra_photos, for albums) and v2.5
    # one more (strong_model, for open-proposal edits); the four original ones are unchanged.
    assert list(LlmRequest.__dataclass_fields__) == [
        *("prompt", "schema", "photo", "validate", "web_search", "pin", "extra_photos", "strong_model")
    ]
    request = LlmRequest("p", SchemaName.ANSWER, None, lambda document: document)
    assert (request.web_search, request.pin, request.extra_photos) == (False, None, ())
