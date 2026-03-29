#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from telegram_ingest.critic_engine import critic_review  # noqa: E402
from telegram_ingest.editorial_evaluation import build_critic_review_debug  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Critic review for a Telegram draft post.")
    parser.add_argument("--file", help="Path to UTF-8 text file with draft", default=None)
    parser.add_argument("--text", help="Inline text to review", default=None)
    parser.add_argument("--debug", action="store_true", help="Include semantic extractor and novelty debug fields.")
    args = parser.parse_args()

    if args.file:
        text = Path(args.file).read_text(encoding="utf-8")
    elif args.text:
        text = args.text
    else:
        raise SystemExit("Provide --file or --text")

    payload = build_critic_review_debug(text) if args.debug else critic_review(text)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
