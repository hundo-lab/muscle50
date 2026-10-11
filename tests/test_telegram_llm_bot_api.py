"""Telegram LLM v2 additions to the Bot API adapter: photo/caption/document parsing and `download_photo`.

Through a patched `urllib.request.urlopen` only (never the network). The file URL contains the token,
so every failure must be redacted and carry no chained exception.
"""

from __future__ import annotations

import json
import traceback
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

import pytest

from muscle50.application.telegram_bot import PHOTO_MAX_BYTES, IncomingMessage, TelegramUnavailableError
from muscle50.infrastructure.telegram.bot_api import UrllibTelegramBotApi

TOKEN = "123456789:AAFakeSyntheticToken_ab-cd"
QUOTED = urllib.parse.quote(TOKEN, safe="")


class Response:
    def __init__(self, body: bytes) -> None:
        self.body = body

    def __enter__(self) -> Response:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self, size: int = -1) -> bytes:
        return self.body if size < 0 else self.body[:size]


def _updates(monkeypatch: pytest.MonkeyPatch, message: dict[str, Any]) -> IncomingMessage:
    item = {"update_id": 7, "message": {"chat": {"id": 111}, "date": 1000, **message}}
    body = json.dumps({"ok": True, "result": [item]}).encode()
    monkeypatch.setattr(urllib.request, "urlopen", lambda request, timeout: Response(body))
    updates = UrllibTelegramBotApi(TOKEN).get_updates(None, 10)
    assert updates[0].message is not None
    return updates[0].message


def _size(file_id: str, size: int | None, width: int) -> dict[str, Any]:
    entry: dict[str, Any] = {"file_id": file_id, "file_unique_id": file_id, "width": width, "height": width}
    if size is not None:
        entry["file_size"] = size
    return entry


def test_text_message_is_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    assert _updates(monkeypatch, {"text": "/today"}) == IncomingMessage(111, "/today", 1000)


def test_photo_takes_the_largest_size_within_the_cap_and_the_caption(monkeypatch: pytest.MonkeyPatch) -> None:
    sizes = [_size("small", 1000, 90), _size("big", 300_000, 1280), _size("huge", PHOTO_MAX_BYTES + 1, 4000)]
    message = _updates(monkeypatch, {"photo": sizes, "caption": "저녁"})
    assert (message.text, message.photo_file_id, message.photo_size, message.caption) == (None, "big", 300_000, "저녁")
    assert message.photo_too_large is False


def test_photo_over_the_cap_and_image_documents_are_flagged(monkeypatch: pytest.MonkeyPatch) -> None:
    too_large = _updates(monkeypatch, {"photo": [_size("huge", PHOTO_MAX_BYTES + 1, 4000)]})
    assert (too_large.photo_file_id, too_large.photo_too_large) == (None, True)
    document = _updates(monkeypatch, {"document": {"file_id": "d", "mime_type": "image/png"}})
    assert (document.document_image, document.photo_file_id) == (True, None)
    pdf = _updates(monkeypatch, {"document": {"file_id": "d", "mime_type": "application/pdf"}})
    assert pdf.document_image is False


def test_download_photo_gets_the_file_path_then_the_bytes(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, str, float]] = []

    def urlopen(request: urllib.request.Request, timeout: float) -> Response:
        calls.append((request.get_method(), request.full_url, timeout))
        if request.full_url.endswith("/getFile"):
            assert isinstance(request.data, bytes) and json.loads(request.data) == {"file_id": "big"}
            return Response(
                json.dumps({"ok": True, "result": {"file_path": "photos/file_1.jpg", "file_size": 3}}).encode()
            )
        return Response(b"\xff\xd8\xff")

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    assert UrllibTelegramBotApi(TOKEN).download_photo("big", PHOTO_MAX_BYTES) == b"\xff\xd8\xff"
    assert calls == [
        ("POST", f"https://api.telegram.org/bot{TOKEN}/getFile", 15),
        ("GET", f"https://api.telegram.org/file/bot{TOKEN}/photos/file_1.jpg", 15),
    ]


def _assert_redacted(exc: BaseException) -> None:
    assert exc.__cause__ is None and exc.__context__ is None
    for text in (str(exc), repr(exc), "".join(traceback.format_exception(exc))):
        assert TOKEN not in text and QUOTED not in text and "api.telegram.org" not in text


@pytest.mark.parametrize("failure", ["http", "network", "size", "too_large_body", "no_path"])
def test_download_failures_are_redacted_without_a_chained_exception(
    monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    url = f"https://api.telegram.org/file/bot{TOKEN}/photos/file_1.jpg"

    def urlopen(request: urllib.request.Request, timeout: float) -> Response:
        if request.full_url.endswith("/getFile"):
            result: dict[str, Any] = {"file_path": "photos/file_1.jpg", "file_size": 10}
            if failure == "size":
                result["file_size"] = 11
            if failure == "no_path":
                result = {}
            return Response(json.dumps({"ok": True, "result": result}).encode())
        if failure == "http":
            raise urllib.error.HTTPError(url, 404, f"not found {url}", None, None)  # type: ignore[arg-type]
        if failure == "network":
            raise urllib.error.URLError(f"failed {url} {TOKEN}")
        return Response(b"x" * 11)

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    with pytest.raises(TelegramUnavailableError) as raised:
        UrllibTelegramBotApi(TOKEN).download_photo("big", 10)
    _assert_redacted(raised.value)
