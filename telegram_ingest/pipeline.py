from __future__ import annotations

from datetime import datetime, timezone

from .annotate import annotate_post
from .editorial_extractor import infer_editorial_metadata_from_post
from .memory_sync import upsert_post_record
from .normalize import extract_message, normalize_update, detect_media_type
from .store import persist_raw_update, upsert_published_post


def process_update(update: dict) -> dict | None:
    update_id = update.get("update_id")
    extracted = extract_message(update)
    if update_id is None or extracted is None:
        return None

    update_type, message = extracted
    received_at = datetime.now(tz=timezone.utc).isoformat()
    persist_raw_update(
        update_id=update_id,
        update_type=update_type,
        chat_id=str(message["chat"]["id"]) if message.get("chat") else None,
        message_id=message.get("message_id"),
        payload=update,
        received_at=received_at,
    )

    normalized = normalize_update(update)
    if normalized is None:
        return None

    annotated = annotate_post(normalized)
    record = infer_editorial_metadata_from_post(annotated.to_record())
    media_type = detect_media_type(message)
    db_record = dict(record)
    db_record["media_type"] = media_type

    upsert_published_post(db_record)
    upsert_post_record(record)
    return record
