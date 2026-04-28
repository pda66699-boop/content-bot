from __future__ import annotations

import json
from typing import Any

from .editorial_metadata import DEFAULT_NOVELTY_WINDOW_DAYS, normalize_editorial_metadata
from .llm_client import complete_json, llm_available


EDITORIAL_FIELDS = (
    "primary_thesis",
    "secondary_theses",
    "angle",
    "content_goal",
    "funnel_stage",
    "business_dimensions",
    "format_type",
    "novelty_window_days",
)


def _normalize_text(value: Any) -> str:
    """Return a stripped string representation of the value."""

    if value is None:
        return ""
    return " ".join(str(value).split()).strip()


def _infer_business_dimensions(text: str, theme: str) -> list[str]:
    """Infer lightweight business dimensions from post or topic wording."""

    lowered = f"{theme} {text}".lower().replace("ё", "е")
    dimensions: list[str] = []
    candidates = [
        ("управление", ("управ", "собствен", "ответствен", "роль", "оргструкт")),
        ("операционка", ("процесс", "операцион", "регламент", "стык", "согласован")),
        ("финансы", ("прибыл", "издерж", "расход", "потер", "теря", "утеч", "марж", "деньг")),
        ("команда", ("команд", "сотруд", "люд", "делег", "найм")),
        ("контроль", ("контрол", "показател", "метрик", "данн", "отчет")),
        ("автоматизация", ("ии", "ai", "gpt", "автомат", "нейро")),
    ]
    for label, tokens in candidates:
        if any(token in lowered for token in tokens):
            dimensions.append(label)
    return dimensions or ["управление"]


def _infer_primary_thesis(text: str, theme: str, existing: str | None = None) -> str | None:
    """Infer a concise primary thesis while preserving known legacy values."""

    if _normalize_text(existing):
        return _normalize_text(existing)
    lowered = f"{theme} {text}".lower().replace("ё", "е")
    if any(token in lowered for token in ("издерж", "потер", "теря", "утеч", "расход")):
        return "Главные потери бизнеса часто скрыты в процессах и управленческих разрывах, а не только в видимых расходах."
    if any(token in lowered for token in ("оргструкт", "роль", "ответствен")):
        return "Без ролей и ясной ответственности управляемость не появляется, даже если команда уже есть."
    if any(token in lowered for token in ("регламент", "процесс")):
        return "Процессы приносят результат только тогда, когда у них есть владелец, контроль и понятный выход."
    if any(token in lowered for token in ("ии", "ai", "gpt", "нейро")):
        return "ИИ усиливает уже существующую систему и без управляемой основы может только ускорить хаос."
    if theme:
        return f"Центральная мысль темы '{theme}' требует системного, а не симптоматического управленческого разбора."
    return None


def _infer_secondary_theses(text: str, theme: str, dimensions: list[str], existing: Any = None) -> list[str]:
    """Infer supporting theses for planning and novelty checks."""

    if isinstance(existing, list) and existing:
        return [item for item in (str(value).strip() for value in existing) if item]
    statements: list[str] = []
    lowered = f"{theme} {text}".lower().replace("ё", "е")
    if "финансы" in dimensions:
        statements.append("Сокращение потерь начинается с диагностики скрытых утечек, а не только с урезания бюджета.")
    if "операционка" in dimensions:
        statements.append("Разрывы между функциями и ручной режим создают накопленный операционный шум.")
    if "управление" in dimensions:
        statements.append("Симптомы стоит разбирать через архитектуру управления, а не через разовые действия.")
    if "автоматизация" in dimensions and any(token in lowered for token in ("ии", "ai", "gpt", "нейро")):
        statements.append("Инструмент работает только внутри уже собранного процесса и понятной роли.")
    return statements[:3]


