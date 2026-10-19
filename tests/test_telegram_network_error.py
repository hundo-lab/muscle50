"""AC9 of docs/specs/telegram-llm-reliability.md: network errors read as a number and a short English phrase.

The Windows message of an `OSError` is localized and may hold a URL, so it is never used. The cases build the
errors with fixed `winerror`/`errno` values, so they give the same text on every OS.
"""

from __future__ import annotations

import errno
import http.client
import socket
import ssl
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any

import pytest

from muscle50.application.telegram_bot import TelegramUnavailableError
from muscle50.infrastructure.telegram.bot_api import UrllibTelegramBotApi
from muscle50.infrastructure.telegram.network_error import describe_network_error, describe_os_error

TOKEN = "123456789:AAFakeSyntheticToken_ab-cd"
KOREAN = "원격 호스트가 강제로 기존 연결을 끊었습니다"


def _winerror(code: int, message: str = KOREAN) -> OSError:
    """What Windows raises: `winerror` set, `errno` derived. Built portably through the attribute."""
    exc = ConnectionResetError(code, message)
    exc.winerror = code
    return exc


CASES: list[tuple[str, BaseException, str]] = [
    ("reset by winerror", _winerror(10054), "WinError 10054 connection reset by remote host"),
    ("reset by errno", ConnectionResetError(10054, KOREAN), "WinError 10054 connection reset by remote host"),
    ("aborted", OSError(10053, KOREAN), "WinError 10053 connection aborted"),
    ("timed out number", OSError(10060, KOREAN), "WinError 10060 timed out"),
    ("refused", ConnectionRefusedError(10061, KOREAN), "WinError 10061 connection refused"),
    ("unreachable", OSError(10051, KOREAN), "WinError 10051 network unreachable"),
    ("host unreachable", OSError(10065, KOREAN), "WinError 10065 host unreachable"),
    ("permission", OSError(10013, KOREAN), "WinError 10013 permission denied"),
    ("dns", socket.gaierror(11001, KOREAN), "WinError 11001 host not found"),
    ("url error with dns", urllib.error.URLError(socket.gaierror(11001, KOREAN)), "WinError 11001 host not found"),
    ("url error with reset", urllib.error.URLError(_winerror(10054)), "WinError 10054 connection reset by remote host"),
    ("url error with a text reason", urllib.error.URLError("cannot reach https://example.invalid/"), "URLError"),
    ("remote closed", http.client.RemoteDisconnected(KOREAN), "remote end closed the connection"),
    ("ssl", ssl.SSLError(1, KOREAN), "SSL error"),
    ("timeout", TimeoutError(KOREAN), "timed out"),
    ("socket timeout", TimeoutError(KOREAN), "timed out"),
    ("incomplete read", http.client.IncompleteRead(b"ab", 5), "incomplete read"),
    ("other os error by errno", OSError(errno.ENOSPC, KOREAN), "ENOSPC"),
    ("unknown winerror", _winerror(5), "WinError 5"),
    ("os error without a number", OSError(KOREAN), "OSError"),
    ("not an os error", ValueError(KOREAN), "ValueError"),
    ("http status", http.client.BadStatusLine(KOREAN), "BadStatusLine"),
]


@pytest.mark.parametrize(("case", "exc", "expected"), CASES, ids=[case[0] for case in CASES])
def test_describe_network_error(case: str, exc: BaseException, expected: str) -> None:
    text = describe_network_error(exc)
    assert text == expected
    assert text.isascii() and KOREAN not in text


def test_describe_os_error_names_a_file_error() -> None:
    assert describe_os_error(PermissionError(13, KOREAN)) == "EACCES"
    assert describe_os_error(OSError(errno.ENOSPC, KOREAN)) == "ENOSPC"
    assert describe_os_error(FileNotFoundError(KOREAN)) == "FileNotFoundError"


def test_a_url_reason_chain_stops_at_a_depth() -> None:
    inner: BaseException = OSError(KOREAN)
    for _ in range(10):
        inner = urllib.error.URLError(inner)
    assert describe_network_error(inner) == "URLError"


# --- the adapter's message ---------------------------------------------------------------------------------


def _install(monkeypatch: pytest.MonkeyPatch, respond: Callable[..., Any]) -> None:
    monkeypatch.setattr(urllib.request, "urlopen", respond)


def _raise(exc: BaseException) -> Callable[..., Any]:
    def respond(*args: object, **kwargs: object) -> Any:
        raise exc

    return respond


@pytest.mark.parametrize(("case", "exc", "expected"), CASES[:12], ids=[case[0] for case in CASES[:12]])
def test_the_adapter_message_is_the_number_and_the_phrase(
    monkeypatch: pytest.MonkeyPatch, case: str, exc: BaseException, expected: str
) -> None:
    _install(monkeypatch, _raise(exc))
    with pytest.raises(TelegramUnavailableError) as raised:
        UrllibTelegramBotApi(TOKEN).get_updates(None, 10)
    assert str(raised.value) == f"network error ({expected})"
    assert raised.value.status is None and raised.value.__cause__ is None


def test_the_console_wording_for_a_reset_is_the_spec_example() -> None:
    assert f"network error ({describe_network_error(_winerror(10054))})" == (
        "network error (WinError 10054 connection reset by remote host)"
    )
