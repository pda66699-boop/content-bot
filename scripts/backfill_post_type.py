#!/usr/bin/env python3
"""
Ретроспективный прогон: заполняет поле post_type для записей в posts_index.jsonl
у которых это поле отсутствует или пустое.

Запускать вручную:
    python3 scripts/backfill_post_type.py [--dry-run]

Rule-based классификатор по признакам из спека v3 (без LLM).
Не трогает ранжирование, editorial gates или другие поля.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Добавляем корень проекта в sys.path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from telegram_ingest.planner_engine import infer_post_type
from telegram_ingest.memory_sync import load_posts_index, write_posts_index


def classify_record(record: dict) -> str:
    """Determine post_type from existing record fields using rule-based logic."""
    strategic_format = record.get("strategic_format") or ""
    content_pillar = record.get("content_pillar") or record.get("format") or "expert"
    cta_need = record.get("cta_type") or "none"
    source_kind = record.get("source") or "editorial"
    marketing_rubric = record.get("marketing_rubric") or ""

    # Normalise source_kind: channel posts aren't cases
    if source_kind in {"channel_post", "bot_manual_accept"}:
        source_kind = "editorial"

    # Fallback: infer strategic_format from available fields when missing
    if not strategic_format:
        body = (record.get("body_text") or record.get("body_summary") or "").lower()
        role = (record.get("content_role") or record.get("content_goal") or "").lower()
        pillar = content_pillar.lower()
        if role == "case" or "кейс" in body[:100]:
            strategic_format = "case_breakdown"
        elif pillar == "conversational":
            strategic_format = "practice_observation"
        elif any(tok in body[:200] for tok in ("не работает", "ловушка", "миф", "на самом деле")):
            strategic_format = "provocative_thesis"
        elif any(tok in body[:200] for tok in ("исследован", "согласно", "данные", "статистик")):
            strategic_format = "research_signal"

    # Normalise marketing_rubric fallback
    if not marketing_rubric:
        theme = (record.get("primary_theme") or "").lower()
        if any(tok in theme for tok in ("стабилизац", "потер", "контрол", "управляем", "процесс", "роль", "оргструкт")):
            marketing_rubric = "flagship_warmup"
        elif any(tok in theme for tok in ("диагност", "стад", "кризис", "перекос")):
            marketing_rubric = "diagnostic_entry"

    return infer_post_type(
        strategic_format=strategic_format,
        content_pillar=content_pillar,
        cta_need=cta_need,
        source_kind=source_kind,
        marketing_rubric=marketing_rubric,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill post_type in posts_index.jsonl")
    parser.add_argument("--dry-run", action="store_true", help="Print changes without writing")
    args = parser.parse_args()

    rows = load_posts_index()
    updated = 0
    type_counts: dict[str, int] = {}

    for record in rows:
        if record.get("post_type"):
            type_counts[record["post_type"]] = type_counts.get(record["post_type"], 0) + 1
            continue  # already set, skip

        post_type = classify_record(record)
        record["post_type"] = post_type
        type_counts[post_type] = type_counts.get(post_type, 0) + 1
        updated += 1
        if args.dry_run:
            print(f"  [{post_type}] {record.get('date', '?')} — {record.get('title_hook', '')[:60]}")

    if args.dry_run:
        print(f"\n--- DRY RUN: {updated} records would be updated ---")
        print("Type distribution:", type_counts)
    else:
        write_posts_index(rows)
        print(f"Updated {updated} records. Type distribution: {type_counts}")


if __name__ == "__main__":
    main()
