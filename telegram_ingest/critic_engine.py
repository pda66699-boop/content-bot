from __future__ import annotations

import json
import re
from pathlib import Path

from .config import POSTS_INDEX_PATH
from .editorial_extractor import infer_editorial_metadata_from_post
from .editorial_similarity import classify_topic_novelty
from .knowledge import load_editorial_feedback, load_terminology_registry
from .positioning import get_positioning_flags


AI_WORDS = ("ии", "ai", "gpt", "chatgpt", "нейросет", "нейро")
PRIMARY_SEGMENT_TOKENS = ("сервис", "агентств", "юрид", "консалт", "школ", "образов", "творчес", "логист", "услуг")
NEW_MODEL_TOKENS = (
    "потер",
    "утеч",
    "прибыл",
    "марж",
    "деньг",
    "выруч",
    "все на мне",
    "всё на мне",
    "без меня",
    "узк",
    "ручн",
    "ответствен",
    "дедлайн",
    "передел",
    "собственник",
)
TRANSITION_TOPIC_TOKENS = (
    "делег",
    "найм",
    "команд",
    "сотруд",
    "роль",
    "оргструкт",
    "регламент",
    "процесс",
    "управл",
    "подряд",
    "контрол",
)
HYPE_PATTERNS = (
    "волшебн",
    "секрет успеха",
    "за 1 день",
    "навсегда изменит",
    "революцион",
    "уникальнейший",
)
FORBIDDEN_VOICE_MARKERS = (
    "цкп",
    "qa-владел",
    "qa владел",
    "владелец процесса",
    "архитектура управления",
    "контур управления",
    "декомпозици",
    "оркестрац",
)
CORPORATE_JARGON_MARKERS = (
    "измерим",
    "eskala",
)
STOP_WORDS_PATH = Path(__file__).resolve().parents[1] / "memory" / "stop_words.json"
GOLDEN_STYLE_SET_PATH = Path(__file__).resolve().parents[1] / "memory" / "golden_style_set.json"


def load_rows() -> list[dict]:
    if not POSTS_INDEX_PATH.exists():
        return []
    return [json.loads(line) for line in POSTS_INDEX_PATH.read_text(encoding="utf-8").splitlines() if line.strip()]


def load_stop_words() -> dict:
    if not STOP_WORDS_PATH.exists():
        return {}
    stop_words = json.loads(STOP_WORDS_PATH.read_text(encoding="utf-8"))
    terminology = load_terminology_registry()
    taboo = list(stop_words.get("banned_phrases", []))
    for phrase in terminology.get("taboo_phrases", []):
        if phrase not in taboo:
            taboo.append(phrase)
    stop_words["banned_phrases"] = taboo
    return stop_words


def load_golden_style_set() -> dict:
    if not GOLDEN_STYLE_SET_PATH.exists():
        return {}
    return json.loads(GOLDEN_STYLE_SET_PATH.read_text(encoding="utf-8"))


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower()).strip()


def text_overlap(a: str, b: str) -> float:
    aw = set(re.findall(r"[a-zа-я0-9]+", normalize(a)))
    bw = set(re.findall(r"[a-zа-я0-9]+", normalize(b)))
    if not aw or not bw:
        return 0.0
    return len(aw & bw) / len(aw | bw)


def phrase_overlap(a: str, b: str, n: int = 4) -> float:
    def grams(text: str) -> set[tuple[str, ...]]:
        words = re.findall(r"[a-zа-я0-9]+", normalize(text))
        return {tuple(words[i:i + n]) for i in range(len(words) - n + 1)}
    ag = grams(a)
    bg = grams(b)
    if not ag or not bg:
        return 0.0
    return len(ag & bg) / min(len(ag), len(bg))


def detect_main_issue(text: str) -> tuple[str, str]:
    normalized = normalize(text)
    if any(pattern in normalized for pattern in HYPE_PATTERNS):
        return "style_hype", "В тексте есть признаки маркетингового или инфобизнесового перегрева."
    if len(re.findall(r"[.!?]\s*", text)) <= 1:
        return "weak_structure", "Текст выглядит недоразделённым и может читаться как сплошной блок мысли."
    if sum(1 for line in text.splitlines() if line.strip().startswith("–")) > 5:
        return "list_heavy", "Текст слишком уходит в список и может потерять живую авторскую подачу."
    return "none", "Критичной структурной проблемы не найдено."


