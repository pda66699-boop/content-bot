#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from telegram_ingest.editorial_evaluation import (  # noqa: E402
    build_planner_batch_review,
    build_extractor_review_for_post,
    build_extractor_review_for_topic,
    load_cases,
)
from telegram_ingest.memory_sync import load_posts_index  # noqa: E402


def _truncate(value: object, width: int) -> str:
    """Render one cell into a short table-safe string."""

    if isinstance(value, list):
        text = "; ".join(str(item) for item in value)
    else:
        text = str(value or "")
    text = " ".join(text.split())
    return text if len(text) <= width else f"{text[: width - 1]}…"


def _render_table(rows: list[dict]) -> str:
    """Render semantic review rows as a compact plain-text table."""

    headers = [
        ("kind", 6),
        ("label", 24),
        ("primary_thesis", 30),
        ("angle", 28),
        ("novelty_status", 18),
        ("funnel_stage", 16),
        ("format_type", 12),
        ("matched_posts", 30),
        ("reason", 40),
    ]
    lines = [
        " | ".join(name.ljust(width) for name, width in headers),
        "-+-".join("-" * width for _, width in headers),
    ]
    for row in rows:
        matched_posts = [
            f"{item.get('date') or '?'}:{item.get('title_hook') or item.get('primary_theme') or '?'}"
            for item in row.get("matched_posts", [])[:2]
        ]
        cells = {
            "kind": row.get("kind"),
            "label": row.get("label"),
            "primary_thesis": row.get("primary_thesis"),
            "angle": row.get("angle"),
            "novelty_status": row.get("novelty_status"),
            "funnel_stage": row.get("funnel_stage"),
            "format_type": row.get("format_type"),
            "matched_posts": matched_posts,
            "reason": row.get("reason"),
        }
        lines.append(" | ".join(_truncate(cells[name], width).ljust(width) for name, width in headers))
    return "\n".join(lines)


def _render_planner_table(rows: list[dict]) -> str:
    """Render ranked planner-review rows as a compact plain-text table."""

    headers = [
        ("rank", 4),
        ("theme", 24),
        ("primary_thesis", 28),
        ("angle", 24),
        ("novelty_status", 18),
        ("admissibility", 16),
        ("score", 6),
        ("matched_posts", 30),
        ("reason", 42),
    ]
    lines = [
        " | ".join(name.ljust(width) for name, width in headers),
        "-+-".join("-" * width for _, width in headers),
    ]
    for row in rows:
        matched_posts = [
            f"{item.get('date') or '?'}:{item.get('title_hook') or item.get('primary_theme') or '?'}"
            for item in row.get("matched_posts", [])[:2]
        ]
        cells = {
            "rank": row.get("rank"),
            "theme": row.get("theme"),
            "primary_thesis": row.get("primary_thesis"),
            "angle": row.get("angle"),
            "novelty_status": row.get("novelty_status"),
            "admissibility": row.get("editorial_admissibility"),
            "score": row.get("score"),
            "matched_posts": matched_posts,
            "reason": row.get("reason"),
        }
        lines.append(" | ".join(_truncate(cells[name], width).ljust(width) for name, width in headers))
    return "\n".join(lines)


def _extract_topics(cases: list[dict]) -> list[str]:
    """Return a flat topic list from mixed JSON/JSONL review payloads."""

    topics: list[str] = []
    for case in cases:
        if case.get("topics"):
            topics.extend(str(topic).strip() for topic in case.get("topics") or [] if str(topic).strip())
        elif case.get("topic"):
            topics.append(str(case.get("topic") or "").strip())
        elif case.get("label") and case.get("kind") == "topic":
            topics.append(str(case.get("label") or "").strip())
    return [topic for topic in topics if topic]


def build_arg_parser() -> argparse.ArgumentParser:
    """Create CLI arguments for semantic batch review."""

    parser = argparse.ArgumentParser(
        description="Batch-review editorial semantic extraction and novelty classification."
    )
    parser.add_argument("--input", type=Path, help="Path to JSON or JSONL with topic/post cases.")
    parser.add_argument("--topic", action="append", default=[], help="Add a topic directly from CLI. Repeatable.")
    parser.add_argument(
        "--mode",
        choices=("rules-only", "hybrid"),
        default="rules-only",
        help="Use local rules only or allow LLM classifier fallback.",
    )
    parser.add_argument(
        "--format",
        choices=("table", "json"),
        default="table",
        help="Render a compact table or full JSON.",
    )
    parser.add_argument(
        "--review-type",
        choices=("extractor", "planner"),
        default="extractor",
        help="Review semantic extraction only or planner-style ranking for a batch of topics.",
    )
    parser.add_argument("--goal", default="expert", help="Planner business goal for ranking mode.")
    parser.add_argument("--compare", action="store_true", help="In planner mode, show ranking order for the provided topics.")
    parser.add_argument("--limit", type=int, default=0, help="Process at most N cases. 0 means no limit.")
    return parser


def main() -> int:
    """Review editorial semantics for a batch of topics or post cards."""

    args = build_arg_parser().parse_args()
    if not args.input and not args.topic:
        raise SystemExit("Pass --input or at least one --topic.")

    cases = load_cases(args.input) if args.input else []
    if args.limit > 0:
        cases = cases[: args.limit]
    archive = load_posts_index()
    prefer_llm = args.mode == "hybrid"

    if args.review_type == "planner":
        topics = list(args.topic) + _extract_topics(cases)
        if args.limit > 0:
            topics = topics[: args.limit]
        review = build_planner_batch_review(topics, archive=archive, business_goal=args.goal)
        if args.format == "json":
            print(json.dumps(review, ensure_ascii=False, indent=2))
        else:
            print(_render_planner_table(review.get("topics", [])))
            if args.compare:
                print()
                print("Ranking order:")
                for index, theme in enumerate(review.get("ranking_order", []), start=1):
                    print(f"{index}. {theme}")
        return 0

    reviewed: list[dict] = []
    for case in cases:
        if case.get("topic"):
            reviewed.append(
                build_extractor_review_for_topic(
                    str(case.get("topic") or ""),
                    context=case.get("context") if isinstance(case.get("context"), dict) else None,
                    archive=archive,
                    prefer_llm=prefer_llm,
                )
            )
            continue

        card = dict(case.get("card") or {})
        if case.get("text") and "body_text" not in card:
            card["body_text"] = case["text"]
        if case.get("title_hook") and "title_hook" not in card:
            card["title_hook"] = case["title_hook"]
        if case.get("primary_theme") and "primary_theme" not in card:
            card["primary_theme"] = case["primary_theme"]
        reviewed.append(build_extractor_review_for_post(card, archive=archive, prefer_llm=prefer_llm))

    for topic in args.topic:
        reviewed.append(build_extractor_review_for_topic(topic, archive=archive, prefer_llm=prefer_llm))

    if args.format == "json":
        print(json.dumps(reviewed, ensure_ascii=False, indent=2))
    else:
        print(_render_table(reviewed))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
