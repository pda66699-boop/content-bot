from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping


DEFAULT_NOVELTY_WINDOW_DAYS = 30

EDITORIAL_METADATA_DEFAULTS: dict[str, Any] = {
    "primary_thesis": None,
    "secondary_theses": [],
    "angle": "",
    "content_goal": "expert",
    "funnel_stage": "aware",
    "business_dimensions": [],
    "format_type": "expert",
    "novelty_window_days": DEFAULT_NOVELTY_WINDOW_DAYS,
}


def _normalize_optional_string(value: Any, default: str | None = None) -> str | None:
    """Return a stripped string value or the provided default."""

    if value is None:
        return default
    if not isinstance(value, str):
        value = str(value)
    cleaned = value.strip()
    return cleaned if cleaned else default


def _normalize_string(value: Any, default: str) -> str:
    """Return a stripped string value or a non-empty fallback."""

    normalized = _normalize_optional_string(value)
    return normalized if normalized is not None else default


def _normalize_string_list(value: Any) -> list[str]:
    """Convert a loose list-like value into a de-duplicated list of strings."""

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
        cleaned = _normalize_optional_string(item)
        if cleaned is None or cleaned in seen:
            continue
        normalized.append(cleaned)
        seen.add(cleaned)
    return normalized


def _normalize_int(value: Any, default: int) -> int:
    """Coerce a value to int and clamp invalid values to the default."""

    try:
        normalized = int(value)
    except (TypeError, ValueError):
        return default
    return normalized if normalized > 0 else default


def _normalize_funnel_stage(value: Any, default: str) -> str:
    """Return a canonical funnel-stage slug for downstream planner and coverage logic."""

    cleaned = _normalize_string(value, default).lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "problemaware": "problem_aware",
        "problem_aware": "problem_aware",
        "solutionaware": "solution_aware",
        "solution_aware": "solution_aware",
        "solutionconsideration": "solution_consideration",
        "solution_consideration": "solution_consideration",
        "diagnosticentry": "diagnostic_entry",
        "diagnostic_entry": "diagnostic_entry",
    }
    return aliases.get(cleaned, cleaned)


def normalize_editorial_metadata(record: Mapping[str, Any] | None) -> dict[str, Any]:
    """Return a backward-compatible post record with editorial metadata defaults.

    The normalizer is intentionally soft:
    - missing fields are added with safe defaults;
    - old fields remain untouched;
    - new fields are derived from legacy fields when possible;
    - malformed values are coerced instead of raising exceptions.
    """

    payload = dict(record or {})

    primary_thesis = _normalize_optional_string(
        payload.get("primary_thesis"),
        default=_normalize_optional_string(payload.get("core_thesis")),
    )
    secondary_theses = _normalize_string_list(
        payload.get("secondary_theses") or payload.get("secondary_themes")
    )
    angle = _normalize_string(payload.get("angle"), EDITORIAL_METADATA_DEFAULTS["angle"])
    content_goal = _normalize_string(
        payload.get("content_goal") or payload.get("content_role"),
        EDITORIAL_METADATA_DEFAULTS["content_goal"],
    )
    funnel_stage = _normalize_funnel_stage(
        payload.get("funnel_stage"),
        EDITORIAL_METADATA_DEFAULTS["funnel_stage"],
    )
    business_dimensions = _normalize_string_list(payload.get("business_dimensions"))
    format_type = _normalize_string(
        payload.get("format_type") or payload.get("format"),
        EDITORIAL_METADATA_DEFAULTS["format_type"],
    )
    novelty_window_days = _normalize_int(
        payload.get("novelty_window_days"),
        EDITORIAL_METADATA_DEFAULTS["novelty_window_days"],
    )

    normalized = deepcopy(payload)
    normalized["primary_thesis"] = primary_thesis
    normalized["secondary_theses"] = secondary_theses
    normalized["angle"] = angle
    normalized["content_goal"] = content_goal
    normalized["funnel_stage"] = funnel_stage
    normalized["business_dimensions"] = business_dimensions
    normalized["format_type"] = format_type
    normalized["novelty_window_days"] = novelty_window_days
    return normalized


def ensure_editorial_metadata(record: Mapping[str, Any] | None) -> dict[str, Any]:
    """Backward-compatible alias for normalizing editorial metadata."""

    return normalize_editorial_metadata(record)
