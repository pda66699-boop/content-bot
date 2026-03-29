from __future__ import annotations

import re
from datetime import date
from typing import Any

from .editorial_metadata import normalize_editorial_metadata


SIMILARITY_WEIGHTS = {
    "primary_thesis": 0.58,
    "angle": 0.22,
    "secondary_theses": 0.09,
    "business_dimensions": 0.05,
    "funnel_stage": 0.03,
    "format_type": 0.02,
    "lexical": 0.01,
}


def _normalize_text(value: Any) -> str:
    """Return a normalized lowercase string for semantic comparison."""

    if value is None:
        return ""
    text = str(value).lower().replace("ё", "е")
    text = re.sub(r"[^a-zа-я0-9\s]+", " ", text)
    return " ".join(text.split())


def _token_set(value: Any) -> set[str]:
    """Return a token set for normalized semantic fields."""

    return set(_normalize_text(value).split())


def _jaccard_similarity(left: set[str], right: set[str]) -> float:
    """Return Jaccard similarity for two token sets."""

    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def _string_similarity(left: Any, right: Any) -> float:
    """Compare two text fields using a soft token-based similarity."""

    left_tokens = _token_set(left)
    right_tokens = _token_set(right)
    return _jaccard_similarity(left_tokens, right_tokens)


def _list_similarity(left: Any, right: Any) -> float:
    """Compare two list-like semantic fields using token set overlap."""

    def normalize_items(value: Any) -> set[str]:
        if value is None:
            return set()
        if isinstance(value, str):
            items = [value]
        elif isinstance(value, (list, tuple, set)):
            items = list(value)
        else:
            items = [value]
        normalized: set[str] = set()
        for item in items:
            cleaned = _normalize_text(item)
            if cleaned:
                normalized.add(cleaned)
        return normalized

    return _jaccard_similarity(normalize_items(left), normalize_items(right))


def _field_match(left: Any, right: Any) -> float:
    """Return 1.0 when two normalized categorical fields match."""

    left_value = _normalize_text(left)
    right_value = _normalize_text(right)
    if not left_value or not right_value:
        return 0.0
    return 1.0 if left_value == right_value else 0.0


def _lexical_overlap(candidate: dict, archived: dict) -> float:
    """Compute a weak lexical signal from theme and title fields."""

    candidate_text = " ".join(
        str(candidate.get(key) or "")
        for key in ("primary_theme", "title_hook", "body_summary")
    )
    archived_text = " ".join(
        str(archived.get(key) or "")
        for key in ("primary_theme", "title_hook", "body_summary")
    )
    return _string_similarity(candidate_text, archived_text)


def _parse_iso_date(value: Any) -> date | None:
    """Parse an ISO date string and return `None` for invalid values."""

    if not value:
        return None
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None


def _age_in_days(candidate: dict, archived: dict) -> int | None:
    """Return the archive row age relative to candidate date when possible."""

    candidate_date = _parse_iso_date(candidate.get("date")) or date.today()
    archived_date = _parse_iso_date(archived.get("date"))
    if archived_date is None:
        return None
    return abs((candidate_date - archived_date).days)


def _within_novelty_window(candidate: dict, archived: dict) -> bool:
    """Check whether an archive row is still inside the candidate novelty window."""

    window_days = int(candidate.get("novelty_window_days") or archived.get("novelty_window_days") or 30)
    age_days = _age_in_days(candidate, archived)
    if age_days is None:
        return False
    return age_days <= window_days


def _has_series_signal(row: dict) -> bool:
    """Detect explicit series/continuation hints in a card or topic."""

    haystack = " ".join(
        str(row.get(key) or "")
        for key in (
            "title_hook",
            "primary_theme",
            "angle",
            "primary_thesis",
            "body_summary",
        )
    ).lower().replace("ё", "е")
    return any(token in haystack for token in ("серия", "часть", "продолж", "follow up", "продолжение"))


