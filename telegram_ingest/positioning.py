from __future__ import annotations

import os
import re
from pathlib import Path

from .config import ROOT
from .knowledge import get_active_knowledge_version


POSITIONING_SNAPSHOT_PATH = ROOT / "CURRENT_POSITIONING_SNAPSHOT.md"
BALANCE_RANGES = {
    "expert": {"min": 0.35, "max": 0.45},
    "conversational": {"min": 0.20, "max": 0.30},
    "money": {"min": 0.25, "max": 0.35},
}
CTA_BALANCE_RANGES = {
    "comments": {"min": 0.45, "max": 0.60},
    "diagnostic": {"min": 0.20, "max": 0.30},
    "personal": {"min": 0.05, "max": 0.10},
    "none": {"min": 0.20, "max": 0.30},
}
FLAGSHIP_KEYWORDS = (
    "хаос",
    "потери",
    "издерж",
    "контроль",
    "управляем",
    "стабилиз",
    "архитект",
    "процесс",
    "роль",
    "оргструкт",
    "операцион",
    "прибыл",
    "собственник",
    "ручн",
    "узк",
    "ответствен",
    "дедлайн",
    "передел",
    "маржа",
    "утеч",
    "сервис",
)
MONEY_TOKENS = ("расход", "издерж", "прибыл", "деньг", "выруч", "потер", "марж", "себестоим")
CONVERSATIONAL_TOKENS = ("жизн", "отдых", "пауза", "инсайт", "свобод", "отношение", "сует", "выбор")
DIAGNOSTIC_TOKENS = ("стад", "кризис", "диагност", "перекос", "симптом", "причин")
SEGMENT_TOKENS = ("сервис", "агентств", "юрид", "консалт", "школ", "образов", "креатив", "логист")
OWNER_DEPENDENCY_TOKENS = ("все на мне", "всё на мне", "без меня", "узкое горлышко", "собственник", "ручн")


def normalize_positioning_text(text: str) -> str:
    lowered = text.lower().replace("ё", "е")
    lowered = re.sub(r"[^a-zа-я0-9\s]+", " ", lowered)
    lowered = re.sub(r"\s+", " ", lowered)
    return lowered.strip()


def get_campaign_mode() -> str:
    raw = os.environ.get("CONTENT_BOT_CAMPAIGN_MODE", "base").strip().lower()
    allowed = {"base", "warmup", "offer_push", "diagnostics_push"}
    return raw if raw in allowed else "base"


def infer_positioning_pillar(theme: str, content_pillar: str | None = None) -> str:
    if content_pillar in {"expert", "conversational", "money"}:
        return content_pillar
    normalized = normalize_positioning_text(theme)
    if any(token in normalized for token in CONVERSATIONAL_TOKENS):
        return "conversational"
    if any(token in normalized for token in MONEY_TOKENS + DIAGNOSTIC_TOKENS):
        return "money"
    return "expert"


def compute_flagship_fit(theme: str, angle: str = "", content_pillar: str | None = None) -> dict:
    combined = normalize_positioning_text(f"{theme} {angle}")
    score = 0
    reasons: list[str] = []
    pillar = infer_positioning_pillar(theme, content_pillar)

    keyword_hits = [token for token in FLAGSHIP_KEYWORDS if token in combined]
    if keyword_hits:
        score += min(12, len(keyword_hits) * 3)
        reasons.append("тема близка к ядру флагмана: управляемость, потери, процессы и контроль")

    if pillar == "money":
        score += 5
        reasons.append("денежный разбор хорошо подводит к антикризисной стабилизации")
    elif pillar == "expert":
        score += 3
        reasons.append("экспертная тема усиливает доверие к флагману через методологию")

    if any(token in combined for token in ("регламент", "роль", "оргструкт", "процесс", "операцион")):
        score += 4
        reasons.append("тема показывает опорные узлы, которые логично связываются с 45-дневной сборкой")

    if any(token in combined for token in SEGMENT_TOKENS):
        score += 4
        reasons.append("тема ближе к приоритетному сегменту сервисного бизнеса 60-150 млн")

    if any(token in combined for token in OWNER_DEPENDENCY_TOKENS):
        score += 4
        reasons.append("тема заходит через зависимость бизнеса от собственника, а это один из самых сильных входов в позиционирование")

    return {
        "score": score,
        "reason": reasons[0] if reasons else "тема нейтральна по отношению к флагману и работает скорее как поддержка ленты",
        "reasons": reasons,
    }


