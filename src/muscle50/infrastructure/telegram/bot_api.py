"""Telegram Bot API over the standard library (`urllib`), long polling only.

This adapter is the only code that holds the bot token. It builds
``https://api.telegram.org/bot<token>/<method>``, so every failure is turned into a
`TelegramUnavailableError` whose message is redacted and ASCII. The error is raised outside the
``except`` block, so it carries no chained original exception (and no URL) at all.
"""

from __future__ import annotations

import http.client
import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from muscle50.application.telegram_bot import (
    BotIdentity,
    IncomingMessage,
    IncomingUpdate,
    TelegramTokenRejectedError,
    TelegramUnavailableError,
)

API_BASE_URL = "https://api.telegram.org"
REQUEST_TIMEOUT_S = 15
# getUpdates holds the request open for its long-poll timeout; the HTTP timeout allows for that.
POLL_HTTP_MARGIN_S = 10
REDACTED = "<redacted>"


def redact(text: str, token: str) -> str:
    """`text` with the token, raw or URL-quoted, replaced by ``<redacted>``."""
    if not token:
        return text
    for secret in (token, urllib.parse.quote(token, safe="")):
        text = text.replace(secret, REDACTED)
    return text


class UrllibTelegramBotApi:
    __slots__ = ("_token",)

    def __init__(self, token: str) -> None:
        self._token = token

    def __repr__(self) -> str:
        return f"UrllibTelegramBotApi(token={REDACTED})"

    def get_me(self) -> BotIdentity:
        result = self._call("getMe", {}, REQUEST_TIMEOUT_S)
        if not isinstance(result, dict):
            raise TelegramUnavailableError("unexpected getMe response")
        bot_id, username = result.get("id"), result.get("username")
        if type(bot_id) is not int or not isinstance(username, str):
            raise TelegramUnavailableError("unexpected getMe response")
        return BotIdentity(bot_id, username)

    def webhook_is_set(self) -> bool:
        result = self._call("getWebhookInfo", {}, REQUEST_TIMEOUT_S)
        if not isinstance(result, dict):
            raise TelegramUnavailableError("unexpected getWebhookInfo response")
        url = result.get("url")
        return isinstance(url, str) and url != ""

    def get_updates(self, offset: int | None, timeout_s: int) -> tuple[IncomingUpdate, ...]:
        payload: dict[str, Any] = {"timeout": timeout_s, "allowed_updates": ["message"]}
        if offset is not None:
            payload["offset"] = offset
        result = self._call("getUpdates", payload, timeout_s + POLL_HTTP_MARGIN_S)
        if not isinstance(result, list):
            raise TelegramUnavailableError("unexpected getUpdates response")
        return tuple(_update(item) for item in result)

    def send_message(self, chat_id: int, html: str) -> None:
        payload: dict[str, Any] = {"chat_id": chat_id, "text": html, "parse_mode": "HTML"}
        if "<a href=" in html:
            # A Garmin Connect link would otherwise add a preview card to every summary.
            payload["link_preview_options"] = {"is_disabled": True}
        self._call("sendMessage", payload, REQUEST_TIMEOUT_S)

    def _call(self, method: str, payload: dict[str, Any], timeout_s: float) -> Any:
        request = urllib.request.Request(
            f"{API_BASE_URL}/bot{self._token}/{method}",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        failure: TelegramUnavailableError | None = None
        document: Any = None
        try:
            with urllib.request.urlopen(request, timeout=timeout_s) as response:
                body = response.read()
            document = json.loads(body.decode("utf-8"))
        except urllib.error.HTTPError as exc:
            failure = self._http_failure(exc.code, _error_body(exc))
        except (urllib.error.URLError, http.client.HTTPException, OSError, ValueError) as exc:
            failure = TelegramUnavailableError(self._clean(f"network error ({exc})"))
        if failure is not None:
            raise failure
        if not isinstance(document, dict) or document.get("ok") is not True:
            error_code = document.get("error_code") if isinstance(document, dict) else None
            raise self._http_failure(error_code if type(error_code) is int else None, document)
        return document.get("result")

    def _http_failure(self, status: int | None, document: Any) -> TelegramUnavailableError:
        description = document.get("description") if isinstance(document, dict) else None
        parameters = document.get("parameters") if isinstance(document, dict) else None
        retry_after = parameters.get("retry_after") if isinstance(parameters, dict) else None
        label = f"API error {status}" if status is not None else "API error"
        message = self._clean(f"{label} ({description})" if isinstance(description, str) else label)
        retry_after_s = float(retry_after) if isinstance(retry_after, int | float) and retry_after >= 0 else None
        if status in (401, 404):
            return TelegramTokenRejectedError(message, status=status, retry_after_s=retry_after_s)
        return TelegramUnavailableError(message, status=status, retry_after_s=retry_after_s)

    def _clean(self, text: str) -> str:
        return redact(text, self._token).encode("ascii", "backslashreplace").decode("ascii")


def _error_body(exc: urllib.error.HTTPError) -> Any:
    try:
        return json.loads(exc.read().decode("utf-8"))
    except (OSError, ValueError, http.client.HTTPException):
        return None


def _update(item: Any) -> IncomingUpdate:
    if not isinstance(item, dict) or type(item.get("update_id")) is not int:
        raise TelegramUnavailableError("unexpected getUpdates response")
    message = item.get("message")
    if not isinstance(message, dict):
        return IncomingUpdate(item["update_id"], None)
    chat = message.get("chat")
    chat_id = chat.get("id") if isinstance(chat, dict) else None
    sent_at = message.get("date")
    if type(chat_id) is not int or type(sent_at) is not int:
        return IncomingUpdate(item["update_id"], None)
    text = message.get("text")
    return IncomingUpdate(item["update_id"], IncomingMessage(chat_id, text if isinstance(text, str) else None, sent_at))
