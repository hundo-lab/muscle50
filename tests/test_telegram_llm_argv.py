"""Telegram LLM v2 provider execution: pinned isolation argv, temp cwd, stdin-only prompts, env scrub,
timeouts, process-tree kill, fallback and output parsing. Never runs the real `claude` or `codex`."""

from __future__ import annotations

import base64
import json
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import pytest

from muscle50.application.llm_provider import LlmRequest, SchemaName
from muscle50.domain.llm_settings import DEFAULT_SETTINGS, LlmSettings, ProviderName, ProviderSettings
from muscle50.infrastructure.llm import process as process_module
from muscle50.infrastructure.llm.argv import (
    CLAUDE_ISOLATION_ARGV,
    CLAUDE_SYSTEM_PROMPT,
    CODEX_ISOLATION_ARGV,
    claude_argv,
    codex_argv,
)
from muscle50.infrastructure.llm.executables import ResolvedExecutable, resolve_executable
from muscle50.infrastructure.llm.process import ProcessResult, SubprocessRunner, child_environment
from muscle50.infrastructure.llm.provider import TEMP_PREFIX, CliLlmProvider, load_schema

REPO = Path(__file__).resolve().parents[1]
CLAUDE_EXE = r"C:\Tools\claude.exe"
CODEX_EXE = r"C:\Tools\codex.exe"
PROMPT = "[메시지]\n점심에 닭가슴살 먹었어 (persona 머슬, memory 61 g)"
PHOTO = b"\xff\xd8\xff\xe0synthetic-jpeg"
DOCUMENT = {"answer": "ok", "memory_summary": ""}

EXPECTED_CLAUDE = (
    "-p",
    "--tools",
    "",
    "--safe-mode",
    "--strict-mcp-config",
    "--disable-slash-commands",
    "--no-session-persistence",
    "--input-format",
    "stream-json",
    "--output-format",
    "stream-json",
    "--verbose",
)
EXPECTED_CODEX = (
    "exec",
    "--skip-git-repo-check",
    "--ephemeral",
    "-s",
    "read-only",
    "--ignore-user-config",
    "--ignore-rules",
    "-c",
    'web_search="disabled"',
    *(
        item
        for feature in (
            "shell_tool",
            "unified_exec",
            "code_mode_host",
            "computer_use",
            "browser_use",
            "browser_use_external",
            "in_app_browser",
            "apps",
            "plugins",
            "multi_agent",
            "image_generation",
            "hooks",
            "tool_suggest",
            "skill_search",
            "goals",
            "sleep_tool",
            "view_image",
        )
        for item in ("--disable", feature)
    ),
)


def test_isolation_argv_tuples_are_pinned() -> None:
    assert CLAUDE_ISOLATION_ARGV == EXPECTED_CLAUDE
    assert CODEX_ISOLATION_ARGV == EXPECTED_CODEX
    assert "--bare" not in CLAUDE_ISOLATION_ARGV
    assert CLAUDE_SYSTEM_PROMPT.isascii()


def test_claude_argv_with_and_without_model() -> None:
    schema = load_schema(SchemaName.ANSWER)
    compact = json.dumps(schema, separators=(",", ":"))
    tail = ("--system-prompt", CLAUDE_SYSTEM_PROMPT, "--json-schema", compact)
    assert claude_argv("claude.exe", "sonnet", schema) == ("claude.exe", *EXPECTED_CLAUDE, "--model", "sonnet", *tail)
    assert claude_argv("claude.exe", None, schema) == ("claude.exe", *EXPECTED_CLAUDE, *tail)


def test_codex_argv_with_and_without_model_and_photo(tmp_path: Path) -> None:
    schema, output, work, photo = tmp_path / "s", tmp_path / "o", tmp_path / "w", tmp_path / "w" / "photo.jpg"
    files = ("--output-schema", str(schema), "-o", str(output), "-C", str(work))
    plain = codex_argv("codex.exe", None, schema_path=schema, output_path=output, work_dir=work, photo_path=None)
    assert plain == ("codex.exe", *EXPECTED_CODEX, *files, "-")
    with_photo = codex_argv(
        "codex.exe", "gpt-5", schema_path=schema, output_path=output, work_dir=work, photo_path=photo
    )
    assert with_photo == ("codex.exe", *EXPECTED_CODEX, *files, "-m", "gpt-5", "-", "-i", str(photo))


