#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from telegram_ingest.polish_engine import polish_text


def main() -> int:
    parser = argparse.ArgumentParser(description="Polish a Telegram draft post into a more natural final version.")
    parser.add_argument("--file", help="Path to UTF-8 text file with draft", default=None)
    parser.add_argument("--text", help="Inline text to polish", default=None)
    args = parser.parse_args()

    if args.file:
        text = Path(args.file).read_text(encoding="utf-8")
    elif args.text:
        text = args.text
    else:
        raise SystemExit("Provide --file or --text")

    print(json.dumps(polish_text(text), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
