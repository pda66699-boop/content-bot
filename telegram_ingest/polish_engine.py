from __future__ import annotations

import hashlib
import json
import logging
import re

from .config import MEMORY_DIR
from .critic_engine import critic_review
from .positioning import get_positioning_flags


STYLE_PROFILE_PATH = MEMORY_DIR / "style_profile.json"
USER_PREFERENCES_PATH = MEMORY_DIR / "user_preferences.json"

LOGGER = logging.getLogger(__name__)


def load_style_profile() -> dict:
    if not STYLE_PROFILE_PATH.exists():
        return {}
    try:
        return json.loads(STYLE_PROFILE_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        LOGGER.error("Corrupted style_profile.json: %s — using empty profile", exc)
        return {}


def load_user_preferences() -> dict:
    if not USER_PREFERENCES_PATH.exists():
        return {}
    try:
        return json.loads(USER_PREFERENCES_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        LOGGER.error("Corrupted user_preferences.json: %s — using empty preferences", exc)
        return {}


def normalize_spacing(text: str) -> str:
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def remove_templatey_phrases(text: str) -> str:
    text = text.replace(
        "Если смотреть глубже, вопрос здесь не в инструменте, а в конструкции управления:",
        "Если смотреть практично, проблема обычно не в инструменте, а в том, как собрана сама управленческая логика:",
    )
    text = text.replace(
        "И именно здесь обычно скрыт главный разрыв.",
        "На этом месте как раз и становится видно, где всё начинает сыпаться.",
    )
    text = text.replace(
        "Именно в этот момент многие компании начинают лечить не ту проблему.",
        "В этот момент многие компании начинают чинить не причину, а последствия.",
    )
    text = text.replace(
        "После этого эта зона перестаёт держаться только на ручном включении владельца.",
        "После этого зона уже не висит целиком на ручном включении собственника.",
    )
    text = text.replace(
        "Появляется порядок, снижаются потери и решения перестают зависеть от постоянного ручного вмешательства.",
        "Появляется порядок, снижаются потери, и решения меньше зависят от постоянного ручного вмешательства.",
    )
    text = text.replace(
        "Обычно в этот момент и становится видно, что проблема держится не на системе, а на ручном включении собственника.",
        "В этот момент обычно и видно, что проблема до сих пор держится на ручном включении собственника.",
    )
    text = text.replace(
        "Если будет полезно, в следующем посте могу разобрать это уже на конкретной управленческой сцене.",
        "Если будет полезно, в следующий раз могу разобрать это на конкретной управленческой сцене.",
    )
    return text


def compress_overexplained_lines(text: str) -> str:
    text = text.replace(
        "Суть в том, что бизнес меняется быстрее, чем управленческая модель собственника. И когда она не успевает перестроиться, кризис проявляется не как теория, а как деньги, сроки, нагрузка и потеря контроля.",
        "Бизнес меняется быстрее, чем управленческая модель собственника. И когда она не успевает перестроиться, кризис сразу становится виден в деньгах, сроках и потере контроля.",
    )
    text = text.replace(
        "Проблема здесь редко в одном человеке или одном инструменте. Чаще всего не хватает архитектуры: роли, процесса, понятного результата и ритма контроля.",
        "Проблема здесь редко в одном человеке или инструменте. Обычно не хватает роли, процесса, понятного результата и ритма контроля.",
    )
    return text


def tune_cta(text: str) -> str:
    normalized = text.lower()
    if any(token in normalized for token in ("стад", "кризис", "жизненного цикла")) and "@adizesbizbot" not in text:
        text += "\n\nЕсли хочешь быстро понять, где именно сейчас главный перекос, можешь пройти бесплатную диагностику в @adizesbizbot."
    return text


def split_paragraphs(text: str) -> list[str]:
    return [part.strip() for part in text.split("\n\n") if part.strip()]


def smooth_paragraph_rhythm(text: str) -> str:
    paragraphs = split_paragraphs(text)
    if not paragraphs:
        return text

    smoothed: list[str] = []
    for idx, paragraph in enumerate(paragraphs):
        if idx > 0 and len(paragraph) < 35 and not paragraph.startswith("–") and not paragraph.startswith("#"):
            smoothed[-1] = f"{smoothed[-1]}\n\n{paragraph}"
            continue
        smoothed.append(paragraph)
    return "\n\n".join(smoothed)


def apply_paragraph_terminal_period_policy(text: str, keep_ratio: float = 0.15) -> str:
    paragraphs = split_paragraphs(text)
    if not paragraphs:
        return text

    updated: list[str] = []
    for paragraph in paragraphs:
        if paragraph.startswith("–") or paragraph.startswith("#"):
            updated.append(paragraph)
            continue
        if not paragraph.endswith("."):
            updated.append(paragraph)
            continue

        digest = hashlib.md5(paragraph.encode("utf-8")).hexdigest()
        bucket = int(digest[:8], 16) / 0xFFFFFFFF
        if bucket <= keep_ratio:
            updated.append(paragraph)
        else:
            updated.append(paragraph[:-1].rstrip())
    return "\n\n".join(updated)


def polish_text(
    text: str,
    selected_theme: str | None = None,
    selected_angle: str | None = None,
) -> dict:
    style_profile = load_style_profile()
    user_preferences = load_user_preferences()
    positioning_flags = get_positioning_flags()

    polished = normalize_spacing(text)
    polished = remove_templatey_phrases(polished)
    polished = compress_overexplained_lines(polished)
    polished = smooth_paragraph_rhythm(polished)
    polished = tune_cta(polished)
    polished = apply_paragraph_terminal_period_policy(
        polished,
        keep_ratio=float(user_preferences.get("paragraph_terminal_period_keep_ratio", 0.15)),
    )
    polished = normalize_spacing(polished)

    review = critic_review(polished, selected_theme=selected_theme, selected_angle=selected_angle)
    return {
        "positioning_flags": positioning_flags,
        "style_profile": style_profile,
        "original_text": text,
        "polished_text": polished,
        "critic_review": review,
    }