@dataclass
class Call:
    argv: tuple[str, ...]
    cwd: Path
    stdin: bytes | None
    timeout_s: float
    env: dict[str, str]
    cwd_files: list[str]
    io_files: list[str]


Responder = Callable[[Sequence[str], Path], ProcessResult]


class FakeRunner:
    def __init__(self, *responses: ProcessResult | Responder | BaseException) -> None:
        self.responses = list(responses)
        self.calls: list[Call] = []

    def run(
        self, argv: Sequence[str], *, cwd: Path, stdin: bytes | None, timeout_s: float, env: Mapping[str, str]
    ) -> ProcessResult:
        io = cwd.parent / "io"
        self.calls.append(
            Call(
                tuple(argv),
                cwd,
                stdin,
                timeout_s,
                dict(env),
                sorted(path.name for path in cwd.iterdir()),
                sorted(path.name for path in io.iterdir()) if io.exists() else [],
            )
        )
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        if callable(response):
            return response(argv, cwd)
        return response


def claude_ok(document: Any = DOCUMENT, *, structured: bool = True) -> ProcessResult:
    result: dict[str, Any] = {"type": "result", "subtype": "success", "is_error": False, "result": json.dumps(document)}
    if structured:
        result["structured_output"] = document
    lines = [{"type": "system", "subtype": "init", "tools": ["StructuredOutput"]}, result]
    return ProcessResult(0, "\n".join(json.dumps(line) for line in lines).encode(), b"", False)


def codex_ok(document: Any = DOCUMENT) -> Responder:
    def respond(argv: Sequence[str], cwd: Path) -> ProcessResult:
        Path(argv[list(argv).index("-o") + 1]).write_text(json.dumps(document), encoding="utf-8")
        return ProcessResult(0, b"", b"", False)

    return respond


FAILED = ProcessResult(1, b"", b"login required", False)
TIMED_OUT = ProcessResult(None, b"", b"", True)


def _executables(**overrides: ResolvedExecutable) -> dict[ProviderName, ResolvedExecutable]:
    resolved = {
        ProviderName.CLAUDE: ResolvedExecutable(ProviderName.CLAUDE, CLAUDE_EXE, None),
        ProviderName.CODEX: ResolvedExecutable(ProviderName.CODEX, CODEX_EXE, None),
    }
    resolved.update({ProviderName(name): value for name, value in overrides.items()})
    return resolved


def _provider(
    runner: FakeRunner,
    tmp_path: Path,
    *,
    settings: LlmSettings = DEFAULT_SETTINGS,
    executables: dict[ProviderName, ResolvedExecutable] | None = None,
    environ: Mapping[str, str] | None = None,
) -> tuple[CliLlmProvider, list[str], list[Path]]:
    logs: list[str] = []
    made: list[Path] = []

    def make_temp_dir() -> str:
        path = tmp_path / "temp" / f"{TEMP_PREFIX}{len(made)}"
        path.mkdir(parents=True)
        made.append(path)
        return str(path)

    provider = CliLlmProvider(
        settings,
        executables if executables is not None else _executables(),
        runner,
        log=logs.append,
        environ=environ if environ is not None else {"PATH": "x"},
        make_temp_dir=make_temp_dir,
        clock=lambda: 0.0,
    )
    return provider, logs, made


def _request(photo: bytes | None = None, validate: Callable[[Any], Any] = lambda document: document) -> LlmRequest:
    return LlmRequest(PROMPT, SchemaName.ANSWER, photo, validate)


