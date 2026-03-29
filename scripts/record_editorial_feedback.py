#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json

from telegram_ingest.editorial_memory import record_editorial_feedback


def main() -> None:
    parser = argparse.ArgumentParser(description="Append editorial feedback to long-term memory.")
    parser.add_argument("summary", help="Short feedback summary")
    parser.add_argument("--category", default="quality", help="style / quality / terminology / positioning / funnel")
    parser.add_argument("--impact", default="medium", help="low / medium / high")
    parser.add_argument("--status", default="active", help="active / resolved / archived")
    parser.add_argument("--source", default="user", help="user / analyst / system")
    args = parser.parse_args()

    row = record_editorial_feedback(
        summary=args.summary,
        category=args.category,
        impact=args.impact,
        status=args.status,
        source=args.source,
    )
    print(json.dumps(row, ensure_ascii=False))


if __name__ == "__main__":
    main()
