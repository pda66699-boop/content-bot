from __future__ import annotations

import sys
import unittest
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from telegram_ingest.editorial_similarity import (  # noqa: E402
    classify_topic_novelty,
    find_semantic_neighbors,
    suggest_reframes,
)


def _build_card(
    *,
    days_ago: int,
    primary_thesis: str,
    secondary_theses: list[str],
    angle: str,
    business_dimensions: list[str],
    funnel_stage: str = "problem-aware",
    format_type: str = "expert",
    novelty_window_days: int = 30,
    title_hook: str = "Тестовая тема",
    primary_theme: str = "тестовая тема",
) -> dict:
    current_date = date.today() - timedelta(days=days_ago)
    return {
        "post_id": f"post-{days_ago}-{abs(hash(primary_thesis)) % 10000}",
        "date": current_date.isoformat(),
        "title_hook": title_hook,
        "primary_theme": primary_theme,
        "primary_thesis": primary_thesis,
        "secondary_theses": secondary_theses,
        "angle": angle,
        "content_goal": "diagnostic",
        "funnel_stage": funnel_stage,
        "business_dimensions": business_dimensions,
        "format_type": format_type,
        "novelty_window_days": novelty_window_days,
        "body_summary": primary_thesis,
    }


class EditorialSimilarityTests(unittest.TestCase):
    """Cover novelty statuses and nearest-neighbor behavior."""

    def test_new_thesis_is_fresh(self) -> None:
        """A different thesis should be classified as fresh."""

        archive = [
            _build_card(
                days_ago=10,
                primary_thesis="Потери прячутся в процессах и ручном труде.",
                secondary_theses=["ручной труд", "разрывы между функциями"],
                angle="зайти через скрытые издержки в операционке",
                business_dimensions=["операционка", "финансы"],
                primary_theme="скрытые потери в операционке",
            )
        ]
        candidate = _build_card(
            days_ago=0,
            primary_thesis="Без ролей и ответственности команда остаётся зависимой от собственника.",
            secondary_theses=["границы решений", "оргструктура"],
            angle="показать перегрузку владельца через размытые роли",
            business_dimensions=["управление", "команда"],
            primary_theme="оргструктура и роли",
        )

        verdict = classify_topic_novelty(candidate, archive)

        self.assertEqual(verdict["status"], "fresh")

    def test_same_thesis_new_angle_is_reframe_allowed(self) -> None:
        """The same thesis with a different angle should allow a reframe."""

        archive = [
            _build_card(
                days_ago=14,
                primary_thesis="Потери прячутся в процессах и ручном труде.",
                secondary_theses=["ручной труд", "разрывы между функциями"],
                angle="зайти через скрытые издержки в операционке",
                business_dimensions=["операционка", "финансы"],
                primary_theme="скрытые потери в операционке",
            )
        ]
        candidate = _build_card(
            days_ago=0,
            primary_thesis="Потери прячутся в процессах и ручном труде.",
            secondary_theses=["ручной труд", "разрывы между функциями"],
            angle="разобрать тему через задержки решений и зависание согласований",
            business_dimensions=["операционка", "финансы"],
            primary_theme="скрытые потери в операционке",
        )

        verdict = classify_topic_novelty(candidate, archive)

        self.assertEqual(verdict["status"], "reframe_allowed")
        self.assertTrue(verdict["reframes"])

    def test_same_thesis_same_angle_recent_post_is_too_close(self) -> None:
        """A very close recent match should be marked as too_close."""

        archive = [
            _build_card(
                days_ago=5,
                primary_thesis="Потери прячутся в процессах и ручном труде.",
                secondary_theses=["ручной труд", "разрывы между функциями"],
                angle="зайти через скрытые издержки в операционке",
                business_dimensions=["операционка", "финансы"],
                primary_theme="скрытые потери в операционке",
            )
        ]
        candidate = _build_card(
            days_ago=0,
            primary_thesis="Потери прячутся в процессах и ручном труде.",
            secondary_theses=["ручной труд", "разрывы между функциями"],
            angle="зайти через скрытые издержки в операционке",
            business_dimensions=["операционка", "финансы"],
            primary_theme="скрытые потери в операционке",
        )

        verdict = classify_topic_novelty(candidate, archive)

        self.assertEqual(verdict["status"], "too_close")

    def test_series_continuation_scenario(self) -> None:
        """A close thesis with continuation signal should be treated as series continuation."""

        archive = [
            _build_card(
                days_ago=20,
                primary_thesis="Ошибки собственника меняются вместе со стадией бизнеса.",
                secondary_theses=["стадия роста", "неверный управленческий фокус"],
                angle="первая часть серии про типовые ошибки на стадии роста",
                business_dimensions=["управление", "финансы"],
                primary_theme="ошибки собственника по стадиям",
                title_hook="Часть 1. Ошибки собственника на стадии роста",
            )
        ]
        candidate = _build_card(
            days_ago=0,
            primary_thesis="Ошибки собственника меняются вместе со стадией бизнеса.",
            secondary_theses=["стадия зрелости", "неверный управленческий фокус"],
            angle="продолжение серии: вторая часть про ошибки на стадии зрелости",
            business_dimensions=["управление", "финансы"],
            primary_theme="ошибки собственника по стадиям",
            title_hook="Часть 2. Ошибки собственника на стадии зрелости",
        )

        verdict = classify_topic_novelty(candidate, archive)

        self.assertEqual(verdict["status"], "series_continuation")

    def test_find_semantic_neighbors_returns_sorted_matches(self) -> None:
        """Neighbors should be sorted by semantic proximity."""

        archive = [
            _build_card(
                days_ago=12,
                primary_thesis="Потери прячутся в процессах и ручном труде.",
                secondary_theses=["ручной труд"],
                angle="скрытые издержки",
                business_dimensions=["операционка", "финансы"],
            ),
            _build_card(
                days_ago=12,
                primary_thesis="Без ролей команда зависит от собственника.",
                secondary_theses=["оргструктура"],
                angle="размытая ответственность",
                business_dimensions=["управление", "команда"],
                primary_theme="оргструктура и роли",
            ),
        ]
        candidate = _build_card(
            days_ago=0,
            primary_thesis="Потери прячутся в процессах и ручном труде.",
            secondary_theses=["ручной труд"],
            angle="новый угол про зависание согласований",
            business_dimensions=["операционка", "финансы"],
        )

        neighbors = find_semantic_neighbors(candidate, archive, limit=2)

        self.assertEqual(len(neighbors), 2)
        self.assertGreaterEqual(neighbors[0]["semantic_score"], neighbors[1]["semantic_score"])
        self.assertEqual(neighbors[0]["primary_thesis"], "Потери прячутся в процессах и ручном труде.")

    def test_suggest_reframes_returns_actionable_options(self) -> None:
        """Reframe suggestions should stay non-empty for close matches."""

        candidate = _build_card(
            days_ago=0,
            primary_thesis="Потери прячутся в процессах и ручном труде.",
            secondary_theses=["ручной труд"],
            angle="скрытые издержки",
            business_dimensions=["операционка", "финансы"],
        )
        matched_posts = [
            _build_card(
                days_ago=7,
                primary_thesis="Потери прячутся в процессах и ручном труде.",
                secondary_theses=["ручной труд"],
                angle="скрытые издержки",
                business_dimensions=["операционка", "финансы"],
            )
        ]

        suggestions = suggest_reframes(candidate, matched_posts)

        self.assertTrue(suggestions)


if __name__ == "__main__":
    unittest.main()
