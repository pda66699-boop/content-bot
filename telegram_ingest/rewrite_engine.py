from __future__ import annotations

import re
from typing import Any

from .critic_engine import critic_review, load_rows
from .editorial_extractor import infer_editorial_metadata_from_post
from .editorial_similarity import find_semantic_neighbors
from .hybrid_llm import maybe_generate_rewrite
from .knowledge import load_editorial_feedback, load_terminology_registry
from .polish_engine import polish_text
from .writer_engine import (
    add_emojis_if_needed,
    apply_editorial_feedback_guards,
    apply_stop_word_guard,
    build_effect,
    build_focus_line,
    build_hook,
    build_reason,
    build_solution,
    finalize_text,
    generate_drafts,
    infer_profile,
    load_stop_words,
    load_user_preferences,
    merge_stop_word_sources,
    select_hashtag,
    strip_emojis_if_needed,
)


def normalize_rewrite_plan(
    rewrite_plan: dict | None,
    source_text: str,
    theme: str,
    business_goal: str,
    topic_brief: dict | None = None,
) -> dict:
    """Return a safe explicit rewrite plan with soft defaults."""

    payload = dict(rewrite_plan or {})
    topic_brief = dict(topic_brief or {})
    source_metadata = infer_editorial_metadata_from_post(
        {
            "title_hook": theme,
            "primary_theme": theme,
            "body_text": source_text,
            "body_summary": source_text[:280],
            "content_role": topic_brief.get("content_goal") or business_goal,
            "format": topic_brief.get("format_type") or "expert",
            "funnel_stage": topic_brief.get("funnel_stage"),
        }
    )
    matched_posts = find_semantic_neighbors(source_metadata, load_rows(), limit=3)
    avoid_similarity_with_post_ids = payload.get("avoid_similarity_with_post_ids")
    if not isinstance(avoid_similarity_with_post_ids, list):
        avoid_similarity_with_post_ids = []
    if not avoid_similarity_with_post_ids:
        avoid_similarity_with_post_ids = [item.get("post_id") for item in matched_posts if item.get("post_id")]

    must_remove_patterns = payload.get("must_remove_patterns")
    if not isinstance(must_remove_patterns, list):
        must_remove_patterns = []

    normalized = {
        "target_primary_thesis": (payload.get("target_primary_thesis") or source_metadata.get("primary_thesis") or "").strip(),
        "target_angle": (payload.get("target_angle") or topic_brief.get("angle") or "").strip(),
        "target_format_type": (payload.get("target_format_type") or topic_brief.get("recommended_format") or topic_brief.get("format_type") or "expert").strip(),
        "target_content_goal": (payload.get("target_content_goal") or topic_brief.get("content_goal") or business_goal or "expert").strip(),
        "target_funnel_stage": (payload.get("target_funnel_stage") or topic_brief.get("funnel_stage") or source_metadata.get("funnel_stage") or "aware").strip(),
        "avoid_similarity_with_post_ids": avoid_similarity_with_post_ids,
        "must_remove_patterns": [str(item).strip() for item in must_remove_patterns if str(item).strip()],
    }
    return normalized


