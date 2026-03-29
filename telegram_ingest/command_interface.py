from __future__ import annotations

import json
import os
import re
import html
from dataclasses import dataclass
from pathlib import Path

from .editorial_memory import build_feedback_confirmation, record_editorial_feedback
from .knowledge import load_editorial_feedback
from .planner_engine import plan_next_topics
from .publishable_engine import generate_publishable_post


@dataclass
class CommandResult:
    command: str
    theme: str | None
    payload: dict


def sanitize_user_theme(text: str | None) -> str | None:
    if text is None:
        return None
    cleaned = text.strip()
    cleaned = cleaned.lstrip("*-•").strip()
    if cleaned.startswith("—"):
        cleaned = cleaned[1:].strip()
    return cleaned or None


def normalize_topic(text: str | None) -> str:
    if not text:
        return ""
    text = text.lower().replace("ё", "е")
    text = "".join(ch if ch.isalnum() or ch.isspace() else " " for ch in text)
    return " ".join(text.split())


def topic_match_score(a: str | None, b: str | None) -> float:
    aw = set(normalize_topic(a).split())
    bw = set(normalize_topic(b).split())
    if not aw or not bw:
        return 0.0
    return len(aw & bw) / len(aw | bw)


def select_applied_feedback(theme: str | None, final_text: str, limit: int = 3) -> list[dict]:
    notes = [row for row in load_editorial_feedback() if row.get("status") == "active"]
    haystack = f"{theme or ''} {final_text}".lower().replace("ё", "е")
    haystack_words = set(re.findall(r"[a-zа-я0-9]+", haystack))

    scored: list[tuple[float, dict]] = []
    for row in notes:
        summary = (row.get("summary") or "").lower().replace("ё", "е")
        score = 0.0
        summary_words = set(re.findall(r"[a-zа-я0-9]+", summary))
        if summary_words:
            score += len(haystack_words & summary_words) / len(summary_words)
        if row.get("impact") == "high":
            score += 0.25
        if row.get("category") in {"style", "quality"}:
            score += 0.1
        if "ии" in summary and "ии" in haystack:
            score += 0.4
        if "расход" in summary and any(token in haystack for token in ("расход", "налог", "цен", "издерж")):
            score += 0.4
        if "эмод" in summary:
            emoji_count = len(re.findall(r"[\U0001F300-\U0001FAFF\u2600-\u27BF]", final_text))
            if emoji_count >= 1:
                score += 0.35
        if "шаблон" in summary and any(token in final_text.lower() for token in ("главный вопрос здесь", "если смотреть глубже")):
            score -= 0.2
        if score > 0.14:
            scored.append((score, row))

    scored.sort(key=lambda item: item[0], reverse=True)
    return [row for _, row in scored[:limit]]


def parse_post_command(raw_text: str) -> dict:
    text = raw_text.strip()
    if not text:
        return {"command": None, "theme": None}

    if text.startswith("/post"):
        theme = sanitize_user_theme(text[5:].strip() or None)
        return {"command": "post", "theme": theme}

    if text.startswith("/note"):
        note = sanitize_user_theme(text[5:].strip() or None)
        return {"command": "note", "theme": note}

    return {"command": None, "theme": sanitize_user_theme(text)}


def build_post_command_result(
    theme: str | None,
    goal: str = "expert",
    exclude_variants: set[int] | None = None,
    preferred_cta_mode: str | None = None,
    angle: str | None = None,
    case_context: dict | None = None,
    topic_brief: dict | None = None,
) -> CommandResult:
    plan = plan_next_topics(user_theme=theme, business_goal=goal)
    publishable = generate_publishable_post(
        theme=theme,
        angle=angle,
        business_goal=goal,
        draft_count=4,
        exclude_variants=exclude_variants,
        preferred_cta_mode=preferred_cta_mode,
        case_context=case_context,
        topic_brief=topic_brief,
    )

    alternative = None
    candidates = plan.get("best_next_topics", [])
    if len(candidates) > 1:
        candidate = candidates[1]
        if theme is None or topic_match_score(theme, candidate.get("theme")) >= 0.18:
            alternative = candidate

    primary_open_loop = None
    open_loops = plan.get("open_loops", [])
    if open_loops:
        selected_theme = publishable["selected_theme"]
        matches = sorted(
            open_loops,
            key=lambda item: topic_match_score(selected_theme, item.get("open_loop_topic")),
            reverse=True,
        )
        if matches and topic_match_score(selected_theme, matches[0].get("open_loop_topic")) >= 0.15:
            primary_open_loop = matches[0]

    payload = {
        "selected_theme": publishable["selected_theme"],
        "selected_angle": publishable["selected_angle"],
        "final_text": publishable["final_text"],
        "why_now": publishable["why_now"],
        "cta_explanation": publishable["cta_explanation"],
        "repeat_risk": publishable["critic_review"]["repeat_risk"],
        "user_theme_verdict": publishable["user_theme_verdict"],
        "alternative_angle": alternative,
        "open_loop_used": primary_open_loop,
        "critic_review": publishable["critic_review"],
        "positioning_flags": publishable["positioning_flags"],
        "applied_feedback": select_applied_feedback(theme or publishable["selected_theme"], publishable["final_text"]),
        "chosen_variant": publishable["chosen_variant"],
        "preferred_cta_mode": preferred_cta_mode,
        "case_context": case_context,
        "topic_brief": topic_brief,
    }
    return CommandResult(command="post", theme=theme, payload=payload)


