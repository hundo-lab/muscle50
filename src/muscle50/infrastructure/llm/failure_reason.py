"""Why a provider CLI run failed (Telegram LLM v2.5), from its exit and its short error marks.

Pure and deterministic. The inputs are the run's exit, the final Claude `result` event's text and API status (only
for an error result), the CLI's own connection-retry status, and the **last 4096 characters** of stderr (and of a
failed Codex run's stdout). Codex echoes the prompt on stderr, so the prompt is removed first and only Codex lines
that say `error` are read. The text is casefolded and matched against fixed marks; **only the reason value leaves this
module**: nothing is logged, stored or returned. A wording the table does not know is `other`.

Marks were checked live on 2026-10-21 (Claude Code 2.1.296, Codex CLI 0.160.0, synthetic prompts): Claude without a
login answers `Not logged in · Please run /login` as an error result; Claude behind an unreachable proxy keeps
retrying (`system/api_retry` events without an HTTP status) until the time limit; Codex without a login prints
`401 Unauthorized`; Codex behind an unreachable proxy prints `workspace routing discovery failed`. A usage limit cannot
be triggered on demand: its marks follow the CLIs' known messages.
"""

from __future__ import annotations

import re

from muscle50.domain.llm_failure import FailureReason
from muscle50.domain.llm_settings import ProviderName
from muscle50.infrastructure.llm.process import ProcessResult

TAIL_CHARS = 4096

USAGE_LIMIT_MARKS = (
    "usage limit",
    "limit reached",
    "hit your limit",
    "hit your usage limit",
    "rate limit",
    "too many requests",
    "quota",
    "5-hour limit",
    "weekly limit",
)
LOGIN_MARKS = (
    "/login",
    "not logged in",
    "invalid api key",
    "oauth token has expired",
    "authentication_error",
    "codex login",
    "401 unauthorized",
    "missing bearer",
    "could not be refreshed",
    "sign in again",
    "log in again",
)
NETWORK_MARKS = (
    "connection error",
    "unable to connect",
    "econnrefused",
    "econnreset",
    "enotfound",
    "etimedout",
    "getaddrinfo",
    "error sending request",
    "stream disconnected",
    "failed to connect",
    "connection refused",
    "connection reset",
    "dns",
    "workspace routing discovery failed",
    "request timed out",
)
# Windows socket errors by number, so a Korean (or any other language) system message still matches.
_OS_ERROR = re.compile(r"os error (10051|10053|10054|10060|10061|10065|11001)\b")


def classify(
    provider: ProviderName,
    result: ProcessResult,
    *,
    result_text: str | None = None,
    api_status: int | None = None,
    retrying: bool = False,
    retry_status: int | None = None,
    prompt: str | None = None,
) -> FailureReason:
    """The reason of a run that did not succeed.

    ``result_text`` / ``api_status``: the final Claude `result` event of an error (or a plain-text answer).
    ``retrying`` / ``retry_status``: the run ended while the CLI was still retrying its API connection (Claude
    `system/api_retry`, with the HTTP status when there was one). ``prompt``: the stdin text, removed from the Codex
    output it is echoed in.
    """
    if result.timed_out and not retrying:
        return FailureReason.TIMEOUT
    for status in (api_status, retry_status):
        if status == 429:
            return FailureReason.USAGE_LIMIT
        if status in (401, 403):
            return FailureReason.LOGIN
    texts = [result_text or ""]
    texts.append(_tail(result.stderr, provider, prompt))
    if provider is ProviderName.CODEX and result.exit_code not in (0, None):
        texts.append(_tail(result.stdout, provider, prompt))
    text = "\n".join(texts).casefold()
    if any(mark in text for mark in USAGE_LIMIT_MARKS):
        return FailureReason.USAGE_LIMIT
    if any(mark in text for mark in LOGIN_MARKS):
        return FailureReason.LOGIN
    if any(mark in text for mark in NETWORK_MARKS) or _OS_ERROR.search(text):
        return FailureReason.NETWORK
    if retrying and retry_status is None:
        return FailureReason.NETWORK  # never reached the API: no HTTP status in any retry
    return FailureReason.TIMEOUT if result.timed_out else FailureReason.OTHER


def _tail(data: bytes, provider: ProviderName, prompt: str | None) -> str:
    text = data.decode("utf-8", errors="replace")
    if provider is ProviderName.CODEX:
        if prompt:
            text = text.replace(prompt.strip(), " ")
        text = "\n".join(line for line in text.splitlines() if "error" in line.casefold())
    return text[-TAIL_CHARS:]
