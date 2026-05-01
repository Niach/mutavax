"""HLAIIPred baseline adapter.

Wraps the open-source HLAIIPred 2025 model (pfizer-opensource/HLAIIPred,
Karasev et al., Communications Biology 2025) through its Python API.
HLAIIPred ships two ensemble checkpoints; the publication score is the
mean of both, so this adapter follows that convention.

Setup expectations on the host:

    git clone https://github.com/pfizer-opensource/HLAIIPred /path/to/HLAIIPred
    pip install -e /path/to/HLAIIPred
    pip install pandas tqdm pyyaml biopython

Set ``HLAIIPRED_ROOT`` to the repo path so the adapter knows where to
find the bundled ``models/`` and ``mhcII/`` directories. Alternatively,
pass them explicitly to the constructor.

The model takes peptides + a per-peptide list-of-up-to-14-alleles. We
score each (peptide, allele) pair as a single-allele input so the output
is the model's prediction for that exact pair (the 13 unused slots are
filled with ``0`` per the example script).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Sequence

from app.research.mhc2.baselines.base import BaselineModel, BaselinePrediction


class HLAIIPredAdapter(BaselineModel):
    name = "HLAIIPred-2025"

    def __init__(
        self,
        repo_root: str | None = None,
        *,
        model_dir: str | None = None,
        mhc2_dir: str | None = None,
        device: str = "auto",
        batch_size: int = 256,
    ) -> None:
        repo_root = repo_root or os.environ.get("HLAIIPRED_ROOT")
        if repo_root:
            self._model_dir = model_dir or str(Path(repo_root) / "models")
            self._mhc2_dir = mhc2_dir or str(Path(repo_root) / "mhcII")
        else:
            self._model_dir = model_dir
            self._mhc2_dir = mhc2_dir
        self._device = device
        self._batch_size = batch_size
        self._predictors = None

    def is_available(self) -> tuple[bool, str]:
        if not self._model_dir or not self._mhc2_dir:
            return (
                False,
                "HLAIIPred not configured (set $HLAIIPRED_ROOT or pass repo_root)",
            )
        if not Path(self._model_dir).exists() or not Path(self._mhc2_dir).exists():
            return (False, f"missing dirs: {self._model_dir} / {self._mhc2_dir}")
        try:
            import hlapred  # noqa: F401
        except ModuleNotFoundError:
            return (
                False,
                "hlapred package not installed (pip install -e <HLAIIPRED_ROOT>)",
            )
        try:
            import pandas, yaml  # noqa: F401
        except ModuleNotFoundError as exc:
            return (False, f"HLAIIPred runtime dep missing: {exc.name}")
        return (True, f"models={self._model_dir}")

    def _resolve_device(self):
        import torch
        if self._device == "auto":
            return torch.device("cuda" if torch.cuda.is_available() else "cpu")
        return torch.device(self._device)

    def predict(self, pairs: Sequence[tuple[str, str]]) -> list[BaselinePrediction]:
        ok, msg = self.is_available()
        if not ok:
            raise RuntimeError(msg)
        import numpy as np
        from collections import defaultdict

        predictors = self._load_predictors()

        # Group by HLAIIPred-formatted allele so an unsupported allele only
        # NaNs out its own group instead of crashing the whole batch.
        # HLAIIPred raises KeyError inside prepare_input when the alpha or
        # beta chain isn't in its bundled mhcII/{alpha,beta}_dict.
        groups: dict[str, list[int]] = defaultdict(list)
        converted_alleles: list[str] = []
        for idx, (_peptide, allele) in enumerate(pairs):
            converted = _to_hlaiipred_allele(allele)
            converted_alleles.append(converted)
            groups[converted].append(idx)

        out: list[BaselinePrediction | None] = [None] * len(pairs)
        for converted, indices in groups.items():
            group_peptides = [pairs[i][0] for i in indices]
            slots = [[converted] + [0] * 13 for _ in indices]
            try:
                ensemble = []
                for predictor in predictors:
                    inputs = predictor.prepare_input(group_peptides, slots)
                    y_pred, _ = predictor.predict(
                        inputs, batch_size=self._batch_size, sigmoid=True
                    )
                    ensemble.append(np.asarray(y_pred, dtype=float))
                scores = (ensemble[0] + ensemble[1]) / 2.0
                for local_i, idx in enumerate(indices):
                    peptide, allele = pairs[idx]
                    out[idx] = BaselinePrediction(
                        peptide=peptide,
                        allele=allele,
                        score=float(scores[local_i]),
                        rank_percent=float("nan"),
                    )
            except KeyError:
                # Unsupported allele in HLAIIPred's reference dictionaries
                # (e.g. rare DPB1*10:401). Mark group as NaN so polyallelic
                # max-over-alleles can still try other alleles for the same
                # record. Mirrors NetMHCIIpan / MixMHC2pred adapter policy.
                for idx in indices:
                    peptide, allele = pairs[idx]
                    out[idx] = BaselinePrediction(
                        peptide=peptide,
                        allele=allele,
                        score=float("nan"),
                        rank_percent=float("nan"),
                    )

        return [item for item in out if item is not None]

    def _load_predictors(self):
        if self._predictors is None:
            from hlapred.predict import HLAIIPredict

            device = self._resolve_device()
            self._predictors = [
                HLAIIPredict(self._model_dir, idx, device, self._mhc2_dir)
                for idx in (0, 1)
            ]
        return self._predictors


def _to_hlaiipred_allele(allele: str) -> str:
    """HLAIIPred uses IPD nomenclature without the leading ``HLA-`` prefix.

    Examples:
        HLA-DRB1*15:01            -> DRB1*15:01
        HLA-DPA1*01:03-DPB1*04:01 -> DPA1*01:03-DPB1*04:01
        HLA-DQA1*01:02-DQB1*06:02 -> DQA1*01:02-DQB1*06:02
    """
    return allele.removeprefix("HLA-")
