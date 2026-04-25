from __future__ import annotations

import re
from typing import Any


NARRATIVE_ROLES = ("trust", "pain", "reframe", "solution", "tool", "proof", "bridge", "cta")

BASE_SEQUENCES = (
    ("trust", "pain", "reframe", "solution"),
    ("pain", "solution", "tool"),
    ("reframe", "proof", "cta"),
    ("pain", "proof", "reframe", "solution", "cta"),
)


def _normalize(text: str | None) -> str:
    value = (text or "").lower().replace("ё", "е")
    value = re.sub(r"[^a-zа-я0-9\s]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def infer_narrative_role(
    *,
    theme: str,
    angle: str = "",
    content_role: str = "expert",
    content_pillar: str = "expert",
    marketing_rubric: str = "",
    strategic_format: str = "",
    cta_need: str = "optional",
) -> str:
    normalized = _normalize(f"{theme} {angle}")
    role = (content_role or "").lower()
    rubric = (marketing_rubric or "").lower()
    format_key = (strategic_format or "").lower()

    if format_key in {"case_breakdown"} or rubric == "case" or role == "case":
        return "proof"
    if format_key in {"practice_observation"} or rubric == "reflective_observation" or content_pillar == "conversational":
        return "trust"
    if format_key in {"comparison_post", "provocative_thesis"}:
        return "reframe"
    if format_key in {"diagnostic_post"} or rubric in {"mistake_breakdown", "diagnostic_entry"}:
        return "pain"
    if format_key in {"practical_framework"} or rubric == "flagship_warmup":
        return "solution"
    if format_key in {"bridge_post"}:
        return "bridge"
    if format_key in {"research_signal"}:
        return "proof"
    if any(token in normalized for token in ("чек лист", "чеклист", "self check", "5 призна", "вопроса", "вопросы", "шаг")):
        return "tool"
    if cta_need == "hard":
        return "cta"
    if any(token in normalized for token in ("кейс", "доказ", "подтвержд", "результат", "исследован", "статист")):
        return "proof"
    if any(token in normalized for token in ("ошиб", "симптом", "боль", "потер", "издерж", "плавает прибыль")):
        return "pain"
    if any(token in normalized for token in ("не ", "на деле", "как думает", "vs", "вместо")):
        return "reframe"
    if any(token in normalized for token in ("решение", "подход", "модель", "система", "собрать")):
        return "solution"
    return "trust"


def _normalize_role_list(items: list[Any]) -> list[str]:
    result: list[str] = []
    for item in items:
        role = str(item or "").strip().lower()
        if role in NARRATIVE_ROLES:
            result.append(role)
    return result


def build_narrative_state(rows: list[dict], max_roles: int = 10) -> dict:
    roles = _normalize_role_list([row.get("narrative_role") for row in rows][-max_roles:])
    if not roles:
        return {
            "current_chain_id": "chain-1",
            "current_stage": "pain",
            "last_roles": [],
            "chain_progress": {"pain": False, "reframe": False, "solution": False, "proof": False},
            "next_required_role": "trust",
            "allowed_roles": list(NARRATIVE_ROLES),
            "forbidden_roles": [],
            "chain_complete": False,
            "max_trust_streak": 2,
        }

    # New chain starts after CTA event.
    last_cta_idx = -1
    for idx, role in enumerate(roles):
        if role == "cta":
            last_cta_idx = idx
    chain_roles = roles[last_cta_idx + 1 :]

    progress = {
        "pain": "pain" in chain_roles,
        "reframe": "reframe" in chain_roles,
        "solution": "solution" in chain_roles,
        "proof": "proof" in chain_roles,
    }
    chain_complete = progress["pain"] and progress["reframe"] and progress["solution"]

    if not progress["pain"]:
        stage = "pain"
        next_role = "pain" if chain_roles else "trust"
    elif not progress["reframe"]:
        stage = "reframe"
        next_role = "reframe"
    elif not progress["solution"]:
        stage = "solution"
        next_role = "solution"
    elif not progress["proof"]:
        stage = "proof"
        next_role = "proof"
    else:
        stage = "cta"
        next_role = "cta"

    allowed = set(NARRATIVE_ROLES)
    forbidden = set()
    if not progress["pain"]:
        forbidden.add("solution")
        forbidden.add("tool")
    if not progress["solution"]:
        forbidden.add("tool")
    if not chain_complete:
        forbidden.add("cta")
    if len(chain_roles) >= 2 and chain_roles[-1] == chain_roles[-2]:
        forbidden.add(chain_roles[-1])

    allowed = allowed - forbidden
    if not allowed:
        allowed = set(NARRATIVE_ROLES)

    return {
        "current_chain_id": f"chain-{last_cta_idx + 2}",
        "current_stage": stage,
        "last_roles": roles,
        "chain_progress": progress,
        "next_required_role": next_role,
        "allowed_roles": sorted(allowed),
        "forbidden_roles": sorted(forbidden),
        "chain_complete": chain_complete,
        "max_trust_streak": 2,
    }


