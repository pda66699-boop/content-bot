#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json

from telegram_ingest.command_interface import (
    build_note_command_result,
    build_post_command_result,
    format_note_command_response,
    format_post_command_response,
    parse_post_command,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Convenience /post command runner for local CLI and future Telegram bot.")
    parser.add_argument("text", help="Command text, for example: /post Типичные кризисы на разных стадиях бизнеса")
    parser.add_argument("--goal", default="expert", help="Business goal: expert, money, image")
    parser.add_argument("--json", action="store_true", help="Print raw JSON payload instead of formatted text")
    args = parser.parse_args()

    parsed = parse_post_command(args.text)
    if parsed["command"] == "post":
        result = build_post_command_result(theme=parsed["theme"], goal=args.goal)
        if args.json:
            print(json.dumps(result.payload, ensure_ascii=False, indent=2))
        else:
            print(format_post_command_response(result))
        return 0

    if parsed["command"] == "note":
        result = build_note_command_result(note=parsed["theme"])
        if args.json:
            print(json.dumps(result.payload, ensure_ascii=False, indent=2))
        else:
            print(format_note_command_response(result))
        return 0

    raise SystemExit("Expected /post or /note command")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
