"""`config\\telegram_llm.json`: turns Telegram LLM v2 on and chooses the provider, written by the user.

Absent file: the feature is off and the bot behaves exactly as v1.2. Strict UTF-8 JSON (a BOM is
accepted); every key is optional, unknown keys are refused, and error messages name the key but
never echo a value. `{}` gives exactly `DEFAULT_SETTINGS`. The file holds no secret: each CLI keeps
its own login.
"""

from __future__ import annotations

import json
import unicodedata
from pathlib import Path
from typing import Any

from muscle50.domain.llm_settings import (
    DEFAULT_SETTINGS,
    MODEL_PATTERN,
    PERSONA_NAME_MAX_LENGTH,
    PERSONA_TONE_MAX_LENGTH,
    TIMEOUT_MAX_S,
    TIMEOUT_MIN_S,
    LlmSettings,
    ProviderName,
    ProviderSettings,
)

_TOP_KEYS = frozenset({"provider", "claude", "codex", "persona", "timeout_seconds", "fallback_provider", "keep_photos"})
_PROVIDER_KEYS = frozenset({"model", "photo_model", "retry_model", "executable"})
_PERSONA_KEYS = frozenset({"name", "tone"})


class LlmConfigError(RuntimeError):
    """`config\\telegram_llm.json` is invalid. The message never contains a configured value."""


def load_llm_settings(path: Path) -> LlmSettings | None:
    """The settings, or None when the file does not exist (feature off)."""
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise LlmConfigError(f"telegram LLM 설정 파일을 읽을 수 없습니다: {path} ({exc.strerror})") from None
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise LlmConfigError(f"telegram LLM 설정 파일이 UTF-8이 아닙니다: {path}") from None
    try:
        document: Any = json.loads(text)
    except json.JSONDecodeError as exc:
        raise LlmConfigError(
            f"telegram LLM 설정 파일이 올바른 JSON이 아닙니다: {path} (line {exc.lineno}, column {exc.colno})"
        ) from None
    try:
        return _settings(document)
    except ValueError as exc:
        raise LlmConfigError(f"telegram LLM 설정 파일이 올바르지 않습니다: {path} ({exc})") from None


def _settings(document: Any) -> LlmSettings:
    root = _object(document, _TOP_KEYS, "the file")
    defaults = DEFAULT_SETTINGS
    provider = _provider(root.get("provider", defaults.provider.value), "provider")
    fallback_value = root.get("fallback_provider")
    fallback = None if fallback_value is None else _provider(fallback_value, "fallback_provider")
    if fallback is provider:
        raise ValueError("fallback_provider must be the other provider or null")
    persona = _object(root.get("persona", {}), _PERSONA_KEYS, "persona")
    timeout = root.get("timeout_seconds", defaults.timeout_seconds)
    if type(timeout) is not int or not TIMEOUT_MIN_S <= timeout <= TIMEOUT_MAX_S:
        raise ValueError(f"timeout_seconds must be an integer from {TIMEOUT_MIN_S} to {TIMEOUT_MAX_S}")
    keep_photos = root.get("keep_photos", defaults.keep_photos)
    if type(keep_photos) is not bool:
        raise ValueError("keep_photos must be true or false")
    return LlmSettings(
        provider=provider,
        claude=_provider_settings(root.get("claude", {}), "claude", defaults.claude),
        codex=_provider_settings(root.get("codex", {}), "codex", defaults.codex),
        persona_name=_line(persona.get("name", defaults.persona_name), "persona.name", PERSONA_NAME_MAX_LENGTH),
        persona_tone=_line(persona.get("tone", defaults.persona_tone), "persona.tone", PERSONA_TONE_MAX_LENGTH),
        timeout_seconds=timeout,
        fallback_provider=fallback,
        keep_photos=keep_photos,
    )


def _provider(value: Any, key: str) -> ProviderName:
    if not isinstance(value, str) or value not in {name.value for name in ProviderName}:
        raise ValueError(f"{key} must be claude or codex")
    return ProviderName(value)


def _provider_settings(value: Any, key: str, default: ProviderSettings) -> ProviderSettings:
    entry = _object(value, _PROVIDER_KEYS, key)
    model = _model(entry, "model", key, default.model)
    photo_model = _model(entry, "photo_model", key, default.photo_model)
    retry_model = _model(entry, "retry_model", key, default.retry_model)
    executable = entry.get("executable", default.executable)
    if executable is not None and (not isinstance(executable, str) or not Path(executable).is_absolute()):
        raise ValueError(f"{key}.executable must be null or an absolute path")
    return ProviderSettings(model, executable, photo_model, retry_model)


def _model(entry: dict[str, Any], name: str, key: str, default: str | None) -> str | None:
    value = entry.get(name, default)
    if value is not None and (not isinstance(value, str) or MODEL_PATTERN.fullmatch(value) is None):
        raise ValueError(f"{key}.{name} must be null or 1-64 letters, digits, '.', '_', ':' or '-'")
    return value


def _object(value: Any, keys: frozenset[str], where: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{where} must be a JSON object")
    unknown = sorted(set(value) - keys)
    if unknown:
        # Key names are the user's own typing but never a secret value; at most the first is named.
        raise ValueError(f"unknown key in {where}: {unknown[0]!r}")
    return value


def _line(value: Any, key: str, limit: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} must be a non-empty string")
    text = value.strip()
    if len(text) > limit:
        raise ValueError(f"{key} must be at most {limit} characters")
    if any(unicodedata.category(character) == "Cc" for character in text):
        raise ValueError(f"{key} must be one line")
    return text