def _infer_angle(text: str, theme: str, dimensions: list[str], existing: str | None = None) -> str:
    """Infer a practical editorial angle for a post or topic."""

    if _normalize_text(existing):
        return _normalize_text(existing)
    lowered = f"{theme} {text}".lower().replace("ё", "е")
    if "финансы" in dimensions:
        return "зайти через видимые расходы, затем перевести внимание на скрытые потери внутри процессов и решений"
    if "команда" in dimensions:
        return "показать узнаваемую рабочую ситуацию и развернуть её через роли, ответственность и границы решений"
    if "автоматизация" in dimensions:
        return "подать тему через системную готовность бизнеса, а ИИ оставить инструментом внутри процесса"
    if any(token in lowered for token in ("симптом", "почему", "ошиб")):
        return "начать с симптома, затем раскрыть системную причину и довести до одного прикладного вывода"
    return "начать с понятной управленческой сцены, затем раскрыть системную причину и практический вывод"


def _infer_content_goal(text: str, theme: str, existing: str | None = None) -> str:
    """Infer the editorial goal using stable local heuristics."""

    if _normalize_text(existing):
        return _normalize_text(existing)
    lowered = f"{theme} {text}".lower().replace("ё", "е")
    if any(token in lowered for token in ("кейс", "пример", "история", "domino")):
        return "case"
    if any(token in lowered for token in ("почему", "ошиб", "симптом", "проблем")):
        return "diagnostic"
    if any(token in lowered for token in ("как ", "шаг", "признак", "инструмент", "разобрал")):
        return "applied"
    return "expert"


def _infer_funnel_stage(text: str, goal: str, existing: str | None = None) -> str:
    """Infer the funnel stage while remaining compatible with legacy values."""

    if _normalize_text(existing):
        return _normalize_text(existing)
    lowered = text.lower().replace("ё", "е")
    if any(token in lowered for token in ("@pda33", "диагност", "бот", "комментар")):
        return "solution-aware"
    if goal in {"diagnostic", "case"} or any(token in lowered for token in ("почему", "ошиб", "симптом", "проблем")):
        return "problem-aware"
    return "aware"


def _infer_format_type(card: dict, goal: str, existing: str | None = None) -> str:
    """Infer a stable format type without changing legacy fields."""

    if _normalize_text(existing):
        return _normalize_text(existing)
    legacy_format = _normalize_text(card.get("format"))
    if legacy_format:
        return legacy_format
    return "case" if goal == "case" else "expert"


def _infer_novelty_window_days(goal: str, dimensions: list[str], existing: Any = None) -> int:
    """Infer how long the topic should be treated as sensitive for repeats."""

    try:
        if existing is not None and int(existing) > 0:
            return int(existing)
    except (TypeError, ValueError):
        pass
    if goal == "case":
        return 45
    if "автоматизация" in dimensions:
        return 21
    if "финансы" in dimensions:
        return 35
    return DEFAULT_NOVELTY_WINDOW_DAYS


def _build_rules_metadata(card: dict) -> dict:
    """Build editorial metadata using local heuristics only."""

    body_text = _normalize_text(card.get("body_text") or card.get("body_summary"))
    theme = _normalize_text(card.get("primary_theme") or card.get("title_hook"))
    dimensions = _infer_business_dimensions(body_text, theme)
    content_goal = _infer_content_goal(body_text, theme, existing=card.get("content_goal") or card.get("content_role"))
    return {
        "primary_thesis": _infer_primary_thesis(body_text, theme, existing=card.get("primary_thesis") or card.get("core_thesis")),
        "secondary_theses": _infer_secondary_theses(body_text, theme, dimensions, existing=card.get("secondary_theses")),
        "angle": _infer_angle(body_text, theme, dimensions, existing=card.get("angle")),
        "content_goal": content_goal,
        "funnel_stage": _infer_funnel_stage(body_text, content_goal, existing=card.get("funnel_stage")),
        "business_dimensions": dimensions,
        "format_type": _infer_format_type(card, content_goal, existing=card.get("format_type")),
        "novelty_window_days": _infer_novelty_window_days(content_goal, dimensions, existing=card.get("novelty_window_days")),
    }


