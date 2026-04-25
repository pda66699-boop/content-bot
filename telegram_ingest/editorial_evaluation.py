from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

from .critic_engine import critic_review_with_rows
from .editorial_extractor import infer_editorial_metadata_from_post, infer_editorial_metadata_from_topic
from .editorial_metadata import normalize_editorial_metadata
from .editorial_similarity import classify_topic_novelty, find_semantic_neighbors
from .memory_sync import load_posts_index
from .planner_engine import (
    TopicCandidate,
    build_feed_state,
    enrich_candidate_with_balance,
    enrich_candidate_with_semantics,
    gate_priority,
    humanize_editorial_admissibility,
    infer_planner_metadata,
    infer_candidate_pillar,
    infer_candidate_rubric,
    plan_next_topics,
    rank_admissible_candidates,
)
from .narrative_engine import infer_narrative_role
from .feed_coverage import analyze_feed_coverage, recommend_content_plan_slot
from .open_loops import get_high_priority_open_loops
from .positioning import get_positioning_flags


REVIEW_FIELDS = (
    "primary_thesis",
    "secondary_theses",
    "angle",
    "content_goal",
    "funnel_stage",
    "business_dimensions",
    "format_type",
    "novelty_window_days",
)
DEFAULT_MATCH_LIMIT = 3


def _normalize_scalar(value: Any) -> str:
    """Return a stable normalized string for debug output and comparisons."""

    if value is None:
        return ""
    return " ".join(str(value).lower().replace("ё", "е").split())


def _normalize_categorical(value: Any) -> str:
    """Return a normalized categorical slug tolerant to hyphen/underscore variance."""

    return _normalize_scalar(value).replace("-", "_").replace(" ", "_")


def _normalize_list(value: Any) -> list[str]:
    """Return a normalized list of strings for set-like comparisons."""

    if value is None:
        return []
    if isinstance(value, str):
        items = [value]
    elif isinstance(value, (list, tuple, set)):
        items = list(value)
    else:
        items = [value]
    normalized = [_normalize_scalar(item) for item in items if _normalize_scalar(item)]
    return sorted(dict.fromkeys(normalized))


def _load_archive(archive: list[dict] | None = None) -> list[dict]:
    """Return the provided archive or load the normalized JSONL archive."""

    if archive is not None:
        return [normalize_editorial_metadata(row) for row in archive]
    return load_posts_index()


def _candidate_from_metadata(label: str, metadata: dict, kind: str) -> dict:
    """Build a candidate card for semantic comparison from extracted metadata."""

    return {
        "date": date.today().isoformat(),
        "title_hook": label,
        "primary_theme": label,
        "body_summary": metadata.get("primary_thesis") or label,
        "content_role": metadata.get("content_goal"),
        "format": metadata.get("format_type"),
        **normalize_editorial_metadata(metadata),
        "source_kind": kind,
    }


def _summarize_match(row: dict) -> dict:
    """Return a compact semantic-neighbor record for debug output."""

    return {
        "post_id": row.get("post_id"),
        "date": row.get("date"),
        "title_hook": row.get("title_hook"),
        "primary_theme": row.get("primary_theme"),
        "primary_thesis": row.get("primary_thesis"),
        "angle": row.get("angle"),
        "funnel_stage": row.get("funnel_stage"),
        "format_type": row.get("format_type"),
        "novelty_status": row.get("novelty_status"),
        "semantic_score": row.get("semantic_score"),
        "within_novelty_window": row.get("within_novelty_window"),
        "age_days": row.get("age_days"),
    }


def _semantic_review(candidate: dict, archive: list[dict], limit: int = DEFAULT_MATCH_LIMIT) -> dict:
    """Return novelty status, explanation, and compact matched posts for a candidate."""

    verdict = classify_topic_novelty(candidate, archive)
    neighbors = find_semantic_neighbors(candidate, archive, limit=limit)
    return {
        "novelty_status": verdict.get("status") or "fresh",
        "reason": verdict.get("explanation"),
        "allowed_reframes": verdict.get("reframes") or [],
        "matched_posts": [_summarize_match(row) for row in neighbors],
        "best_match": _summarize_match(verdict["best_match"]) if verdict.get("best_match") else None,
    }


