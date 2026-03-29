#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json

from telegram_ingest.publishable_engine import generate_publishable_post


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate the best publishable Telegram post from the full pipeline.")
    parser.add_argument("--theme", help="User-proposed theme", default=None)
    parser.add_argument("--angle", help="Optional explicit angle", default=None)
    parser.add_argument("--goal", help="Business goal: expert, money, image", default="expert")
    parser.add_argument("--draft-count", type=int, default=2, help="How many draft variants to compare")
    args = parser.parse_args()

    payload = generate_publishable_post(
        theme=args.theme,
        angle=args.angle,
        business_goal=args.goal,
        draft_count=max(1, min(args.draft_count, 3)),
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
