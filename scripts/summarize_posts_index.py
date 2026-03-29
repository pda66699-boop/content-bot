#!/usr/bin/env python3
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path


def load_rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def main() -> int:
    rows = load_rows(Path("content-bot/memory/posts_index.jsonl"))
    hashtags = Counter()
    roles = Counter()
    ai_count = 0
    cta_count = 0

    for row in rows:
        hashtags.update(row["hashtags"])
        roles[row["content_role"]] += 1
        ai_count += int(row["mentions_ai"])
        cta_count += int(row["cta_present"])

    lines = [
        "# Posts Index Summary",
        "",
        f"- Всего карточек: {len(rows)}",
        f"- Период: {rows[0]['date']} -> {rows[-1]['date']}",
        f"- Постов с ИИ: {ai_count}",
        f"- Постов с CTA: {cta_count}",
        "",
        "## Роли контента",
    ]

    for role, count in roles.most_common():
        lines.append(f"- {role}: {count}")

    lines.extend(["", "## Топ хэштегов"])
    for hashtag, count in hashtags.most_common(10):
        lines.append(f"- #{hashtag}: {count}")

    lines.extend(["", "## Последние 10 постов"])
    for row in rows[-10:]:
        time_label = row["time"] or "00:00"
        lines.append(f"- {row['date']} {time_label} | {row['title_hook']}")

    output = Path("content-bot/memory/posts_index_summary.md")
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
