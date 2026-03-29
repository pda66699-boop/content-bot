from __future__ import annotations

import json
import logging
from pathlib import Path

from .config import EDITORIAL_FEEDBACK_PATH, KNOWLEDGE_REGISTRY_PATH, TERMINOLOGY_REGISTRY_PATH


LOGGER = logging.getLogger(__name__)

_DEFAULT_KNOWLEDGE_REGISTRY = {
    "active_version": "v1",
    "versions": {
        "v1": {
            "label": "Initial positioning base",
            "notes": "Built from 00-07 files and Telegram export as of 2026-03-13.",
        }
    },
}


def load_knowledge_registry() -> dict:
    if not KNOWLEDGE_REGISTRY_PATH.exists():
        return dict(_DEFAULT_KNOWLEDGE_REGISTRY)
    try:
        return json.loads(KNOWLEDGE_REGISTRY_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        LOGGER.error("Corrupted knowledge registry at %s: %s — using defaults", KNOWLEDGE_REGISTRY_PATH, exc)
        return dict(_DEFAULT_KNOWLEDGE_REGISTRY)


def save_knowledge_registry(payload: dict) -> None:
    KNOWLEDGE_REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
    KNOWLEDGE_REGISTRY_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def get_active_knowledge_version() -> str:
    registry = load_knowledge_registry()
    return registry.get("active_version", "v1")


def load_terminology_registry() -> dict:
    if not TERMINOLOGY_REGISTRY_PATH.exists():
        return {"version": "v0", "canonical_terms": {}, "taboo_phrases": []}
    try:
        return json.loads(TERMINOLOGY_REGISTRY_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        LOGGER.error("Corrupted terminology registry at %s: %s — using empty registry", TERMINOLOGY_REGISTRY_PATH, exc)
        return {"version": "v0", "canonical_terms": {}, "taboo_phrases": []}


def load_editorial_feedback() -> list[dict]:
    if not EDITORIAL_FEEDBACK_PATH.exists():
        return []
    rows = []
    for lineno, line in enumerate(EDITORIAL_FEEDBACK_PATH.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as exc:
            LOGGER.warning("Skipping malformed line %d in %s: %s", lineno, EDITORIAL_FEEDBACK_PATH, exc)
    return rows