def detect_stop_word_risk(text: str, stop_words: dict) -> tuple[str, str | None]:
    normalized = normalize(text)
    for phrase in stop_words.get("banned_phrases", []):
        if normalize(phrase) in normalized:
            return "medium", f"В тексте есть запрещенная или нежелательная фраза: '{phrase}'."
    hits = []
    for phrase in stop_words.get("template_phrases_to_avoid", []):
        if normalize(phrase) in normalized:
            hits.append(phrase)
    if hits:
        return "medium", f"В тексте остались шаблонные связки: {', '.join(hits[:2])}."
    return "low", None


def detect_golden_copy_risk(text: str, rows: list[dict], golden_style_set: dict) -> tuple[str, str | None]:
    golden_ids = set(golden_style_set.get("post_ids", []))
    if not golden_ids:
        return "low", None
    golden_rows = [row for row in rows if row.get("post_id") in golden_ids]
    best_score = 0.0
    best_match = None
    for row in golden_rows:
        score = phrase_overlap(text, row.get("body_text", ""))
        if score > best_score:
            best_score = score
            best_match = row
    if best_score >= 0.18 and best_match is not None:
        return "high", f"Черновик слишком близко подходит к эталонному посту {best_match.get('date')} '{best_match.get('title_hook')}'."
    if best_score >= 0.1 and best_match is not None:
        return "medium", f"Есть риск слишком буквальной опоры на эталонный пост {best_match.get('date')}."
    return "low", None


def detect_editorial_feedback_risk(text: str, feedback_rows: list[dict]) -> tuple[str, str | None]:
    normalized = normalize(text)
    active = [row.get("summary", "").lower() for row in feedback_rows if row.get("status") == "active"]
    if any("шаблонно" in row for row in active):
        repeated_markers = sum(int(token in normalized) for token in ("главный вопрос здесь", "поэтому", "если смотреть глубже"))
        if repeated_markers >= 2:
            return "medium", "Текст всё ещё звучит слишком шаблонно относительно накопленных замечаний."
    if any("узнаваемую ситуацию" in row or "не пост-тезис" in row or "с примерами" in row for row in active):
        has_example = any(token in normalized for token in ("например", "допустим", "на этапе", "если у вас"))
        has_tool = sum(int(token in normalized) for token in ("3 вещи", "3 вопрос", "4 признака", "5 шаг", "смотреть на", "полезно проверить")) >= 1
        if not has_example or not has_tool:
            return "medium", "Текст остаётся слишком общим: не хватает примера из бизнеса или понятного инструмента внутри самого поста."
    return "low", None


def detect_repeat_risk(text: str, rows: list[dict]) -> tuple[str, str | None]:
    recent = rows[-12:]
    best_score = 0.0
    best_match = None
    for row in recent:
        score = text_overlap(text, row.get("body_text", ""))
        if score > best_score:
            best_score = score
            best_match = row

    if best_score >= 0.42 and best_match is not None:
        return "high", f"Текст заметно пересекается с постом {best_match.get('date')} '{best_match.get('title_hook')}'."
    if best_score >= 0.24 and best_match is not None:
        return "medium", f"Есть смысловое пересечение с недавним постом {best_match.get('date')}."
    return "low", None


def detect_semantic_repeat_risk(text: str, rows: list[dict]) -> tuple[str, str | None]:
    """Detect semantic repeat risk using editorial metadata rather than lexical overlap."""

    if not rows:
        return "low", None
    candidate = infer_editorial_metadata_from_post(
        {
            "title_hook": text.splitlines()[0] if text.splitlines() else text[:120],
            "primary_theme": text.splitlines()[0] if text.splitlines() else text[:120],
            "body_text": text,
            "body_summary": text[:280],
            "content_role": "diagnostic" if any(token in normalize(text) for token in ("проблем", "ошиб", "симптом", "потер")) else "expert",
            "format": "expert",
        },
        prefer_llm=False,
    )
    verdict = classify_topic_novelty(candidate, rows[-20:])
    best_match = verdict.get("best_match") or {}
    status = verdict.get("status") or "fresh"
    if status == "too_close":
        return "high", f"Текст слишком близок по смыслу к посту {best_match.get('date')} '{best_match.get('title_hook')}'."
    if status in {"reframe_allowed", "series_continuation"}:
        return "medium", f"Текст пересекается по смыслу с постом {best_match.get('date')} и требует другого угла подачи."
    return "low", None


