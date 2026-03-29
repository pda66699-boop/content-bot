from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from .config import POSTS_INDEX_PATH
from .backlog_memory import load_backlog
from .editorial_extractor import infer_editorial_metadata_from_topic
from .feed_coverage import analyze_feed_coverage, infer_angle_signature, recommend_content_plan_slot
from .editorial_metadata import normalize_editorial_metadata
from .editorial_similarity import classify_topic_novelty
from .hybrid_llm import maybe_generate_planner_candidates
from .open_loops import get_high_priority_open_loops
from .positioning import BALANCE_RANGES, CTA_BALANCE_RANGES, compute_flagship_fit, get_positioning_flags, resolve_cta_strategy


DEFAULT_BUSINESS_GOAL = "expert"

SYSTEM_PRIORITY_TOPICS = (
    "оргструктура и роли",
    "регламенты и процессы",
    "перегрузка собственника",
    "скрытые потери в операционке",
    "систематизация и управляемость",
    "работа с причинами, а не симптомами",
)

AI_TOPICS = (
    "ИИ как инструмент внутри системы",
    "ИИ и хаос в процессах",
    "применение ИИ по функциям бизнеса",
    "готовность бизнеса к ИИ",
    "признаки результативного ИИ",
    "ИИ без прикладной пользы",
    "диагностический бот по стадиям бизнеса",
)

AI_TOKENS_EXACT = {"ии", "ai", "gpt"}
AI_TOKENS_PREFIX = ("нейро",)

COST_OPTIMIZATION_TOKENS = (
    "дороже",
    "налог",
    "цены",
    "эконом",
    "оптимизац",
    "расход",
    "издерж",
    "марж",
    "себестоим",
)

CONTENT_PILLAR_TARGETS = {
    pillar: round((bounds["min"] + bounds["max"]) / 2, 2)
    for pillar, bounds in BALANCE_RANGES.items()
}

CONVERSATIONAL_THEME_TOKENS = (
    "мысл",
    "жизн",
    "свобод",
    "пауза",
    "отдых",
    "пересбор",
    "инсайт",
    "выбор",
    "сует",
    "отношение",
    "баланс",
)

MONEY_THEME_TOKENS = (
    "диагност",
    "бот",
    "стад",
    "кризис",
    "расход",
    "издерж",
    "потер",
    "прибыл",
    "деньг",
    "выруч",
    "результат",
    "кейс",
    "стабилизац",
)

MARKETING_RUBRIC_RANGES = {
    "case": {"min": 0.10, "max": 0.20},
    "mistake_breakdown": {"min": 0.10, "max": 0.20},
    "diagnostic_entry": {"min": 0.15, "max": 0.25},
    "reflective_observation": {"min": 0.10, "max": 0.20},
    "flagship_warmup": {"min": 0.10, "max": 0.20},
    "expert_explainer": {"min": 0.15, "max": 0.30},
}

RUBRIC_TARGETS = {
    rubric: round((bounds["min"] + bounds["max"]) / 2, 2)
    for rubric, bounds in MARKETING_RUBRIC_RANGES.items()
}

WEEKLY_PUBLISHING_CAP = 3

RANKING_COMPONENT_WEIGHTS = {
    "novelty": 1.8,
    "angle_freshness": 1.25,
    "funnel_fit": 0.8,
    "positioning": 0.55,
    "utility": 0.65,
    "conversion_relevance": 0.45,
    "slot_fit": 0.85,
    "continuity": 1.0,
}

NOVELTY_PENALTIES = {
    "too_close": 120,
    "reframe_allowed": 34,
    "series_without_continuity": 24,
    "window_repeat_boost": 12,
}


@dataclass
class TopicCandidate:
    theme: str
    angle: str
    score: int
    why_now: str
    content_role: str
    cta_need: str
    content_pillar: str
    marketing_rubric: str = ""
    funnel_stage: str = ""
    primary_thesis: str | None = None
    secondary_theses: list[str] | None = None
    business_dimensions: list[str] | None = None
    format_type: str = "expert"
    novelty_window_days: int = 30
    novelty_status: str = "fresh"
    reason: str = ""
    allowed_reframes: list[str] | None = None
    recommended_format: str = "expert"
    recommended_cta_type: str = "none"
    content_goal: str = "expert"
    novelty_score: int = 0
    angle_freshness_score: int = 0
    funnel_fit_score: int = 0
    positioning_score: int = 0
    utility_score: int = 0
    conversion_relevance_score: int = 0
    slot_fit_score: int = 0
    editorial_gate: str = "allowed"
    continuity_confirmed: bool = False
    continuity_evidence: list[str] | None = None
    matched_post_title_or_date: str | None = None
    matched_primary_thesis: str | None = None
    why_not_fresh: str | None = None
    continuity_component: int = 0
    novelty_penalty: int = 0
    repeat_penalty: int = 0
    total_penalty: int = 0


RECYCLED_ANGLES = (
    "зайти в тему через более прикладную управленческую сцену и довести её до одного ясного вывода",
    "вернуть тему через денежные последствия ошибки и показать, где именно бизнес теряет управляемость",
    "раскрыть тему через типичную ошибку собственника и системную причину, которую обычно не трогают",
    "подать тему через новую практическую ситуацию из бизнеса без повтора прежнего тезиса буквально",
)


RECYCLED_WHY_NOW = (
    "тема уже есть в контуре канала, но сейчас её можно вернуть через более прикладной и взрослый угол",
    "тема не новая для ленты, но её можно развернуть глубже и ближе к текущим болям собственника",
    "тема уже звучала, но сейчас уместно показать её не абстрактно, а через последствия для денег и управления",
    "тему можно безопасно вернуть в ленту, если обновить ракурс и не повторять старую формулировку",
)


def load_posts() -> list[dict]:
    if not POSTS_INDEX_PATH.exists():
        return []
    return [normalize_editorial_metadata(json.loads(line)) for line in POSTS_INDEX_PATH.read_text(encoding="utf-8").splitlines() if line.strip()]


def recent_rows_by_days(rows: list[dict], days: int) -> list[dict]:
    cutoff = date.today() - timedelta(days=max(days - 1, 0))
    selected: list[dict] = []
    for row in rows:
        raw_date = row.get("date")
        if not raw_date:
            continue
        try:
            row_date = date.fromisoformat(str(raw_date))
        except ValueError:
            continue
        if row_date >= cutoff:
            selected.append(row)
    return selected


def normalize_topic(text: str) -> str:
    lowered = text.lower().strip()
    lowered = lowered.replace("ё", "е")
    lowered = re.sub(r"[^a-zа-я0-9\s]+", " ", lowered)
    lowered = re.sub(r"\s+", " ", lowered)
    return lowered.strip()


def topic_overlap_score(topic_a: str, topic_b: str) -> float:
    a = set(normalize_topic(topic_a).split())
    b = set(normalize_topic(topic_b).split())
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def tokenize_topic(text: str) -> list[str]:
    return normalize_topic(text).split()


def contains_ai_signal(text: str) -> bool:
    tokens = tokenize_topic(text)
    return any(token in AI_TOKENS_EXACT for token in tokens) or any(
        token.startswith(AI_TOKENS_PREFIX) for token in tokens
    )


def build_cta_mode(topic: str, pillar: str, cta_need: str, campaign_mode: str) -> str:
    """Return a UI-friendly CTA type suggestion for a topic candidate."""

    strategy = resolve_cta_strategy(topic, pillar, campaign_mode)
    allowed = set(strategy.get("allowed_ctas") or [])
    if cta_need in {"soft", "hard"} and "diagnostic" in allowed:
        return "diagnostic"
    if cta_need == "optional" and "comment" in allowed:
        return "comments"
    if "personal" in allowed and any(token in topic.lower() for token in ("роль", "оргструкт", "процесс", "операцион")):
        return "personal"
    return "none"


def score_candidate_against_slot(candidate_metadata: dict, recommended_slot: dict) -> int:
    """Score how well candidate metadata fits the currently needed content-plan slot."""

    score = 0
    dimensions = set(candidate_metadata.get("business_dimensions") or [])
    if recommended_slot.get("target_business_dimension") in dimensions:
        score += 8
    if infer_angle_signature(candidate_metadata) == recommended_slot.get("target_angle_signature"):
        score += 7
    if (candidate_metadata.get("funnel_stage") or "") == recommended_slot.get("target_funnel_stage"):
        score += 7
    if (candidate_metadata.get("content_goal") or "") == recommended_slot.get("target_content_goal"):
        score += 6
    if (candidate_metadata.get("format_type") or "") == recommended_slot.get("target_format_type"):
        score += 5
    return score


def classify_post_pillar(row: dict) -> str:
    theme = normalize_topic(row.get("primary_theme") or row.get("title_hook") or "")
    role = (row.get("content_role") or "").lower()
    hashtags = [str(tag).lower() for tag in (row.get("hashtags") or [])]
    cta_present = bool(row.get("cta_present"))

    if "#мысли" in hashtags or any(token in theme for token in CONVERSATIONAL_THEME_TOKENS):
        return "conversational"
    if any(token in theme for token in MONEY_THEME_TOKENS):
        return "money"
    if cta_present and role in {"case", "applied"}:
        return "money"
    if role in {"image", "reflective", "personal", "conversation"}:
        return "conversational"
    return "expert"


def infer_candidate_pillar(theme: str, content_role: str, cta_need: str) -> str:
    normalized_theme = normalize_topic(theme)
    normalized_role = (content_role or "").lower()

    if any(token in normalized_theme for token in CONVERSATIONAL_THEME_TOKENS):
        return "conversational"
    if any(token in normalized_theme for token in MONEY_THEME_TOKENS):
        return "money"
    if normalized_role in {"image", "reflective", "personal", "conversation"}:
        return "conversational"
    if cta_need in {"soft", "hard"} and normalized_role in {"case", "applied", "diagnostic"}:
        return "money"
    return "expert"


