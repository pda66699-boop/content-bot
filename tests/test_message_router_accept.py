from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from telegram_ingest.message_router import persist_accepted_post_from_session  # noqa: E402


class MessageRouterAcceptTests(unittest.TestCase):
    def test_persist_accepted_post_from_session_writes_record(self) -> None:
        session = {
            "last_generated": {
                "theme": "у вас не много всего, у вас система держится на вашем внимании",
                "goal": "expert",
                "final_text": (
                    "⚠️ У вас не много дел, у вас бизнес держится на вашем внимании\n\n"
                    "Это видно в мелочах: все вопросы снова сходятся к собственнику.\n\n"
                    "Пока решения держатся на одном человеке, рост упирается в его пропускную способность.\n\n"
                    "#управление"
                ),
                "topic_brief": {
                    "theme": "у вас не много всего, у вас система держится на вашем внимании",
                    "angle": "показать дорогую зависимость бизнеса от внимания собственника",
                    "content_role": "diagnostic",
                    "funnel_stage": "solution_consideration",
                    "primary_thesis": "Пока ключевые решения держатся на одном человеке, рост компании ограничен его пропускной способностью.",
                },
            }
        }

        with patch("telegram_ingest.message_router.upsert_post_record") as upsert_post_record, patch(
            "telegram_ingest.message_router.upsert_published_post"
        ) as upsert_published_post:
            record = persist_accepted_post_from_session(chat_id=1, user_id=2, session=session)

        self.assertIsNotNone(record)
        self.assertEqual(record["source"], "bot_manual_accept")
        self.assertEqual(record["primary_theme"], "у вас не много всего, у вас система держится на вашем внимании")
        self.assertEqual(record["telegram_chat_id"], "1")
        self.assertLess(record["telegram_message_id"], 0)
        upsert_post_record.assert_called_once()
        upsert_published_post.assert_called_once()

    def test_persist_accepted_post_from_session_returns_none_without_text(self) -> None:
        session = {"last_generated": {"theme": "тема", "final_text": ""}}

        with patch("telegram_ingest.message_router.upsert_post_record") as upsert_post_record, patch(
            "telegram_ingest.message_router.upsert_published_post"
        ) as upsert_published_post:
            record = persist_accepted_post_from_session(chat_id=1, user_id=2, session=session)

        self.assertIsNone(record)
        upsert_post_record.assert_not_called()
        upsert_published_post.assert_not_called()


if __name__ == "__main__":
    unittest.main()