def build_extractor_review_for_post(
    card: dict,
    archive: list[dict] | None = None,
    prefer_llm: bool = False,
) -> dict:
    """Return extractor debug output for one post card, including novelty context."""

    rows = _load_archive(archive)
    metadata = infer_editorial_metadata_from_post(card, prefer_llm=prefer_llm)
    label = str(card.get("title_hook") or card.get("primary_theme") or "post").strip()
    candidate = _candidate_from_metadata(label, metadata, kind="post")
    semantic = _semantic_review(candidate, rows)
    return {
        "kind": "post",
        "label": label,
        **{field: metadata.get(field) for field in REVIEW_FIELDS},
        **semantic,
    }


def build_extractor_review_for_topic(
    topic: str,
    context: dict | None = None,
    archive: list[dict] | None = None,
    prefer_llm: bool = False,
) -> dict:
    """Return extractor debug output for one topic string, including novelty context."""

    rows = _load_archive(archive)
    metadata = infer_editorial_metadata_from_topic(topic, context=context, prefer_llm=prefer_llm)
    candidate = _candidate_from_metadata(topic, metadata, kind="topic")
    semantic = _semantic_review(candidate, rows)
    return {
        "kind": "topic",
        "label": topic,
        **{field: metadata.get(field) for field in REVIEW_FIELDS},
        **semantic,
    }


def build_critic_review_debug(
    text: str,
    archive: list[dict] | None = None,
    prefer_llm: bool = False,
) -> dict:
    """Return critic diagnostics enriched with extractor and novelty debug fields."""

    rows = _load_archive(archive)
    first_line = next((line.strip() for line in text.splitlines() if line.strip()), text[:120].strip() or "draft")
    metadata = infer_editorial_metadata_from_post(
        {
            "title_hook": first_line,
            "primary_theme": first_line,
            "body_text": text,
            "body_summary": text[:280],
        },
        prefer_llm=prefer_llm,
    )
    candidate = _candidate_from_metadata(first_line, metadata, kind="critic")
    semantic = _semantic_review(candidate, rows[-20:] if rows else rows)
    review = critic_review_with_rows(text, rows=rows)
    return {
        **review,
        "label": first_line,
        **{field: metadata.get(field) for field in REVIEW_FIELDS},
        **semantic,
    }


def build_planner_review(
    user_theme: str | None = None,
    business_goal: str = "expert",
    exclude_topics: list[str] | None = None,
    archive: list[dict] | None = None,
) -> dict:
    """Return planner output with compact semantic debug data for top candidates."""

    rows = _load_archive(archive)
    plan = plan_next_topics(
        user_theme=user_theme,
        business_goal=business_goal,
        exclude_topics=exclude_topics,
        rows_override=rows,
    )
    reviewed_candidates: list[dict] = []
    for item in plan.get("best_next_topics", [])[:5]:
        topic = item.get("theme") or item.get("topic") or ""
        if not topic:
            continue
        candidate = _candidate_from_metadata(topic, item, kind="planner")
        semantic = _semantic_review(candidate, rows)
        reviewed_candidates.append(
            {
                "theme": topic,
                "primary_thesis": item.get("primary_thesis"),
                "secondary_theses": item.get("secondary_theses") or [],
                "angle": item.get("angle"),
                "content_goal": item.get("content_goal"),
                "funnel_stage": item.get("funnel_stage"),
                "business_dimensions": item.get("business_dimensions") or [],
                "recommended_format": item.get("recommended_format"),
                "recommended_cta_type": item.get("recommended_cta_type"),
                "novelty_status": item.get("novelty_status") or semantic["novelty_status"],
                "reason": item.get("reason") or semantic["reason"],
                "allowed_reframes": item.get("allowed_reframes") or semantic["allowed_reframes"],
                "matched_posts": semantic["matched_posts"],
            }
        )

    recommended = plan.get("recommended_topic_now") or {}
    recommended_debug = None
    if recommended:
        recommended_debug = next(
            (item for item in reviewed_candidates if item.get("theme") == recommended.get("theme")),
            None,
        )

    return {
        "recommended_slot": plan.get("recommended_slot"),
        "why_now": plan.get("why_now"),
        "topic": plan.get("topic"),
        "novelty_status": plan.get("novelty_status"),
        "recommended_angle": plan.get("recommended_angle"),
        "recommended_format": plan.get("recommended_format"),
        "recommended_cta_type": plan.get("recommended_cta_type"),
        "reason": (recommended_debug or {}).get("reason") or (recommended.get("reason") if isinstance(recommended, dict) else None),
        "matched_posts": (recommended_debug or {}).get("matched_posts") or [],
        "primary_thesis": recommended.get("primary_thesis") if isinstance(recommended, dict) else None,
        "secondary_theses": recommended.get("secondary_theses") if isinstance(recommended, dict) else None,
        "content_goal": recommended.get("content_goal") if isinstance(recommended, dict) else None,
        "funnel_stage": recommended.get("funnel_stage") if isinstance(recommended, dict) else None,
        "format_type": recommended.get("recommended_format") if isinstance(recommended, dict) else None,
        "business_dimensions": recommended.get("business_dimensions") if isinstance(recommended, dict) else None,
        "top_candidates": reviewed_candidates,
    }


