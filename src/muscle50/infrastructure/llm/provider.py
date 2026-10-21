"""`LlmProvider` over the local `claude` and `codex` CLIs (Telegram LLM v2).

Each call runs in a fresh temp folder (`muscle50-llm-*`) with `work/` as the CLI's cwd and `io/`
(schema and output files) outside it; the folder is removed afterwards. Codex gets the photo as
`work/photo.<ext>` (the only file in its cwd) and `-i`; Claude gets it as a base64 image block in its
stream-json stdin, so its cwd stays empty. An album's further photos are `work/photo-2.<ext>`, ... (v2.4).
Only the outcome kind, exit code, duration and (v2.5) the failure reason are logged: stdout and stderr are never
logged or kept (they can contain the message and the answer). The reason is decided by
`infrastructure/llm/failure_reason.py`, and only its value leaves it.
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
from muscle50.domain.llm_failure import FailureReason
from muscle50.domain.llm_settings import LlmSettings, ProviderName, other_provider
from muscle50.infrastructure.llm.argv import claude_argv, claude_stdin, codex_argv, image_suffix
from muscle50.infrastructure.llm.executables import ResolvedExecutable
from muscle50.infrastructure.llm.failure_reason import classify
from muscle50.infrastructure.llm.process import ProcessResult, ProcessRunner, child_environment

TEMP_PREFIX = "muscle50-llm-"
PLAIN_RESULT_MAX = 500
"""A plain-text Claude answer this short is read for a usage-limit mark (a longer one is the model's own text)."""


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
        if request.pin is not None:
            return self._pinned(request, provider, request.pin.model)
        attempts: list[LlmAttempt] = []
        order = [provider]
        fallback = self._settings.fallback_provider
        if fallback is not None and fallback is not provider:
            order.append(fallback)
        document: Any = None
        index = 0
        while index < len(order):
            name = order[index]
            settings = self._settings.provider_settings(name)
            first_model = settings.model_for(photo=request.has_photo)
            if request.strong_model and settings.retry_model is not None:
                first_model = settings.retry_model
            attempt, document, format_failure = self._attempt(request, name, first_model, retry=False)
            attempts.append(attempt)
            retry_model = settings.retry_after(attempt.model) if format_failure else None
            if retry_model is not None:
                # One more run of the same input on the retry model; its failure is not retried again.
                attempt, document, _ = self._attempt(request, name, retry_model, retry=True)
                attempts.append(attempt)
            if attempt.outcome == "ok":
                break
            if (
                index == 0
                and len(order) == 1
                and attempt.reason is FailureReason.USAGE_LIMIT
                and self._settings.fallback_on_usage_limit
            ):
                # v2.5: a usage limit goes once to the other provider (never a third provider's run).
                order.append(other_provider(name))
            if index + 1 < len(order):
                self._log(f"llm {name.value}: {_describe(attempt)}; trying fallback {order[index + 1].value}")
            index += 1
        last = attempts[-1]
        return LlmCallResult(
            provider=last.provider,
            model=last.model,
            outcome=last.outcome,
            document=document if last.outcome == "ok" else None,
            seconds=sum(item.seconds for item in attempts),
            used_fallback=any(item.provider is not provider for item in attempts),
            attempts=tuple(attempts),
        )

    def _pinned(self, request: LlmRequest, provider: ProviderName, model: str | None) -> LlmCallResult:
        """A corrective re-ask: one run on ``model`` of ``provider``; its failure is neither retried nor sent on."""
        attempt, document, _format_failure = self._attempt(request, provider, model, retry=False)
        return LlmCallResult(
            provider=provider,
            model=model,
            outcome=attempt.outcome,
            document=document if attempt.outcome == "ok" else None,
            seconds=attempt.seconds,
            used_fallback=False,
            attempts=(attempt,),
        )

    def _attempt(
        self, request: LlmRequest, provider: ProviderName, model: str | None, *, retry: bool
    ) -> tuple[LlmAttempt, Any, bool]:
        """One CLI run. The last item is True for a format failure: the model answered but the answer is unusable."""
        resolved = self._executables.get(provider)
        if resolved is None or resolved.path is None:
            outcome: CallOutcome = resolved.failure if resolved is not None and resolved.failure else "not_found"
            attempt = LlmAttempt(provider, model, outcome, 0.0, retry=retry, reason=FailureReason.NOT_FOUND)
            self._log(f"llm {provider.value}: {_describe(attempt)}")
            return attempt, None, False
        started = self._clock()
        searches: int | None = None
        reason: FailureReason | None
        try:
            outcome, raw, exit_code, format_failure, searches, reason = self._run(
                request, provider, resolved.path, model
            )
        except OSError:  # the executable vanished or the temp folder could not be written
            outcome, raw, exit_code, format_failure, reason = "failed", None, None, False, FailureReason.OTHER
        document: Any = None
        if outcome == "ok":
            try:
                document = request.validate(raw)
            except ValueError:
                outcome, format_failure, reason = "bad_output", True, FailureReason.OTHER
        seconds = round(self._clock() - started, 1)
        attempt = LlmAttempt(provider, model, outcome, seconds, exit_code, retry, searches, reason)
        self._log(f"llm {provider.value}: {_describe(attempt)}")
        if searches is not None and searches > self._settings.web_search_max:
            self._log(
                f"llm {provider.value}: web search used {searches}, above the limit {self._settings.web_search_max}"
            )
        return attempt, document, format_failure

    def _run(
        self, request: LlmRequest, provider: ProviderName, executable: str, model: str | None
    ) -> tuple[CallOutcome, Any, int | None, bool, int | None, FailureReason | None]:
        """(outcome, raw document, exit code, format failure, web searches or None when the tool was not offered,
        the failure reason or None for `ok`)."""
        root = Path(self._make_temp_dir())
        searches: int | None = None
        try:
            work, io = root / "work", root / "io"
            work.mkdir()
            io.mkdir()
            schema = load_schema(request.schema)
            if provider is ProviderName.CLAUDE:
                web = request.web_search
                result = self._runner.run(
                    claude_argv(executable, model, schema, web_search=web),
                    cwd=work,
                    stdin=claude_stdin(request.prompt, request.photo, request.extra_photos),
                    timeout_s=self._settings.web_search_timeout_seconds if web else self._settings.timeout_seconds,
                    env=self._child_env(),
                )
                outcome, raw, format_failure, reason = _claude_output(result)
                searches = count_web_searches(result.stdout) if web else None
            else:
                schema_path, output_path = io / "schema.json", io / "last.json"
                schema_path.write_text(json.dumps(schema, ensure_ascii=True), encoding="utf-8", newline="\n")
                photo_path = None
                extra_paths: list[Path] = []
                if request.photo is not None:
                    photo_path = work / f"photo{image_suffix(request.photo)}"
                    photo_path.write_bytes(request.photo)
                    for number, extra in enumerate(request.extra_photos, start=2):
                        extra_path = work / f"photo-{number}{image_suffix(extra)}"
                        extra_path.write_bytes(extra)
                        extra_paths.append(extra_path)
                result = self._runner.run(
                    codex_argv(
                        executable,
                        model,
                        schema_path=schema_path,
                        output_path=output_path,
                        work_dir=work,
                        photo_path=photo_path,
                        extra_photo_paths=tuple(extra_paths),
                    ),
                    cwd=work,
                    stdin=request.prompt.encode("utf-8"),
                    timeout_s=self._settings.timeout_seconds,
                    env=self._child_env(),
                )
                outcome, raw, format_failure, reason = _codex_output(result, output_path, request.prompt)
        finally:
            shutil.rmtree(root, ignore_errors=True)
        return outcome, raw, result.exit_code, format_failure, searches, reason

    def _child_env(self) -> dict[str, str]:
        return child_environment(self._environ if self._environ is not None else os.environ)


def _claude_output(result: ProcessResult) -> tuple[CallOutcome, Any, bool, FailureReason | None]:
    """The outcome, the raw document, whether a `bad_output` is a format failure (worth one retry), and the reason.

    A missing `result` event, a subtype other than `success` and `is_error: true` are CLI errors (for example a
    usage limit): `bad_output` as in v2, but not a format failure. v2.5: the final `result` event is read even when
    the exit is not 0 (for the reason only; the outcome is unchanged), and a short plain-text answer with a usage-limit
    mark is not a format failure either (a retry would only spend more of the same limit).
    """
    final, retrying, retry_status = _claude_events(result.stdout)
    error_text = final.get("result") if final is not None and isinstance(final.get("result"), str) else None
    status = final.get("api_error_status") if final is not None else None
    api_status = status if type(status) is int else None

    def why(text: str | None) -> FailureReason:
        return classify(
            ProviderName.CLAUDE,
            result,
            result_text=text,
            api_status=api_status,
            retrying=retrying,
            retry_status=retry_status,
        )

    if result.timed_out:
        return "timeout", None, False, why(None)
    if result.exit_code != 0:
        return "failed", None, False, why(error_text)
    if final is None or final.get("subtype") != "success" or final.get("is_error") is True:
        return "bad_output", None, False, why(error_text)
    if "structured_output" in final and final["structured_output"] is not None:
        return "ok", final["structured_output"], False, None
    text = final.get("result")
    if not isinstance(text, str):
        return "bad_output", None, True, FailureReason.OTHER
    try:
        return "ok", json.loads(text), False, None
    except ValueError:
        if len(text) <= PLAIN_RESULT_MAX and why(text) is FailureReason.USAGE_LIMIT:
            return "bad_output", None, False, FailureReason.USAGE_LIMIT
        return "bad_output", None, True, FailureReason.OTHER


def _claude_events(stdout: bytes) -> tuple[dict[str, Any] | None, bool, int | None]:
    """(the final `result` event, whether the run ended in the CLI's API retries, the HTTP status of that retry).

    "Ended in retries": the last `system/api_retry` event comes after the last assistant message.
    """
    final: dict[str, Any] | None = None
    retry: dict[str, Any] | None = None
    for line in stdout.decode("utf-8", errors="replace").splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if not isinstance(event, dict):
            continue
        if event.get("type") == "result":
            final = event
        elif event.get("type") == "system" and event.get("subtype") == "api_retry":
            retry = event
        elif event.get("type") == "assistant":
            retry = None
    status = retry.get("error_status") if retry is not None else None
    return final, retry is not None, status if type(status) is int else None


def count_web_searches(stdout: bytes) -> int:
    """The distinct web search calls in a stream-json stdout (also a timed-out run's partial output).

    Counts `tool_use` / `server_tool_use` blocks named `WebSearch` (or `web_search`) once per block id. Only
    this number is kept: the queries and the results never leave this function.
    """
    seen: set[str] = set()
    anonymous = 0
    for line in stdout.decode("utf-8", errors="replace").splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        message = event.get("message") if isinstance(event, dict) else None
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict) or block.get("type") not in ("tool_use", "server_tool_use"):
                continue
            if block.get("name") not in ("WebSearch", "web_search"):
                continue
            block_id = block.get("id")
            if isinstance(block_id, str):
                seen.add(block_id)
            else:
                anonymous += 1
    return len(seen) + anonymous


