from __future__ import annotations

from contextlib import contextmanager
from datetime import date, timedelta
from typing import Iterator
from unittest.mock import patch


def archive_row(
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
    body_text: str | None = None,
) -> dict:
    """Return a stable archive row fixture for planner regression scenarios."""

    current_date = date.today() - timedelta(days=days_ago)
    return {
        "post_id": f"row-{days_ago}-{abs(hash(primary_theme + primary_thesis)) % 10000}",
        "date": current_date.isoformat(),
        "time": "12:00",
        "title_hook": primary_theme,
        "body_summary": primary_thesis,
        "body_text": body_text or primary_thesis,
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


@contextmanager
def patched_planner_runtime(
    archive: list[dict],
    *,
    open_loops: list[dict] | None = None,
    backlog: list[dict] | None = None,
    llm_candidates: list[dict] | None = None,
) -> Iterator[None]:
    """Patch planner runtime dependencies for stable regression scenarios."""

    with patch("telegram_ingest.planner_engine.load_posts", return_value=archive), patch(
        "telegram_ingest.planner_engine.get_high_priority_open_loops",
        return_value=open_loops or [],
    ), patch(
        "telegram_ingest.editorial_evaluation.get_high_priority_open_loops",
        return_value=open_loops or [],
    ), patch(
        "telegram_ingest.planner_engine.load_backlog",
        return_value=backlog or [],
    ), patch(
        "telegram_ingest.planner_engine.maybe_generate_planner_candidates",
        return_value=llm_candidates,
    ):
        yield
