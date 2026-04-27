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
                        help="Multiply each per-sample loss by record.cluster_weight.")
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
        )
    )
    print(checkpoint)


if __name__ == "__main__":
    main()