def classify_post_rubric(row: dict) -> str:
    theme = normalize_topic(row.get("primary_theme") or row.get("title_hook") or "")
    role = (row.get("content_role") or "").lower()
    source = (row.get("source") or "").lower()
    if source == "case_research" or role == "case" or theme.startswith("кейс ") or theme.startswith("разбор кейса"):
        return "case"
    if any(token in theme for token in ("ошиб", "причин", "симптом")):
        return "mistake_breakdown"
    if any(token in theme for token in ("диагност", "стад", "кризис", "перекос")):
        return "diagnostic_entry"
    if role in {"image", "reflective", "personal", "conversation"} or any(token in theme for token in CONVERSATIONAL_THEME_TOKENS):
        return "reflective_observation"
    if any(token in theme for token in ("45 дней", "стабилизац", "потер", "контрол", "управляем")):
        return "flagship_warmup"
    return "expert_explainer"


def infer_candidate_rubric(theme: str, content_role: str, content_pillar: str, cta_need: str, source_kind: str | None = None) -> str:
    normalized_theme = normalize_topic(theme)
    normalized_role = (content_role or "").lower()
    if source_kind in {"verified_case", "case_research"} or normalized_role == "case" or normalized_theme.startswith("кейс ") or normalized_theme.startswith("разбор кейса"):
        return "case"
    if any(token in normalized_theme for token in ("ошиб", "причин", "симптом")):
        return "mistake_breakdown"
    if any(token in normalized_theme for token in ("диагност", "стад", "кризис", "перекос")) or cta_need in {"soft", "hard"} and content_pillar == "money":
        return "diagnostic_entry"
    if content_pillar == "conversational":
        return "reflective_observation"
    if any(token in normalized_theme for token in ("стабилизац", "потер", "контрол", "управляем", "процесс", "роль", "оргструкт")):
        return "flagship_warmup"
    return "expert_explainer"


def rubric_rebalance_bonus(rubric: str, feed_state: dict) -> int:
    need = feed_state.get("rubric_needs", {}).get(rubric, 0.0)
    if need >= 0.12:
        return 7
    if need >= 0.06:
        return 4
    if need <= -0.12:
        return -6
    if need <= -0.06:
        return -3
    return 0


def backlog_priority_score(theme: str, content_role: str, cta_need: str) -> int:
    pillar = infer_candidate_pillar(theme, content_role, cta_need)
    if pillar == "conversational":
        return 93
    if pillar == "money":
        return 89
    return 84


def backlog_priority_angle(theme: str, pillar: str, item: dict | None = None) -> str:
    context = (item or {}).get("context") or {}
    if context.get("post_angle"):
        return str(context.get("post_angle")).strip()
    if pillar == "conversational":
        return "взять личную авторскую тему из backlog и раскрыть её как живое наблюдение с понятным выводом, без потери управленческой глубины"
    if pillar == "money":
        return "взять тему из backlog и развернуть её через боль собственника, экономический перекос и практический следующий шаг"
    return "взять тему из backlog и раскрыть её через боль собственника, системную причину и практический вывод"


def backlog_priority_why_now(pillar: str, item: dict | None = None) -> str:
    context = (item or {}).get("context") or {}
    if context.get("fit_reason"):
        return f"это ваша сохранённая тема из кейса, и она уместна потому что {str(context.get('fit_reason')).strip()}"
    if pillar == "conversational":
        return "это ваша сохранённая жизненная тема, и сейчас она особенно уместна, потому что помогает добавить в ленту живой разговорный слой"
    if pillar == "money":
        return "это ваша сохранённая тема, и сейчас она уместна как авторский денежный разбор, который можно мягко довести до действия"
    return "это ваша сохранённая тема, поэтому ей стоит дать небольшой приоритет в контент-плане как авторской идее"


def pillar_rebalance_bonus(pillar: str, feed_state: dict) -> int:
    need = feed_state.get("pillar_needs", {}).get(pillar, 0.0)
    if need >= 0.15:
        return 12
    if need >= 0.08:
        return 7
    if need <= -0.15:
        return -10
    if need <= -0.08:
        return -5
    return 0


def campaign_score_bonus(candidate: TopicCandidate, campaign_mode: str) -> tuple[int, str | None]:
    normalized = normalize_topic(candidate.theme)
    if campaign_mode == "warmup":
        if candidate.content_pillar == "conversational":
            return 8, "сейчас идёт warmup-режим, и живая авторская тема особенно уместна"
        if candidate.content_pillar == "money":
            return -4, None
    if campaign_mode == "offer_push":
        fit = compute_flagship_fit(candidate.theme, candidate.angle, candidate.content_pillar)
        if fit["score"] >= 12:
            return 10, "тема хорошо стыкуется с текущим оффером и может вести ближе к флагману"
        if candidate.content_pillar == "conversational":
            return -3, None
    if campaign_mode == "diagnostics_push":
        if any(token in normalized for token in ("стад", "кризис", "диагност", "перекос")) or candidate.content_pillar == "money":
            return 9, "сейчас полезнее вести темы, которые логично подводят к диагностике"
        if candidate.content_pillar == "conversational":
            return -2, None
    return 0, None


def _dedupe_reason_fragments(text: str) -> str:
    """Collapse repeated semicolon-separated fragments in planner explanations."""

    normalized_text = text.replace(". ", "; ").replace("..", ".")
    parts = [part.strip(" .") for part in normalized_text.split(";") if part.strip(" .")]
    deduped: list[str] = []
    seen: set[str] = set()
    for part in parts:
        key = part.lower()
        if key in seen:
            continue
        deduped.append(part)
        seen.add(key)
    if not deduped:
        return ""

    normalized_parts: list[str] = []
    for index, part in enumerate(deduped):
        if index == 0:
            normalized_parts.append(part[:1].upper() + part[1:] if part else part)
        else:
            normalized_parts.append(part[:1].upper() + part[1:] if part else part)
    return ". ".join(normalized_parts) + "."


def enrich_candidate_with_balance(candidate: TopicCandidate, feed_state: dict, campaign_mode: str) -> TopicCandidate:
    pillar = candidate.content_pillar or infer_candidate_pillar(candidate.theme, candidate.content_role, candidate.cta_need)
    bonus = pillar_rebalance_bonus(pillar, feed_state)
    campaign_bonus, campaign_reason = campaign_score_bonus(candidate, campaign_mode)
    cta_strategy = resolve_cta_strategy(candidate.theme, pillar, campaign_mode)
    flagship_fit = compute_flagship_fit(candidate.theme, candidate.angle, pillar)
    rubric = candidate.marketing_rubric or infer_candidate_rubric(candidate.theme, candidate.content_role, pillar, candidate.cta_need)
    rubric_bonus = rubric_rebalance_bonus(rubric, feed_state)
    score = candidate.score + bonus + campaign_bonus + flagship_fit["score"] + rubric_bonus
    why_now = candidate.why_now
    if bonus > 0:
        pillar_labels = {
            "expert": "экспертный",
            "conversational": "разговорный",
            "money": "денежный",
        }
        why_now = f"{why_now}; сейчас ленте полезно добавить {pillar_labels.get(pillar, pillar)} слой"
    if campaign_reason:
        why_now = f"{why_now}; {campaign_reason}"
    if flagship_fit["score"] >= 10 and candidate.content_pillar != "conversational":
        why_now = f"{why_now}; тема хорошо поддерживает флагман «45 дней»"
    if rubric_bonus > 0:
        why_now = f"{why_now}; такого формата сейчас не хватает в ленте"
    why_now = _dedupe_reason_fragments(why_now)
    return TopicCandidate(
        theme=candidate.theme,
        angle=candidate.angle,
        score=score,
        why_now=why_now,
        content_role=candidate.content_role,
        cta_need=cta_strategy["preferred_cta_need"] if candidate.cta_need != "none" else "none",
        content_pillar=pillar,
        marketing_rubric=rubric,
        funnel_stage=cta_strategy.get("funnel_stage") or "",
        primary_thesis=candidate.primary_thesis,
        secondary_theses=candidate.secondary_theses,
        business_dimensions=candidate.business_dimensions,
        format_type=candidate.format_type,
        novelty_window_days=candidate.novelty_window_days,
        novelty_status=candidate.novelty_status,
        reason=candidate.reason,
        allowed_reframes=candidate.allowed_reframes,
        recommended_format=candidate.recommended_format,
        recommended_cta_type=candidate.recommended_cta_type,
        content_goal=candidate.content_goal,
        novelty_score=candidate.novelty_score,
        angle_freshness_score=candidate.angle_freshness_score,
        funnel_fit_score=candidate.funnel_fit_score,
        positioning_score=candidate.positioning_score,
        utility_score=candidate.utility_score,
        conversion_relevance_score=candidate.conversion_relevance_score,
        slot_fit_score=candidate.slot_fit_score,
        editorial_gate=candidate.editorial_gate,
        continuity_confirmed=candidate.continuity_confirmed,
        continuity_evidence=candidate.continuity_evidence,
        matched_post_title_or_date=candidate.matched_post_title_or_date,
        matched_primary_thesis=candidate.matched_primary_thesis,
        why_not_fresh=candidate.why_not_fresh,
        continuity_component=candidate.continuity_component,
        novelty_penalty=candidate.novelty_penalty,
        repeat_penalty=candidate.repeat_penalty,
        total_penalty=candidate.total_penalty,
    )


def _stage_need_score(stage: str, feed_state: dict) -> int:
    """Score how useful a funnel stage is right now for the content plan."""

    recent_counts = feed_state.get("weekly_stage_counts", {})
    if stage == "solution_aware" and recent_counts.get("solution_aware", 0) == 0:
        return 8
    if stage == "problem_aware" and recent_counts.get("problem_aware", 0) <= 1:
        return 6
    if stage in {"aware", "trust"} and recent_counts.get(stage, 0) == 0:
        return 5
    return 2


