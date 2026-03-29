from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from telegram_ingest.editorial_metadata import ensure_editorial_metadata, normalize_editorial_metadata
from telegram_ingest.memory_sync import load_posts_index


class EditorialMetadataNormalizationTests(unittest.TestCase):
    """Cover backward-compatible normalization of editorial metadata."""

    def test_normalize_editorial_metadata_adds_missing_fields_from_legacy_card(self) -> None:
        """Legacy post cards should gain safe editorial metadata defaults."""

        legacy = {
            "post_id": "2026-01-26_1200",
            "date": "2026-01-26",
            "title_hook": "Почему оптимизация издержек почти всегда не там, где её ищут",
            "body_summary": "Короткое описание",
            "primary_theme": "скрытые потери в операционке",
            "secondary_themes": ["издержки", "процессы"],
            "format": "expert",
            "content_role": "diagnostic",
            "funnel_stage": "problem-aware",
            "core_thesis": "Настоящие потери прячутся в процессах, а не только в бюджете.",
        }

        normalized = normalize_editorial_metadata(legacy)

        self.assertEqual(normalized["primary_thesis"], legacy["core_thesis"])
        self.assertEqual(normalized["secondary_theses"], legacy["secondary_themes"])
        self.assertEqual(normalized["angle"], "")
        self.assertEqual(normalized["content_goal"], "diagnostic")
        self.assertEqual(normalized["funnel_stage"], "problem_aware")
        self.assertEqual(normalized["business_dimensions"], [])
        self.assertEqual(normalized["format_type"], "expert")
        self.assertEqual(normalized["novelty_window_days"], 30)

    def test_ensure_editorial_metadata_alias_preserves_contract(self) -> None:
        """Compatibility alias should return the same normalized shape."""

        row = {
            "primary_theme": "оргструктура и роли",
            "core_thesis": "Без ролей нет управляемости.",
            "content_role": "expert",
            "format": "expert",
        }

        normalized = ensure_editorial_metadata(row)

        self.assertEqual(normalized["primary_thesis"], "Без ролей нет управляемости.")
        self.assertEqual(normalized["content_goal"], "expert")
        self.assertEqual(normalized["format_type"], "expert")

    def test_normalize_editorial_metadata_coerces_invalid_types(self) -> None:
        """Malformed editorial fields should be coerced instead of raising errors."""

        normalized = normalize_editorial_metadata(
            {
                "primary_thesis": 123,
                "secondary_theses": "операционка",
                "content_goal": None,
                "business_dimensions": ("финансы", "операции", "финансы"),
                "format_type": None,
                "novelty_window_days": "0",
            }
        )

        self.assertEqual(normalized["primary_thesis"], "123")
        self.assertEqual(normalized["secondary_theses"], ["операционка"])
        self.assertEqual(normalized["content_goal"], "expert")
        self.assertEqual(normalized["business_dimensions"], ["финансы", "операции"])
        self.assertEqual(normalized["format_type"], "expert")
        self.assertEqual(normalized["novelty_window_days"], 30)

    def test_load_posts_index_normalizes_old_rows(self) -> None:
        """Reading old JSONL rows should stay backward-compatible."""

        with tempfile.TemporaryDirectory() as tmp_dir:
            posts_index_path = Path(tmp_dir) / "posts_index.jsonl"
            posts_index_path.write_text(
                json.dumps(
                    {
                        "post_id": "legacy-1",
                        "date": "2026-03-01",
                        "time": "12:00",
                        "title_hook": "Старый пост",
                        "body_summary": "Описание",
                        "primary_theme": "оргструктура и роли",
                        "secondary_themes": [],
                        "format": "expert",
                        "content_role": "expert",
                        "funnel_stage": "aware",
                        "core_thesis": "Роли важнее героизма.",
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )

            with patch("telegram_ingest.memory_sync.POSTS_INDEX_PATH", posts_index_path):
                rows = load_posts_index()

            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["primary_thesis"], "Роли важнее героизма.")
            self.assertEqual(rows[0]["secondary_theses"], [])
            self.assertEqual(rows[0]["format_type"], "expert")

    def test_normalize_editorial_metadata_canonicalizes_funnel_stage(self) -> None:
        """Legacy stage labels should be normalized into one canonical slug."""

        normalized = normalize_editorial_metadata({"funnel_stage": "solution-aware"})

        self.assertEqual(normalized["funnel_stage"], "solution_aware")


if __name__ == "__main__":
    unittest.main()
