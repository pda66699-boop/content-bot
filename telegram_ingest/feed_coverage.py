from __future__ import annotations

from collections import Counter
from typing import Any

from .editorial_metadata import normalize_editorial_metadata


DEFAULT_FEED_COVERAGE_WINDOW = 18


def _normalize_list(value: Any) -> list[str]:
    """Return a cleaned list of strings for coverage counters."""

    if value is None:
        return []
    if isinstance(value, str):
        items = [value]
    elif isinstance(value, (list, tuple, set)):
        items = list(value)
    else:
        items = [value]
    normalized: list[str] = []
    seen: set[str] = set()
    for item in items:
        cleaned = str(item).strip()
        if cleaned and cleaned not in seen:
            normalized.append(cleaned)
            seen.add(cleaned)
    return normalized


def infer_angle_signature(row: dict) -> str:
    """Map a raw angle or thesis to a coarse slot-friendly angle signature."""

    haystack = " ".join(
        str(row.get(key) or "")
        for key in ("angle", "primary_thesis", "title_hook", "primary_theme")
    ).lower().replace("ё", "е")
    if any(token in haystack for token in ("кейс", "пример", "история", "разбор кейса")):
        return "case_proof"
    if any(token in haystack for token in ("деньг", "издерж", "расход", "прибыл", "потер")):
        return "money_impact"
    if any(token in haystack for token in ("роль", "оргструкт", "ответствен", "границ")):
        return "roles_architecture"
    if any(token in haystack for token in ("процесс", "регламент", "стык", "контрол", "владелец")):
        return "process_architecture"
    if any(token in haystack for token in ("ии", "ai", "gpt", "нейро", "автомат")):
        return "ai_system_fit"
    if any(token in haystack for token in ("наблюден", "личн", "отношен", "жизн", "свобод")):
        return "personal_observation"
    return "system_diagnostic"


def _counter_distribution(counter: Counter[str], total: int) -> dict[str, float]:
    """Convert a counter into a ratio map."""

    if total <= 0:
        return {}
    return {key: round(value / total, 4) for key, value in counter.items()}


def _coverage_summary(counter: Counter[str], total: int, *, min_ratio: float, max_ratio: float) -> dict[str, list[str]]:
    """Return missing and overheated labels for one coverage dimension."""

    if total <= 0:
        return {"missing": [], "overheated": []}
    missing = [key for key, ratio in _counter_distribution(counter, total).items() if ratio < min_ratio]
    overheated = [key for key, ratio in _counter_distribution(counter, total).items() if ratio > max_ratio]
    return {"missing": sorted(missing), "overheated": sorted(overheated)}


def analyze_feed_coverage(rows: list[dict], window_size: int = DEFAULT_FEED_COVERAGE_WINDOW) -> dict:
    """Analyze the last feed window and return content-plan coverage signals."""

    window = [normalize_editorial_metadata(row) for row in rows[-window_size:]]
    total = len(window)
    business_dimensions = Counter()
    angles = Counter()
    funnel_stages = Counter()
    content_goals = Counter()
    format_types = Counter()

    for row in window:
        for dimension in _normalize_list(row.get("business_dimensions")):
            business_dimensions[dimension] += 1
        angles[infer_angle_signature(row)] += 1
        funnel_stages[str(row.get("funnel_stage") or "aware")] += 1
        content_goals[str(row.get("content_goal") or row.get("content_role") or "expert")] += 1
        format_types[str(row.get("format_type") or row.get("format") or "expert")] += 1

    return {
        "window_size": total,
        "business_dimensions": {
            "counts": dict(business_dimensions),
            "ratios": _counter_distribution(business_dimensions, total),
            "summary": _coverage_summary(business_dimensions, total, min_ratio=0.08, max_ratio=0.38),
        },
        "angles": {
            "counts": dict(angles),
            "ratios": _counter_distribution(angles, total),
            "summary": _coverage_summary(angles, total, min_ratio=0.08, max_ratio=0.34),
        },
        "funnel_stage": {
            "counts": dict(funnel_stages),
            "ratios": _counter_distribution(funnel_stages, total),
            "summary": _coverage_summary(funnel_stages, total, min_ratio=0.12, max_ratio=0.46),
        },
        "content_goal": {
            "counts": dict(content_goals),
            "ratios": _counter_distribution(content_goals, total),
            "summary": _coverage_summary(content_goals, total, min_ratio=0.12, max_ratio=0.44),
        },
        "format_type": {
            "counts": dict(format_types),
            "ratios": _counter_distribution(format_types, total),
            "summary": _coverage_summary(format_types, total, min_ratio=0.08, max_ratio=0.4),
        },
    }


def recommend_content_plan_slot(coverage: dict, campaign_mode: str = "base") -> dict:
    """Pick the next content-plan slot from feed coverage gaps and heat."""

    missing_dimensions = coverage.get("business_dimensions", {}).get("summary", {}).get("missing", [])
    overheated_dimensions = coverage.get("business_dimensions", {}).get("summary", {}).get("overheated", [])
    missing_angles = coverage.get("angles", {}).get("summary", {}).get("missing", [])
    overheated_angles = coverage.get("angles", {}).get("summary", {}).get("overheated", [])
    missing_funnel = coverage.get("funnel_stage", {}).get("summary", {}).get("missing", [])
    overheated_funnel = coverage.get("funnel_stage", {}).get("summary", {}).get("overheated", [])
    missing_goals = coverage.get("content_goal", {}).get("summary", {}).get("missing", [])
    missing_formats = coverage.get("format_type", {}).get("summary", {}).get("missing", [])

    target_dimension = missing_dimensions[0] if missing_dimensions else "управление"
    target_angle = missing_angles[0] if missing_angles else "system_diagnostic"
    target_funnel_stage = "solution_aware" if campaign_mode in {"offer_push", "diagnostics_push"} else (missing_funnel[0] if missing_funnel else "problem_aware")
    target_content_goal = "diagnostic" if campaign_mode == "diagnostics_push" else (missing_goals[0] if missing_goals else "expert")
    target_format_type = missing_formats[0] if missing_formats else ("case" if target_angle == "case_proof" else "expert")

    why_parts = []
    if overheated_dimensions:
        why_parts.append(f"перегреты измерения: {', '.join(overheated_dimensions[:2])}")
    if missing_dimensions:
        why_parts.append(f"не хватает измерения: {target_dimension}")
    if overheated_angles:
        why_parts.append(f"перегреты углы: {', '.join(overheated_angles[:2])}")
    if missing_angles:
        why_parts.append(f"нужен угол: {target_angle}")
    if missing_funnel:
        why_parts.append(f"проседает стадия воронки: {target_funnel_stage}")
    if missing_goals:
        why_parts.append(f"не хватает goal-слоя: {target_content_goal}")
    if missing_formats:
        why_parts.append(f"полезно вернуть формат: {target_format_type}")

    why_now = "; ".join(why_parts) if why_parts else "лента выглядит сбалансированной, поэтому лучше выбрать слот с максимальной utility для следующего окна"

    return {
        "target_business_dimension": target_dimension,
        "target_angle_signature": target_angle,
        "target_funnel_stage": target_funnel_stage,
        "target_content_goal": target_content_goal,
        "target_format_type": target_format_type,
        "overheated": {
            "business_dimensions": overheated_dimensions,
            "angles": overheated_angles,
            "funnel_stage": overheated_funnel,
        },
        "missing": {
            "business_dimensions": missing_dimensions,
            "angles": missing_angles,
            "funnel_stage": missing_funnel,
            "content_goal": missing_goals,
            "format_type": missing_formats,
        },
        "why_now": why_now,
    }
