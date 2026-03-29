#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from telegram_ingest.editorial_metadata import (  # noqa: E402
    DEFAULT_NOVELTY_WINDOW_DAYS,
    normalize_editorial_metadata,
)
from telegram_ingest.editorial_extractor import infer_editorial_metadata_from_post  # noqa: E402


DATE_RE = re.compile(r"^\d{1,2} [A-Z][a-z]+ \d{4}$")
TIME_RE = re.compile(r"^\d{2}:\d{2}$")
REACTION_LINE_RE = re.compile(r"^[❤🔥⚡👍🤪😁😱🥰👌💯🤍🫨🙌🏿⭐🎉\d\s]+$")
HASHTAG_RE = re.compile(r"#([A-Za-zА-Яа-я0-9_]+)")

CHANNEL_PREFIXES = (
    "Денис Педченко | Архитектура системного бизнеса",
    "Денис Педченко | Арх…",
)

SERVICE_SUBSTRINGS = (
    "pinned this message",
    "Channel ",
    "created",
    "changed",
    "Not included, change data exporting settings to download.",
)

MEDIA_MARKERS = {
    "Photo",
    "Video file",
    "Voice message",
    "Video note",
    "Sticker",
    "Animation",
    "Poll",
}

CTA_PATTERNS = (
    "@pda33",
    "диагностик",
    "комментар",
    "пиши,",
    "пишите,",
    "пишите ",
    "напиши",
    "напишите",
    "пройди диагност",
    "посмотрите видео",
    "посмотри видео",
)

AI_REGEXES = (
    re.compile(r"\bии\b", re.IGNORECASE),
    re.compile(r"\bai\b", re.IGNORECASE),
    re.compile(r"\bgpt\b", re.IGNORECASE),
    re.compile(r"chatgpt", re.IGNORECASE),
    re.compile(r"нейросет", re.IGNORECASE),
    re.compile(r"нейросотрудник", re.IGNORECASE),
)


@dataclass
class ParsedPost:
    date_label: str
    time_label: str
    lines: list[str]


def is_channel_header(line: str) -> bool:
    return any(line.startswith(prefix) for prefix in CHANNEL_PREFIXES)


def is_service_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return True
    if stripped == "Д":
        return True
    if TIME_RE.match(stripped):
        return True
    if stripped in MEDIA_MARKERS:
        return True
    if stripped.startswith("In reply to this message"):
        return True
    if any(token in stripped for token in SERVICE_SUBSTRINGS):
        return True
    if re.match(r"^\d+×\d+,", stripped):
        return True
    if re.match(r"^\d{1,2}:\d{2},\s+\d+(\.\d+)?\s+[KMG]B$", stripped):
        return True
    if re.match(r"^\d+(\.\d+)?\s+[KMG]B$", stripped):
        return True
    return False


def clean_post_lines(lines: Iterable[str]) -> list[str]:
    cleaned: list[str] = []
    for raw_line in lines:
        line = raw_line.strip()
        if is_service_line(line):
            continue
        if REACTION_LINE_RE.match(line):
            continue
        cleaned.append(line)
    while cleaned and not cleaned[-1]:
        cleaned.pop()
    return cleaned


def is_noise_post(lines: list[str]) -> bool:
    if not lines:
        return True
    first_line = lines[0].strip()
    if re.match(r"^\d{1,2}:\d{2},\s+\d+(\.\d+)?\s+[KMG]B$", first_line):
        return True
    if re.match(r"^\d+(\.\d+)?\s+[KMG]B$", first_line):
        return True
    return False


def iter_posts(text: str) -> Iterable[ParsedPost]:
    lines = text.splitlines()
    current_date = ""
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if DATE_RE.match(line):
            current_date = line
            i += 1
            continue

        if current_date and is_channel_header(line):
            time_label = ""
            content_start = i + 1

            if i >= 2 and TIME_RE.match(lines[i - 1].strip()):
                time_label = lines[i - 1].strip()
            elif i >= 3 and TIME_RE.match(lines[i - 2].strip()):
                time_label = lines[i - 2].strip()

            if content_start < len(lines) and lines[content_start].strip() == "Д":
                content_start += 1
            if content_start < len(lines) and TIME_RE.match(lines[content_start].strip()):
                time_label = lines[content_start].strip()
                content_start += 1

            content_lines: list[str] = []
            j = content_start
            while j < len(lines):
                next_line = lines[j].strip()
                if DATE_RE.match(next_line) or is_channel_header(next_line):
                    break
                content_lines.append(lines[j])
                j += 1

            cleaned = clean_post_lines(content_lines)
            if cleaned and not is_noise_post(cleaned):
                yield ParsedPost(date_label=current_date, time_label=time_label, lines=cleaned)
            i = j
            continue

        i += 1


def normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def infer_content_role(text: str) -> str:
    lower = text.lower()
    if (
        "кейс" in lower
        or "история" in lower
        or "domino" in lower
        or "бренд" in lower
        or "компания" in lower and "результат" in lower
    ):
        return "case"
    if any(token in lower for token in ("почему", "что происходит", "дело не", "часто", "ошибка")):
        return "diagnostic"
    if any(
        token in lower
        for token in ("как ", "что с этим делать", "инструмент", "разобрал", "разбер", "гайд", "шаг", "признак")
    ):
        return "applied"
    return "expert"


def infer_format(text: str) -> str:
    lower = text.lower()
    if any(token in lower for token in ("я", "мне", "мой путь", "лично", "иногда")):
        return "expert"
    return "expert"


def infer_funnel_stage(text: str, cta_present: bool) -> str:
    lower = text.lower()
    if cta_present and any(token in lower for token in ("диагностик", "@pda33", "обратиться", "бот")):
        return "solution-aware"
    if any(token in lower for token in ("почему", "проблем", "ошибка", "симптом")):
        return "problem-aware"
    return "aware"


def build_record(post: ParsedPost) -> dict:
    text = "\n\n".join(post.lines)
    normalized = normalize_whitespace(text)
    title_hook = post.lines[0]
    hashtags = HASHTAG_RE.findall(text)
    lower = normalized.lower()
    cta_present = any(pattern in lower for pattern in CTA_PATTERNS)
    mentions_ai = any(regex.search(normalized) for regex in AI_REGEXES)

    date_iso = convert_date_label(post.date_label)
    post_id = f"{date_iso}_{post.time_label.replace(':', '') or '0000'}"

    record = normalize_editorial_metadata({
        "post_id": post_id,
        "date": date_iso,
        "time": post.time_label or None,
        "source": "telegram_export",
        "title_hook": title_hook,
        "body_text": text,
        "body_summary": normalized[:280],
        "primary_theme": None,
        "secondary_themes": [],
        "format": infer_format(normalized),
        "content_role": infer_content_role(normalized),
        "funnel_stage": infer_funnel_stage(normalized, cta_present),
        "core_thesis": None,
        "cta_type": "soft" if cta_present else "none",
        "cta_present": cta_present,
        "cta_target": infer_cta_target(lower) if cta_present else None,
        "hashtags": hashtags,
        "mentions_ai": mentions_ai,
        "mentions_offer": cta_present,
        "novelty_keys": [],
        "manual_review_required": True,
        "primary_thesis": None,
        "secondary_theses": [],
        "angle": "",
        "content_goal": infer_content_role(normalized),
        "business_dimensions": [],
        "format_type": infer_format(normalized),
        "novelty_window_days": DEFAULT_NOVELTY_WINDOW_DAYS,
    })
    return infer_editorial_metadata_from_post(record)


def infer_cta_target(lower: str) -> str:
    if "@pda33" in lower:
        return "personal_dm"
    if "бот" in lower:
        return "bot"
    if "комментар" in lower:
        return "comments"
    if "диагностик" in lower:
        return "diagnostic"
    if "видео" in lower:
        return "video"
    return "other"


def convert_date_label(date_label: str) -> str:
    months = {
        "January": "01",
        "February": "02",
        "March": "03",
        "April": "04",
        "May": "05",
        "June": "06",
        "July": "07",
        "August": "08",
        "September": "09",
        "October": "10",
        "November": "11",
        "December": "12",
    }
    day, month_name, year = date_label.split()
    return f"{year}-{months[month_name]}-{int(day):02d}"


def write_jsonl(records: Iterable[dict], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Parse Telegram TXT export into JSONL post cards.")
    parser.add_argument("input", type=Path, help="Path to Telegram export messages.txt")
    parser.add_argument("output", type=Path, help="Path to output JSONL file")
    args = parser.parse_args()

    text = args.input.read_text(encoding="utf-8")
    records = [build_record(post) for post in iter_posts(text)]
    write_jsonl(records, args.output)

    print(f"Parsed {len(records)} posts into {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
