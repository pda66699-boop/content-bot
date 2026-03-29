from __future__ import annotations

import html
import logging
import os
from collections import Counter

from .backlog_memory import (
    add_themes_to_backlog,
    add_structured_theme_to_backlog,
    delete_backlog_theme,
    format_backlog_save_confirmation,
    get_backlog_topics,
    mark_backlog_theme_used,
)
from .bot_api import answer_callback_query, send_message, send_message_with_markup
from .bot_state import clear_session_field, get_session, save_session
from .case_research_engine import research_case_topics, verify_case
from .command_interface import (
    build_note_command_result,
    build_post_command_result,
    format_note_command_response,
    format_post_for_telegram_html,
    format_post_command_response,
    parse_post_command,
)
from .critic_engine import critic_review
from .open_loops import get_high_priority_open_loops, get_open_loops_chronological
from .planner_engine import classify_post_pillar, contains_ai_signal, load_posts, plan_next_topics
from .polish_engine import polish_text
from .positioning import resolve_cta_strategy
from .rewrite_engine import build_rewrite_plan_from_improvement, rewrite_post_by_improvement, rewrite_post_in_author_style
from .ui import (
    BUTTON_ANALYTICS,
    BUTTON_BACK_TO_MENU,
    BUTTON_BACKLOG_DELETE,
    BUTTON_BACKLOG_MARK_USED,
    BUTTON_CASES,
    BUTTON_CHECK_CASE,
    BUTTON_MORE_CASES,
    BUTTON_RESET_CASES,
    BUTTON_RESET_TOPICS,
    BUTTON_SECTION_ANALYTICS,
    BUTTON_SECTION_CASES,
    BUTTON_SECTION_MY_TOPICS,
    BUTTON_SECTION_REWRITE,
    BUTTON_EVALUATE,
    BUTTON_EVALUATE_POST,
    BUTTON_MODE_CONVERSATIONAL,
    BUTTON_MODE_EXPERT,
    BUTTON_MODE_MONEY,
    BUTTON_MORE_TOPICS,
    BUTTON_REWRITE,
    BUTTON_SAVE_TOPICS,
    BUTTON_TOPICS,
    BUTTON_VIEW_BACKLOG,
    BUTTON_WRITE,
    CALLBACK_ACCEPT,
    CALLBACK_ANALYZE,
    CALLBACK_BUILD_VERIFIED_CASE_POST,
    CALLBACK_CASE_TOPIC_PICK_PREFIX,
    CALLBACK_FORGET,
    CALLBACK_IMPROVE,
    CALLBACK_NEXT_VARIANT,
    CALLBACK_REWRITE_OPTION_1,
    CALLBACK_REWRITE_OPTION_2,
    CALLBACK_SAVE_VERIFIED_CASE,
    CALLBACK_SAVE_TO_TOPICS,
    CALLBACK_SAVE_RULE,
    CALLBACK_REVISE,
    build_analytics_menu_keyboard,
    build_main_menu_keyboard,
    build_backlog_keyboard,
    build_case_pick_keyboard,
    build_cases_menu_keyboard,
    build_case_topic_suggestion_keyboard,
    build_my_topics_menu_keyboard,
    build_post_improvement_keyboard,
    build_post_mode_keyboard,
    build_post_actions_keyboard,
    build_rewrite_menu_keyboard,
    build_topic_pick_keyboard,
    build_verified_case_keyboard,
)


MAX_MESSAGE_LEN = 3800
LOGGER = logging.getLogger(__name__)

RUBRIC_LABELS = {
    "case": "Кейс",
    "mistake_breakdown": "Разбор ошибки",
    "diagnostic_entry": "Диагностика",
    "reflective_observation": "Личное наблюдение",
    "flagship_warmup": "Прогрев к флагману",
    "expert_explainer": "Экспертный разбор",
}


def get_allowed_user_ids() -> set[int]:
    raw = os.environ.get("TELEGRAM_ALLOWED_USER_IDS", "").strip()
    if not raw:
        return set()
    allowed: set[int] = set()
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            allowed.add(int(part))
        except ValueError:
            logging.getLogger(__name__).warning(
                "Invalid value %r in TELEGRAM_ALLOWED_USER_IDS — skipping", part
            )
    return allowed


def split_plain_message(text: str, limit: int = MAX_MESSAGE_LEN) -> list[str]:
    if len(text) <= limit:
        return [text]

    chunks: list[str] = []
    current = text
    while len(current) > limit:
        split_at = current.rfind("\n\n", 0, limit)
        if split_at == -1:
            split_at = current.rfind("\n", 0, limit)
        if split_at == -1:
            split_at = limit
        chunks.append(current[:split_at].strip())
        current = current[split_at:].strip()
    if current:
        chunks.append(current)
    return chunks


def split_html_message(text: str, limit: int = MAX_MESSAGE_LEN) -> list[str]:
    if len(text) <= limit:
        return [text]

    sections = [section for section in text.split("\n\n") if section.strip()]
    if not sections:
        return [text]

    chunks: list[str] = []
    current = ""
    for section in sections:
        candidate = f"{current}\n\n{section}".strip() if current else section
        if len(candidate) <= limit:
            current = candidate
            continue
        if current:
            chunks.append(current)
            current = section
            if len(current) <= limit:
                continue
        # Fallback for an unusually large single section: split only on HTML-safe line boundaries.
        safe_lines = section.split("\n")
        current = ""
        for line in safe_lines:
            candidate = f"{current}\n{line}".strip() if current else line
            if len(candidate) <= limit:
                current = candidate
                continue
            if current:
                chunks.append(current)
            current = line
        if current:
            chunks.append(current)
            current = ""

    if current:
        chunks.append(current)
    return chunks


def split_message(text: str, limit: int = MAX_MESSAGE_LEN, parse_mode: str | None = None) -> list[str]:
    if parse_mode == "HTML":
        return split_html_message(text, limit=limit)
    return split_plain_message(text, limit=limit)


def send_chunks(chat_id: int | str, text: str, reply_markup: dict | None = None, parse_mode: str | None = None) -> None:
    chunks = split_message(text, parse_mode=parse_mode)
    for idx, chunk in enumerate(chunks):
        if idx == 0 and reply_markup is not None:
            send_message_with_markup(chat_id, chunk, reply_markup=reply_markup, parse_mode=parse_mode)
        else:
            send_message(chat_id, chunk, parse_mode=parse_mode)


def send_rich_chunks(chat_id: int | str, text: str, reply_markup: dict | None = None) -> None:
    send_chunks(chat_id, text, reply_markup=reply_markup, parse_mode="HTML")


def format_rich_block(title: str, items: list[str], icon: str | None = None) -> str:
    header = f"<b>{html.escape(f'{icon} {title}' if icon else title)}</b>"
    body = "\n".join(f"• {html.escape(item)}" for item in items)
    return f"{header}\n{body}" if body else header


def escape_with_breaks(text: str) -> str:
    return html.escape(text)


def html_block(text: str, tag: str = "b") -> str:
    return f"<{tag}>{html.escape(text)}</{tag}>"


def html_join(*parts: str) -> str:
    return "\n\n".join(part for part in parts if part)


def format_rich_text(text: str) -> str:
    sections = [part.strip() for part in text.split("\n\n") if part.strip()]
    rendered: list[str] = []
    for idx, section in enumerate(sections):
        if idx == 0:
            rendered.append(f"<b>{html.escape(section)}</b>")
            continue
        if section.endswith(":") and len(section) < 80:
            rendered.append(f"<b>{html.escape(section)}</b>")
            continue
        lines = section.splitlines()
        if lines and all(line.startswith("– ") or line.startswith("• ") for line in lines):
            rendered.append("\n".join(f"• {html.escape(line[2:].strip())}" for line in lines))
            continue
        if lines and lines[0].endswith(":") and len(lines) > 1:
            title = lines[0][:-1]
            body = [line[2:].strip() if line.startswith("– ") else line.strip() for line in lines[1:]]
            rendered.append(format_rich_block(title, body))
            continue
        rendered.append(html.escape(section))
    return "\n\n".join(rendered)


def build_help_text() -> str:
    return (
        "<b>Привет. Я собран как рабочий редакторский бот для контента канала</b>\n\n"
        "<b>Главные разделы:</b>\n"
        "• ✨ Предложить 5 тем\n"
        "• 🌐 Кейсы\n"
        "• 📊 Аналитика канала\n"
        "• 📚 Мои темы\n"
        "• ♻️ Рерайт\n\n"
        "<b>Что внутри:</b>\n"
        "• в «Кейсы» — поиск и проверка кейсов\n"
        "• в «Аналитика канала» — аналитика ленты и оценка тем/постов\n"
        "• в «Мои темы» — написать пост, сохранить темы и открыть backlog\n\n"
        "<blockquote>🧠 Команда <code>/note &lt;замечание&gt;</code> сохраняет правило в долгосрочную память</blockquote>"
    )


