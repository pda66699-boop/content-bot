from __future__ import annotations

import json
import logging

from .config import PROMPTS_DIR
from .llm_client import (
    WRITER_MODEL,
    WRITER_REASONING_EFFORT,
    complete_json,
    complete_json_with_web_search,
    llm_available,
)


LOGGER = logging.getLogger(__name__)


def _load_writer_prompt() -> str:
    path = PROMPTS_DIR / "writer.md"
    if path.exists():
        return path.read_text(encoding="utf-8")
    return (
        "Ты пишешь Telegram-пост в стиле Дениса Педченко. "
        "Нужен живой экспертный текст, не шаблон. Одна мысль на пост. "
        "Сначала управленческая проблема, потом системная причина, потом практический вывод. "
        "Не используй инфобизнес-клише. Верни только JSON."
    )


def maybe_generate_planner_candidates(payload: dict) -> list[dict] | None:
    if not llm_available():
        return None

    system_prompt = (
        "Ты контент-стратег Дениса Педченко. Придумывай темы и углы для Telegram-канала, "
        "но не ломай методологию: сервисный бизнес 60-150 млн, управленческие потери, зависимость от собственника, роли, процессы, ответственность и системные причины. "
        "Старые широкие темы допустимы только как переходные мосты в новую модель. "
        "ИИ допустим только как инструмент внутри системы. Верни только JSON."
    )
    user_prompt = json.dumps(
        {
            "task": "Предложи до 5 тем для следующего окна ленты. Можно улучшать текущие rule-based темы и добавлять новые, но без повторов и без инфостиля.",
            "required_output_format": {
                "best_next_topics": [
                    {
                        "theme": "название темы",
                        "angle": "угол подачи",
                        "content_role": "diagnostic|educational|trust",
                        "funnel_stage": "problem-aware|solution-aware|aware",
                        "repositioning_mode": "transition|new_model",
                        "novelty_rationale": "почему тема сейчас свежа",
                        "cta_suggestion": "optional|soft|none",
                    }
                ]
            },
            "business_goal": payload.get("business_goal"),
            "campaign_mode": payload.get("campaign_mode"),
            "flagship_offer": payload.get("flagship_offer"),
            "primary_segment": payload.get("primary_segment"),
            "priority_pillars": payload.get("priority_pillars"),
            "repositioning_rules": payload.get("repositioning_rules"),
            "content_balance_ranges": payload.get("content_balance_ranges"),
            "cta_matrix_overview": payload.get("cta_matrix_overview"),
            "current_feed_state": payload.get("current_feed_state"),
            "recent_topics_closed": payload.get("recent_topics_closed"),
            "avoid_now": payload.get("avoid_now"),
            "open_loops": payload.get("open_loops"),
            "rule_based_candidates": payload.get("best_next_topics"),
            "user_theme_verdict": payload.get("user_theme_verdict"),
        },
        ensure_ascii=False,
    )
    response = complete_json(system_prompt, user_prompt, temperature=0.9)
    if not response:
        LOGGER.warning("planner_candidates: LLM returned None")
        return None
    candidates = response.get("best_next_topics")
    if not isinstance(candidates, list):
        LOGGER.warning("planner_candidates: LLM response missing 'best_next_topics', got keys=%s", list(response.keys()))
        return None
    LOGGER.info("planner_candidates: LLM returned %d candidate(s)", len(candidates))
    return [item for item in candidates if isinstance(item, dict)]


_POST_TYPE_CHAR_LIMITS: dict[str, int] = {
    "pain_breakdown": 1200,
    "case": 1500,
    "provocation": 900,
    "loss_calculator": 800,
    "authority_breakdown": 1400,
    "personal_insight": 1000,
    "soft_sell": 1000,
}


def _char_limit_for_type(post_type: str) -> int:
    return _POST_TYPE_CHAR_LIMITS.get(post_type, 1200)


