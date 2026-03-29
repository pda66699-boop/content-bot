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
    accumulate_match_stats,
    compare_planner_prediction_to_expected,
    compare_prediction_to_expected,
    load_cases,
    predict_semantic_case,
)
from telegram_ingest.memory_sync import load_posts_index  # noqa: E402


def build_arg_parser() -> argparse.ArgumentParser:
    """Create CLI arguments for semantic golden-set evaluation."""

    parser = argparse.ArgumentParser(
        description="Evaluate editorial semantic extraction and novelty classification against a golden set."
    )
    parser.add_argument("--input", type=Path, required=True, help="Path to JSON or JSONL with expected labels.")
    parser.add_argument(
        "--mode",
        choices=("rules-only", "hybrid"),
        default="rules-only",
        help="Use local rules only or allow LLM classifier fallback.",
    )
    parser.add_argument("--limit", type=int, default=0, help="Process at most N cases. 0 means no limit.")
    return parser


def main() -> int:
    """Run a lightweight golden-set evaluation for editorial semantics."""

    args = build_arg_parser().parse_args()
    cases = load_cases(args.input)
    if args.limit > 0:
        cases = cases[: args.limit]
    archive = load_posts_index()
    prefer_llm = args.mode == "hybrid"

    comparisons: list[dict] = []
    rows: list[dict] = []
    for index, case in enumerate(cases, start=1):
        prediction = predict_semantic_case(case, archive=archive, prefer_llm=prefer_llm)
        expected = dict(case.get("expected") or {})
        if case.get("topics"):
            comparison = compare_planner_prediction_to_expected(prediction, expected)
        else:
            comparison = compare_prediction_to_expected(prediction, expected)
        comparisons.append(comparison)
        rows.append(
            {
                "index": index,
                "label": prediction.get("label"),
                "kind": prediction.get("kind"),
                "prediction": prediction,
                "expected": expected,
                "comparison": comparison,
            }
        )

    print(
        json.dumps(
            {
                "cases": len(rows),
                "mode": args.mode,
                "field_stats": accumulate_match_stats(comparisons),
                "rows": rows,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