def detect_ai_balance_risk(text: str, rows: list[dict]) -> str:
    normalized = normalize(text)
    recent_ai_count = sum(int(row.get("mentions_ai", False)) for row in rows[-12:])
    mentions_ai = any(word in normalized for word in AI_WORDS)
    if mentions_ai and recent_ai_count >= 4:
        return "medium"
    return "low"


def detect_cta_risk(text: str) -> str:
    normalized = normalize(text)
    cta_hits = sum(
        int(token in normalized)
        for token in ("@pda33", "диагност", "пишите", "напишите", "пиши", "в комментар")
    )
    if cta_hits >= 2:
        return "medium"
    return "low"


def detect_legacy_positioning_risk(text: str) -> tuple[str, str | None]:
    normalized = normalize(text)
    new_hits = sum(1 for token in NEW_MODEL_TOKENS if token in normalized)
    transition_hits = sum(1 for token in TRANSITION_TOPIC_TOKENS if token in normalized)
    segment_hits = sum(1 for token in PRIMARY_SEGMENT_TOKENS if token in normalized)

    if transition_hits >= 1 and new_hits == 0 and segment_hits == 0:
        return "medium", "Текст звучит как старая широкая экспертная тема и не дотягивает до новой рамки: мало языка потерь, денег, зависимости от собственника или целевого сегмента."
    if transition_hits == 0 and new_hits == 0:
        return "medium", "Текст слишком общий и не попадает в актуальное позиционирование канала: не видно ни сегмента, ни управленческих потерь, ни новой продуктовой логики."
    return "low", None


def detect_synthetic_case_risk(text: str) -> tuple[str, str | None]:
    normalized = normalize(text)
    exact_metric_patterns = (
        r"\b\d+\s*%",
        r"\b\d+\s*час",
        r"\b\d+\s*спринт",
        r"\b\d+\s*недел",
        r"\b\d+\s*дн",
    )
    fabricated_case_markers = (
        "в одной компании, с которой я работал",
        "в одной компании с которой я работал",
        "мы переписали",
        "через два спринта",
        "через 2 спринта",
        "количество вопросов к собственнику упало",
        "собственник получил",
    )
    metric_hits = sum(
        len(re.findall(pattern, normalized))
        for pattern in exact_metric_patterns
    )
    fabricated_hits = sum(int(marker in normalized) for marker in fabricated_case_markers)

    if fabricated_hits >= 2 and metric_hits >= 1:
        return "high", "Текст выглядит как синтетический кейс: есть слишком точные результаты и детали, которые звучат придуманно."
    if fabricated_hits >= 1 and metric_hits >= 1:
        return "medium", "Есть риск выдуманного кейса: текст использует точные детали и цифры без достаточной опоры на подтверждённый контекст."
    return "low", None


def detect_corporate_jargon_risk(text: str) -> tuple[str, str | None]:
    normalized = normalize(text)
    jargon_hits: list[str] = []
    if "цкп" in normalized:
        jargon_hits.append("ЦКП")
    if "qa-владел" in normalized or "qa владел" in normalized:
        jargon_hits.append("QA-владелец")
    if "владелец процесса" in normalized:
        jargon_hits.append("владелец процесса")
    if "архитектура управления" in normalized:
        jargon_hits.append("архитектура управления")
    if "контур управления" in normalized:
        jargon_hits.append("контур управления")
    if "декомпозици" in normalized:
        jargon_hits.append("декомпозиция")
    if "оркестрац" in normalized:
        jargon_hits.append("оркестрация")
    if "эскалац" in normalized:
        jargon_hits.append("эскалация")
    if "измерим" in normalized and "результат" in normalized:
        jargon_hits.append("измеримый результат")

    if len(jargon_hits) >= 2:
        return "high", f"Текст уходит в корпоративно-консультантский язык: {', '.join(jargon_hits[:3])}."
    if len(jargon_hits) == 1:
        return "medium", f"В тексте есть неестественный для голоса автора термин: {jargon_hits[0]}."
    return "low", None