def generate_core_idea(topic: str, angle: str) -> str | None:
    """One cheap LLM call: returns the single controlling thought for the post.

    Used as a hard constraint passed into maybe_generate_writer_drafts so the
    main generation call cannot drift off-topic.
    """
    if not llm_available():
        return None

    system_prompt = (
        "Ты помогаешь сформулировать главную мысль Telegram-поста для канала "
        "Дениса Педченко — консультанта по управленческим потерям в сервисных "
        "бизнесах 60–150 млн ₽/год. "
        "Ответ — строго одно предложение, максимум 20 слов, без вводных слов. "
        "Это не заголовок и не тезис — это точная управленческая мысль, "
        "которой подчинён весь пост. "
        "Главная мысль должна быть достаточно ёмкой, чтобы её можно было раскрыть "
        "на 800–1000 знаков. Не формулируй тезис, который исчерпывается одним абзацем. "
        "Хорошая главная мысль содержит напряжение — причину и следствие, "
        "или противопоставление двух подходов. "
        "Верни только JSON."
    )
    user_prompt = json.dumps(
        {
            "topic": topic,
            "angle": angle,
            "required_output_format": {"core_idea": "одно предложение, максимум 20 слов"},
        },
        ensure_ascii=False,
    )
    response = complete_json(system_prompt, user_prompt, temperature=0.7)
    if not response:
        return None
    idea = response.get("core_idea")
    if not isinstance(idea, str) or not idea.strip():
        return None
    return idea.strip()


def maybe_generate_writer_drafts(payload: dict, count: int = 2) -> list[dict] | None:
    if not llm_available():
        return None

    system_prompt = _load_writer_prompt()

    # Передаём полный текст style_references, а не только заголовки
    style_refs_raw = payload.get("style_references") or []
    style_refs_full = []
    for ref in style_refs_raw[:5]:  # не более 5 чтобы не раздувать контекст
        entry: dict = {"date": ref.get("date"), "theme": ref.get("primary_theme")}
        if ref.get("body_text"):
            entry["full_text"] = ref["body_text"]
        elif ref.get("title_hook"):
            entry["hook"] = ref["title_hook"]
        style_refs_full.append(entry)

    post_type = (payload.get("post_type") or "").strip()
    core_idea = (payload.get("core_idea") or "").strip()

    LOGGER.debug("[DEBUG] post_type received: %r", post_type or "(empty)")
    LOGGER.debug("[DEBUG] core_idea received: %r", core_idea or "(empty)")

    VALID_POST_TYPES = {
        "pain_breakdown", "case", "provocation",
        "loss_calculator", "authority_breakdown",
        "personal_insight", "soft_sell",
    }
    if post_type and post_type not in VALID_POST_TYPES:
        LOGGER.warning("maybe_generate_writer_drafts: unknown post_type=%r — clearing", post_type)
        post_type = ""

    # Build a hard preamble block that appears BEFORE the writer.md system prompt.
    # This block is the first thing the model reads and cannot be contradicted by
    # anything that follows.
    preamble_lines: list[str] = [
        "╔══════════════════════════════════════════════════════════╗",
        "║  ЖЁСТКИЕ ОГРАНИЧЕНИЯ — ПРОЧИТАТЬ ПЕРЕД НАПИСАНИЕМ       ║",
        "╚══════════════════════════════════════════════════════════╝",
    ]
    if post_type:
        preamble_lines += [
            f"ТИП ПОСТА: {post_type}",
            f"Писать СТРОГО по шаблону типа «{post_type}» из раздела «ШАБЛОН ПО ТИПУ ПОСТА».",
            "Раздел «СТРУКТУРА ПОСТА» — НЕ ПРИМЕНЯЕТСЯ. Игнорировать его полностью.",
            "Отступление от шаблона типа — критическая ошибка.",
        ]
    if core_idea:
        preamble_lines += [
            f"ГЛАВНАЯ МЫСЛЬ: «{core_idea}»",
            "Каждый абзац работает только на эту мысль.",
            "Если абзац не усиливает эту мысль — его нет в посте.",
        ]
    preamble_lines.append("══════════════════════════════════════════════════════════")
    preamble = "\n".join(preamble_lines)
    system_prompt = preamble + "\n\n" + system_prompt

    char_limit = _char_limit_for_type(post_type)
    post_type_instruction = (
        f"ТИП ПОСТА: {post_type} — писать строго по шаблону этого типа. "
        if post_type
        else ""
    )
    core_idea_constraint = (
        f"ГЛАВНАЯ МЫСЛЬ (жёсткое ограничение): «{core_idea}» — весь пост только на неё. "
        if core_idea
        else ""
    )

    user_prompt = json.dumps(
        {
            "task": (
                f"Сделай {count} разных черновика поста на одну тему. "
                "Каждый черновик должен заметно отличаться по заходу и ритму. "
                "Строго следуй правилам стиля из системного промпта. "
                + post_type_instruction
                + core_idea_constraint
                + "ОБЯЗАТЕЛЬНО: пост заканчивается ровно ОДНОЙ финальной фразой-выводом. "
                "НЕТ 'Итог:', НЕТ 'Жёсткий вывод:' после уже написанного вывода — пост не пересказывает себя в конце. "
                f"ОБЯЗАТЕЛЬНО: длина текста не более {char_limit} знаков с пробелами. "
                "Если длиннее — сократить: убрать вводные обороты, убрать повторы мысли, оставить 3 пункта списка вместо 5."
            ),
            "required_output_format": {
                "drafts": [
                    {
                        "core_idea": core_idea or "одна главная мысль поста одним предложением",
                        "text": f"полный текст поста, строго до {char_limit} знаков",
                        "hook_type": "тип хука: negation|observation|paradox|personal",
                        "char_count": "примерное число знаков с пробелами",
                    }
                ]
            },
            "selected_topic": payload.get("selected_topic"),
            "angle": payload.get("angle"),
            "goal": payload.get("goal"),
            "content_role": payload.get("content_role"),
            "cta_policy": payload.get("cta_policy"),
            "post_type": post_type or None,
            "style_references": style_refs_full,
            "knowledge_core_notes": payload.get("knowledge_core_notes"),
            "avoid_phrases": payload.get("avoid_phrases"),
            "voice_profile": payload.get("voice_profile"),
            "editorial_feedback": payload.get("editorial_feedback"),
            "case_context": payload.get("case_context"),
            "topic_brief": payload.get("topic_brief"),
        },
        ensure_ascii=False,
    )
    response = complete_json(
        system_prompt,
        user_prompt,
        temperature=0.95,
        model_override=WRITER_MODEL,
        reasoning_effort_override=WRITER_REASONING_EFFORT,
    )
    if not response:
        LOGGER.warning("writer_drafts: LLM returned None")
        return None
    drafts = response.get("drafts")
    if not isinstance(drafts, list):
        LOGGER.warning("writer_drafts: LLM response missing 'drafts' list, got keys=%s", list(response.keys()))
        return None
    LOGGER.info("writer_drafts: LLM returned %d draft(s)", len(drafts))
    cleaned: list[dict] = []
    for item in drafts:
        if not isinstance(item, dict):
            continue
        text = item.get("text")
        if not isinstance(text, str) or not text.strip():
            continue
        cleaned.append({"text": text.strip()})
    return cleaned or None