def build_rewrite_plan_from_improvement(
    source_text: str,
    improvement_mode: str,
    theme: str,
    business_goal: str,
    option_text: str | None = None,
    topic_brief: dict | None = None,
) -> dict:
    """Build an explicit rewrite plan from an improvement choice."""

    topic_brief = dict(topic_brief or {})
    metadata = infer_editorial_metadata_from_post(
        {
            "title_hook": theme,
            "primary_theme": theme,
            "body_text": source_text,
            "body_summary": source_text[:280],
            "content_role": business_goal,
            "format": topic_brief.get("format_type") or "expert",
            "funnel_stage": topic_brief.get("funnel_stage"),
        }
    )
    target_angle = build_improvement_angle(theme, improvement_mode, business_goal)
    target_format_type = topic_brief.get("recommended_format") or metadata.get("format_type") or "expert"
    target_content_goal = topic_brief.get("content_goal") or business_goal
    target_funnel_stage = topic_brief.get("funnel_stage") or metadata.get("funnel_stage") or "aware"
    must_remove_patterns = []

    lowered_option = (option_text or "").lower().replace("ё", "е")
    novelty_status = (topic_brief.get("novelty_status") or "").lower()
    if improvement_mode == "improvement_1":
        must_remove_patterns.extend(["Если сжать это до одной мысли", "Ключевой момент здесь такой"])
    if improvement_mode == "improvement_2":
        must_remove_patterns.extend(["Если сжать это до одной мысли", "проблема обычно глубже, чем кажется на поверхности"])
        if topic_brief.get("allowed_reframes"):
            target_angle = topic_brief["allowed_reframes"][0]
        if topic_brief.get("recommended_format"):
            target_format_type = topic_brief["recommended_format"]
        if topic_brief.get("recommended_cta_type") == "diagnostic":
            target_funnel_stage = "solution_aware"
            target_content_goal = "diagnostic"
    if "другой следующий слой" in lowered_option and topic_brief.get("content_goal"):
        target_content_goal = topic_brief.get("content_goal")
    if novelty_status in {"reframe_allowed", "too_close"}:
        if topic_brief.get("allowed_reframes"):
            target_angle = topic_brief["allowed_reframes"][0]
        target_format_type = topic_brief.get("recommended_format") or ("case" if target_format_type == "expert" else target_format_type)
        must_remove_patterns.extend(
            [
                split_paragraphs(source_text)[0] if split_paragraphs(source_text) else "",
                "Если сжать это до одной мысли",
                "Ключевой момент здесь такой",
            ]
        )

    return normalize_rewrite_plan(
        {
            "target_primary_thesis": metadata.get("primary_thesis"),
            "target_angle": target_angle,
            "target_format_type": target_format_type,
            "target_content_goal": target_content_goal,
            "target_funnel_stage": target_funnel_stage,
            "must_remove_patterns": must_remove_patterns,
        },
        source_text=source_text,
        theme=theme,
        business_goal=business_goal,
        topic_brief=topic_brief,
    )


def split_paragraphs(text: str) -> list[str]:
    return [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]


def split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return [part.strip() for part in parts if part.strip()]


def infer_rewrite_theme(source_text: str) -> str:
    lowered = source_text.lower().replace("ё", "е")
    if any(token in lowered for token in ("налог", "дорож", "издерж", "расход", "себестоим", "марж")):
        return "рост расходов и оптимизация затрат"
    if any(token in lowered for token in ("стад", "кризис", "adizes", "жизненного цикла")):
        return "разбор типичных причинно-следственных ошибок собственника по стадиям бизнеса"
    if any(token in lowered for token in ("роль", "оргструкт", "ответствен", "сотрудник", "команда")):
        return "оргструктура и роли"
    if any(token in lowered for token in ("процесс", "регламент", "согласован", "стык", "операцион")):
        return "скрытые потери в операционке"
    if any(token in lowered for token in ("ии", "ai", "gpt", "нейро")):
        return "работа с причинами, а не симптомами"
    return "работа с причинами, а не симптомами"


def extract_source_summary(source_text: str) -> dict:
    paragraphs = split_paragraphs(source_text)
    sentences = split_sentences(source_text)
    first_sentence = sentences[0] if sentences else source_text.strip()
    problem_sentence = ""
    recommendation_sentence = ""
    conclusion_sentence = ""

    for sentence in sentences:
        lowered = sentence.lower()
        if not problem_sentence and any(token in lowered for token in ("проблем", "ошиб", "теря", "не может", "не уме", "хаос", "дороже")):
            problem_sentence = sentence
        if not recommendation_sentence and any(token in lowered for token in ("нужно", "важно", "стоит", "надо", "сначала", "поэтому")):
            recommendation_sentence = sentence
        if not conclusion_sentence and any(token in lowered for token in ("поэтому", "тогда", "в итоге", "значит")):
            conclusion_sentence = sentence

    if not problem_sentence and len(paragraphs) > 1:
        problem_sentence = split_sentences(paragraphs[1])[0] if split_sentences(paragraphs[1]) else paragraphs[1]
    if not recommendation_sentence and len(sentences) > 2:
        recommendation_sentence = sentences[min(2, len(sentences) - 1)]
    if not conclusion_sentence and sentences:
        conclusion_sentence = sentences[-1]

    return {
        "first_sentence": first_sentence,
        "problem_sentence": problem_sentence or first_sentence,
        "recommendation_sentence": recommendation_sentence or "",
        "conclusion_sentence": conclusion_sentence or "",
    }


