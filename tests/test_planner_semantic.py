from __future__ import annotations

import sys
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from telegram_ingest.planner_engine import TopicCandidate, evaluate_editorial_gate, plan_next_topics  # noqa: E402


def _archive_row(
    *,
    days_ago: int,
    primary_theme: str,
    primary_thesis: str,
    angle: str,
    business_dimensions: list[str],
    funnel_stage: str = "problem-aware",
    format_type: str = "expert",
    content_role: str = "diagnostic",
    content_pillar: str | None = None,
) -> dict:
    current_date = date.today() - timedelta(days=days_ago)
    return {
        "post_id": f"row-{days_ago}-{abs(hash(primary_theme + primary_thesis)) % 10000}",
        "date": current_date.isoformat(),
        "time": "12:00",
        "title_hook": primary_theme,
        "body_summary": primary_thesis,
        "body_text": primary_thesis,
        "primary_theme": primary_theme,
        "secondary_themes": [],
        "format": format_type,
        "content_role": content_role,
        "funnel_stage": funnel_stage,
        "core_thesis": primary_thesis,
        "primary_thesis": primary_thesis,
        "secondary_theses": [],
        "angle": angle,
        "content_goal": content_role,
        "business_dimensions": business_dimensions,
        "format_type": format_type,
        "novelty_window_days": 30,
        "cta_type": "none",
        "cta_present": False,
        "cta_target": None,
        "hashtags": [],
        "mentions_ai": False,
        "mentions_offer": False,
        "novelty_keys": [],
        "manual_review_required": False,
        "content_pillar": content_pillar or ("money" if "финансы" in business_dimensions else "expert"),
    }


