"""Training loop for the optional open MHC-II PyTorch model."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Sequence

from app.research.mhc2.data import MHC2Record, load_pseudosequences, read_jsonl
from app.research.mhc2.decoys import (
    positive_9mer_index,
    read_fasta_sequences,
    sample_length_matched_decoys,
)
from app.research.mhc2.model import (
    MHCIIInteractionModel,
    MissingTorchError,
    TORCH_AVAILABLE,
    encode_sequence,
    enumerate_cores,
)


@dataclass(frozen=True)
class TrainConfig:
    train_jsonl: Path
    valid_jsonl: Path | None
    pseudosequences: Path
    output_dir: Path
    proteome_fasta: Path | None = None
    checkpoint_track: str = "public_reproduce"
    epochs: int = 5
    batch_size: int = 32
    learning_rate: float = 1e-4
    decoys_per_positive: int = 1
    max_pseudoseq_length: int = 64
    seed: int = 13


def train(config: TrainConfig) -> Path:
    if not TORCH_AVAILABLE:
        raise MissingTorchError(
            "PyTorch is required for MHC-II training. "
            "Install backend/requirements-mhc2.txt in a research environment."
        )
    import torch
    from torch import nn
    from torch.utils.data import DataLoader, Dataset

    torch.manual_seed(config.seed)
    pseudosequences = load_pseudosequences(config.pseudosequences)
    positives = _records_with_pseudosequences(list(read_jsonl(config.train_jsonl)), pseudosequences)
    train_records: list[MHC2Record] = positives
    decoy_stats = None
    if config.proteome_fasta is not None:
        decoys, decoy_stats = sample_length_matched_decoys(
            positives,
            read_fasta_sequences(config.proteome_fasta),
            positive_9mers=positive_9mer_index(positives),
            per_positive=config.decoys_per_positive,
            seed=config.seed,
        )
        train_records = positives + decoys

    class _Dataset(Dataset):
        def __init__(self, records: Sequence[MHC2Record]) -> None:
            self.records = list(records)

        def __len__(self) -> int:
            return len(self.records)

        def __getitem__(self, index: int) -> MHC2Record:
            return self.records[index]

    def collate(records: list[MHC2Record]) -> tuple:
        max_cores = max(len(enumerate_cores(record.peptide)) for record in records)
        max_alleles = max(len(record.alleles) for record in records)
        core_batch: list[list[list[int]]] = []
        allele_batch: list[list[list[int]]] = []
        core_masks: list[list[bool]] = []
        allele_masks: list[list[bool]] = []
        labels: list[float] = []
        for record in records:
            cores = [encode_sequence(core, 9) for _, core in enumerate_cores(record.peptide)]
            core_mask = [True] * len(cores)
            while len(cores) < max_cores:
                cores.append([0] * 9)
                core_mask.append(False)
            alleles = [
                encode_sequence(pseudosequences[allele], config.max_pseudoseq_length)
                for allele in record.alleles
                if allele in pseudosequences
            ]
            allele_mask = [True] * len(alleles)
            while len(alleles) < max_alleles:
                alleles.append([0] * config.max_pseudoseq_length)
                allele_mask.append(False)
            core_batch.append(cores)
            allele_batch.append(alleles)
            core_masks.append(core_mask)
            allele_masks.append(allele_mask)
            labels.append(record.target)
        return (
            torch.tensor(core_batch, dtype=torch.long),
            torch.tensor(allele_batch, dtype=torch.long),
            torch.tensor(core_masks, dtype=torch.bool),
            torch.tensor(allele_masks, dtype=torch.bool),
            torch.tensor(labels, dtype=torch.float32),
        )

    model_config = {"max_pseudoseq_length": config.max_pseudoseq_length}
    model = MHCIIInteractionModel(**model_config)
    optimizer = torch.optim.AdamW(model.parameters(), lr=config.learning_rate)
    loss_fn = nn.BCEWithLogitsLoss()
    loader = DataLoader(
        _Dataset(train_records),
        batch_size=config.batch_size,
        shuffle=True,
        collate_fn=collate,
    )

    history: list[dict[str, float]] = []
    for epoch in range(1, config.epochs + 1):
        model.train()
        total_loss = 0.0
        total_items = 0
        for core_tokens, allele_tokens, core_mask, allele_mask, labels in loader:
            optimizer.zero_grad(set_to_none=True)
            logits, _ = model(core_tokens, allele_tokens, core_mask=core_mask, allele_mask=allele_mask)
            loss = loss_fn(logits, labels)
            loss.backward()
            optimizer.step()
            total_loss += float(loss.detach()) * len(labels)
            total_items += len(labels)
        history.append({"epoch": float(epoch), "loss": total_loss / max(total_items, 1)})

    config.output_dir.mkdir(parents=True, exist_ok=True)
    checkpoint_path = config.output_dir / f"{config.checkpoint_track}.pt"
    torch.save(
        {
            "model_state": model.state_dict(),
            "model_config": model_config,
            "train_config": {key: str(value) for key, value in asdict(config).items()},
            "history": history,
            "decoy_stats": asdict(decoy_stats) if decoy_stats else None,
        },
        checkpoint_path,
    )
    (config.output_dir / f"{config.checkpoint_track}.history.json").write_text(
        json.dumps(history, indent=2) + "\n",
        encoding="utf-8",
    )
    return checkpoint_path


def _records_with_pseudosequences(
    records: list[MHC2Record], pseudosequences: dict[str, str]
) -> list[MHC2Record]:
    filtered: list[MHC2Record] = []
    for record in records:
        alleles = tuple(allele for allele in record.alleles if allele in pseudosequences)
        if alleles:
            filtered.append(MHC2Record.from_json({**record.to_json(), "alleles": list(alleles)}))
    return filtered