def detect_voice_authenticity_risk(
    text: str,
    synthetic_case_risk: str,
    corporate_jargon_risk: str,
) -> tuple[str, str | None]:
    normalized = normalize(text)
    prompt_artifacts = (
        "и меня это нисколько не удивило",
        "если смотреть глубже",
        "главный разрыв",
        "вопрос здесь простой",
    )
    artifact_hits = [artifact for artifact in prompt_artifacts if artifact in normalized]
    if synthetic_case_risk == "high" or corporate_jargon_risk == "high":
        note_parts = []
        if synthetic_case_risk == "high":
            note_parts.append("синтетический кейс")
        if corporate_jargon_risk == "high":
            note_parts.append("корпоративный язык")
        if artifact_hits:
            note_parts.append("шаблонные артефакты")
        return "high", f"Текст звучит неаутентично для автора: {', '.join(note_parts)}."
    if synthetic_case_risk == "medium" or corporate_jargon_risk == "medium" or artifact_hits:
        note_parts = []
        if synthetic_case_risk == "medium":
            note_parts.append("подозрение на придуманный кейс")
        if corporate_jargon_risk == "medium":
            note_parts.append("слишком консультантский язык")
        if artifact_hits:
            note_parts.append("шаблонные обороты")
        return "medium", f"Есть риск потери авторского голоса: {', '.join(note_parts)}."
    return "low", None


def detect_funnel_fit_note(text: str) -> str | None:
    normalized = normalize(text)
    if any(token in normalized for token in ("стад", "кризис", "жизненного цикла")) and "@adizesbizbot" not in normalized:
        return "Для темы про стадии бизнеса или типичные кризисы можно рассмотреть CTA в @adizesbizbot как мягкий вход в воронку."
    return None


def build_rewrite_guidance(
    main_issue: str,
    repeat_risk: str,
    ai_balance_risk: str,
    stop_word_risk: str = "low",
    golden_copy_risk: str = "low",
    legacy_positioning_risk: str = "low",
    voice_authenticity_risk: str = "low",
) -> str:
    guidance = []
    if repeat_risk == "high":
        guidance.append("Сменить угол подачи и убрать формулировки, близкие к последним постам.")
    if golden_copy_risk == "high":
        guidance.append("Уйти от эталонного поста: сохранить мысль, но полностью пересобрать формулировки и ритм.")
    elif golden_copy_risk == "medium":
        guidance.append("Ослабить сходство с эталонными постами и сделать подачу свободнее.")
    if ai_balance_risk == "medium":
        guidance.append("Сместить фокус с ИИ на архитектуру, роли, процесс или управленческую причину.")
    if legacy_positioning_risk == "medium":
        guidance.append("Сузить тему под сервисный бизнес 60-150 млн и перевести текст в язык потерь, денег, зависимости от собственника или точек управленческого сбоя.")
    if voice_authenticity_risk == "high":
        guidance.append("Полностью убрать синтетический кейс и корпоративный язык: переписать текст как живое наблюдение без выдуманных цифр, ролей и терминов.")
    elif voice_authenticity_risk == "medium":
        guidance.append("Сделать голос живее: убрать казённые термины, точные цифры без источника и всё, что звучит как придуманная кейсовая сцена.")
    if stop_word_risk == "medium":
        guidance.append("Убрать стоп-фразы и шаблонные связки.")
    if main_issue == "style_hype":
        guidance.append("Убрать перегретые обещания и вернуть спокойный деловой тон.")
    if main_issue == "list_heavy":
        guidance.append("Сделать текст более связным и уменьшить долю списков.")
    if main_issue == "weak_structure":
        guidance.append("Разделить мысль на короткие смысловые блоки: проблема, причина, решение, эффект.")
    if not guidance:
        guidance.append("Текст можно использовать как базовый черновик, но стоит слегка усилить конкретику и человеческую интонацию.")
    return " ".join(guidance)


