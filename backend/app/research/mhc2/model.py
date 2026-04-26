"""Optional-PyTorch MHC-II presentation model.

The model uses multiple-instance supervision: each peptide can bind through
any candidate 9-mer core and any allele in a polyallelic sample. The sample
score is the max over allele/core scores, while inference also returns the
best core and offset.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.research.mhc2.constants import MODEL_AMINO_ACIDS, PAD_TOKEN
from app.research.mhc2.data import clean_peptide


class MissingTorchError(RuntimeError):
    pass


try:  # pragma: no cover - exercised only in the optional training environment.
    import torch
    from torch import Tensor, nn

    TORCH_AVAILABLE = True
except ModuleNotFoundError:  # pragma: no cover - default lightweight dev env.
    torch = None  # type: ignore[assignment]
    Tensor = object  # type: ignore[assignment,misc]
    nn = object  # type: ignore[assignment]
    TORCH_AVAILABLE = False


VOCAB = {aa: index + 1 for index, aa in enumerate(MODEL_AMINO_ACIDS)}
PAD_INDEX = 0
UNKNOWN_INDEX = VOCAB[PAD_TOKEN]


@dataclass(frozen=True)
class CorePrediction:
    score: float
    core: str
    offset: int
    allele: str


def encode_sequence(sequence: str, max_length: int) -> list[int]:
    sequence = sequence.upper()
    encoded = [VOCAB.get(char, UNKNOWN_INDEX) for char in sequence[:max_length]]
    encoded.extend([PAD_INDEX] * (max_length - len(encoded)))
    return encoded


def enumerate_cores(peptide: str, core_length: int = 9) -> list[tuple[int, str]]:
    peptide = clean_peptide(peptide)
    if len(peptide) < core_length:
        return [(0, peptide + PAD_TOKEN * (core_length - len(peptide)))]
    return [
        (offset, peptide[offset : offset + core_length])
        for offset in range(len(peptide) - core_length + 1)
    ]


if TORCH_AVAILABLE:  # pragma: no cover

    class MHCIIESMModel(nn.Module):
        """Phase B model: frozen ESM-2 features + small adapter on each branch.

        Inputs are ``[batch, n_cores, 9, esm_dim]`` and ``[batch, n_alleles,
        pseudoseq_len, esm_dim]`` — pre-computed feature tensors, not token
        IDs. The adapter learns to specialize ESM's general PLM features to
        the binding-prediction task while keeping ESM frozen.
        """

        def __init__(
            self,
            esm_dim: int = 480,
            adapter_layers: int = 2,
            adapter_heads: int = 8,
            adapter_hidden: int = 1024,
            max_pseudoseq_length: int = 64,
            dropout: float = 0.1,
        ) -> None:
            super().__init__()
            self.esm_dim = esm_dim
            self.max_pseudoseq_length = max_pseudoseq_length
            self.core_adapter = nn.TransformerEncoder(
                nn.TransformerEncoderLayer(
                    d_model=esm_dim,
                    nhead=adapter_heads,
                    dim_feedforward=adapter_hidden,
                    dropout=dropout,
                    batch_first=True,
                ),
                num_layers=adapter_layers,
            )
            self.allele_adapter = nn.TransformerEncoder(
                nn.TransformerEncoderLayer(
                    d_model=esm_dim,
                    nhead=adapter_heads,
                    dim_feedforward=adapter_hidden,
                    dropout=dropout,
                    batch_first=True,
                ),
                num_layers=adapter_layers,
            )
            self.cross_attention = nn.MultiheadAttention(
                esm_dim, adapter_heads, dropout=dropout, batch_first=True
            )
            self.scorer = nn.Sequential(
                nn.Linear(esm_dim * 3, adapter_hidden),
                nn.GELU(),
                nn.Dropout(dropout),
                nn.Linear(adapter_hidden, 1),
            )

        def forward(
            self,
            core_feats: Tensor,
            allele_feats: Tensor,
            core_mask: Tensor | None = None,
            allele_mask: Tensor | None = None,
        ) -> tuple[Tensor, Tensor]:
            batch, n_cores, core_len, dim = core_feats.shape
            _, n_alleles, allele_len, _ = allele_feats.shape

            core_flat = core_feats.reshape(batch * n_cores, core_len, dim)
            allele_flat = allele_feats.reshape(batch * n_alleles, allele_len, dim)
            core_encoded = self.core_adapter(core_flat)
            allele_encoded = self.allele_adapter(allele_flat)

            core_pairs = core_encoded.reshape(batch, n_cores, core_len, dim)
            allele_pairs = allele_encoded.reshape(batch, n_alleles, allele_len, dim)
            core_pairs = (
                core_pairs[:, :, None, :, :]
                .expand(batch, n_cores, n_alleles, core_len, dim)
                .reshape(batch * n_cores * n_alleles, core_len, dim)
            )
            allele_pairs = (
                allele_pairs[:, None, :, :, :]
                .expand(batch, n_cores, n_alleles, allele_len, dim)
                .reshape(batch * n_cores * n_alleles, allele_len, dim)
            )

            attended, _ = self.cross_attention(core_pairs, allele_pairs, allele_pairs)
            core_pool = core_pairs.mean(dim=1)
            allele_pool = allele_pairs.mean(dim=1)
            attended_pool = attended.mean(dim=1)
            logits = self.scorer(
                torch.cat([core_pool, allele_pool, attended_pool], dim=-1)
            ).squeeze(-1)
            grid = logits.reshape(batch, n_cores, n_alleles).transpose(1, 2)

            if core_mask is None:
                core_mask = core_feats.abs().sum(dim=-1).ne(0).any(dim=-1)
            if allele_mask is None:
                allele_mask = allele_feats.abs().sum(dim=-1).ne(0).any(dim=-1)
            valid = allele_mask[:, :, None] & core_mask[:, None, :]
            masked_grid = grid.masked_fill(~valid, torch.finfo(grid.dtype).min)
            sample_logits = masked_grid.flatten(start_dim=1).max(dim=1).values
            return sample_logits, grid


    class MHCIIInteractionModel(nn.Module):
        def __init__(
            self,
            max_pseudoseq_length: int = 64,
            embedding_dim: int = 96,
            hidden_dim: int = 128,
            attention_heads: int = 4,
            num_layers: int = 2,
            dropout: float = 0.1,
        ) -> None:
            super().__init__()
            self.max_pseudoseq_length = max_pseudoseq_length
            self.embedding = nn.Embedding(
                len(VOCAB) + 1, embedding_dim, padding_idx=PAD_INDEX
            )
            self.core_encoder = nn.TransformerEncoder(
                nn.TransformerEncoderLayer(
                    d_model=embedding_dim,
                    nhead=attention_heads,
                    dim_feedforward=hidden_dim,
                    dropout=dropout,
                    batch_first=True,
                ),
                num_layers=num_layers,
            )
            self.allele_encoder = nn.TransformerEncoder(
                nn.TransformerEncoderLayer(
                    d_model=embedding_dim,
                    nhead=attention_heads,
                    dim_feedforward=hidden_dim,
                    dropout=dropout,
                    batch_first=True,
                ),
                num_layers=num_layers,
            )
            self.cross_attention = nn.MultiheadAttention(
                embedding_dim,
                attention_heads,
                dropout=dropout,
                batch_first=True,
            )
            self.scorer = nn.Sequential(
                nn.Linear(embedding_dim * 3, hidden_dim),
                nn.GELU(),
                nn.Dropout(dropout),
                nn.Linear(hidden_dim, 1),
            )

        def forward(
            self,
            core_tokens: Tensor,
            allele_tokens: Tensor,
            core_mask: Tensor | None = None,
            allele_mask: Tensor | None = None,
        ) -> tuple[Tensor, Tensor]:
            """Return sample scores and allele/core score grid.

            ``core_tokens`` shape: ``[batch, n_cores, 9]``.
            ``allele_tokens`` shape: ``[batch, n_alleles, pseudoseq_len]``.
            """
            batch, n_cores, core_len = core_tokens.shape
            _, n_alleles, allele_len = allele_tokens.shape

            core_flat = core_tokens.reshape(batch * n_cores, core_len)
            allele_flat = allele_tokens.reshape(batch * n_alleles, allele_len)
            core_encoded = self.core_encoder(self.embedding(core_flat))
            allele_encoded = self.allele_encoder(self.embedding(allele_flat))

            core_pairs = core_encoded.reshape(batch, n_cores, core_len, -1)
            allele_pairs = allele_encoded.reshape(batch, n_alleles, allele_len, -1)
            core_pairs = (
                core_pairs[:, :, None, :, :]
                .expand(batch, n_cores, n_alleles, core_len, -1)
                .reshape(batch * n_cores * n_alleles, core_len, -1)
            )
            allele_pairs = (
                allele_pairs[:, None, :, :, :]
                .expand(batch, n_cores, n_alleles, allele_len, -1)
                .reshape(batch * n_cores * n_alleles, allele_len, -1)
            )

            attended, _ = self.cross_attention(core_pairs, allele_pairs, allele_pairs)
            core_pool = core_pairs.mean(dim=1)
            allele_pool = allele_pairs.mean(dim=1)
            attended_pool = attended.mean(dim=1)
            logits = self.scorer(
                torch.cat([core_pool, allele_pool, attended_pool], dim=-1)
            ).squeeze(-1)
            grid = logits.reshape(batch, n_cores, n_alleles).transpose(1, 2)
            if core_mask is None:
                core_mask = core_tokens.ne(PAD_INDEX).any(dim=-1)
            if allele_mask is None:
                allele_mask = allele_tokens.ne(PAD_INDEX).any(dim=-1)
            valid = allele_mask[:, :, None] & core_mask[:, None, :]
            masked_grid = grid.masked_fill(~valid, torch.finfo(grid.dtype).min)
            sample_logits = masked_grid.flatten(start_dim=1).max(dim=1).values
            return sample_logits, grid

else:

    class MHCIIInteractionModel:  # type: ignore[no-redef]
        def __init__(self, *args, **kwargs) -> None:
            raise MissingTorchError(
                "PyTorch is required for MHC-II model training/inference. "
                "Install backend/requirements-mhc2.txt in a research environment."
            )


    class MHCIIESMModel:  # type: ignore[no-redef]
        def __init__(self, *args, **kwargs) -> None:
            raise MissingTorchError(
                "PyTorch is required for MHC-II model training/inference. "
                "Install backend/requirements-mhc2.txt in a research environment."
            )
