from __future__ import annotations

import json
import logging
from pathlib import Path

from .config import MEMORY_DIR


LOGGER = logging.getLogger(__name__)
OFFSET_PATH = MEMORY_DIR / "telegram_polling_offset.json"


def load_offset() -> int | None:
    if not OFFSET_PATH.exists():
        return None
    try:
        payload = json.loads(OFFSET_PATH.read_text(encoding="utf-8"))
        return payload.get("offset")
    except json.JSONDecodeError as exc:
        LOGGER.error("Corrupted polling offset file %s: %s — starting from None", OFFSET_PATH, exc)
        return None


def save_offset(offset: int) -> None:
    OFFSET_PATH.parent.mkdir(parents=True, exist_ok=True)
    temp_path = OFFSET_PATH.with_suffix(".tmp")
    temp_path.write_text(
        json.dumps({"offset": offset}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temp_path.replace(OFFSET_PATH)
