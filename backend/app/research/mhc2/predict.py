"""Checkpoint loading and prediction helpers for the optional MHC-II model.

The predictor auto-detects which model architecture a checkpoint was
trained with (Phase A from-scratch ``MHCIIInteractionModel`` vs. Phase B
``MHCIIESMModel``) by inspecting the model_config keys saved alongside
the weights, then loads the matching feature path.
"""

from __future__ import annotations

import bisect
from dataclasses import dataclass
from pathlib import Path

from app.research.mhc2.alleles import normalize_mhc2_allele
from app.research.mhc2.data import load_pseudosequences
from app.research.mhc2.model import (
    PAD_INDEX,
    CorePrediction,
    MHCIIESMModel,
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


# Keys that uniquely identify each model architecture's config.
_ESM_KEYS = {"esm_dim", "adapter_layers", "adapter_heads", "adapter_hidden"}
_SCRATCH_KEYS = {"embedding_dim", "hidden_dim", "attention_heads", "num_layers"}


class MHC2Predictor:
    def __init__(
        self,
        checkpoint_path: Path,
        pseudosequence_path: Path,
        percentile_ranker: PercentileRanker | None = None,
        device: str = "cpu",
        esm_cache_dir: Path | None = None,
    ) -> None:
        if not TORCH_AVAILABLE:
            raise MissingTorchError(
                "PyTorch is required for MHC-II prediction. "
                "Install backend/requirements-mhc2.txt in a research environment."
            )
        import torch

        self.device = torch.device(device)
        checkpoint_path = Path(checkpoint_path)
        payload = torch.load(checkpoint_path, map_location=self.device, weights_only=False)
        config = payload.get("model_config", {})
        is_esm = bool(set(config.keys()) & _ESM_KEYS)
        if is_esm:
            self.model_kind = "esm2_35m"
            if esm_cache_dir is None:
                raise ValueError(
                    f"checkpoint {checkpoint_path} is an ESM model but no esm_cache_dir was provided"
                )
            from app.research.mhc2.esm import load_packed_or_dict_cache, load_esm2_35m
            self.peptide_features = load_packed_or_dict_cache(esm_cache_dir, "peptides")
            self.pseudoseq_features = load_packed_or_dict_cache(esm_cache_dir, "pseudoseqs")
            # We also need a live ESM model for OOC peptides at inference
            # time; benchmark sets are usually a subset of the cache so this
            # rarely fires.
            self._esm_model = None
            self._esm_tokenizer = None
            self.model = MHCIIESMModel(**config).to(self.device)
        else:
            self.model_kind = "scratch"
            self.model = MHCIIInteractionModel(**config).to(self.device)
        self.model.load_state_dict(payload["model_state"])
        self.model.eval()
        self.pseudosequences = load_pseudosequences(Path(pseudosequence_path))
        self.percentile_ranker = percentile_ranker
        self._esm_dim = int(config.get("esm_dim", 480))
        self._max_pseudoseq_length = int(config.get("max_pseudoseq_length", 64))

    def predict_one(self, peptide: str, allele: str) -> PresentationPrediction:
        import torch

        normalized = normalize_mhc2_allele(allele).normalized
        pseudoseq = self.pseudosequences.get(normalized)
        if pseudoseq is None:
            raise KeyError(f"missing pseudosequence for {normalized}")
        cores = enumerate_cores(peptide)

        if self.model_kind == "scratch":
            core_tokens = torch.tensor(
                [[encode_sequence(core, 9) for _, core in cores]],
                dtype=torch.long,
                device=self.device,
            )
            allele_tokens = torch.tensor(
                [[[t for t in encode_sequence(pseudoseq, self.model.max_pseudoseq_length)]]],
                dtype=torch.long,
                device=self.device,
            )
            with torch.no_grad():
                out = self.model(core_tokens, allele_tokens)
                grid = out[1]
                probabilities = torch.sigmoid(grid[0, 0]).detach().cpu().tolist()
        else:
            # ESM path: look up cached features (or live-embed if absent).
            peptide_feat = self._lookup_peptide_features(peptide)
            pseudoseq_feat = self._lookup_pseudoseq_features(pseudoseq)
            core_feats = []
            core_pad = torch.zeros(9, self._esm_dim, dtype=torch.float32)
            for offset, core in cores:
                if len(peptide) >= 9:
                    sliced = peptide_feat[offset : offset + 9]
                else:
                    sliced = peptide_feat
                if sliced.shape[0] < 9:
                    padded = core_pad.clone()
                    padded[: sliced.shape[0]] = sliced
                    sliced = padded
                core_feats.append(sliced)
            cf = torch.stack(core_feats, dim=0).unsqueeze(0).to(self.device)  # [1, n_cores, 9, d]
            allele_pad = torch.zeros(self._max_pseudoseq_length, self._esm_dim,
                                     dtype=torch.float32)
            ps_truncated = pseudoseq_feat[: self._max_pseudoseq_length]
            ap = allele_pad.clone()
            ap[: ps_truncated.shape[0]] = ps_truncated
            af = ap.unsqueeze(0).unsqueeze(0).to(self.device)  # [1, 1, max_len, d]
            with torch.no_grad():
                out = self.model(cf, af)
                grid = out[1]
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

    def _lookup_peptide_features(self, peptide):
        feat = self.peptide_features.get(peptide)
        if feat is not None:
            return feat.float()
        # Out-of-cache: live-embed. Lazy-load the ESM model.
        from app.research.mhc2.esm import embed_sequences, load_esm2_35m
        if self._esm_model is None:
            self._esm_model, self._esm_tokenizer = load_esm2_35m(device=str(self.device))
        feats = embed_sequences(
            self._esm_model, self._esm_tokenizer, [peptide],
            device=str(self.device), batch_size=1,
        )
        return feats[0].float()

    def _lookup_pseudoseq_features(self, pseudoseq):
        feat = self.pseudoseq_features.get(pseudoseq)
        if feat is not None:
            return feat.float()
        from app.research.mhc2.esm import embed_sequences, load_esm2_35m
        if self._esm_model is None:
            self._esm_model, self._esm_tokenizer = load_esm2_35m(device=str(self.device))
        feats = embed_sequences(
            self._esm_model, self._esm_tokenizer, [pseudoseq],
            device=str(self.device), batch_size=1,
        )
        return feats[0].float()


__all__ = [
    "CorePrediction",
    "MHC2Predictor",
    "PercentileRanker",
    "PresentationPrediction",
    "PAD_INDEX",
]