def _codex_output(
    result: ProcessResult, output_path: Path, prompt: str
) -> tuple[CallOutcome, Any, bool, FailureReason | None]:
    if result.timed_out:
        return "timeout", None, False, FailureReason.TIMEOUT
    if result.exit_code != 0:
        return "failed", None, False, classify(ProviderName.CODEX, result, prompt=prompt)
    try:
        return "ok", json.loads(output_path.read_text(encoding="utf-8")), False, None
    except (OSError, ValueError):
        return "bad_output", None, True, FailureReason.OTHER


def _describe(attempt: LlmAttempt) -> str:
    model = attempt.model or "default model"
    if attempt.retry:
        model += ", retry"
    if attempt.web_searches:
        model += f", web search {attempt.web_searches}"
    if attempt.outcome in ("not_found", "executable_not_supported"):
        return attempt.outcome.replace("_", " ")
    if attempt.outcome == "failed":
        text = f"failed (exit {attempt.exit_code}) after {attempt.seconds:g} s ({model})"
    else:
        text = f"{attempt.outcome.replace('_', ' ')} after {attempt.seconds:g} s ({model})"
    if attempt.reason is not None and attempt.reason not in (FailureReason.OTHER, FailureReason.TIMEOUT):
        text += f"; reason {attempt.reason.value}"  # v2.5: only the reason value, never the CLI's text
    return text