def rewrite_source_scene(problem_sentence: str) -> str:
    cleaned = re.sub(r"\s+", " ", problem_sentence).strip()
    cleaned = cleaned.lstrip("–-•")
    if not cleaned:
        return ""
    return f"Обычно это выглядит очень приземлённо. {cleaned}"


def rewrite_source_focus(summary: dict, theme: str, variant: int) -> str:
    recommendation = summary.get("recommendation_sentence", "").strip()
    if recommendation:
        recommendation = recommendation[0].upper() + recommendation[1:]
        return f"Если сжать смысл исходного поста до одной мысли, то она такая: {recommendation}"
    return build_focus_line(theme, "сохранить центральную мысль исходного текста, но подать её через системную причину и практический вывод", variant)


def rewrite_source_effect(summary: dict, profile: dict, variant: int) -> str:
    conclusion = summary.get("conclusion_sentence", "").strip()
    if conclusion and len(conclusion) <= 220:
        return f"И тогда результат читается иначе. {conclusion}"
    return build_effect(profile, variant)


def rewrite_post_in_author_style(source_text: str, variant: int = 0, rewrite_plan: dict | None = None) -> dict:
    theme = infer_rewrite_theme(source_text)
    profile = infer_profile(theme)
    summary = extract_source_summary(source_text)
    rewrite_plan = normalize_rewrite_plan(rewrite_plan, source_text, theme, "expert")

    llm_result = maybe_generate_rewrite(source_text, theme, rewrite_plan=rewrite_plan)
    if llm_result:
        draft = llm_result["rewritten_text"]
        if select_hashtag(theme) not in draft:
            draft = finalize_text([draft], select_hashtag(theme))
    else:
        hook = rewrite_plan.get("target_primary_thesis") or build_hook(profile, variant)
        scene = rewrite_source_scene(summary["problem_sentence"])
        reason = build_reason(profile, "переосмыслить чужой пост через системную причину", variant)
        focus = rewrite_plan.get("target_angle") or rewrite_source_focus(summary, theme, variant)
        solution = build_solution(profile, theme, variant)
        effect = rewrite_source_effect(summary, profile, variant)
        hashtag = select_hashtag(theme)
        draft = finalize_text([hook, scene, reason, focus, solution, effect], hashtag)

    terminology_registry = load_terminology_registry()
    stop_words = merge_stop_word_sources(load_stop_words(), terminology_registry)
    editorial_feedback = load_editorial_feedback()
    user_preferences = load_user_preferences()

    draft = add_emojis_if_needed(draft, theme, user_preferences, "expert")
    draft = apply_stop_word_guard(draft, stop_words)
    draft = apply_editorial_feedback_guards(draft, editorial_feedback)
    draft = strip_emojis_if_needed(draft, user_preferences)

    review = critic_review(draft)
    return {
        "source_theme": theme,
        "source_summary": summary,
        "final_text": draft,
        "critic_review": review,
        "rewrite_plan": rewrite_plan,
    }


def infer_business_goal_from_text(source_text: str, theme_hint: str | None = None) -> str:
    combined = f"{theme_hint or ''} {source_text}".lower().replace("ё", "е")
    if "#мысли" in combined or any(token in combined for token in ("пауза", "жизн", "свобод", "инсайт", "отдых", "выбор")):
        return "conversational"
    if any(token in combined for token in ("расход", "издерж", "прибыл", "выруч", "@adizesbizbot", "диагност")):
        return "money"
    return "expert"