def format_feed_analytics() -> str:
    rows = load_posts()
    recent = rows[-15:]
    if not recent:
        return "📊 Пока не вижу постов в памяти канала, поэтому аналитику собрать не из чего."

    pillar_counts = Counter(classify_post_pillar(row) for row in recent)
    loops = get_open_loops_chronological(reverse=True)[:5]
    plan = plan_next_topics()
    recommendation = plan.get("recommended_topic_now") or {}
    content_balance = plan.get("content_balance") or {}
    cta_balance = plan.get("cta_balance") or {}
    rubric_balance = plan.get("rubric_balance") or {}
    weekly_funnel = plan.get("weekly_funnel") or {}
    publishing_cadence = plan.get("publishing_cadence") or {}
    publication_feedback = plan.get("publication_feedback") or {}
    weekly_plan = plan.get("weekly_plan") or []
    needs = content_balance.get("needs") or {}
    cta_needs = cta_balance.get("needs") or {}
    rubric_needs = rubric_balance.get("needs") or {}
    campaign_mode = (plan.get("positioning_flags") or {}).get("campaign_mode") or "base"

    pillar_labels = {
        "expert": "Экспертный",
        "conversational": "Разговорный",
        "money": "Денежный",
    }

    lines = ["<b>📊 Аналитика последних 15 постов</b>", "", "<b>⚖️ Соотношение типов:</b>"]
    for pillar in ("expert", "conversational", "money"):
        count = pillar_counts.get(pillar, 0)
        ratio = round((count / len(recent)) * 100)
        lines.append(f"– {pillar_labels[pillar]}: {count} ({ratio}%)")

    lines.append("")
    lines.append(f"<b>🎛 Режим кампании:</b> {html.escape(campaign_mode)}")
    lines.append(f"<b>📅 Публикаций за 7 дней:</b> {int(publishing_cadence.get('published_last_7_days', 0))} из {int(publishing_cadence.get('weekly_cap', 3))}")
    lines.append(f"<b>🕳 Свободных слотов на неделе:</b> {int(publishing_cadence.get('weekly_slots_left', 0))}")

    lines.append("")
    lines.append("<b>🧭 Баланс рубрик:</b>")
    for rubric_key, label in RUBRIC_LABELS.items():
        count = int((rubric_balance.get("recent_counts") or {}).get(rubric_key, 0))
        ratio = round(((rubric_balance.get("recent_ratios") or {}).get(rubric_key, 0)) * 100)
        lines.append(f"– {label}: {count} ({ratio}%)")

    rubric_missing = [RUBRIC_LABELS[key] for key, value in rubric_needs.items() if value > 0.08 and key in RUBRIC_LABELS]
    if rubric_missing:
        lines.append("")
        lines.append("<b>🧩 Чего не хватает по рубрикам:</b>")
        for item in rubric_missing[:3]:
            lines.append(f"– {item}")

    cta_labels = {
        "comments": "Обсуждение",
        "diagnostic": "@adizesbizbot",
        "personal": "Личка",
        "none": "Без CTA",
    }
    lines.append("")
    lines.append("<b>🧲 Баланс CTA:</b>")
    for cta_key in ("comments", "diagnostic", "personal", "none"):
        count = int((cta_balance.get("recent_counts") or {}).get(cta_key, 0))
        ratio = round(((cta_balance.get("recent_ratios") or {}).get(cta_key, 0)) * 100)
        lines.append(f"– {cta_labels[cta_key]}: {count} ({ratio}%)")

    cta_missing = [cta_labels[key] for key, value in cta_needs.items() if value > 0.08 and key in cta_labels]
    cta_overheated = [cta_labels[key] for key, value in cta_needs.items() if value < -0.08 and key in cta_labels]

    lines.append("")
    lines.append("<b>📣 Чего не хватает по CTA:</b>")
    if cta_missing:
        for item in cta_missing:
            lines.append(f"– {item}")
    else:
        lines.append("– CTA-ритм сейчас выглядит достаточно ровно")

    lines.append("")
    lines.append("<b>🧯 Что перегрето по CTA:</b>")
    if cta_overheated:
        for item in cta_overheated:
            lines.append(f"– <s>{item}</s>")
    else:
        lines.append("– Перегрева по CTA сейчас не вижу")

    lines.append("")
    lines.append("<b>🎯 Что лучше публиковать следующим по CTA:</b>")
    preferred_cta = None
    preferred_need = None
    if cta_missing:
        priority_order = ("comments", "diagnostic", "personal", "none")
        for key in priority_order:
            if key in cta_needs and cta_needs.get(key, 0) > 0.08:
                preferred_cta = key
                break
    if preferred_cta is None:
        if cta_needs.get("none", 0) > 0.03:
            preferred_cta = "none"
        else:
            preferred_cta = "comments"

    if preferred_cta == "comments":
        preferred_need = "лучше закончить пост обсуждением или вопросом в комментарии"
    elif preferred_cta == "diagnostic":
        preferred_need = "сейчас уместнее мягко вести в @adizesbizbot"
    elif preferred_cta == "personal":
        preferred_need = "можно дать редкий персональный CTA в личку, если тема это выдерживает"
    else:
        preferred_need = "следующий пост можно оставить вообще без CTA, чтобы не перегревать воронку"

    lines.append(f"– Приоритет: {cta_labels.get(preferred_cta, 'Не определён')}")
    lines.append(f"– Почему: {preferred_need}")

    weekly_offer_balance = weekly_funnel.get("offer_balance") or {}
    lines.append("")
    lines.append("<b>📆 Связь с оффером и воронкой за неделю:</b>")
    lines.append(f"– Ведут в @adizesbizbot: {int(weekly_offer_balance.get('diagnostic_entry', 0))}")
    lines.append(f"– Греют к 45 дням: {int(weekly_offer_balance.get('warmup', 0))}")
    lines.append(f"– Работают на доверие: {int(weekly_offer_balance.get('trust', 0))}")
    if weekly_offer_balance.get("diagnostic_entry", 0) == 0:
        lines.append("– Провал: за последнюю неделю нет явного входа в диагностику")
    elif weekly_offer_balance.get("warmup", 0) == 0:
        lines.append("– Провал: за последнюю неделю почти нет прогрева к флагману")

    lines.append("")
    feedback_days = int(publication_feedback.get("window_size", 0) or 0)
    lines.append(f"<b>🧪 Что реально публиковалось за {feedback_days} {days_label(feedback_days)}:</b>")
    feedback_notes = publication_feedback.get("notes") or []
    if feedback_notes:
        for note in feedback_notes[:3]:
            lines.append(f"– {html.escape(note)}")
    else:
        lines.append("– Явных провалов по реальному набору публикаций сейчас не вижу")

    lines.append("")
    lines.append("<b>🗓 Что ставить в недельный план:</b>")
    if weekly_plan:
        for idx, item in enumerate(weekly_plan, start=1):
            lines.append(
                f"– {idx}. {html.escape(item.get('theme') or '')} "
                f"({html.escape(RUBRIC_LABELS.get(item.get('marketing_rubric'), item.get('marketing_rubric') or 'Не определена'))} · "
                f"{html.escape(item.get('funnel_stage') or 'Не определена')})"
            )
    else:
        lines.append("– Лимит недели уже закрыт. Лучше не форсировать лишний пост без сильной причины.")

    missing = [pillar_labels[key] for key, value in needs.items() if value > 0.08 and key in pillar_labels]
    overheated = [pillar_labels[key] for key, value in needs.items() if value < -0.08 and key in pillar_labels]

    lines.append("")
    lines.append("<b>🧩 Чего сейчас не хватает ленте:</b>")
    if missing:
        for item in missing:
            lines.append(f"– {item}")
    else:
        lines.append("– Баланс сейчас выглядит ровно, явного дефицита по типам нет")

    lines.append("")
    lines.append("<b>🔥 Что уже перегрето:</b>")
    if overheated:
        for item in overheated:
            lines.append(f"– <s>{item}</s>")
    else:
        lines.append("– Явного перегрева по типам не вижу")

    lines.append("")
    lines.append("<b>🗂 Последние темы:</b>")
    for row in reversed(recent[-6:]):
        theme = row.get("primary_theme") or row.get("title_hook") or "без темы"
        post_date = row.get("date") or "без даты"
        lines.append(f"– {html.escape(post_date)} · {html.escape(theme)}")

    lines.append("")
    if loops:
        lines.append("<b>🪝 Незакрытые петли:</b>")
        for loop in loops[:4]:
            topic = html.escape(loop.get("open_loop_topic") or "")
            status = html.escape(loop.get("status") or "")
            loop_date = html.escape(loop.get("date") or "")
            promise = html.escape(loop.get("promise_excerpt") or loop.get("title_hook") or "")
            lines.append(f"– {loop_date} · {topic} — {status}")
            if promise:
                lines.append(f"  <i>Цитата:</i> «{promise}»")
    else:
        lines.append("<b>🪝 Незакрытые петли:</b>")
        lines.append("– Явных открытых петель сейчас не вижу")

    if recommendation:
        lines.append("")
        lines.append("<b>🎯 Что бот советует следующим:</b>")
        lines.append(f"– Тема: {html.escape(recommendation.get('theme') or '')}")
        lines.append(
            f"– Тип: {html.escape(pillar_labels.get(recommendation.get('content_pillar'), recommendation.get('content_pillar') or 'Не определён'))}"
        )
        lines.append(f"– Рубрика: {html.escape(RUBRIC_LABELS.get(recommendation.get('marketing_rubric'), recommendation.get('marketing_rubric') or 'Не определена'))}")
        lines.append(f"– Стадия воронки: {html.escape(recommendation.get('funnel_stage') or 'Не определена')}")
        lines.append(f"– Почему сейчас: {html.escape(recommendation.get('why_now') or '')}")

    return "\n".join(lines).strip()


def format_post_analytics(text: str, theme_hint: str | None = None) -> str:
    review = critic_review(text)
    plan = plan_next_topics()
    loops = get_high_priority_open_loops()[:5]
    pillar = classify_post_pillar(
        {
            "primary_theme": theme_hint or "",
            "title_hook": text.splitlines()[0] if text.splitlines() else "",
            "content_role": "image" if "#мысли" in text.lower() else "expert",
            "cta_present": any(token in text.lower() for token in ("@adizesbizbot", "@pda33", "диагност")),
            "hashtags": [part for part in text.split() if part.startswith("#")],
        }
    )
    pillar_labels = {
        "expert": "Экспертный",
        "conversational": "Разговорный",
        "money": "Денежный",
    }

    strengths: list[str] = []
    if review.get("repeat_risk") == "low":
        strengths.append("не выглядит прямым повтором последних постов")
    if review.get("style_risk") == "low":
        strengths.append("по стилю не выглядит перегретым или слишком инфобизнесовым")
    if review.get("method_risk") == "low":
        strengths.append("не ломает текущую методологическую рамку канала")
    if review.get("cta_risk") == "low" and any(token in text.lower() for token in ("@adizesbizbot", "@pda33", "диагност")):
        strengths.append("CTA не выглядит слишком навязчивым")

    improvements: list[str] = []
    if review.get("editorial_feedback_note"):
        improvements.append(review["editorial_feedback_note"])
    if review.get("repeat_note"):
        improvements.append(review["repeat_note"])
    if review.get("stop_word_note"):
        improvements.append(review["stop_word_note"])
    if review.get("golden_copy_note"):
        improvements.append(review["golden_copy_note"])
    if review.get("funnel_fit_note"):
        improvements.append(review["funnel_fit_note"])
    if not improvements:
        improvements.append(review.get("rewrite_guidance") or "Сильных замечаний к посту сейчас нет.")

    matching_loops = []
    normalized_text = text.lower()
    for loop in loops:
        topic = (loop.get("open_loop_topic") or "").lower()
        if topic and any(word in normalized_text for word in topic.split()[:3]):
            matching_loops.append(loop)

    recommendation = plan.get("recommended_topic_now") or {}
    fits_now = "да" if recommendation and pillar == recommendation.get("content_pillar") else "частично"

    lines = ["<b>📋 Анализ поста</b>", ""]
    lines.append(f"<b>Тип поста:</b> {html.escape(pillar_labels.get(pillar, pillar))}")
    lines.append(f"<b>Вердикт critic:</b> {html.escape(review.get('verdict') or '')}")
    lines.append(f"<b>Попадание в текущий ритм ленты:</b> {html.escape(fits_now)}")

    lines.append("")
    lines.append("<b>✅ Что в посте уже хорошо:</b>")
    if strengths:
        for item in strengths[:4]:
            lines.append(f"– {item}")
    else:
        lines.append("– Потенциал есть, но сильные стороны пока не очень собраны")

    lines.append("")
    lines.append("<b>🛠 Что стоит усилить:</b>")
    for item in improvements[:4]:
        lines.append(f"– {item}")

    lines.append("")
    if matching_loops:
        lines.append("<b>🪝 Связь с открытыми петлями:</b>")
        for loop in matching_loops[:3]:
            lines.append(f"– Закрывает или касается темы: {html.escape(loop.get('open_loop_topic') or '')}")
    else:
        lines.append("<b>🪝 Связь с открытыми петлями:</b>")
        lines.append("– Явного закрытия открытой петли не вижу")

    if recommendation:
        lines.append("")
        lines.append("<b>🎯 Что советует лента сейчас:</b>")
        lines.append(
            f"– Следующий рекомендуемый режим: {html.escape(pillar_labels.get(recommendation.get('content_pillar'), recommendation.get('content_pillar') or 'Не определён'))}"
        )
        lines.append(f"– Следующая тема: {html.escape(recommendation.get('theme') or '')}")

    return "\n".join(lines).strip()


def build_topic_percent_map(topics: list[dict]) -> dict[str, int]:
    if not topics:
        return {}

    scores = [int(topic.get("score") or 0) for topic in topics]
    min_score = min(scores)
    max_score = max(scores)
    percent_map: dict[str, int] = {}

    for idx, topic in enumerate(topics):
        theme = str(topic.get("theme") or "")
        score = int(topic.get("score") or 0)
        if max_score == min_score:
            percent = max(72, 92 - idx * 4)
        else:
            normalized = (score - min_score) / (max_score - min_score)
            percent = int(round(72 + normalized * 24))
        percent_map[theme] = max(60, min(96, percent))

    return percent_map


def days_label(value: int) -> str:
    value = abs(int(value))
    last_two = value % 100
    last = value % 10
    if 11 <= last_two <= 14:
        return "дней"
    if last == 1:
        return "день"
    if 2 <= last <= 4:
        return "дня"
    return "дней"


def build_topic_fit_comment(topic: dict) -> tuple[str, str | None]:
    why_now = (topic.get("why_now") or "").strip()
    pillar = topic.get("content_pillar") or ""
    angle = (topic.get("angle") or "").strip()
    lowered = why_now.lower()

    if "открытый крючок" in lowered:
        positive = "подходит, потому что тема продолжает уже обещанную линию и помогает не терять логическую связность канала"
        caution = "важно не повторить старую формулировку буквально, а дать новый угол или более прикладной разбор"
        return positive, caution

    if "не хватает живого разговорного слоя" in lowered or pillar == "conversational":
        positive = "подходит, потому что добавляет в ленту более живой и человеческий слой, которого сейчас мало"
        caution = "важно не уйти в абстрактные размышления и всё равно довести пост до понятного вывода"
        return positive, caution

    if "много ии" in lowered:
        positive = "подходит, потому что возвращает фокус из инструментов в архитектуру управления и базовые системные вещи"
        caution = "важно не скатиться в слишком общий экспертный текст без узнаваемой сцены или примера"
        return positive, caution

    if pillar == "money":
        positive = "подходит, потому что тема ближе к деньгам, диагностике и действию, а такие посты уместно двигают воронку"
        caution = "важно, чтобы CTA выглядел логичным продолжением смысла, а не отдельной вставкой"
        return positive, caution

    if pillar == "expert":
        positive = "подходит, потому что усиливает экспертный слой канала и помогает держать позицию через прикладной разбор"
        caution = "важно не уйти в воздух и добавить конкретную ситуацию, пример или инструмент"
        return positive, caution

    positive = "подходит, потому что тема в целом совпадает с текущим ритмом ленты и может дать нормальное продолжение канала"
    caution = None
    if angle:
        caution = "нужно аккуратно удержать заявленный угол, чтобы пост не расплылся и не стал повтором соседних тем"
    return positive, caution


