#!/usr/bin/env python3
"""Train a cancerstudio MHC-II checkpoint in an optional PyTorch environment."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.research.mhc2.train import TrainConfig, train


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--train-jsonl", type=Path, required=True)
    parser.add_argument("--valid-jsonl", type=Path)
    parser.add_argument("--pseudosequences", type=Path, required=True)
    parser.add_argument("--proteome-fasta", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--track", default="public_reproduce")
    parser.add_argument("--epochs", type=int, default=5)
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--learning-rate", type=float, default=1e-4)
    parser.add_argument("--decoys-per-positive", type=int, default=1)
    parser.add_argument("--device", default="auto", help="auto|cuda|cpu (default: auto)")
    parser.add_argument("--num-workers", type=int, default=0)
    parser.add_argument("--log-every", type=int, default=200)
    parser.add_argument("--early-stopping-patience", type=int, default=0,
                        help="Stop after N epochs with no val_auc improvement (0 disables)")
    parser.add_argument("--no-save-every-epoch", action="store_true",
                        help="Skip per-epoch checkpoints (only keep .pt and .best.pt)")
    parser.add_argument("--embedding-dim", type=int, default=96)
    parser.add_argument("--hidden-dim", type=int, default=128)
    parser.add_argument("--attention-heads", type=int, default=4)
    parser.add_argument("--num-layers", type=int, default=2)
    parser.add_argument("--dropout", type=float, default=0.1)
    parser.add_argument("--warmup-steps", type=int, default=0,
                        help="Linear warmup steps before cosine decay (0 = no scheduler).")
    parser.add_argument("--min-lr", type=float, default=1e-6,
                        help="Cosine decay floor.")
    parser.add_argument("--bf16", action="store_true",
                        help="Use bfloat16 autocast on CUDA (Ampere/Ada).")
    parser.add_argument("--model-kind", choices=["scratch", "esm2_35m"], default="scratch",
                        help="Phase A 'scratch' (default) or Phase B 'esm2_35m' (frozen ESM-2 features).")
    parser.add_argument("--esm-cache-dir", type=Path, default=None,
                        help="Directory with cores.pt + pseudoseqs.pt; required for esm2_35m.")
    parser.add_argument("--esm-adapter-layers", type=int, default=2)
    parser.add_argument("--esm-adapter-heads", type=int, default=8)
    parser.add_argument("--esm-adapter-hidden", type=int, default=1024)
    parser.add_argument("--multi-task-ba", action="store_true",
                        help="Enable BA regression head + multi-task EL+BA loss.")
    parser.add_argument("--ba-loss-weight", type=float, default=0.3)
    parser.add_argument("--cluster-weighted", action="store_true",
                        help="Multiply each per-sample loss by record.cluster_weight (legacy / shrinks gradients).")
    parser.add_argument("--cluster-weighted-sampler", action="store_true",
                        help="Use WeightedRandomSampler with weights=cluster_weight to balance cluster "
                             "representation per epoch (HLAIIPred protocol). Preserves gradient magnitude.")
    parser.add_argument("--allele-aggregation", choices=["max", "logsumexp"], default="max",
                        help="How to combine per-allele logits into a sample logit: "
                             "'max' (Phase A/B v0) or 'logsumexp' (soft 'any allele can present').")
    parser.add_argument("--allele-dropout", type=float, default=0.0,
                        help="HLAIIPred-style allele-score dropout: per-step probability of "
                             "masking each allele in a polyallelic sample (0 = off).")
    parser.add_argument("--dynamic-decoys", action="store_true",
                        help="Regenerate length-matched decoys at the start of each epoch "
                             "instead of fixing them once (HLAIIPred protocol).")
    parser.add_argument("--locus-upweight",
                        choices=["none", "balanced", "inverse_frequency", "sqrt_inverse"],
                        default="none",
                        help="Per-locus loss reweighting. 'none' (default) = no reweighting. "
                             "'balanced'/'inverse_frequency' = weight ∝ N/(n_loci * count[locus]) "
                             "so each locus contributes equal mass to total loss. "
                             "'sqrt_inverse' = gentler 1/sqrt(count[locus]) variant.")
    parser.add_argument("--inverted-dp", action="store_true",
                        help="HLA-DP inverted binding: also score the reversed peptide "
                             "(C->N) for DP records and let the existing max-over-cores "
                             "pick the best orientation. Recipe-mandated for 2026 SOTA on "
                             "DP. Requires a peptides_rev.bin cache built with "
                             "scripts/mhc2_build_esm_cache.py --build-reversed.")
    parser.add_argument("--use-length-features", action="store_true",
                        help="Concatenate three scalars (peptide n_cores, N-term offset, "
                             "C-term distance) into the per-(core, allele) fused vector "
                             "before the scorer. Targets the long-peptide (≥20 aa) "
                             "FRANK degradation. Adds 3 input dims to the scorer; "
                             "checkpoints record the flag so predictor reloads match.")
    parser.add_argument("--use-chain-boundary", action="store_true",
                        help="Add a learned 2-vocab segment embedding (α=0..14, β=15..33) "
                             "to per-residue allele features before the encoder. "
                             "Targets the DP/DQ heterodimer FRANK weakness. NetMHCIIpan-4.3 "
                             "pseudoseq layout is fixed: positions 0-14 = α-chain, "
                             "15-33 = β-chain.")
    parser.add_argument("--alpha-chain-length", type=int, default=15,
                        help="Boundary position. Default 15 matches the NetMHCIIpan-4.3 "
                             "convention. Only used when --use-chain-boundary is on.")
    parser.add_argument("--eval-fa-sentinel", type=Path, default=None,
                        help="Path to NetMHCIIpan_eval.fa. If set, a stratified subset is "
                             "scored after each epoch and merged into history.json under "
                             "sentinel_* keys. Doesn't gate early stopping yet.")
    parser.add_argument("--eval-fa-sentinel-n", type=int, default=100,
                        help="Sentinel subset size (default 100, deterministic).")
    parser.add_argument("--eval-fa-sentinel-seed", type=int, default=13)
    parser.add_argument("--eval-fa-sentinel-batch-size", type=int, default=64)
    parser.add_argument("--early-stop-metric",
                        choices=["val_auc", "sentinel_frank"], default="val_auc",
                        help="Metric to gate early stopping. 'sentinel_frank' uses the "
                             "per-epoch eval.fa median FRANK (lower-is-better); requires "
                             "--eval-fa-sentinel.")
    parser.add_argument("--grad-clip", type=float, default=0.0,
                        help="Clip grad-norm to this value. 0 disables. Recommended 1.0 "
                             "for FRANK-aligned ranking-loss training.")
    parser.add_argument("--grad-accum-steps", type=int, default=1,
                        help="Gradient-accumulation steps. Effective batch size = "
                             "--batch-size * --grad-accum-steps.")
    parser.add_argument("--ranking-loss-weight", type=float, default=0.0,
                        help="Weight on in-batch pairwise hinge ranking loss "
                             "score(pos) > score(neg) + margin. 0 disables (BCE-only "
                             "legacy). Recipe target ~1.0 once hard SwissProt negatives "
                             "are mined and replace random decoys.")
    parser.add_argument("--ranking-loss-margin", type=float, default=1.0,
                        help="Logit-space margin for the ranking hinge.")
    parser.add_argument("--hard-negatives-jsonl", type=Path, default=None,
                        help="Pre-mined hard SwissProt negatives "
                             "(scripts/mhc2_mine_hard_negatives.py output). "
                             "When set, replaces the length-matched random decoys "
                             "and disables --dynamic-decoys for the training set.")
    args = parser.parse_args()

    checkpoint = train(
        TrainConfig(
            train_jsonl=args.train_jsonl,
            valid_jsonl=args.valid_jsonl,
            pseudosequences=args.pseudosequences,
            output_dir=args.out,
            proteome_fasta=args.proteome_fasta,
            checkpoint_track=args.track,
            epochs=args.epochs,
            batch_size=args.batch_size,
            learning_rate=args.learning_rate,
            decoys_per_positive=args.decoys_per_positive,
            device=args.device,
            num_workers=args.num_workers,
            log_every=args.log_every,
            early_stopping_patience=args.early_stopping_patience,
            save_every_epoch=not args.no_save_every_epoch,
            embedding_dim=args.embedding_dim,
            hidden_dim=args.hidden_dim,
            attention_heads=args.attention_heads,
            num_layers=args.num_layers,
            dropout=args.dropout,
            warmup_steps=args.warmup_steps,
            min_lr=args.min_lr,
            bf16=args.bf16,
            model_kind=args.model_kind,
            esm_cache_dir=args.esm_cache_dir,
            esm_adapter_layers=args.esm_adapter_layers,
            esm_adapter_heads=args.esm_adapter_heads,
            esm_adapter_hidden=args.esm_adapter_hidden,
            multi_task_ba=args.multi_task_ba,
            ba_loss_weight=args.ba_loss_weight,
            cluster_weighted=args.cluster_weighted,
            cluster_weighted_sampler=args.cluster_weighted_sampler,
            allele_aggregation=args.allele_aggregation,
            allele_dropout=args.allele_dropout,
            dynamic_decoys=args.dynamic_decoys,
            locus_upweight=args.locus_upweight,
            inverted_dp=args.inverted_dp,
            use_length_features=args.use_length_features,
            use_chain_boundary=args.use_chain_boundary,
            alpha_chain_length=args.alpha_chain_length,
            eval_fa_sentinel_path=args.eval_fa_sentinel,
            eval_fa_sentinel_n=args.eval_fa_sentinel_n,
            eval_fa_sentinel_seed=args.eval_fa_sentinel_seed,
            eval_fa_sentinel_batch_size=args.eval_fa_sentinel_batch_size,
            early_stop_metric=args.early_stop_metric,
            grad_clip=args.grad_clip,
            grad_accum_steps=args.grad_accum_steps,
            ranking_loss_weight=args.ranking_loss_weight,
            ranking_loss_margin=args.ranking_loss_margin,
            hard_negatives_jsonl=args.hard_negatives_jsonl,
        )
    )
    print(checkpoint)


if __name__ == "__main__":
    main()

