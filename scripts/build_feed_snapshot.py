#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path


def load_rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def main() -> int:
    rows = load_rows(Path("content-bot/memory/posts_index.jsonl"))
    recent = rows[-12:]

    lines = [
        "# Current Feed Snapshot",
        "",
        "## Последние 12 постов",
    ]

    for row in recent:
        lines.append(f"- {row['date']} | {row['title_hook']}")
        lines.append(f"  Тема: {row['primary_theme'] or 'TODO'}")
        lines.append(f"  Роль: {row['content_role']}")
        lines.append(f"  Тезис: {row['core_thesis'] or 'TODO'}")

    ai_recent = sum(int(row["mentions_ai"]) for row in recent)
    cta_recent = sum(int(row["cta_present"]) for row in recent)

    lines.extend(
        [
            "",
            "## Быстрые выводы",
            f"- ИИ-постов в последних 12: {ai_recent}",
            f"- Постов с CTA в последних 12: {cta_recent}",
            "- Если пользователь предлагает свою тему, planner должен сначала проверить ее на повтор относительно этого окна.",
            "- Если тема уместна, ее нужно не отвергать, а упаковать в лучший угол и формат для текущего состояния ленты."
        ]
    )

    output = Path("content-bot/memory/current_feed_snapshot.md")
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