def _build_manual_topic_candidate(topic: str) -> TopicCandidate:
    """Build a baseline planner candidate for manual batch evaluation of one topic."""

    metadata = infer_planner_metadata(topic)
    content_goal = metadata.get("content_goal") or "expert"
    pillar = infer_candidate_pillar(topic, content_goal, "optional")
    rubric = infer_candidate_rubric(topic, content_goal, pillar, "optional")
    # Manual batch review compares topics semantically; use a theme-only narrative role
    # so synthetic planner defaults do not mark every candidate as a forbidden "solution".
    narrative_role = infer_narrative_role(
        theme=topic,
        angle="",
        content_role=content_goal,
        content_pillar=pillar,
        marketing_rubric="",
        strategic_format="",
        cta_need="optional",
    )
    return TopicCandidate(
        theme=topic,
        angle=metadata.get("angle") or "подать тему через системную причину и один практический вывод",
        score=70,
        why_now="тема добавлена в ручной evaluation batch для редакторской калибровки",
        content_role=content_goal,
        cta_need="optional",
        content_pillar=pillar,
        marketing_rubric=rubric,
        funnel_stage=metadata.get("funnel_stage") or "",
        primary_thesis=metadata.get("primary_thesis"),
        secondary_theses=metadata.get("secondary_theses") or [],
        business_dimensions=metadata.get("business_dimensions") or [],
        format_type=metadata.get("format_type") or "expert",
        content_goal=content_goal,
        narrative_role=narrative_role,
    )


def _serialize_planner_candidate(candidate: TopicCandidate, archive: list[dict]) -> dict:
    """Convert one ranked planner candidate into debug-friendly review output."""

    semantic = _semantic_review(candidate.__dict__, archive)
    return {
        "theme": candidate.theme,
        "primary_thesis": candidate.primary_thesis,
        "secondary_theses": candidate.secondary_theses or [],
        "angle": candidate.angle,
        "content_goal": candidate.content_goal,
        "funnel_stage": candidate.funnel_stage,
        "business_dimensions": candidate.business_dimensions or [],
        "novelty_status": candidate.novelty_status,
        "editorial_admissibility": humanize_editorial_admissibility(candidate.editorial_gate),
        "continuity_confirmed": candidate.continuity_confirmed,
        "continuity_evidence": candidate.continuity_evidence or [],
        "matched_posts": semantic["matched_posts"],
        "matched_post_title_or_date": candidate.matched_post_title_or_date,
        "matched_primary_thesis": candidate.matched_primary_thesis,
        "why_not_fresh": candidate.why_not_fresh,
        "reason": candidate.reason,
        "allowed_reframes": candidate.allowed_reframes or [],
        "recommended_format": candidate.recommended_format,
        "recommended_cta_type": candidate.recommended_cta_type,
        "score": candidate.score,
        "score_breakdown": {
            "novelty_component": candidate.novelty_score,
            "angle_freshness_component": candidate.angle_freshness_score,
            "funnel_fit_component": candidate.funnel_fit_score,
            "positioning_component": candidate.positioning_score,
            "utility_component": candidate.utility_score,
            "conversion_relevance_component": candidate.conversion_relevance_score,
            "continuity_component": candidate.continuity_component,
            "slot_fit_component": candidate.slot_fit_score,
            "penalties": {
                "novelty_penalty": candidate.novelty_penalty,
                "repeat_penalty": candidate.repeat_penalty,
                "total_penalty": candidate.total_penalty,
            },
        },
    }


