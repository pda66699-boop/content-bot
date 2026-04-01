from __future__ import annotations

import sys
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from telegram_ingest.critic_engine import (  # noqa: E402
    critic_review,
    detect_legacy_positioning_risk,
    detect_semantic_repeat_risk,
    detect_synthetic_case_risk,
    detect_corporate_jargon_risk,
)


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

    def test_detect_legacy_positioning_risk_flags_broad_old_frame(self) -> None:
        """Broad useful text without the new positioning signals should be flagged as legacy-risk."""

        text = (
            "Как нанимать сотрудников без ошибок.\n\n"
            "Найм важен для любого бизнеса. Нужно прописать требования, провести собеседование и выстроить адаптацию."
        )

        risk, note = detect_legacy_positioning_risk(text)

        self.assertEqual(risk, "medium")
        self.assertTrue(note)

    def test_critic_review_exposes_legacy_positioning_fields(self) -> None:
        """critic_review should expose legacy-positioning diagnostics for strategic drift."""

        archive = [
            _archive_row(
                20,
                "оргструктура и роли",
                "Без ролей и ответственности управляемость не появляется.",
                "через перегрузку собственника",
            )
        ]
        text = (
            "Как делегировать задачи команде.\n\n"
            "Делегирование нужно каждому руководителю. Важно правильно ставить задачи и контролировать исполнение."
        )

        with patch("telegram_ingest.critic_engine.load_rows", return_value=archive):
            review = critic_review(text)

        self.assertIn("legacy_positioning_risk", review)
        self.assertIn("legacy_positioning_note", review)
        self.assertEqual(review["legacy_positioning_risk"], "medium")
        self.assertEqual(review["method_risk"], "medium")
        self.assertIn("сузить тему", review["rewrite_guidance"].lower())

    def test_detect_synthetic_case_risk_flags_invented_case_details(self) -> None:
        """Invented-looking exact case metrics should trigger a voice/authenticity warning."""

        text = (
            "В одной компании, с которой я работал, мы переписали три роли.\n\n"
            "Через два спринта количество вопросов к собственнику упало на 60%, "
            "а сам собственник получил 8 часов в неделю."
        )

        risk, note = detect_synthetic_case_risk(text)

        self.assertEqual(risk, "high")
        self.assertTrue(note)

    def test_detect_corporate_jargon_risk_flags_consultant_language(self) -> None:
        """Corporate consultant jargon should be treated as a voice risk."""

        text = (
            "Роль должна быть описана через измеримый результат и ЦКП.\n\n"
            "Дальше нужен владелец процесса и правила эскалации."
        )

        risk, note = detect_corporate_jargon_risk(text)

        self.assertEqual(risk, "high")
        self.assertTrue(note)

    def test_critic_review_exposes_voice_authenticity_fields(self) -> None:
        """critic_review should surface voice authenticity diagnostics for synthetic/corporate drift."""

        archive = [
            _archive_row(
                14,
                "роль и ответственность",
                "Без ролей и ответственности управляемость не появляется.",
                "через перегрузку собственника",
            )
        ]
        text = (
            "⚠️ Сильная команда не гарантирует управляемость\n\n"
            "В одной компании, с которой я работал, мы переписали три роли.\n\n"
            "Через два спринта количество вопросов к собственнику упало на 60%."
        )

        with patch("telegram_ingest.critic_engine.load_rows", return_value=archive):
            review = critic_review(text)

        self.assertIn("voice_authenticity_risk", review)
        self.assertIn("voice_authenticity_note", review)
        self.assertIn(review["voice_authenticity_risk"], {"medium", "high"})
        guidance = review["rewrite_guidance"].lower()
        self.assertTrue("синтет" in guidance or "выдум" in guidance)


if __name__ == "__main__":
    unittest.main()
