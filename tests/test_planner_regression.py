from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
TESTS_DIR = Path(__file__).resolve().parent
if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))

from telegram_ingest.editorial_evaluation import build_planner_batch_review  # noqa: E402
from telegram_ingest.planner_engine import build_roadmap_state, plan_next_topics  # noqa: E402

from planner_regression_fixtures import archive_row, patched_planner_runtime  # noqa: E402


class PlannerRegressionTests(unittest.TestCase):
    """Protect calibrated planner behavior on real editorial scenarios."""

    def test_near_duplicate_does_not_outrank_fresh_topic(self) -> None:
        """A near-duplicate diagnostic topic should stay below a fresh alternative."""

        archive = [
            archive_row(
                days_ago=5,
                primary_theme="оптимизация издержек через процессы",
                primary_thesis="Главные потери бизнеса часто скрыты в процессах и управленческих разрывах.",
                angle="зайти через скрытые издержки в операционке",
                business_dimensions=["операционка", "финансы"],
            )
        ]

        with patched_planner_runtime(archive):
            review = build_planner_batch_review(
                ["скрытые потери в операционке", "оргструктура и роли"],
                archive=archive,
            )

        self.assertEqual(review["ranking_order"][0], "оргструктура и роли")
        near_duplicate = next(item for item in review["topics"] if item["theme"] == "скрытые потери в операционке")
        self.assertEqual(near_duplicate["novelty_status"], "reframe_allowed")
        self.assertEqual(near_duplicate["editorial_admissibility"], "reframe_only")

    def test_hidden_losses_vs_cost_optimization_processes_is_reframe_not_fresh(self) -> None:
        """The hidden-losses topic should not masquerade as fresh against the close cost-optimization case."""

        archive = [
            archive_row(
                days_ago=5,
                primary_theme="оптимизация издержек через процессы",
                primary_thesis="Главные потери бизнеса часто скрыты в процессах и управленческих разрывах.",
                angle="зайти через скрытые издержки в операционке",
                business_dimensions=["операционка", "финансы"],
                body_text="Основные издержки часто скрыты не в бюджете, а в ручном труде, сбоях процессов и управленческих разрывах.",
            )
        ]

        with patched_planner_runtime(archive):
            plan = plan_next_topics(user_theme="скрытые потери в операционке")

        self.assertEqual(plan["user_theme_verdict"]["status"], "reframe")
        candidate = plan["user_theme_analysis"]
        self.assertIsNotNone(candidate)
        self.assertEqual(candidate["novelty_status"], "reframe_allowed")
        self.assertEqual(candidate["editorial_admissibility"], "reframe_only")
        self.assertTrue(candidate["why_not_fresh"])

    def test_planner_treats_teryaet_dengi_as_hidden_losses_repeat(self) -> None:
        """Roadmap wording with 'теряет деньги' should match older hidden-losses posts."""

        archive = [
            archive_row(
                days_ago=10,
                primary_theme="оптимизация издержек через процессы",
                primary_thesis="Основные издержки часто скрыты не в бюджете, а в ручном труде, сбоях процессов и управленческих разрывах.",
                angle="показать, почему оптимизация издержек начинается с поиска скрытых операционных потерь",
                business_dimensions=["операционка", "финансы"],
                body_text="Самые дорогие потери редко лежат в строке расходов: они прячутся во времени, ошибках, разрывах процессов и ручном контроле.",
            )
        ]
        roadmap = [
            {
                "id": "w1_p2",
                "week": 1,
                "order": 2,
                "narrative_position_index": 2,
                "theme": "где на самом деле бизнес теряет деньги, даже если p and l этого не показывает",
                "angle": "разобрать скрытые потери в переделках, разрывах между функциями, ручном контроле и ошибках исполнения",
                "narrative_role": "pain",
                "narrative_chain_id": "week-1",
            }
        ]

        state = build_roadmap_state(archive, roadmap)

        self.assertTrue(state["items"][0]["completed"])
        self.assertIn("оптимизация издержек", state["items"][0]["matched_post_title_or_date"])

    def test_completed_hidden_losses_roadmap_topic_is_not_recommended_again(self) -> None:
        """A completed hidden-losses roadmap item should not be offered as a fresh next topic."""

        archive = [
            archive_row(
                days_ago=10,
                primary_theme="оптимизация издержек через процессы",
                primary_thesis="Основные издержки часто скрыты не в бюджете, а в ручном труде, сбоях процессов и управленческих разрывах.",
                angle="показать, почему оптимизация издержек начинается с поиска скрытых операционных потерь",
                business_dimensions=["операционка", "финансы"],
                body_text="Самые дорогие потери редко лежат в строке расходов: они прячутся во времени, ошибках, разрывах процессов и ручном контроле.",
            )
        ]

        with patched_planner_runtime(archive):
            plan = plan_next_topics()

        themes = [item["theme"] for item in plan["best_next_topics"]]
        self.assertNotIn("где на самом деле бизнес теряет деньги, даже если p and l этого не показывает", themes)

    def test_reframe_allowed_never_masquerades_as_fresh_in_user_output(self) -> None:
        """User-facing planner output should keep reframe candidates explicitly non-fresh."""

        archive = [
            archive_row(
                days_ago=4,
                primary_theme="оптимизация издержек через процессы",
                primary_thesis="Главные потери бизнеса часто скрыты в процессах и управленческих разрывах.",
                angle="зайти через скрытые издержки в операционке",
                business_dimensions=["операционка", "финансы"],
            )
        ]

        with patched_planner_runtime(archive):
            plan = plan_next_topics(user_theme="скрытые потери в операционке")

        candidate = plan["user_theme_analysis"]
        self.assertIsNotNone(candidate)
        self.assertNotEqual(candidate["novelty_status"], "fresh")
        self.assertEqual(candidate["editorial_admissibility"], "reframe_only")
        self.assertTrue("reframe" in candidate["reason"].lower() or "не считается fresh" in candidate["reason"].lower())
        self.assertTrue(candidate["allowed_reframes"])

    def test_series_continuation_requires_continuity_evidence(self) -> None:
        """Series-like topics should downgrade without a supporting open loop or campaign thread."""

        archive = [
            archive_row(
                days_ago=6,
                primary_theme="ошибки собственника по стадиям бизнеса. Часть 1",
                primary_thesis="Ошибки собственника меняются вместе со стадией бизнеса, и их нельзя лечить одинаково.",
                angle="первая часть серии про ошибки стадии роста",
                business_dimensions=["управление"],
                body_text="Это первая часть серии про ошибки собственника на разных стадиях бизнеса.",
            )
        ]

        series_metadata = {
            "primary_thesis": "Ошибки собственника меняются вместе со стадией бизнеса, и их нельзя лечить одинаково.",
            "secondary_theses": [],
            "angle": "продолжение серии про ошибки собственника на следующей стадии бизнеса",
            "content_goal": "diagnostic",
            "funnel_stage": "problem_aware",
            "business_dimensions": ["управление"],
            "format_type": "expert",
            "novelty_window_days": 30,
        }

        with patched_planner_runtime(archive, open_loops=[]), patch(
            "telegram_ingest.planner_engine.infer_editorial_metadata_from_topic",
            side_effect=lambda topic, **_: series_metadata
            if topic == "ошибки собственника по стадиям бизнеса"
            else {
                "primary_thesis": "Без ролей и ясной ответственности управляемость не появляется, даже если команда уже есть.",
                "secondary_theses": [],
                "angle": "начать с понятной управленческой сцены, затем раскрыть системную причину и практический вывод",
                "content_goal": "expert",
                "funnel_stage": "solution_consideration",
                "business_dimensions": ["управление"],
                "format_type": "expert",
                "novelty_window_days": 30,
            },
        ):
            plan = plan_next_topics(user_theme="ошибки собственника по стадиям бизнеса")

        self.assertEqual(plan["user_theme_verdict"]["status"], "reframe")
        self.assertNotIn("ошибки собственника по стадиям бизнеса", [item["theme"] for item in plan["best_next_topics"]])
        self.assertIn("continuity", plan["user_theme_verdict"]["comment"].lower())

    def test_too_close_is_excluded_from_top_recommendations(self) -> None:
        """A strict duplicate inside the novelty window should disappear from top recommendations."""

        archive = [
            archive_row(
                days_ago=2,
                primary_theme="скрытые потери в операционке",
                primary_thesis="Главные потери бизнеса часто скрыты в процессах и управленческих разрывах, а не только в видимых расходах.",
                angle="зайти через видимые расходы, затем перевести внимание на скрытые потери внутри процессов и решений",
                business_dimensions=["операционка", "финансы"],
                body_text="Главные потери бизнеса часто скрыты в процессах и управленческих разрывах, а не только в видимых расходах.",
            )
        ]

        duplicate_metadata = {
            "primary_thesis": "Главные потери бизнеса часто скрыты в процессах и управленческих разрывах, а не только в видимых расходах.",
            "secondary_theses": [],
            "angle": "зайти через видимые расходы, затем перевести внимание на скрытые потери внутри процессов и решений",
            "content_goal": "diagnostic",
            "funnel_stage": "problem_aware",
            "business_dimensions": ["операционка", "финансы"],
            "format_type": "expert",
            "novelty_window_days": 30,
        }

        with patched_planner_runtime(archive), patch(
            "telegram_ingest.editorial_evaluation.infer_editorial_metadata_from_topic",
            side_effect=lambda topic, **_: duplicate_metadata if topic == "скрытые потери в операционке" else {
                "primary_thesis": "Без ролей и ясной ответственности управляемость не появляется, даже если команда уже есть.",
                "secondary_theses": [],
                "angle": "начать с понятной управленческой сцены, затем раскрыть системную причину и практический вывод",
                "content_goal": "expert",
                "funnel_stage": "solution_consideration",
                "business_dimensions": ["управление"],
                "format_type": "expert",
                "novelty_window_days": 30,
            },
        ), patch(
            "telegram_ingest.planner_engine.infer_editorial_metadata_from_topic",
            side_effect=lambda topic, **_: duplicate_metadata if topic == "скрытые потери в операционке" else {
                "primary_thesis": "Без ролей и ясной ответственности управляемость не появляется, даже если команда уже есть.",
                "secondary_theses": [],
                "angle": "начать с понятной управленческой сцены, затем раскрыть системную причину и практический вывод",
                "content_goal": "expert",
                "funnel_stage": "solution_consideration",
                "business_dimensions": ["управление"],
                "format_type": "expert",
                "novelty_window_days": 30,
            },
        ):
            review = build_planner_batch_review(
                ["скрытые потери в операционке", "оргструктура и роли"],
                archive=archive,
            )

        self.assertNotIn("скрытые потери в операционке", review["ranking_order"])
        self.assertEqual(review["top_theme"], "оргструктура и роли")

    def test_personal_trust_topic_beats_repeat_diagnostic_topic_when_equal(self) -> None:
        """A fresh personal/trust topic should outrank a repeated diagnostic topic in a balanced batch."""

        archive = [
            archive_row(
                days_ago=4,
                primary_theme="скрытые потери в операционке",
                primary_thesis="Главные потери бизнеса часто скрыты в процессах и управленческих разрывах.",
                angle="зайти через скрытые издержки в операционке",
                business_dimensions=["операционка", "финансы"],
            )
        ]

        with patched_planner_runtime(archive):
            review = build_planner_batch_review(
                ["отношение к работе", "скрытые потери в операционке"],
                archive=archive,
            )

        self.assertEqual(review["top_theme"], "отношение к работе")
        repeated = next(item for item in review["topics"] if item["theme"] == "скрытые потери в операционке")
        self.assertEqual(repeated["editorial_admissibility"], "reframe_only")

    def test_promised_continuation_can_beat_fresh_topic_when_continuity_confirmed(self) -> None:
        """A promised continuation with evidence should outrank a fresh topic when continuity is explicit."""

        archive = [
            archive_row(
                days_ago=9,
                primary_theme="ошибки собственника по стадиям бизнеса. Часть 1",
                primary_thesis="Ошибки собственника меняются вместе со стадией бизнеса, и их нельзя лечить одинаково.",
                angle="первая часть серии про ошибки стадии роста",
                business_dimensions=["управление"],
                body_text="Это первая часть серии про ошибки собственника на разных стадиях бизнеса.",
            ),
            archive_row(
                days_ago=40,
                primary_theme="оргструктура как скелет управляемости",
                primary_thesis="Без ролей и ответственности управляемость не появляется.",
                angle="через перегрузку собственника",
                business_dimensions=["управление", "команда"],
                content_role="expert",
                content_pillar="expert",
            ),
        ]
        open_loops = [
            {
                "date": archive[0]["date"],
                "open_loop_topic": "ошибки собственника по стадиям бизнеса",
                "recommended_follow_up": "продолжить серию и разобрать следующую стадию бизнеса",
                "priority": "high",
            }
        ]

        series_metadata = {
            "primary_thesis": "Ошибки собственника меняются вместе со стадией бизнеса, и их нельзя лечить одинаково.",
            "secondary_theses": [],
            "angle": "продолжение серии про ошибки собственника на следующей стадии бизнеса",
            "content_goal": "diagnostic",
            "funnel_stage": "problem_aware",
            "business_dimensions": ["управление"],
            "format_type": "expert",
            "novelty_window_days": 30,
        }
        fresh_metadata = {
            "primary_thesis": "Без ролей и ясной ответственности управляемость не появляется, даже если команда уже есть.",
            "secondary_theses": [],
            "angle": "начать с понятной управленческой сцены, затем раскрыть системную причину и практический вывод",
            "content_goal": "expert",
            "funnel_stage": "solution_consideration",
            "business_dimensions": ["управление"],
            "format_type": "expert",
            "novelty_window_days": 30,
        }

        metadata_side_effect = lambda topic, **_: series_metadata if topic == "ошибки собственника по стадиям бизнеса" else fresh_metadata

        with patched_planner_runtime(archive, open_loops=open_loops), patch(
            "telegram_ingest.planner_engine.infer_editorial_metadata_from_topic",
            side_effect=metadata_side_effect,
        ), patch(
            "telegram_ingest.editorial_evaluation.infer_editorial_metadata_from_topic",
            side_effect=metadata_side_effect,
        ):
            review = build_planner_batch_review(
                ["ошибки собственника по стадиям бизнеса", "оргструктура и роли"],
                archive=archive,
            )

        self.assertEqual(review["top_theme"], "ошибки собственника по стадиям бизнеса")
        continuation = next(item for item in review["topics"] if item["theme"] == "ошибки собственника по стадиям бизнеса")
        self.assertEqual(continuation["novelty_status"], "series_continuation")
        self.assertEqual(continuation["editorial_admissibility"], "series_only")
        self.assertTrue(continuation["continuity_confirmed"])
        self.assertTrue(continuation["continuity_evidence"])

    def test_planner_metadata_path_forces_rules_only_even_when_hybrid_mode_is_on(self) -> None:
        """Planner novelty path should not allow hybrid LLM extraction to override semantic gating."""

        archive = [
            archive_row(
                days_ago=5,
                primary_theme="оптимизация издержек через процессы",
                primary_thesis="Главные потери бизнеса часто скрыты в процессах и управленческих разрывах.",
                angle="зайти через скрытые издержки в операционке",
                business_dimensions=["операционка", "финансы"],
            )
        ]

        def _fake_extractor(topic: str, context: dict | None = None, prefer_llm: bool = True) -> dict:
            if topic == "скрытые потери в операционке" and prefer_llm:
                return {
                    "primary_thesis": "Ручные согласования и разрывы между функциями создают непрямые, невидимые операционные потери.",
                    "secondary_theses": [
                        "Скрытые потери проявляются через задержки и дублирование работ.",
                    ],
                    "angle": "показать, как ручные согласования съедают деньги без строки расходов",
                    "content_goal": "diagnostic",
                    "funnel_stage": "solution_aware",
                    "business_dimensions": ["операционная эффективность", "процессы и согласования"],
                    "format_type": "diagnostic_entry",
                    "novelty_window_days": 30,
                }
            return {
                "primary_thesis": "Главные потери бизнеса часто скрыты в процессах и управленческих разрывах, а не только в видимых расходах.",
                "secondary_theses": [
                    "Сокращение потерь начинается с диагностики скрытых утечек, а не только с урезания бюджета.",
                    "Разрывы между функциями и ручной режим создают накопленный операционный шум.",
                ],
                "angle": "зайти через видимые расходы, затем перевести внимание на скрытые потери внутри процессов и решений",
                "content_goal": "diagnostic",
                "funnel_stage": "solution_aware",
                "business_dimensions": ["операционка", "финансы"],
                "format_type": "expert",
                "novelty_window_days": 30,
            }

        with patched_planner_runtime(archive), patch(
            "telegram_ingest.planner_engine.infer_editorial_metadata_from_topic",
            side_effect=_fake_extractor,
        ):
            plan = plan_next_topics(user_theme="скрытые потери в операционке")

        candidate = plan["user_theme_analysis"]
        self.assertIsNotNone(candidate)
        self.assertEqual(candidate["novelty_status"], "reframe_allowed")
        self.assertEqual(candidate["editorial_admissibility"], "reframe_only")


if __name__ == "__main__":
    unittest.main()