def build_topic_cta_hint(topic: dict, cta_balance: dict) -> tuple[str, str]:
    strategy = resolve_cta_strategy(topic.get("theme") or "", topic.get("content_pillar"))
    cta_needs = cta_balance.get("needs") or {}
    allowed = set(strategy.get("allowed_ctas") or [])

    if cta_needs.get("comments", 0) > 0.08 and "comment" in allowed:
        return "лучше закончить обсуждением в комментариях", "в ленте сейчас не хватает вовлечения без прямого дожима"
    if cta_needs.get("diagnostic", 0) > 0.08 and "diagnostic" in allowed:
        return "мягко вести в @adizesbizbot", "эта тема выдерживает вход в диагностику, а диагностический слой сейчас не перегрет"
    if cta_needs.get("none", 0) > 0.08:
        return "можно оставить пост без CTA", "сейчас ленте полезно дать часть текстов без завершающего призыва"
    if cta_needs.get("personal", 0) > 0.05 and "personal" in allowed:
        return "можно редким исключением вести в личку", "личный CTA сейчас уместен только для точечного персонального разбора"

    if "comment" in allowed and topic.get("cta_need") == "optional":
        return "лучше закончить обсуждением в комментариях", "для этой темы обсуждение выглядит естественнее, чем продажный шаг"
    if "diagnostic" in allowed and topic.get("cta_need") == "soft":
        return "мягко вести в @adizesbizbot", "тема логично продолжает путь через диагностику"
    if "personal" in allowed and any(
        token in (topic.get("theme") or "").lower()
        for token in ("оргструкт", "роль", "регламент", "процесс", "эффектив", "операцион")
    ):
        return "иногда можно вести в личку", "здесь персональный разбор может быть уместнее общего CTA"
    return "можно оставить без явного CTA", "если пост получится достаточно самодостаточным, лучше не перегружать его завершающим призывом"


def build_topic_cta_mode(topic: dict, cta_balance: dict) -> str | None:
    strategy = resolve_cta_strategy(topic.get("theme") or "", topic.get("content_pillar"))
    cta_needs = cta_balance.get("needs") or {}
    allowed = set(strategy.get("allowed_ctas") or [])

    if cta_needs.get("comments", 0) > 0.08 and "comment" in allowed:
        return "comments"
    if cta_needs.get("diagnostic", 0) > 0.08 and "diagnostic" in allowed:
        return "diagnostic"
    if cta_needs.get("none", 0) > 0.08:
        return "none"
    if cta_needs.get("personal", 0) > 0.05 and "personal" in allowed:
        return "personal"

    if "comment" in allowed and topic.get("cta_need") == "optional":
        return "comments"
    if "diagnostic" in allowed and topic.get("cta_need") == "soft":
        return "diagnostic"
    if "personal" in allowed and any(
        token in (topic.get("theme") or "").lower()
        for token in ("оргструкт", "роль", "регламент", "процесс", "эффектив", "операцион")
    ):
        return "personal"
    return "none"


def format_post_improvements(text: str, theme_hint: str | None = None) -> str:
    review = critic_review(text)
    plan = plan_next_topics(user_theme=theme_hint) if theme_hint else plan_next_topics()
    recommendation = plan.get("recommended_topic_now") or {}
    pillar = classify_post_pillar(
        {
            "primary_theme": theme_hint or "",
            "title_hook": text.splitlines()[0] if text.splitlines() else "",
            "content_role": "image" if "#мысли" in text.lower() else "expert",
            "cta_present": any(token in text.lower() for token in ("@adizesbizbot", "@pda33", "диагност")),
            "hashtags": [part for part in text.split() if part.startswith("#")],
        }
    )

    option_1_title = "Усилить вход и конкретику"
    option_1_body = "Сделать первый абзац понятнее и приземлённее, быстрее показать узнаваемую ситуацию и раньше дать один конкретный пример из бизнеса."
    if review.get("editorial_feedback_note"):
        option_1_body = review["editorial_feedback_note"]

    option_2_title = "Сместить акцент в более сильный угол"
    option_2_body = "Оставить тему, но сделать вывод жёстче: меньше общих формулировок, больше ясного управленческого вывода или прикладного шага."
    if recommendation and recommendation.get("content_pillar") != pillar:
        option_2_body = (
            f"Сейчас лента просит другой следующий слой: {recommendation.get('content_pillar')}. "
            f"Можно либо переписать этот текст ближе к нему, либо взять следующей темой '{recommendation.get('theme')}'."
        )
    elif review.get("funnel_fit_note"):
        option_2_body = review["funnel_fit_note"]

    return (
        "<b>✨ 2 варианта улучшения</b>\n\n"
        f"<b>1. {html.escape(option_1_title)}</b>\n"
        f"• {html.escape(option_1_body)}\n\n"
        f"<b>2. {html.escape(option_2_title)}</b>\n"
        f"• {html.escape(option_2_body)}"
    )


def looks_like_full_post(text: str) -> bool:
    return len(text) >= 260 or text.count("\n") >= 4


def infer_local_rewrite_mode(note: str) -> str:
    lowered = note.lower().replace("ё", "е")
    if any(token in lowered for token in ("начал", "заголов", "хук", "понят", "проще", "пример", "конкрет")):
        return "improvement_1"
    if any(token in lowered for token in ("жест", "жёст", "короч", "сильн", "дожм", "вывод", "акцент")):
        return "improvement_2"
    return "improvement_1"


def build_post_improvement_options(text: str, theme_hint: str | None = None) -> list[str]:
    review = critic_review(text)
    plan = plan_next_topics(user_theme=theme_hint) if theme_hint else plan_next_topics()
    recommendation = plan.get("recommended_topic_now") or {}

    option_1 = review.get("editorial_feedback_note") or "Сделать вход проще и приземлённее: раньше дать узнаваемую ситуацию, один конкретный пример и быстрее вывести читателя в суть."
    if review.get("repeat_note"):
        option_2 = review["repeat_note"]
    elif recommendation and recommendation.get("theme"):
        option_2 = f"Сместить акцент ближе к тому, что сейчас просит лента: либо усилить текущий угол, либо развернуть мысль в сторону темы '{recommendation.get('theme')}'."
    else:
        option_2 = "Сделать вывод жёстче и прикладнее: меньше общих формулировок, больше одного ясного управленческого вывода."
    return [option_1, option_2]


def build_topic_preview(topic: dict) -> str:
    theme = (topic.get("theme") or "").lower()
    angle = topic.get("angle") or ""
    content_role = topic.get("content_role") or "expert"

    if "стад" in theme or "кризис" in theme:
        return "В посте разберём одну типичную ошибку собственника на конкретной стадии бизнеса, покажем, почему она возникает именно сейчас, к каким потерям приводит и какой управленческий фокус стоит поставить первым."
    if "оргструкт" in theme or "роль" in theme:
        return "Пост покажет живую ситуацию, где команда вроде бы работает, но всё равно упирается в владельца. Дальше развернём мысль через роли, ответственность, границы решений и последствия для управляемости бизнеса."
    if "причин" in theme or "симптом" in theme:
        return "Это будет пост про разницу между симптомом и причиной: что собственники обычно пытаются чинить в лоб, почему это не даёт устойчивого эффекта и где на самом деле ломается сама модель управления."
    if "потер" in theme or "операцион" in theme or "издерж" in theme:
        return "В посте разберём, где бизнес теряет деньги и время внутри процессов, хотя это не видно в прямых статьях расходов. Покажем конкретные зоны утечки и как они превращаются в системные финансовые потери."
    if "регламент" in theme or "процесс" in theme:
        return "Пост объяснит, почему процессы и регламенты сами по себе не создают порядок. Разберём, как связать процесс с владельцем, результатом, контролем и зачем без этого даже хорошие инструкции не работают."
    if contains_ai_signal(theme):
        return "Тема будет раскрыта не как разговор про инструмент ради инструмента, а через систему: какая управленческая конструкция должна быть собрана заранее, где ИИ реально даёт пользу и где без неё только усиливает хаос."
    if content_role == "applied":
        return "Это будет прикладной пост: начнём с конкретной рабочей ситуации, затем покажем системную причину проблемы и доведём до одного практического вывода, который собственник сможет примерить на свой бизнес."
    if content_role == "diagnostic":
        return "Это будет диагностический пост: сначала подсветим саму проблему, затем разложим её источник на уровне системы управления и покажем, куда собственнику стоит смотреть, чтобы не лечить только внешние симптомы."
    if angle:
        return f"Пост раскроет тему через такой фокус: {angle}. Сначала дадим понятную сцену или наблюдение из бизнеса, затем развернём системную причину и соберём это в один практический вывод без перегруза."
    return "Будет экспертный пост с одной центральной мыслью: сначала покажем понятную для собственника ситуацию, затем раскроем системную причину происходящего и подведём к ясному практическому выводу."


def format_five_topics(session: dict, exclude_history: bool = False) -> tuple[str, list[dict]]:
    exclude_topics = []
    if exclude_history:
        exclude_topics.extend(session.get("suggested_topics_history", []))
        exclude_topics.extend(session.get("generated_themes_history", []))
    plan = plan_next_topics(exclude_topics=exclude_topics)
    topics = sorted(plan.get("best_next_topics", [])[:5], key=lambda item: item.get("score", 0), reverse=True)
    cta_balance = plan.get("cta_balance") or {}
    percent_map = build_topic_percent_map(topics)
    lines = ["<b>✨ Пять уместных тем на сейчас:</b>"]
    for idx, topic in enumerate(topics, start=1):
        positive, caution = build_topic_fit_comment(topic)
        cta_label, cta_reason = build_topic_cta_hint(topic, cta_balance)
        topic["preferred_cta_mode"] = build_topic_cta_mode(topic, cta_balance)
        lines.append(f"<b>{idx}. {html.escape(topic.get('theme') or '')}</b>")
        lines.append(f"📈 <b>Насколько подходит сейчас:</b> {percent_map.get(topic.get('theme') or '', 72)}%")
        lines.append(f"✅ <b>Почему подходит:</b> {html.escape(positive)}")
        if caution:
            lines.append(f"⚠️ <i>Но:</i> {html.escape(caution)}")
        lines.append(f"🧩 <b>Что будет в посте:</b> {html.escape(build_topic_preview(topic))}")
        lines.append(f"🏷 <b>Рубрика:</b> {html.escape(RUBRIC_LABELS.get(topic.get('marketing_rubric'), topic.get('marketing_rubric') or 'Не определена'))}")
        lines.append(f"🪜 <b>Стадия воронки:</b> {html.escape(topic.get('funnel_stage') or 'Не определена')}")
        lines.append(f"🎯 <b>Угол:</b> {html.escape(topic.get('angle') or '')}")
        lines.append(f"🧲 <b>CTA:</b> {html.escape(cta_label)}")
        lines.append(f"💬 <b>Почему по CTA:</b> {html.escape(cta_reason)}")
        lines.append(f"🕒 <b>Почему сейчас:</b> {html.escape(topic.get('why_now') or '')}")
        lines.append("")
    return "\n".join(lines).strip(), topics


def extend_unique_history(session: dict, field: str, values: list[str], limit: int) -> None:
    session.setdefault(field, [])
    existing = session[field]
    for value in values:
        if value and value not in existing:
            existing.append(value)
    session[field] = existing[-limit:]


def format_theme_verdict(theme: str) -> str:
    plan = plan_next_topics(user_theme=theme, business_goal="expert")
    verdict = plan.get("user_theme_verdict", {})
    return (
        f"<b>🧭 Оценка темы</b>\n"
        f"<blockquote>{html.escape(theme)}</blockquote>\n"
        f"<b>Вердикт:</b> {html.escape(verdict.get('status', 'none'))}\n"
        f"<b>Риск повтора:</b> {html.escape(verdict.get('repeat_risk', 'unknown'))}\n"
        f"<b>Угол:</b> {html.escape(verdict.get('recommended_angle') or 'не указан')}\n"
        f"<b>Комментарий:</b> {html.escape(verdict.get('comment') or 'без комментария')}"
    )