def build_note_command_result(note: str | None) -> CommandResult:
    if not note:
        raise ValueError("Expected note text")
    lowered = note.lower()
    category = "quality"
    if any(token in lowered for token in ("термин", "слово", "лексик", "понят")):
        category = "terminology"
    elif any(token in lowered for token in ("позиционир", "оффер", "воронк", "cta")):
        category = "positioning"
    elif any(token in lowered for token in ("стиль", "эмод", "ритм", "жив", "шаблон")):
        category = "style"

    impact = "high" if any(token in lowered for token in ("главн", "критич", "обязательно", "нельзя")) else "medium"
    row = record_editorial_feedback(summary=note, category=category, impact=impact, status="active", source="user")
    return CommandResult(
        command="note",
        theme=note,
        payload={
            "saved_feedback": row,
            "confirmation_text": build_feedback_confirmation(row),
        },
    )


def should_include_post_metadata() -> bool:
    raw = os.environ.get("CONTENT_BOT_SHOW_POST_METADATA", "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def format_post_command_metadata(result: CommandResult) -> str:
    payload = result.payload
    lines = []

    verdict = payload.get("user_theme_verdict") or {}
    if verdict.get("status") and verdict.get("status") != "none":
        lines.append(
            f"Вердикт по вашей теме: {verdict.get('status')} — {verdict.get('comment')}"
        )

    alternative = payload.get("alternative_angle")
    if alternative:
        lines.append(
            f"Альтернативный угол: {alternative.get('theme')} — {alternative.get('angle')}"
        )

    open_loop = payload.get("open_loop_used")
    if open_loop:
        lines.append(
            f"Открытый крючок: {open_loop.get('open_loop_topic')} ({open_loop.get('status')})"
        )

    applied_feedback = payload.get("applied_feedback") or []
    if applied_feedback:
        lines.append("Учтённые замечания (beta):")
        for row in applied_feedback:
            lines.append(f"– {row.get('summary')}")

    return "\n".join(lines).strip()


def escape_with_breaks(text: str) -> str:
    return html.escape(text)


def format_post_for_telegram_html(text: str) -> str:
    paragraphs = [part.strip() for part in text.strip().split("\n\n") if part.strip()]
    if not paragraphs:
        return ""

    heading_map = {
        "например:": "🧩",
        "что обычно происходит:": "⚙️",
        "чтобы не лечить всё подряд, полезно проверить 3 вещи:": "🔎",
        "без пауз обычно происходит одно и то же:": "🔎",
        "что для меня оказалось самым ценным:": "✨",
        "здесь полезно начать с трёх вещей:": "🧱",
        "здесь полезно начать с трех вещей:": "🧱",
    }

    rendered: list[str] = []
    for idx, paragraph in enumerate(paragraphs):
        lowered = paragraph.lower()
        lines = paragraph.splitlines()

        if idx == 0:
            first = paragraph
            if not re.search(r"[\U0001F300-\U0001FAFF\u2600-\u27BF]", first):
                first = f"📍 {first}"
            rendered.append(f"<b>{escape_with_breaks(first)}</b>")
            continue

        if lowered in heading_map:
            rendered.append(f"<b>{heading_map[lowered]} {html.escape(paragraph)}</b>")
            continue

        if len(lines) > 1 and lines[0].strip().lower() in heading_map:
            heading = f"<b>{heading_map[lines[0].strip().lower()]} {html.escape(lines[0].strip())}</b>"
            body = "\n".join(html.escape(line) for line in lines[1:])
            rendered.append(f"{heading}\n{body}" if body else heading)
            continue

        if len(lines) > 1 and all(line.lstrip().startswith(("– ", "• ", "🔧", "⚙️", "📌", "✅")) for line in lines):
            rendered.append("\n".join(html.escape(line) for line in lines))
            continue

        if paragraph.startswith("– "):
            rendered.append("\n".join(html.escape(line) for line in lines))
            continue

        if any(token in lowered for token in ("@adizesbizbot", "@pda33", "пройти диагност", "короткую диагност", "в личку")):
            cta_text = paragraph
            if not cta_text.startswith("🎯"):
                cta_text = f"🎯 {cta_text}"
            rendered.append(f"<blockquote>{escape_with_breaks(cta_text)}</blockquote>")
            continue

        if lowered.startswith(("на поверхности", "иногда кажется", "снаружи это выглядит")):
            rendered.append(f"<blockquote>{escape_with_breaks(paragraph)}</blockquote>")
            continue

        if len(lines) == 1 and paragraph.endswith(":") and len(paragraph) < 80:
            rendered.append(f"<b>{html.escape(paragraph)}</b>")
            continue

        rendered.append(escape_with_breaks(paragraph))

    return "\n\n".join(rendered)


def format_post_command_response(result: CommandResult) -> str:
    payload = result.payload
    final_text = payload["final_text"].strip()
    formatted = format_post_for_telegram_html(final_text)
    if not should_include_post_metadata():
        return formatted

    metadata = format_post_command_metadata(result)
    if metadata:
        return f"{formatted}\n\n<i>— Служебная аналитика —</i>\n{escape_with_breaks(metadata)}"
    return formatted


def format_note_command_response(result: CommandResult) -> str:
    return result.payload["confirmation_text"]
