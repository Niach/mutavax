#!/usr/bin/env python3
"""Pre-compute ESM-2 features for the Phase B model.

Two caches are produced under ``--out``:

* ``peptides.pt``     — one Tensor(L, 480) per unique peptide string
                        encountered during training. Positives come from
                        the JSONL inputs, decoys are generated with the
                        same seed the trainer uses, and *all* of them are
                        embedded as **standalone peptides** so positives
                        and decoys see the same ESM context.
* ``pseudoseqs.pt``   — one Tensor(L, 480) per unique allele pseudoseq.

The earlier proteins-level cache (one Tensor per protein, decoys sliced
from full-protein features) was discarded because it produced a context
asymmetry: positives saw a peptide-only ESM context, decoys saw a
protein-wide one. The model trivially classified the asymmetry rather
than the binding signal.

Usage:
    python3 scripts/mhc2_build_esm_cache.py \\
        --train-jsonl     data/mhc2/curated/combined_train.jsonl \\
        --valid-jsonl     data/mhc2/curated/hlaiipred_valid.jsonl \\
        --pseudosequences data/mhc2/netmhciipan_43/extracted/pseudosequence.2023.dat \\
        --proteome-fasta  data/mhc2/proteome/human_uniprot_sprot.fasta \\
        --decoys-per-positive 10 --seed 13 \\
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
    cache_embeddings_packed,
    cache_embeddings_to_disk,
    normalize_for_esm,
)


def collect_unique_peptides(
    train_jsonl: Path,
    extra_jsonls: list[Path],
    proteome_fasta: Path | None,
    decoys_per_positive: int,
    seed: int,
) -> list[str]:
    """Return all unique peptide strings the trainer will see in a run.

    Mirrors ``train.train()``'s decoy-generation call exactly so the cache
    covers every record the trainer will iterate over: positives from the
    JSONL inputs plus decoys sampled with the same seed scheme (train
    decoys with seed N, valid decoys with seed N+1).
    """
    peptides: set[str] = set()

    def _add(peptide: str) -> None:
        try:
            peptides.add(normalize_for_esm(peptide))
        except ValueError:
            pass

    train_records = list(read_jsonl(train_jsonl))
    for record in train_records:
        _add(record.peptide)
    extra_record_lists: list[list] = []
    for path in extra_jsonls:
        extra_records = list(read_jsonl(path))
        extra_record_lists.append(extra_records)
        for record in extra_records:
            _add(record.peptide)

    if proteome_fasta is not None and decoys_per_positive > 0:
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
        for extra_records in extra_record_lists:
            extra_decoys, _ = sample_length_matched_decoys(
                extra_records,
                proteome,
                positive_9mers=positive_9mer_index(extra_records),
                per_positive=decoys_per_positive,
                seed=seed + 1,
            )
            for record in extra_decoys:
                _add(record.peptide)

    return sorted(peptides)


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
    parser.add_argument("--proteome-fasta", type=Path, required=True,
                        help="Used to deterministically generate the same decoys "
                             "the trainer will sample, so their peptide strings "
                             "land in the cache.")
    parser.add_argument("--decoys-per-positive", type=int, default=10,
                        help="Must match what the trainer will use.")
    parser.add_argument("--seed", type=int, default=13,
                        help="Must match what the trainer will use (TrainConfig.seed).")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--bf16", action="store_true")
    parser.add_argument("--skip-peptides", action="store_true")
    parser.add_argument("--skip-pseudoseqs", action="store_true")
    parser.add_argument("--legacy-dict", action="store_true",
                        help="Write legacy {name}.pt dict instead of packed memmap-able .bin/.idx.pt.")
    parser.add_argument("--build-reversed", action="store_true",
                        help="Also write peptides_rev.bin / peptides_rev.idx.pt with each "
                             "peptide embedded *as if reversed* (C->N) for inverted-DP "
                             "scoring. Indexed by the original forward sequence so train/predict "
                             "can do `reversed_cache[peptide]` to get the reversed embedding.")
    args = parser.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)

    extras = []
    if args.valid_jsonl is not None:
        extras.append(args.valid_jsonl)
    if args.test_jsonl is not None:
        extras.append(args.test_jsonl)

    print(f"[esm-cache] using {ESM_MODEL_ID} on {args.device}", flush=True)

    if not args.skip_peptides:
        print(
            f"[esm-cache] enumerating peptides: train + {len(extras)} extras "
            f"+ decoys ({args.decoys_per_positive}x, seed={args.seed})",
            flush=True,
        )
        peptides = collect_unique_peptides(
            args.train_jsonl,
            extras,
            proteome_fasta=args.proteome_fasta,
            decoys_per_positive=args.decoys_per_positive,
            seed=args.seed,
        )
        print(f"[esm-cache] unique peptides: {len(peptides)}", flush=True)
        if args.legacy_dict:
            cache_embeddings_to_disk(
                peptides,
                args.out / "peptides.pt",
                device=args.device,
                batch_size=args.batch_size,
                use_bf16=args.bf16,
                source_files=tuple(str(p) for p in [args.train_jsonl, *extras, args.proteome_fasta]),
            )
        else:
            cache_embeddings_packed(
                peptides,
                args.out,
                "peptides",
                device=args.device,
                batch_size=args.batch_size,
                use_bf16=args.bf16,
                source_files=tuple(str(p) for p in [args.train_jsonl, *extras, args.proteome_fasta]),
            )
            if args.build_reversed:
                print(f"[esm-cache] embedding REVERSED peptides for inverted-DP", flush=True)
                cache_embeddings_packed(
                    peptides,
                    args.out,
                    "peptides_rev",
                    device=args.device,
                    batch_size=args.batch_size,
                    use_bf16=args.bf16,
                    source_files=tuple(str(p) for p in [args.train_jsonl, *extras, args.proteome_fasta]),
                    reverse_input=True,
                )

    if not args.skip_pseudoseqs:
        pseudoseqs = collect_pseudoseqs(args.pseudosequences)
        print(f"[esm-cache] unique pseudoseqs: {len(pseudoseqs)}", flush=True)
        if args.legacy_dict:
            cache_embeddings_to_disk(
                pseudoseqs,
                args.out / "pseudoseqs.pt",
                device=args.device,
                batch_size=args.batch_size,
                use_bf16=args.bf16,
                source_files=(str(args.pseudosequences),),
            )
        else:
            cache_embeddings_packed(
                pseudoseqs,
                args.out,
                "pseudoseqs",
                device=args.device,
                batch_size=args.batch_size,
                use_bf16=args.bf16,
                source_files=(str(args.pseudosequences),),
            )

    print(f"[esm-cache] done; outputs in {args.out}", flush=True)


if __name__ == "__main__":
    main()
