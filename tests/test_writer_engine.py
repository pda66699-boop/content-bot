from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from telegram_ingest.writer_engine import build_focus_line, is_ai_core_topic  # noqa: E402


class WriterEngineVoiceTests(unittest.TestCase):
    def test_ai_focus_line_only_for_ai_core_topic(self) -> None:
        text = build_focus_line("зависимость бизнеса от собственника", "через точки потерь", 0)
        self.assertNotIn("ии", text.lower())

    def test_is_ai_core_topic_requires_real_ai_context(self) -> None:
        self.assertFalse(is_ai_core_topic("структура без магии"))
        self.assertFalse(is_ai_core_topic("хаос в управлении и роли"))
        self.assertTrue(is_ai_core_topic("ИИ и хаос в процессах"))


if __name__ == "__main__":
    unittest.main()