def test_claude_call_uses_stdin_stream_json_and_an_empty_temp_cwd(tmp_path: Path) -> None:
    runner = FakeRunner(claude_ok())
    provider, logs, made = _provider(runner, tmp_path)
    result = provider.call(_request(PHOTO), ProviderName.CLAUDE)
    assert (result.outcome, result.document, result.used_fallback) == ("ok", DOCUMENT, False)
    call = runner.calls[0]
    assert call.argv == claude_argv(CLAUDE_EXE, "sonnet", load_schema(SchemaName.ANSWER))
    assert call.cwd == made[0] / "work" and call.cwd_files == [] and call.io_files == []
    assert REPO not in call.cwd.parents
    assert call.timeout_s == 90
    assert call.stdin is not None
    message = json.loads(call.stdin.decode("ascii"))
    assert message["type"] == "user"
    text, image = message["message"]["content"]
    assert text == {"type": "text", "text": PROMPT}
    assert image["source"] == {"type": "base64", "media_type": "image/jpeg", "data": base64.b64encode(PHOTO).decode()}
    assert not any("닭가슴살" in item or "머슬" in item or "61 g" in item for item in call.argv)
    assert not made[0].exists()
    assert logs == ["llm claude: ok after 0 s (sonnet)"]


def test_codex_call_puts_only_the_photo_in_its_cwd_and_the_prompt_on_stdin(tmp_path: Path) -> None:
    runner = FakeRunner(codex_ok())
    provider, _logs, made = _provider(runner, tmp_path)
    result = provider.call(_request(PHOTO), ProviderName.CODEX)
    assert result.outcome == "ok" and result.model is None
    call = runner.calls[0]
    work, io = made[0] / "work", made[0] / "io"
    assert call.cwd == work and call.cwd_files == ["photo.jpg"] and call.io_files == ["schema.json"]
    assert call.argv == codex_argv(
        CODEX_EXE,
        None,
        schema_path=io / "schema.json",
        output_path=io / "last.json",
        work_dir=work,
        photo_path=work / "photo.jpg",
    )
    assert call.argv[-3:] == ("-", "-i", str(work / "photo.jpg"))
    assert call.stdin == PROMPT.encode("utf-8")
    assert not any("닭가슴살" in item for item in call.argv)
    assert not made[0].exists()


def test_text_only_codex_call_has_no_photo(tmp_path: Path) -> None:
    runner = FakeRunner(codex_ok())
    provider, _logs, _made = _provider(runner, tmp_path)
    provider.call(_request(), ProviderName.CODEX)
    assert runner.calls[0].cwd_files == [] and "-i" not in runner.calls[0].argv


def test_child_environment_drops_api_keys_and_muscle50_settings() -> None:
    environ = {
        "PATH": "p",
        "USERPROFILE": "u",
        "ANTHROPIC_API_KEY": "k",
        "ANTHROPIC_AUTH_TOKEN": "k",
        "OPENAI_API_KEY": "k",
        "codex_api_key": "k",
        "MUSCLE50_HOME": "h",
    }
    assert child_environment(environ) == {"PATH": "p", "USERPROFILE": "u"}


def test_provider_passes_the_scrubbed_environment(tmp_path: Path) -> None:
    runner = FakeRunner(claude_ok())
    provider, _logs, _made = _provider(
        runner, tmp_path, environ={"PATH": "p", "OPENAI_API_KEY": "k", "MUSCLE50_HOME": "h"}
    )
    provider.call(_request(), ProviderName.CLAUDE)
    assert runner.calls[0].env == {"PATH": "p"}


def test_claude_result_text_is_parsed_when_there_is_no_structured_output(tmp_path: Path) -> None:
    runner = FakeRunner(claude_ok(structured=False))
    provider, _logs, _made = _provider(runner, tmp_path)
    assert provider.call(_request(), ProviderName.CLAUDE).document == DOCUMENT


@pytest.mark.parametrize(
    ("response", "outcome", "log"),
    [
        (FAILED, "failed", "llm claude: failed (exit 1) after 0 s (haiku)"),
        (TIMED_OUT, "timeout", "llm claude: timeout after 0 s (haiku)"),
        (ProcessResult(0, b"not json\n", b"", False), "bad_output", "llm claude: bad output after 0 s (haiku)"),
        (
            ProcessResult(0, json.dumps({"type": "result", "subtype": "error_max_turns"}).encode(), b"", False),
            "bad_output",
            "llm claude: bad output after 0 s (haiku)",
        ),
    ],
)
def test_claude_failures_are_reported_without_output_text(
    tmp_path: Path, response: ProcessResult, outcome: str, log: str
) -> None:
    runner = FakeRunner(response)
    provider, logs, made = _provider(runner, tmp_path)
    result = provider.call(_request(), ProviderName.CLAUDE)
    assert (result.outcome, result.document) == (outcome, None)
    assert logs == [log]
    assert "login required" not in "".join(logs)
    assert not made[0].exists()