def format_backlog_topics() -> tuple[str, list[dict]]:
    topics = get_backlog_topics(limit=5)
    if not topics:
        return "<b>📚 В backlog пока нет сохранённых тем.</b>", []
    pillar_labels = {
        "conversational": "разговорная",
        "expert": "экспертная",
        "money": "денежная",
    }
    lines = ["<b>📚 Ваши сохранённые темы:</b>"]
    for idx, item in enumerate(topics, start=1):
        status = item.get("status") or "saved"
        status_text = "использована" if status == "used" else "сохранена"
        pillar = pillar_labels.get(item.get("desired_pillar"))
        source_kind = ((item.get("context") or {}).get("source_kind") if isinstance(item.get("context"), dict) else None) or item.get("source")
        kind_label = "кейс" if source_kind in {"verified_case", "case_research"} else None
        prefix = "🌐 " if kind_label else ""
        parts = [part for part in (kind_label, pillar) if part]
        suffix = f" · {' · '.join(parts)}" if parts else ""
        lines.append(f"{idx}. {prefix}{html.escape(item.get('theme') or '')} <i>({status_text}{suffix})</i>")
        notes = (item.get("notes") or "").strip()
        if notes and item.get("source") == "case_research":
            preview = notes.splitlines()[0][:180].rstrip()
            lines.append(f"<i>   {html.escape(preview)}</i>")
    lines.append("")
    lines.append("Нажмите номер темы, и я сразу соберу по ней пост")
    lines.append("<i>Или выберите действие ниже: отметить использованной / удалить</i>")
    return "\n".join(lines), topics


def format_case_research(result: dict) -> tuple[str, list[dict]]:
    if not result.get("available"):
        reason = result.get("reason")
        if reason == "llm_unavailable":
            related_queries = result.get("related_queries") or []
            lines = [
                "<b>🌐 Режим кейс-ресерча сейчас недоступен.</b>",
                "",
                "Для него нужен hybrid LLM-режим с включённым интернет-поиском через OpenAI.",
            ]
            if related_queries:
                lines.extend(
                    [
                        "",
                        "<b>🧭 Пока можно взять один из смежных запросов на потом:</b>",
                    ]
                )
                for idx, item in enumerate(related_queries[:5], start=1):
                    lines.append(f"{idx}. {html.escape(item)}")
            return (
                "\n".join(lines),
                [],
            )
        return ("<b>🌐 Не вижу запроса для поиска кейсов.</b>", [])

    cases = result.get("cases") or []
    if not cases:
        related_queries = result.get("related_queries") or []
        lines = [
            "<b>🌐 Не нашёл достаточно сильных кейсов под этот запрос.</b>",
            "",
            "Я отфильтровал истории без явной системной пересборки, сокращения потерь, автоматизации, контроля или операционного эффекта.",
        ]
        if related_queries:
            lines.extend(
                [
                    "",
                    "<b>🧭 Зато вот 5 смежных направлений, куда логично копнуть дальше:</b>",
                ]
            )
            for idx, item in enumerate(related_queries, start=1):
                lines.append(f"{idx}. {html.escape(item)}")
            lines.extend(
                [
                    "",
                    "<i>Можно просто нажать 🌐 Найти кейсы ещё раз и отправить один из этих запросов.</i>",
                ]
            )
        return (
            "\n".join(lines),
            [],
        )

    lines = [
        f"<b>🌐 Нашёл кейсы по запросу:</b> {html.escape(result.get('query') or '')}",
        "<i>Показываю только те истории, где есть явная системная польза и более-менее внятный факт-чек</i>",
        "",
    ]
    attempted_queries = result.get("attempted_queries") or []
    if result.get("expanded_search") and len(attempted_queries) > 1:
        lines.extend(
            [
                f"<i>По точной формулировке выдача была слабой, поэтому я расширил поиск через смежные запросы: {html.escape(', '.join(attempted_queries[1:3]))}</i>",
                "",
            ]
        )
    topic_suggestions = result.get("topic_suggestions") or []
    if topic_suggestions:
        topic_count = min(len(topic_suggestions), 5)
        title = "Пять тем" if topic_count == 5 else f"{topic_count} темы" if topic_count in {2, 3, 4} else "1 тема"
        lines.append(f"<b>🧠 {title.capitalize()}, которые можно сделать из этой подборки:</b>")
        for idx, item in enumerate(topic_suggestions[:5], start=1):
            lines.append(f"• <b>{idx}. {html.escape(item.get('theme') or '')}</b>")
            lines.append(f"  🧭 Полезна для темы: {html.escape(item.get('useful_topic') or '')}")
            lines.append(f"  🎯 Угол: {html.escape(item.get('angle') or '')}")
            lines.append(f"  ✅ Почему брать: {html.escape(item.get('why_now') or '')}")
        lines.append("")

    for idx, item in enumerate(cases, start=1):
        lines.append(f"<b>{idx}. {html.escape(item.get('case_title') or '')}</b>")
        if item.get("company") or item.get("timeframe"):
            meta = " · ".join(part for part in (item.get("company"), item.get("timeframe")) if part)
            lines.append(f"🏢 <b>Контекст:</b> {html.escape(meta)}")
        lines.append(f"📈 <b>Насколько в теме:</b> {int(item.get('score') or 0)}%")
        lines.append(f"✅ <b>Почему подходит:</b> {html.escape(item.get('why_fit') or '')}")
        if item.get("what_broke"):
            lines.append(f"⚠️ <b>Что было не так:</b> {html.escape(item.get('what_broke') or '')}")
        if item.get("system_changes"):
            lines.append(f"⚙️ <b>Что именно пересобрали:</b> {html.escape('; '.join(item.get('system_changes') or []))}")
        if item.get("measurable_outcomes"):
            lines.append(f"💸 <b>Какой был эффект:</b> {html.escape('; '.join(item.get('measurable_outcomes') or []))}")
        if item.get("useful_topic"):
            lines.append(f"🧭 <b>Полезен для темы:</b> {html.escape(item.get('useful_topic') or '')}")
        lines.append(f"🎯 <b>Тема поста:</b> {html.escape(item.get('post_theme') or '')}")
        lines.append(f"🪝 <b>Угол:</b> {html.escape(item.get('post_angle') or '')}")
        if item.get("caution"):
            lines.append(f"⚠️ <i>Но:</i> {html.escape(item.get('caution') or '')}")
        if item.get("sources"):
            source_links = []
            for source in item.get("sources") or []:
                title = html.escape(source.get("title") or source.get("url") or "")
                url = html.escape(source.get("url") or "", quote=True)
                source_links.append(f'<a href="{url}">{title}</a>')
            if source_links:
                lines.append(f"🔎 <b>Источники:</b> {'; '.join(source_links)}")
        lines.append("")
    lines.append("Нажмите номер кейса, и я соберу по нему пост")
    return "\n".join(lines).strip(), cases


def format_case_verification(result: dict) -> str:
    if not result.get("available"):
        reason = result.get("reason")
        if reason == "llm_unavailable":
            return (
                "<b>🔎 Проверка кейса сейчас недоступна.</b>\n\n"
                "Для неё нужен hybrid LLM-режим с включённым интернет-поиском через OpenAI."
            )
        return "<b>🔎 Не вижу названия кейса для проверки.</b>"

    verdict = result.get("verdict")
    if not verdict:
        return (
            f"<b>🔎 Не смог уверенно проверить кейс:</b> {html.escape(result.get('query') or '')}\n\n"
            "Либо в источниках слишком мало внятной фактологии, либо кейс оказался слабым именно под вашу тему канала."
        )

    verdict_label = {
        "take": "брать",
        "caution": "можно брать, но осторожно",
        "skip": "лучше не брать",
    }.get(verdict.get("fit_verdict"), verdict.get("fit_verdict") or "без вердикта")

    lines = [
        f"<b>🔎 Проверка кейса:</b> {html.escape(result.get('query') or '')}",
        f"📈 <b>Насколько подходит:</b> {int(verdict.get('score') or 0)}%",
        f"🎯 <b>Вердикт:</b> {html.escape(verdict_label)}",
        f"✅ <b>Почему:</b> {html.escape(verdict.get('fit_reason') or '')}",
    ]
    confirmed = verdict.get("what_is_confirmed") or []
    if confirmed:
        lines.append(f"📌 <b>Что подтверждается:</b> {html.escape('; '.join(confirmed))}")
    changes = verdict.get("system_changes") or []
    if changes:
        lines.append(f"⚙️ <b>Какие были системные изменения:</b> {html.escape('; '.join(changes))}")
    outcomes = verdict.get("measurable_outcomes") or []
    if outcomes:
        lines.append(f"💸 <b>Какой был эффект:</b> {html.escape('; '.join(outcomes))}")
    unclear = verdict.get("what_is_unclear_or_weak") or []
    if unclear:
        lines.append(f"⚠️ <i>Что спорно или слабее подтверждено:</i> {html.escape('; '.join(unclear))}")
    if verdict.get("post_theme"):
        lines.append(f"🧩 <b>Тема поста:</b> {html.escape(verdict.get('post_theme') or '')}")
    if verdict.get("post_angle"):
        lines.append(f"🪝 <b>Угол:</b> {html.escape(verdict.get('post_angle') or '')}")
    sources = verdict.get("sources") or []
    if sources:
        source_links = []
        for source in sources:
            title = html.escape(source.get("title") or source.get("url") or "")
            url = html.escape(source.get("url") or "", quote=True)
            source_links.append(f'<a href="{url}">{title}</a>')
        lines.append(f"🔎 <b>Источники:</b> {'; '.join(source_links)}")
    if verdict.get("fit_verdict") in {"take", "caution"} and verdict.get("post_theme"):
        lines.append("")
        lines.append("Можно сразу собрать пост по этому углу или сохранить кейс в ваши темы на потом")
    return "\n".join(lines)


