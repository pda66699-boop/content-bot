from __future__ import annotations

import sys
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from telegram_ingest.critic_engine import critic_review, detect_semantic_repeat_risk  # noqa: E402


def _archive_row(days_ago: int, title: str, thesis: str, angle: str) -> dict:
    current_date = date.today() - timedelta(days=days_ago)
    return {
        "post_id": f"critic-{days_ago}-{abs(hash(title)) % 10000}",
        "date": current_date.isoformat(),
        "title_hook": title,
        "primary_theme": title,
        "body_text": thesis,
        "body_summary": thesis,
        "primary_thesis": thesis,
        "secondary_theses": [],
        "angle": angle,
        "content_goal": "diagnostic",
        "funnel_stage": "problem-aware",
        "business_dimensions": ["операционка", "финансы"],
        "format_type": "expert",
        "novelty_window_days": 30,
        "content_role": "diagnostic",
        "format": "expert",
    }


class CriticSemanticRepeatTests(unittest.TestCase):
    """Smoke coverage for critic semantic repeat detection."""

    def test_detect_semantic_repeat_risk_flags_close_meaning(self) -> None:
        """A semantically close paraphrase should be caught even without lexical identity."""

        archive = [
            _archive_row(
                7,
                "оптимизация издержек через процессы",
                "Главные потери бизнеса часто скрыты в процессах и управленческих разрывах.",
                "зайти через скрытые издержки в операционке",
            )
        ]
        text = (
            "Почему деньги утекают не в бюджете, а глубже.\n\n"
            "Настоящие потери компании обычно сидят в процессах, разрывах между функциями и ручном режиме."
        )

        risk, note = detect_semantic_repeat_risk(text, archive)

        self.assertEqual(risk, "medium")
        self.assertTrue(note)

    def test_critic_review_exposes_semantic_repeat_fields(self) -> None:
        """critic_review should publish semantic repeat diagnostics."""

        archive = [
            _archive_row(
                5,
                "скрытые потери в операционке",
                "Главные потери бизнеса часто скрыты в процессах и управленческих разрывах.",
                "зайти через скрытые издержки в операционке",
            )
        ]
        text = (
            "Почему потери не видны в расходах.\n\n"
            "Главные потери бизнеса часто скрыты в процессах и управленческих разрывах."
        )

        with patch("telegram_ingest.critic_engine.load_rows", return_value=archive):
            review = critic_review(text)

        self.assertIn("semantic_repeat_risk", review)
        self.assertIn("semantic_repeat_note", review)
        self.assertIn(review["semantic_repeat_risk"], {"medium", "high"})


if __name__ == "__main__":
    unittest.main()
