"""`LlmProvider` over the local `claude` and `codex` CLIs (Telegram LLM v2).

Each call runs in a fresh temp folder (`muscle50-llm-*`) with `work/` as the CLI's cwd and `io/`
(schema and output files) outside it; the folder is removed afterwards. Codex gets the photo as
`work/photo.<ext>` (the only file in its cwd) and `-i`; Claude gets it as a base64 image block in its
stream-json stdin, so its cwd stays empty. Only the outcome kind, exit code and duration are logged:
stdout and stderr are never logged or kept (they can contain the message and the answer).
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import time
from collections.abc import Callable, Mapping
from importlib.resources import files
from pathlib import Path
from typing import Any

from muscle50.application.llm_provider import (
    CallOutcome,
    LlmAttempt,
    LlmCallResult,
    LlmRequest,
    SchemaName,
)
from muscle50.domain.llm_settings import LlmSettings, ProviderName
from muscle50.infrastructure.llm.argv import claude_argv, claude_stdin, codex_argv, image_suffix
from muscle50.infrastructure.llm.executables import ResolvedExecutable
from muscle50.infrastructure.llm.process import ProcessResult, ProcessRunner, child_environment

TEMP_PREFIX = "muscle50-llm-"


def load_schema(name: SchemaName) -> dict[str, Any]:
    text = files("muscle50").joinpath("schemas", f"telegram_llm_{name.value}_v1.schema.json").read_text("utf-8")
    document = json.loads(text)
    if not isinstance(document, dict):
        raise ValueError(f"schema {name.value} is not a JSON object")
    return document


class CliLlmProvider:
    def __init__(
        self,
        settings: LlmSettings,
        executables: Mapping[ProviderName, ResolvedExecutable],
        runner: ProcessRunner,
        *,
        log: Callable[[str], None],
        environ: Mapping[str, str] | None = None,
        make_temp_dir: Callable[[], str] = lambda: tempfile.mkdtemp(prefix=TEMP_PREFIX),
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._settings = settings
        self._executables = executables
        self._runner = runner
        self._log = log
        self._environ = environ
        self._make_temp_dir = make_temp_dir
        self._clock = clock

    def call(self, request: LlmRequest, provider: ProviderName) -> LlmCallResult:
        attempts: list[LlmAttempt] = []
        order = [provider]
        fallback = self._settings.fallback_provider
        if fallback is not None and fallback is not provider:
            order.append(fallback)
        document: Any = None
        for index, name in enumerate(order):
            attempt, document = self._attempt(request, name)
            attempts.append(attempt)
            if attempt.outcome == "ok":
                break
            if index + 1 < len(order):
                self._log(f"llm {name.value}: {_describe(attempt)}; trying fallback {order[index + 1].value}")
        last = attempts[-1]
        return LlmCallResult(
            provider=last.provider,
            model=last.model,
            outcome=last.outcome,
            document=document if last.outcome == "ok" else None,
            seconds=sum(item.seconds for item in attempts),
            used_fallback=len(attempts) > 1,
            attempts=tuple(attempts),
        )

    def _attempt(self, request: LlmRequest, provider: ProviderName) -> tuple[LlmAttempt, Any]:
        model = self._settings.provider_settings(provider).model
        resolved = self._executables.get(provider)
        if resolved is None or resolved.path is None:
            outcome: CallOutcome = resolved.failure if resolved is not None and resolved.failure else "not_found"
            attempt = LlmAttempt(provider, model, outcome, 0.0)
            self._log(f"llm {provider.value}: {_describe(attempt)}")
            return attempt, None
        started = self._clock()
        try:
            outcome, raw, exit_code = self._run(request, provider, resolved.path, model)
        except OSError:  # the executable vanished or the temp folder could not be written
            outcome, raw, exit_code = "failed", None, None
        document: Any = None
        if outcome == "ok":
            try:
                document = request.validate(raw)
            except ValueError:
                outcome = "bad_output"
        attempt = LlmAttempt(provider, model, outcome, round(self._clock() - started, 1), exit_code)
        self._log(f"llm {provider.value}: {_describe(attempt)}")
        return attempt, document

    def _run(
        self, request: LlmRequest, provider: ProviderName, executable: str, model: str | None
    ) -> tuple[CallOutcome, Any, int | None]:
        root = Path(self._make_temp_dir())
        try:
            work, io = root / "work", root / "io"
            work.mkdir()
            io.mkdir()
            schema = load_schema(request.schema)
            if provider is ProviderName.CLAUDE:
                result = self._runner.run(
                    claude_argv(executable, model, schema),
                    cwd=work,
                    stdin=claude_stdin(request.prompt, request.photo),
                    timeout_s=self._settings.timeout_seconds,
                    env=self._child_env(),
                )
                outcome, raw = _claude_output(result)
            else:
                schema_path, output_path = io / "schema.json", io / "last.json"
                schema_path.write_text(json.dumps(schema, ensure_ascii=True), encoding="utf-8", newline="\n")
                photo_path = None
                if request.photo is not None:
                    photo_path = work / f"photo{image_suffix(request.photo)}"
                    photo_path.write_bytes(request.photo)
                result = self._runner.run(
                    codex_argv(
                        executable,
                        model,
                        schema_path=schema_path,
                        output_path=output_path,
                        work_dir=work,
                        photo_path=photo_path,
                    ),
                    cwd=work,
                    stdin=request.prompt.encode("utf-8"),
                    timeout_s=self._settings.timeout_seconds,
                    env=self._child_env(),
                )
                outcome, raw = _codex_output(result, output_path)
        finally:
            shutil.rmtree(root, ignore_errors=True)
        return outcome, raw, result.exit_code

    def _child_env(self) -> dict[str, str]:
        return child_environment(self._environ if self._environ is not None else os.environ)


def _claude_output(result: ProcessResult) -> tuple[CallOutcome, Any]:
    if result.timed_out:
        return "timeout", None
    if result.exit_code != 0:
        return "failed", None
    final: dict[str, Any] | None = None
    for line in result.stdout.decode("utf-8", errors="replace").splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if isinstance(event, dict) and event.get("type") == "result":
            final = event
    if final is None or final.get("subtype") != "success" or final.get("is_error") is True:
        return "bad_output", None
    if "structured_output" in final and final["structured_output"] is not None:
        return "ok", final["structured_output"]
    text = final.get("result")
    if not isinstance(text, str):
        return "bad_output", None
    try:
        return "ok", json.loads(text)
    except ValueError:
        return "bad_output", None


def _codex_output(result: ProcessResult, output_path: Path) -> tuple[CallOutcome, Any]:
    if result.timed_out:
        return "timeout", None
    if result.exit_code != 0:
        return "failed", None
    try:
        return "ok", json.loads(output_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return "bad_output", None


def _describe(attempt: LlmAttempt) -> str:
    model = attempt.model or "default model"
    if attempt.outcome == "failed":
        return f"failed (exit {attempt.exit_code}) after {attempt.seconds:g} s ({model})"
    if attempt.outcome in ("not_found", "executable_not_supported"):
        return attempt.outcome.replace("_", " ")
    return f"{attempt.outcome.replace('_', ' ')} after {attempt.seconds:g} s ({model})"
