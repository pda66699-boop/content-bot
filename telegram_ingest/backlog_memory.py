from __future__ import annotations

import html
import json
import re
from datetime import date

from .config import CONTENT_BACKLOG_PATH


def load_backlog() -> list[dict]:
    if not CONTENT_BACKLOG_PATH.exists():
        return []
    return json.loads(CONTENT_BACKLOG_PATH.read_text(encoding="utf-8"))


def save_backlog(items: list[dict]) -> None:
    CONTENT_BACKLOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONTENT_BACKLOG_PATH.write_text(json.dumps(items, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


PILLAR_TAG_ALIASES = {
    "разговорный": "conversational",
    "разговорная": "conversational",
    "жизненная": "conversational",
    "личная": "conversational",
    "🗣": "conversational",
    "экспертный": "expert",
    "экспертная": "expert",
    "🧠": "expert",
    "денежный": "money",
    "денежная": "money",
    "продающий": "money",
    "💸": "money",
}


def detect_desired_pillar(line: str) -> tuple[str | None, str]:
    working = line.strip()

    bracket_match = re.match(r"^\[(.*?)\]\s*(.+)$", working)
    if bracket_match:
        tag = bracket_match.group(1).strip().lower()
        pillar = PILLAR_TAG_ALIASES.get(tag)
        if pillar:
            return pillar, bracket_match.group(2).strip()

    prefix_match = re.match(r"^(разговорн\w*|экспертн\w*|денежн\w*|личн\w*|жизненн\w*)[:\-]\s*(.+)$", working, flags=re.IGNORECASE)
    if prefix_match:
        pillar = PILLAR_TAG_ALIASES.get(prefix_match.group(1).strip().lower())
        if pillar:
            return pillar, prefix_match.group(2).strip()

    for marker, pillar in PILLAR_TAG_ALIASES.items():
        if marker and working.startswith(marker):
            cleaned = working[len(marker) :].strip(" :-")
            return pillar, cleaned or working

    return None, working


def infer_theme_pillar(theme: str) -> str:
    normalized = theme.lower().replace("ё", "е")
    if any(token in normalized for token in ("жизн", "отдых", "пауза", "инсайт", "отношение", "сует", "выбор", "свобод")):
        return "conversational"
    if any(token in normalized for token in ("диагност", "стад", "кризис", "деньг", "расход", "издерж", "потер", "прибыл", "кейс")):
        return "money"
    return "expert"


def parse_theme_entries(raw_text: str) -> list[dict]:
    text = raw_text.strip()
    if not text:
        return []

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    parsed: list[dict] = []
    for line in lines:
        cleaned = re.sub(r"^\d+[\).\s-]+", "", line).strip()
        cleaned = re.sub(r"^[•*\-]\s*", "", cleaned).strip()
        desired_pillar, cleaned = detect_desired_pillar(cleaned)
        if cleaned:
            parsed.append(
                {
                    "theme": cleaned,
                    "desired_pillar": desired_pillar or infer_theme_pillar(cleaned),
                }
            )

    if not parsed:
        return []

    if len(parsed) == 1 and "\n" not in raw_text:
        return parsed
    return parsed


def parse_theme_list(raw_text: str) -> list[str]:
    return [item["theme"] for item in parse_theme_entries(raw_text)]


def add_themes_to_backlog(raw_text: str, source: str = "user") -> list[dict]:
    entries = parse_theme_entries(raw_text)
    if not entries:
        return []

    backlog = load_backlog()
    existing = {item.get("theme", "").strip().lower() for item in backlog}
    added: list[dict] = []
    for entry in entries:
        theme = entry["theme"]
        normalized = theme.strip().lower()
        if not normalized or normalized in existing:
            continue
        row = {
            "theme": theme.strip(),
            "desired_pillar": entry.get("desired_pillar") or infer_theme_pillar(theme),
            "status": "saved",
            "source": source,
            "created_at": str(date.today()),
            "notes": "",
        }
        backlog.append(row)
        added.append(row)
        existing.add(normalized)

    if added:
        save_backlog(backlog)
    return added


def add_structured_theme_to_backlog(
    theme: str,
    desired_pillar: str | None = None,
    source: str = "user",
    notes: str = "",
    context: dict | None = None,
) -> dict | None:
    cleaned_theme = (theme or "").strip()
    if not cleaned_theme:
        return None

    backlog = load_backlog()
    normalized = cleaned_theme.lower()
    if any((item.get("theme") or "").strip().lower() == normalized for item in backlog):
        return None

    row = {
        "theme": cleaned_theme,
        "desired_pillar": desired_pillar or infer_theme_pillar(cleaned_theme),
        "status": "saved",
        "source": source,
        "created_at": str(date.today()),
        "notes": (notes or "").strip(),
        "context": context or {},
    }
    backlog.append(row)
    save_backlog(backlog)
    return row


def format_backlog_save_confirmation(added: list[dict]) -> str:
    if not added:
        return "Новых тем не сохранил: похоже, они уже были в памяти или сообщение оказалось пустым."
    lines = [f"💾 Сохранил тем: {len(added)}", ""]
    pillar_labels = {
        "conversational": "разговорная",
        "expert": "экспертная",
        "money": "денежная",
    }
    for idx, item in enumerate(added, start=1):
        label = pillar_labels.get(item.get("desired_pillar"))
        source_kind = ((item.get("context") or {}).get("source_kind") if isinstance(item.get("context"), dict) else None) or item.get("source")
        kind_label = "кейс" if source_kind == "verified_case" or source_kind == "case_research" else None
        prefix = "🌐 " if kind_label else ""
        parts = [part for part in (kind_label, label) if part]
        suffix = f" <i>({' · '.join(parts)})</i>" if parts else ""
        lines.append(f"{idx}. {prefix}{html.escape(item['theme'])}{suffix}")
    lines.append("")
    lines.append("Эти темы теперь лежат в backlog и позже могут использоваться в планировании.")
    return "\n".join(lines)


def get_backlog_topics(limit: int = 5) -> list[dict]:
    items = [item for item in load_backlog() if item.get("status") == "saved" and item.get("theme")]
    return list(reversed(items))[:limit]


def mark_backlog_theme_used(theme: str) -> bool:
    backlog = load_backlog()
    changed = False
    for item in backlog:
        if item.get("theme") == theme and item.get("status") == "saved":
            item["status"] = "used"
            changed = True
            break
    if changed:
        save_backlog(backlog)
    return changed


def delete_backlog_theme(theme: str) -> bool:
    backlog = load_backlog()
    updated = [item for item in backlog if item.get("theme") != theme]
    if len(updated) == len(backlog):
        return False
    save_backlog(updated)
    return True
