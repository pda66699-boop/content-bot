#!/usr/bin/env python3
from __future__ import annotations

import argparse
import logging

from telegram_ingest.polling_runner import run_polling


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    parser = argparse.ArgumentParser(description="Run Telegram polling ingest for channel posts.")
    parser.add_argument("--timeout", type=int, default=30, help="Long polling timeout in seconds")
    parser.add_argument("--idle-sleep", type=float, default=1.0, help="Sleep between empty polls")
    parser.add_argument(
        "--keep-webhook",
        action="store_true",
        help="Do not call deleteWebhook before polling",
    )
    args = parser.parse_args()

    run_polling(
        timeout=args.timeout,
        idle_sleep=args.idle_sleep,
        reset_webhook=not args.keep_webhook,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
