from __future__ import annotations

import logging
import re

from .hybrid_llm import maybe_research_case_topics, maybe_verify_case
from .llm_client import llm_available
from .positioning import compute_flagship_fit, get_positioning_flags, infer_positioning_pillar, resolve_cta_strategy


CASE_TOPIC_OPTIONS = [
    "сокращение потерь через процессы",
    "системный turnaround после кризиса",
    "автоматизация и контроль качества",
    "кейсы, где системный подход дал рост эффективности",
    "оптимизация операционки без полной пересборки бизнеса",
    "рост прибыли через стандарты, контроль и управляемость",
]
LOGGER = logging.getLogger(__name__)
STRONG_SOURCE_HINTS = (
    ".gov",
    ".edu",
    ".org",
    "toyota.com",
    "walmart.com",
    "ikea.com",
    "zara.com",
    "inditex.com",
    "keaz.ru",
    "mit.edu",
    "lunduniversity",
    "hbr.org",
)
WEAK_SOURCE_HINTS = (
    "scribd.com",
    "wikipedia.org",
    "allfreepapers",
    "newasiagarment",
    "researchprospect",
    "leeshion",
)


def normalize_score(raw: object, default: int) -> int:
    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = default
    return max(0, min(100, value))


def normalize_list(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def normalize_sources(value: object) -> list[dict]:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return []
    cleaned: list[dict] = []
    for item in value:
        if isinstance(item, str):
            text = item.strip()
            if not text:
                continue
            url_match = re.search(r"https?://\\S+", text)
            url = url_match.group(0).rstrip(".,);]") if url_match else ""
            title = text.replace(url, "").strip(" -") if url else text
        elif isinstance(item, dict):
            title = str(item.get("title") or item.get("name") or item.get("source") or "").strip()
            url = str(item.get("url") or item.get("link") or item.get("href") or "").strip()
            if not url:
                combined = " ".join(
                    str(item.get(key) or "").strip()
                    for key in ("title", "name", "source", "url", "link", "href", "text")
                    if str(item.get(key) or "").strip()
                )
                url_match = re.search(r"https?://\\S+", combined)
                url = url_match.group(0).rstrip(".,);]") if url_match else ""
                if not title and combined:
                    title = combined.replace(url, "").strip(" -") if url else combined
        else:
            continue
        if not url:
            continue
        cleaned.append(
            {
                "title": title or url,
                "url": url,
            }
        )
    return cleaned


def extract_sources_from_item(item: dict) -> list[dict]:
    source_values: list[object] = []
    for key in ("sources", "source_urls", "references", "links"):
        value = item.get(key)
        if value:
            source_values.append(value)
    normalized: list[dict] = []
    for value in source_values:
        normalized.extend(normalize_sources(value))

    unique: list[dict] = []
    seen: set[str] = set()
    for source in normalized:
        url = source.get("url", "")
        if not url or url in seen:
            continue
        seen.add(url)
        unique.append(source)
    return unique


def score_source_quality(sources: list[dict]) -> tuple[int, list[dict]]:
    scored: list[tuple[int, dict]] = []
    for source in sources:
        url = (source.get("url") or "").lower()
        title = (source.get("title") or "").lower()
        score = 55
        if any(hint in url for hint in STRONG_SOURCE_HINTS):
            score += 25
        if url.endswith(".pdf"):
            score += 10
        if any(token in title for token in ("case", "study", "report", "review", "thesis", "research")):
            score += 5
        if any(hint in url for hint in WEAK_SOURCE_HINTS):
            score -= 25
        scored.append((max(0, min(100, score)), source))
    scored.sort(key=lambda item: item[0], reverse=True)
    avg = round(sum(item[0] for item in scored) / len(scored)) if scored else 0
    return avg, [item[1] for item in scored]


def first_nonempty_text(item: dict, keys: tuple[str, ...]) -> str:
    for key in keys:
        value = str(item.get(key) or "").strip()
        if value:
            return value
    return ""


def case_signature(item: dict) -> str:
    company = str(item.get("company") or "").strip().lower()
    title = str(item.get("case_title") or item.get("title") or "").strip().lower()
    return " | ".join(part for part in (company, title) if part)


def derive_case_topic_label(query: str, post_theme: str, post_angle: str, system_changes: list[str], outcomes: list[str]) -> str:
    haystack = " ".join([query, post_theme, post_angle, *system_changes, *outcomes]).lower().replace("ё", "е")
    query_norm = (query or "").lower().replace("ё", "е")
    if any(token in haystack for token in ("turnaround", "криз", "разворот", "перезапуск", "спас")):
        return "системный turnaround после кризиса"
    if any(token in haystack for token in ("tps", "lean", "kaizen", "smed", "heijunka", "производительност", "эффективност", "бережлив")):
        return "кейсы, где системный подход дал рост эффективности"
    if any(token in haystack for token in ("потер", "издерж", "сниж", "утеч", "эконом")) or any(token in query_norm for token in ("потер", "издерж", "процесс")):
        return "сокращение потерь через процессы"
    if any(token in haystack for token in ("учет", "инвентар", "склад", "запас", "working capital", "ритейл", "logist", "логист", "supply chain", "поставщик", "distribution", "распредел")):
        return "оптимизация операционки без полной пересборки бизнеса"
    if any(token in haystack for token in ("качеств", "стандарт", "контрол", "автомат", "монитор", "rfid", "цифров")):
        return "автоматизация и контроль качества"
    if any(token in haystack for token in ("прибыл", "маржин", "экономик")):
        return "рост прибыли через стандарты, контроль и управляемость"
    return "кейсы, где системный подход дал рост эффективности"


def suggest_related_case_queries(query: str) -> list[str]:
    normalized = (query or "").lower().replace("ё", "е")
    suggestions: list[str] = []
    if any(token in normalized for token in ("потер", "издерж", "процесс", "операцион")):
        suggestions.extend(
            [
                "сокращение потерь через процессы",
                "оптимизация операционки без полной пересборки бизнеса",
                "рост прибыли через стандарты, контроль и управляемость",
                "автоматизация и контроль качества",
                "кейсы, где системный подход дал рост эффективности",
            ]
        )
    elif any(token in normalized for token in ("криз", "turnaround", "перезапуск")):
        suggestions.extend(
            [
                "системный turnaround после кризиса",
                "кейсы, где системный подход дал рост эффективности",
                "автоматизация и контроль качества",
                "рост прибыли через стандарты, контроль и управляемость",
                "сокращение потерь через процессы",
            ]
        )
    elif any(token in normalized for token in ("автомат", "качеств", "контрол")):
        suggestions.extend(
            [
                "автоматизация и контроль качества",
                "сокращение потерь через процессы",
                "кейсы, где системный подход дал рост эффективности",
                "оптимизация операционки без полной пересборки бизнеса",
                "системный turnaround после кризиса",
            ]
        )
    else:
        suggestions.extend(CASE_TOPIC_OPTIONS)

    unique: list[str] = []
    for item in suggestions:
        if item not in unique:
            unique.append(item)
    return unique[:5]


def build_case_topic_suggestions(cases: list[dict]) -> list[dict]:
    ranked: dict[str, dict] = {}
    for item in cases:
        theme = str(item.get("post_theme") or "").strip()
        if not theme:
            continue
        score = int(item.get("score") or 0)
        candidate = {
            "theme": theme,
            "score": score,
            "useful_topic": item.get("useful_topic") or "",
            "angle": item.get("post_angle") or "",
            "why_now": item.get("why_fit") or "",
            "content_pillar": item.get("content_pillar") or "expert",
            "case_title": item.get("case_title") or "",
            "company": item.get("company") or "",
            "preferred_cta_mode": item.get("preferred_cta_mode"),
            "what_is_confirmed": item.get("what_is_confirmed") or [],
            "system_changes": item.get("system_changes") or [],
            "measurable_outcomes": item.get("measurable_outcomes") or [],
            "sources": item.get("sources") or [],
        }
        existing = ranked.get(theme)
        if existing is None or score > int(existing.get("score") or 0):
            ranked[theme] = candidate
    return sorted(ranked.values(), key=lambda item: item.get("score", 0), reverse=True)[:5]


def dedupe_cases(cases: list[dict], excluded: set[str], limit: int) -> list[dict]:
    unique: list[dict] = []
    seen: set[str] = set(excluded)
    for item in sorted(cases, key=lambda row: row.get("score", 0), reverse=True):
        signature = case_signature(item)
        if not signature or signature in seen:
            continue
        seen.add(signature)
        unique.append(item)
        if len(unique) >= limit:
            break
    return unique


def enrich_case(item: dict, query: str) -> tuple[dict | None, list[str]]:
    reasons: list[str] = []
    company = str(item.get("company") or "").strip()
    title = str(item.get("case_title") or item.get("title") or "").strip()
    timeframe = str(item.get("timeframe") or "").strip()
    what_broke = first_nonempty_text(item, ("what_broke", "problem", "what_changed", "summary"))
    system_changes = normalize_list(item.get("system_changes"))
    if not system_changes:
        system_changes = normalize_list(item.get("changes_made") or item.get("operational_changes") or item.get("actions_taken"))
    outcomes = normalize_list(item.get("measurable_outcomes") or item.get("outcomes"))
    if not outcomes:
        outcomes = normalize_list(item.get("results") or item.get("impact") or item.get("effect"))
    confirmed = normalize_list(item.get("what_is_confirmed") or item.get("confirmed_facts"))
    if not confirmed:
        confirmed = normalize_list(item.get("confirmed") or item.get("facts"))
    why_fit = first_nonempty_text(item, ("why_fit", "fit_reason", "why_relevant"))
    caution = str(item.get("caution") or item.get("limitations") or "").strip()
    post_theme = str(item.get("post_theme") or "").strip()
    post_angle = str(item.get("post_angle") or "").strip()
    content_pillar = infer_positioning_pillar(post_theme or title or query, item.get("content_pillar"))
    sources = extract_sources_from_item(item)
    source_quality_score, ranked_sources = score_source_quality(sources)
    sources = ranked_sources
    evidence_score = normalize_score(item.get("evidence_score"), 65)
    fit_score = normalize_score(item.get("positioning_fit_score"), 70)
    evidence_score = round((evidence_score * 0.7) + (source_quality_score * 0.3)) if sources else evidence_score
    flagship_fit = compute_flagship_fit(post_theme or title or query, post_angle, content_pillar)
    combined_score = min(
        99,
        round((fit_score * 0.45) + (evidence_score * 0.35) + (flagship_fit["score"] * 1.2)),
    )

    if not title:
        reasons.append("missing_title")
    if not post_theme:
        if title:
            post_theme = title
            reasons.append("fallback_post_theme_from_title")
        else:
            reasons.append("missing_post_theme")
    if not post_angle:
        if why_fit:
            post_angle = why_fit
            reasons.append("fallback_post_angle_from_fit_reason")
        elif system_changes:
            post_angle = f"показать, какие системные изменения дали эффект: {system_changes[0].lower()}"
            reasons.append("fallback_post_angle_from_system_changes")
        elif outcomes:
            post_angle = f"разобрать, как системные изменения привели к результату: {outcomes[0].lower()}"
            reasons.append("fallback_post_angle_from_outcomes")
        else:
            reasons.append("missing_post_angle")
    if len(sources) < 1:
        reasons.append("missing_sources")
    if not system_changes and not outcomes and not confirmed and not what_broke:
        reasons.append("missing_substance")
    if fit_score < 45:
        reasons.append(f"low_fit_score:{fit_score}")
    if evidence_score < 35:
        reasons.append(f"low_evidence_score:{evidence_score}")
    if "missing_title" in reasons or "missing_post_theme" in reasons or "missing_sources" in reasons or "missing_substance" in reasons:
        return None, reasons

    cta_strategy = resolve_cta_strategy(post_theme, content_pillar)
    preferred_cta_mode = "comments"
    if cta_strategy.get("preferred_cta_need") == "soft":
        preferred_cta_mode = "diagnostic"
    elif "personal" in set(cta_strategy.get("allowed_ctas") or []) and any(
        token in (post_theme.lower()) for token in ("оргструкт", "роль", "регламент", "процесс", "эффектив", "операцион")
    ):
        preferred_cta_mode = "personal"

    useful_topic = derive_case_topic_label(query, post_theme, post_angle, system_changes, outcomes)

    caution_notes = [caution] if caution else []
    if len(sources) == 1:
        caution_notes.append("источник пока только один, поэтому кейс лучше подавать осторожно")
    if source_quality_score and source_quality_score < 55:
        caution_notes.append("часть источников выглядит слабее, поэтому кейс лучше использовать как иллюстрацию, а не как жёсткий фактологический разбор")
    if fit_score < 60:
        caution_notes.append("позиционирование совпадает неидеально, поэтому угол лучше держать ближе к процессам, потерям и управляемости")
    if evidence_score < 45:
        caution_notes.append("доказательная база слабее обычного, поэтому лучше не перегружать кейс точными цифрами")

    return {
        "company": company,
        "case_title": title,
        "timeframe": timeframe,
        "what_broke": what_broke,
        "system_changes": system_changes[:4],
        "measurable_outcomes": outcomes[:4],
        "why_fit": why_fit or flagship_fit["reason"],
        "caution": " ".join(note for note in caution_notes if note).strip() or ("важно не превратить кейс в пересказ истории без связи с вашей методологией" if len(sources) > 1 else "источников пока немного, поэтому кейс лучше подавать осторожно и не перегружать точными цифрами"),
        "what_is_confirmed": (confirmed[:4] if confirmed else ([what_broke] if what_broke else [])),
        "post_theme": post_theme,
        "useful_topic": useful_topic,
        "post_angle": post_angle,
        "content_pillar": content_pillar,
        "evidence_score": evidence_score,
        "positioning_fit_score": fit_score,
        "score": combined_score,
        "sources": sources[:3],
        "preferred_cta_mode": preferred_cta_mode,
    }, reasons


def run_case_research_attempt(query: str, excluded: set[str]) -> tuple[list[dict], int]:
    payload = {
        "query": query,
        "positioning_flags": get_positioning_flags(),
        "exclude_signatures": sorted(excluded),
    }
    raw_cases = maybe_research_case_topics(payload) or []
    LOGGER.info("Case research raw response query=%r raw_cases=%s", query, len(raw_cases))
    cases: list[dict] = []
    for idx, item in enumerate(raw_cases, start=1):
        enriched, reasons = enrich_case(item, query)
        signature = case_signature(item) or str(item.get("case_title") or item.get("title") or item.get("company") or f"case_{idx}")
        if reasons:
            LOGGER.info("Case research candidate query=%r idx=%s signature=%r notes=%s", query, idx, signature, ", ".join(reasons))
        if enriched and case_signature(enriched) not in excluded:
            cases.append(enriched)
        elif enriched:
            LOGGER.info("Case research candidate excluded by history query=%r idx=%s signature=%r", query, idx, signature)
    return cases, len(raw_cases)


def research_case_topics(query: str, limit: int = 5, exclude_signatures: list[str] | None = None) -> dict:
    query = (query or "").strip()
    LOGGER.info("Case research requested query=%r limit=%s excluded=%s", query, limit, len(exclude_signatures or []))
    if not query:
        LOGGER.info("Case research aborted: empty query")
        return {
            "available": False,
            "reason": "empty_query",
            "cases": [],
            "related_queries": [],
        }
    if not llm_available():
        LOGGER.info("Case research unavailable: llm unavailable for query=%r", query)
        return {
            "available": False,
            "reason": "llm_unavailable",
            "cases": [],
            "related_queries": suggest_related_case_queries(query),
        }

    excluded = {item.strip().lower() for item in (exclude_signatures or []) if item}
    attempted_queries = [query]
    cases, raw_case_count = run_case_research_attempt(query, excluded)
    if not cases and raw_case_count > 0:
        for related_query in suggest_related_case_queries(query):
            if related_query == query:
                continue
            attempted_queries.append(related_query)
            fallback_cases, fallback_raw_count = run_case_research_attempt(related_query, excluded)
            if fallback_cases:
                cases.extend(fallback_cases)
                excluded.update(case_signature(item) for item in fallback_cases if case_signature(item))
            if fallback_raw_count == 0:
                LOGGER.info("Case research stopping fallback chain query=%r because related query=%r returned no raw cases", query, related_query)
                break
            if len(cases) >= limit:
                break

    cases = dedupe_cases(cases, {item.strip().lower() for item in (exclude_signatures or []) if item}, limit)
    expanded = len(attempted_queries) > 1
    LOGGER.info(
        "Case research finished query=%r passed_filter=%s returned=%s topic_suggestions=%s reason=%s attempts=%s",
        query,
        len(cases),
        len(cases[:limit]),
        len(build_case_topic_suggestions(cases[:limit])),
        "ok" if cases else "no_cases",
        attempted_queries,
    )
    return {
        "available": True,
        "query": query,
        "cases": cases[:limit],
        "topic_suggestions": build_case_topic_suggestions(cases[:limit]),
        "reason": "ok" if cases else "no_cases",
        "related_queries": suggest_related_case_queries(query),
        "attempted_queries": attempted_queries,
        "expanded_search": expanded,
    }


def verify_case(query: str) -> dict:
    query = (query or "").strip()
    LOGGER.info("Case verify requested query=%r", query)
    if not query:
        LOGGER.info("Case verify aborted: empty query")
        return {
            "available": False,
            "reason": "empty_query",
        }
    if not llm_available():
        LOGGER.info("Case verify unavailable: llm unavailable for query=%r", query)
        return {
            "available": False,
            "reason": "llm_unavailable",
        }

    payload = {
        "query": query,
        "positioning_flags": get_positioning_flags(),
    }
    raw = maybe_verify_case(payload)
    if not raw:
        LOGGER.info("Case verify no result query=%r", query)
        return {
            "available": True,
            "reason": "no_result",
            "query": query,
            "verdict": None,
        }

    theme = str(raw.get("post_theme") or "").strip()
    angle = str(raw.get("post_angle") or "").strip()
    fit_reason = str(raw.get("fit_reason") or "").strip()
    fit_verdict = str(raw.get("fit_verdict") or "").strip().lower()
    sources = normalize_sources(raw.get("sources"))
    confirmed = normalize_list(raw.get("what_is_confirmed"))
    unclear = normalize_list(raw.get("what_is_unclear_or_weak"))
    system_changes = normalize_list(raw.get("system_changes"))
    outcomes = normalize_list(raw.get("measurable_outcomes"))
    pillar = infer_positioning_pillar(theme or query, raw.get("content_pillar"))
    flagship_fit = compute_flagship_fit(theme or query, angle, pillar)
    fit_score = normalize_score(raw.get("positioning_fit_score"), 72)
    evidence_score = normalize_score(raw.get("evidence_score"), 68)
    score = min(
        99,
        round((fit_score * 0.45) + (evidence_score * 0.35) + (flagship_fit["score"] * 1.2)),
    )

    if len(sources) < 2 or not confirmed:
        fit_verdict = "skip"
        fit_reason = fit_reason or "кейс не прошёл по качеству факт-чекинга или не дал достаточно подтверждённых фактов"

    preferred_cta_mode = "comments"
    strategy = resolve_cta_strategy(theme or query, pillar)
    if strategy.get("preferred_cta_need") == "soft":
        preferred_cta_mode = "diagnostic"
    elif "personal" in set(strategy.get("allowed_ctas") or []) and any(
        token in (theme or query).lower() for token in ("оргструкт", "роль", "регламент", "процесс", "эффектив", "операцион")
    ):
        preferred_cta_mode = "personal"

    result = {
        "available": True,
        "reason": "ok",
        "query": query,
        "verdict": {
            "fit_verdict": fit_verdict or "caution",
            "fit_reason": fit_reason or flagship_fit["reason"],
            "score": score,
            "what_is_confirmed": confirmed[:5],
            "what_is_unclear_or_weak": unclear[:4],
            "system_changes": system_changes[:5],
            "measurable_outcomes": outcomes[:5],
            "post_theme": theme,
            "post_angle": angle,
            "content_pillar": pillar,
            "sources": sources[:4],
            "preferred_cta_mode": preferred_cta_mode,
        },
    }
    LOGGER.info(
        "Case verify finished query=%r verdict=%s score=%s sources=%s confirmed=%s",
        query,
        result["verdict"]["fit_verdict"],
        result["verdict"]["score"],
        len(sources),
        len(confirmed),
    )
    return result
