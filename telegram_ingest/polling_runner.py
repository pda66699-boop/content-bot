from __future__ import annotations

import logging
import time

from .bot_api import TelegramBotApiError, delete_webhook, get_updates
from .bot_state import startup_clear_stale_drafts
from .message_router import route_message_update
from .pipeline import process_update
from .runtime import load_offset, save_offset


LOGGER = logging.getLogger(__name__)
DEFAULT_ALLOWED_UPDATES = ["channel_post", "edited_channel_post", "message", "callback_query"]


def run_polling(timeout: int = 30, idle_sleep: float = 1.0, reset_webhook: bool = True) -> None:
    # Clear draft fields from all sessions so that any text generated under a
    # previous version of writer.md / stop_words.json cannot be served without
    # re-running the guard.
    startup_clear_stale_drafts()

    if reset_webhook:
        delete_webhook(drop_pending_updates=False)

    offset = load_offset()
    while True:
        try:
            updates = get_updates(
                offset=offset,
                timeout=timeout,
                allowed_updates=DEFAULT_ALLOWED_UPDATES,
            )
        except TelegramBotApiError as exc:
            LOGGER.warning("Polling error: %s", exc)
            time.sleep(5)
            continue

        if not updates:
            time.sleep(idle_sleep)
            continue

        for update in updates:
            update_id = update.get("update_id")
            try:
                handled_message = route_message_update(update)
                if not handled_message:
                    process_update(update)
                LOGGER.info("Processed update_id=%s", update_id)
            except (KeyboardInterrupt, SystemExit):
                raise
            except Exception as exc:  # noqa: BLE001
                LOGGER.exception("Update handling failed for update_id=%s: %s", update_id, exc)
            finally:
                if update_id is not None:
                    offset = update_id + 1
                    save_offset(offset)
