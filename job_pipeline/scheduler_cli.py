"""Headless wake entry for the per-user Windows scheduled task."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

# The scheduled task starts Python directly, outside Electron's PYTHONPATH.
# Prepend the packaged runtime so named ZoneInfo recurrences work on Windows.
_BUNDLED_RUNTIME = Path(__file__).resolve().parent.parent / "python-runtime"
if _BUNDLED_RUNTIME.is_dir() and str(_BUNDLED_RUNTIME) not in sys.path:
    sys.path.insert(0, str(_BUNDLED_RUNTIME))

from .service import build_default_runtime


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run due Expedient Employment schedules.")
    parser.add_argument("command", choices=("run-due",))
    parser.add_argument("--project-root", type=Path, default=Path(__file__).resolve().parent.parent)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=10)
    args = parser.parse_args(argv)
    runtime = build_default_runtime(args.project_root, args.data_root)
    try:
        results = runtime.scheduler.run_due(
            now=datetime.now(timezone.utc),
            limit=max(1, min(args.limit, 50)),
        )
    finally:
        runtime.close()
    failed = sum(item["status"] not in {"succeeded", "dry_run"} for item in results)
    print(f"Scheduled wake completed: {len(results)} run(s), {failed} non-success status(es).")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
