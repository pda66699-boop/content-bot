from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from .editorial_metadata import normalize_editorial_metadata


@dataclass
class NormalizedTelegramPost:
    post_id: str
    telegram_chat_id: str
    telegram_message_id: int
    date: str
    time: str | None
    published_at: str
    edited_at: str | None
    source: str
    title_hook: str
    body_text: str
    body_summary: str
    primary_theme: str | None
    secondary_themes: list[str]
    format: str
    content_role: str
    funnel_stage: str
    core_thesis: str | None
    cta_type: str
    cta_present: bool
    cta_target: str | None
    hashtags: list[str]
    mentions_ai: bool
    mentions_offer: bool
    novelty_keys: list[str]
    manual_review_required: bool
    knowledge_base_version: str | None
    primary_thesis: str | None = None
    secondary_theses: list[str] | None = None
    angle: str = ""
    content_goal: str = "expert"
    business_dimensions: list[str] | None = None
    format_type: str = "expert"
    novelty_window_days: int = 30

    def to_record(self) -> dict[str, Any]:
        """Serialize the dataclass into a backward-compatible post record."""

        return normalize_editorial_metadata(asdict(self))
