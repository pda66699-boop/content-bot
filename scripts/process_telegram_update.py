#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from telegram_ingest.pipeline import process_update


def load_payload(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Process one Telegram update JSON file into content memory.")
    parser.add_argument("payload", type=Path, help="Path to Telegram update JSON")
    args = parser.parse_args()

    record = process_update(load_payload(args.payload))
    if record is None:
        print("No channel post content found in payload")
        return 0

    print(json.dumps(record, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
