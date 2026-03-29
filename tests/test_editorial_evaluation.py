from __future__ import annotations

import sys
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from telegram_ingest.editorial_evaluation import (  # noqa: E402
    accumulate_match_stats,
    build_planner_batch_review,
    build_critic_review_debug,
    build_extractor_review_for_topic,
    build_planner_review,
    compare_planner_prediction_to_expected,
    compare_prediction_to_expected,
)


def _archive_row(
    *,
    days_ago: int,
    primary_theme: str,
    primary_thesis: str,
    angle: str,
    business_dimensions: list[str],
    funnel_stage: str = "problem-aware",
    format_type: str = "expert",
) -> dict:
    current_date = date.today() - timedelta(days=days_ago)
    return {
        "post_id": f"eval-{days_ago}-{abs(hash(primary_theme + primary_thesis)) % 10000}",
        "date": current_date.isoformat(),
        "title_hook": primary_theme,
        "primary_theme": primary_theme,
        "body_text": primary_thesis,
        "body_summary": primary_thesis,
        "primary_thesis": primary_thesis,
        "secondary_theses": [],
        "angle": angle,
        "content_goal": "diagnostic",
        "funnel_stage": funnel_stage,
        "business_dimensions": business_dimensions,
        "format_type": format_type,
        "novelty_window_days": 30,
        "content_role": "diagnostic",
        "format": format_type,
        "mentions_ai": False,
        "cta_present": False,
    }


