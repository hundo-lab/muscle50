"""Telegram LLM v2.5: why an LLM call failed, the reply that says what to do, and the `/retry_` texts.

Pure values. The reason is decided from the CLI's exit and its short error marks
(`infrastructure/llm/failure_reason.py`); only the reason value leaves that function, never the CLI's text.
"""

from __future__ import annotations

from enum import StrEnum

from muscle50.domain.llm_settings import PROVIDER_COMPANIES, ProviderName, other_provider


class FailureReason(StrEnum):
    NETWORK = "network"
    USAGE_LIMIT = "usage_limit"
    LOGIN = "login"
    TIMEOUT = "timeout"
    NOT_FOUND = "not_found"
    OTHER = "other"


FAILURE_REASON_VALUES = frozenset(reason.value for reason in FailureReason)

REASON_NAMES = {
    FailureReason.NETWORK: "네트워크",
    FailureReason.USAGE_LIMIT: "사용 한도",
    FailureReason.LOGIN: "로그인 필요",
    FailureReason.TIMEOUT: "시간 초과",
    FailureReason.NOT_FOUND: "실행 파일 없음",
    FailureReason.OTHER: "기타",
}
"""The Korean names `/history` shows (` · 실패 이유: 네트워크`)."""

_DISPLAY = {ProviderName.CLAUDE: "Claude", ProviderName.CODEX: "Codex"}

RETRY_TTL_S = 60 * 60
"""A failed message can be sent again with `/retry_<id>` for 60 minutes; its text is then removed."""
RETRY_UNKNOWN_TEXT = "이 다시 보내기 명령을 찾지 못했습니다."
RETRY_USED_TEXT = "이미 다시 보낸 메시지입니다. /history로 확인하세요."
RETRY_EXPIRED_TEXT = "다시 보내기 유효 시간(60분)이 지났습니다. 메시지를 다시 보내 주세요."


def reason_of(outcome: str, reason: FailureReason | None) -> FailureReason | None:
    """The reason of a call outcome: None for `ok`; the outcome decides timeout and a missing executable."""
    if outcome == "ok":
        return None
    if outcome == "timeout":
        # A run that hung in the CLI's own connection retries is a network (or limit/login) failure, not a slow model.
        return reason if reason is not None and reason is not FailureReason.OTHER else FailureReason.TIMEOUT
    if outcome in ("not_found", "executable_not_supported"):
        return FailureReason.NOT_FOUND
    return reason if reason is not None else FailureReason.OTHER


def provider_display(provider: ProviderName) -> str:
    return _DISPLAY[provider]


def failure_text(reason: FailureReason, provider: ProviderName, *, other_tried: bool) -> str | None:
    """The reply body for a failed call; None for `other` (the caller keeps its v2.4 text)."""
    name = _DISPLAY[provider]
    if reason is FailureReason.NETWORK:
        return "인터넷 연결이 끊긴 것 같아 해석하지 못했습니다. 연결되면 아래 명령으로 다시 보내세요."
    if reason is FailureReason.USAGE_LIMIT:
        if other_tried:
            return f"{name} 사용 한도에 걸려 해석하지 못했습니다. 한도가 풀린 뒤 다시 보내세요."
        other = other_provider(provider).value
        return f"{name} 사용 한도에 걸려 해석하지 못했습니다. 잠시 뒤 다시 보내거나 /llm {other} 로 바꾸세요."
    if reason is FailureReason.LOGIN:
        if provider is ProviderName.CLAUDE:
            return (
                "Claude 로그인이 필요해 해석하지 못했습니다. PC 터미널에서 claude 를 실행해 /login 한 뒤 다시 보내세요."
            )
        return "Codex 로그인이 필요해 해석하지 못했습니다. PC 터미널에서 codex login 을 실행한 뒤 다시 보내세요."
    if reason is FailureReason.TIMEOUT:
        return f"{name}가 시간 안에 답하지 않아 해석하지 못했습니다. 다시 보내거나 /log 로 보내세요."
    if reason is FailureReason.NOT_FOUND:
        return (
            f"{name} 실행 파일을 찾지 못해 해석하지 못했습니다. "
            "PC에서 설치와 telegram_llm.json의 executable을 확인하고 bot을 다시 시작하세요."
        )
    return None


def retry_line(token: str) -> str:
    """The tappable command line after a failure reply."""
    return f"다시 보내기(60분 유효): /retry_{token}"


def usage_fallback_note(limited: ProviderName, answered: ProviderName) -> str:
    """Appended to the reply when the other company answered because the first one hit its usage limit."""
    return (
        f"({_DISPLAY[limited]} 사용 한도라 이번에는 {answered.value}({PROVIDER_COMPANIES[answered]})로 처리했습니다.)"
    )