def handle_waiting_mode(chat_id: int | str, user_id: int | None, text: str, session: dict) -> bool:
    mode = session.get("mode")
    if mode == "await_eval_theme":
        session["mode"] = None
        save_session(chat_id, user_id, session)
        send_rich_chunks(chat_id, format_theme_verdict(text), reply_markup=build_main_menu_keyboard())
        return True

    if mode == "await_save_topics":
        added = add_themes_to_backlog(text)
        session["mode"] = None
        save_session(chat_id, user_id, session)
        send_rich_chunks(chat_id, format_backlog_save_confirmation(added), reply_markup=build_main_menu_keyboard())
        return True

    if mode == "await_rewrite_source":
        rewrite_result = rewrite_post_in_author_style(text)
        session["mode"] = None
        session["last_generated"] = {
            "theme": rewrite_result["source_theme"],
            "final_text": rewrite_result["final_text"],
            "rewrite_source": text,
        }
        save_session(chat_id, user_id, session)
        response = (
            "♻️ Рерайт в вашем стиле:\n\n"
            f"{rewrite_result['final_text']}\n\n"
            f"Исходная тема: {rewrite_result['source_theme']}\n"
            f"Риск повтора: {rewrite_result['critic_review']['repeat_risk']}"
        )
        send_chunks(chat_id, response, reply_markup=build_post_actions_keyboard())
        return True

    if mode == "await_post_analysis":
        session["last_analyzed_post"] = {
            "text": text,
            "theme": None,
            "goal": None,
            "preferred_cta_mode": None,
            "case_context": None,
            "topic_brief": None,
        }
        session["mode"] = None
        save_session(chat_id, user_id, session)
        send_rich_chunks(chat_id, format_post_analytics(text), reply_markup=build_main_menu_keyboard())
        return True

    if mode == "await_case_research_query":
        LOGGER.info("Telegram case flow: incoming research query chat_id=%s text=%r", chat_id, text[:160])
        send_chunks(chat_id, "🌐 Ищу реальные кейсы и быстро отфильтровываю слабые истории. Это может занять до минуты.")
        research_result = research_case_topics(text)
        session["mode"] = None
        session["last_case_query"] = text
        text_payload, cases = format_case_research(research_result)
        topic_suggestions = research_result.get("topic_suggestions") or []
        if cases:
            session["mode"] = "await_case_pick"
            session["initial_case_suggestions"] = cases
            session["last_case_suggestions"] = cases
            session["suggested_case_history"] = collect_case_signatures(cases)
            session["initial_case_topic_suggestions"] = topic_suggestions
            session["last_case_topic_suggestions"] = topic_suggestions
        save_session(chat_id, user_id, session)
        reply_markup = build_case_pick_keyboard(len(cases)) if cases else build_main_menu_keyboard()
        LOGGER.info(
            "Telegram case flow: formatted result chat_id=%s reason=%s cases=%s topic_suggestions=%s",
            chat_id,
            research_result.get("reason"),
            len(cases),
            len(topic_suggestions),
        )
        send_rich_chunks(chat_id, text_payload, reply_markup=reply_markup)
        if topic_suggestions:
            send_rich_chunks(
                chat_id,
                html_join(
                    html_block("🧠 Можно выбрать не только кейс, но и готовую тему поста из этой подборки"),
                    "Нажмите кнопку ниже, и я соберу пост сразу по тематическому углу, а не только по компании.",
                ),
                reply_markup=build_case_topic_suggestion_keyboard(len(topic_suggestions)),
            )
        return True

    if mode == "await_case_check_query":
        verification = verify_case(text)
        session["mode"] = None
        verdict = verification.get("verdict")
        if verdict and verdict.get("fit_verdict") in {"take", "caution"} and verdict.get("post_theme"):
            session["last_verified_case"] = verification
        save_session(chat_id, user_id, session)
        reply_markup = build_verified_case_keyboard() if verdict and verdict.get("fit_verdict") in {"take", "caution"} and verdict.get("post_theme") else build_main_menu_keyboard()
        send_rich_chunks(chat_id, format_case_verification(verification), reply_markup=reply_markup)
        return True

    if mode == "await_post_rule_note":
        note_result = build_note_command_result(note=text)
        session["mode"] = None
        save_session(chat_id, user_id, session)
        send_chunks(chat_id, f"🧠 Сохранил как правило.\n\n{format_note_command_response(note_result)}", reply_markup=build_main_menu_keyboard())
        return True

    if mode == "await_post_theme":
        goal = session.get("post_goal") or "expert"
        result = build_post_command_result(theme=text, goal=goal)
        session["mode"] = None
        session.setdefault("generated_themes_history", [])
        if text not in session["generated_themes_history"]:
            session["generated_themes_history"].append(text)
            session["generated_themes_history"] = session["generated_themes_history"][-12:]
        session["last_generated"] = {
            "theme": text,
            "goal": goal,
            "final_text": result.payload["final_text"],
            "chosen_variant": result.payload.get("chosen_variant"),
            "variants_tried": [result.payload.get("chosen_variant")],
            "preferred_cta_mode": result.payload.get("preferred_cta_mode"),
            "case_context": result.payload.get("case_context"),
            "topic_brief": result.payload.get("topic_brief"),
        }
        save_session(chat_id, user_id, session)
        send_rich_chunks(chat_id, format_post_command_response(result), reply_markup=build_post_actions_keyboard())
        return True

    if mode == "await_post_revision":
        last_generated = session.get("last_generated") or {}
        theme = last_generated.get("theme")
        source_text = last_generated.get("final_text")
        goal = last_generated.get("goal") or session.get("post_goal") or "expert"
        preferred_cta_mode = last_generated.get("preferred_cta_mode")
        case_context = last_generated.get("case_context")
        topic_brief = last_generated.get("topic_brief")
        if not source_text:
            session["mode"] = None
            save_session(chat_id, user_id, session)
            send_chunks(chat_id, "Не вижу последнего черновика в рабочей памяти. Лучше заново выбрать тему.", reply_markup=build_main_menu_keyboard())
            return True
        session["mode"] = None

        if looks_like_full_post(text):
            polished_payload = polish_text(text)
            final_text = polished_payload["polished_text"]
            session["last_generated"] = {
                "theme": theme,
                "goal": goal,
                "final_text": final_text,
                "last_revision_source": "user_full_text",
                "chosen_variant": None,
                "variants_tried": [],
                "preferred_cta_mode": preferred_cta_mode,
                "case_context": case_context,
                "topic_brief": topic_brief,
            }
            session["last_analyzed_post"] = {
                "text": final_text,
                "theme": theme,
                "goal": goal,
                "preferred_cta_mode": preferred_cta_mode,
                "case_context": case_context,
                "topic_brief": topic_brief,
            }
            save_session(chat_id, user_id, session)
            send_rich_chunks(
                chat_id,
                html_join(
                    html_block("✏️ Взял вашу версию и аккуратно доточил её"),
                    format_post_for_telegram_html(final_text),
                ),
                reply_markup=build_post_actions_keyboard(),
            )
            return True

        rewrite_result = rewrite_post_by_improvement(
            source_text,
            improvement_mode=infer_local_rewrite_mode(text),
            theme_hint=theme,
            business_goal=goal,
            topic_brief=topic_brief,
            preferred_cta_mode=preferred_cta_mode,
            case_context=case_context,
        )
        final_text = rewrite_result["final_text"]
        session["last_generated"] = {
            "theme": theme,
            "goal": goal,
            "final_text": final_text,
            "last_revision_note": text,
            "chosen_variant": None,
            "variants_tried": [],
            "preferred_cta_mode": preferred_cta_mode,
            "case_context": case_context,
            "topic_brief": rewrite_result.get("topic_brief") or topic_brief,
        }
        session["last_analyzed_post"] = {
            "text": final_text,
            "theme": theme,
            "goal": goal,
            "preferred_cta_mode": preferred_cta_mode,
            "case_context": case_context,
            "topic_brief": rewrite_result.get("topic_brief") or topic_brief,
        }
        save_session(chat_id, user_id, session)
        send_rich_chunks(
            chat_id,
            html_join(
                html_block("✏️ Доработал текущий пост по вашей правке, но не записывал её в долговременную память"),
                format_post_for_telegram_html(final_text),
            ),
            reply_markup=build_post_actions_keyboard(),
        )
        return True

    return False


def handle_topic_pick(chat_id: int | str, user_id: int | None, text: str, session: dict) -> bool:
    if not text.isdigit():
        return False
    suggestions = session.get("last_topic_suggestions") or []
    index = int(text) - 1
    if index >= len(suggestions):
        send_chunks(chat_id, "Не вижу такой темы в последней пятёрке. Лучше заново запросить темы.", reply_markup=build_main_menu_keyboard())
        return True
    selected = suggestions[index]
    theme = selected.get("theme")
    goal = selected.get("content_pillar") or "expert"
    preferred_cta_mode = selected.get("preferred_cta_mode")
    result = build_post_command_result(
        theme=theme,
        goal=goal,
        preferred_cta_mode=preferred_cta_mode,
        angle=selected.get("angle"),
        topic_brief=selected,
    )
    session["mode"] = None
    session.setdefault("generated_themes_history", [])
    if theme and theme not in session["generated_themes_history"]:
        session["generated_themes_history"].append(theme)
        session["generated_themes_history"] = session["generated_themes_history"][-12:]
    session["last_generated"] = {
        "theme": theme,
        "goal": goal,
        "final_text": result.payload["final_text"],
        "chosen_variant": result.payload.get("chosen_variant"),
        "variants_tried": [result.payload.get("chosen_variant")],
        "preferred_cta_mode": result.payload.get("preferred_cta_mode"),
        "case_context": result.payload.get("case_context"),
        "topic_brief": result.payload.get("topic_brief") or selected,
    }
    save_session(chat_id, user_id, session)
    send_rich_chunks(
        chat_id,
        html_join(
            html_block(f"✍️ Беру тему {text}"),
            format_post_command_response(result),
        ),
        reply_markup=build_post_actions_keyboard(),
    )
    return True


def can_fallback_to_last_topic_pick(session: dict, text: str) -> bool:
    if not text.isdigit():
        return False
    suggestions = session.get("last_topic_suggestions") or []
    if not suggestions:
        return False
    index = int(text) - 1
    return 0 <= index < len(suggestions)


def handle_case_pick(chat_id: int | str, user_id: int | None, text: str, session: dict) -> bool:
    if not text.isdigit():
        return False
    suggestions = session.get("last_case_suggestions") or []
    index = int(text) - 1
    if index >= len(suggestions):
        send_chunks(chat_id, "Не вижу такой кейс в последней подборке. Лучше заново запустить поиск кейсов.", reply_markup=build_main_menu_keyboard())
        return True
    selected = suggestions[index]
    theme = selected.get("post_theme")
    goal = selected.get("content_pillar") or "expert"
    preferred_cta_mode = selected.get("preferred_cta_mode")
    case_context = {
        "source_kind": "verified_case",
        "case_query": selected.get("case_title") or selected.get("company"),
        "fit_reason": selected.get("why_fit"),
        "post_angle": selected.get("post_angle"),
        "what_is_confirmed": selected.get("what_is_confirmed"),
        "system_changes": selected.get("system_changes"),
        "measurable_outcomes": selected.get("measurable_outcomes"),
        "sources": selected.get("sources"),
        "content_pillar": selected.get("content_pillar"),
    }
    result = build_post_command_result(
        theme=theme,
        goal=goal,
        preferred_cta_mode=preferred_cta_mode,
        angle=selected.get("post_angle"),
        case_context=case_context,
    )
    session["mode"] = None
    extend_unique_history(session, "generated_themes_history", [theme], 12)
    session["last_generated"] = {
        "theme": theme,
        "goal": goal,
        "final_text": result.payload["final_text"],
        "chosen_variant": result.payload.get("chosen_variant"),
        "variants_tried": [result.payload.get("chosen_variant")],
        "preferred_cta_mode": result.payload.get("preferred_cta_mode"),
        "case_context": case_context,
    }
    save_session(chat_id, user_id, session)
    send_rich_chunks(
        chat_id,
        html_join(
            html_block(f"🌐 Беру кейс {text}"),
            f"<i>{html.escape(selected.get('case_title') or '')}</i>",
            format_post_command_response(result),
        ),
        reply_markup=build_post_actions_keyboard(),
    )
    return True


def can_fallback_to_last_case_pick(session: dict, text: str) -> bool:
    if not text.isdigit():
        return False
    suggestions = session.get("last_case_suggestions") or []
    if not suggestions:
        return False
    index = int(text) - 1
    return 0 <= index < len(suggestions)


def collect_case_signatures(cases: list[dict]) -> list[str]:
    signatures: list[str] = []
    for item in cases:
        company = str(item.get("company") or "").strip().lower()
        title = str(item.get("case_title") or "").strip().lower()
        signature = " | ".join(part for part in (company, title) if part)
        if signature and signature not in signatures:
            signatures.append(signature)
    return signatures


def restore_topic_suggestions(session: dict) -> tuple[str, list[dict]]:
    topics = session.get("last_topic_suggestions") or []
    if not topics:
        return "Не вижу сохранённых тем. Сначала запросите новую пятёрку.", []
    lines = ["<b>✨ Пять уместных тем на сейчас:</b>"]
    cta_balance = plan_next_topics().get("cta_balance") or {}
    percent_map = build_topic_percent_map(topics)
    for idx, topic in enumerate(topics, start=1):
        positive, caution = build_topic_fit_comment(topic)
        cta_label, cta_reason = build_topic_cta_hint(topic, cta_balance)
        lines.append(f"<b>{idx}. {html.escape(topic.get('theme') or '')}</b>")
        lines.append(f"📈 <b>Насколько подходит сейчас:</b> {percent_map.get(topic.get('theme') or '', 72)}%")
        lines.append(f"✅ <b>Почему подходит:</b> {html.escape(positive)}")
        if caution:
            lines.append(f"⚠️ <i>Но:</i> {html.escape(caution)}")
        lines.append(f"🧩 <b>Что будет в посте:</b> {html.escape(build_topic_preview(topic))}")
        lines.append(f"🏷 <b>Рубрика:</b> {html.escape(RUBRIC_LABELS.get(topic.get('marketing_rubric'), topic.get('marketing_rubric') or 'Не определена'))}")
        lines.append(f"🪜 <b>Стадия воронки:</b> {html.escape(topic.get('funnel_stage') or 'Не определена')}")
        lines.append(f"🎯 <b>Угол:</b> {html.escape(topic.get('angle') or '')}")
        lines.append(f"🧲 <b>CTA:</b> {html.escape(cta_label)}")
        lines.append(f"💬 <b>Почему по CTA:</b> {html.escape(cta_reason)}")
        lines.append(f"🕒 <b>Почему сейчас:</b> {html.escape(topic.get('why_now') or '')}")
        lines.append("")
    return "\n".join(lines).strip(), topics


def restore_case_suggestions(session: dict) -> tuple[str, list[dict]]:
    cases = session.get("last_case_suggestions") or []
    query = session.get("last_case_query") or "ваш запрос"
    return format_case_research(
        {
            "available": True,
            "query": query,
            "cases": cases,
            "reason": "ok" if cases else "no_cases",
        }
    )


def build_case_topic_context(item: dict) -> dict:
    return {
        "source_kind": "case_research",
        "case_query": item.get("case_title") or item.get("company"),
        "fit_reason": item.get("why_now") or item.get("why_fit"),
        "post_angle": item.get("angle") or item.get("post_angle"),
        "what_is_confirmed": item.get("what_is_confirmed"),
        "system_changes": item.get("system_changes"),
        "measurable_outcomes": item.get("measurable_outcomes"),
        "sources": item.get("sources"),
        "content_pillar": item.get("content_pillar"),
    }