def build_planner_batch_review(
    topics: list[str],
    *,
    archive: list[dict] | None = None,
    business_goal: str = "expert",
) -> dict:
    """Rank a manual batch of candidate topics and expose full semantic planner diagnostics."""

    rows = _load_archive(archive)
    cleaned_topics = [str(topic).strip() for topic in topics if str(topic).strip()]
    feed_coverage = analyze_feed_coverage(rows, window_size=18)
    campaign_mode = get_positioning_flags().get("campaign_mode", "base")
    recommended_slot = recommend_content_plan_slot(feed_coverage, campaign_mode=campaign_mode)
    open_loops = get_high_priority_open_loops()
    current_feed_state = build_feed_state(rows)
    candidates = [
        enrich_candidate_with_balance(
            enrich_candidate_with_semantics(
                _build_manual_topic_candidate(topic),
                rows,
                current_feed_state,
                campaign_mode,
                recommended_slot=recommended_slot,
                open_loops=open_loops,
            ),
            current_feed_state,
            campaign_mode,
        )
        for topic in cleaned_topics
    ]
    ranked = [
        candidate
        for candidate in candidates
        if candidate.editorial_gate != "disallowed" and candidate.narrative_gate != "forbidden"
    ]
    ranked.sort(
        key=lambda candidate: (
            gate_priority(candidate),
            candidate.score,
            1 if candidate.novelty_status == "fresh" else 0,
            candidate.slot_fit_score,
            candidate.novelty_score,
            candidate.narrative_priority_score,
        ),
        reverse=True,
    )
    ranked_rows = []
    for index, candidate in enumerate(ranked, start=1):
        row = _serialize_planner_candidate(candidate, rows)
        row["rank"] = index
        ranked_rows.append(row)

    return {
        "business_goal": business_goal,
        "recommended_slot": recommended_slot,
        "ranking_order": [row["theme"] for row in ranked_rows],
        "top_theme": ranked_rows[0]["theme"] if ranked_rows else None,
        "topics": ranked_rows,
    }


def compare_planner_prediction_to_expected(prediction: dict, expected: dict) -> dict:
    """Return lightweight comparison diagnostics for planner-ranking golden-set cases."""

    results: dict[str, dict[str, Any]] = {}
    if "top_theme" in expected:
        predicted_top = _normalize_scalar(prediction.get("top_theme"))
        expected_top = _normalize_scalar(expected.get("top_theme"))
        results["top_theme"] = {
            "matched": predicted_top == expected_top,
            "predicted": predicted_top,
            "expected": expected_top,
        }
    if "ranking_order_prefix" in expected:
        predicted_order = [_normalize_scalar(item) for item in (prediction.get("ranking_order") or [])]
        expected_prefix = [_normalize_scalar(item) for item in (expected.get("ranking_order_prefix") or [])]
        results["ranking_order_prefix"] = {
            "matched": predicted_order[: len(expected_prefix)] == expected_prefix,
            "predicted": predicted_order[: len(expected_prefix)],
            "expected": expected_prefix,
        }
    if "novelty_status_by_topic" in expected:
        predicted_map = {
            _normalize_scalar(item.get("theme")): _normalize_categorical(item.get("novelty_status"))
            for item in (prediction.get("topics") or [])
        }
        expected_map = {
            _normalize_scalar(topic): _normalize_categorical(status)
            for topic, status in dict(expected.get("novelty_status_by_topic") or {}).items()
        }
        results["novelty_status_by_topic"] = {
            "matched": all(predicted_map.get(topic) == status for topic, status in expected_map.items()),
            "predicted": {topic: predicted_map.get(topic, "") for topic in expected_map},
            "expected": expected_map,
        }
    return results