def resolve_rewrite_theme(source_text: str, theme_hint: str | None = None) -> str:
    canonical = infer_rewrite_theme(source_text)
    if not theme_hint:
        return canonical
    lowered = theme_hint.lower().replace("ё", "е")
    if any(token in lowered for token in ("стад", "кризис", "диагност", "расход", "издерж", "оргструкт", "роль", "симптом", "причин")):
        return theme_hint
    return canonical


def build_improvement_angle(theme: str, improvement_mode: str, business_goal: str) -> str:
    normalized = theme.lower().replace("ё", "е")
    if improvement_mode == "improvement_1":
        if business_goal == "conversational":
            return "зайти через более живую личную сцену, быстрее заземлить мысль и убрать сухую рефлексию"
        if any(token in normalized for token in ("стад", "кризис", "найм", "сотруд", "команд")):
            return "зайти через более узнаваемую ситуацию из бизнеса, раньше дать конкретный пример и убрать общий заход"
        return "сделать вход понятнее, быстрее дать конкретику и показать пример раньше абстрактного вывода"
    if improvement_mode == "improvement_2":
        if business_goal == "conversational":
            return "сделать личный вывод сильнее и связать наблюдение с более ясной мыслью без лишнего воздуха"
        if any(token in normalized for token in ("расход", "издерж", "деньг", "прибыл")):
            return "сделать вывод жёстче и прикладнее: меньше общих формулировок, больше денежного последствия и управленческого решения"
        return "сместить акцент в более сильный угол, сделать вывод жёстче и оставить один ясный практический вывод"


def score_rewrite_candidate(text: str, improvement_mode: str) -> int:
    review = critic_review(text)
    score = 100
    if review.get("verdict") == "rewrite":
        score -= 25
    if review.get("repeat_risk") == "medium":
        score -= 8
    if review.get("repeat_risk") == "high":
        score -= 18
    if review.get("style_risk") == "medium":
        score -= 10
    if review.get("editorial_feedback_risk") == "medium":
        score -= 18
    if review.get("stop_word_risk") == "medium":
        score -= 12
    if 900 <= len(text) <= 2200:
        score += 4

    lowered = text.lower().replace("ё", "е")
    if improvement_mode == "improvement_1":
        if "например" in lowered:
            score += 8
        if any(token in lowered for token in ("что обычно происходит", "3 вещи", "полезно проверить")):
            score += 8
        if "на поверхности кажется" in lowered or "снаружи" in lowered:
            score += 5
    if improvement_mode == "improvement_2":
        if any(token in lowered for token in ("ключевой момент", "фокус здесь", "главный вопрос")):
            score += 7
        if any(token in lowered for token in ("тогда", "после такой диагностики", "это уже")):
            score += 7
        if "например" not in lowered and "что обычно происходит" not in lowered:
            score += 3
        if "что обычно происходит" in lowered:
            score -= 12
        if len(text) < 1500:
            score += 8
        if len(text) > 1900:
            score -= 8
    return score