def test_invalid_document_is_bad_output(tmp_path: Path) -> None:
    def reject(document: Any) -> Any:
        raise ValueError("nope")

    runner = FakeRunner(codex_ok())
    provider, _logs, _made = _provider(runner, tmp_path)
    assert provider.call(_request(validate=reject), ProviderName.CODEX).outcome == "bad_output"


def test_codex_without_output_file_is_bad_output(tmp_path: Path) -> None:
    runner = FakeRunner(ProcessResult(0, b"", b"", False))
    provider, _logs, _made = _provider(runner, tmp_path)
    assert provider.call(_request(), ProviderName.CODEX).outcome == "bad_output"


def test_fallback_off_calls_only_the_chosen_provider(tmp_path: Path) -> None:
    runner = FakeRunner(FAILED)
    provider, _logs, _made = _provider(runner, tmp_path)
    result = provider.call(_request(), ProviderName.CLAUDE)
    assert (result.outcome, result.used_fallback, len(runner.calls)) == ("failed", False, 1)


def test_fallback_on_tries_the_other_provider_once(tmp_path: Path) -> None:
    settings = replace(DEFAULT_SETTINGS, fallback_provider=ProviderName.CODEX)
    runner = FakeRunner(TIMED_OUT, codex_ok())
    provider, logs, made = _provider(runner, tmp_path, settings=settings)
    result = provider.call(_request(), ProviderName.CLAUDE)
    assert (result.outcome, result.provider, result.used_fallback) == ("ok", ProviderName.CODEX, True)
    assert [attempt.outcome for attempt in result.attempts] == ["timeout", "ok"]
    assert runner.calls[0].argv[0] == CLAUDE_EXE and runner.calls[1].argv[0] == CODEX_EXE
    assert logs[1] == "llm claude: timeout after 0 s (haiku); trying fallback codex"
    assert not any(path.exists() for path in made)


def test_both_providers_failing_is_a_failure(tmp_path: Path) -> None:
    settings = replace(DEFAULT_SETTINGS, fallback_provider=ProviderName.CLAUDE)
    runner = FakeRunner(FAILED, FAILED)
    provider, _logs, _made = _provider(runner, tmp_path, settings=settings)
    result = provider.call(_request(), ProviderName.CODEX)
    assert (result.outcome, result.provider, result.used_fallback, len(runner.calls)) == (
        "failed",
        ProviderName.CLAUDE,
        True,
        2,
    )


def test_fallback_equal_to_the_active_provider_is_not_tried_twice(tmp_path: Path) -> None:
    settings = replace(DEFAULT_SETTINGS, fallback_provider=ProviderName.CODEX)
    runner = FakeRunner(FAILED)
    provider, _logs, _made = _provider(runner, tmp_path, settings=settings)
    assert provider.call(_request(), ProviderName.CODEX).used_fallback is False
    assert len(runner.calls) == 1


def test_missing_or_unsupported_executable_is_never_run(tmp_path: Path) -> None:
    runner = FakeRunner()
    missing = ResolvedExecutable(ProviderName.CLAUDE, None, "not_found")
    provider, logs, _made = _provider(runner, tmp_path, executables=_executables(claude=missing))
    assert provider.call(_request(), ProviderName.CLAUDE).outcome == "not_found"
    shim = ResolvedExecutable(ProviderName.CODEX, None, "executable_not_supported")
    provider, logs, _made = _provider(runner, tmp_path / "b", executables=_executables(codex=shim))
    assert provider.call(_request(), ProviderName.CODEX).outcome == "executable_not_supported"
    assert runner.calls == []


def test_ctrl_c_during_a_call_still_removes_the_temp_folder(tmp_path: Path) -> None:
    runner = FakeRunner(KeyboardInterrupt())
    provider, _logs, made = _provider(runner, tmp_path)
    with pytest.raises(KeyboardInterrupt):
        provider.call(_request(), ProviderName.CLAUDE)
    assert not made[0].exists()


