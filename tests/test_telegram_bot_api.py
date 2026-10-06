"""The stdlib Bot API adapter, through a patched `urllib.request.urlopen` (never the network).

Pins the request shape (POST, JSON body, URL path, HTTP timeout), the response and error mapping,
and token redaction: no error carries the token, raw or URL-quoted, or a chained original error.
"""

from __future__ import annotations

import http.client
import io
import json
import traceback
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from typing import Any

import pytest

from muscle50.application.telegram_bot import (
    BotIdentity,
    IncomingMessage,
    IncomingUpdate,
    TelegramTokenRejectedError,
    TelegramUnavailableError,
)
from muscle50.infrastructure.telegram.bot_api import UrllibTelegramBotApi, redact

TOKEN = "123456789:AAFakeSyntheticToken_ab-cd"
QUOTED = urllib.parse.quote(TOKEN, safe="")
BASE = f"https://api.telegram.org/bot{TOKEN}"


class FakeResponse:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return self._body


class Recorder:
    def __init__(self, respond: Callable[[urllib.request.Request], bytes]) -> None:
        self.respond = respond
        self.calls: list[tuple[urllib.request.Request, float]] = []

    def __call__(self, request: urllib.request.Request, timeout: float) -> FakeResponse:
        self.calls.append((request, timeout))
        return FakeResponse(self.respond(request))

    def payload(self, index: int = -1) -> Any:
        data = self.calls[index][0].data
        assert isinstance(data, bytes)
        return json.loads(data.decode("utf-8"))


def _ok(result: Any) -> Callable[[urllib.request.Request], bytes]:
    return lambda request: json.dumps({"ok": True, "result": result}).encode("utf-8")


def _install(monkeypatch: pytest.MonkeyPatch, respond: Callable[[urllib.request.Request], bytes]) -> Recorder:
    recorder = Recorder(respond)
    monkeypatch.setattr(urllib.request, "urlopen", recorder)
    return recorder


def _raise(exc: BaseException) -> Callable[[urllib.request.Request], bytes]:
    def respond(request: urllib.request.Request) -> bytes:
        raise exc

    return respond


def _http_error(code: int, document: Any) -> urllib.error.HTTPError:
    body = io.BytesIO(json.dumps(document).encode("utf-8"))
    return urllib.error.HTTPError(f"{BASE}/getUpdates", code, "synthetic", http.client.HTTPMessage(), body)


def _assert_no_token(exc: BaseException) -> None:
    rendered = [str(exc), repr(exc), "".join(traceback.format_exception(exc))]
    for text in rendered:
        assert TOKEN not in text
        assert QUOTED not in text
    assert exc.__cause__ is None
    assert exc.__context__ is None


def test_get_me_posts_json_to_the_method_url(monkeypatch: pytest.MonkeyPatch) -> None:
    recorder = _install(monkeypatch, _ok({"id": 1234567890, "is_bot": True, "username": "muscle50_example_bot"}))
    assert UrllibTelegramBotApi(TOKEN).get_me() == BotIdentity(1234567890, "muscle50_example_bot")
    request, timeout = recorder.calls[0]
    assert request.full_url == f"{BASE}/getMe"
    assert request.get_method() == "POST"
    assert request.get_header("Content-type") == "application/json"
    assert recorder.payload() == {}
    assert timeout == 15


def test_get_updates_requests_messages_only_with_poll_timeout_plus_margin(monkeypatch: pytest.MonkeyPatch) -> None:
    result = [
        {"update_id": 5500, "message": {"chat": {"id": 111}, "date": 1_790_000_000, "text": "/status"}},
        {"update_id": 5501, "message": {"chat": {"id": -100222}, "date": 1_790_000_001, "photo": [{}]}},
        {"update_id": 5502, "edited_message": {"chat": {"id": 111}, "date": 1_790_000_002, "text": "x"}},
    ]
    recorder = _install(monkeypatch, _ok(result))
    api = UrllibTelegramBotApi(TOKEN)
    assert api.get_updates(None, 10) == (
        IncomingUpdate(5500, IncomingMessage(111, "/status", 1_790_000_000)),
        IncomingUpdate(5501, IncomingMessage(-100222, None, 1_790_000_001)),
        IncomingUpdate(5502, None),
    )
    assert recorder.calls[0][0].full_url == f"{BASE}/getUpdates"
    assert recorder.payload() == {"timeout": 10, "allowed_updates": ["message"]}
    assert recorder.calls[0][1] == 20
    api.get_updates(5503, 10)
    assert recorder.payload() == {"timeout": 10, "allowed_updates": ["message"], "offset": 5503}


def test_send_message_uses_html_parse_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    recorder = _install(monkeypatch, _ok({"message_id": 1}))
    UrllibTelegramBotApi(TOKEN).send_message(111, "<pre>x</pre>")
    assert recorder.calls[0][0].full_url == f"{BASE}/sendMessage"
    assert recorder.payload() == {"chat_id": 111, "text": "<pre>x</pre>", "parse_mode": "HTML"}


@pytest.mark.parametrize(("url", "expected"), [("", False), ("https://example.invalid/hook", True)])
def test_webhook_is_set_reads_the_url_without_returning_it(
    monkeypatch: pytest.MonkeyPatch, url: str, expected: bool
) -> None:
    _install(monkeypatch, _ok({"url": url, "pending_update_count": 0}))
    assert UrllibTelegramBotApi(TOKEN).webhook_is_set() is expected