def build_generated_backlog_payload(last_generated: dict) -> tuple[str | None, str | None, str, dict]:
    theme = (last_generated.get("theme") or "").strip()
    if not theme:
        return None, None, "", {}

    goal = (last_generated.get("goal") or "expert").strip() or "expert"
    topic_brief = last_generated.get("topic_brief") or {}
    case_context = last_generated.get("case_context") or {}
    final_text = (last_generated.get("final_text") or "").strip()

    source_kind = (
        case_context.get("source_kind")
        or topic_brief.get("source_kind")
        or ("case_research" if case_context or topic_brief.get("sources") else "user")
    )

    context: dict = {}
    if isinstance(case_context, dict):
        context.update(case_context)
    if isinstance(topic_brief, dict):
        if topic_brief.get("angle") and not context.get("post_angle"):
            context["post_angle"] = topic_brief.get("angle")
        if topic_brief.get("why_now") and not context.get("fit_reason"):
            context["fit_reason"] = topic_brief.get("why_now")
        if topic_brief.get("what_is_confirmed") and not context.get("what_is_confirmed"):
            context["what_is_confirmed"] = topic_brief.get("what_is_confirmed")
        if topic_brief.get("system_changes") and not context.get("system_changes"):
            context["system_changes"] = topic_brief.get("system_changes")
        if topic_brief.get("measurable_outcomes") and not context.get("measurable_outcomes"):
            context["measurable_outcomes"] = topic_brief.get("measurable_outcomes")
        if topic_brief.get("sources") and not context.get("sources"):
            context["sources"] = topic_brief.get("sources")
        if topic_brief.get("content_pillar") and not context.get("content_pillar"):
            context["content_pillar"] = topic_brief.get("content_pillar")
        if topic_brief.get("case_title") and not context.get("case_query"):
            context["case_query"] = topic_brief.get("case_title")
    if source_kind:
        context["source_kind"] = source_kind
    if final_text:
        context["draft_snapshot"] = final_text

    notes_parts: list[str] = []
    angle = context.get("post_angle")
    fit_reason = context.get("fit_reason")
    outcomes = context.get("measurable_outcomes") or []
    if angle:
        notes_parts.append(f"Угол: {angle}")
    if fit_reason:
        notes_parts.append(f"Почему брать: {fit_reason}")
    if outcomes:
        notes_parts.append(f"Эффект: {'; '.join(str(item) for item in outcomes[:3])}")
    if final_text:
        preview = final_text.splitlines()[0][:220].rstrip()
        if preview:
            notes_parts.append(f"Черновик: {preview}")

    source = "case_research" if source_kind in {"case_research", "verified_case"} else "user"
    return theme, goal, "\n".join(notes_parts), context


def handle_backlog_pick(chat_id: int | str, user_id: int | None, text: str, session: dict) -> bool:
    if not text.isdigit():
        return False
    suggestions = session.get("last_backlog_topics") or []
    index = int(text) - 1
    if index >= len(suggestions):
        send_chunks(chat_id, "Не вижу такой темы в сохранённом списке. Лучше заново открыть backlog.", reply_markup=build_main_menu_keyboard())
        return True
    selected = suggestions[index]
    theme = selected.get("theme")
    context = selected.get("context") or {}
    preferred_cta_mode = None
    if context.get("source_kind") == "verified_case":
        preferred_cta_mode = "diagnostic"
    result = build_post_command_result(
        theme=theme,
        goal=selected.get("desired_pillar") or "expert",
        preferred_cta_mode=preferred_cta_mode,
        angle=context.get("post_angle"),
        case_context=context if context.get("source_kind") == "verified_case" else None,
    )
    session["mode"] = None
    extend_unique_history(session, "generated_themes_history", [theme], 12)
    session["last_generated"] = {
        "theme": theme,
        "goal": selected.get("desired_pillar") or "expert",
        "final_text": result.payload["final_text"],
        "chosen_variant": result.payload.get("chosen_variant"),
        "variants_tried": [result.payload.get("chosen_variant")],
        "preferred_cta_mode": result.payload.get("preferred_cta_mode"),
        "case_context": result.payload.get("case_context") or (context if context.get("source_kind") == "verified_case" else None),
        "topic_brief": result.payload.get("topic_brief"),
    }
    save_session(chat_id, user_id, session)
    send_rich_chunks(
        chat_id,
        html_join(
            html_block(f"📚 Беру тему из backlog: {text}"),
            format_post_command_response(result),
        ),
        reply_markup=build_post_actions_keyboard(),
    )
    return True


def can_fallback_to_last_backlog_pick(session: dict, text: str) -> bool:
    if not text.isdigit():
        return False
    suggestions = session.get("last_backlog_topics") or []
    if not suggestions:
        return False
    index = int(text) - 1
    return 0 <= index < len(suggestions)


def handle_backlog_manage(chat_id: int | str, user_id: int | None, text: str, session: dict) -> bool:
    if not text.isdigit():
        return False
    suggestions = session.get("last_backlog_topics") or []
    index = int(text) - 1
    if index >= len(suggestions):
        send_chunks(chat_id, "Не вижу такой темы в backlog. Лучше заново открыть список.", reply_markup=build_main_menu_keyboard())
        return True
    selected = suggestions[index]
    theme = selected.get("theme")
    mode = session.get("mode")

    if mode == "await_backlog_mark_used":
        changed = mark_backlog_theme_used(theme)
        session["mode"] = None
        save_session(chat_id, user_id, session)
        if changed:
            send_chunks(chat_id, f"✅ Тема отмечена использованной:\n{theme}", reply_markup=build_main_menu_keyboard())
        else:
            send_chunks(chat_id, f"Тему не удалось отметить использованной:\n{theme}", reply_markup=build_main_menu_keyboard())
        return True

    if mode == "await_backlog_delete":
        deleted = delete_backlog_theme(theme)
        session["mode"] = None
        save_session(chat_id, user_id, session)
        if deleted:
            send_chunks(chat_id, f"🗑️ Тема удалена из backlog:\n{theme}", reply_markup=build_main_menu_keyboard())
        else:
            send_chunks(chat_id, f"Не удалось удалить тему:\n{theme}", reply_markup=build_main_menu_keyboard())
        return True

    return False


