#!/usr/bin/env python3
from __future__ import annotations

import argparse

from telegram_ingest.webhook_server import run_webhook_server


def main() -> int:
    parser = argparse.ArgumentParser(description="Run local webhook server for Telegram channel post ingest.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8081)
    args = parser.parse_args()

    run_webhook_server(host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