def test_ok_false_envelope_is_an_api_error(monkeypatch: pytest.MonkeyPatch) -> None:
    body = {"ok": False, "error_code": 400, "description": "Bad Request: message text is empty"}
    _install(monkeypatch, lambda request: json.dumps(body).encode("utf-8"))
    with pytest.raises(TelegramUnavailableError) as raised:
        UrllibTelegramBotApi(TOKEN).send_message(111, "")
    assert str(raised.value) == "API error 400 (Bad Request: message text is empty)"
    assert raised.value.status == 400
    assert not isinstance(raised.value, TelegramTokenRejectedError)


@pytest.mark.parametrize("code", [401, 404])
def test_rejected_token_is_its_own_error(monkeypatch: pytest.MonkeyPatch, code: int) -> None:
    _install(monkeypatch, _raise(_http_error(code, {"ok": False, "error_code": code, "description": "Unauthorized"})))
    with pytest.raises(TelegramTokenRejectedError) as raised:
        UrllibTelegramBotApi(TOKEN).get_me()
    assert str(raised.value) == f"API error {code} (Unauthorized)"
    assert raised.value.status == code
    _assert_no_token(raised.value)


def test_http_409_and_429_keep_status_and_retry_after(monkeypatch: pytest.MonkeyPatch) -> None:
    conflict = {"ok": False, "error_code": 409, "description": "Conflict: terminated by other getUpdates request"}
    _install(monkeypatch, _raise(_http_error(409, conflict)))
    with pytest.raises(TelegramUnavailableError) as raised:
        UrllibTelegramBotApi(TOKEN).get_updates(None, 10)
    assert str(raised.value) == "API error 409 (Conflict: terminated by other getUpdates request)"
    assert (raised.value.status, raised.value.retry_after_s) == (409, None)
    too_many = {
        "ok": False,
        "error_code": 429,
        "description": "Too Many Requests: retry after 3",
        "parameters": {"retry_after": 3},
    }
    _install(monkeypatch, _raise(_http_error(429, too_many)))
    with pytest.raises(TelegramUnavailableError) as raised:
        UrllibTelegramBotApi(TOKEN).get_updates(None, 10)
    assert (raised.value.status, raised.value.retry_after_s) == (429, 3.0)


def test_http_error_without_json_body(monkeypatch: pytest.MonkeyPatch) -> None:
    error = urllib.error.HTTPError(
        f"{BASE}/getMe", 502, "Bad Gateway", http.client.HTTPMessage(), io.BytesIO(b"<html>bad gateway</html>")
    )
    _install(monkeypatch, _raise(error))
    with pytest.raises(TelegramUnavailableError) as raised:
        UrllibTelegramBotApi(TOKEN).get_me()
    assert str(raised.value) == "API error 502"
    _assert_no_token(raised.value)


@pytest.mark.parametrize(
    "exc",
    [
        urllib.error.URLError(f"cannot reach {BASE}/getUpdates"),
        urllib.error.URLError(f"cannot reach https://api.telegram.org/bot{QUOTED}/getUpdates"),
        http.client.InvalidURL(f"URL can't contain control characters. '/bot{TOKEN}/getMe' (found at least ' ')"),
        TimeoutError("timed out"),
        ConnectionResetError(10054, "connection reset"),
    ],
)
def test_network_errors_are_redacted_and_unchained(monkeypatch: pytest.MonkeyPatch, exc: Exception) -> None:
    _install(monkeypatch, _raise(exc))
    with pytest.raises(TelegramUnavailableError) as raised:
        UrllibTelegramBotApi(TOKEN).get_updates(None, 10)
    assert str(raised.value).startswith("network error (")
    assert raised.value.status is None
    _assert_no_token(raised.value)


def test_redacted_urls_keep_their_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, _raise(urllib.error.URLError(f"cannot reach {BASE}/getMe")))
    with pytest.raises(TelegramUnavailableError) as raised:
        UrllibTelegramBotApi(TOKEN).get_me()
    assert str(raised.value) == (
        "network error (<urlopen error cannot reach https://api.telegram.org/bot<redacted>/getMe>)"
    )


def test_invalid_json_response_is_a_network_error(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, lambda request: b"not json")
    with pytest.raises(TelegramUnavailableError) as raised:
        UrllibTelegramBotApi(TOKEN).get_me()
    assert str(raised.value).startswith("network error (")
    _assert_no_token(raised.value)


def test_error_messages_are_ascii(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, _raise(OSError("연결 실패 \U0001f357")))
    with pytest.raises(TelegramUnavailableError) as raised:
        UrllibTelegramBotApi(TOKEN).get_me()
    assert str(raised.value).isascii()


def test_adapter_repr_and_redact_never_show_the_token() -> None:
    assert TOKEN not in repr(UrllibTelegramBotApi(TOKEN))
    assert redact(f"a {TOKEN} b {QUOTED} c", TOKEN) == "a <redacted> b <redacted> c"
    assert redact("nothing secret", TOKEN) == "nothing secret"
    assert redact("text", "") == "text"
