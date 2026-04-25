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
        )
    )
    print(checkpoint)


if __name__ == "__main__":
    main()