def apply_must_remove_patterns(text: str, patterns: list[str]) -> str:
    """Remove or soften banned fragments from rewritten text."""

    cleaned = text
    for pattern in patterns:
        if not pattern:
            continue
        cleaned = cleaned.replace(pattern, "")
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def build_plan_based_rewrite(
    source_text: str,
    theme: str,
    rewrite_plan: dict,
    preferred_cta_mode: str | None = None,
) -> str:
    """Build a deterministic fallback rewrite from an explicit rewrite plan."""

    summary = extract_source_summary(source_text)
    primary_thesis = rewrite_plan.get("target_primary_thesis") or summary.get("problem_sentence") or theme
    target_angle = rewrite_plan.get("target_angle") or "сместить подачу в новый управленческий угол"
    target_format_type = rewrite_plan.get("target_format_type") or "expert"
    target_content_goal = rewrite_plan.get("target_content_goal") or "expert"
    target_funnel_stage = rewrite_plan.get("target_funnel_stage") or "aware"

    opening = primary_thesis
    angle_line = f"Если разбирать это не по старой поверхности, а через другой фокус, то главный угол здесь такой: {target_angle}."
    format_line_map = {
        "case": "Такой переписанный вариант лучше подавать как кейсовый разбор: не тезис ради тезиса, а сцена, решение и управленческий вывод.",
        "applied": "Лучше собрать это как прикладной пост: одна ситуация, одна причина, один следующий шаг для собственника.",
        "conversation": "Эту мысль лучше подать спокойнее и ближе к наблюдению, а не как жёсткий экспертный тезис.",
        "reflective": "Эту подачу лучше сделать более наблюдательной и личной, чтобы вывод звучал живо, а не как конспект.",
        "expert": "Эту тему лучше держать как экспертный разбор: симптом, причина, архитектурный вывод.",
    }
    goal_line_map = {
        "diagnostic": "Смысл переписывания здесь не в перефразировании, а в том, чтобы быстрее довести читателя до диагностики системной причины.",
        "applied": "Смысл переписывания здесь в прикладном выводе: что именно проверять или менять первым.",
        "case": "Смысл переписывания здесь в разборе через пример или кейсовую механику, а не через абстрактное объяснение.",
        "expert": "Смысл переписывания здесь в более собранной экспертной логике без лишних общих формулировок.",
        "conversational": "Смысл переписывания здесь в более живой и менее декларативной подаче.",
    }
    funnel_line_map = {
        "solution_aware": "По воронке такой текст лучше доводить до слоя solution-aware: показать не только проблему, но и куда смотреть дальше.",
        "problem_aware": "По воронке такой текст лучше оставить на уровне problem-aware: назвать симптом и раскрыть его системную причину.",
        "solution_consideration": "По воронке такой текст стоит сместить в solution_consideration: показать, почему именно этот подход уместен сейчас.",
        "aware": "По воронке здесь лучше оставить спокойный awareness-формат без лишнего дожима.",
        "trust": "По воронке здесь полезнее строить доверие через ясность мысли, а не через жёсткий CTA.",
    }
    effect = summary.get("conclusion_sentence") or "Тогда текст меняет не только формулировки, но и сам управленческий акцент."

    parts = [
        opening,
        angle_line,
        format_line_map.get(target_format_type, format_line_map["expert"]),
        goal_line_map.get(target_content_goal, goal_line_map["expert"]),
        funnel_line_map.get(target_funnel_stage, funnel_line_map["aware"]),
        f"Практический эффект такого сдвига читается иначе: {effect}",
    ]

    if preferred_cta_mode == "diagnostic":
        parts.append("Если это узнаётся в вашем бизнесе, логично продолжить разговор уже через диагностику самого перекоса, а не только обсуждение симптома.")
    elif preferred_cta_mode == "comments":
        parts.append("Если откликается, это можно продолжить в комментариях и сравнить, где именно такой перекос проявляется сильнее всего.")

    hashtag = "#мысли" if target_format_type in {"conversation", "reflective"} else select_hashtag(theme)
    return finalize_text(parts, hashtag)


def normalize_topic_brief(topic_brief: dict | None, theme: str, angle: str, business_goal: str, preferred_cta_mode: str | None = None) -> dict:
    """Return a safe topic brief for downstream draft generation."""

    payload = dict(topic_brief or {})
    payload["theme"] = payload.get("theme") or theme
    payload["angle"] = payload.get("angle") or angle
    payload["content_role"] = payload.get("content_role") or payload.get("content_goal") or business_goal
    payload["content_goal"] = payload.get("content_goal") or payload.get("content_role") or business_goal
    payload["content_pillar"] = payload.get("content_pillar") or business_goal
    payload["funnel_stage"] = payload.get("funnel_stage") or "aware"
    payload["format_type"] = payload.get("format_type") or payload.get("recommended_format") or "expert"
    payload["cta_need"] = payload.get("cta_need") or "optional"
    payload["why_now"] = payload.get("why_now") or payload.get("reason") or "переписать тему через новый смысловой план без повтора прежнего угла"
    payload["preferred_cta_mode"] = preferred_cta_mode or payload.get("preferred_cta_mode")
    payload["allowed_reframes"] = payload.get("allowed_reframes") or []
    return payload


