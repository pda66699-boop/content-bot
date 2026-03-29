from __future__ import annotations

import json
import logging
import os
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .message_router import route_message_update
from .pipeline import process_update


LOGGER = logging.getLogger(__name__)


def get_secret_token() -> str:
    token = os.environ.get("TELEGRAM_WEBHOOK_SECRET", "").strip()
    if not token:
        raise RuntimeError(
            "TELEGRAM_WEBHOOK_SECRET must be set — webhook will not accept any requests without it"
        )
    return token


class TelegramWebhookHandler(BaseHTTPRequestHandler):
    server_version = "TelegramWebhook/0.1"

    def do_POST(self) -> None:  # noqa: N802
        try:
            secret = get_secret_token()
        except RuntimeError:
            LOGGER.error("TELEGRAM_WEBHOOK_SECRET is not set; rejecting all webhook requests")
            self.send_response(HTTPStatus.INTERNAL_SERVER_ERROR)
            self.end_headers()
            self.wfile.write(b"server misconfiguration")
            return

        incoming = self.headers.get("X-Telegram-Bot-Api-Secret-Token")
        if incoming != secret:
            self.send_response(HTTPStatus.FORBIDDEN)
            self.end_headers()
            self.wfile.write(b"forbidden")
            return

        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        try:
            payload = json.loads(body.decode("utf-8"))
        except json.JSONDecodeError:
            self.send_response(HTTPStatus.BAD_REQUEST)
            self.end_headers()
            self.wfile.write(b"invalid json")
            return

        handled_message = route_message_update(payload)
        record = None if handled_message else process_update(payload)
        self.send_response(HTTPStatus.OK)
        self.end_headers()
        if handled_message:
            self.wfile.write(b'{"ok":true,"processed":true,"kind":"message"}')
        elif record is None:
            self.wfile.write(b'{"ok":true,"processed":false}')
        else:
            self.wfile.write(b'{"ok":true,"processed":true}')

    def do_GET(self) -> None:  # noqa: N802
        self.send_response(HTTPStatus.OK)
        self.end_headers()
        self.wfile.write(b"telegram ingest webhook is running")

    def log_message(self, format: str, *args) -> None:  # noqa: A002
        LOGGER.debug(format, *args)


def run_webhook_server(host: str = "127.0.0.1", port: int = 8081) -> None:
    get_secret_token()  # fail fast if not configured
    server = ThreadingHTTPServer((host, port), TelegramWebhookHandler)
    LOGGER.info("Webhook server listening on http://%s:%s", host, port)
    server.serve_forever()