def maybe_generate_rewrite(source_text: str, theme: str, rewrite_plan: dict | None = None) -> dict | None:
    if not llm_available():
        return None

    system_prompt = (
        "Ты делаешь рерайт чужого Telegram-поста под стиль Дениса Педченко. "
        "Нельзя копировать фразы. Нужно сохранить центральный смысл, но собрать текст заново через управленческую логику, системную причину и практический вывод. "
        "Если передан rewrite_plan, ты обязан следовать ему: смещать тезис, угол, формат и роль текста, а не только перефразировать формулировки. "
        "Верни только JSON."
    )
    user_prompt = json.dumps(
        {
            "task": "Сохрани смысл исходного поста, но перепиши его в более системной, спокойной, деловой манере с учётом rewrite plan.",
            "required_output_format": {
                "rewritten_text": "полный переписанный текст поста"
            },
            "detected_theme": theme,
            "source_post": source_text,
            "rewrite_plan": rewrite_plan,
        },
        ensure_ascii=False,
    )
    response = complete_json(system_prompt, user_prompt, temperature=0.9)
    if not response:
        return None
    rewritten = response.get("rewritten_text")
    if not isinstance(rewritten, str) or not rewritten.strip():
        return None
    return {"rewritten_text": rewritten.strip()}


def maybe_research_case_topics(payload: dict) -> list[dict] | None:
    if not llm_available():
        return None

    system_prompt = (
        "Ты исследователь бизнес-кейсов для Telegram-канала Дениса Педченко. "
        "Ищи только кейсы, которые прямо подтверждают пользу системного подхода: "
        "сокращение потерь, пересборка процессов, контроль, автоматизация, стандарты, операционная эффективность, управляемость. "
        "Не предлагай кейсы, если там нет явной системной перестройки или измеримого эффекта. "
        "Исключай истории только про маркетинг, ребрендинг, хайп, личный бренд или общую мотивацию. "
        "Нужен факт-чекинг по источникам. "
        "Для каждого кейса ОБЯЗАТЕЛЬНО верни непустые поля: title, post_theme, post_angle, what_is_confirmed, system_changes, measurable_outcomes, sources. "
        "В sources верни массив объектов вида {title, url}. Не возвращай кейс без источников. "
        "Если точных цифр нет, всё равно верни качественно подтверждённый эффект и 1-3 источника. Верни только JSON."
    )
    user_prompt = json.dumps(
        {
            "task": "Найди до 5 реальных и проверяемых бизнес-кейсов под тему канала. Для каждого кейса сразу предложи, какой пост можно из него сделать.",
            "research_query": payload.get("query"),
            "positioning_flags": payload.get("positioning_flags"),
            "exclude_signatures": payload.get("exclude_signatures"),
            "required_case_schema": {
                "title": "краткое название кейса",
                "company": "компания или бренд",
                "timeframe": "период, если известен",
                "what_broke": "какая была проблема",
                "what_is_confirmed": ["1-3 подтверждённых факта"],
                "system_changes": ["1-4 системных изменения"],
                "measurable_outcomes": ["1-4 результата или эффекта"],
                "why_fit": "почему кейс подходит под позиционирование канала",
                "post_theme": "какую тему поста из этого делать",
                "post_angle": "под каким углом разбирать кейс",
                "sources": [
                    {
                        "title": "название источника",
                        "url": "https://..."
                    }
                ],
            },
            "required_filters": [
                "явная польза от системного подхода",
                "сокращение потерь / рост эффективности / оптимизация / контроль / автоматизация / стандарты",
                "измеримый результат или качественно подтверждённый операционный эффект",
                "минимум 1 источник всегда, минимум 2 источника если есть цифры",
            ],
            "exclude": [
                "маркетинговые истории без процессной пересборки",
                "просто вдохновляющие истории без управленческой конкретики",
                "кейсы, которые нельзя связать с управляемостью бизнеса",
            ],
            "important": [
                "не возвращай пустые массивы sources",
                "не ограничивайся одними заголовками компаний",
                "если нет точных чисел, заполни качественно подтверждённый эффект",
                "если источник один, всё равно верни кейс, но с осторожной подачей",
            ],
        },
        ensure_ascii=False,
    )
    response = complete_json_with_web_search(system_prompt, user_prompt, temperature=0.25)
    if not response:
        return None
    cases = response.get("cases")
    if not isinstance(cases, list):
        return None
    return [item for item in cases if isinstance(item, dict)]