def _novelty_score_from_verdict(verdict: dict) -> int:
    """Convert novelty classification into a ranking contribution."""

    status = verdict.get("status")
    score = float(verdict.get("score") or 0.0)
    if status == "fresh":
        return max(10, 28 - int(score * 10))
    if status == "reframe_allowed":
        return 2
    if status == "series_continuation":
        return 5
    return -40


def _angle_freshness_score(verdict: dict) -> int:
    """Score whether the angle stays meaningfully fresh relative to neighbors."""

    best_match = verdict.get("best_match") or {}
    angle_score = float(best_match.get("angle_score") or 0.0)
    status = verdict.get("status")
    if status == "fresh":
        return 10
    if status == "series_continuation":
        return 6
    if status == "reframe_allowed":
        return max(2, 10 - int(angle_score * 12))
    return -8


def _positioning_score(candidate: TopicCandidate) -> int:
    """Score how well the topic fits the flagship positioning."""

    return compute_flagship_fit(candidate.theme, candidate.angle, candidate.content_pillar)["score"]


def _utility_score(candidate: TopicCandidate, feed_state: dict) -> int:
    """Score how useful the candidate is for balance and content planning."""

    pillar_need = feed_state.get("pillar_needs", {}).get(candidate.content_pillar, 0.0)
    rubric_need = feed_state.get("rubric_needs", {}).get(candidate.marketing_rubric or "", 0.0)
    score = 4
    if pillar_need > 0:
        score += int(round(pillar_need * 40))
    if rubric_need > 0:
        score += int(round(rubric_need * 25))
    return score


def _conversion_relevance_score(candidate: TopicCandidate, campaign_mode: str) -> int:
    """Score how relevant the topic is to conversion and current campaign mode."""

    strategy = resolve_cta_strategy(candidate.theme, candidate.content_pillar, campaign_mode)
    stage = strategy.get("funnel_stage") or candidate.funnel_stage
    if campaign_mode == "diagnostics_push" and stage in {"solution_aware", "problem_aware"}:
        return 10
    if campaign_mode == "offer_push" and stage in {"solution_aware", "solution_consideration"}:
        return 9
    if candidate.cta_need in {"soft", "hard"}:
        return 7
    return 3


def _continuity_component(candidate: TopicCandidate, continuity_confirmed: bool) -> int:
    """Return a small bonus for genuinely confirmed continuity cases."""

    if candidate.novelty_status == "series_continuation" and continuity_confirmed:
        return 8
    return 0


def _compute_penalties(novelty: dict, editorial_gate: str, continuity_confirmed: bool) -> tuple[int, int, int]:
    """Return novelty, repeat, and total penalties for final ranking."""

    status = novelty.get("status") or "fresh"
    best_match = novelty.get("best_match") or {}
    within_window = bool(best_match.get("within_novelty_window"))
    semantic_score = float(best_match.get("semantic_score") or 0.0)

    novelty_penalty = 0
    repeat_penalty = 0

    if status == "too_close" or editorial_gate == "disallowed":
        novelty_penalty += NOVELTY_PENALTIES["too_close"]
    elif status == "reframe_allowed" or editorial_gate == "reframe_only":
        novelty_penalty += NOVELTY_PENALTIES["reframe_allowed"]
    elif status == "series_continuation" and not continuity_confirmed:
        novelty_penalty += NOVELTY_PENALTIES["series_without_continuity"]

    if within_window and semantic_score >= 0.55:
        repeat_penalty += NOVELTY_PENALTIES["window_repeat_boost"] + int(round(semantic_score * 8))
    elif semantic_score >= 0.72:
        repeat_penalty += int(round(semantic_score * 6))

    return novelty_penalty, repeat_penalty, novelty_penalty + repeat_penalty


def _weighted_component(value: int, key: str) -> int:
    """Apply configured ranking weight to one planner component."""

    return int(round(value * RANKING_COMPONENT_WEIGHTS[key]))


def infer_planner_metadata(topic: str, context: dict | None = None) -> dict:
    """Return planner-safe editorial metadata using rules-only extraction.

    Planner novelty gating must stay stable and reproducible even when the global
    runtime enables hybrid LLM mode. We therefore force `prefer_llm=False` here
    and use the local heuristic extractor as the single source of truth for
    similarity, admissibility, and ranking penalties.
    """

    return infer_editorial_metadata_from_topic(topic, context=context, prefer_llm=False)


def enrich_candidate_with_semantics(
    candidate: TopicCandidate,
    archive: list[dict],
    feed_state: dict,
    campaign_mode: str,
    recommended_slot: dict | None = None,
    open_loops: list[dict] | None = None,
) -> TopicCandidate:
    """Attach editorial metadata and semantic novelty signals to a topic candidate."""

    metadata = infer_planner_metadata(
        candidate.theme,
        context={
            "angle": candidate.angle,
            "content_goal": candidate.content_role,
            "content_role": candidate.content_role,
            "funnel_stage": candidate.funnel_stage,
            "format_type": candidate.marketing_rubric or candidate.content_role,
            "business_dimensions": candidate.business_dimensions,
        },
    )
    candidate_archive_row = {
        "date": date.today().isoformat(),
        "title_hook": candidate.theme,
        "primary_theme": candidate.theme,
        **metadata,
    }
    novelty = classify_topic_novelty(candidate_archive_row, archive)
    best_match = novelty.get("best_match") or {}
    novelty_status = novelty.get("status") or "fresh"
    recommended_format = metadata.get("format_type") or "expert"
    recommended_cta_type = build_cta_mode(candidate.theme, candidate.content_pillar, candidate.cta_need, campaign_mode)
    novelty_score = _novelty_score_from_verdict(novelty)
    angle_score = _angle_freshness_score(novelty)
    funnel_score = _stage_need_score(metadata.get("funnel_stage") or candidate.funnel_stage, feed_state)
    positioning_score = _positioning_score(candidate)
    utility_score = _utility_score(candidate, feed_state)
    conversion_score = _conversion_relevance_score(candidate, campaign_mode)
    slot_fit_score = score_candidate_against_slot(metadata, recommended_slot or {})
    editorial_gate, continuity_confirmed, continuity_evidence = evaluate_editorial_gate(
        candidate,
        novelty,
        campaign_mode=campaign_mode,
        open_loops=open_loops or [],
    )
    continuity_component = _continuity_component(candidate, continuity_confirmed)
    novelty_penalty, repeat_penalty, total_penalty = _compute_penalties(novelty, editorial_gate, continuity_confirmed)

    why_not_fresh = build_why_not_fresh(novelty_status, best_match, continuity_confirmed, continuity_evidence)
    reason = build_reason_summary(
        novelty_status,
        editorial_gate,
        best_match,
        recommended_slot,
        continuity_confirmed,
        continuity_evidence,
    )

    weighted_novelty = _weighted_component(novelty_score, "novelty")
    weighted_angle = _weighted_component(angle_score, "angle_freshness")
    weighted_funnel = _weighted_component(funnel_score, "funnel_fit")
    weighted_positioning = _weighted_component(positioning_score, "positioning")
    weighted_utility = _weighted_component(utility_score, "utility")
    weighted_conversion = _weighted_component(conversion_score, "conversion_relevance")
    weighted_slot = _weighted_component(slot_fit_score, "slot_fit")
    weighted_continuity = _weighted_component(continuity_component, "continuity")

    score = (
        candidate.score
        + weighted_novelty
        + weighted_angle
        + weighted_funnel
        + weighted_positioning
        + weighted_utility
        + weighted_conversion
        + weighted_slot
        + weighted_continuity
        - total_penalty
    )
    score = apply_editorial_score_caps(score, novelty_status, editorial_gate, continuity_confirmed)

    return TopicCandidate(
        theme=candidate.theme,
        angle=candidate.angle,
        score=score,
        why_now=candidate.why_now,
        content_role=candidate.content_role,
        cta_need=candidate.cta_need,
        content_pillar=candidate.content_pillar,
        marketing_rubric=candidate.marketing_rubric,
        funnel_stage=metadata.get("funnel_stage") or candidate.funnel_stage,
        primary_thesis=metadata.get("primary_thesis"),
        secondary_theses=metadata.get("secondary_theses") or [],
        business_dimensions=metadata.get("business_dimensions") or [],
        format_type=metadata.get("format_type") or recommended_format,
        novelty_window_days=int(metadata.get("novelty_window_days") or 30),
        novelty_status=novelty_status,
        reason=reason,
        allowed_reframes=novelty.get("reframes") or [],
        recommended_format=recommended_format,
        recommended_cta_type=recommended_cta_type,
        content_goal=metadata.get("content_goal") or candidate.content_role,
        novelty_score=weighted_novelty,
        angle_freshness_score=weighted_angle,
        funnel_fit_score=weighted_funnel,
        positioning_score=weighted_positioning,
        utility_score=weighted_utility,
        conversion_relevance_score=weighted_conversion,
        slot_fit_score=weighted_slot,
        editorial_gate=editorial_gate,
        continuity_confirmed=continuity_confirmed,
        continuity_evidence=continuity_evidence,
        matched_post_title_or_date=matched_post_reference(best_match),
        matched_primary_thesis=best_match.get("primary_thesis"),
        why_not_fresh=why_not_fresh,
        continuity_component=weighted_continuity,
        novelty_penalty=novelty_penalty,
        repeat_penalty=repeat_penalty,
        total_penalty=total_penalty,
    )


