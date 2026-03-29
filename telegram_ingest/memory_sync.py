from __future__ import annotations

import json
import logging
import threading
from pathlib import Path

from .config import POSTS_INDEX_PATH
from .editorial_metadata import normalize_editorial_metadata

POSTS_INDEX_LOCK = threading.RLock()


LOGGER = logging.getLogger(__name__)


def load_posts_index() -> list[dict]:
    """Load post cards from JSONL and soft-normalize editorial metadata."""

    with POSTS_INDEX_LOCK:
        if not POSTS_INDEX_PATH.exists():
            return []
        rows = []
        for lineno, line in enumerate(POSTS_INDEX_PATH.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            try:
                rows.append(normalize_editorial_metadata(json.loads(line)))
            except json.JSONDecodeError as exc:
                LOGGER.warning("Skipping malformed line %d in posts_index.jsonl: %s", lineno, exc)
        return rows


def write_posts_index(rows: list[dict]) -> None:
    """Write JSONL post cards with normalized editorial metadata."""

    with POSTS_INDEX_LOCK:
        POSTS_INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
        temp_path = POSTS_INDEX_PATH.with_suffix(".tmp")
        temp_path.write_text(
            "".join(
                json.dumps(normalize_editorial_metadata(row), ensure_ascii=False) + "\n"
                for row in rows
            ),
            encoding="utf-8",
        )
        temp_path.replace(POSTS_INDEX_PATH)


def upsert_post_record(record: dict) -> None:
    """Insert or replace one post card in `posts_index.jsonl` safely."""

    record = normalize_editorial_metadata(record)
    with POSTS_INDEX_LOCK:
        rows = load_posts_index()
        replaced = False
        for index, existing in enumerate(rows):
            if existing["post_id"] == record["post_id"]:
                rows[index] = record
                replaced = True
                break
        if not replaced:
            rows.append(record)

        rows.sort(key=lambda row: (row["date"], row.get("time") or "00:00", row["post_id"]))
        write_posts_index(rows)
