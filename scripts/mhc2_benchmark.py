#!/usr/bin/env python3
"""Evaluate an MHC-II prediction CSV/TSV with cancerstudio metrics."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.research.mhc2.benchmark import evaluate_prediction_file, write_metrics_json


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("predictions", type=Path)
    parser.add_argument("--threshold", type=float, default=0.5)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()

    metrics = evaluate_prediction_file(args.predictions, threshold=args.threshold)
    if args.out:
        write_metrics_json(metrics, args.out)
    print(json.dumps(metrics, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