def continuity_signals(candidate: TopicCandidate, open_loops: list[dict], campaign_mode: str) -> list[str]:
    """Return concrete continuity evidence for series-like topics."""

    evidence: list[str] = []
    normalized_theme = normalize_topic(candidate.theme)
    normalized_angle = normalize_topic(candidate.angle)
    normalized_why_now = normalize_topic(candidate.why_now)

    for loop in open_loops:
        loop_topic = normalize_topic(str(loop.get("open_loop_topic") or ""))
        if loop_topic and (topic_overlap_score(normalized_theme, loop_topic) >= 0.45 or loop_topic in normalized_theme):
            evidence.append(f"open_loop:{loop.get('date') or 'unknown'}")
            break

    if any(token in normalized_angle or token in normalized_why_now or token in normalized_theme for token in ("продолж", "серия", "часть", "обещан")):
        evidence.append("promised_continuation")

    if campaign_mode in {"offer_push", "diagnostics_push"} and candidate.marketing_rubric in {"flagship_warmup", "diagnostic_entry"}:
        evidence.append(f"campaign_{campaign_mode}")

    return evidence


def evaluate_editorial_gate(
    candidate: TopicCandidate,
    novelty: dict,
    *,
    campaign_mode: str,
    open_loops: list[dict],
) -> tuple[str, bool, list[str]]:
    """Return editorial admissibility, continuity confirmation, and evidence."""

    novelty_status = novelty.get("status") or "fresh"
    evidence = continuity_signals(candidate, open_loops, campaign_mode)
    continuity_confirmed = bool(evidence)

    if novelty_status == "too_close":
        return "disallowed", False, evidence
    if novelty_status == "reframe_allowed":
        return "reframe_only", False, evidence
    if novelty_status == "series_continuation":
        if continuity_confirmed:
            return "series_only", True, evidence
        return "reframe_only", False, evidence
    return "allowed", continuity_confirmed, evidence


def apply_editorial_score_caps(
    score: int,
    novelty_status: str,
    editorial_gate: str,
    continuity_confirmed: bool,
) -> int:
    """Clamp ranking score according to editorial admissibility rules."""

    if editorial_gate == "disallowed":
        return min(score, 0)
    if novelty_status == "reframe_allowed" or editorial_gate == "reframe_only":
        return min(score, 72)
    if novelty_status == "series_continuation":
        return min(score, 82 if continuity_confirmed else 70)
    return score


def humanize_editorial_admissibility(editorial_gate: str) -> str:
    """Return a user-facing editorial admissibility label."""

    mapping = {
        "allowed": "allowed",
        "reframe_only": "reframe_only",
        "series_only": "series_only",
        "disallowed": "disallowed",
    }
    return mapping.get(editorial_gate, editorial_gate or "allowed")


def matched_post_reference(best_match: dict) -> str | None:
    """Return a short human-readable reference to the closest matched post."""

    if not best_match:
        return None
    title = str(best_match.get("title_hook") or best_match.get("primary_theme") or "").strip()
    post_date = str(best_match.get("date") or "").strip()
    if title and post_date:
        return f"{post_date} — {title}"
    return title or post_date or None


def build_why_not_fresh(
    novelty_status: str,
    best_match: dict,
    continuity_confirmed: bool,
    continuity_evidence: list[str],
) -> str | None:
    """Explain why a candidate is not fresh when semantic novelty is limited."""

    if novelty_status == "reframe_allowed":
        return "Тема не fresh: главный тезис уже звучал в ленте, поэтому её можно брать только через новый угол или формат."
    if novelty_status == "too_close":
        return "Тема не fresh: рядом уже есть недавний пост с почти тем же тезисом и слишком близкой подачей."
    if novelty_status == "series_continuation":
        if continuity_confirmed:
            return f"Это не fresh-тема, а продолжение уже начатой линии. Continuity подтверждена: {', '.join(continuity_evidence[:2])}."
        return "Тема похожа на продолжение серии, но без подтверждённого continuity её нельзя считать обычной fresh-рекомендацией."
    return None


def build_reason_summary(
    novelty_status: str,
    editorial_gate: str,
    best_match: dict,
    recommended_slot: dict | None,
    continuity_confirmed: bool,
    continuity_evidence: list[str],
) -> str:
    """Build a readable planner explanation without exposing raw ranking internals."""

    if novelty_status == "fresh":
        slot_reason = (recommended_slot or {}).get("why_now")
        if slot_reason:
            return f"Тема считается новой по тезису и углу в текущем окне ленты и хорошо попадает в нужный слот: {slot_reason}."
        return "Тема считается новой по тезису и углу в текущем окне ленты."

    if novelty_status == "reframe_allowed":
        reference = matched_post_reference(best_match)
        if reference:
            return f"Тема не fresh: рядом уже есть близкая публикация ({reference}), поэтому её стоит брать только как reframe."
        return "Тема не fresh и допустима только как reframe."

    if novelty_status == "series_continuation":
        if continuity_confirmed:
            return f"Тема идёт как продолжение уже начатой линии. Continuity: {', '.join(continuity_evidence[:2])}."
        return "Тема выглядит как продолжение серии, но без подтверждённого continuity её лучше подавать только как reframe."

    if editorial_gate == "disallowed":
        return "Тема слишком близка к недавнему посту и не должна идти в рекомендации как следующая."

    return "Тема требует дополнительной редакторской проверки."


def gate_priority(candidate: TopicCandidate) -> int:
    """Return editorial-priority bucket for final planner ranking."""

    if (
        candidate.editorial_gate == "series_only"
        and candidate.continuity_confirmed
        and any(
            evidence.startswith("open_loop:") or evidence == "promised_continuation"
            for evidence in (candidate.continuity_evidence or [])
        )
    ):
        return 5
    if candidate.editorial_gate == "allowed" and candidate.novelty_status == "fresh":
        return 4
    if candidate.editorial_gate == "series_only" and candidate.continuity_confirmed:
        return 3
    if candidate.editorial_gate == "reframe_only":
        return 2
    if candidate.editorial_gate == "allowed":
        return 1
    return 0


def rank_admissible_candidates(candidates: list[TopicCandidate]) -> list[TopicCandidate]:
    """Apply editorial gate first, then rank only admissible candidates."""

    admissible = [candidate for candidate in candidates if candidate.editorial_gate != "disallowed"]
    admissible.sort(
        key=lambda candidate: (
            gate_priority(candidate),
            candidate.score,
            1 if candidate.novelty_status == "fresh" else 0,
            candidate.slot_fit_score,
            candidate.novelty_score,
        ),
        reverse=True,
    )
    return admissible


def apply_user_theme_verdict(candidate: TopicCandidate, user_verdict: dict) -> TopicCandidate:
    """Align enriched user-theme candidate with the earlier novelty verdict."""

    status = user_verdict.get("status")
    if status != "reframe":
        return candidate
    score = apply_editorial_score_caps(candidate.score, "reframe_allowed", "reframe_only", False)
    reason = "Пользовательская тема не считается fresh и допустима только как reframe с явным новым углом."
    novelty_penalty = max(candidate.novelty_penalty, NOVELTY_PENALTIES["reframe_allowed"])
    total_penalty = novelty_penalty + candidate.repeat_penalty
    return TopicCandidate(
        **{
            **candidate.__dict__,
            "score": score,
            "editorial_gate": "reframe_only",
            "reason": reason,
            "why_not_fresh": candidate.why_not_fresh or "Тема уже близка к недавней публикации по тезису, поэтому её нельзя подавать как fresh.",
            "matched_post_title_or_date": candidate.matched_post_title_or_date or user_verdict.get("matched_post_title_or_date"),
            "matched_primary_thesis": candidate.matched_primary_thesis or user_verdict.get("matched_primary_thesis"),
            "novelty_penalty": novelty_penalty,
            "total_penalty": total_penalty,
        }
    )