def maybe_verify_case(payload: dict) -> dict | None:
    if not llm_available():
        return None

    system_prompt = (
        "Ты проверяешь конкретный бизнес-кейс для Telegram-канала Дениса Педченко. "
        "Тебе нужно отделить подтверждённые факты от легенды, понять, был ли там реальный системный сдвиг, "
        "и оценить, подходит ли этот кейс под позиционирование: управляемость, процессы, контроль, автоматизация, сокращение потерь и операционная эффективность. "
        "Если кейс в основном про маркетинг, личный бренд, продуктовый хайп или вдохновляющую историю без системной пересборки, отбрасывай его. "
        "Верни только JSON."
    )
    user_prompt = json.dumps(
        {
            "task": "Проверь конкретный кейс и скажи, стоит ли делать по нему пост.",
            "case_query": payload.get("query"),
            "positioning_flags": payload.get("positioning_flags"),
            "required_output": [
                "what_is_confirmed",
                "what_is_unclear_or_weak",
                "system_changes",
                "measurable_outcomes",
                "fit_verdict",
                "fit_reason",
                "post_theme",
                "post_angle",
                "sources",
            ],
        },
        ensure_ascii=False,
    )
    response = complete_json_with_web_search(system_prompt, user_prompt, temperature=0.2)
    return response if isinstance(response, dict) else None
