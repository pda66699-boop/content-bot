#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from telegram_ingest.editorial_extractor import infer_editorial_metadata_from_post  # noqa: E402
from telegram_ingest.editorial_metadata import normalize_editorial_metadata  # noqa: E402
from telegram_ingest.memory_sync import write_posts_index  # noqa: E402


EDITORIAL_FIELDS = (
    "primary_thesis",
    "secondary_theses",
    "angle",
    "content_goal",
    "funnel_stage",
    "business_dimensions",
    "format_type",
    "novelty_window_days",
)


def load_jsonl_raw(path: Path) -> list[dict]:
    """Load raw JSONL rows without enriching them on read."""

    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def has_incomplete_editorial_metadata(row: dict) -> bool:
    """Return True when a row is missing semantic metadata or keeps only defaults."""

    normalized = normalize_editorial_metadata(row)
    raw_missing = any(field not in row for field in EDITORIAL_FIELDS)
    if raw_missing:
        return True

    if not normalized.get("primary_thesis"):
        return True
    if not normalized.get("angle"):
        return True
    if not normalized.get("content_goal"):
        return True
    if not normalized.get("funnel_stage"):
        return True
    if not normalized.get("format_type"):
        return True
    if not normalized.get("business_dimensions"):
        return True
    return False


def enrich_row(row: dict, prefer_llm: bool = True) -> tuple[dict, bool]:
    """Return an enriched row and whether semantic metadata changed materially."""

    before = normalize_editorial_metadata(row)
    after = infer_editorial_metadata_from_post(before, prefer_llm=prefer_llm)
    changed = any(before.get(field) != after.get(field) for field in EDITORIAL_FIELDS)
    return after, changed


def build_arg_parser() -> argparse.ArgumentParser:
    """Create CLI arguments for archival editorial enrichment."""

    parser = argparse.ArgumentParser(
        description="Retro-enrich posts_index.jsonl with editorial metadata for semantic planning."
    )
    parser.add_argument(
        "--index",
        type=Path,
        default=Path("content-bot/memory/posts_index.jsonl"),
        help="Path to posts_index.jsonl",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only report how many rows would be enriched without writing changes.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Process at most N incomplete rows. 0 means no limit.",
    )
    parser.add_argument(
        "--mode",
        choices=("rules-only", "hybrid"),
        default="rules-only",
        help="Use local rules only or allow LLM classification fallback.",
    )
    return parser


def main() -> int:
    """Enrich archival posts with semantic editorial metadata safely."""

    args = build_arg_parser().parse_args()
    rows = load_jsonl_raw(args.index)
    if not rows:
        print(f"No rows found in {args.index}")
        return 0

    prefer_llm = args.mode == "hybrid"
    processed = 0
    changed = 0
    enriched_rows: list[dict] = []

    for row in rows:
        current = row
        if has_incomplete_editorial_metadata(row) and (args.limit <= 0 or processed < args.limit):
            current, row_changed = enrich_row(row, prefer_llm=prefer_llm)
            processed += 1
            changed += int(row_changed)
        else:
            current = normalize_editorial_metadata(row)
        enriched_rows.append(current)

    if args.dry_run:
        print(
            f"Dry run: scanned {len(rows)} rows, processed {processed} incomplete rows, "
            f"{changed} rows would be updated (mode={args.mode})."
        )
        return 0

    write_posts_index(enriched_rows)
    print(
        f"Updated {changed} rows in {args.index} "
        f"(processed {processed} incomplete rows, mode={args.mode})."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
