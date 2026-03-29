from __future__ import annotations

import json
import os
import socket
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


class TelegramBotApiError(RuntimeError):
    pass


def get_bot_token() -> str:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise TelegramBotApiError("TELEGRAM_BOT_TOKEN is not set")
    return token


def build_api_url(method: str) -> str:
    token = get_bot_token()
    return f"https://api.telegram.org/bot{token}/{method}"


def call_api(method: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    data = None
    headers = {"Content-Type": "application/json; charset=utf-8"}
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    request = urllib.request.Request(
        build_api_url(method),
        data=data,
        headers=headers,
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise TelegramBotApiError(f"Telegram API {method} failed: {exc.code} {detail}") from exc
    except urllib.error.URLError as exc:
        raise TelegramBotApiError(f"Telegram API {method} connection failed: {exc}") from exc
    except (TimeoutError, socket.timeout) as exc:
        raise TelegramBotApiError(f"Telegram API {method} timed out") from exc

    parsed = json.loads(body)
    if not parsed.get("ok"):
        raise TelegramBotApiError(f"Telegram API {method} returned error: {parsed}")
    return parsed


def get_updates(offset: int | None = None, timeout: int = 30, allowed_updates: list[str] | None = None) -> list[dict[str, Any]]:
    payload: dict[str, Any] = {"timeout": timeout}
    if offset is not None:
        payload["offset"] = offset
    if allowed_updates is not None:
        payload["allowed_updates"] = allowed_updates
    result = call_api("getUpdates", payload)
    return result.get("result", [])


def set_webhook(url: str, secret_token: str | None = None, allowed_updates: list[str] | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {"url": url}
    if secret_token:
        payload["secret_token"] = secret_token
    if allowed_updates is not None:
        payload["allowed_updates"] = allowed_updates
    return call_api("setWebhook", payload)


def delete_webhook(drop_pending_updates: bool = False) -> dict[str, Any]:
    return call_api("deleteWebhook", {"drop_pending_updates": drop_pending_updates})


def send_message(chat_id: int | str, text: str, parse_mode: str | None = None, disable_web_page_preview: bool = True) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "chat_id": chat_id,
        "text": text,
        "disable_web_page_preview": disable_web_page_preview,
    }
    if parse_mode:
        payload["parse_mode"] = parse_mode
    return call_api("sendMessage", payload)


def send_message_with_markup(
    chat_id: int | str,
    text: str,
    reply_markup: dict[str, Any],
    parse_mode: str | None = None,
    disable_web_page_preview: bool = True,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "chat_id": chat_id,
        "text": text,
        "reply_markup": reply_markup,
        "disable_web_page_preview": disable_web_page_preview,
    }
    if parse_mode:
        payload["parse_mode"] = parse_mode
    return call_api("sendMessage", payload)


def answer_callback_query(callback_query_id: str, text: str | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {"callback_query_id": callback_query_id}
    if text:
        payload["text"] = text
    return call_api("answerCallbackQuery", payload)