def build_feed_state(rows: list[dict]) -> dict:
    recent = rows[-12:]
    weekly = recent_rows_by_days(rows, 7) or rows[-7:]
    feedback_window = recent_rows_by_days(rows, 21) or rows[-21:]
    recent_topics = [row.get("primary_theme") for row in recent if row.get("primary_theme")]
    recent_roles = [row.get("content_role") for row in recent if row.get("content_role")]
    ai_recent = sum(int(row.get("mentions_ai", False)) for row in recent)
    cta_recent = sum(int(row.get("cta_present", False)) for row in recent)
    pillar_counts = Counter(classify_post_pillar(row) for row in recent)
    def normalize_cta_target(row: dict) -> str:
        if not row.get("cta_present"):
            return "none"
        target = (row.get("cta_target") or "").lower()
        if target in {"comments", "comment"}:
            return "comments"
        if target in {"diagnostic", "bot"}:
            return "diagnostic"
        if target in {"personal", "personal_dm"}:
            return "personal"
        lower_text = f"{row.get('body_text') or ''} {row.get('body_summary') or ''}".lower()
        if "комментар" in lower_text:
            return "comments"
        if "@pda33" in lower_text:
            return "personal"
        if "@adizesbizbot" in lower_text or "диагност" in lower_text or "бот" in lower_text:
            return "diagnostic"
        return "comments"

    cta_counts = Counter(normalize_cta_target(row) for row in recent)
    rubric_counts = Counter(classify_post_rubric(row) for row in recent)
    total = len(recent) or 1
    pillar_ratios = {pillar: pillar_counts.get(pillar, 0) / total for pillar in CONTENT_PILLAR_TARGETS}
    cta_ratios = {cta: cta_counts.get(cta, 0) / total for cta in CTA_BALANCE_RANGES}
    rubric_ratios = {rubric: rubric_counts.get(rubric, 0) / total for rubric in RUBRIC_TARGETS}
    pillar_needs: dict[str, float] = {}
    for pillar, bounds in BALANCE_RANGES.items():
        ratio = pillar_ratios.get(pillar, 0)
        if ratio < bounds["min"]:
            pillar_needs[pillar] = round(bounds["min"] - ratio, 3)
        elif ratio > bounds["max"]:
            pillar_needs[pillar] = round(bounds["max"] - ratio, 3)
        else:
            midpoint = CONTENT_PILLAR_TARGETS[pillar]
            pillar_needs[pillar] = round(midpoint - ratio, 3)
    cta_needs: dict[str, float] = {}
    for cta, bounds in CTA_BALANCE_RANGES.items():
        ratio = cta_ratios.get(cta, 0)
        if ratio < bounds["min"]:
            cta_needs[cta] = round(bounds["min"] - ratio, 3)
        elif ratio > bounds["max"]:
            cta_needs[cta] = round(bounds["max"] - ratio, 3)
        else:
            midpoint = round((bounds["min"] + bounds["max"]) / 2, 3)
            cta_needs[cta] = round(midpoint - ratio, 3)
    rubric_needs: dict[str, float] = {}
    for rubric, bounds in MARKETING_RUBRIC_RANGES.items():
        ratio = rubric_ratios.get(rubric, 0)
        if ratio < bounds["min"]:
            rubric_needs[rubric] = round(bounds["min"] - ratio, 3)
        elif ratio > bounds["max"]:
            rubric_needs[rubric] = round(bounds["max"] - ratio, 3)
        else:
            rubric_needs[rubric] = round(RUBRIC_TARGETS[rubric] - ratio, 3)

    weekly_stage_counts: Counter[str] = Counter()
    weekly_flagship_fit = {"warmup": 0, "diagnostic_entry": 0, "trust": 0}
    for row in weekly:
        theme = row.get("primary_theme") or row.get("title_hook") or ""
        pillar = classify_post_pillar(row)
        strategy = resolve_cta_strategy(theme, pillar)
        stage = strategy.get("funnel_stage") or "trust"
        weekly_stage_counts[stage] += 1
        cta_target = normalize_cta_target(row)
        if cta_target == "diagnostic":
            weekly_flagship_fit["diagnostic_entry"] += 1
        elif compute_flagship_fit(theme, row.get("title_hook") or "", pillar)["score"] >= 10:
            weekly_flagship_fit["warmup"] += 1
        else:
            weekly_flagship_fit["trust"] += 1

    feedback_pillar_counts = Counter(classify_post_pillar(row) for row in feedback_window)
    feedback_rubric_counts = Counter(classify_post_rubric(row) for row in feedback_window)
    feedback_cta_counts = Counter(normalize_cta_target(row) for row in feedback_window)
    feedback_stage_counts: Counter[str] = Counter()
    for row in feedback_window:
        theme = row.get("primary_theme") or row.get("title_hook") or ""
        pillar = classify_post_pillar(row)
        strategy = resolve_cta_strategy(theme, pillar)
        feedback_stage_counts[strategy.get("funnel_stage") or "trust"] += 1

    feedback_notes: list[str] = []
    if feedback_stage_counts.get("diagnostic_entry", 0) == 0:
        feedback_notes.append("в опубликованных постах почти нет явного входа в диагностику")
    if feedback_stage_counts.get("solution_consideration", 0) == 0 and weekly_flagship_fit.get("warmup", 0) == 0:
        feedback_notes.append("прогрев к флагману в реальных публикациях пока слабый")
    if feedback_pillar_counts.get("conversational", 0) == 0:
        feedback_notes.append("разговорный слой в реально опубликованных постах почти не используется")

    published_last_7_days = len(weekly)
    weekly_slots_left = max(0, WEEKLY_PUBLISHING_CAP - published_last_7_days)

    return {
        "recent_window_size": len(recent),
        "recent_topics": recent_topics,
        "recent_roles": recent_roles,
        "ai_recent_count": ai_recent,
        "cta_recent_count": cta_recent,
        "last_post_theme": recent[-1].get("primary_theme") if recent else None,
        "last_post_title": recent[-1].get("title_hook") if recent else None,
        "pillar_counts": dict(pillar_counts),
        "pillar_ratios": pillar_ratios,
        "pillar_needs": pillar_needs,
        "pillar_ranges": BALANCE_RANGES,
        "cta_counts": dict(cta_counts),
        "cta_ratios": cta_ratios,
        "cta_needs": cta_needs,
        "cta_ranges": CTA_BALANCE_RANGES,
        "rubric_counts": dict(rubric_counts),
        "rubric_ratios": rubric_ratios,
        "rubric_needs": rubric_needs,
        "rubric_ranges": MARKETING_RUBRIC_RANGES,
        "weekly_stage_counts": dict(weekly_stage_counts),
        "weekly_offer_balance": weekly_flagship_fit,
        "published_last_7_days": published_last_7_days,
        "weekly_cap": WEEKLY_PUBLISHING_CAP,
        "weekly_slots_left": weekly_slots_left,
        "feedback_window_size": len(feedback_window),
        "feedback_pillar_counts": dict(feedback_pillar_counts),
        "feedback_rubric_counts": dict(feedback_rubric_counts),
        "feedback_cta_counts": dict(feedback_cta_counts),
        "feedback_stage_counts": dict(feedback_stage_counts),
        "feedback_notes": feedback_notes,
    }


def build_recycled_candidate(row: dict, score: int, index: int) -> TopicCandidate:
    theme = row.get("primary_theme") or row.get("title_hook") or "архивная тема"
    content_role = row.get("content_role") or "expert"
    title_hook = (row.get("title_hook") or "").strip()
    date = row.get("date")

    angle = RECYCLED_ANGLES[index % len(RECYCLED_ANGLES)]
    why_now = RECYCLED_WHY_NOW[index % len(RECYCLED_WHY_NOW)]

    normalized_theme = normalize_topic(theme)
    if "роль" in normalized_theme or "оргструкт" in normalized_theme:
        angle = "вернуть тему через зависимость команды от собственника, размытые роли и отсутствие границ решений"
        why_now = "тема снова уместна, если подать её через управляемость и реальную перегрузку собственника"
    elif "регламент" in normalized_theme or "процесс" in normalized_theme:
        angle = "зайти через разрыв между описанным процессом и реальным владельцем результата"
        why_now = "тему полезно вернуть, потому что она хорошо продолжает разговор не про бумагу, а про работающий порядок"
    elif "сотруд" in normalized_theme or "команд" in normalized_theme or "найм" in normalized_theme:
        angle = "подать тему через управленческую ошибку в работе с людьми, а не через претензию к самим сотрудникам"
        why_now = "тему можно вернуть как более зрелый разбор причин проблем с командой, а не только их симптомов"
    elif "врем" in normalized_theme or "перегруз" in normalized_theme:
        angle = "раскрыть тему через цену ручного режима собственника и то, почему свободное время не появляется само"
        why_now = "эта тема снова своевременна, если связать её не с лайфстайлом, а с архитектурой управления"
    elif "страх" in normalized_theme or "системат" in normalized_theme:
        angle = "разобрать, что именно пугает собственника в систематизации и где он путает порядок с бюрократией"
        why_now = "тему стоит вернуть, потому что она помогает снять внутреннее сопротивление перед изменением модели управления"

    if title_hook and len(title_hook) <= 120:
        why_now = f"{why_now}; раньше тема заходила через хук '{title_hook.lower()}'"
    elif date:
        why_now = f"{why_now}; в архиве уже есть опора от {date}"

    return TopicCandidate(
        theme=theme,
        angle=angle,
        score=score,
        why_now=why_now,
        content_role=content_role,
        cta_need="optional",
        content_pillar=infer_candidate_pillar(theme, content_role, "optional"),
    )


def compute_recycled_score(row: dict, recycled_index: int) -> int:
    base = 78 - recycled_index * 4
    row_date = row.get("date")
    if row_date:
        try:
            delta_days = (date.today() - date.fromisoformat(row_date)).days
        except ValueError:
            delta_days = 365
        if delta_days <= 60:
            base += 6
        elif delta_days <= 180:
            base += 3
        elif delta_days >= 365:
            base -= 4
    return max(58, min(84, base))


