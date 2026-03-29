from __future__ import annotations

import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROMPTS_DIR = ROOT / "prompts"
SOURCE_MEMORY_DIR = ROOT / "memory"
MEMORY_DIR = Path(os.environ.get("CONTENT_BOT_MEMORY_DIR", SOURCE_MEMORY_DIR)).expanduser()
SQLITE_PATH = MEMORY_DIR / "telegram_ingest.sqlite3"
POSTS_INDEX_PATH = MEMORY_DIR / "posts_index.jsonl"
RAW_UPDATES_DIR = MEMORY_DIR / "raw_updates"
KNOWLEDGE_REGISTRY_PATH = MEMORY_DIR / "knowledge_registry.json"
TERMINOLOGY_REGISTRY_PATH = MEMORY_DIR / "terminology_registry.json"
EDITORIAL_FEEDBACK_PATH = MEMORY_DIR / "editorial_feedback_log.jsonl"
CONTENT_BACKLOG_PATH = MEMORY_DIR / "content_backlog.json"
SUMMARY_PATH = MEMORY_DIR / "posts_index_summary.md"
FEED_SNAPSHOT_PATH = MEMORY_DIR / "current_feed_snapshot.md"