def _score_candidate_pair(candidate: dict, archived: dict) -> dict:
    """Score semantic proximity between a candidate and one archive card."""

    primary_thesis_score = _string_similarity(candidate.get("primary_thesis"), archived.get("primary_thesis"))
    secondary_theses_score = _list_similarity(candidate.get("secondary_theses"), archived.get("secondary_theses"))
    angle_score = _string_similarity(candidate.get("angle"), archived.get("angle"))
    dimensions_score = _list_similarity(candidate.get("business_dimensions"), archived.get("business_dimensions"))
    funnel_stage_score = _field_match(candidate.get("funnel_stage"), archived.get("funnel_stage"))
    format_type_score = _field_match(candidate.get("format_type"), archived.get("format_type"))
    lexical_score = _lexical_overlap(candidate, archived)

    semantic_score = (
        primary_thesis_score * SIMILARITY_WEIGHTS["primary_thesis"]
        + angle_score * SIMILARITY_WEIGHTS["angle"]
        + secondary_theses_score * SIMILARITY_WEIGHTS["secondary_theses"]
        + dimensions_score * SIMILARITY_WEIGHTS["business_dimensions"]
        + funnel_stage_score * SIMILARITY_WEIGHTS["funnel_stage"]
        + format_type_score * SIMILARITY_WEIGHTS["format_type"]
        + lexical_score * SIMILARITY_WEIGHTS["lexical"]
    )

    within_window = _within_novelty_window(candidate, archived)
    age_days = _age_in_days(candidate, archived)
    return {
        "semantic_score": round(semantic_score, 4),
        "primary_thesis_score": round(primary_thesis_score, 4),
        "secondary_theses_score": round(secondary_theses_score, 4),
        "angle_score": round(angle_score, 4),
        "business_dimensions_score": round(dimensions_score, 4),
        "funnel_stage_score": round(funnel_stage_score, 4),
        "format_type_score": round(format_type_score, 4),
        "lexical_score": round(lexical_score, 4),
        "within_novelty_window": within_window,
        "age_days": age_days,
        "series_signal": _has_series_signal(candidate) or _has_series_signal(archived),
    }


def _prepare_row(row: dict) -> dict:
    """Normalize a row before semantic comparison."""

    return normalize_editorial_metadata(row)


def _classify_neighbor(candidate: dict, archived: dict, score: dict) -> str:
    """Classify one candidate/archive pair into a novelty status."""

    primary_score = score["primary_thesis_score"]
    angle_score = score["angle_score"]
    secondary_score = score["secondary_theses_score"]
    dimensions_score = score["business_dimensions_score"]
    semantic_score = score["semantic_score"]
    within_window = score["within_novelty_window"]

    if (
        semantic_score >= 0.78
        and primary_score >= 0.72
        and angle_score >= 0.55
        and within_window
    ):
        return "too_close"

    if (
        primary_score >= 0.68
        and (
            score["series_signal"]
            or (0.12 <= secondary_score < 0.9 and angle_score < 0.45 and dimensions_score >= 0.34)
        )
    ):
        return "series_continuation"

    if primary_score >= 0.6 and angle_score < 0.52:
        return "reframe_allowed"

    if semantic_score >= 0.66 and within_window:
        return "reframe_allowed"

    return "fresh"


def find_semantic_neighbors(candidate: dict, archive: list[dict], limit: int = 5) -> list[dict]:
    """Return the closest semantic neighbors for a candidate post or topic."""

    prepared_candidate = _prepare_row(candidate)
    neighbors: list[dict] = []
    for item in archive:
        prepared_item = _prepare_row(item)
        score = _score_candidate_pair(prepared_candidate, prepared_item)
        neighbor = dict(prepared_item)
        neighbor.update(score)
        neighbor["novelty_status"] = _classify_neighbor(prepared_candidate, prepared_item, score)
        neighbors.append(neighbor)

    neighbors.sort(
        key=lambda item: (
            item["semantic_score"],
            item["primary_thesis_score"],
            1 if item["within_novelty_window"] else 0,
        ),
        reverse=True,
    )
    return neighbors[: max(limit, 0)]


