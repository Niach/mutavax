#!/usr/bin/env python3
"""Predict peptide presentation scores with a cancerstudio MHC-II checkpoint."""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.research.mhc2.predict import MHC2Predictor


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--pseudosequences", type=Path, required=True)
    parser.add_argument("--input", type=Path, required=True, help="CSV/TSV with peptide and allele columns.")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--device", default="cpu")
    args = parser.parse_args()

    predictor = MHC2Predictor(args.checkpoint, args.pseudosequences, device=args.device)
    delimiter = "\t" if args.input.suffix.lower() in {".tsv", ".txt"} else ","
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.input.open("r", encoding="utf-8", newline="") as source:
        reader = csv.DictReader(source, delimiter=delimiter)
        with args.out.open("w", encoding="utf-8", newline="") as target:
            fieldnames = ["peptide", "allele", "score", "core", "core_offset", "percentile_rank"]
            writer = csv.DictWriter(target, fieldnames=fieldnames)
            writer.writeheader()
            for row in reader:
                prediction = predictor.predict_one(row["peptide"], row["allele"])
                writer.writerow(prediction.__dict__)


if __name__ == "__main__":
    main()

