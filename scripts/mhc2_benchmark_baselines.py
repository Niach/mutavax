#!/usr/bin/env python3
"""Score every available MHC-II baseline + our model on the locked test set.

For each labeled record (peptide + allele set + label), score the peptide
against EVERY allele in the sample and take the max as the sample-level
prediction. This matches HLAIIPred / NetMHCIIpan_MA / MixMHC2pred protocols
for polyallelic data and prevents the "first allele" shortcut that earlier
runs of this script used.

Usage:
    python3 scripts/mhc2_benchmark_baselines.py \\
        --test-jsonl     data/mhc2/curated/cluster/cluster_test.jsonl \\
        --proteome-fasta data/mhc2/proteome/human_uniprot_sprot.fasta \\
        --decoys-per-positive 10 \\
        --pseudosequences data/mhc2/netmhciipan_43/extracted/pseudosequence.2023.dat \\
        --our-checkpoint data/mhc2/checkpoints/phaseB_v3/phaseB_v3.best.pt \\
        --our-esm-cache-dir data/mhc2/esm_cache \\
        --out            data/mhc2/benchmarks/cluster_test/
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.research.mhc2.baselines.base import BaselineModel
from app.research.mhc2.baselines.hlaiipred import HLAIIPredAdapter
from app.research.mhc2.baselines.mixmhc2pred import MixMHC2predAdapter
from app.research.mhc2.baselines.netmhciipan import NetMHCIIpanAdapter
from app.research.mhc2.baselines.our_model import OurModelAdapter
from app.research.mhc2.benchmark import compute_sota_report, report_to_markdown
from app.research.mhc2.data import read_jsonl
from app.research.mhc2.decoys import (
    positive_9mer_index,
    read_fasta_sequences,
    sample_length_matched_decoys,
)


def _build_test_records(
    test_jsonl: Path,
    proteome_fasta: Path | None,
    decoys_per_positive: int,
    seed: int,
    label_type_filter: str | None = "presentation",
) -> tuple[list, list[float]]:
    """Returns (records_with_full_allele_sets, labels). Each record keeps
    its complete ``alleles`` tuple so the scoring driver can fan-out."""
    positives = [
        r for r in read_jsonl(test_jsonl)
        if 9 <= len(r.peptide) <= 25
        and (label_type_filter is None or r.label_type == label_type_filter)
    ]
    records: list = []
    labels: list[float] = []
    for record in positives:
        if not record.alleles:
            continue
        records.append(record)
        labels.append(1.0)
    if proteome_fasta is not None and decoys_per_positive > 0:
        proteome = read_fasta_sequences(proteome_fasta)
        decoys, _ = sample_length_matched_decoys(
            positives,
            proteome,
            positive_9mers=positive_9mer_index(positives),
            per_positive=decoys_per_positive,
            seed=seed,
        )
        for record in decoys:
            if not record.alleles:
                continue
            records.append(record)
            labels.append(0.0)
    return records, labels


def _score_polyallelic(
    adapter: BaselineModel,
    records: list,
) -> tuple[list[float], int]:
    """Score each record against all alleles in its sample, return per-record
    max-score. Also returns the count of NaN scores from the adapter."""
    pairs: list[tuple[str, str]] = []
    record_idx_for_pair: list[int] = []
    for i, record in enumerate(records):
        for allele in record.alleles:
            pairs.append((record.peptide, allele))
            record_idx_for_pair.append(i)
    predictions = adapter.predict(pairs)
    if len(predictions) != len(pairs):
        raise RuntimeError(f"{adapter.name} returned {len(predictions)} of {len(pairs)} predictions")
    record_max: list[float] = [float("-inf")] * len(records)
    n_nan = 0
    for i, prediction in zip(record_idx_for_pair, predictions):
        score = prediction.score
        if score != score:  # nan
            n_nan += 1
            score = float("-inf")
        if score > record_max[i]:
            record_max[i] = score
    # If a record had only NaN scores, fall back to a sentinel min.
    record_max = [s if s > float("-inf") else -1e9 for s in record_max]
    return record_max, n_nan


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--test-jsonl", type=Path, required=True)
    parser.add_argument("--proteome-fasta", type=Path)
    parser.add_argument("--decoys-per-positive", type=int, default=10)
    parser.add_argument("--seed", type=int, default=13)
    parser.add_argument("--pseudosequences", type=Path,
                        help="Required when --our-checkpoint is set.")
    parser.add_argument("--our-checkpoint", type=Path)
    parser.add_argument("--our-esm-cache-dir", type=Path,
                        help="Required when --our-checkpoint is an ESM (Phase B) checkpoint.")
    parser.add_argument("--device", default="auto")
    parser.add_argument("--n-bootstrap", type=int, default=1000)
    parser.add_argument("--label-type", default="presentation",
                        choices=["presentation", "affinity", "any"],
                        help="Filter test records by label_type. 'any' keeps all.")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)

    label_filter = None if args.label_type == "any" else args.label_type
    print(f"[bench] building test set from {args.test_jsonl} (label_type={args.label_type})", flush=True)
    records, labels = _build_test_records(
        args.test_jsonl,
        args.proteome_fasta,
        args.decoys_per_positive,
        args.seed,
        label_type_filter=label_filter,
    )
    n_pairs = sum(len(r.alleles) for r in records)
    print(
        f"[bench] {len(records):,} records ({sum(int(y) for y in labels):,} pos), "
        f"{n_pairs:,} (peptide,allele) pairs to score per tool",
        flush=True,
    )

    adapters: list[BaselineModel] = [
        NetMHCIIpanAdapter(),
        MixMHC2predAdapter(),
        HLAIIPredAdapter(device=args.device),
    ]
    if args.our_checkpoint is not None:
        if args.pseudosequences is None:
            raise SystemExit("--pseudosequences is required with --our-checkpoint")
        adapters.append(OurModelAdapter(
            args.our_checkpoint,
            args.pseudosequences,
            device=args.device,
            esm_cache_dir=args.our_esm_cache_dir,
        ))

    summary: dict = {"missing_tools": {}, "models": {}}
    peptides = [r.peptide for r in records]
    primary_alleles = [r.alleles[0] for r in records]  # for per-locus slicing only

    for adapter in adapters:
        ok, msg = adapter.is_available()
        if not ok:
            print(f"[bench] {adapter.name}: SKIP ({msg})", flush=True)
            summary["missing_tools"][adapter.name] = msg
            continue
        print(f"[bench] {adapter.name}: scoring {n_pairs:,} pairs ({msg})", flush=True)
        scores, n_nan = _score_polyallelic(adapter, records)
        if n_nan:
            print(f"[bench] {adapter.name}: {n_nan} NaN scores treated as worst-binder", flush=True)
        report = compute_sota_report(
            labels, scores, peptides, primary_alleles,
            n_bootstrap=args.n_bootstrap,
            metadata={
                "title": f"{adapter.name} on {args.test_jsonl.name}",
                "model": adapter.name,
                "test_set": str(args.test_jsonl),
                "n_nan_pair_scores": n_nan,
                "scoring": "max-over-sample-alleles",
            },
        )
        slug = adapter.name.replace(" ", "_").replace("/", "-")
        (args.out / f"{slug}.json").write_text(
            json.dumps(report.to_json(), indent=2) + "\n", encoding="utf-8",
        )
        (args.out / f"{slug}.md").write_text(
            report_to_markdown(report), encoding="utf-8",
        )
        summary["models"][adapter.name] = {
            "rows": report.rows,
            "n_pos": report.n_pos,
            "n_neg": report.n_neg,
            "roc_auc": report.roc_auc,
            "pr_auc": report.pr_auc,
        }
        print(
            f"[bench] {adapter.name}: AUC={report.roc_auc['point']:.4f} "
            f"[{report.roc_auc['low']:.4f}, {report.roc_auc['high']:.4f}]",
            flush=True,
        )

    summary_path = args.out / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    comparison_md = ["# Cross-tool MHC-II benchmark (max-over-sample-alleles)", ""]
    if summary["missing_tools"]:
        comparison_md.append("## Tools skipped")
        comparison_md.append("")
        for name, msg in summary["missing_tools"].items():
            comparison_md.append(f"- **{name}**: {msg}")
        comparison_md.append("")
    if summary["models"]:
        comparison_md.append("## Comparison")
        comparison_md.append("")
        comparison_md.append("| Model | rows | pos | neg | ROC-AUC | 95% CI | PR-AUC | 95% CI |")
        comparison_md.append("|---|---:|---:|---:|---:|---:|---:|---:|")
        for name, m in summary["models"].items():
            comparison_md.append(
                f"| {name} | {m['rows']:,} | {m['n_pos']:,} | {m['n_neg']:,} | "
                f"{m['roc_auc']['point']:.4f} | "
                f"[{m['roc_auc']['low']:.4f}, {m['roc_auc']['high']:.4f}] | "
                f"{m['pr_auc']['point']:.4f} | "
                f"[{m['pr_auc']['low']:.4f}, {m['pr_auc']['high']:.4f}] |"
            )
    (args.out / "comparison.md").write_text("\n".join(comparison_md) + "\n", encoding="utf-8")
    print(f"[bench] wrote summary to {summary_path}", flush=True)


if __name__ == "__main__":
    main()
