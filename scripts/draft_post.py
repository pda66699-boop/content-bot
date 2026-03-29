#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json

from telegram_ingest.writer_engine import generate_drafts


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate 1-2 Telegram post drafts from planner memory.")
    parser.add_argument("--theme", help="User-proposed theme", default=None)
    parser.add_argument("--angle", help="Optional explicit angle for the theme", default=None)
    parser.add_argument("--goal", help="Business goal: expert, money, image", default="expert")
    parser.add_argument("--count", help="How many drafts to generate", type=int, default=2)
    args = parser.parse_args()

    result = generate_drafts(
        theme=args.theme,
        angle=args.angle,
        business_goal=args.goal,
        count=max(1, min(args.count, 3)),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
