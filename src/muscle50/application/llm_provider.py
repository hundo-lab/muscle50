"""Telegram LLM v2: the port to a local LLM CLI (`claude -p` or `codex exec`) and its call results.

A call sends one prompt (and at most one photo) and gets one JSON document back. The provider
validates that document with the caller's own validator, so a malformed answer counts as a failure
(`bad_output`) and may go to the fallback provider. The LLM never writes anything: it has no tools
and its output is only data that the bot checks and the user confirms.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Literal, Protocol

from muscle50.domain.llm_settings import ProviderName


class SchemaName(StrEnum):
    """The JSON schema the CLI must answer with (`src/muscle50/schemas/telegram_llm_<name>_v1.schema.json`)."""

    INTERPRET = "interpret"
    ANSWER = "answer"
    SUGGEST = "suggest"


CallOutcome = Literal["ok", "timeout", "failed", "bad_output", "not_found", "executable_not_supported"]


@dataclass(frozen=True)
class LlmRequest:
    prompt: str
    """Sent on stdin, never in argv."""
    schema: SchemaName
    photo: bytes | None
    validate: Callable[[Any], Any]
    """Turns the raw JSON document into the checked value; raises ValueError (`bad_output`) otherwise."""


@dataclass(frozen=True)
class LlmAttempt:
    provider: ProviderName
    model: str | None
    outcome: CallOutcome
    seconds: float
    exit_code: int | None = None


@dataclass(frozen=True)
class LlmCallResult:
    provider: ProviderName
    """The provider of the last attempt (the fallback when it was tried)."""
    model: str | None
    outcome: CallOutcome
    document: Any | None
    """The validated value when `outcome == "ok"`, otherwise None."""
    seconds: float
    used_fallback: bool
    attempts: tuple[LlmAttempt, ...] = ()

    @property
    def ok(self) -> bool:
        return self.outcome == "ok"


class LlmProvider(Protocol):
    def call(self, request: LlmRequest, provider: ProviderName) -> LlmCallResult:
        """Try ``provider``, then the configured fallback provider once when it differs and the first try failed."""
        ...
