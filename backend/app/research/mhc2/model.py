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

    _LENGTH_FEATURE_SCALE = 20.0

    def _length_features(
        core_mask: Tensor, n_cores: int, n_alleles: int
    ) -> Tensor:
        """Per-(sample, core, allele) length signals built from ``core_mask``.

        Returns ``[batch * n_cores * n_alleles, 3]`` matching the order
        ``fused`` is laid out in (sample-major, core-major, allele-minor).
        Channels: peptide n_cores, N-term offset, C-term distance — all
        divided by ~typical max length so values stay roughly in [0, 1.5].
        Padded core slots get arbitrary values (the scorer's output is masked
        before the max-over-cores step).
        """
        batch = core_mask.shape[0]
        n_cores_per_sample = core_mask.sum(dim=1).float()  # [batch]
        core_idx = torch.arange(
            n_cores, dtype=torch.float32, device=core_mask.device
        )
        core_idx_b = core_idx.unsqueeze(0).expand(batch, n_cores)
        n_cores_b = n_cores_per_sample.unsqueeze(1).expand(batch, n_cores)
        length_feat = n_cores_b / _LENGTH_FEATURE_SCALE
        n_term_feat = core_idx_b / _LENGTH_FEATURE_SCALE
        c_term_feat = (n_cores_b - 1.0 - core_idx_b).clamp(min=0.0) / _LENGTH_FEATURE_SCALE
        feat = torch.stack([length_feat, n_term_feat, c_term_feat], dim=-1)  # [batch, n_cores, 3]
        return (
            feat.unsqueeze(2)
            .expand(batch, n_cores, n_alleles, 3)
            .reshape(-1, 3)
        )


    class MHCIIESMModel(nn.Module):
        """Phase B model: frozen ESM-2 features + small adapter on each branch.

        Inputs are ``[batch, n_cores, 9, esm_dim]`` and ``[batch, n_alleles,
        pseudoseq_len, esm_dim]`` — pre-computed feature tensors, not token
        IDs. The adapter learns to specialize ESM's general PLM features to
        the binding-prediction task while keeping ESM frozen.

        When ``with_ba_head=True`` the model also produces a
        binding-affinity regression head over the same shared encoder so
        the trainer can run a multi-task EL + BA loss.
        """

        def __init__(
            self,
            esm_dim: int = 480,
            adapter_layers: int = 2,
            adapter_heads: int = 8,
            adapter_hidden: int = 1024,
            max_pseudoseq_length: int = 64,
            dropout: float = 0.1,
            with_ba_head: bool = False,
            allele_aggregation: str = "max",
            use_length_features: bool = False,
            use_chain_boundary: bool = False,
            alpha_chain_length: int = 15,
        ) -> None:
            super().__init__()
            self.esm_dim = esm_dim
            self.max_pseudoseq_length = max_pseudoseq_length
            self.with_ba_head = with_ba_head
            if allele_aggregation not in {"max", "logsumexp"}:
                raise ValueError(
                    f"allele_aggregation must be 'max' or 'logsumexp', got {allele_aggregation!r}"
                )
            self.allele_aggregation = allele_aggregation
            self.use_length_features = use_length_features
            self.use_chain_boundary = use_chain_boundary
            self.alpha_chain_length = alpha_chain_length
            if use_chain_boundary:
                # NetMHCIIpan-4.3 convention: 34-aa pseudoseq is α-chain
                # contact residues followed by β-chain contact residues.
                # DR alleles share the first 15 (DRA is conserved); DP/DQ
                # heterodimers vary across both halves. We mark the boundary
                # with a learned segment embedding added to per-residue
                # allele features before the adapter.
                self.chain_segment_emb = nn.Embedding(2, esm_dim)
                seg_ids = torch.zeros(max_pseudoseq_length, dtype=torch.long)
                seg_ids[alpha_chain_length:] = 1
                self.register_buffer("_segment_ids", seg_ids, persistent=False)
            scorer_in = esm_dim * 3 + (3 if use_length_features else 0)
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
                nn.Linear(scorer_in, adapter_hidden),
                nn.GELU(),
                nn.Dropout(dropout),
                nn.Linear(adapter_hidden, 1),
            )
            if with_ba_head:
                # BA head shares the same fused (core, allele, attended)
                # representation but predicts a single scalar
                # log-affinity for each (peptide, allele) pair. We pool
                # over candidate cores at the end so it's directly
                # comparable to the IEDB log-affinity targets.
                self.ba_scorer = nn.Sequential(
                    nn.Linear(scorer_in, adapter_hidden),
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

            if self.use_chain_boundary:
                seg_emb = self.chain_segment_emb(self._segment_ids[:allele_len])
                allele_feats = allele_feats + seg_emb[None, None, :, :]

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
            fused = torch.cat([core_pool, allele_pool, attended_pool], dim=-1)

            if core_mask is None:
                core_mask = core_feats.abs().sum(dim=-1).ne(0).any(dim=-1)
            if allele_mask is None:
                allele_mask = allele_feats.abs().sum(dim=-1).ne(0).any(dim=-1)

            if self.use_length_features:
                fused = torch.cat(
                    [fused, _length_features(core_mask, n_cores, n_alleles)],
                    dim=-1,
                )

            logits = self.scorer(fused).squeeze(-1)
            grid = logits.reshape(batch, n_cores, n_alleles).transpose(1, 2)
            valid = allele_mask[:, :, None] & core_mask[:, None, :]
            masked_grid = grid.masked_fill(~valid, torch.finfo(grid.dtype).min)
            # Step 1: max over candidate cores within each allele -> per-allele
            # logit. Picking the best register is what the literature does and
            # works well for both aggregation modes below.
            per_allele_logits = masked_grid.max(dim=2).values  # [batch, n_alleles]
            if self.allele_aggregation == "logsumexp":
                # Soft "any-of-these-alleles can present" aggregation. Mask
                # out absent alleles so they don't contribute mass to the LSE.
                per_allele_logits = per_allele_logits.masked_fill(
                    ~allele_mask, torch.finfo(per_allele_logits.dtype).min
                )
                sample_logits = torch.logsumexp(per_allele_logits, dim=1)
            else:
                sample_logits = per_allele_logits.masked_fill(
                    ~allele_mask, torch.finfo(per_allele_logits.dtype).min
                ).max(dim=1).values

            if self.with_ba_head:
                # Per-(core, allele) BA prediction, then max over cores
                # within each allele, then max OVER ALLELES for the
                # sample-level BA prediction (max here is appropriate
                # even under LSE aggregation: BA records are mono-allelic).
                ba_logits = self.ba_scorer(fused).squeeze(-1)
                ba_grid = ba_logits.reshape(batch, n_cores, n_alleles).transpose(1, 2)
                ba_masked = ba_grid.masked_fill(~valid, torch.finfo(ba_grid.dtype).min)
                ba_per_allele = ba_masked.max(dim=2).values
                ba_sample_logits = ba_per_allele.masked_fill(
                    ~allele_mask, torch.finfo(ba_per_allele.dtype).min
                ).max(dim=1).values
                return sample_logits, grid, ba_sample_logits
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
            with_ba_head: bool = False,
            allele_aggregation: str = "max",
            use_length_features: bool = False,
            use_chain_boundary: bool = False,
            alpha_chain_length: int = 15,
        ) -> None:
            super().__init__()
            self.max_pseudoseq_length = max_pseudoseq_length
            self.with_ba_head = with_ba_head
            if allele_aggregation not in {"max", "logsumexp"}:
                raise ValueError(
                    f"allele_aggregation must be 'max' or 'logsumexp', got {allele_aggregation!r}"
                )
            self.allele_aggregation = allele_aggregation
            self.use_length_features = use_length_features
            self.use_chain_boundary = use_chain_boundary
            self.alpha_chain_length = alpha_chain_length
            if use_chain_boundary:
                self.chain_segment_emb = nn.Embedding(2, embedding_dim)
                seg_ids = torch.zeros(max_pseudoseq_length, dtype=torch.long)
                seg_ids[alpha_chain_length:] = 1
                self.register_buffer("_segment_ids", seg_ids, persistent=False)
            scorer_in = embedding_dim * 3 + (3 if use_length_features else 0)
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
                nn.Linear(scorer_in, hidden_dim),
                nn.GELU(),
                nn.Dropout(dropout),
                nn.Linear(hidden_dim, 1),
            )
            if with_ba_head:
                self.ba_scorer = nn.Sequential(
                    nn.Linear(scorer_in, hidden_dim),
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
            allele_emb = self.embedding(allele_flat)
            if self.use_chain_boundary:
                seg_emb = self.chain_segment_emb(self._segment_ids[:allele_len])
                allele_emb = allele_emb + seg_emb[None, :, :]
            allele_encoded = self.allele_encoder(allele_emb)

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
            fused = torch.cat([core_pool, allele_pool, attended_pool], dim=-1)
            if core_mask is None:
                core_mask = core_tokens.ne(PAD_INDEX).any(dim=-1)
            if allele_mask is None:
                allele_mask = allele_tokens.ne(PAD_INDEX).any(dim=-1)
            if self.use_length_features:
                fused = torch.cat(
                    [fused, _length_features(core_mask, n_cores, n_alleles)],
                    dim=-1,
                )
            logits = self.scorer(fused).squeeze(-1)
            grid = logits.reshape(batch, n_cores, n_alleles).transpose(1, 2)
            valid = allele_mask[:, :, None] & core_mask[:, None, :]
            masked_grid = grid.masked_fill(~valid, torch.finfo(grid.dtype).min)
            per_allele_logits = masked_grid.max(dim=2).values  # [batch, n_alleles]
            if self.allele_aggregation == "logsumexp":
                per_allele_logits = per_allele_logits.masked_fill(
                    ~allele_mask, torch.finfo(per_allele_logits.dtype).min
                )
                sample_logits = torch.logsumexp(per_allele_logits, dim=1)
            else:
                sample_logits = per_allele_logits.masked_fill(
                    ~allele_mask, torch.finfo(per_allele_logits.dtype).min
                ).max(dim=1).values

            if self.with_ba_head:
                ba_logits = self.ba_scorer(fused).squeeze(-1)
                ba_grid = ba_logits.reshape(batch, n_cores, n_alleles).transpose(1, 2)
                ba_masked = ba_grid.masked_fill(~valid, torch.finfo(ba_grid.dtype).min)
                ba_per_allele = ba_masked.max(dim=2).values
                ba_sample_logits = ba_per_allele.masked_fill(
                    ~allele_mask, torch.finfo(ba_per_allele.dtype).min
                ).max(dim=1).values
                return sample_logits, grid, ba_sample_logits
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