def test_model_is_left_out_when_null(tmp_path: Path) -> None:
    settings = replace(DEFAULT_SETTINGS, claude=ProviderSettings(None, None))
    runner = FakeRunner(claude_ok())
    provider, _logs, _made = _provider(runner, tmp_path, settings=settings)
    provider.call(_request(), ProviderName.CLAUDE)
    assert "--model" not in runner.calls[0].argv


# --- executables -------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("found", "windows", "expected"),
    [
        (r"C:\Users\x\.local\bin\claude.EXE", True, (r"C:\Users\x\.local\bin\claude.EXE", None)),
        (r"C:\Users\x\bin\claude.exe", True, (r"C:\Users\x\bin\claude.exe", None)),
        (r"C:\npm\claude.cmd", True, (None, "executable_not_supported")),
        (r"C:\npm\claude.ps1", True, (None, "executable_not_supported")),
        ("/usr/local/bin/claude", False, ("/usr/local/bin/claude", None)),
        (None, True, (None, "not_found")),
    ],
)
def test_executable_resolution(found: str | None, windows: bool, expected: tuple[str | None, str | None]) -> None:
    resolved = resolve_executable(
        ProviderName.CLAUDE, None, which=lambda name: found, is_file=lambda path: True, windows=windows
    )
    assert (resolved.path, resolved.failure) == expected


def test_configured_executable_wins_and_must_exist() -> None:
    def which(name: str) -> str:
        raise AssertionError("PATH must not be searched")

    configured = resolve_executable(
        ProviderName.CODEX, r"D:\codex\codex.exe", which=which, is_file=lambda path: True, windows=True
    )
    assert configured.path == r"D:\codex\codex.exe"
    absent = resolve_executable(ProviderName.CODEX, r"D:\x.exe", which=which, is_file=lambda path: False, windows=True)
    assert absent.failure == "not_found"
    assert "set codex.executable" in ResolvedExecutable(ProviderName.CODEX, None, "executable_not_supported").log_text()


# --- the real subprocess runner (with a harmless Python child, never a provider CLI) -----------------


def test_runner_uses_devnull_without_input_and_pipes_input(tmp_path: Path) -> None:
    script = "import sys; data = sys.stdin.buffer.read(); print(len(data))"
    runner = SubprocessRunner()
    env = {"PATH": "", "SYSTEMROOT": __import__("os").environ.get("SYSTEMROOT", "")}
    without = runner.run([sys.executable, "-c", script], cwd=tmp_path, stdin=None, timeout_s=30, env=env)
    assert (without.exit_code, without.stdout.strip(), without.timed_out) == (0, b"0", False)
    with_input = runner.run([sys.executable, "-c", script], cwd=tmp_path, stdin=b"abc", timeout_s=30, env=env)
    assert with_input.stdout.strip() == b"3"


def test_runner_kills_the_tree_on_timeout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    killed: list[int] = []
    original = process_module.kill_tree

    def spy(process: subprocess.Popen[bytes]) -> None:
        killed.append(process.pid)
        original(process)

    monkeypatch.setattr(process_module, "kill_tree", spy)
    env = {"PATH": "", "SYSTEMROOT": __import__("os").environ.get("SYSTEMROOT", "")}
    result = SubprocessRunner().run(
        [sys.executable, "-c", "import time; time.sleep(60)"], cwd=tmp_path, stdin=None, timeout_s=1, env=env
    )
    assert (result.timed_out, result.exit_code) == (True, None)
    assert len(killed) == 1


def test_runner_kills_the_tree_on_ctrl_c(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    killed: list[int] = []

    def kill(process: subprocess.Popen[bytes]) -> None:
        killed.append(process.pid)
        process.kill()

    monkeypatch.setattr(process_module, "kill_tree", kill)

    def interrupted(self: subprocess.Popen[bytes], *args: Any, **kwargs: Any) -> tuple[bytes, bytes]:
        if not killed:
            raise KeyboardInterrupt
        return b"", b""

    monkeypatch.setattr(subprocess.Popen, "communicate", interrupted)
    env = {"PATH": "", "SYSTEMROOT": __import__("os").environ.get("SYSTEMROOT", "")}
    with pytest.raises(KeyboardInterrupt):
        SubprocessRunner().run(
            [sys.executable, "-c", "import time; time.sleep(60)"], cwd=tmp_path, stdin=None, timeout_s=30, env=env
        )
    assert len(killed) == 1
