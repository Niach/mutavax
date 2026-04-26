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
from app.research.mhc2.data import (
    iter_generic_records,
    iter_hlaiipred_positive_csv,
    iter_netmhciipan_partition_file,
    load_netmhciipan_allelelist,
    read_jsonl,
)
from app.research.mhc2.splits import assign_cluster_splits, leakage_report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inputs", nargs="+", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--source", default=None)
    parser.add_argument("--split", default=None)
    parser.add_argument("--cluster-split", action="store_true")
    parser.add_argument(
        "--netmhciipan-allelelist",
        type=Path,
        default=None,
        help="Path to NetMHCIIpan-4.3 allelelist (required for --source netmhciipan_43_el).",
    )
    parser.add_argument(
        "--include-netmhciipan-decoys",
        action="store_true",
        help="Keep target=0 rows from NetMHCIIpan partitions (default: positives only).",
    )
    args = parser.parse_args()

    netmhciipan_allelelist = None
    if args.source == "netmhciipan_43_el":
        if args.netmhciipan_allelelist is None:
            raise SystemExit(
                "--netmhciipan-allelelist is required when --source netmhciipan_43_el"
            )
        netmhciipan_allelelist = load_netmhciipan_allelelist(args.netmhciipan_allelelist)

    if args.cluster_split:
        records = []
        for path in args.inputs:
            records.extend(
                _iter_records(
                    path,
                    source=args.source,
                    split=args.split,
                    netmhciipan_allelelist=netmhciipan_allelelist,
                    include_netmhciipan_decoys=args.include_netmhciipan_decoys,
                )
            )
        records = deduplicate_records(records)
        records = assign_cluster_splits(records)
        count = write_jsonl(records, args.out)
    else:
        count = write_jsonl(
            _iter_deduplicated(
                args.inputs,
                source=args.source,
                split=args.split,
                netmhciipan_allelelist=netmhciipan_allelelist,
                include_netmhciipan_decoys=args.include_netmhciipan_decoys,
            ),
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


def _iter_deduplicated(
    inputs: list[Path],
    source: str | None,
    split: str | None,
    netmhciipan_allelelist: dict[str, tuple[str, ...]] | None = None,
    include_netmhciipan_decoys: bool = False,
):
    seen = set()
    for path in inputs:
        for record in _iter_records(
            path,
            source=source,
            split=split,
            netmhciipan_allelelist=netmhciipan_allelelist,
            include_netmhciipan_decoys=include_netmhciipan_decoys,
        ):
            key = (record.peptide, record.alleles, record.target, record.split)
            if key in seen:
                continue
            seen.add(key)
            yield record


def _iter_records(
    path: Path,
    source: str | None,
    split: str | None,
    netmhciipan_allelelist: dict[str, tuple[str, ...]] | None = None,
    include_netmhciipan_decoys: bool = False,
):
    if path.suffix.lower() == ".jsonl":
        yield from read_jsonl(path)
    elif source == "netmhciipan_43_el":
        if netmhciipan_allelelist is None:
            raise ValueError("netmhciipan_allelelist required for netmhciipan_43_el source")
        yield from iter_netmhciipan_partition_file(
            path,
            allelelist=netmhciipan_allelelist,
            split=split,
            positives_only=not include_netmhciipan_decoys,
        )
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
