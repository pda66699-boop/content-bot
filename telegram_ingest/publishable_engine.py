from __future__ import annotations

from dataclasses import dataclass

from .critic_engine import critic_review
from .knowledge import load_terminology_registry
from .polish_engine import polish_text
from .positioning import resolve_cta_strategy
from .writer_engine import (
    apply_stop_word_guard,
    generate_drafts,
    load_stop_words,
    merge_stop_word_sources,
)


@dataclass
class RankedDraft:
    text: str
    score: int
    critic: dict
    cta_need: str
    variant: int


def score_draft(critic: dict, text: str, cta_need: str) -> int:
    score = 100

    if critic["verdict"] == "rewrite":
        score -= 30
    if critic["repeat_risk"] == "medium":
        score -= 10
    if critic["repeat_risk"] == "high":
        score -= 25
    if critic["style_risk"] == "medium":
        score -= 10
    if critic["method_risk"] == "medium":
        score -= 8
    if critic["cta_risk"] == "medium":
        score -= 5
    if critic.get("stop_word_risk") == "medium":
        score -= 14
    if critic.get("editorial_feedback_risk") == "medium":
        score -= 18
    if critic.get("golden_copy_risk") == "medium":
        score -= 12
    if critic.get("golden_copy_risk") == "high":
        score -= 28
    if critic.get("voice_authenticity_risk") == "medium":
        score -= 18
    if critic.get("voice_authenticity_risk") == "high":
        score -= 36
    if critic.get("synthetic_case_risk") == "medium":
        score -= 12
    if critic.get("synthetic_case_risk") == "high":
        score -= 24
    if critic.get("corporate_jargon_risk") == "medium":
        score -= 10
    if critic.get("corporate_jargon_risk") == "high":
        score -= 20
    if critic.get("topic_alignment_risk") == "medium":
        score -= 22
    if critic.get("topic_alignment_risk") == "high":
        score -= 48

    length = len(text)
    if length < 900:
        score -= 8
    elif 1000 <= length <= 2100:
        score += 4

    if "@adizesbizbot" in text:
        score += 3
    if cta_need == "none":
        score -= 1

    return score


def choose_best_variant(drafts_payload: dict, exclude_variants: set[int] | None = None) -> RankedDraft:
    exclude_variants = exclude_variants or set()
    # Load stop_words once for the final safety pass applied after polish_text.
    _stop_words = merge_stop_word_sources(load_stop_words(), load_terminology_registry())
    ranked: list[RankedDraft] = []
    for draft in drafts_payload["drafts"]:
        if draft["variant"] in exclude_variants:
            continue
        polished_payload = polish_text(
            draft["text"],
            selected_theme=drafts_payload.get("selected_theme"),
            selected_angle=drafts_payload.get("selected_angle"),
        )
        polished_text_value = polished_payload["polished_text"]
        # Final safety pass: polish_text may produce or preserve forbidden phrases,
        # so we re-run the guard here, after polish, before scoring and display.
        polished_text_value = apply_stop_word_guard(polished_text_value, _stop_words)
        critic = polished_payload["critic_review"]
        score = score_draft(critic, polished_text_value, draft["cta_need"])
        ranked.append(
            RankedDraft(
                text=polished_text_value,
                score=score,
                critic=critic,
                cta_need=draft["cta_need"],
                variant=draft["variant"],
            )
        )

    if not ranked:
        raise ValueError("No draft variants available after exclusions")
    ranked.sort(key=lambda item: item.score, reverse=True)
    return ranked[0]


def explain_cta(final_text: str, cta_need: str) -> str:
    strategy = resolve_cta_strategy(final_text, None)
    if "@adizesbizbot" in final_text:
        return "Выбран CTA в @adizesbizbot, потому что тема логично ведёт в диагностику как мягкий вход к следующему шагу."
    if "@pda33" in final_text:
        return "Выбран CTA в личку, потому что тема логично переводит в персональный разбор ситуации."
    if "комментар" in final_text.lower():
        return "Выбран CTA в обсуждение, чтобы пост чаще собирал реакцию и вовлечение без лишнего давления продажей."
    if "60 дней" in final_text.lower() or "бизнес без потерь" in final_text.lower():
        return "Выбран CTA к флагману, потому что тема уже близка к офферу и допускает более прямой следующий шаг."
    if "диагностик" in final_text.lower():
        return "Выбран CTA на диагностику, потому что тема уже подводит к системному разбору бизнеса."
    if cta_need == "optional":
        return "CTA оставлен мягким, чтобы не ломать экспертный тон поста."
    if cta_need == "hard":
        return f"CTA усилен, потому что тема уже находится на стадии {strategy.get('funnel_stage')} и может вести ближе к офферу."
    return "CTA не является главным элементом этого поста."


def generate_publishable_post(
    theme: str | None = None,
    angle: str | None = None,
    business_goal: str = "expert",
    draft_count: int = 4,
    exclude_variants: set[int] | None = None,
    preferred_cta_mode: str | None = None,
    case_context: dict | None = None,
    topic_brief: dict | None = None,
) -> dict:
    drafts_payload = generate_drafts(
        theme=theme,
        angle=angle,
        business_goal=business_goal,
        count=draft_count,
        preferred_cta_mode=preferred_cta_mode,
        case_context=case_context,
        topic_brief=topic_brief,
    )
    best = choose_best_variant(drafts_payload, exclude_variants=exclude_variants)

    return {
        "selected_theme": drafts_payload["selected_theme"],
        "selected_angle": drafts_payload["selected_angle"],
        "positioning_flags": drafts_payload["positioning_flags"],
        "style_profile": drafts_payload.get("style_profile", {}),
        "why_now": drafts_payload["why_now"],
        "preferred_cta_mode": drafts_payload.get("preferred_cta_mode"),
        "case_context": drafts_payload.get("case_context"),
        "topic_brief": topic_brief,
        "user_theme_verdict": drafts_payload["user_theme_verdict"],
        "style_references": drafts_payload["style_references"],
        "chosen_variant": best.variant,
        "final_score": best.score,
        "final_text": best.text,
        "critic_review": best.critic,
        "cta_explanation": explain_cta(best.text, best.cta_need),
        "editor_note": "Пост выбран как лучший вариант после генерации, полировки и критической проверки.",
    }
