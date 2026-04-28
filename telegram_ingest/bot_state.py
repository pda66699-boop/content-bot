from __future__ import annotations

import json
import threading
from pathlib import Path

from .config import MEMORY_DIR


STATE_PATH = MEMORY_DIR / "telegram_ui_state.json"
STATE_LOCK = threading.RLock()


def load_all_state() -> dict:
    with STATE_LOCK:
        if not STATE_PATH.exists():
            return {}
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))


def save_all_state(payload: dict) -> None:
    with STATE_LOCK:
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        temp_path = STATE_PATH.with_suffix(".tmp")
        temp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temp_path.replace(STATE_PATH)


def _key(chat_id: int | str, user_id: int | str | None) -> str:
    return f"{chat_id}:{user_id or 'unknown'}"


def get_session(chat_id: int | str, user_id: int | str | None) -> dict:
    with STATE_LOCK:
        state = load_all_state()
        return state.get(_key(chat_id, user_id), {})


def save_session(chat_id: int | str, user_id: int | str | None, session: dict) -> None:
    with STATE_LOCK:
        state = load_all_state()
        state[_key(chat_id, user_id)] = session
        save_all_state(state)


def clear_session_field(chat_id: int | str, user_id: int | str | None, field: str) -> dict:
    with STATE_LOCK:
        state = load_all_state()
        key = _key(chat_id, user_id)
        session = state.get(key, {})
        session.pop(field, None)
        state[key] = session
        save_all_state(state)
        return session


# Fields that hold generated text and must be cleared on service start.
# If writer.md or stop_words.json changed between restarts, stale drafts
# could contain forbidden phrases and would be served to the user via
# "улучшить", "анализ" or revision flows without passing through the guard.
_STALE_DRAFT_FIELDS = ("last_generated", "last_analyzed_post", "last_improvement_options")


def startup_clear_stale_drafts() -> int:
    """Drop all persisted draft fields from every session at service startup.

    Called once by the polling runner before entering the update loop so that
    any drafts generated under a previous version of writer.md / stop_words.json
    cannot be served in follow-up actions (revision, улучшить, анализ).

    Returns the number of sessions that were modified.
    """
    import logging
    logger = logging.getLogger(__name__)
    with STATE_LOCK:
        state = load_all_state()
        modified = 0
        for key, session in state.items():
            if any(field in session for field in _STALE_DRAFT_FIELDS):
                for field in _STALE_DRAFT_FIELDS:
                    session.pop(field, None)
                state[key] = session
                modified += 1
        if modified:
            save_all_state(state)
        logger.info("[STARTUP] startup_clear_stale_drafts: cleared draft fields in %d session(s)", modified)
        print(f"[STARTUP] Cleared stale draft fields from {modified} session(s)", flush=True)
        return modified
