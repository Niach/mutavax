"""Our own MHC-II model wrapped as a baseline.

Lets the harness score "our model" alongside the third-party baselines
through the same ``BaselineModel`` interface. Loads a checkpoint via
``predict.predict_pairs`` and returns one prediction per pair.
"""

from __future__ import annotations

from pathlib import Path
from typing import Sequence

from app.research.mhc2.baselines.base import BaselineModel, BaselinePrediction


class OurModelAdapter(BaselineModel):
    name = "cancerstudio-mhc2"

    def __init__(
        self,
        checkpoint: Path,
        pseudosequences: Path,
        *,
        device: str = "auto",
        batch_size: int = 64,
        esm_cache_dir: Path | None = None,
    ) -> None:
        self._checkpoint = Path(checkpoint)
        self._pseudosequences = Path(pseudosequences)
        self._device = device
        self._batch_size = batch_size
        self._esm_cache_dir = Path(esm_cache_dir) if esm_cache_dir else None

    def is_available(self) -> tuple[bool, str]:
        if not self._checkpoint.exists():
            return (False, f"checkpoint missing: {self._checkpoint}")
        if not self._pseudosequences.exists():
            return (False, f"pseudosequences missing: {self._pseudosequences}")
        try:
            import torch  # noqa: F401
        except ModuleNotFoundError:
            return (False, "torch not available")
        return (True, f"checkpoint {self._checkpoint.name}")

    def predict(self, pairs: Sequence[tuple[str, str]]) -> list[BaselinePrediction]:
        ok, msg = self.is_available()
        if not ok:
            raise RuntimeError(msg)
        from app.research.mhc2.alleles import normalize_mhc2_allele
        from app.research.mhc2.predict import MHC2Predictor

        device = self._resolve_device()
        predictor = MHC2Predictor(
            checkpoint_path=self._checkpoint,
            pseudosequence_path=self._pseudosequences,
            device=device,
            esm_cache_dir=self._esm_cache_dir,
        )

        # Pre-filter pairs whose allele has no pseudoseq; mark NaN so a
        # single rare allele doesn't crash the whole batched call.
        out: list[BaselinePrediction | None] = [None] * len(pairs)
        keep_indices: list[int] = []
        keep_pairs: list[tuple[str, str]] = []
        for idx, (peptide, allele) in enumerate(pairs):
            try:
                normalized = normalize_mhc2_allele(allele).normalized
            except ValueError:
                out[idx] = BaselinePrediction(
                    peptide=peptide, allele=allele,
                    score=float("nan"), rank_percent=float("nan"),
                )
                continue
            if normalized not in predictor.pseudosequences:
                out[idx] = BaselinePrediction(
                    peptide=peptide, allele=allele,
                    score=float("nan"), rank_percent=float("nan"),
                )
                continue
            keep_indices.append(idx)
            keep_pairs.append((peptide, allele))

        if keep_pairs:
            predictions = predictor.predict_many(keep_pairs, batch_size=self._batch_size)
            for idx, prediction in zip(keep_indices, predictions):
                peptide, allele = pairs[idx]
                out[idx] = BaselinePrediction(
                    peptide=peptide,
                    allele=allele,
                    score=float(prediction.score),
                    rank_percent=float(prediction.percentile_rank or float("nan")),
                    core=prediction.core,
                    offset=prediction.core_offset,
                )

        return [item for item in out if item is not None]

    def _resolve_device(self) -> str:
        if self._device != "auto":
            return self._device
        try:
            import torch
            return "cuda" if torch.cuda.is_available() else "cpu"
        except ModuleNotFoundError:
            return "cpu"
