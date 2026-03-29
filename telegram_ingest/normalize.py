from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

from .editorial_metadata import DEFAULT_NOVELTY_WINDOW_DAYS
from .knowledge import get_active_knowledge_version
from .models import NormalizedTelegramPost


LOGGER = logging.getLogger(__name__)


HASHTAG_RE = re.compile(r"#([A-Za-zА-Яа-я0-9_]+)")
CTA_PATTERNS = ("@pda33", "диагност", "комментар", "напиши", "напишите", "бот")
AI_REGEXES = (
    re.compile(r"\bИИ\b", re.IGNORECASE),
    re.compile(r"\bAI\b", re.IGNORECASE),
    re.compile(r"\bGPT\b", re.IGNORECASE),
    re.compile(r"chatgpt", re.IGNORECASE),
    re.compile(r"нейросет", re.IGNORECASE),
    re.compile(r"нейросотрудник", re.IGNORECASE),
)


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def infer_content_role(text: str) -> str:
    lower = text.lower()
    if any(token in lower for token in ("кейс", "история", "пример", "domino")):
        return "case"
    if any(token in lower for token in ("почему", "ошибка", "симптом", "проблем")):
        return "diagnostic"
    if any(token in lower for token in ("как ", "шаг", "признак", "инструмент", "разобрал", "гайд")):
        return "applied"
    return "expert"


def infer_funnel_stage(text: str, cta_present: bool) -> str:
    lower = text.lower()
    if cta_present:
        return "solution-aware"
    if any(token in lower for token in ("ошибка", "симптом", "проблем", "почему")):
        return "problem-aware"
    return "aware"


def infer_cta_target(lower: str) -> str | None:
    if "@pda33" in lower:
        return "personal_dm"
    if "диагност" in lower:
        return "diagnostic"
    if "комментар" in lower:
        return "comments"
    if "бот" in lower:
        return "bot"
    return None


def extract_message(update: dict) -> tuple[str, dict] | None:
    if "channel_post" in update:
        return "channel_post", update["channel_post"]
    if "edited_channel_post" in update:
        return "edited_channel_post", update["edited_channel_post"]
    return None


def normalize_update(update: dict) -> NormalizedTelegramPost | None:
    extracted = extract_message(update)
    if extracted is None:
        return None

    update_type, message = extracted
    text = message.get("text") or message.get("caption")
    if not text or not normalize_text(text):
        return None

    chat_id = message.get("chat", {}).get("id")
    message_id = message.get("message_id")
    raw_date = message.get("date")
    if chat_id is None or message_id is None or raw_date is None:
        LOGGER.warning(
            "Skipping update: missing required fields (chat.id=%s, message_id=%s, date=%s)",
            chat_id,
            message_id,
            raw_date,
        )
        return None

    normalized_text = normalize_text(text)
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    title_hook = lines[0] if lines else normalized_text[:120]
    hashtags = HASHTAG_RE.findall(text)
    lower = normalized_text.lower()
    cta_present = any(token in lower for token in CTA_PATTERNS)
    mentions_ai = any(regex.search(normalized_text) for regex in AI_REGEXES)
    published_at = datetime.fromtimestamp(raw_date, tz=timezone.utc).isoformat()
    edited_at = None
    if update_type == "edited_channel_post" and message.get("edit_date"):
        edited_at = datetime.fromtimestamp(message["edit_date"], tz=timezone.utc).isoformat()

    date_part = published_at[:10]
    time_part = published_at[11:16]
    post_id = f"tg_{chat_id}_{message_id}"
    media_type = detect_media_type(message)

    return NormalizedTelegramPost(
        post_id=post_id,
        telegram_chat_id=str(chat_id),
        telegram_message_id=message_id,
        date=date_part,
        time=time_part,
        published_at=published_at,
        edited_at=edited_at,
        source=update_type,
        title_hook=title_hook,
        body_text=text.strip(),
        body_summary=normalized_text[:280],
        primary_theme=None,
        secondary_themes=[],
        format="expert",
        content_role=infer_content_role(normalized_text),
        funnel_stage=infer_funnel_stage(normalized_text, cta_present),
        core_thesis=None,
        cta_type="soft" if cta_present else "none",
        cta_present=cta_present,
        cta_target=infer_cta_target(lower) if cta_present else None,
        hashtags=hashtags,
        mentions_ai=mentions_ai,
        mentions_offer=cta_present,
        novelty_keys=[],
        manual_review_required=True,
        knowledge_base_version=get_active_knowledge_version(),
        primary_thesis=None,
        secondary_theses=[],
        angle="",
        content_goal=infer_content_role(normalized_text),
        business_dimensions=[],
        format_type="expert",
        novelty_window_days=DEFAULT_NOVELTY_WINDOW_DAYS,
    )


def detect_media_type(message: dict) -> str:
    if "photo" in message:
        return "photo"
    if "video" in message:
        return "video"
    if "document" in message:
        return "document"
    return "text"
