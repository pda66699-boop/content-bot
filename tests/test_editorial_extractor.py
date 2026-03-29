from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from telegram_ingest.editorial_extractor import (  # noqa: E402
    infer_editorial_metadata_from_post,
    infer_editorial_metadata_from_topic,
)


class EditorialExtractorTests(unittest.TestCase):
    """Cover rules-only and hybrid classifier behavior for editorial metadata."""

    def test_infer_editorial_metadata_from_post_on_simple_text(self) -> None:
        """Rules-only extraction should infer useful metadata from a plain card."""

        card = {
            "title_hook": "Почему потери не видны в расходах",
            "primary_theme": "скрытые потери в операционке",
            "body_summary": "Компания теряет деньги в переделках, разрывах и ручном труде.",
            "body_text": "Компания теряет деньги в процессах, ручном труде и разрывах между функциями.",
            "content_role": "diagnostic",
            "format": "expert",
        }

        metadata = infer_editorial_metadata_from_post(card)

        self.assertIn("потери", (metadata["primary_thesis"] or "").lower())
        self.assertEqual(metadata["content_goal"], "diagnostic")
        self.assertEqual(metadata["format_type"], "expert")
        self.assertIn("финансы", metadata["business_dimensions"])
        self.assertGreaterEqual(metadata["novelty_window_days"], 30)

    def test_fallback_without_llm_does_not_fail(self) -> None:
        """Unavailable LLM should gracefully fall back to local rules."""

        with patch("telegram_ingest.editorial_extractor.llm_available", return_value=False):
            metadata = infer_editorial_metadata_from_topic("оргструктура и роли")

        self.assertEqual(metadata["content_goal"], "expert")
        self.assertIn("управление", metadata["business_dimensions"])
        self.assertTrue(metadata["angle"])

    def test_invalid_llm_json_falls_back_to_rules(self) -> None:
        """Malformed classifier JSON should be rejected and replaced by rules-only metadata."""

        with patch("telegram_ingest.editorial_extractor.llm_available", return_value=True), patch(
            "telegram_ingest.editorial_extractor.complete_json",
            return_value={
                "primary_thesis": "Неверный ответ",
                "secondary_theses": "должен быть массив",
                "angle": "угол",
                "content_goal": "diagnostic",
                "funnel_stage": "problem-aware",
                "business_dimensions": ["финансы"],
                "format_type": "expert",
                "novelty_window_days": 30,
            },
        ):
            metadata = infer_editorial_metadata_from_post(
                {
                    "title_hook": "Почему потери не видны в расходах",
                    "primary_theme": "скрытые потери в операционке",
                    "body_text": "Потери чаще лежат в процессах, а не только в бюджете.",
                    "content_role": "diagnostic",
                    "format": "expert",
                }
            )

        self.assertIn("потери", (metadata["primary_thesis"] or "").lower())
        self.assertIsInstance(metadata["secondary_theses"], list)
        self.assertNotEqual(metadata["secondary_theses"], "должен быть массив")


if __name__ == "__main__":
    unittest.main()