def pick_default_candidates(feed_state: dict, rows: list[dict], exclude_topics: set[str] | None = None) -> list[TopicCandidate]:
    candidates: list[TopicCandidate] = []
    recent_topics = set(feed_state["recent_topics"])
    exclude_topics = {normalize_topic(topic) for topic in (exclude_topics or set()) if topic}
    ai_recent_count = feed_state["ai_recent_count"]
    open_loops = get_high_priority_open_loops()
    backlog_topics = load_backlog()
    campaign_mode = get_positioning_flags().get("campaign_mode", "base")

    for loop in open_loops[:2]:
        topic = loop.get("open_loop_topic")
        if not topic or topic in recent_topics or normalize_topic(topic) in exclude_topics:
            continue
        candidates.append(
            TopicCandidate(
                theme=topic,
                angle=loop.get("recommended_follow_up") or "аккуратно закрыть обещанное продолжение темы без повтора старого поста",
                score=94 if loop.get("priority") == "high" else 82,
                why_now=f"в ленте есть открытый крючок от {loop.get('date')}, который стоит закрыть содержательно",
                content_role="applied",
                cta_need="optional",
                content_pillar=infer_candidate_pillar(topic, "applied", "optional"),
            )
        )

    for item in backlog_topics:
        topic = item.get("theme")
        if not topic or normalize_topic(topic) in exclude_topics or topic in recent_topics:
            continue
        desired_pillar = item.get("desired_pillar")
        pillar = desired_pillar or infer_candidate_pillar(topic, "expert", "optional")
        content_role = "image" if pillar == "conversational" else ("diagnostic" if pillar == "money" else "expert")
        candidates.append(
            TopicCandidate(
                theme=topic,
                angle=backlog_priority_angle(topic, pillar, item),
                score=backlog_priority_score(topic, content_role, "optional"),
                why_now=backlog_priority_why_now(pillar, item),
                content_role=content_role,
                cta_need="optional",
                content_pillar=pillar,
                marketing_rubric=infer_candidate_rubric(topic, content_role, pillar, "optional", (item.get("context") or {}).get("source_kind") or item.get("source")),
            )
        )

    if ai_recent_count >= 4:
        candidates.extend(
            [
                TopicCandidate(
                    theme="оргструктура и роли",
                    angle="показать, почему даже сильная команда остается зависимой от собственника без описанных ролей",
                    score=92,
                    why_now="в последних постах было много ИИ, поэтому ленту полезно вернуть к архитектуре управления",
                    content_role="applied",
                    cta_need="optional",
                    content_pillar="expert",
                ),
                TopicCandidate(
                    theme="работа с причинами, а не симптомами",
                    angle="развернуть мысль через типичную управленческую ошибку: меняют людей или инструмент, не трогая модель управления",
                    score=89,
                    why_now="эта тема продолжает мартовский пост, но позволяет зайти глубже в системную причину",
                    content_role="diagnostic",
                    cta_need="optional",
                    content_pillar="expert",
                ),
                TopicCandidate(
                    theme="скрытые потери в операционке",
                    angle="показать, как ручные согласования и разрывы между функциями съедают деньги без строки расходов",
                    score=84,
                    why_now="логично продолжает тему издержек и уводит фокус из ИИ в управляемость",
                    content_role="diagnostic",
                    cta_need="soft",
                    content_pillar="money",
                ),
            ]
        )

    for topic in SYSTEM_PRIORITY_TOPICS:
        if topic not in recent_topics and normalize_topic(topic) not in exclude_topics and len(candidates) < 7:
            candidates.append(
                TopicCandidate(
                    theme=topic,
                    angle="дать свежий угол без повтора последних формулировок",
                    score=70,
                    why_now="тема входит в системное ядро канала и сейчас не перегрета в последних постах",
                    content_role="expert",
                    cta_need="optional",
                    content_pillar="expert",
                )
            )

    if feed_state.get("pillar_needs", {}).get("conversational", 0) > 0.08:
        candidates.extend(
            [
                TopicCandidate(
                    theme="отношение к работе",
                    angle="зайти через личное наблюдение о работе, инерции и выборе, а потом мягко связать это с управляемостью жизни и бизнеса",
                    score=79,
                    why_now="в ленте не хватает живого разговорного слоя, который делает позицию автора человечнее и объёмнее",
                    content_role="image",
                    cta_need="optional",
                    content_pillar="conversational",
                ),
                TopicCandidate(
                    theme="свободное время собственника",
                    angle="развернуть тему не про лайфстайл, а про цену отсутствия пауз и право собственника жить, а не только держать всё на себе",
                    score=77,
                    why_now="сейчас полезно добавить разговорный пост, который связывает жизнь собственника и качество управления без ухода в абстракцию",
                    content_role="image",
                    cta_need="optional",
                    content_pillar="conversational",
                ),
            ]
        )

    if feed_state.get("pillar_needs", {}).get("money", 0) > 0.08:
        candidates.extend(
            [
                TopicCandidate(
                    theme="диагностика стадии бизнеса",
                    angle="показать, как стадия бизнеса помогает быстрее увидеть главный перекос, деньги на утечках и куда владельцу смотреть в первую очередь",
                    score=83,
                    why_now="денежный слой в ленте просел, и сейчас полезно вернуть тему, которая естественно ведёт к диагностике без жёсткого прогрева",
                    content_role="diagnostic",
                    cta_need="soft",
                    content_pillar="money",
                ),
                TopicCandidate(
                    theme="скрытые потери в операционке",
                    angle="разобрать, как деньги теряются не в расходах на поверхности, а в переделках, разрывах между функциями и ручном режиме",
                    score=81,
                    why_now="в ленте сейчас уместен денежный разбор, который показывает экономику бардака и логично подводит к действию",
                    content_role="diagnostic",
                    cta_need="soft",
                    content_pillar="money",
                ),
            ]
        )

    deduped: list[TopicCandidate] = []
    seen = set()
    balanced_candidates = [enrich_candidate_with_balance(candidate, feed_state, campaign_mode) for candidate in candidates]
    for candidate in sorted(balanced_candidates, key=lambda item: item.score, reverse=True):
        if candidate.theme in seen or normalize_topic(candidate.theme) in exclude_topics:
            continue
        deduped.append(candidate)
        seen.add(candidate.theme)
    if len(deduped) < 5:
        seen_norm = {normalize_topic(item.theme) for item in deduped}
        recycled_index = 0
        for row in reversed(rows):
            theme = row.get("primary_theme")
            if not theme:
                continue
            normalized_theme = normalize_topic(theme)
            if normalized_theme in seen_norm or normalized_theme in exclude_topics or theme in recent_topics:
                continue
            if ai_recent_count >= 4 and row.get("mentions_ai"):
                continue
            recycled = build_recycled_candidate(row, score=compute_recycled_score(row, recycled_index), index=recycled_index)
            deduped.append(enrich_candidate_with_balance(recycled, feed_state, campaign_mode))
            recycled_index += 1
            seen_norm.add(normalized_theme)
            if len(deduped) >= 5:
                break

    deduped.sort(key=lambda item: item.score, reverse=True)
    return deduped[:5]


def evaluate_user_theme(user_theme: str, rows: list[dict], feed_state: dict) -> dict:
    normalized_user_theme = normalize_topic(user_theme)
    campaign_mode = get_positioning_flags().get("campaign_mode", "base")
    open_loops = get_high_priority_open_loops()

    if any(token in normalized_user_theme for token in COST_OPTIMIZATION_TOKENS):
        return {
            "status": "take_now",
            "original_theme": user_theme,
            "recommended_angle": "показать, почему в период роста налогов, цен и себестоимости экономия начинается не с хаотичных сокращений, а с поиска системных потерь",
            "repeat_risk": "low",
            "comment": "тема максимально рыночная и приземлённая, хорошо попадает в текущий контекст и естественно усиливает денежный слой ленты",
        }

    if contains_ai_signal(normalized_user_theme) and feed_state["ai_recent_count"] >= 4:
        return {
            "status": "reframe",
            "original_theme": user_theme,
            "recommended_angle": "сместить фокус с ИИ на архитектуру, роли, процессы или управленческую причину, а ИИ оставить инструментом",
            "repeat_risk": "high",
            "comment": "сама тема может быть полезной, но в текущем окне ленты ИИ уже звучал слишком часто; лучше подать ее через системную рамку",
        }

    novelty = classify_topic_novelty(
        {
            "date": date.today().isoformat(),
            "title_hook": user_theme,
            "primary_theme": user_theme,
            **infer_planner_metadata(user_theme),
        },
        rows,
    )
    best_row = novelty.get("best_match") or {}
    novelty_status = novelty.get("status")
    gate_candidate = TopicCandidate(
        theme=user_theme,
        angle=(novelty.get("reframes") or ["подать тему через другой угол и практическое следствие"])[0],
        score=0,
        why_now="",
        content_role="diagnostic",
        cta_need="optional",
        content_pillar=infer_candidate_pillar(user_theme, "diagnostic", "optional"),
    )
    editorial_gate, continuity_confirmed, continuity_evidence = evaluate_editorial_gate(
        gate_candidate,
        novelty,
        campaign_mode=campaign_mode,
        open_loops=open_loops,
    )

    if novelty_status == "too_close" and best_row:
        return {
            "status": "reframe",
            "original_theme": user_theme,
            "recommended_angle": (novelty.get("reframes") or [f"зайти через новый угол относительно темы '{best_row.get('primary_theme')}' и не повторять прежний тезис дословно"])[0],
            "repeat_risk": "high",
            "comment": novelty.get("explanation") or f"тема заметно пересекается с недавним постом от {best_row.get('date')}; лучше изменить ракурс, формат или timing",
            "matched_post_title_or_date": matched_post_reference(best_row),
            "matched_primary_thesis": best_row.get("primary_thesis"),
        }

    if novelty_status == "reframe_allowed":
        return {
            "status": "reframe",
            "original_theme": user_theme,
            "recommended_angle": (novelty.get("reframes") or ["оставить тему, но усилить её через конкретную управленческую сцену и системную причину"])[0],
            "repeat_risk": "medium",
            "comment": (novelty.get("explanation") or "тезис уже звучал, поэтому тему лучше брать только как reframe с новым углом") + " Показывать её как обычную fresh-тему нельзя.",
            "matched_post_title_or_date": matched_post_reference(best_row),
            "matched_primary_thesis": best_row.get("primary_thesis"),
        }

    if novelty_status == "series_continuation":
        if not continuity_confirmed:
            return {
                "status": "reframe",
                "original_theme": user_theme,
                "recommended_angle": (novelty.get("reframes") or ["оставить тему, но усилить её через конкретную управленческую сцену и системную причину"])[0],
                "repeat_risk": "medium",
                "comment": (novelty.get("explanation") or "тема похожа на продолжение серии") + " Но continuity сейчас не подтверждена, поэтому тему лучше подавать только как reframe.",
                "matched_post_title_or_date": matched_post_reference(best_row),
                "matched_primary_thesis": best_row.get("primary_thesis"),
            }
        return {
            "status": "take_now",
            "original_theme": user_theme,
            "recommended_angle": (novelty.get("reframes") or ["оставить тему, но усилить её через конкретную управленческую сцену и системную причину"])[0],
            "repeat_risk": "medium",
            "comment": (novelty.get("explanation") or "тема пересекается с лентой, но не дублирует её буквально; можно брать сейчас при хорошем угле подачи") + f" Continuity подтверждена: {', '.join(continuity_evidence[:2])}.",
            "matched_post_title_or_date": matched_post_reference(best_row),
            "matched_primary_thesis": best_row.get("primary_thesis"),
        }

    return {
        "status": "take_now",
        "original_theme": user_theme,
        "recommended_angle": "подать тему через боль собственника, системную причину и 1 практический вывод",
        "repeat_risk": "low",
        "comment": "тема выглядит свежей для текущего окна ленты и может быть взята сразу",
    }