def evaluate_candidate_narrative_fit(
    *,
    role: str,
    narrative_state: dict,
    campaign_mode: str,
    cta_need: str = "optional",
) -> dict:
    role = str(role or "").lower()
    if role not in NARRATIVE_ROLES:
        role = "trust"

    last_roles = _normalize_role_list(narrative_state.get("last_roles") or [])
    progress = narrative_state.get("chain_progress") or {}
    allowed = set(narrative_state.get("allowed_roles") or NARRATIVE_ROLES)
    forbidden = set(narrative_state.get("forbidden_roles") or [])
    next_required = str(narrative_state.get("next_required_role") or "trust")

    max_trust_streak = 3 if campaign_mode == "warmup" else 2
    trust_streak = 0
    for item in reversed(last_roles):
        if item == "trust":
            trust_streak += 1
        else:
            break

    narrative_gate = "allowed"
    reasons: list[str] = []
    narrative_gap_score = 4
    chain_completion_score = 2

    if role == next_required:
        narrative_gap_score += 16
        reasons.append("закрывает обязательный следующий шаг нарратива")
    elif role in allowed:
        narrative_gap_score += 8
    else:
        narrative_gap_score -= 20
        reasons.append("роль не рекомендована в текущем состоянии цепочки")

    if role == "pain" and not progress.get("pain"):
        chain_completion_score += 12
    if role == "reframe" and progress.get("pain") and not progress.get("reframe"):
        chain_completion_score += 12
    if role == "solution" and progress.get("reframe") and not progress.get("solution"):
        chain_completion_score += 12
    if role == "proof" and progress.get("solution") and not progress.get("proof"):
        chain_completion_score += 10
    if role == "tool" and progress.get("solution"):
        chain_completion_score += 8
    if role == "cta" and progress.get("pain") and progress.get("reframe") and progress.get("solution"):
        chain_completion_score += 6
    if role == "cta" and not (progress.get("pain") and progress.get("reframe") and progress.get("solution")):
        narrative_gate = "forbidden"
        chain_completion_score -= 20
        reasons.append("CTA до завершения смысловой цепочки запрещён")

    if role == "trust" and trust_streak >= max_trust_streak:
        chain_completion_score -= 14
        forbidden.add("trust")
        reasons.append("достигнут лимит подряд trust-постов")

    if len(last_roles) >= 2 and last_roles[-1] == last_roles[-2] == role:
        chain_completion_score -= 12
        reasons.append("нельзя ставить 3 одинаковые narrative-роли подряд")

    if role in forbidden:
        narrative_gate = "forbidden"

    if cta_need == "hard" and role != "cta":
        # hard CTA topics should be explicitly marked as CTA role
        chain_completion_score -= 4

    narrative_priority = narrative_gap_score + chain_completion_score
    intent = {
        "trust": "stabilize_trust",
        "pain": "intensify_problem_awareness",
        "reframe": "shift_mental_model",
        "solution": "introduce_method",
        "tool": "enable_first_action",
        "proof": "provide_evidence",
        "bridge": "connect_contexts",
        "cta": "trigger_next_step",
    }.get(role, "stabilize_trust")

    return {
        "narrative_role": role,
        "narrative_gate": narrative_gate,
        "narrative_gap_score": narrative_gap_score,
        "chain_completion_score": chain_completion_score,
        "narrative_priority_score": narrative_priority,
        "narrative_intent": intent,
        "narrative_reason": "; ".join(reasons) if reasons else "роль допустима в текущем контексте цепочки",
    }
