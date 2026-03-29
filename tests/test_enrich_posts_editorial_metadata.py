from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.enrich_posts_editorial_metadata import (  # noqa: E402
    enrich_row,
    has_incomplete_editorial_metadata,
)


class EnrichPostsEditorialMetadataTests(unittest.TestCase):
    """Cover archival enrichment helpers without touching the real index."""

    def test_incomplete_editorial_metadata_is_detected(self) -> None:
        """Legacy rows without semantic layer should be marked as incomplete."""

        row = {
            "post_id": "legacy-1",
            "title_hook": "Старый пост",
            "primary_theme": "оргструктура и роли",
            "core_thesis": "Без ролей нет управляемости.",
            "format": "expert",
            "content_role": "expert",
            "funnel_stage": "aware",
        }

        self.assertTrue(has_incomplete_editorial_metadata(row))

    def test_enrich_row_fills_editorial_fields(self) -> None:
        """Row enrichment should add semantic metadata even in rules-only mode."""

        row = {
            "post_id": "legacy-2",
            "title_hook": "Почему потери не видны в расходах",
            "primary_theme": "скрытые потери в операционке",
            "body_text": "Потери сидят в процессах и ручном труде.",
            "body_summary": "Потери сидят в процессах и ручном труде.",
            "format": "expert",
            "content_role": "diagnostic",
            "funnel_stage": "problem-aware",
            "core_thesis": None,
        }

        enriched, changed = enrich_row(row, prefer_llm=False)

        self.assertTrue(changed)
        self.assertTrue(enriched["primary_thesis"])
        self.assertTrue(enriched["business_dimensions"])
        self.assertTrue(enriched["angle"])


if __name__ == "__main__":
    unittest.main()
