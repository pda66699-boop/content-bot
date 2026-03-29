from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from .config import RAW_UPDATES_DIR, SQLITE_PATH
from .editorial_metadata import normalize_editorial_metadata


SCHEMA = """
CREATE TABLE IF NOT EXISTS raw_updates (
  update_id INTEGER PRIMARY KEY,
  update_type TEXT NOT NULL,
  telegram_chat_id TEXT,
  telegram_message_id INTEGER,
  payload_json TEXT NOT NULL,
  received_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS published_posts (
  telegram_chat_id TEXT NOT NULL,
  telegram_message_id INTEGER NOT NULL,
  published_at TEXT NOT NULL,
  edited_at TEXT,
  source TEXT NOT NULL,
  title_hook TEXT NOT NULL,
  body_text TEXT NOT NULL,
  body_summary TEXT NOT NULL,
  media_type TEXT NOT NULL,
  hashtags_json TEXT NOT NULL,
  mentions_ai INTEGER NOT NULL,
  cta_present INTEGER NOT NULL,
  content_record_json TEXT NOT NULL,
  PRIMARY KEY (telegram_chat_id, telegram_message_id)
);
"""


def connect() -> sqlite3.Connection:
    SQLITE_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(SQLITE_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def persist_raw_update(update_id: int, update_type: str, chat_id: str | None, message_id: int | None, payload: dict, received_at: str) -> None:
    RAW_UPDATES_DIR.mkdir(parents=True, exist_ok=True)
    (RAW_UPDATES_DIR / f"{update_id}.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    with connect() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO raw_updates (
              update_id, update_type, telegram_chat_id, telegram_message_id, payload_json, received_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                update_id,
                update_type,
                chat_id,
                message_id,
                json.dumps(payload, ensure_ascii=False),
                received_at,
            ),
        )


def upsert_published_post(record: dict) -> None:
    """Persist a published post snapshot to SQLite without changing the schema."""

    record = normalize_editorial_metadata(record)
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO published_posts (
              telegram_chat_id, telegram_message_id, published_at, edited_at, source,
              title_hook, body_text, body_summary, media_type, hashtags_json,
              mentions_ai, cta_present, content_record_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(telegram_chat_id, telegram_message_id) DO UPDATE SET
              edited_at=excluded.edited_at,
              source=excluded.source,
              title_hook=excluded.title_hook,
              body_text=excluded.body_text,
              body_summary=excluded.body_summary,
              media_type=excluded.media_type,
              hashtags_json=excluded.hashtags_json,
              mentions_ai=excluded.mentions_ai,
              cta_present=excluded.cta_present,
              content_record_json=excluded.content_record_json
            """,
            (
                record["telegram_chat_id"],
                record["telegram_message_id"],
                record["published_at"],
                record["edited_at"],
                record["source"],
                record["title_hook"],
                record["body_text"],
                record["body_summary"],
                record.get("media_type", "text"),
                json.dumps(record["hashtags"], ensure_ascii=False),
                int(record["mentions_ai"]),
                int(record["cta_present"]),
                json.dumps(record, ensure_ascii=False),
            ),
        )
