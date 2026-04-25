#!/usr/bin/env python3
"""Summarize MHC-II CSV/TSV/JSONL files without loading them all into memory."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.research.mhc2.data import (
    iter_generic_records,
    iter_hlaiipred_positive_csv,
    read_jsonl,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inputs", nargs="+", type=Path)
    parser.add_argument("--source", default=None)
    args = parser.parse_args()

    peptide_counts: Counter[str] = Counter()
    allele_counts: Counter[str] = Counter()
    split_counts: Counter[str] = Counter()
    source_counts: Counter[str] = Counter()
    rows = 0

    for path in args.inputs:
        for record in _iter_records(path, args.source):
            rows += 1
            peptide_counts[record.peptide] += 1
            for allele in record.alleles:
                allele_counts[allele] += 1
            split_counts[record.split or "none"] += 1
            source_counts[record.source] += 1

    summary = {
        "rows": rows,
        "unique_peptides": len(peptide_counts),
        "unique_alleles": len(allele_counts),
        "splits": dict(sorted(split_counts.items())),
        "sources": dict(sorted(source_counts.items())),
        "top_alleles": allele_counts.most_common(20),
        "top_repeated_peptides": peptide_counts.most_common(10),
    }
    print(json.dumps(summary, indent=2, sort_keys=True))


def _iter_records(path: Path, source: str | None):
    if path.suffix.lower() == ".jsonl":
        yield from read_jsonl(path)
    elif path.name.endswith("_positive.csv") or "hlaiipred" in (source or ""):
        yield from iter_hlaiipred_positive_csv(path)
    else:
        yield from iter_generic_records(path, source=source or path.stem)


if __name__ == "__main__":
    main()
