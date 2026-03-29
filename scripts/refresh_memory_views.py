#!/usr/bin/env python3
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def run(script_name: str) -> None:
    subprocess.run(
        [sys.executable, str(ROOT / "scripts" / script_name)],
        check=True,
        cwd=ROOT.parent,
    )


def main() -> int:
    run("summarize_posts_index.py")
    run("build_feed_snapshot.py")
    print("Memory views refreshed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
