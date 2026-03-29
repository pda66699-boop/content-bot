from __future__ import annotations

import json
import logging

from .config import MEMORY_DIR


LOGGER = logging.getLogger(__name__)
OPEN_LOOPS_PATH = MEMORY_DIR / "open_loops.json"


def load_open_loops() -> list[dict]:
    if not OPEN_LOOPS_PATH.exists():
        return []
    try:
        return json.loads(OPEN_LOOPS_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        LOGGER.error("Corrupted open_loops.json: %s — returning empty list", exc)
        return []


def get_open_loops(statuses: tuple[str, ...] = ("open", "partially_closed")) -> list[dict]:
    return [loop for loop in load_open_loops() if loop.get("status") in statuses]


def get_high_priority_open_loops() -> list[dict]:
    loops = get_open_loops()
    loops.sort(
        key=lambda item: (
            0 if item.get("priority") == "high" else 1 if item.get("priority") == "medium" else 2,
            item.get("date", ""),
        ),
        reverse=False,
    )
    return loops


def get_open_loops_chronological(reverse: bool = True) -> list[dict]:
    loops = get_open_loops()
    loops.sort(key=lambda item: item.get("date", ""), reverse=reverse)
    return loops