def build_user_theme_candidate(user_verdict: dict) -> TopicCandidate | None:
    if user_verdict["status"] == "later":
        return None
    return TopicCandidate(
        theme=user_verdict["original_theme"],
        angle=user_verdict["recommended_angle"],
        score=95 if user_verdict["status"] == "take_now" else 83,
        why_now=user_verdict["comment"],
        content_role="diagnostic",
        cta_need="optional",
        content_pillar=infer_candidate_pillar(user_verdict["original_theme"], "diagnostic", "optional"),
    )


def merge_llm_candidates(
    llm_candidates: list[dict] | None,
    existing_candidates: list[TopicCandidate],
    feed_state: dict,
    avoid_now: list[str],
    exclude_topics: list[str] | None,
    archive: list[dict],
    recommended_slot: dict | None = None,
) -> list[TopicCandidate]:
    if not llm_candidates:
        return existing_candidates
    campaign_mode = get_positioning_flags().get("campaign_mode", "base")

    merged: list[TopicCandidate] = []
    seen = {normalize_topic(item.theme) for item in existing_candidates}
    avoid_norm = {normalize_topic(item) for item in avoid_now}
    exclude_norm = {normalize_topic(item) for item in (exclude_topics or [])}

    for item in llm_candidates:
        theme = (item.get("theme") or "").strip()
        if not theme:
            continue
        normalized = normalize_topic(theme)
        if normalized in seen or normalized in avoid_norm or normalized in exclude_norm:
            continue
        if feed_state["ai_recent_count"] >= 4 and contains_ai_signal(normalized):
            continue
        merged.append(
            TopicCandidate(
                theme=theme,
                angle=(item.get("angle") or "подать тему через боль собственника, системную причину и 1 практический вывод").strip(),
                score=int(item.get("score", 78)),
                why_now=(item.get("why_now") or "тему стоит взять сейчас как свежий следующий шаг для ленты").strip(),
                content_role=(item.get("content_role") or "expert").strip(),
                cta_need=(item.get("cta_need") or "optional").strip(),
                content_pillar=(item.get("content_pillar") or infer_candidate_pillar(theme, item.get("content_role") or "expert", item.get("cta_need") or "optional")).strip(),
                marketing_rubric=(item.get("marketing_rubric") or infer_candidate_rubric(theme, item.get("content_role") or "expert", item.get("content_pillar") or "expert", item.get("cta_need") or "optional")).strip(),
                primary_thesis=item.get("primary_thesis"),
                secondary_theses=item.get("secondary_theses") or [],
                business_dimensions=item.get("business_dimensions") or [],
                format_type=item.get("recommended_format") or item.get("format_type") or "expert",
                novelty_status=item.get("novelty_status") or "fresh",
                reason=item.get("reason") or "",
                allowed_reframes=item.get("allowed_reframes") or [],
                recommended_format=item.get("recommended_format") or item.get("format_type") or "expert",
                recommended_cta_type=item.get("recommended_cta_type") or "none",
                content_goal=item.get("content_goal") or item.get("content_role") or "expert",
            )
        )
        seen.add(normalized)

    semantic_candidates = [
        enrich_candidate_with_semantics(candidate, archive, feed_state, campaign_mode, recommended_slot=recommended_slot, open_loops=get_high_priority_open_loops())
        for candidate in (merged + existing_candidates)
    ]
    combined = rank_admissible_candidates(
        [enrich_candidate_with_balance(candidate, feed_state, campaign_mode) for candidate in semantic_candidates]
    )
    deduped: list[TopicCandidate] = []
    dedup_seen: set[str] = set()
    for candidate in combined:
        normalized = normalize_topic(candidate.theme)
        if normalized in dedup_seen:
            continue
        deduped.append(candidate)
        dedup_seen.add(normalized)
    return deduped[:5]


