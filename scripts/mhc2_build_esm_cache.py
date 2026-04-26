#!/usr/bin/env python3
"""Pre-compute ESM-2 features for the Phase B model.

Three caches are produced under ``--out``:

* ``peptides.pt``     — one Tensor(L, 480) per unique positive peptide
                        string in the JSONL inputs.
* ``proteins.pt``     — one Tensor(L, 480) per protein in the proteome
                        FASTA, keyed ``"p<index>"`` (matching the
                        ``protein_id`` written by the decoy generator).
* ``pseudoseqs.pt``   — one Tensor(L, 480) per unique allele pseudoseq.

At training time, decoy 9-mer cores are sliced from
``proteins.pt[protein_id][peptide_offset : peptide_offset + len(peptide)]``,
which is several orders of magnitude smaller than caching every 9-mer.

Usage:
    python3 scripts/mhc2_build_esm_cache.py \\
        --train-jsonl     data/mhc2/curated/combined_train.jsonl \\
        --valid-jsonl     data/mhc2/curated/hlaiipred_valid.jsonl \\
        --pseudosequences data/mhc2/netmhciipan_43/extracted/pseudosequence.2023.dat \\
        --proteome-fasta  data/mhc2/proteome/human_uniprot_sprot.fasta \\
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
from app.research.mhc2.decoys import read_fasta_sequences
from app.research.mhc2.esm import (
    ESM_MODEL_ID,
    cache_embeddings_to_disk,
    normalize_for_esm,
    normalize_proteome_sequence,
)


def collect_unique_peptides(jsonl_paths: list[Path]) -> list[str]:
    sequences: set[str] = set()
    for path in jsonl_paths:
        for record in read_jsonl(path):
            try:
                sequences.add(normalize_for_esm(record.peptide))
            except ValueError:
                continue
    return sorted(sequences)


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
                        help="Used to embed proteins for decoy 9-mer slicing.")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--bf16", action="store_true")
    parser.add_argument("--skip-peptides", action="store_true",
                        help="Skip the peptides cache (already built).")
    parser.add_argument("--skip-proteins", action="store_true",
                        help="Skip the proteins cache (already built).")
    parser.add_argument("--skip-pseudoseqs", action="store_true",
                        help="Skip the pseudoseqs cache (already built).")
    args = parser.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)

    jsonls = [args.train_jsonl]
    if args.valid_jsonl is not None:
        jsonls.append(args.valid_jsonl)
    if args.test_jsonl is not None:
        jsonls.append(args.test_jsonl)

    print(f"[esm-cache] using {ESM_MODEL_ID} on {args.device}", flush=True)

    if not args.skip_peptides:
        print(f"[esm-cache] enumerating unique peptides from {len(jsonls)} JSONLs", flush=True)
        peptides = collect_unique_peptides(jsonls)
        print(f"[esm-cache] unique peptides: {len(peptides)}", flush=True)
        cache_embeddings_to_disk(
            peptides,
            args.out / "peptides.pt",
            device=args.device,
            batch_size=args.batch_size,
            use_bf16=args.bf16,
            source_files=tuple(str(path) for path in jsonls),
        )

    if not args.skip_proteins:
        print(f"[esm-cache] reading proteome from {args.proteome_fasta}", flush=True)
        proteome = read_fasta_sequences(args.proteome_fasta)
        # Substitute non-standard residues with X (selenocysteine, ambiguous
        # codes) so EVERY protein in the original list is embeddable. The
        # protein_id "p<index>" must align 1:1 with the index used by the
        # decoy generator's `proteome_sequences` list.
        normalized: list[tuple[str, str]] = []
        for idx, seq in enumerate(proteome):
            try:
                normalized.append((f"p{idx}", normalize_proteome_sequence(seq)))
            except ValueError:
                continue
        print(f"[esm-cache] proteins to embed: {len(normalized)} of {len(proteome)}", flush=True)
        # cache_embeddings_to_disk only takes plain sequences and dedupes,
        # which would lose the protein_id mapping. Build manually:
        _embed_proteins_to_disk(
            normalized,
            args.out / "proteins.pt",
            device=args.device,
            batch_size=args.batch_size,
            use_bf16=args.bf16,
            source_files=(str(args.proteome_fasta),),
        )

    if not args.skip_pseudoseqs:
        print(f"[esm-cache] enumerating pseudoseqs from {args.pseudosequences}", flush=True)
        pseudoseqs = collect_pseudoseqs(args.pseudosequences)
        print(f"[esm-cache] unique pseudoseqs: {len(pseudoseqs)}", flush=True)
        cache_embeddings_to_disk(
            pseudoseqs,
            args.out / "pseudoseqs.pt",
            device=args.device,
            batch_size=args.batch_size,
            use_bf16=args.bf16,
            source_files=(str(args.pseudosequences),),
        )

    print(f"[esm-cache] done; outputs in {args.out}", flush=True)


def _embed_proteins_to_disk(
    proteins: list[tuple[str, str]],
    cache_path: Path,
    *,
    device: str,
    batch_size: int,
    use_bf16: bool,
    source_files: tuple[str, ...],
) -> None:
    """Embed proteins and persist as ``{protein_id: Tensor(L, 480)}``.

    Different from the generic helper because the key is a protein id, not
    the sequence itself, and proteins are typically much longer (forces
    smaller per-batch counts to control VRAM).
    """
    import json
    import torch

    from app.research.mhc2.esm import (
        ESM_FEATURE_DIM,
        ESMCacheManifest,
        embed_sequences,
        load_esm2_35m,
    )

    if not proteins:
        raise ValueError("no proteins to embed")

    model, tokenizer = load_esm2_35m(device=device)

    # Sort by length so each padded batch is roughly homogeneous; saves VRAM
    proteins_sorted = sorted(proteins, key=lambda kv: len(kv[1]))
    embeddings: dict = {}
    log_every = max(1, len(proteins_sorted) // 20)
    pbar_count = 0
    for start in range(0, len(proteins_sorted), batch_size):
        batch = proteins_sorted[start : start + batch_size]
        batch_seqs = [seq for _, seq in batch]
        # For very long proteins, drop batch_size to 1 to avoid OOM; ESM2
        # 35M can handle ~3k-residue proteins on a 4090 in bf16.
        if max(len(s) for s in batch_seqs) > 1500:
            for pid, seq in batch:
                feats = embed_sequences(model, tokenizer, [seq], device=device,
                                         batch_size=1, use_bf16=use_bf16)
                embeddings[pid] = feats[0].to(torch.bfloat16) if use_bf16 else feats[0]
                pbar_count += 1
        else:
            features = embed_sequences(
                model, tokenizer, batch_seqs,
                device=device, batch_size=len(batch_seqs), use_bf16=use_bf16,
            )
            for (pid, _), feat in zip(batch, features):
                embeddings[pid] = feat.to(torch.bfloat16) if use_bf16 else feat
                pbar_count += 1
        if pbar_count % log_every < batch_size:
            print(f"[esm] proteins {pbar_count}/{len(proteins_sorted)}", flush=True)

    manifest = ESMCacheManifest(
        model_id="facebook/esm2_t12_35M_UR50D",
        feature_dim=ESM_FEATURE_DIM,
        n_sequences=len(embeddings),
        max_length=max(seq.shape[0] for seq in embeddings.values()),
        source_files=source_files,
    )
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    torch.save(
        {"embeddings": embeddings, "manifest": manifest.to_json()},
        cache_path,
    )
    cache_path.with_suffix(".json").write_text(
        json.dumps(manifest.to_json(), indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"[esm] wrote {cache_path} ({len(embeddings)} entries)", flush=True)


if __name__ == "__main__":
    main()