def resolve_cta_strategy(theme: str, content_pillar: str | None = None, campaign_mode: str | None = None) -> dict:
    campaign = campaign_mode or get_campaign_mode()
    normalized = normalize_positioning_text(theme)
    pillar = infer_positioning_pillar(theme, content_pillar)

    stage = "trust"
    allowed_ctas = ["comment", "none", "diagnostic"]
    preferred = "optional"
    path = "контент -> доверие -> диагностика -> 45 дней"
    reason = "тема работает скорее на доверие и постепенный прогрев, чем на прямой оффер"

    if any(token in normalized for token in DIAGNOSTIC_TOKENS):
        stage = "problem_aware"
        allowed_ctas = ["diagnostic", "comment", "personal"]
        preferred = "soft"
        path = "симптом -> диагностика -> разбор перекоса -> 45 дней"
        reason = "тема естественно ведёт в диагностику как мягкий вход в воронку"
    elif pillar == "money" or any(token in normalized for token in MONEY_TOKENS):
        stage = "solution_aware"
        allowed_ctas = ["diagnostic", "comment", "personal", "flagship"]
        preferred = "soft"
        path = "деньги и потери -> диагностика/разбор -> 45 дней"
        reason = "денежная тема может вести ближе к офферу, если дать логичный следующий шаг"
    elif pillar == "expert":
        stage = "solution_consideration"
        allowed_ctas = ["comment", "none", "diagnostic", "personal"]
        preferred = "optional"
        path = "экспертность -> доверие -> диагностика -> 45 дней"
        reason = "экспертная тема лучше работает как мост к следующему шагу, а не как прямой дожим"

    flagship_fit = compute_flagship_fit(theme, content_pillar=content_pillar)
    if campaign == "diagnostics_push":
        if "diagnostic" in allowed_ctas:
            preferred = "soft"
            reason = "сейчас приоритетно собирать вход в диагностику, поэтому мягкий CTA уместнее"
    elif campaign == "warmup":
        preferred = "optional" if preferred != "none" else preferred
        allowed_ctas = [cta for cta in allowed_ctas if cta != "flagship"] or ["none"]
        reason = "режим warmup: контент должен прогревать и собирать доверие без резкого дожима"
    elif campaign == "offer_push" and flagship_fit["score"] >= 10 and pillar != "conversational":
        preferred = "hard"
        if "flagship" not in allowed_ctas:
            allowed_ctas.append("flagship")
        path = "боль -> решение -> 45 дней"
        reason = "тема хорошо стыкуется с флагманом, поэтому можно вести ближе к офферу"

    return {
        "campaign_mode": campaign,
        "funnel_stage": stage,
        "allowed_ctas": allowed_ctas,
        "preferred_cta_need": preferred,
        "flagship_path": path,
        "reason": reason,
        "flagship_fit": flagship_fit,
    }


def load_positioning_snapshot() -> str:
    if not POSITIONING_SNAPSHOT_PATH.exists():
        return ""
    return POSITIONING_SNAPSHOT_PATH.read_text(encoding="utf-8")


def get_positioning_flags() -> dict:
    return {
        "knowledge_base_version": get_active_knowledge_version(),
        "flagship_offer": "Бизнес без потерь — 45 рабочих дней на устранение управленческих потерь",
        "market_language": ["потери", "контроль", "прибыль", "плавающая прибыль", "узкие места", "зависимость от собственника"],
        "primary_segment": "сервисный бизнес 60-150 млн ₽",
        "priority_pillars": [
            "управленческий хаос -> потери денег",
            "собственник как узкое горлышко",
            "кейсы и мини-кейсы системных изменений",
            "ошибки собственников в управлении, найме и делегировании",
            "систематизация без тотальной перестройки",
        ],
        "repositioning_rules": {
            "soft_shift_only": True,
            "bridge_topics_first": True,
            "avoid_long_legacy_sequences": True,
            "transition_logic": "старая знакомая тема -> новый угол через деньги, потери, зависимость и управляемость",
        },
        "funnel_entry_bot": "@adizesbizbot",
        "ai_policy": "ИИ как усилитель внутри системы, а не фасад бренда",
        "campaign_mode": get_campaign_mode(),
        "content_balance_ranges": BALANCE_RANGES,
        "cta_balance_ranges": CTA_BALANCE_RANGES,
        "flagship_keywords": list(FLAGSHIP_KEYWORDS),
        "cta_matrix_overview": {
            "trust": "контент -> доверие -> диагностика -> 45 дней",
            "problem_aware": "симптом -> диагностика -> разбор перекоса -> 45 дней",
            "solution_aware": "деньги и потери -> диагностика/разбор -> 45 дней",
            "offer_push": "боль -> решение -> 45 дней",
        },
    }