def _normalize_line(text: str) -> str:
    cleaned = re.sub(r"\s+", " ", text).strip()
    return cleaned.rstrip(". ")


def rewrite_conversational_post(
    source_text: str,
    source_theme: str,
    improvement_mode: str,
    preferred_cta_mode: str | None = None,
) -> str:
    summary = extract_source_summary(source_text)
    source_paragraphs = split_paragraphs(source_text)
    theme_sentences = [part.strip(" .") for part in re.split(r"[?.!]\s*", source_theme) if part.strip()]
    opening = _normalize_line(theme_sentences[0] if theme_sentences else summary.get("first_sentence") or source_theme)

    internal_conflict = ""
    practical_step = ""
    lowered_theme = source_theme.lower().replace("ё", "е")
    if "какое решение" in lowered_theme:
        before, _, after = source_theme.partition("Какое решение")
        before_sentences = [part.strip(" .") for part in re.split(r"[?.!]\s*", before) if part.strip()]
        if before_sentences:
            opening = _normalize_line(before_sentences[0])
            if len(before_sentences) > 1:
                internal_conflict = _normalize_line(before_sentences[1])
        practical_step = _normalize_line(after.strip(" :.-?"))

    if not internal_conflict and len(theme_sentences) > 1:
        internal_conflict = _normalize_line(theme_sentences[1])
    if not practical_step and len(theme_sentences) > 2:
        practical_step = _normalize_line(theme_sentences[-1])

    if not internal_conflict:
        internal_conflict = _normalize_line(summary.get("problem_sentence") or "")
    if not practical_step:
        practical_step = _normalize_line(summary.get("recommendation_sentence") or "")

    reflective_bridge = (
        "Такая конструкция быстро начинает влиять не только на ощущение от работы, но и на сам способ принимать решения: "
        "день собирается через давление, а не через ясный выбор."
    )
    practical_bridge = (
        "На практике это бьёт по работе очень конкретно: растёт внутреннее сопротивление, важные задачи откладываются, "
        "а внимание уходит не туда, где действительно держится результат."
    )
    stronger_conclusion = (
        "Поэтому здесь полезно собирать день не от чувства долга, а от нескольких действий, которые реально дают основной результат. "
        "Так работа становится спокойнее и точнее: появляется приоритет, а не вечное внутреннее принуждение."
    )
    softer_conclusion = (
        "Тогда работа перестаёт быть бесконечным долгом. Появляется больше воздуха, а вместе с ним и более спокойное управление собой."
    )

    if not practical_step:
        practical_step = "сначала выделить 3-4 действия в день, которые действительно держат основной результат"

    step_line = f"Для себя здесь вижу более рабочий ход: {practical_step[0].lower() + practical_step[1:]}" if practical_step else ""
    cta = ""
    if preferred_cta_mode != "none":
        cta = "Если откликается, можно продолжить это обсуждение в комментариях и посмотреть, как это проявляется в работе."

    if improvement_mode == "improvement_2":
        parts = [
            opening,
            internal_conflict or "Сейчас мне особенно заметно, как сильно работа через внутреннее «надо» съедает энергию и фокус.",
            practical_bridge,
            step_line,
            stronger_conclusion,
        ]
    else:
        parts = [
            opening,
            internal_conflict or "Сейчас мне особенно заметно, как сильно работа через внутреннее «надо» съедает энергию и фокус.",
            reflective_bridge,
            step_line,
            softer_conclusion,
        ]

    if cta:
        parts.append(cta)
    return finalize_text(parts, "#мысли")


