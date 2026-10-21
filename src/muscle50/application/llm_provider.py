"""Telegram LLM v2: the port to a local LLM CLI (`claude -p` or `codex exec`) and its call results.

A call sends one prompt (and the photos of one message: one, or an album of up to four) and gets one JSON
document back. The provider validates that document with the caller's own validator, so a malformed answer
counts as a failure (`bad_output`) and may go to the fallback provider. The LLM never writes anything: it has
no tools and its output is only data that the bot checks and the user confirms.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Literal, Protocol

from muscle50.domain.llm_failure import FailureReason, reason_of
from muscle50.domain.llm_settings import ProviderName


class SchemaName(StrEnum):
    """The JSON schema the CLI must answer with (`src/muscle50/schemas/telegram_llm_<name>_v1.schema.json`)."""

    INTERPRET = "interpret"
    ANSWER = "answer"
    SUGGEST = "suggest"


CallOutcome = Literal["ok", "timeout", "failed", "bad_output", "not_found", "executable_not_supported"]


@dataclass(frozen=True)
class RunPin:
    """Run exactly once, on this model of the given provider: no format retry and no fallback provider."""

    model: str | None


@dataclass(frozen=True)
class LlmRequest:
    prompt: str
    """Sent on stdin, never in argv."""
    schema: SchemaName
    photo: bytes | None
    validate: Callable[[Any], Any]
    """Turns the raw JSON document into the checked value; raises ValueError (`bad_output`) otherwise."""
    web_search: bool = False
    """Offer the web search tool (Claude only; Codex never searches). Every other call has no tool."""
    pin: RunPin | None = None
    """A corrective re-ask: one run on the pinned model, no retry and no fallback."""
    extra_photos: tuple[bytes, ...] = ()
    """v2.4 albums: the photos after ``photo`` (``photo`` is the first). Empty for a single photo."""
    strong_model: bool = False
    """v2.5: start on the provider's `retry_model` (when set) instead of the text or photo model: an edit of an open
    proposal. The normal retry and fallback rules still apply."""

    @property
    def has_photo(self) -> bool:
        return self.photo is not None


@dataclass(frozen=True)
class LlmAttempt:
    provider: ProviderName
    model: str | None
    outcome: CallOutcome
    seconds: float
    exit_code: int | None = None
    retry: bool = False
    """True for the one re-run on the retry model after a format failure."""
    web_searches: int | None = None
    """How many web searches the run made; None when the tool was not offered, 0 when offered but unused."""
    reason: FailureReason | None = None
    """v2.5: why a run that did not succeed failed (None for `ok`); decided from the exit and the CLI's error marks."""


@dataclass(frozen=True)
class LlmCallResult:
    provider: ProviderName
    """The provider of the last attempt (the fallback when it was tried)."""
    model: str | None
    outcome: CallOutcome
    document: Any
    """The validated value when `outcome == "ok"`, otherwise None."""
    seconds: float
    used_fallback: bool
    attempts: tuple[LlmAttempt, ...] = ()

    @property
    def ok(self) -> bool:
        return self.outcome == "ok"

    @property
    def web_searches(self) -> int | None:
        """The searches of all attempts of this call; None when no attempt was offered the tool."""
        counts = [attempt.web_searches for attempt in self.attempts if attempt.web_searches is not None]
        return sum(counts) if counts else None

    @property
    def failure_reason(self) -> FailureReason | None:
        """Why the call failed, from its last attempt; None when it succeeded."""
        last = self.attempts[-1] if self.attempts else None
        return reason_of(self.outcome, last.reason if last is not None else None)

    @property
    def usage_limited(self) -> ProviderName | None:
        """The provider whose usage limit sent this successful call on to the other provider (None otherwise)."""
        if not self.ok:
            return None
        for attempt in self.attempts:
            if attempt.provider is not self.provider and attempt.reason is FailureReason.USAGE_LIMIT:
                return attempt.provider
        return None

    @property
    def other_tried(self) -> bool:
        """True when some attempt ran on a provider other than the last attempt's."""
        return any(attempt.provider is not self.provider for attempt in self.attempts)

    @property
    def retried(self) -> bool:
        """True when some attempt was a re-run on the retry model."""
        return any(attempt.retry for attempt in self.attempts)


class LlmProvider(Protocol):
    def call(self, request: LlmRequest, provider: ProviderName) -> LlmCallResult:
        """Try ``provider`` (the photo or text model), re-run once on the retry model after a format failure,
        then the configured fallback provider once (with the same rules) when it differs and the provider failed.
        v2.5: a usage limit of ``provider`` sends the call once to the other provider (`fallback_on_usage_limit`)."""
        ...
