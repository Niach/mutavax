#!/usr/bin/env python3
"""Normalize MHC-II ligand CSV/TSV files into cancerstudio JSONL."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.research.mhc2.data import deduplicate_records, load_records, write_jsonl
from app.research.mhc2.data import iter_generic_records, iter_hlaiipred_positive_csv, read_jsonl
from app.research.mhc2.splits import assign_cluster_splits, leakage_report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inputs", nargs="+", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--source", default=None)
    parser.add_argument("--split", default=None)
    parser.add_argument("--cluster-split", action="store_true")
    args = parser.parse_args()

    if args.cluster_split:
        records = []
        for path in args.inputs:
            records.extend(load_records(path, source=args.source, split=args.split))
        records = deduplicate_records(records)
        records = assign_cluster_splits(records)
        count = write_jsonl(records, args.out)
    else:
        count = write_jsonl(
            _iter_deduplicated(args.inputs, source=args.source, split=args.split),
            args.out,
        )
        records = list()

    if args.cluster_split:
        train = [record for record in records if record.split == "train"]
        valid = [record for record in records if record.split == "valid"]
        test = [record for record in records if record.split == "test"]
        leakage = {
            "valid_leakage_from_train": leakage_report(train, valid).__dict__ if train and valid else None,
            "test_leakage_from_train": leakage_report(train, test).__dict__ if train and test else None,
        }
        split_counts = {
            "train": len(train),
            "valid": len(valid),
            "test": len(test),
            "none": sum(1 for record in records if record.split is None),
        }
    else:
        leakage = {
            "valid_leakage_from_train": None,
            "test_leakage_from_train": None,
        }
        split_counts = _count_splits(args.out)
    summary = {
        "out": str(args.out),
        "records": count,
        "splits": split_counts,
        **leakage,
    }
    print(json.dumps(summary, indent=2, sort_keys=True))


def _iter_deduplicated(inputs: list[Path], source: str | None, split: str | None):
    seen = set()
    for path in inputs:
        for record in _iter_records(path, source=source, split=split):
            key = (record.peptide, record.alleles, record.target, record.split)
            if key in seen:
                continue
            seen.add(key)
            yield record


def _iter_records(path: Path, source: str | None, split: str | None):
    if path.suffix.lower() == ".jsonl":
        yield from read_jsonl(path)
    elif path.name.endswith("_positive.csv") or "hlaiipred" in (source or ""):
        yield from iter_hlaiipred_positive_csv(path, split=split)
    else:
        yield from iter_generic_records(path, source=source or path.stem, split=split)


def _count_splits(path: Path) -> dict[str, int]:
    counts = {"train": 0, "valid": 0, "test": 0, "none": 0}
    for record in read_jsonl(path):
        counts[record.split or "none"] = counts.get(record.split or "none", 0) + 1
    return counts


if __name__ == "__main__":
    main()