def classify_topic_novelty(candidate: dict, archive: list[dict]) -> dict:
    """Classify candidate novelty against the archive using semantic neighbors."""

    prepared_candidate = _prepare_row(candidate)
    neighbors = find_semantic_neighbors(prepared_candidate, archive, limit=5)
    if not neighbors:
        return {
            "status": "fresh",
            "score": 0.0,
            "matched_posts": [],
            "explanation": "Архив пуст или не дал релевантных semantic neighbors.",
        }

    best_match = neighbors[0]
    statuses = [item["novelty_status"] for item in neighbors]
    if "too_close" in statuses:
        status = "too_close"
        explanation = "Есть недавний пост с очень близким тезисом и почти тем же углом подачи."
    elif "series_continuation" in statuses:
        status = "series_continuation"
        explanation = "Тема похожа на уже начатую линию и выглядит как естественное продолжение серии."
    elif "reframe_allowed" in statuses:
        status = "reframe_allowed"
        explanation = "Центральный тезис уже звучал, но новый угол или формат позволяют безопасный reframe."
    else:
        status = "fresh"
        if best_match.get("semantic_score", 0.0) >= 0.72 and not best_match.get("within_novelty_window"):
            explanation = "Похожий тезис в архиве есть, но он уже вне novelty window, поэтому тему можно считать свежей."
        else:
            explanation = "Тема достаточно далека от недавних постов по editorial semantics."

    return {
        "status": status,
        "score": best_match["semantic_score"],
        "matched_posts": neighbors,
        "best_match": best_match,
        "explanation": explanation,
        "reframes": suggest_reframes(prepared_candidate, neighbors),
    }


def suggest_reframes(candidate: dict, matched_posts: list[dict]) -> list[str]:
    """Suggest safe reframes when the archive already contains close semantic matches."""

    prepared_candidate = _prepare_row(candidate)
    suggestions: list[str] = []
    used = set()

    matched_dimensions = {
        dimension
        for item in matched_posts
        for dimension in item.get("business_dimensions", [])
    }
    candidate_dimensions = set(prepared_candidate.get("business_dimensions", []))
    alternative_dimensions = sorted(candidate_dimensions - matched_dimensions)
    if alternative_dimensions:
        suggestion = f"Сместить фокус в другой бизнес-слой: {', '.join(alternative_dimensions[:2])}."
        suggestions.append(suggestion)
        used.add(suggestion)

    matched_formats = {item.get("format_type") for item in matched_posts if item.get("format_type")}
    candidate_format = prepared_candidate.get("format_type")
    for alternative_format in ("case", "applied", "expert", "conversation"):
        if alternative_format != candidate_format and alternative_format not in matched_formats:
            suggestion = f"Сменить формат подачи и раскрыть тему как {alternative_format}."
            if suggestion not in used:
                suggestions.append(suggestion)
                used.add(suggestion)
            break

    matched_stages = {item.get("funnel_stage") for item in matched_posts if item.get("funnel_stage")}
    candidate_stage = prepared_candidate.get("funnel_stage")
    for alternative_stage in ("aware", "problem-aware", "solution-aware", "trust"):
        if alternative_stage != candidate_stage and alternative_stage not in matched_stages:
            suggestion = f"Сместить стадию воронки и подать тему ближе к этапу '{alternative_stage}'."
            if suggestion not in used:
                suggestions.append(suggestion)
                used.add(suggestion)
            break

    for item in matched_posts[:3]:
        archived_angle = _normalize_text(item.get("angle"))
        candidate_angle = _normalize_text(prepared_candidate.get("angle"))
        if archived_angle and archived_angle != candidate_angle:
            suggestion = "Уйти от прежнего угла и начать с другой управленческой сцены или следствия."
            if suggestion not in used:
                suggestions.append(suggestion)
                used.add(suggestion)
            break

    if not suggestions:
        suggestions.append("Тему лучше раскрыть через новый кейс, другой слой бизнеса или более узкий симптом.")
    return suggestions[:3]
