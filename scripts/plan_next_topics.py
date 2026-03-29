#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from telegram_ingest.editorial_evaluation import build_planner_review  # noqa: E402
from telegram_ingest.planner_engine import plan_next_topics  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Plan next Telegram post topics from content memory.")
    parser.add_argument("--theme", help="User-proposed theme to evaluate", default=None)
    parser.add_argument("--goal", help="Business goal: expert, money, image", default="expert")
    parser.add_argument("--debug", action="store_true", help="Show semantic review data for the planner output.")
    args = parser.parse_args()

    if args.debug:
        result = build_planner_review(user_theme=args.theme, business_goal=args.goal)
    else:
        result = plan_next_topics(user_theme=args.theme, business_goal=args.goal)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
