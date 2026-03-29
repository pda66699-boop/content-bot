from __future__ import annotations

import json
from datetime import date

from .config import EDITORIAL_FEEDBACK_PATH


def record_editorial_feedback(
    summary: str,
    category: str = "quality",
    impact: str = "medium",
    status: str = "active",
    source: str = "user",
) -> dict:
    row = {
        "date": str(date.today()),
        "source": source,
        "category": category,
        "summary": summary.strip(),
        "impact": impact,
        "status": status,
    }
    EDITORIAL_FEEDBACK_PATH.parent.mkdir(parents=True, exist_ok=True)
    with EDITORIAL_FEEDBACK_PATH.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    return row


def build_feedback_confirmation(row: dict) -> str:
    return (
        "Замечание сохранено в долгосрочную память.\n\n"
        f"Категория: {row['category']}\n"
        f"Влияние: {row['impact']}\n"
        f"Суть: {row['summary']}\n\n"
        "Следующие посты и проверки будут учитывать это замечание."
    )
