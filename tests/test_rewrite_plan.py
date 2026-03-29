from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from telegram_ingest.rewrite_engine import (  # noqa: E402
    build_rewrite_plan_from_improvement,
    rewrite_post_by_improvement,
)


class RewritePlanTests(unittest.TestCase):
    """Smoke tests for explicit rewrite plan application."""

    def test_rewrite_plan_applies_target_thesis_angle_and_removals(self) -> None:
        """Explicit rewrite plan should steer fallback rewrite semantics."""

        source_text = (
            "Самые дорогие потери в компании обычно не видны в строке расходов\n\n"
            "Если сжать это до одной мысли, то она такая: проблема обычно глубже, чем кажется на поверхности."
        )
        rewrite_plan = {
            "target_primary_thesis": "Главный фокус нужно сместить с расходов на зависание решений между функциями.",
            "target_angle": "разобрать тему через стоимость задержек согласования, а не через бюджетную экономию",
            "target_format_type": "case",
            "target_content_goal": "diagnostic",
            "target_funnel_stage": "solution_aware",
            "avoid_similarity_with_post_ids": ["post-1"],
            "must_remove_patterns": ["Если сжать это до одной мысли"],
        }

        with patch("telegram_ingest.rewrite_engine.generate_drafts", return_value={"drafts": []}):
            result = rewrite_post_by_improvement(
                source_text,
                improvement_mode="improvement_2",
                theme_hint="скрытые потери в операционке",
                business_goal="money",
                rewrite_plan=rewrite_plan,
            )

        self.assertIn("зависание решений", result["final_text"])
        self.assertIn("стоимость задержек согласования", result["final_text"])
        self.assertNotIn("Если сжать это до одной мысли", result["final_text"])
        self.assertEqual(result["rewrite_plan"]["target_format_type"], "case")

    def test_build_rewrite_plan_uses_reframes_for_semantic_repeat(self) -> None:
        """Improvement plan should switch angle and format for semantic repeat cases."""

        plan = build_rewrite_plan_from_improvement(
            source_text="Потери часто лежат глубже видимых расходов.",
            improvement_mode="improvement_2",
            theme="скрытые потери в операционке",
            business_goal="money",
            option_text="Сместить акцент ближе к тому, что сейчас просит лента.",
            topic_brief={
                "novelty_status": "too_close",
                "allowed_reframes": ["уйти в разбор задержек решений между функциями"],
                "recommended_format": "case",
                "recommended_cta_type": "diagnostic",
                "content_goal": "diagnostic",
                "funnel_stage": "problem_aware",
            },
        )

        self.assertEqual(plan["target_angle"], "уйти в разбор задержек решений между функциями")
        self.assertEqual(plan["target_format_type"], "case")
        self.assertEqual(plan["target_funnel_stage"], "solution_aware")


if __name__ == "__main__":
    unittest.main()