def critic_review_with_rows(text: str, rows: list[dict] | None = None) -> dict:
    """Return critic diagnostics using an optional in-memory archive override."""

    rows = rows if rows is not None else load_rows()
    stop_words = load_stop_words()
    golden_style_set = load_golden_style_set()
    editorial_feedback = load_editorial_feedback()
    positioning_flags = get_positioning_flags()
    main_issue_code, main_issue = detect_main_issue(text)
    repeat_risk, repeat_note = detect_repeat_risk(text, rows)
    semantic_repeat_risk, semantic_repeat_note = detect_semantic_repeat_risk(text, rows)
    risk_order = {"low": 0, "medium": 1, "high": 2}
    if risk_order.get(semantic_repeat_risk, 0) > risk_order.get(repeat_risk, 0):
        repeat_risk = semantic_repeat_risk
        repeat_note = semantic_repeat_note
    ai_balance_risk = detect_ai_balance_risk(text, rows)
    cta_risk = detect_cta_risk(text)
    legacy_positioning_risk, legacy_positioning_note = detect_legacy_positioning_risk(text)
    synthetic_case_risk, synthetic_case_note = detect_synthetic_case_risk(text)
    corporate_jargon_risk, corporate_jargon_note = detect_corporate_jargon_risk(text)
    voice_authenticity_risk, voice_authenticity_note = detect_voice_authenticity_risk(
        text,
        synthetic_case_risk,
        corporate_jargon_risk,
    )
    stop_word_risk, stop_word_note = detect_stop_word_risk(text, stop_words)
    golden_copy_risk, golden_copy_note = detect_golden_copy_risk(text, rows, golden_style_set)
    editorial_feedback_risk, editorial_feedback_note = detect_editorial_feedback_risk(text, editorial_feedback)

    style_risk = "medium" if main_issue_code in {"style_hype", "list_heavy"} or stop_word_risk == "medium" or editorial_feedback_risk == "medium" or corporate_jargon_risk == "medium" else "low"
    method_risk = "medium" if ai_balance_risk == "medium" or legacy_positioning_risk == "medium" or synthetic_case_risk in {"medium", "high"} else "low"
    verdict = "rewrite" if repeat_risk == "high" or main_issue_code == "style_hype" or golden_copy_risk == "high" or voice_authenticity_risk == "high" else "pass"
    funnel_fit_note = detect_funnel_fit_note(text)

    return {
        "verdict": verdict,
        "positioning_flags": positioning_flags,
        "main_issue": main_issue,
        "repeat_risk": repeat_risk,
        "repeat_note": repeat_note,
        "semantic_repeat_risk": semantic_repeat_risk,
        "semantic_repeat_note": semantic_repeat_note,
        "style_risk": style_risk,
        "method_risk": method_risk,
        "cta_risk": cta_risk,
        "legacy_positioning_risk": legacy_positioning_risk,
        "legacy_positioning_note": legacy_positioning_note,
        "synthetic_case_risk": synthetic_case_risk,
        "synthetic_case_note": synthetic_case_note,
        "corporate_jargon_risk": corporate_jargon_risk,
        "corporate_jargon_note": corporate_jargon_note,
        "voice_authenticity_risk": voice_authenticity_risk,
        "voice_authenticity_note": voice_authenticity_note,
        "stop_word_risk": stop_word_risk,
        "stop_word_note": stop_word_note,
        "golden_copy_risk": golden_copy_risk,
        "golden_copy_note": golden_copy_note,
        "editorial_feedback_risk": editorial_feedback_risk,
        "editorial_feedback_note": editorial_feedback_note,
        "funnel_fit_note": funnel_fit_note,
        "rewrite_guidance": build_rewrite_guidance(
            main_issue_code,
            repeat_risk,
            ai_balance_risk,
            stop_word_risk,
            golden_copy_risk,
            legacy_positioning_risk,
            voice_authenticity_risk,
        ),
    }


def critic_review(text: str) -> dict:
    """Return critic diagnostics for one draft post using the stored archive."""

    return critic_review_with_rows(text)
