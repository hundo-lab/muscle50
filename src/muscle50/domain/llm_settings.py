"""Telegram LLM v2 settings: which local CLI interprets free text and photos, with what persona and limits.

Pure values. The user writes `config\\telegram_llm.json` (read by `infrastructure/telegram/llm_config_file.py`);
an absent file means the feature is off. Every key is optional and `{}` gives exactly `DEFAULT_SETTINGS`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum


class ProviderName(StrEnum):
    CLAUDE = "claude"
    """Claude Code, `claude -p` (Anthropic)."""
    CODEX = "codex"
    """OpenAI Codex CLI, `codex exec` (OpenAI)."""


PROVIDER_COMPANIES: dict[ProviderName, str] = {ProviderName.CLAUDE: "Anthropic", ProviderName.CODEX: "OpenAI"}

MODEL_PATTERN = re.compile(r"[A-Za-z0-9._:-]{1,64}")
PERSONA_NAME_MAX_LENGTH = 20
PERSONA_TONE_MAX_LENGTH = 100
TIMEOUT_MIN_S = 10
TIMEOUT_MAX_S = 600


@dataclass(frozen=True)
class ProviderSettings:
    model: str | None
    """None: the CLI's own default model (no model option is passed)."""
    executable: str | None
    """An absolute path, or None to look the CLI up on PATH."""


@dataclass(frozen=True)
class LlmSettings:
    provider: ProviderName
    claude: ProviderSettings
    codex: ProviderSettings
    persona_name: str
    persona_tone: str
    timeout_seconds: int
    fallback_provider: ProviderName | None
    keep_photos: bool

    def provider_settings(self, provider: ProviderName) -> ProviderSettings:
        return self.claude if provider is ProviderName.CLAUDE else self.codex


DEFAULT_SETTINGS = LlmSettings(
    provider=ProviderName.CLAUDE,
    claude=ProviderSettings(model="sonnet", executable=None),
    codex=ProviderSettings(model=None, executable=None),
    persona_name="머슬",
    persona_tone="존댓말, 짧게, 담백하게",
    timeout_seconds=90,
    fallback_provider=None,
    keep_photos=True,
)


def other_provider(provider: ProviderName) -> ProviderName:
    return ProviderName.CODEX if provider is ProviderName.CLAUDE else ProviderName.CLAUDE
