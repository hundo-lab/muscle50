"""Short, ASCII descriptions of network and OS errors for the console and the run log.

The Windows message of an `OSError` is localized (Korean on a Korean Windows) and may carry a URL, so
`str(exc)` is never used: the description comes from the error number and a fixed English table.
`ConnectionResetError(10054, ...)` and `socket.gaierror(11001, ...)` resolve the same on every OS
(the number is looked up as `winerror` first, then as `errno` when the number is in the table).
"""

from __future__ import annotations

import errno
import http.client
import ssl
import urllib.error

# Winsock error numbers (WSAE*) that a long-poll bot meets, with a short English description.
WINSOCK_DESCRIPTIONS: dict[int, str] = {
    10013: "permission denied",
    10051: "network unreachable",
    10053: "connection aborted",
    10054: "connection reset by remote host",
    10060: "timed out",
    10061: "connection refused",
    10065: "host unreachable",
    11001: "host not found",
}

_MAX_REASON_DEPTH = 4


def describe_network_error(exc: BaseException) -> str:
    """`WinError 10054 connection reset by remote host`, `remote end closed the connection`, `ECONNRESET`, ... .

    Never `str(exc)`: the result is a fixed ASCII phrase, an error name or a type name.
    """
    return _describe(exc, _MAX_REASON_DEPTH)


def describe_os_error(exc: OSError) -> str:
    """The same idea for a file error: `EACCES`, `ENOSPC`, `WinError 32`, ... ."""
    return _describe(exc, 0)


def _describe(exc: BaseException, depth: int) -> str:
    if isinstance(exc, urllib.error.HTTPError):
        return f"HTTP {exc.code}"
    if isinstance(exc, urllib.error.URLError):
        reason = exc.reason
        if isinstance(reason, BaseException) and depth > 0:
            return _describe(reason, depth - 1)
        return type(exc).__name__
    if isinstance(exc, OSError):
        numbered = _numbered(exc)
        if numbered is not None:
            return numbered
    if isinstance(exc, http.client.RemoteDisconnected):
        return "remote end closed the connection"
    if isinstance(exc, ssl.SSLError):
        return "SSL error"
    if isinstance(exc, TimeoutError):
        return "timed out"
    if isinstance(exc, http.client.IncompleteRead):
        return "incomplete read"
    if isinstance(exc, OSError):
        return _describe_os(exc)
    return type(exc).__name__


def _numbered(exc: OSError) -> str | None:
    """`WinError <n> <phrase>` when the error number is a known Winsock one (as `winerror`, else as `errno`)."""
    for number in (getattr(exc, "winerror", None), exc.errno):
        if type(number) is int and number in WINSOCK_DESCRIPTIONS:
            return f"WinError {number} {WINSOCK_DESCRIPTIONS[number]}"
    return None


def _describe_os(exc: OSError) -> str:
    numbered = _numbered(exc)
    if numbered is not None:
        return numbered
    winerror = getattr(exc, "winerror", None)
    if type(winerror) is int:
        return f"WinError {winerror}"
    number = exc.errno
    if type(number) is int:
        name = errno.errorcode.get(number)
        if name is not None:
            return name
    return type(exc).__name__