def rewrite_post_by_improvement(
    source_text: str,
    improvement_mode: str,
    theme_hint: str | None = None,
    business_goal: str | None = None,
    topic_brief: dict | None = None,
    preferred_cta_mode: str | None = None,
    case_context: dict | None = None,
    rewrite_plan: dict | None = None,
) -> dict:
    theme = theme_hint or resolve_rewrite_theme(source_text, theme_hint=theme_hint)
    goal = business_goal or infer_business_goal_from_text(source_text, theme_hint=theme_hint)
    rewrite_plan = normalize_rewrite_plan(rewrite_plan, source_text, theme, goal, topic_brief=topic_brief)
    angle = rewrite_plan.get("target_angle") or build_improvement_angle(theme, improvement_mode, goal)
    target_goal = rewrite_plan.get("target_content_goal") or goal
    locked_brief = normalize_topic_brief(topic_brief, theme, angle, target_goal, preferred_cta_mode=preferred_cta_mode)
    locked_brief["format_type"] = rewrite_plan.get("target_format_type") or locked_brief.get("format_type")
    locked_brief["funnel_stage"] = rewrite_plan.get("target_funnel_stage") or locked_brief.get("funnel_stage")
    locked_brief["primary_thesis"] = rewrite_plan.get("target_primary_thesis") or locked_brief.get("primary_thesis")

    if target_goal == "conversational" and not case_context:
        best_text = rewrite_conversational_post(
            source_text,
            theme,
            improvement_mode,
            preferred_cta_mode=preferred_cta_mode,
        )
        best_text = apply_must_remove_patterns(best_text, rewrite_plan.get("must_remove_patterns") or [])
        return {
            "source_theme": theme,
            "source_summary": extract_source_summary(source_text),
            "final_text": best_text,
            "critic_review": critic_review(best_text),
            "improvement_mode": improvement_mode,
            "selected_angle": angle,
            "business_goal": target_goal,
            "topic_brief": locked_brief,
            "preferred_cta_mode": preferred_cta_mode,
            "case_context": case_context,
            "rewrite_plan": rewrite_plan,
        }

    drafts_payload = generate_drafts(
        theme=theme,
        angle=angle,
        business_goal=target_goal,
        count=3,
        preferred_cta_mode=preferred_cta_mode,
        case_context=case_context,
        topic_brief=locked_brief,
    )
    best_text = ""
    best_review: dict | None = None
    best_score = -10_000

    for draft in drafts_payload.get("drafts", []):
        polished_payload = polish_text(draft["text"])
        polished_text_value = apply_must_remove_patterns(
            polished_payload["polished_text"],
            rewrite_plan.get("must_remove_patterns") or [],
        )
        score = score_rewrite_candidate(polished_text_value, improvement_mode)
        if score > best_score:
            best_score = score
            best_text = polished_text_value
            best_review = polished_payload["critic_review"]

    if not best_text:
        fallback_text = build_plan_based_rewrite(
            source_text,
            theme,
            rewrite_plan,
            preferred_cta_mode=preferred_cta_mode,
        )
        fallback_text = apply_must_remove_patterns(fallback_text, rewrite_plan.get("must_remove_patterns") or [])
        return {
            "source_theme": theme,
            "source_summary": extract_source_summary(source_text),
            "final_text": fallback_text,
            "critic_review": critic_review(fallback_text),
            "improvement_mode": improvement_mode,
            "selected_angle": angle,
            "business_goal": target_goal,
            "topic_brief": locked_brief,
            "preferred_cta_mode": preferred_cta_mode,
            "case_context": case_context,
            "rewrite_plan": rewrite_plan,
        }

    return {
        "source_theme": theme,
        "source_summary": extract_source_summary(source_text),
        "final_text": best_text,
        "critic_review": best_review or critic_review(best_text),
        "improvement_mode": improvement_mode,
        "selected_angle": angle,
        "business_goal": target_goal,
        "topic_brief": locked_brief,
        "preferred_cta_mode": preferred_cta_mode,
        "case_context": case_context,
        "rewrite_plan": rewrite_plan,
    }
