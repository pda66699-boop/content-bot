from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from telegram_ingest.feed_coverage import analyze_feed_coverage, recommend_content_plan_slot  # noqa: E402


class FeedCoverageTests(unittest.TestCase):
    """Cover feed coverage analysis and slot recommendation."""

    def test_recommend_content_plan_slot_detects_missing_layers(self) -> None:
        """Coverage should surface underused dimensions and return a slot."""

        rows = [
            {
                "primary_theme": "скрытые потери в операционке",
                "primary_thesis": "Потери сидят в процессах.",
                "angle": "через скрытые издержки",
                "business_dimensions": ["операционка", "финансы"],
                "funnel_stage": "problem-aware",
                "content_goal": "diagnostic",
                "format_type": "expert",
            }
            for _ in range(6)
        ]

        coverage = analyze_feed_coverage(rows, window_size=6)
        slot = recommend_content_plan_slot(coverage, campaign_mode="base")

        self.assertIn("business_dimensions", coverage)
        self.assertIn("angles", coverage)
        self.assertIn("why_now", slot)
        self.assertIn("target_business_dimension", slot)
        self.assertTrue(slot["why_now"])


if __name__ == "__main__":
    unittest.main()
