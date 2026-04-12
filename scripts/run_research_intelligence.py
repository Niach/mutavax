#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "backend"

if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.research_intelligence import run_research_cycle  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the cancerstudio daily research intelligence loop."
    )
    parser.add_argument(
        "--as-of",
        help="Override the run date in YYYY-MM-DD format.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch and synthesize results without updating state or cache.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    run_date = None
    if args.as_of:
        run_date = __import__("datetime").date.fromisoformat(args.as_of)

    summary = run_research_cycle(
        repo_root=REPO_ROOT,
        run_date=run_date,
        write_outputs_flag=not args.dry_run,
    )

    print(f"Research run date: {summary.run_date}")
    print(f"Window: {summary.window_start} -> {summary.window_end}")
    print(f"Items: {summary.item_count}")
    print(f"Findings: {summary.finding_count}")
    print(f"Brief: {summary.brief_path}")
    print(f"Backlog: {summary.backlog_path}")
    if summary.source_failures:
        print("Source failures:")
        for failure in summary.source_failures:
            print(f"- {failure.source_id}: {failure.message}")
    else:
        print("Source failures: none")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