class PlannerSemanticLayerTests(unittest.TestCase):
    """Cover semantic novelty integration inside the planner."""

    def test_semantic_duplicate_is_not_returned_as_fresh_topic(self) -> None:
        """A semantically duplicated user theme should be downgraded to reframe."""

        archive = [
            _archive_row(
                days_ago=5,
                primary_theme="оптимизация издержек через процессы",
                primary_thesis="Главные потери бизнеса часто скрыты в процессах и управленческих разрывах.",
                angle="зайти через скрытые издержки в операционке",
                business_dimensions=["операционка", "финансы"],
            )
        ]

        with patch("telegram_ingest.planner_engine.load_posts", return_value=archive), patch(
            "telegram_ingest.planner_engine.get_high_priority_open_loops",
            return_value=[],
        ), patch("telegram_ingest.planner_engine.load_backlog", return_value=[]), patch(
            "telegram_ingest.planner_engine.maybe_generate_planner_candidates",
            return_value=None,
        ):
            plan = plan_next_topics(user_theme="скрытые потери в операционке")

        self.assertEqual(plan["user_theme_verdict"]["status"], "reframe")
        self.assertTrue(plan["user_theme_verdict"]["comment"])

    def test_planner_output_contains_semantic_fields(self) -> None:
        """Planner output should expose semantic metadata alongside legacy fields."""

        archive = [
            _archive_row(
                days_ago=40,
                primary_theme="оргструктура и роли",
                primary_thesis="Без ролей и ответственности управляемость не появляется.",
                angle="через перегрузку собственника",
                business_dimensions=["управление", "команда"],
                content_role="expert",
                content_pillar="expert",
            )
        ]

        with patch("telegram_ingest.planner_engine.load_posts", return_value=archive), patch(
            "telegram_ingest.planner_engine.get_high_priority_open_loops",
            return_value=[],
        ), patch("telegram_ingest.planner_engine.load_backlog", return_value=[]), patch(
            "telegram_ingest.planner_engine.maybe_generate_planner_candidates",
            return_value=None,
        ):
            plan = plan_next_topics()

        self.assertTrue(plan["best_next_topics"])
        candidate = plan["best_next_topics"][0]
        self.assertIn("primary_thesis", candidate)
        self.assertIn("novelty_status", candidate)
        self.assertIn("reason", candidate)
        self.assertIn("allowed_reframes", candidate)
        self.assertIn("recommended_format", candidate)
        self.assertIn("recommended_cta_type", candidate)
        self.assertIn("score", candidate)
        self.assertIn("recommended_slot", plan)
        self.assertIn("topic", plan)
        self.assertIn("recommended_angle", plan)
        self.assertIn("recommended_format", plan)
        self.assertIn("recommended_cta_type", plan)
        self.assertIn("score_breakdown", candidate)
        self.assertIn("editorial_admissibility", candidate)
        self.assertIn("matched_post_title_or_date", candidate)
        self.assertIn("matched_primary_thesis", candidate)
        self.assertIn("why_not_fresh", candidate)

    def test_near_duplicate_topic_does_not_rank_above_fresh_topic(self) -> None:
        """A reframe-only topic should not outrank a genuinely fresh candidate."""

        archive = [
            _archive_row(
                days_ago=3,
                primary_theme="скрытые потери в операционке",
                primary_thesis="Главные потери бизнеса часто скрыты в процессах и управленческих разрывах.",
                angle="зайти через скрытые издержки в операционке",
                business_dimensions=["операционка", "финансы"],
            )
        ]

        with patch("telegram_ingest.planner_engine.load_posts", return_value=archive), patch(
            "telegram_ingest.planner_engine.get_high_priority_open_loops",
            return_value=[],
        ), patch("telegram_ingest.planner_engine.load_backlog", return_value=[]), patch(
            "telegram_ingest.planner_engine.maybe_generate_planner_candidates",
            return_value=None,
        ):
            plan = plan_next_topics(user_theme="скрытые потери в операционке")

        fresh_candidates = [item for item in plan["best_next_topics"] if item["novelty_status"] == "fresh"]
        self.assertTrue(fresh_candidates)
        self.assertNotIn("скрытые потери в операционке", [item["theme"] for item in plan["best_next_topics"]])
        self.assertEqual(plan["user_theme_verdict"]["status"], "reframe")

    def test_reframe_candidate_has_penalty_breakdown(self) -> None:
        """Reframe candidates should expose explicit novelty and repeat penalties."""

        archive = [
            _archive_row(
                days_ago=4,
                primary_theme="оптимизация издержек через процессы",
                primary_thesis="Главные потери бизнеса часто скрыты в процессах и управленческих разрывах.",
                angle="зайти через скрытые издержки в операционке",
                business_dimensions=["операционка", "финансы"],
            )
        ]

        with patch("telegram_ingest.planner_engine.load_posts", return_value=archive), patch(
            "telegram_ingest.planner_engine.get_high_priority_open_loops",
            return_value=[],
        ), patch("telegram_ingest.planner_engine.load_backlog", return_value=[]), patch(
            "telegram_ingest.planner_engine.maybe_generate_planner_candidates",
            return_value=None,
        ):
            plan = plan_next_topics(user_theme="скрытые потери в операционке")

        candidate = next(item for item in plan["best_next_topics"] if item["theme"] == "скрытые потери в операционке")
        self.assertGreater(candidate["total_penalty"], 0)
        self.assertIn("penalties", candidate["score_breakdown"])

    def test_reframe_allowed_candidate_shows_explanation(self) -> None:
        """Reframe-only candidates should carry an explicit reframe explanation."""

        archive = [
            _archive_row(
                days_ago=4,
                primary_theme="оптимизация издержек через процессы",
                primary_thesis="Главные потери бизнеса часто скрыты в процессах и управленческих разрывах.",
                angle="зайти через скрытые издержки в операционке",
                business_dimensions=["операционка", "финансы"],
            )
        ]

        with patch("telegram_ingest.planner_engine.load_posts", return_value=archive), patch(
            "telegram_ingest.planner_engine.get_high_priority_open_loops",
            return_value=[],
        ), patch("telegram_ingest.planner_engine.load_backlog", return_value=[]), patch(
            "telegram_ingest.planner_engine.maybe_generate_planner_candidates",
            return_value=None,
        ):
            plan = plan_next_topics(user_theme="скрытые потери в операционке")

        self.assertEqual(plan["user_theme_verdict"]["status"], "reframe")
        self.assertIn("reframe", plan["user_theme_verdict"]["comment"].lower())
        self.assertEqual(plan["user_theme_verdict"]["recommended_angle"], "Сменить формат подачи и раскрыть тему как case.")

    def test_series_continuation_requires_continuity_evidence(self) -> None:
        """Series-like novelty should downgrade without open-loop or campaign evidence."""

        candidate = TopicCandidate(
            theme="ошибки собственника по стадиям бизнеса",
            angle="разобрать следующую типовую ошибку собственника на другой стадии",
            score=80,
            why_now="тема снова уместна как разбор типовой ошибки",
            content_role="diagnostic",
            cta_need="optional",
            content_pillar="expert",
            marketing_rubric="expert_explainer",
        )

        gate, continuity_confirmed, evidence = evaluate_editorial_gate(
            candidate,
            {"status": "series_continuation"},
            campaign_mode="base",
            open_loops=[],
        )

        self.assertEqual(gate, "reframe_only")
        self.assertFalse(continuity_confirmed)
        self.assertEqual(evidence, [])

    def test_fresh_candidate_explains_why_it_is_fresh(self) -> None:
        """Fresh topics should explain why they are considered new enough right now."""

        archive = [
            _archive_row(
                days_ago=40,
                primary_theme="скрытые потери в операционке",
                primary_thesis="Главные потери бизнеса часто скрыты в процессах.",
                angle="через скрытые издержки",
                business_dimensions=["операционка", "финансы"],
            )
        ]

        with patch("telegram_ingest.planner_engine.load_posts", return_value=archive), patch(
            "telegram_ingest.planner_engine.get_high_priority_open_loops",
            return_value=[],
        ), patch("telegram_ingest.planner_engine.load_backlog", return_value=[]), patch(
            "telegram_ingest.planner_engine.maybe_generate_planner_candidates",
            return_value=None,
        ):
            plan = plan_next_topics()

        fresh = plan["best_next_topics"][0]
        self.assertEqual(fresh["editorial_admissibility"], "allowed")
        self.assertIn("считается новой", fresh["reason"].lower())

    def test_reframe_explanation_fields_are_present_for_user_theme(self) -> None:
        """User reframe verdict should carry matched context and why-not-fresh explanation when candidate survives."""

        archive = [
            _archive_row(
                days_ago=4,
                primary_theme="оптимизация издержек через процессы",
                primary_thesis="Главные потери бизнеса часто скрыты в процессах и управленческих разрывах.",
                angle="зайти через скрытые издержки в операционке",
                business_dimensions=["операционка", "финансы"],
            )
        ]

        with patch("telegram_ingest.planner_engine.load_posts", return_value=archive), patch(
            "telegram_ingest.planner_engine.get_high_priority_open_loops",
            return_value=[],
        ), patch("telegram_ingest.planner_engine.load_backlog", return_value=[]), patch(
            "telegram_ingest.planner_engine.maybe_generate_planner_candidates",
            return_value=None,
        ):
            plan = plan_next_topics(user_theme="скрытые потери в операционке")

        self.assertEqual(plan["user_theme_verdict"]["status"], "reframe")
        self.assertIn("нельзя", plan["user_theme_verdict"]["comment"].lower())


if __name__ == "__main__":
    unittest.main()
