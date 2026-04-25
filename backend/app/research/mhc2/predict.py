"""Checkpoint loading and prediction helpers for the optional MHC-II model."""

from __future__ import annotations

import bisect
from dataclasses import dataclass
from pathlib import Path

from app.research.mhc2.alleles import normalize_mhc2_allele
from app.research.mhc2.data import load_pseudosequences
from app.research.mhc2.model import (
    PAD_INDEX,
    CorePrediction,
    MHCIIInteractionModel,
    MissingTorchError,
    TORCH_AVAILABLE,
    encode_sequence,
    enumerate_cores,
)


@dataclass(frozen=True)
class PresentationPrediction:
    peptide: str
    allele: str
    score: float
    core: str
    core_offset: int
    percentile_rank: float | None = None


class PercentileRanker:
    def __init__(self, background_scores: dict[str, list[float]]) -> None:
        self.background_scores = {
            allele: sorted(scores) for allele, scores in background_scores.items() if scores
        }

    def rank(self, allele: str, score: float) -> float | None:
        scores = self.background_scores.get(allele)
        if not scores:
            return None
        better = len(scores) - bisect.bisect_left(scores, score)
        return 100.0 * better / len(scores)


class MHC2Predictor:
    def __init__(
        self,
        checkpoint_path: Path,
        pseudosequence_path: Path,
        percentile_ranker: PercentileRanker | None = None,
        device: str = "cpu",
    ) -> None:
        if not TORCH_AVAILABLE:
            raise MissingTorchError(
                "PyTorch is required for MHC-II prediction. "
                "Install backend/requirements-mhc2.txt in a research environment."
            )
        import torch

        self.device = torch.device(device)
        payload = torch.load(checkpoint_path, map_location=self.device)
        config = payload.get("model_config", {})
        self.model = MHCIIInteractionModel(**config).to(self.device)
        self.model.load_state_dict(payload["model_state"])
        self.model.eval()
        self.pseudosequences = load_pseudosequences(pseudosequence_path)
        self.percentile_ranker = percentile_ranker

    def predict_one(self, peptide: str, allele: str) -> PresentationPrediction:
        import torch

        normalized = normalize_mhc2_allele(allele).normalized
        pseudoseq = self.pseudosequences.get(normalized)
        if pseudoseq is None:
            raise KeyError(f"missing pseudosequence for {normalized}")
        cores = enumerate_cores(peptide)
        core_tokens = torch.tensor(
            [[encode_sequence(core, 9) for _, core in cores]],
            dtype=torch.long,
            device=self.device,
        )
        allele_tokens = torch.tensor(
            [[[token for token in encode_sequence(pseudoseq, self.model.max_pseudoseq_length)]]],
            dtype=torch.long,
            device=self.device,
        )
        with torch.no_grad():
            _, grid = self.model(core_tokens, allele_tokens)
            probabilities = torch.sigmoid(grid[0, 0]).detach().cpu().tolist()
        best_index = max(range(len(probabilities)), key=probabilities.__getitem__)
        score = float(probabilities[best_index])
        offset, core = cores[best_index]
        rank = self.percentile_ranker.rank(normalized, score) if self.percentile_ranker else None
        return PresentationPrediction(
            peptide=peptide,
            allele=normalized,
            score=score,
            core=core.replace("X", ""),
            core_offset=offset,
            percentile_rank=rank,
        )


__all__ = [
    "CorePrediction",
    "MHC2Predictor",
    "PercentileRanker",
    "PresentationPrediction",
    "PAD_INDEX",
]