def plan_next_topics(
    user_theme: str | None = None,
    business_goal: str = DEFAULT_BUSINESS_GOAL,
    exclude_topics: list[str] | None = None,
    rows_override: list[dict] | None = None,
) -> dict:
    rows = [normalize_editorial_metadata(row) for row in (rows_override if rows_override is not None else load_posts())]
    feed_state = build_feed_state(rows)
    feed_coverage = analyze_feed_coverage(rows, window_size=18)
    recent_topics_counter = Counter(feed_state["recent_topics"])
    avoid_now = [topic for topic, count in recent_topics_counter.items() if count >= 2]
    open_loops = get_high_priority_open_loops()
    positioning_flags = get_positioning_flags()
    campaign_mode = positioning_flags.get("campaign_mode", "base")
    recommended_slot = recommend_content_plan_slot(feed_coverage, campaign_mode=campaign_mode)

    best_next_topics = pick_default_candidates(feed_state, rows, exclude_topics=set(exclude_topics or []))
    best_next_topics = [
        enrich_candidate_with_balance(
            enrich_candidate_with_semantics(candidate, rows, feed_state, campaign_mode, recommended_slot=recommended_slot, open_loops=open_loops),
            feed_state,
            campaign_mode,
        )
        for candidate in best_next_topics
    ]
    best_next_topics = rank_admissible_candidates(best_next_topics)
    user_verdict = {
        "status": "none",
        "original_theme": None,
        "recommended_angle": None,
        "repeat_risk": None,
        "comment": "Пользовательская тема не передана.",
    }

    if user_theme:
        user_verdict = evaluate_user_theme(user_theme, rows, feed_state)
        user_candidate = build_user_theme_candidate(user_verdict)
        if user_candidate is not None:
            enriched_user_candidate = enrich_candidate_with_balance(
                enrich_candidate_with_semantics(
                    user_candidate,
                    rows,
                    feed_state,
                    campaign_mode,
                    recommended_slot=recommended_slot,
                    open_loops=open_loops,
                ),
                feed_state,
                campaign_mode,
            )
            if enriched_user_candidate.novelty_status == "reframe_allowed" and user_verdict.get("status") == "take_now":
                user_verdict = {
                    "status": "reframe",
                    "original_theme": user_theme,
                    "recommended_angle": (enriched_user_candidate.allowed_reframes or [enriched_user_candidate.angle])[0],
                    "repeat_risk": "medium",
                    "comment": "Тема не fresh: в итоговом planner ranking она допустима только как reframe.",
                    "matched_post_title_or_date": enriched_user_candidate.matched_post_title_or_date,
                    "matched_primary_thesis": enriched_user_candidate.matched_primary_thesis,
                }
            if enriched_user_candidate.novelty_status == "series_continuation" and not enriched_user_candidate.continuity_confirmed:
                user_verdict = {
                    "status": "reframe",
                    "original_theme": user_theme,
                    "recommended_angle": (enriched_user_candidate.allowed_reframes or [enriched_user_candidate.angle])[0],
                    "repeat_risk": "medium",
                    "comment": "Тема похожа на продолжение серии, но без подтверждённого continuity её лучше брать только как reframe.",
                    "matched_post_title_or_date": enriched_user_candidate.matched_post_title_or_date,
                    "matched_primary_thesis": enriched_user_candidate.matched_primary_thesis,
                }
            enriched_user_candidate = apply_user_theme_verdict(enriched_user_candidate, user_verdict)
            best_next_topics = rank_admissible_candidates(
                [enriched_user_candidate] + [topic for topic in best_next_topics if topic.theme != user_candidate.theme]
            )[:5]

    current_feed_state = (
        f"Последние {feed_state['recent_window_size']} постов содержат {feed_state['ai_recent_count']} ИИ-постов "
        f"и {feed_state['cta_recent_count']} постов с CTA. "
        f"Баланс режимов: экспертный {feed_state['pillar_counts'].get('expert', 0)}, "
        f"разговорный {feed_state['pillar_counts'].get('conversational', 0)}, "
        f"денежный {feed_state['pillar_counts'].get('money', 0)}. "
        f"Последняя тема: {feed_state['last_post_theme'] or 'не определена'}. "
        f"Режим кампании: {campaign_mode}."
    )

    llm_candidates = maybe_generate_planner_candidates(
        {
            "business_goal": business_goal,
            "current_feed_state": current_feed_state,
            "recent_topics_closed": feed_state["recent_topics"][-5:],
            "avoid_now": avoid_now,
            "open_loops": open_loops[:5],
            "campaign_mode": campaign_mode,
            "recommended_slot": recommended_slot,
            "flagship_offer": positioning_flags.get("flagship_offer"),
            "content_balance_ranges": positioning_flags.get("content_balance_ranges"),
            "cta_matrix_overview": positioning_flags.get("cta_matrix_overview"),
            "best_next_topics": [
                {
                    "theme": item.theme,
                    "primary_thesis": item.primary_thesis,
                    "angle": item.angle,
                    "score": item.score,
                    "why_now": item.why_now,
                    "content_role": item.content_role,
                    "content_goal": item.content_goal,
                    "cta_need": item.cta_need,
                    "content_pillar": item.content_pillar,
                    "marketing_rubric": item.marketing_rubric,
                    "funnel_stage": item.funnel_stage,
                    "business_dimensions": item.business_dimensions,
                    "novelty_status": item.novelty_status,
                    "editorial_gate": item.editorial_gate,
                    "continuity_confirmed": item.continuity_confirmed,
                    "reason": item.reason,
                    "allowed_reframes": item.allowed_reframes,
                    "recommended_format": item.recommended_format,
                    "recommended_cta_type": item.recommended_cta_type,
                }
                for item in best_next_topics
            ],
            "user_theme_verdict": user_verdict,
        }
    )
    best_next_topics = merge_llm_candidates(
        llm_candidates,
        best_next_topics,
        feed_state,
        avoid_now,
        exclude_topics,
        archive=rows,
        recommended_slot=recommended_slot,
    )

    recommended_topic = best_next_topics[0] if best_next_topics else None
    slots_left = feed_state.get("weekly_slots_left", WEEKLY_PUBLISHING_CAP)
    weekly_plan_candidates = best_next_topics[:slots_left] if slots_left > 0 else []
    return {
        "business_goal": business_goal,
        "positioning_flags": positioning_flags,
        "current_feed_state": current_feed_state,
        "feed_coverage": feed_coverage,
        "recommended_slot": recommended_slot,
        "recent_topics_closed": feed_state["recent_topics"][-5:],
        "open_loops": open_loops[:5],
        "content_balance": {
            "targets": CONTENT_PILLAR_TARGETS,
            "ranges": BALANCE_RANGES,
            "recent_counts": feed_state["pillar_counts"],
            "recent_ratios": feed_state["pillar_ratios"],
            "needs": feed_state["pillar_needs"],
        },
        "cta_balance": {
            "ranges": CTA_BALANCE_RANGES,
            "recent_counts": feed_state["cta_counts"],
            "recent_ratios": feed_state["cta_ratios"],
            "needs": feed_state["cta_needs"],
        },
        "rubric_balance": {
            "ranges": MARKETING_RUBRIC_RANGES,
            "recent_counts": feed_state["rubric_counts"],
            "recent_ratios": feed_state["rubric_ratios"],
            "needs": feed_state["rubric_needs"],
        },
        "weekly_funnel": {
            "stage_counts": feed_state["weekly_stage_counts"],
            "offer_balance": feed_state["weekly_offer_balance"],
        },
        "publishing_cadence": {
            "weekly_cap": feed_state["weekly_cap"],
            "published_last_7_days": feed_state["published_last_7_days"],
            "weekly_slots_left": feed_state["weekly_slots_left"],
        },
        "publication_feedback": {
            "window_size": feed_state["feedback_window_size"],
            "pillar_counts": feed_state["feedback_pillar_counts"],
            "rubric_counts": feed_state["feedback_rubric_counts"],
            "cta_counts": feed_state["feedback_cta_counts"],
            "stage_counts": feed_state["feedback_stage_counts"],
            "notes": feed_state["feedback_notes"],
        },
        "weekly_plan": [
            {
                "theme": item.theme,
                "primary_thesis": item.primary_thesis,
                "secondary_theses": item.secondary_theses,
                "content_pillar": item.content_pillar,
                "marketing_rubric": item.marketing_rubric,
                "funnel_stage": item.funnel_stage,
                "why_now": item.why_now,
                "recommended_slot": recommended_slot,
                "angle": item.angle,
                "content_goal": item.content_goal,
                "business_dimensions": item.business_dimensions,
                "novelty_status": item.novelty_status,
                "editorial_admissibility": humanize_editorial_admissibility(item.editorial_gate),
                "editorial_gate": item.editorial_gate,
                "continuity_confirmed": item.continuity_confirmed,
                "continuity_evidence": item.continuity_evidence,
                "matched_post_title_or_date": item.matched_post_title_or_date,
                "matched_primary_thesis": item.matched_primary_thesis,
                "why_not_fresh": item.why_not_fresh,
                "reason": item.reason,
                "allowed_reframes": item.allowed_reframes,
                "recommended_format": item.recommended_format,
                "recommended_cta_type": item.recommended_cta_type,
                "slot_fit_score": item.slot_fit_score,
                "score_breakdown": {
                    "novelty_component": item.novelty_score,
                    "angle_freshness_component": item.angle_freshness_score,
                    "funnel_fit_component": item.funnel_fit_score,
                    "positioning_component": item.positioning_score,
                    "utility_component": item.utility_score,
                    "conversion_relevance_component": item.conversion_relevance_score,
                    "continuity_component": item.continuity_component,
                    "slot_fit_component": item.slot_fit_score,
                    "penalties": {
                        "novelty_penalty": item.novelty_penalty,
                        "repeat_penalty": item.repeat_penalty,
                        "total_penalty": item.total_penalty,
                    },
                },
            }
            for item in weekly_plan_candidates
        ],
        "avoid_now": avoid_now,
        "best_next_topics": [
            {
                "theme": item.theme,
                "primary_thesis": item.primary_thesis,
                "secondary_theses": item.secondary_theses,
                "angle": item.angle,
                "score": item.score,
                "why_now": item.why_now,
                "content_role": item.content_role,
                "content_goal": item.content_goal,
                "cta_need": item.cta_need,
                "content_pillar": item.content_pillar,
                "marketing_rubric": item.marketing_rubric,
                "funnel_stage": item.funnel_stage,
                "business_dimensions": item.business_dimensions,
                "novelty_status": item.novelty_status,
                "editorial_admissibility": humanize_editorial_admissibility(item.editorial_gate),
                "editorial_gate": item.editorial_gate,
                "continuity_confirmed": item.continuity_confirmed,
                "continuity_evidence": item.continuity_evidence,
                "matched_post_title_or_date": item.matched_post_title_or_date,
                "matched_primary_thesis": item.matched_primary_thesis,
                "why_not_fresh": item.why_not_fresh,
                "reason": item.reason or item.why_now,
                "allowed_reframes": item.allowed_reframes,
                "recommended_format": item.recommended_format,
                "recommended_cta_type": item.recommended_cta_type,
                "novelty_score": item.novelty_score,
                "angle_freshness_score": item.angle_freshness_score,
                "funnel_fit_score": item.funnel_fit_score,
                "positioning_score": item.positioning_score,
                "utility_score": item.utility_score,
                "conversion_relevance_score": item.conversion_relevance_score,
                "continuity_component": item.continuity_component,
                "slot_fit_score": item.slot_fit_score,
                "novelty_penalty": item.novelty_penalty,
                "repeat_penalty": item.repeat_penalty,
                "total_penalty": item.total_penalty,
                "score_breakdown": {
                    "novelty_component": item.novelty_score,
                    "angle_freshness_component": item.angle_freshness_score,
                    "funnel_fit_component": item.funnel_fit_score,
                    "positioning_component": item.positioning_score,
                    "utility_component": item.utility_score,
                    "conversion_relevance_component": item.conversion_relevance_score,
                    "continuity_component": item.continuity_component,
                    "slot_fit_component": item.slot_fit_score,
                    "penalties": {
                        "novelty_penalty": item.novelty_penalty,
                        "repeat_penalty": item.repeat_penalty,
                        "total_penalty": item.total_penalty,
                    },
                },
            }
            for item in best_next_topics
        ],
        "recommended_topic_now": None
        if recommended_topic is None
        else {
            "topic": recommended_topic.theme,
            "theme": recommended_topic.theme,
            "primary_thesis": recommended_topic.primary_thesis,
            "secondary_theses": recommended_topic.secondary_theses,
            "angle": recommended_topic.angle,
            "why_now": recommended_topic.why_now,
            "content_role": recommended_topic.content_role,
            "content_goal": recommended_topic.content_goal,
            "cta_need": recommended_topic.cta_need,
            "content_pillar": recommended_topic.content_pillar,
            "marketing_rubric": recommended_topic.marketing_rubric,
            "funnel_stage": recommended_topic.funnel_stage,
            "business_dimensions": recommended_topic.business_dimensions,
            "novelty_status": recommended_topic.novelty_status,
            "editorial_admissibility": humanize_editorial_admissibility(recommended_topic.editorial_gate),
            "editorial_gate": recommended_topic.editorial_gate,
            "continuity_confirmed": recommended_topic.continuity_confirmed,
            "continuity_evidence": recommended_topic.continuity_evidence,
            "matched_post_title_or_date": recommended_topic.matched_post_title_or_date,
            "matched_primary_thesis": recommended_topic.matched_primary_thesis,
            "why_not_fresh": recommended_topic.why_not_fresh,
            "reason": recommended_topic.reason or recommended_topic.why_now,
            "allowed_reframes": recommended_topic.allowed_reframes,
            "recommended_format": recommended_topic.recommended_format,
            "recommended_cta_type": recommended_topic.recommended_cta_type,
            "score_breakdown": {
                "novelty_component": recommended_topic.novelty_score,
                "angle_freshness_component": recommended_topic.angle_freshness_score,
                "funnel_fit_component": recommended_topic.funnel_fit_score,
                "positioning_component": recommended_topic.positioning_score,
                "utility_component": recommended_topic.utility_score,
                "conversion_relevance_component": recommended_topic.conversion_relevance_score,
                "continuity_component": recommended_topic.continuity_component,
                "slot_fit_component": recommended_topic.slot_fit_score,
                "penalties": {
                    "novelty_penalty": recommended_topic.novelty_penalty,
                    "repeat_penalty": recommended_topic.repeat_penalty,
                    "total_penalty": recommended_topic.total_penalty,
                },
            },
            "recommended_slot": recommended_slot,
        },
        "why_now": None if recommended_topic is None else recommended_topic.why_now,
        "topic": None if recommended_topic is None else recommended_topic.theme,
        "novelty_status": None if recommended_topic is None else recommended_topic.novelty_status,
        "recommended_angle": None if recommended_topic is None else recommended_topic.angle,
        "recommended_format": None if recommended_topic is None else recommended_topic.recommended_format,
        "recommended_cta_type": None if recommended_topic is None else recommended_topic.recommended_cta_type,
        "cta_need": None if recommended_topic is None else recommended_topic.cta_need,
        "user_theme_verdict": user_verdict,
    }
