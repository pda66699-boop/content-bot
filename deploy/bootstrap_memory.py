#!/usr/bin/env python3
from __future__ import annotations

import shutil
from pathlib import Path

from telegram_ingest.config import MEMORY_DIR, SOURCE_MEMORY_DIR


RUNTIME_ONLY_NAMES = {
    "telegram_ingest.sqlite3",
    "telegram_polling_offset.json",
    "telegram_ui_state.json",
}
RUNTIME_ONLY_DIRS = {"raw_updates"}
ALWAYS_SYNC_NAMES = {
    "content_plan_roadmap.json",
}


def copy_missing_seed_files() -> list[Path]:
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    copied: list[Path] = []
    for source in SOURCE_MEMORY_DIR.iterdir():
        target = MEMORY_DIR / source.name
        if source.name in RUNTIME_ONLY_NAMES or source.name in RUNTIME_ONLY_DIRS:
            continue
        if source.name in ALWAYS_SYNC_NAMES:
            if source.is_dir():
                if target.exists():
                    shutil.rmtree(target)
                shutil.copytree(source, target)
            else:
                shutil.copy2(source, target)
            copied.append(target)
            continue
        if target.exists():
            continue
        if source.is_dir():
            shutil.copytree(source, target)
        else:
            shutil.copy2(source, target)
        copied.append(target)
    return copied


def main() -> int:
    copied = copy_missing_seed_files()
    print(f"Memory bootstrap complete, copied {len(copied)} item(s) into {MEMORY_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