def _validate_llm_metadata(payload: dict | None) -> dict | None:
    """Validate a classifier payload and return it only if all fields are sane."""

    if not isinstance(payload, dict):
        return None
    if any(field not in payload for field in EDITORIAL_FIELDS):
        return None
    if payload.get("primary_thesis") is not None and not isinstance(payload.get("primary_thesis"), str):
        return None
    if not isinstance(payload.get("secondary_theses"), list) or not all(isinstance(item, str) for item in payload["secondary_theses"]):
        return None
    if not isinstance(payload.get("angle"), str):
        return None
    if not isinstance(payload.get("content_goal"), str):
        return None
    if not isinstance(payload.get("funnel_stage"), str):
        return None
    if not isinstance(payload.get("business_dimensions"), list) or not all(isinstance(item, str) for item in payload["business_dimensions"]):
        return None
    if not isinstance(payload.get("format_type"), str):
        return None
    if not isinstance(payload.get("novelty_window_days"), int):
        return None
    return payload


def _maybe_classify_with_llm(source_type: str, payload: dict, prefer_llm: bool = True) -> dict | None:
    """Classify editorial metadata with LLM and validate the JSON response."""

    if not prefer_llm or not llm_available():
        return None
    system_prompt = (
        "Ты semantic classifier для editorial metadata Telegram-контента Дениса Педченко. "
        "Не переписывай текст и не улучшай стиль. "
        "Твоя задача: классифицировать смысл, угол, цель и novelty window. "
        "Верни только JSON с полями: primary_thesis, secondary_theses, angle, content_goal, funnel_stage, "
        "business_dimensions, format_type, novelty_window_days. "
        "secondary_theses и business_dimensions всегда массивы строк. novelty_window_days всегда целое число."
    )
    user_prompt = json.dumps(
        {
            "task": f"Классифицируй editorial metadata для {source_type}.",
            "source_type": source_type,
            "payload": payload,
            "required_fields": list(EDITORIAL_FIELDS),
        },
        ensure_ascii=False,
    )
    return _validate_llm_metadata(complete_json(system_prompt, user_prompt, temperature=0.1))


def infer_editorial_metadata_from_post(card: dict, prefer_llm: bool = True) -> dict:
    """Infer editorial metadata for a post card with LLM fallback to rules-only."""

    rules_payload = _build_rules_metadata(card)
    llm_payload = _maybe_classify_with_llm(
        "post",
        {
            "title_hook": card.get("title_hook"),
            "primary_theme": card.get("primary_theme"),
            "body_summary": card.get("body_summary"),
            "body_text": card.get("body_text"),
            "content_role": card.get("content_role"),
            "format": card.get("format"),
            "funnel_stage": card.get("funnel_stage"),
            "core_thesis": card.get("core_thesis"),
        },
        prefer_llm=prefer_llm,
    )
    return normalize_editorial_metadata({**card, **(llm_payload or rules_payload)})


def infer_editorial_metadata_from_topic(topic: str, context: dict | None = None, prefer_llm: bool = True) -> dict:
    """Infer editorial metadata for a topic string with optional context."""

    context = dict(context or {})
    seed_card = {
        "title_hook": topic,
        "primary_theme": context.get("primary_theme") or topic,
        "body_summary": context.get("body_summary") or "",
        "body_text": context.get("body_text") or context.get("description") or topic,
        "content_role": context.get("content_role") or context.get("content_goal"),
        "format": context.get("format") or context.get("format_type"),
        "funnel_stage": context.get("funnel_stage"),
        "core_thesis": context.get("core_thesis") or context.get("primary_thesis"),
        "angle": context.get("angle"),
        "secondary_theses": context.get("secondary_theses"),
        "novelty_window_days": context.get("novelty_window_days"),
    }
    rules_payload = _build_rules_metadata(seed_card)
    llm_payload = _maybe_classify_with_llm(
        "topic",
        {
            "topic": topic,
            "context": context,
            "required_fields": list(EDITORIAL_FIELDS),
        },
        prefer_llm=prefer_llm,
    )
    enriched = normalize_editorial_metadata({**seed_card, **(llm_payload or rules_payload)})
    return {field: enriched.get(field) for field in EDITORIAL_FIELDS}
