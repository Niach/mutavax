#!/usr/bin/env python3
"""Fetch direct-download MHC-II research datasets with provenance manifests."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.research.mhc2.fetch import available_sources, fetch_source


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", nargs="?", help="Source key to fetch.")
    parser.add_argument("--out", type=Path, default=ROOT / "data" / "mhc2")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--list", action="store_true")
    args = parser.parse_args()

    if args.list:
        for source in available_sources():
            print(f"{source.key}\t{source.role}\t{source.url}")
        return
    if not args.source:
        parser.error("source is required unless --list is used")

    manifest = fetch_source(args.source, args.out / args.source, dry_run=args.dry_run)
    print(json.dumps(manifest, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

