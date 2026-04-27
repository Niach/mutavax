"""Training loop for the optional open MHC-II PyTorch model."""

from __future__ import annotations

import json
import time
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Sequence

from app.research.mhc2.data import MHC2Record, load_pseudosequences, read_jsonl
from app.research.mhc2.decoys import (
    positive_9mer_index,
    read_fasta_sequences,
    sample_length_matched_decoys,
)
from app.research.mhc2.metrics import roc_auc
from app.research.mhc2.model import (
    MHCIIInteractionModel,
    MHCIIESMModel,
    MissingTorchError,
    TORCH_AVAILABLE,
    encode_sequence,
    enumerate_cores,
)


if TORCH_AVAILABLE:  # pragma: no cover
    import torch as _torch
    from torch.utils.data import Dataset as _TorchDataset

    class _RecordDataset(_TorchDataset):
        """Module-level Dataset so DataLoader workers can pickle it."""

        def __init__(self, records: Sequence[MHC2Record]) -> None:
            self.records = list(records)

        def __len__(self) -> int:
            return len(self.records)

        def __getitem__(self, index: int) -> MHC2Record:
            return self.records[index]

    class _ESMCollator:
        """Phase B collator that emits pre-computed ESM features instead of
        token IDs. Module-level so DataLoader workers can pickle it.

        Symmetric embedding policy:
        * Positives AND decoys are looked up by peptide string in
          ``peptide_features`` -> Tensor(peptide_len, esm_dim). Both kinds
          of record are therefore embedded with the *same* ESM context
          (a standalone peptide of their own length), which avoids the
          context-asymmetry leak that an earlier protein-level decoy
          cache produced.
        * Alleles: pseudoseq string from ``pseudosequences[allele]`` looks
          up ``pseudoseq_features``.
        """

        def __init__(
            self,
            peptide_features: dict,
            pseudoseq_features: dict,
            pseudosequences: dict[str, str],
            esm_dim: int,
            max_pseudoseq_length: int,
        ) -> None:
            self.peptide_features = peptide_features
            self.pseudoseq_features = pseudoseq_features
            self.pseudosequences = pseudosequences
            self.esm_dim = esm_dim
            self.max_pseudoseq_length = max_pseudoseq_length

        def _peptide_features(self, record: MHC2Record) -> "_torch.Tensor":
            feat = self.peptide_features.get(record.peptide)
            if feat is None:
                raise KeyError(f"missing ESM features for peptide {record.peptide!r}")
            if feat.shape[0] != len(record.peptide):
                raise ValueError(
                    f"feature length {feat.shape[0]} does not match peptide "
                    f"{record.peptide!r} length {len(record.peptide)}"
                )
            return feat

        def __call__(self, records: list[MHC2Record]) -> tuple:
            max_cores = max(len(enumerate_cores(record.peptide)) for record in records)
            max_alleles = max(len(record.alleles) for record in records)
            core_pad = _torch.zeros(9, self.esm_dim, dtype=_torch.float32)
            allele_pad = _torch.zeros(self.max_pseudoseq_length, self.esm_dim, dtype=_torch.float32)
            batch_core: list = []
            batch_allele: list = []
            core_masks: list[list[bool]] = []
            allele_masks: list[list[bool]] = []
            labels: list[float] = []
            primary_alleles: list[str] = []
            label_types: list[int] = []  # 0 = presentation, 1 = affinity
            ba_values: list[float] = []
            sample_weights: list[float] = []
            for record in records:
                peptide_feat = self._peptide_features(record).float()
                core_tensors: list = []
                for offset, core in enumerate_cores(record.peptide):
                    if len(record.peptide) >= 9:
                        sliced = peptide_feat[offset : offset + 9]
                    else:
                        sliced = peptide_feat
                    if sliced.shape[0] < 9:
                        padded = core_pad.clone()
                        padded[: sliced.shape[0]] = sliced
                        sliced = padded
                    core_tensors.append(sliced)
                core_mask = [True] * len(core_tensors)
                while len(core_tensors) < max_cores:
                    core_tensors.append(core_pad)
                    core_mask.append(False)
                allele_tensors = []
                for allele in record.alleles:
                    pseudoseq = self.pseudosequences.get(allele)
                    if pseudoseq is None:
                        continue
                    feat = self.pseudoseq_features.get(pseudoseq)
                    if feat is None:
                        raise KeyError(f"missing ESM features for pseudoseq {pseudoseq!r}")
                    truncated = feat[: self.max_pseudoseq_length].float()
                    padded = allele_pad.clone()
                    padded[: truncated.shape[0]] = truncated
                    allele_tensors.append(padded)
                allele_mask = [True] * len(allele_tensors)
                while len(allele_tensors) < max_alleles:
                    allele_tensors.append(allele_pad)
                    allele_mask.append(False)
                batch_core.append(_torch.stack(core_tensors, dim=0))
                batch_allele.append(_torch.stack(allele_tensors, dim=0))
                core_masks.append(core_mask)
                allele_masks.append(allele_mask)
                labels.append(record.target)
                primary_alleles.append(record.alleles[0] if record.alleles else "other")
                label_types.append(1 if record.label_type == "affinity" else 0)
                ba_values.append(record.ba_value if record.ba_value is not None else 0.0)
                sample_weights.append(record.cluster_weight)
            return (
                _torch.stack(batch_core, dim=0),
                _torch.stack(batch_allele, dim=0),
                _torch.tensor(core_masks, dtype=_torch.bool),
                _torch.tensor(allele_masks, dtype=_torch.bool),
                _torch.tensor(labels, dtype=_torch.float32),
                primary_alleles,
                _torch.tensor(label_types, dtype=_torch.long),
                _torch.tensor(ba_values, dtype=_torch.float32),
                _torch.tensor(sample_weights, dtype=_torch.float32),
            )

    class _Collator:
        """Module-level callable so DataLoader workers can pickle it."""

        def __init__(self, pseudosequences: dict[str, str], max_pseudoseq_length: int) -> None:
            self.pseudosequences = pseudosequences
            self.max_pseudoseq_length = max_pseudoseq_length

        def __call__(self, records: list[MHC2Record]) -> tuple:
            max_cores = max(len(enumerate_cores(record.peptide)) for record in records)
            max_alleles = max(len(record.alleles) for record in records)
            core_batch: list[list[list[int]]] = []
            allele_batch: list[list[list[int]]] = []
            core_masks: list[list[bool]] = []
            allele_masks: list[list[bool]] = []
            labels: list[float] = []
            primary_alleles: list[str] = []
            label_types: list[int] = []
            ba_values: list[float] = []
            sample_weights: list[float] = []
            for record in records:
                cores = [encode_sequence(core, 9) for _, core in enumerate_cores(record.peptide)]
                core_mask = [True] * len(cores)
                while len(cores) < max_cores:
                    cores.append([0] * 9)
                    core_mask.append(False)
                alleles = [
                    encode_sequence(self.pseudosequences[allele], self.max_pseudoseq_length)
                    for allele in record.alleles
                    if allele in self.pseudosequences
                ]
                allele_mask = [True] * len(alleles)
                while len(alleles) < max_alleles:
                    alleles.append([0] * self.max_pseudoseq_length)
                    allele_mask.append(False)
                core_batch.append(cores)
                allele_batch.append(alleles)
                core_masks.append(core_mask)
                allele_masks.append(allele_mask)
                labels.append(record.target)
                primary_alleles.append(record.alleles[0] if record.alleles else "other")
                label_types.append(1 if record.label_type == "affinity" else 0)
                ba_values.append(record.ba_value if record.ba_value is not None else 0.0)
                sample_weights.append(record.cluster_weight)
            return (
                _torch.tensor(core_batch, dtype=_torch.long),
                _torch.tensor(allele_batch, dtype=_torch.long),
                _torch.tensor(core_masks, dtype=_torch.bool),
                _torch.tensor(allele_masks, dtype=_torch.bool),
                _torch.tensor(labels, dtype=_torch.float32),
                primary_alleles,
                _torch.tensor(label_types, dtype=_torch.long),
                _torch.tensor(ba_values, dtype=_torch.float32),
                _torch.tensor(sample_weights, dtype=_torch.float32),
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
    device: str = "auto"
    num_workers: int = 0
    log_every: int = 200
    save_every_epoch: bool = True
    early_stopping_patience: int = 0  # 0 disables; otherwise stop after N epochs without val_auc improvement
    embedding_dim: int = 96
    hidden_dim: int = 128
    attention_heads: int = 4
    num_layers: int = 2
    dropout: float = 0.1
    warmup_steps: int = 0  # 0 disables LR scheduler entirely
    min_lr: float = 1e-6  # cosine decay floor
    bf16: bool = False  # bfloat16 autocast on CUDA (Ampere+/Ada). No-op on CPU.
    model_kind: str = "scratch"  # "scratch" (Phase A) or "esm2_35m" (Phase B)
    esm_cache_dir: Path | None = None  # required when model_kind != "scratch"
    esm_dim: int = 480  # 35M model output dim
    esm_adapter_layers: int = 2
    esm_adapter_heads: int = 8
    esm_adapter_hidden: int = 1024
    multi_task_ba: bool = False  # add a BA regression head and mix EL + BA loss
    ba_loss_weight: float = 0.3  # lambda on the BA term: total = L_el + lambda * L_ba
    cluster_weighted: bool = False  # use record.cluster_weight in loss


def _multi_task_loss(
    model_out,
    labels,
    label_types,
    ba_values,
    sample_weights,
    loss_fn,
    ba_loss_fn,
    config: "TrainConfig",
):
    """Combined EL (BCE) + BA (MSE on log-affinity) loss with optional
    cluster weighting. ``model_out`` is either ``(sample_logits, grid)``
    when ``with_ba_head=False`` or ``(sample_logits, grid, ba_logits)``
    when the BA head is enabled."""
    sample_logits = model_out[0]
    el_mask = label_types == 0
    ba_mask = label_types == 1
    weights = sample_weights if config.cluster_weighted else None

    el_loss = loss_fn(sample_logits, labels)  # per-record (reduction='none')
    if weights is not None:
        el_loss = el_loss * weights
    if el_mask.any():
        el_term = el_loss[el_mask].mean()
    else:
        el_term = sample_logits.sum() * 0.0  # zero with grad

    if config.multi_task_ba and len(model_out) >= 3 and ba_mask.any():
        ba_logits = model_out[2]
        ba_pred = _torch.sigmoid(ba_logits)
        ba_loss = ba_loss_fn(ba_pred, ba_values)
        if weights is not None:
            ba_loss = ba_loss * weights
        ba_term = ba_loss[ba_mask].mean()
        return el_term + config.ba_loss_weight * ba_term
    return el_term


def _resolve_device(requested: str) -> str:
    import torch

    if requested != "auto":
        return requested
    return "cuda" if torch.cuda.is_available() else "cpu"


def _locus_for(allele: str) -> str:
    body = allele.removeprefix("HLA-").split("*", 1)[0]
    if body.startswith("DR"):
        return "DR"
    if body.startswith("DQ"):
        return "DQ"
    if body.startswith("DP"):
        return "DP"
    return "other"


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
    device = torch.device(_resolve_device(config.device))

    pseudosequences = load_pseudosequences(config.pseudosequences)

    print(f"[train] device={device} pseudoseqs={len(pseudosequences)}", flush=True)

    train_positives = _records_with_pseudosequences(
        list(read_jsonl(config.train_jsonl)), pseudosequences
    )
    print(f"[train] train positives kept: {len(train_positives)}", flush=True)

    decoy_stats = None
    train_records: list[MHC2Record] = train_positives
    if config.proteome_fasta is not None:
        proteome = read_fasta_sequences(config.proteome_fasta)
        positive_9mers = positive_9mer_index(train_positives)
        decoys, decoy_stats = sample_length_matched_decoys(
            train_positives,
            proteome,
            positive_9mers=positive_9mers,
            per_positive=config.decoys_per_positive,
            seed=config.seed,
        )
        train_records = train_positives + decoys
        print(
            f"[train] decoys generated: {decoy_stats.generated} "
            f"(rejected_overlap={decoy_stats.rejected_overlap})",
            flush=True,
        )

    valid_records: list[MHC2Record] = []
    if config.valid_jsonl is not None:
        valid_positives = _records_with_pseudosequences(
            list(read_jsonl(config.valid_jsonl)), pseudosequences
        )
        if config.proteome_fasta is not None:
            valid_decoys, _ = sample_length_matched_decoys(
                valid_positives,
                read_fasta_sequences(config.proteome_fasta),
                positive_9mers=positive_9mer_index(valid_positives),
                per_positive=config.decoys_per_positive,
                seed=config.seed + 1,
            )
            valid_records = valid_positives + valid_decoys
        else:
            valid_records = valid_positives
        print(f"[train] valid records: {len(valid_records)}", flush=True)

    if config.model_kind == "esm2_35m":
        from app.research.mhc2.esm import load_packed_or_dict_cache

        if config.esm_cache_dir is None:
            raise ValueError("esm_cache_dir is required for model_kind=esm2_35m")
        print(f"[train] loading ESM caches from {config.esm_cache_dir}", flush=True)
        peptide_features = load_packed_or_dict_cache(config.esm_cache_dir, "peptides")
        pseudoseq_features = load_packed_or_dict_cache(config.esm_cache_dir, "pseudoseqs")
        print(
            f"[train] esm cache: {len(peptide_features)} peptides "
            f"({type(peptide_features).__name__}), "
            f"{len(pseudoseq_features)} pseudoseqs "
            f"({type(pseudoseq_features).__name__})",
            flush=True,
        )
        collate = _ESMCollator(
            peptide_features=peptide_features,
            pseudoseq_features=pseudoseq_features,
            pseudosequences=pseudosequences,
            esm_dim=config.esm_dim,
            max_pseudoseq_length=config.max_pseudoseq_length,
        )
    else:
        collate = _Collator(pseudosequences, config.max_pseudoseq_length)

    if config.model_kind == "esm2_35m":
        model_config = {
            "esm_dim": config.esm_dim,
            "adapter_layers": config.esm_adapter_layers,
            "adapter_heads": config.esm_adapter_heads,
            "adapter_hidden": config.esm_adapter_hidden,
            "max_pseudoseq_length": config.max_pseudoseq_length,
            "dropout": config.dropout,
            "with_ba_head": config.multi_task_ba,
        }
        model = MHCIIESMModel(**model_config).to(device)
        n_params = sum(p.numel() for p in model.parameters() if p.requires_grad)
        print(
            f"[train] ESM-2 adapter: dim={config.esm_dim} "
            f"layers={config.esm_adapter_layers} heads={config.esm_adapter_heads} "
            f"hidden={config.esm_adapter_hidden} trainable_params={n_params:,}",
            flush=True,
        )
    else:
        model_config = {
            "max_pseudoseq_length": config.max_pseudoseq_length,
            "embedding_dim": config.embedding_dim,
            "hidden_dim": config.hidden_dim,
            "attention_heads": config.attention_heads,
            "num_layers": config.num_layers,
            "dropout": config.dropout,
        }
        model = MHCIIInteractionModel(**model_config).to(device)
        n_params = sum(p.numel() for p in model.parameters() if p.requires_grad)
        print(
            f"[train] model dim={config.embedding_dim} hidden={config.hidden_dim} "
            f"layers={config.num_layers} heads={config.attention_heads} "
            f"params={n_params:,}",
            flush=True,
        )
    optimizer = torch.optim.AdamW(model.parameters(), lr=config.learning_rate)
    loss_fn = nn.BCEWithLogitsLoss(reduction="none")
    ba_loss_fn = nn.MSELoss(reduction="none")

    use_bf16 = config.bf16 and device.type == "cuda" and torch.cuda.is_bf16_supported()
    if config.bf16 and not use_bf16:
        print("[train] bf16 requested but unsupported on this device; falling back to fp32", flush=True)
    if use_bf16:
        print("[train] enabling bf16 autocast for forward/loss", flush=True)
    if config.multi_task_ba:
        print(
            f"[train] multi-task BA head enabled (ba_loss_weight={config.ba_loss_weight})",
            flush=True,
        )
    if config.cluster_weighted:
        print("[train] cluster-weighted loss enabled", flush=True)

    pin = device.type == "cuda"
    train_loader = DataLoader(
        _RecordDataset(train_records),
        batch_size=config.batch_size,
        shuffle=True,
        collate_fn=collate,
        num_workers=config.num_workers,
        pin_memory=pin,
    )
    valid_loader = (
        DataLoader(
            _RecordDataset(valid_records),
            batch_size=config.batch_size,
            shuffle=False,
            collate_fn=collate,
            num_workers=config.num_workers,
            pin_memory=pin,
        )
        if valid_records
        else None
    )

    scheduler = None
    if config.warmup_steps > 0:
        total_steps = max(len(train_loader) * config.epochs, config.warmup_steps + 1)
        cosine_steps = max(total_steps - config.warmup_steps, 1)
        end_factor = max(config.min_lr / config.learning_rate, 1e-8)
        warmup = torch.optim.lr_scheduler.LinearLR(
            optimizer, start_factor=1e-3, end_factor=1.0, total_iters=config.warmup_steps
        )
        cosine = torch.optim.lr_scheduler.CosineAnnealingLR(
            optimizer, T_max=cosine_steps, eta_min=config.min_lr
        )
        scheduler = torch.optim.lr_scheduler.SequentialLR(
            optimizer, schedulers=[warmup, cosine], milestones=[config.warmup_steps]
        )
        print(
            f"[train] LR schedule: linear warmup {config.warmup_steps} steps -> "
            f"cosine decay over {cosine_steps} steps "
            f"({config.learning_rate:.2e} -> {config.min_lr:.2e}); "
            f"end_factor={end_factor:.2e}",
            flush=True,
        )

    def _save(path: Path, epoch: int) -> None:
        torch.save(
            {
                "model_state": model.state_dict(),
                "model_config": model_config,
                "train_config": {key: str(value) for key, value in asdict(config).items()},
                "history": history,
                "decoy_stats": asdict(decoy_stats) if decoy_stats else None,
                "epoch": epoch,
            },
            path,
        )

    history: list[dict[str, float | dict[str, float]]] = []
    best_val_auc = float("-inf")
    epochs_without_improvement = 0
    for epoch in range(1, config.epochs + 1):
        model.train()
        total_loss = 0.0
        total_items = 0
        epoch_t0 = time.time()
        for step, batch in enumerate(train_loader, start=1):
            (
                core_tokens, allele_tokens, core_mask, allele_mask,
                labels, _, label_types, ba_values, sample_weights,
            ) = batch
            core_tokens = core_tokens.to(device, non_blocking=pin)
            allele_tokens = allele_tokens.to(device, non_blocking=pin)
            core_mask = core_mask.to(device, non_blocking=pin)
            allele_mask = allele_mask.to(device, non_blocking=pin)
            labels = labels.to(device, non_blocking=pin)
            label_types = label_types.to(device, non_blocking=pin)
            ba_values = ba_values.to(device, non_blocking=pin)
            sample_weights = sample_weights.to(device, non_blocking=pin)
            optimizer.zero_grad(set_to_none=True)
            if use_bf16:
                with torch.autocast(device_type="cuda", dtype=torch.bfloat16):
                    out = model(
                        core_tokens, allele_tokens,
                        core_mask=core_mask, allele_mask=allele_mask,
                    )
                    loss = _multi_task_loss(
                        out, labels, label_types, ba_values, sample_weights,
                        loss_fn, ba_loss_fn, config,
                    )
            else:
                out = model(
                    core_tokens, allele_tokens,
                    core_mask=core_mask, allele_mask=allele_mask,
                )
                loss = _multi_task_loss(
                    out, labels, label_types, ba_values, sample_weights,
                    loss_fn, ba_loss_fn, config,
                )
            logits = out[0]
            loss.backward()
            optimizer.step()
            if scheduler is not None:
                scheduler.step()
            total_loss += float(loss.detach()) * len(labels)
            total_items += len(labels)
            if config.log_every and step % config.log_every == 0:
                rate = total_items / max(time.time() - epoch_t0, 1e-6)
                lr_now = optimizer.param_groups[0]["lr"]
                print(
                    f"[train] epoch={epoch} step={step}/{len(train_loader)} "
                    f"loss={total_loss/total_items:.4f} lr={lr_now:.2e} ({rate:.0f} ex/s)",
                    flush=True,
                )

        epoch_dt = time.time() - epoch_t0
        record: dict[str, float | dict[str, float]] = {
            "epoch": float(epoch),
            "loss": total_loss / max(total_items, 1),
            "epoch_seconds": epoch_dt,
        }

        if valid_loader is not None:
            val = _evaluate(model, valid_loader, loss_fn, device, pin, use_bf16=use_bf16)
            record.update(val)

        history.append(record)
        print(f"[train] epoch={epoch} done in {epoch_dt:.1f}s :: {record}", flush=True)

        config.output_dir.mkdir(parents=True, exist_ok=True)
        (config.output_dir / f"{config.checkpoint_track}.history.json").write_text(
            json.dumps(history, indent=2, default=float) + "\n",
            encoding="utf-8",
        )
        if config.save_every_epoch:
            _save(config.output_dir / f"{config.checkpoint_track}.epoch{epoch}.pt", epoch)
        _save(config.output_dir / f"{config.checkpoint_track}.pt", epoch)

        val_auc = record.get("val_auc")
        if isinstance(val_auc, float):
            if val_auc > best_val_auc:
                best_val_auc = val_auc
                _save(config.output_dir / f"{config.checkpoint_track}.best.pt", epoch)
                epochs_without_improvement = 0
                print(f"[train] new best val_auc={val_auc:.4f} at epoch {epoch}", flush=True)
            else:
                epochs_without_improvement += 1
                if config.early_stopping_patience and epochs_without_improvement >= config.early_stopping_patience:
                    print(
                        f"[train] early stop: no val_auc improvement for "
                        f"{epochs_without_improvement} epoch(s)",
                        flush=True,
                    )
                    break

    return config.output_dir / f"{config.checkpoint_track}.pt"


def _evaluate(model, loader, loss_fn, device, pin, use_bf16: bool = False) -> dict[str, float | dict[str, float]]:
    import torch

    model.eval()
    total_loss = 0.0
    total_items = 0
    all_labels: list[float] = []
    all_scores: list[float] = []
    per_locus: dict[str, tuple[list[float], list[float]]] = defaultdict(lambda: ([], []))
    with torch.no_grad():
        for batch in loader:
            # Newer collators emit 9 fields; fall back to legacy 6 for tests.
            core_tokens, allele_tokens, core_mask, allele_mask, labels, primary_alleles = batch[:6]
            core_tokens = core_tokens.to(device, non_blocking=pin)
            allele_tokens = allele_tokens.to(device, non_blocking=pin)
            core_mask = core_mask.to(device, non_blocking=pin)
            allele_mask = allele_mask.to(device, non_blocking=pin)
            labels_dev = labels.to(device, non_blocking=pin)
            if use_bf16:
                with torch.autocast(device_type="cuda", dtype=torch.bfloat16):
                    out = model(
                        core_tokens, allele_tokens, core_mask=core_mask, allele_mask=allele_mask
                    )
                    logits = out[0]
                    loss = loss_fn(logits, labels_dev)
                    if loss.ndim > 0:
                        loss = loss.mean()
                logits = logits.float()
            else:
                out = model(
                    core_tokens, allele_tokens, core_mask=core_mask, allele_mask=allele_mask
                )
                logits = out[0]
                loss = loss_fn(logits, labels_dev)
                if loss.ndim > 0:
                    loss = loss.mean()
            total_loss += float(loss.detach()) * len(labels)
            total_items += len(labels)
            scores = torch.sigmoid(logits).detach().cpu().tolist()
            label_list = labels.tolist()
            all_scores.extend(scores)
            all_labels.extend(label_list)
            for label, score, allele in zip(label_list, scores, primary_alleles):
                locus = _locus_for(allele)
                per_locus[locus][0].append(label)
                per_locus[locus][1].append(score)
    out: dict[str, float | dict[str, float]] = {
        "val_loss": total_loss / max(total_items, 1),
        "val_auc": roc_auc(all_labels, all_scores),
    }
    locus_aucs = {
        locus: roc_auc(labels, scores)
        for locus, (labels, scores) in per_locus.items()
        if len(set(labels)) > 1 and len(labels) >= 20
    }
    if locus_aucs:
        out["val_auc_by_locus"] = locus_aucs
    return out


def _records_with_pseudosequences(
    records: list[MHC2Record], pseudosequences: dict[str, str]
) -> list[MHC2Record]:
    filtered: list[MHC2Record] = []
    for record in records:
        alleles = tuple(allele for allele in record.alleles if allele in pseudosequences)
        if alleles:
            filtered.append(MHC2Record.from_json({**record.to_json(), "alleles": list(alleles)}))
    return filtered