def route_callback_query(update: dict) -> bool:
    callback_query = update.get("callback_query")
    if not callback_query:
        return False

    message = callback_query.get("message") or {}
    chat_id = (message.get("chat") or {}).get("id")
    from_user = callback_query.get("from") or {}
    user_id = from_user.get("id")
    allowed_user_ids = get_allowed_user_ids()
    if allowed_user_ids and user_id not in allowed_user_ids:
        answer_callback_query(callback_query["id"], "Недоступно")
        return True

    session = get_session(chat_id, user_id)
    data = callback_query.get("data")

    if data == CALLBACK_REVISE:
        session["mode"] = "await_post_revision"
        save_session(chat_id, user_id, session)
        answer_callback_query(callback_query["id"], "Жду правку")
        send_chunks(chat_id, "✏️ Пришлите либо короткую правку для текущего поста, либо свою отредактированную версию целиком. Это доработает только текущий пост и не попадёт в долговременную память.", reply_markup=build_main_menu_keyboard())
        return True

    if data == CALLBACK_BUILD_VERIFIED_CASE_POST:
        verified = session.get("last_verified_case") or {}
        verdict = verified.get("verdict") or {}
        theme = verdict.get("post_theme")
        if not theme:
            answer_callback_query(callback_query["id"], "Нет кейса")
            send_chunks(chat_id, "Не вижу последнего подтверждённого кейса. Сначала проверьте кейс через 🔎 Проверить кейс.", reply_markup=build_main_menu_keyboard())
            return True
        goal = verdict.get("content_pillar") or "expert"
        preferred_cta_mode = verdict.get("preferred_cta_mode")
        case_context = {
            "source_kind": "verified_case",
            "case_query": verified.get("query"),
            "fit_reason": verdict.get("fit_reason"),
            "post_angle": verdict.get("post_angle"),
            "what_is_confirmed": verdict.get("what_is_confirmed"),
            "system_changes": verdict.get("system_changes"),
            "measurable_outcomes": verdict.get("measurable_outcomes"),
            "sources": verdict.get("sources"),
            "content_pillar": verdict.get("content_pillar"),
        }
        result = build_post_command_result(
            theme=theme,
            goal=goal,
            preferred_cta_mode=preferred_cta_mode,
            angle=verdict.get("post_angle"),
            case_context=case_context,
        )
        session["last_generated"] = {
            "theme": theme,
            "goal": goal,
            "final_text": result.payload["final_text"],
            "chosen_variant": result.payload.get("chosen_variant"),
            "variants_tried": [result.payload.get("chosen_variant")],
            "preferred_cta_mode": result.payload.get("preferred_cta_mode"),
            "case_context": case_context,
        }
        save_session(chat_id, user_id, session)
        answer_callback_query(callback_query["id"], "Собираю пост")
        send_rich_chunks(
            chat_id,
            html_join(
                html_block("🔎 Собрал пост по подтверждённому кейсу"),
                format_post_command_response(result),
            ),
            reply_markup=build_post_actions_keyboard(),
        )
        return True

    if data.startswith(CALLBACK_CASE_TOPIC_PICK_PREFIX):
        raw_index = data[len(CALLBACK_CASE_TOPIC_PICK_PREFIX) :]
        try:
            index = int(raw_index)
        except ValueError:
            answer_callback_query(callback_query["id"], "Нет темы")
            return True
        suggestions = session.get("last_case_topic_suggestions") or []
        if index < 0 or index >= len(suggestions):
            answer_callback_query(callback_query["id"], "Нет темы")
            send_chunks(chat_id, "Не вижу такой темы из кейс-подборки. Лучше заново открыть результаты кейс-ресерча.", reply_markup=build_main_menu_keyboard())
            return True
        selected = suggestions[index]
        theme = selected.get("theme")
        goal = selected.get("content_pillar") or "expert"
        preferred_cta_mode = selected.get("preferred_cta_mode")
        case_context = build_case_topic_context(selected)
        result = build_post_command_result(
            theme=theme,
            goal=goal,
            preferred_cta_mode=preferred_cta_mode,
            angle=selected.get("angle"),
            case_context=case_context,
            topic_brief=selected,
        )
        session["last_generated"] = {
            "theme": theme,
            "goal": goal,
            "final_text": result.payload["final_text"],
            "chosen_variant": result.payload.get("chosen_variant"),
            "variants_tried": [result.payload.get("chosen_variant")],
            "preferred_cta_mode": result.payload.get("preferred_cta_mode"),
            "case_context": case_context,
            "topic_brief": selected,
        }
        save_session(chat_id, user_id, session)
        answer_callback_query(callback_query["id"], "Собираю пост")
        send_rich_chunks(
            chat_id,
            html_join(
                html_block("🧠 Собрал пост по выбранной теме из кейс-подборки"),
                format_post_command_response(result),
            ),
            reply_markup=build_post_actions_keyboard(),
        )
        return True

    if data == CALLBACK_SAVE_VERIFIED_CASE:
        verified = session.get("last_verified_case") or {}
        verdict = verified.get("verdict") or {}
        theme = verdict.get("post_theme")
        if not theme:
            answer_callback_query(callback_query["id"], "Нет кейса")
            send_chunks(chat_id, "Не вижу подтверждённого кейса для сохранения. Сначала проверьте кейс через 🔎 Проверить кейс.", reply_markup=build_main_menu_keyboard())
            return True
        context = {
            "source_kind": "verified_case",
            "case_query": verified.get("query"),
            "fit_reason": verdict.get("fit_reason"),
            "post_angle": verdict.get("post_angle"),
            "what_is_confirmed": verdict.get("what_is_confirmed"),
            "system_changes": verdict.get("system_changes"),
            "measurable_outcomes": verdict.get("measurable_outcomes"),
            "content_pillar": verdict.get("content_pillar"),
            "sources": verdict.get("sources"),
        }
        notes_parts = []
        if verdict.get("post_angle"):
            notes_parts.append(f"Угол: {verdict.get('post_angle')}")
        if verdict.get("fit_reason"):
            notes_parts.append(f"Почему брать: {verdict.get('fit_reason')}")
        if verdict.get("measurable_outcomes"):
            notes_parts.append(f"Эффект: {'; '.join(verdict.get('measurable_outcomes') or [])}")
        saved = add_structured_theme_to_backlog(
            theme=theme,
            desired_pillar=verdict.get("content_pillar"),
            source="case_research",
            notes="\n".join(notes_parts),
            context=context,
        )
        if not saved:
            answer_callback_query(callback_query["id"], "Уже сохранено")
            send_chunks(chat_id, "Эта тема уже есть в сохранённых. Новую запись не добавлял.", reply_markup=build_main_menu_keyboard())
            return True
        answer_callback_query(callback_query["id"], "Сохранил")
        send_rich_chunks(
            chat_id,
            html_join(
                html_block("💾 Сохранил кейс в ваши темы"),
                format_backlog_save_confirmation([saved]),
            ),
            reply_markup=build_main_menu_keyboard(),
        )
        return True

    if data == CALLBACK_SAVE_TO_TOPICS:
        last_generated = session.get("last_generated") or {}
        theme, goal, notes, context = build_generated_backlog_payload(last_generated)
        if not theme:
            answer_callback_query(callback_query["id"], "Нет темы")
            send_chunks(chat_id, "Не вижу текущей темы или поста для сохранения. Сначала соберите пост по теме или кейсу.", reply_markup=build_main_menu_keyboard())
            return True
        saved = add_structured_theme_to_backlog(
            theme=theme,
            desired_pillar=goal,
            source="case_research" if (context.get("source_kind") in {"case_research", "verified_case"}) else "user",
            notes=notes,
            context=context,
        )
        if not saved:
            answer_callback_query(callback_query["id"], "Уже сохранено")
            send_chunks(chat_id, "Эта тема уже есть в сохранённых. Новую запись не добавлял.", reply_markup=build_post_actions_keyboard())
            return True
        answer_callback_query(callback_query["id"], "Сохранил")
        send_rich_chunks(
            chat_id,
            html_join(
                html_block("💾 Сохранил текущую тему в ваши темы"),
                format_backlog_save_confirmation([saved]),
            ),
            reply_markup=build_post_actions_keyboard(),
        )
        return True

    if data == CALLBACK_SAVE_RULE:
        session["mode"] = "await_post_rule_note"
        save_session(chat_id, user_id, session)
        answer_callback_query(callback_query["id"], "Жду правило")
        send_chunks(chat_id, "🧠 Пришлите замечание, которое нужно сохранить как правило на будущее. Это уже попадёт в долговременную память бота.", reply_markup=build_main_menu_keyboard())
        return True

    if data == CALLBACK_NEXT_VARIANT:
        last_generated = session.get("last_generated") or {}
        theme = last_generated.get("theme")
        goal = last_generated.get("goal") or session.get("post_goal") or "expert"
        preferred_cta_mode = last_generated.get("preferred_cta_mode")
        case_context = last_generated.get("case_context")
        topic_brief = last_generated.get("topic_brief")
        if not theme:
            answer_callback_query(callback_query["id"], "Нет темы")
            send_chunks(chat_id, "Не вижу последней темы в рабочей памяти. Лучше заново запустить генерацию.", reply_markup=build_main_menu_keyboard())
            return True
        tried = {item for item in last_generated.get("variants_tried", []) if isinstance(item, int)}
        try:
            result = build_post_command_result(
                theme=theme,
                goal=goal,
                exclude_variants=tried,
                preferred_cta_mode=preferred_cta_mode,
                angle=(case_context or {}).get("post_angle"),
                case_context=case_context,
                topic_brief=topic_brief,
            )
        except ValueError:
            answer_callback_query(callback_query["id"], "Варианты закончились")
            send_chunks(chat_id, "🔁 Я уже показал все текущие варианты по этой теме. Лучше прислать правку или немного изменить угол.", reply_markup=build_post_actions_keyboard())
            return True
        tried.add(result.payload.get("chosen_variant"))
        session["last_generated"] = {
            "theme": theme,
            "goal": goal,
            "final_text": result.payload["final_text"],
            "chosen_variant": result.payload.get("chosen_variant"),
            "variants_tried": sorted(tried),
            "preferred_cta_mode": result.payload.get("preferred_cta_mode"),
            "case_context": case_context,
            "topic_brief": topic_brief,
        }
        save_session(chat_id, user_id, session)
        answer_callback_query(callback_query["id"], "Собрал другой вариант")
        send_rich_chunks(
            chat_id,
            html_join(
                html_block("🔁 Собрал ещё один вариант"),
                format_post_command_response(result),
            ),
            reply_markup=build_post_actions_keyboard(),
        )
        return True

    if data == CALLBACK_ANALYZE:
        last_generated = session.get("last_generated") or {}
        final_text = last_generated.get("final_text")
        theme = last_generated.get("theme")
        if not final_text:
            answer_callback_query(callback_query["id"], "Нет текста")
            send_chunks(chat_id, "Не вижу последнего текста в памяти. Лучше сначала собрать или выбрать пост.", reply_markup=build_main_menu_keyboard())
            return True
        session["last_analyzed_post"] = {
            "text": final_text,
            "theme": theme,
            "goal": last_generated.get("goal"),
            "preferred_cta_mode": last_generated.get("preferred_cta_mode"),
            "case_context": last_generated.get("case_context"),
            "topic_brief": last_generated.get("topic_brief"),
        }
        save_session(chat_id, user_id, session)
        answer_callback_query(callback_query["id"], "Собираю разбор")
        send_rich_chunks(chat_id, format_post_analytics(final_text, theme_hint=theme), reply_markup=build_post_actions_keyboard())
        return True

    if data == CALLBACK_IMPROVE:
        source = session.get("last_generated") or session.get("last_analyzed_post") or {}
        final_text = source.get("text") or source.get("final_text")
        theme = source.get("theme")
        if not final_text:
            answer_callback_query(callback_query["id"], "Нет текста")
            send_chunks(chat_id, "Сначала нужно проанализировать или сгенерировать пост, чтобы я предложил улучшения.", reply_markup=build_main_menu_keyboard())
            return True
        session["last_improvement_options"] = build_post_improvement_options(final_text, theme_hint=theme)
        save_session(chat_id, user_id, session)
        answer_callback_query(callback_query["id"], "Собираю улучшения")
        send_rich_chunks(chat_id, format_post_improvements(final_text, theme_hint=theme), reply_markup=build_post_improvement_keyboard())
        return True

    if data in {CALLBACK_REWRITE_OPTION_1, CALLBACK_REWRITE_OPTION_2}:
        source = session.get("last_generated") or session.get("last_analyzed_post") or {}
        source_text = source.get("text") or source.get("final_text")
        theme = source.get("theme")
        goal = source.get("goal") or session.get("post_goal") or "expert"
        preferred_cta_mode = source.get("preferred_cta_mode")
        case_context = source.get("case_context")
        topic_brief = source.get("topic_brief")
        if not source_text:
            answer_callback_query(callback_query["id"], "Нет текста")
            send_chunks(chat_id, "Не вижу текста, который нужно переписать. Сначала проанализируйте или сгенерируйте пост.", reply_markup=build_main_menu_keyboard())
            return True

        option_index = 0 if data == CALLBACK_REWRITE_OPTION_1 else 1
        options = session.get("last_improvement_options") or build_post_improvement_options(source_text, theme_hint=theme)
        rewrite_plan = build_rewrite_plan_from_improvement(
            source_text,
            "improvement_1" if option_index == 0 else "improvement_2",
            theme or "",
            goal,
            option_text=options[option_index] if option_index < len(options) else None,
            topic_brief=topic_brief,
        )

        rewrite_result = rewrite_post_by_improvement(
            source_text,
            improvement_mode="improvement_1" if option_index == 0 else "improvement_2",
            theme_hint=theme,
            business_goal=goal,
            topic_brief=topic_brief,
            preferred_cta_mode=preferred_cta_mode,
            case_context=case_context,
            rewrite_plan=rewrite_plan,
        )
        if theme:
            session["last_generated"] = {
                "theme": theme,
                "goal": goal,
                "final_text": rewrite_result["final_text"],
                "chosen_variant": None,
                "variants_tried": [],
                "preferred_cta_mode": preferred_cta_mode,
                "case_context": case_context,
                "topic_brief": rewrite_result.get("topic_brief") or topic_brief,
            }
        session["last_analyzed_post"] = {
            "text": rewrite_result["final_text"],
            "theme": theme or rewrite_result["source_theme"],
            "goal": goal,
            "preferred_cta_mode": preferred_cta_mode,
            "case_context": case_context,
            "topic_brief": rewrite_result.get("topic_brief") or topic_brief,
        }
        save_session(chat_id, user_id, session)
        answer_callback_query(callback_query["id"], "Переписываю")
        send_rich_chunks(
            chat_id,
            html_join(
                html_block(f"✨ Переписал по варианту {option_index + 1}"),
                format_post_for_telegram_html(rewrite_result["final_text"]),
            ),
            reply_markup=build_post_actions_keyboard(),
        )
        return True

    if data == CALLBACK_ACCEPT:
        session["mode"] = None
        save_session(chat_id, user_id, session)
        answer_callback_query(callback_query["id"], "Принято")
        send_chunks(chat_id, "✅ Зафиксировал. Считаю этот вариант принятым.", reply_markup=build_main_menu_keyboard())
        return True

    if data == CALLBACK_FORGET:
        session = clear_session_field(chat_id, user_id, "last_generated")
        session["mode"] = None
        save_session(chat_id, user_id, session)
        answer_callback_query(callback_query["id"], "Удалено")
        send_chunks(chat_id, "🗑️ Последний черновик удалил из рабочей памяти бота. Архив канала не трогал.", reply_markup=build_main_menu_keyboard())
        return True

    answer_callback_query(callback_query["id"])
    return True


