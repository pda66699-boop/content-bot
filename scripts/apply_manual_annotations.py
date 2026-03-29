#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path


INDEX_PATH = Path("content-bot/memory/posts_index.jsonl")
ANNOTATIONS_PATH = Path("content-bot/memory/manual_annotations.json")


def load_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_jsonl(rows: list[dict], path: Path) -> None:
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )


def main() -> int:
    rows = load_jsonl(INDEX_PATH)
    annotations = json.loads(ANNOTATIONS_PATH.read_text(encoding="utf-8"))

    applied = 0
    for row in rows:
        patch = annotations.get(row["post_id"])
        if not patch:
            continue
        row.update(patch)
        row["manual_review_required"] = False
        applied += 1

    write_jsonl(rows, INDEX_PATH)
    print(f"Applied {applied} annotations to {INDEX_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