class EditorialEvaluationTests(unittest.TestCase):
    """Cover debug outputs and golden-set helpers for semantic evaluation."""

    def test_topic_review_exposes_semantic_debug_fields(self) -> None:
        """Topic review should include novelty diagnostics and matched posts."""

        archive = [
            _archive_row(
                days_ago=6,
                primary_theme="скрытые потери в операционке",
                primary_thesis="Главные потери бизнеса часто скрыты в процессах и управленческих разрывах.",
                angle="зайти через скрытые издержки в операционке",
                business_dimensions=["операционка", "финансы"],
            )
        ]

        review = build_extractor_review_for_topic("скрытые потери в операционке", archive=archive)

        self.assertIn("primary_thesis", review)
        self.assertIn("novelty_status", review)
        self.assertIn("reason", review)
        self.assertTrue(review["matched_posts"])

    def test_planner_review_keeps_recommended_slot_and_matches(self) -> None:
        """Planner debug view should expose slot rationale and semantic neighbors."""

        archive = [
            _archive_row(
                days_ago=40,
                primary_theme="оргструктура и роли",
                primary_thesis="Без ролей и ответственности управляемость не появляется.",
                angle="через перегрузку собственника",
                business_dimensions=["управление", "команда"],
            )
        ]

        with patch("telegram_ingest.planner_engine.load_posts", return_value=archive), patch(
            "telegram_ingest.planner_engine.get_high_priority_open_loops",
            return_value=[],
        ), patch("telegram_ingest.planner_engine.load_backlog", return_value=[]), patch(
            "telegram_ingest.planner_engine.maybe_generate_planner_candidates",
            return_value=None,
        ):
            review = build_planner_review()

        self.assertIn("recommended_slot", review)
        self.assertTrue(review["top_candidates"])
        self.assertIn("matched_posts", review["top_candidates"][0])

    def test_planner_review_uses_archive_override(self) -> None:
        """Planner review should be reproducible from an explicit archive override."""

        archive = [
            _archive_row(
                days_ago=10,
                primary_theme="ошибки собственника по стадиям",
                primary_thesis="Ошибки собственника меняются вместе со стадией бизнеса.",
                angle="первая часть серии про ошибки стадии роста",
                business_dimensions=["управление"],
            )
        ]

        with patch("telegram_ingest.planner_engine.get_high_priority_open_loops", return_value=[]), patch(
            "telegram_ingest.planner_engine.load_backlog",
            return_value=[],
        ), patch("telegram_ingest.planner_engine.maybe_generate_planner_candidates", return_value=None):
            review = build_planner_review(archive=archive)

        self.assertIn("recommended_slot", review)
        self.assertIsInstance(review["top_candidates"], list)

    def test_planner_batch_review_ranks_topics_and_exposes_breakdown(self) -> None:
        """Manual planner batch review should expose ranking order and score breakdown."""

        archive = [
            _archive_row(
                days_ago=6,
                primary_theme="скрытые потери в операционке",
                primary_thesis="Главные потери бизнеса часто скрыты в процессах и управленческих разрывах.",
                angle="зайти через скрытые издержки в операционке",
                business_dimensions=["операционка", "финансы"],
            )
        ]

        with patch("telegram_ingest.editorial_evaluation.get_high_priority_open_loops", return_value=[]), patch(
            "telegram_ingest.planner_engine.get_high_priority_open_loops",
            return_value=[],
        ):
            review = build_planner_batch_review(
                ["скрытые потери в операционке", "оргструктура и роли"],
                archive=archive,
            )

        self.assertEqual(review["ranking_order"][0], "оргструктура и роли")
        candidate = next(item for item in review["topics"] if item["theme"] == "скрытые потери в операционке")
        self.assertEqual(candidate["editorial_admissibility"], "reframe_only")
        self.assertIn("score_breakdown", candidate)
        self.assertIn("matched_posts", candidate)

    def test_planner_batch_review_uses_rules_only_metadata_path(self) -> None:
        """Planner batch review should stay aligned with planner rules-only novelty gating."""

        archive = [
            _archive_row(
                days_ago=6,
                primary_theme="оптимизация издержек через процессы",
                primary_thesis="Главные потери бизнеса часто скрыты в процессах и управленческих разрывах.",
                angle="зайти через скрытые издержки в операционке",
                business_dimensions=["операционка", "финансы"],
            )
        ]

        def _fake_extractor(topic: str, context: dict | None = None, prefer_llm: bool = True) -> dict:
            if topic == "скрытые потери в операционке" and prefer_llm:
                return {
                    "primary_thesis": "Ручные согласования и разрывы между функциями создают непрямые потери.",
                    "secondary_theses": ["Повторная работа и задержки не видны в P&L."],
                    "angle": "показать скрытые потери через межфункциональные согласования",
                    "content_goal": "diagnostic",
                    "funnel_stage": "solution_aware",
                    "business_dimensions": ["операционная эффективность"],
                    "format_type": "diagnostic_entry",
                    "novelty_window_days": 30,
                }
            return {
                "primary_thesis": "Главные потери бизнеса часто скрыты в процессах и управленческих разрывах, а не только в видимых расходах.",
                "secondary_theses": [
                    "Сокращение потерь начинается с диагностики скрытых утечек, а не только с урезания бюджета.",
                ],
                "angle": "зайти через видимые расходы, затем перевести внимание на скрытые потери внутри процессов и решений",
                "content_goal": "diagnostic",
                "funnel_stage": "solution_aware",
                "business_dimensions": ["операционка", "финансы"],
                "format_type": "expert",
                "novelty_window_days": 30,
            }

        with patch("telegram_ingest.editorial_evaluation.get_high_priority_open_loops", return_value=[]), patch(
            "telegram_ingest.planner_engine.get_high_priority_open_loops",
            return_value=[],
        ), patch(
            "telegram_ingest.planner_engine.infer_editorial_metadata_from_topic",
            side_effect=_fake_extractor,
        ):
            review = build_planner_batch_review(
                ["скрытые потери в операционке", "оргструктура и роли"],
                archive=archive,
            )

        candidate = next(item for item in review["topics"] if item["theme"] == "скрытые потери в операционке")
        self.assertEqual(candidate["novelty_status"], "reframe_allowed")
        self.assertEqual(candidate["editorial_admissibility"], "reframe_only")

    def test_planner_ranking_comparison_supports_golden_set_fields(self) -> None:
        """Planner ranking evaluation should compare top theme and order prefixes."""

        prediction = {
            "top_theme": "оргструктура и роли",
            "ranking_order": ["оргструктура и роли", "скрытые потери в операционке"],
            "topics": [
                {"theme": "оргструктура и роли", "novelty_status": "fresh"},
                {"theme": "скрытые потери в операционке", "novelty_status": "reframe_allowed"},
            ],
        }

        comparison = compare_planner_prediction_to_expected(
            prediction,
            {
                "top_theme": "оргструктура и роли",
                "ranking_order_prefix": ["оргструктура и роли"],
                "novelty_status_by_topic": {
                    "скрытые потери в операционке": "reframe_allowed",
                },
            },
        )

        self.assertTrue(comparison["top_theme"]["matched"])
        self.assertTrue(comparison["ranking_order_prefix"]["matched"])
        self.assertTrue(comparison["novelty_status_by_topic"]["matched"])

    def test_critic_debug_includes_semantic_review_context(self) -> None:
        """Critic debug view should combine critic verdict with semantic fields."""

        archive = [
            _archive_row(
                days_ago=5,
                primary_theme="скрытые потери в операционке",
                primary_thesis="Главные потери бизнеса часто скрыты в процессах и управленческих разрывах.",
                angle="зайти через скрытые издержки в операционке",
                business_dimensions=["операционка", "финансы"],
            )
        ]
        text = (
            "Почему потери не видны в расходах.\n\n"
            "Главные потери бизнеса часто скрыты в процессах и управленческих разрывах."
        )

        review = build_critic_review_debug(text, archive=archive)

        self.assertIn("semantic_repeat_risk", review)
        self.assertIn("primary_thesis", review)
        self.assertIn("matched_posts", review)

    def test_golden_set_stats_accumulate_per_field_accuracy(self) -> None:
        """Golden-set helpers should compute simple per-field match statistics."""

        prediction = {
            "primary_thesis": "Скрытые потери сидят в процессах.",
            "funnel_stage": "problem-aware",
            "business_dimensions": ["операционка", "финансы"],
        }
        expected = {
            "primary_thesis": "Скрытые потери сидят в процессах.",
            "funnel_stage": "problem-aware",
            "business_dimensions": ["операционка", "финансы"],
        }

        comparison = compare_prediction_to_expected(prediction, expected)
        stats = accumulate_match_stats([comparison])

        self.assertTrue(comparison["primary_thesis"]["matched"])
        self.assertEqual(stats["funnel_stage"]["accuracy"], 1.0)
        self.assertEqual(stats["business_dimensions"]["matched"], 1)

    def test_compare_prediction_normalizes_funnel_stage_aliases(self) -> None:
        """Golden-set comparison should tolerate hyphen vs underscore categorical aliases."""

        comparison = compare_prediction_to_expected(
            {"funnel_stage": "problem_aware"},
            {"funnel_stage": "problem-aware"},
        )

        self.assertTrue(comparison["funnel_stage"]["matched"])


if __name__ == "__main__":
    unittest.main()