def predict_semantic_case(
    case: dict,
    archive: list[dict] | None = None,
    prefer_llm: bool = False,
) -> dict:
    """Predict editorial semantics for one evaluation case described as topic or post."""

    if case.get("topics"):
        topics = [str(topic).strip() for topic in (case.get("topics") or []) if str(topic).strip()]
        return build_planner_batch_review(
            topics,
            archive=archive,
            business_goal=str(case.get("business_goal") or "expert"),
        )

    kind = _normalize_scalar(case.get("kind") or "")
    if kind == "topic" or case.get("topic"):
        topic = str(case.get("topic") or case.get("label") or "").strip()
        context = case.get("context") if isinstance(case.get("context"), dict) else None
        return build_extractor_review_for_topic(topic, context=context, archive=archive, prefer_llm=prefer_llm)

    card = dict(case.get("card") or {})
    if case.get("text") and "body_text" not in card:
        card["body_text"] = case["text"]
    if case.get("title_hook") and "title_hook" not in card:
        card["title_hook"] = case["title_hook"]
    if case.get("primary_theme") and "primary_theme" not in card:
        card["primary_theme"] = case["primary_theme"]
    return build_extractor_review_for_post(card, archive=archive, prefer_llm=prefer_llm)


def compare_prediction_to_expected(prediction: dict, expected: dict) -> dict:
    """Return per-field exact-match diagnostics for a golden-set example."""

    results: dict[str, dict[str, Any]] = {}
    for field, expected_value in expected.items():
        predicted_value = prediction.get(field)
        if isinstance(expected_value, list):
            predicted_normalized = _normalize_list(predicted_value)
            expected_normalized = _normalize_list(expected_value)
            matched = predicted_normalized == expected_normalized
            results[field] = {
                "matched": matched,
                "predicted": predicted_normalized,
                "expected": expected_normalized,
            }
            continue

        predicted_normalized = _normalize_scalar(predicted_value)
        expected_normalized = _normalize_scalar(expected_value)
        if field in {"funnel_stage", "novelty_status", "content_goal", "format_type"}:
            predicted_normalized = _normalize_categorical(predicted_value)
            expected_normalized = _normalize_categorical(expected_value)
        matched = predicted_normalized == expected_normalized
        results[field] = {
            "matched": matched,
            "predicted": predicted_normalized,
            "expected": expected_normalized,
        }
    return results


def accumulate_match_stats(comparisons: list[dict]) -> dict:
    """Aggregate simple accuracy stats for golden-set field comparisons."""

    field_stats: dict[str, dict[str, int]] = {}
    for comparison in comparisons:
        for field, result in comparison.items():
            stats = field_stats.setdefault(field, {"matched": 0, "total": 0})
            stats["matched"] += int(bool(result.get("matched")))
            stats["total"] += 1

    summary: dict[str, dict[str, Any]] = {}
    for field, stats in field_stats.items():
        total = stats["total"]
        matched = stats["matched"]
        summary[field] = {
            "matched": matched,
            "total": total,
            "accuracy": round((matched / total) if total else 0.0, 4),
        }
    return summary


def load_cases(path: Path) -> list[dict]:
    """Load evaluation cases from JSON or JSONL."""

    if path.suffix.lower() == ".jsonl":
        return [normalize_case_payload(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return [normalize_case_payload(item) for item in json.loads(path.read_text(encoding="utf-8"))]


def normalize_case_payload(payload: str | dict) -> dict:
    """Return one normalized evaluation case from a JSON line or dict."""

    if isinstance(payload, str):
        return dict(json.loads(payload))
    return dict(payload)