def route_message_update(update: dict) -> bool:
    if route_callback_query(update):
        return True

    message = update.get("message")
    if not message:
        return False

    text = (message.get("text") or "").strip()
    if not text:
        return False

    chat_id = message["chat"]["id"]
    from_user = message.get("from") or {}
    user_id = from_user.get("id")
    allowed_user_ids = get_allowed_user_ids()
    if allowed_user_ids and user_id not in allowed_user_ids:
        return True

    session = get_session(chat_id, user_id)

    if text.startswith("/start") or text.startswith("/help"):
        send_rich_chunks(chat_id, build_help_text(), reply_markup=build_main_menu_keyboard())
        return True

    if text == BUTTON_BACK_TO_MENU:
        session["mode"] = None
        save_session(chat_id, user_id, session)
        send_chunks(chat_id, "Возвращаю в основное меню 🙂", reply_markup=build_main_menu_keyboard())
        return True

    if text == BUTTON_SECTION_CASES:
        session["mode"] = None
        save_session(chat_id, user_id, session)
        send_chunks(chat_id, "🌐 Раздел кейсов. Здесь можно искать новые кейсы или проверять конкретные истории.", reply_markup=build_cases_menu_keyboard())
        return True

    if text == BUTTON_SECTION_ANALYTICS:
        session["mode"] = None
        save_session(chat_id, user_id, session)
        send_chunks(chat_id, "📊 Раздел аналитики. Здесь можно посмотреть аналитику ленты и оценить тему или пост.", reply_markup=build_analytics_menu_keyboard())
        return True

    if text == BUTTON_SECTION_MY_TOPICS:
        session["mode"] = None
        save_session(chat_id, user_id, session)
        send_chunks(chat_id, "📚 Раздел ваших тем. Здесь можно написать пост, сохранить темы и открыть backlog.", reply_markup=build_my_topics_menu_keyboard())
        return True

    if text == BUTTON_SECTION_REWRITE:
        session["mode"] = None
        save_session(chat_id, user_id, session)
        send_chunks(chat_id, "♻️ Раздел рерайта. Здесь можно прислать пост и пересобрать его в вашем стиле.", reply_markup=build_rewrite_menu_keyboard())
        return True

    if text == BUTTON_TOPICS:
        text_payload, topics = format_five_topics(session, exclude_history=False)
        session["mode"] = "await_topic_pick"
        session["initial_topic_suggestions"] = topics
        session["last_topic_suggestions"] = topics
        session["suggested_topics_history"] = [topic.get("theme") for topic in topics if topic.get("theme")]
        save_session(chat_id, user_id, session)
        send_rich_chunks(chat_id, text_payload, reply_markup=build_topic_pick_keyboard(len(topics)))
        return True

    if text == BUTTON_CASES:
        session["mode"] = "await_case_research_query"
        save_session(chat_id, user_id, session)
        send_chunks(
            chat_id,
            "🌐 Пришлите направление для кейс-ресерча одним сообщением.\n\nНапример:\n– сокращение потерь через процессы\n– системный turnaround после кризиса\n– автоматизация и контроль качества\n– кейсы, где системный подход дал рост эффективности",
            reply_markup=build_main_menu_keyboard(),
        )
        return True

    if text == BUTTON_CHECK_CASE:
        session["mode"] = "await_case_check_query"
        save_session(chat_id, user_id, session)
        send_chunks(
            chat_id,
            "🔎 Пришлите конкретный кейс или компанию одним сообщением.\n\nНапример:\n– Domino's turnaround\n– Starbucks turnaround\n– Toyota production system\n– Zara supply chain\n\nЯ проверю факты, отфильтрую легенду и скажу, стоит ли делать по этому кейсу пост именно под ваше позиционирование.",
            reply_markup=build_main_menu_keyboard(),
        )
        return True

    if text == BUTTON_ANALYTICS:
        session["mode"] = None
        save_session(chat_id, user_id, session)
        send_rich_chunks(chat_id, format_feed_analytics(), reply_markup=build_main_menu_keyboard())
        return True

    if text == BUTTON_EVALUATE_POST:
        session["mode"] = "await_post_analysis"
        save_session(chat_id, user_id, session)
        send_chunks(chat_id, "📝 Пришлите пост одним сообщением, и я разберу его относительно стиля, ленты, повторов и силы подачи.", reply_markup=build_main_menu_keyboard())
        return True

    if text == BUTTON_MORE_TOPICS:
        text_payload, topics = format_five_topics(session, exclude_history=True)
        session["mode"] = "await_topic_pick"
        session["last_topic_suggestions"] = topics
        extend_unique_history(session, "suggested_topics_history", [topic.get("theme") for topic in topics], 20)
        save_session(chat_id, user_id, session)
        send_rich_chunks(
            chat_id,
            html_join(
                html_block("🔁 Собрал ещё 5 тем"),
                text_payload,
            ),
            reply_markup=build_topic_pick_keyboard(len(topics)),
        )
        return True

    if text == BUTTON_RESET_TOPICS:
        topics = session.get("initial_topic_suggestions") or []
        if not topics:
            send_chunks(chat_id, "Сначала запросите темы через ✨ Предложить 5 тем.", reply_markup=build_main_menu_keyboard())
            return True
        session["mode"] = "await_topic_pick"
        session["last_topic_suggestions"] = topics
        save_session(chat_id, user_id, session)
        text_payload, _ = restore_topic_suggestions(session)
        send_rich_chunks(
            chat_id,
            html_join(
                html_block("↩️ Возвращаю первые 5 тем"),
                text_payload,
            ),
            reply_markup=build_topic_pick_keyboard(len(topics)),
        )
        return True

    if text == BUTTON_MORE_CASES:
        last_case_query = session.get("last_case_query")
        if not last_case_query:
            send_chunks(chat_id, "Сначала запустите поиск через 🌐 Найти кейсы.", reply_markup=build_main_menu_keyboard())
            return True
        exclude_signatures = session.get("suggested_case_history") or []
        research_result = research_case_topics(last_case_query, exclude_signatures=exclude_signatures)
        text_payload, cases = format_case_research(research_result)
        topic_suggestions = research_result.get("topic_suggestions") or []
        if cases:
            session["mode"] = "await_case_pick"
            session["last_case_suggestions"] = cases
            extend_unique_history(session, "suggested_case_history", collect_case_signatures(cases), 30)
            session["last_case_topic_suggestions"] = topic_suggestions
        else:
            session["mode"] = None
        save_session(chat_id, user_id, session)
        send_rich_chunks(
            chat_id,
            html_join(
                html_block("🔁 Собрал ещё 5 кейсов"),
                text_payload,
            ),
            reply_markup=build_case_pick_keyboard(len(cases)) if cases else build_main_menu_keyboard(),
        )
        if topic_suggestions:
            send_rich_chunks(
                chat_id,
                html_join(
                    html_block("🧠 Из новой кейс-подборки тоже можно сразу выбрать тему поста"),
                    "Нажмите кнопку ниже, если хотите собрать не просто кейс, а конкретный тематический угол по нему.",
                ),
                reply_markup=build_case_topic_suggestion_keyboard(len(topic_suggestions)),
            )
        return True

    if text == BUTTON_RESET_CASES:
        cases = session.get("initial_case_suggestions") or []
        topic_suggestions = session.get("initial_case_topic_suggestions") or []
        if not cases:
            send_chunks(chat_id, "Сначала запустите поиск через 🌐 Найти кейсы.", reply_markup=build_main_menu_keyboard())
            return True
        session["mode"] = "await_case_pick"
        session["last_case_suggestions"] = cases
        session["last_case_topic_suggestions"] = topic_suggestions
        save_session(chat_id, user_id, session)
        text_payload, restored_cases = restore_case_suggestions(session)
        send_rich_chunks(
            chat_id,
            html_join(
                html_block("↩️ Возвращаю первые 5 кейсов"),
                text_payload,
            ),
            reply_markup=build_case_pick_keyboard(len(restored_cases)),
        )
        if topic_suggestions:
            send_rich_chunks(
                chat_id,
                html_join(
                    html_block("🧠 Возвращаю и первые темы из этой кейс-подборки"),
                    "Можно сразу выбрать тематический угол поста по кнопке ниже.",
                ),
                reply_markup=build_case_topic_suggestion_keyboard(len(topic_suggestions)),
            )
        return True

    if text == BUTTON_EVALUATE:
        session["mode"] = "await_eval_theme"
        save_session(chat_id, user_id, session)
        send_chunks(chat_id, "🧭 Пришлите тему одним сообщением. Я скажу, брать её сейчас, переформулировать или отложить.", reply_markup=build_main_menu_keyboard())
        return True

    if text == BUTTON_SAVE_TOPICS:
        session["mode"] = "await_save_topics"
        save_session(chat_id, user_id, session)
        send_chunks(
            chat_id,
            "💾 Пришлите одну тему или список тем.\n\nМожно так:\n1. [разговорная] Тема первая\n2. [экспертная] Тема вторая\n3. [денежная] Тема третья\n\nЕсли тип не указать, я попробую определить его сам.",
            reply_markup=build_main_menu_keyboard(),
        )
        return True

    if text == BUTTON_VIEW_BACKLOG:
        text_payload, topics = format_backlog_topics()
        if not topics:
            send_rich_chunks(chat_id, text_payload, reply_markup=build_main_menu_keyboard())
            return True
        session["mode"] = "await_backlog_pick"
        session["last_backlog_topics"] = topics
        save_session(chat_id, user_id, session)
        send_rich_chunks(chat_id, text_payload, reply_markup=build_backlog_keyboard(len(topics)))
        return True

    if text == BUTTON_BACKLOG_MARK_USED:
        if not session.get("last_backlog_topics"):
            send_chunks(chat_id, "Сначала откройте список через 📚 Мои сохранённые темы.", reply_markup=build_main_menu_keyboard())
            return True
        session["mode"] = "await_backlog_mark_used"
        save_session(chat_id, user_id, session)
        send_chunks(chat_id, "✅ Нажмите номер темы, которую нужно отметить использованной.", reply_markup=build_backlog_keyboard(len(session.get('last_backlog_topics', []))))
        return True

    if text == BUTTON_BACKLOG_DELETE:
        if not session.get("last_backlog_topics"):
            send_chunks(chat_id, "Сначала откройте список через 📚 Мои сохранённые темы.", reply_markup=build_main_menu_keyboard())
            return True
        session["mode"] = "await_backlog_delete"
        save_session(chat_id, user_id, session)
        send_chunks(chat_id, "🗑️ Нажмите номер темы, которую нужно удалить из backlog.", reply_markup=build_backlog_keyboard(len(session.get('last_backlog_topics', []))))
        return True

    if text == BUTTON_REWRITE:
        session["mode"] = "await_rewrite_source"
        save_session(chat_id, user_id, session)
        send_chunks(
            chat_id,
            "♻️ Пришлите чужой пост одним сообщением. Я возьму его смысл и пересоберу текст под ваш стиль.",
            reply_markup=build_main_menu_keyboard(),
        )
        return True

    if text == BUTTON_WRITE:
        session["mode"] = "await_post_mode"
        save_session(chat_id, user_id, session)
        send_chunks(chat_id, "✍️ Выберите режим поста.", reply_markup=build_post_mode_keyboard())
        return True

    if session.get("mode") == "await_post_mode" and text in {BUTTON_MODE_EXPERT, BUTTON_MODE_MONEY, BUTTON_MODE_CONVERSATIONAL}:
        goal_map = {
            BUTTON_MODE_EXPERT: "expert",
            BUTTON_MODE_MONEY: "money",
            BUTTON_MODE_CONVERSATIONAL: "conversational",
        }
        goal = goal_map[text]
        session["post_goal"] = goal
        session["mode"] = "await_post_theme"
        save_session(chat_id, user_id, session)
        labels = {
            "expert": "🧠 Экспертный режим",
            "money": "💸 Денежный режим",
            "conversational": "🗣 Разговорный режим",
        }
        send_chunks(chat_id, f"{labels[goal]}\n\nПришлите тему одним сообщением. Я соберу пост под этот формат.", reply_markup=build_main_menu_keyboard())
        return True

    if handle_waiting_mode(chat_id, user_id, text, session):
        return True

    if session.get("mode") == "await_topic_pick" and handle_topic_pick(chat_id, user_id, text, session):
        return True

    if can_fallback_to_last_topic_pick(session, text) and handle_topic_pick(chat_id, user_id, text, session):
        return True

    if session.get("mode") == "await_case_pick" and handle_case_pick(chat_id, user_id, text, session):
        return True

    if can_fallback_to_last_case_pick(session, text) and handle_case_pick(chat_id, user_id, text, session):
        return True

    if session.get("mode") == "await_backlog_pick" and handle_backlog_pick(chat_id, user_id, text, session):
        return True

    if can_fallback_to_last_backlog_pick(session, text) and handle_backlog_pick(chat_id, user_id, text, session):
        return True

    if session.get("mode") in {"await_backlog_mark_used", "await_backlog_delete"} and handle_backlog_manage(chat_id, user_id, text, session):
        return True

    parsed = parse_post_command(text)
    if parsed["command"] == "post":
        goal = session.get("post_goal") or "expert"
        result = build_post_command_result(theme=parsed["theme"], goal=goal)
        session.setdefault("generated_themes_history", [])
        if parsed["theme"] and parsed["theme"] not in session["generated_themes_history"]:
            session["generated_themes_history"].append(parsed["theme"])
            session["generated_themes_history"] = session["generated_themes_history"][-12:]
        session["last_generated"] = {
            "theme": parsed["theme"],
            "goal": goal,
            "final_text": result.payload["final_text"],
            "chosen_variant": result.payload.get("chosen_variant"),
            "variants_tried": [result.payload.get("chosen_variant")],
        }
        save_session(chat_id, user_id, session)
        send_rich_chunks(chat_id, format_post_command_response(result), reply_markup=build_post_actions_keyboard())
        return True

    if text.strip().upper() == "СОБРАТЬ ПОСТ":
        verified = session.get("last_verified_case") or {}
        verdict = verified.get("verdict") or {}
        theme = verdict.get("post_theme")
        if not theme:
            send_chunks(chat_id, "Не вижу последнего подтверждённого кейса. Сначала проверьте кейс через 🔎 Проверить кейс.", reply_markup=build_main_menu_keyboard())
            return True
        goal = verdict.get("content_pillar") or "expert"
        preferred_cta_mode = verdict.get("preferred_cta_mode")
        case_context = {
            "source_kind": "verified_case",
            "case_query": verified.get("query"),
            "fit_reason": verdict.get("fit_reason"),
            "post_angle": verdict.get("post_angle"),
            "what_is_confirmed": verdict.get("what_is_confirmed"),
            "system_changes": verdict.get("system_changes"),
            "measurable_outcomes": verdict.get("measurable_outcomes"),
            "sources": verdict.get("sources"),
            "content_pillar": verdict.get("content_pillar"),
        }
        result = build_post_command_result(
            theme=theme,
            goal=goal,
            preferred_cta_mode=preferred_cta_mode,
            angle=verdict.get("post_angle"),
            case_context=case_context,
        )
        session["last_generated"] = {
            "theme": theme,
            "goal": goal,
            "final_text": result.payload["final_text"],
            "chosen_variant": result.payload.get("chosen_variant"),
            "variants_tried": [result.payload.get("chosen_variant")],
            "preferred_cta_mode": result.payload.get("preferred_cta_mode"),
            "case_context": case_context,
        }
        save_session(chat_id, user_id, session)
        send_rich_chunks(
            chat_id,
            html_join(
                html_block("🔎 Собрал пост по подтверждённому кейсу"),
                format_post_command_response(result),
            ),
            reply_markup=build_post_actions_keyboard(),
        )
        return True

    if parsed["command"] == "note":
        result = build_note_command_result(note=parsed["theme"])
        send_chunks(chat_id, format_note_command_response(result), reply_markup=build_main_menu_keyboard())
        return True

    send_chunks(chat_id, "Лучше пользоваться кнопками ниже 👇", reply_markup=build_main_menu_keyboard())
    return True
