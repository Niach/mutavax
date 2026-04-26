#!/usr/bin/env python3
"""Pre-compute ESM-2 features for all peptide cores + allele pseudoseqs.

Usage:
    python3 scripts/mhc2_build_esm_cache.py \\
        --train-jsonl     data/mhc2/curated/combined_train.jsonl \\
        --valid-jsonl     data/mhc2/curated/hlaiipred_valid.jsonl \\
        --pseudosequences data/mhc2/netmhciipan_43/extracted/pseudosequence.2023.dat \\
        --out             data/mhc2/esm_cache \\
        --device          cuda --bf16
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.research.mhc2.data import load_pseudosequences, read_jsonl
from app.research.mhc2.decoys import (
    positive_9mer_index,
    read_fasta_sequences,
    sample_length_matched_decoys,
)
from app.research.mhc2.esm import (
    ESM_MODEL_ID,
    cache_embeddings_to_disk,
    normalize_for_esm,
)
from app.research.mhc2.model import enumerate_cores


def collect_cores_with_decoys(
    train_jsonl: Path,
    extra_jsonls: list[Path],
    proteome_fasta: Path | None,
    decoys_per_positive: int,
    seed: int,
) -> list[str]:
    """Return all unique 9-mer cores covered by training (positives + decoys
    sampled with the same seed the trainer uses) plus extra valid/test sets.
    """
    cores: set[str] = set()

    def _add(peptide: str) -> None:
        for _, core in enumerate_cores(peptide):
            try:
                cores.add(normalize_for_esm(core))
            except ValueError:
                pass

    train_records = list(read_jsonl(train_jsonl))
    for record in train_records:
        _add(record.peptide)

    for path in extra_jsonls:
        for record in read_jsonl(path):
            _add(record.peptide)

    if proteome_fasta is not None and decoys_per_positive > 0:
        # Mirror the trainer: train decoys with seed N, valid decoys with seed N+1
        proteome = read_fasta_sequences(proteome_fasta)
        train_decoys, _ = sample_length_matched_decoys(
            train_records,
            proteome,
            positive_9mers=positive_9mer_index(train_records),
            per_positive=decoys_per_positive,
            seed=seed,
        )
        for record in train_decoys:
            _add(record.peptide)
        for extra in extra_jsonls:
            valid_records = list(read_jsonl(extra))
            valid_decoys, _ = sample_length_matched_decoys(
                valid_records,
                proteome,
                positive_9mers=positive_9mer_index(valid_records),
                per_positive=decoys_per_positive,
                seed=seed + 1,
            )
            for record in valid_decoys:
                _add(record.peptide)

    return sorted(cores)


def collect_pseudoseqs(pseudoseq_path: Path) -> list[str]:
    sequences: set[str] = set()
    for value in load_pseudosequences(pseudoseq_path).values():
        try:
            sequences.add(normalize_for_esm(value))
        except ValueError:
            continue
    return sorted(sequences)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--train-jsonl", type=Path, required=True)
    parser.add_argument("--valid-jsonl", type=Path)
    parser.add_argument("--test-jsonl", type=Path)
    parser.add_argument("--pseudosequences", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True,
                        help="Output directory; cores.pt + pseudoseqs.pt land here.")
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--bf16", action="store_true")
    parser.add_argument("--proteome-fasta", type=Path,
                        help="Mirror the trainer's decoy generation so decoy 9-mer cores are also cached.")
    parser.add_argument("--decoys-per-positive", type=int, default=10)
    parser.add_argument("--seed", type=int, default=13)
    args = parser.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)

    extras = []
    if args.valid_jsonl is not None:
        extras.append(args.valid_jsonl)
    if args.test_jsonl is not None:
        extras.append(args.test_jsonl)

    print(f"[esm-cache] using {ESM_MODEL_ID} on {args.device}", flush=True)
    print(
        f"[esm-cache] enumerating cores from train + {len(extras)} extras"
        + (f" + decoys ({args.decoys_per_positive}/positive, seed={args.seed})"
           if args.proteome_fasta else " (no decoys)"),
        flush=True,
    )
    cores = collect_cores_with_decoys(
        args.train_jsonl,
        extras,
        proteome_fasta=args.proteome_fasta,
        decoys_per_positive=args.decoys_per_positive,
        seed=args.seed,
    )
    print(f"[esm-cache] unique cores: {len(cores)}", flush=True)
    jsonls = [args.train_jsonl] + extras

    pseudoseqs = collect_pseudoseqs(args.pseudosequences)
    print(f"[esm-cache] unique pseudoseqs: {len(pseudoseqs)}", flush=True)

    cache_embeddings_to_disk(
        cores,
        args.out / "cores.pt",
        device=args.device,
        batch_size=args.batch_size,
        use_bf16=args.bf16,
        source_files=tuple(str(path) for path in jsonls),
    )
    cache_embeddings_to_disk(
        pseudoseqs,
        args.out / "pseudoseqs.pt",
        device=args.device,
        batch_size=args.batch_size,
        use_bf16=args.bf16,
        source_files=(str(args.pseudosequences),),
    )

    print(f"[esm-cache] done; outputs in {args.out}", flush=True)


if __name__ == "__main__":
    main()
