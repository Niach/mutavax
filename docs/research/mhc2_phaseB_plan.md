# MHC-II Phase B — ESM-2 embeddings (target: 0.85+)

Phase A landed at val_auc ~0.76 (epoch 2; epoch 3 in flight). The trajectory
is asymptoting around 0.78-0.80 — meaningfully ahead of v0 (0.7209) and the
local Phase A run (0.7259), but well short of SOTA (0.94+). Phase B closes
the architectural gap: replace the from-scratch amino-acid embedding +
small transformer with **frozen ESM-2 protein-language-model features +
a thin adapter on top**.

This is the single biggest lever in the modern MHC-II literature.
NetMHCIIpan-4.3, MixMHC2pred-2.0, and HLAIIPred all use PLM features.

## What Phase A taught us (lessons baked into B)

- **Architecture ceiling.** A 2.75M-param from-scratch transformer
  saturates around 0.76-0.80 on this corpus. The model isn't underfit;
  it's hitting a representation ceiling.
- **Larger batch + bf16 was a real gain, not just speed.** Phase A jumped
  from 0.705 (batch 32) → 0.749 epoch 1 (batch 128) — keep batch 128 as
  the default.
- **DataLoader pickling is mandatory.** Module-level `_RecordDataset` and
  `_Collator` are now in place (commit `ad0211f`). Phase B can re-use.
- **Cloud config is known-good.** Spain RTX 5090 (7.4 Gbit/s host) at
  ~$0.40/h, ~3.87h/epoch with batch 128 + num_workers 8 + bf16. Replicate.
- **Cloud setup overhead is ~10 min/run** (Docker pull + clone + pip +
  fetch + curate). Acceptable for spin-up-per-run.

## Architecture change

### Current (Phase A)

```
peptide  -> embed(20+pad, 96d) -> 4-layer transformer (192d) -\
allele   -> embed(20+pad, 96d) -> 4-layer transformer (192d) -+- cross-attn -> MIL max
```

### Phase B target

```
peptide cores (9-mer)         -> ESM-2 35M (frozen) -> 480d per-residue -\
allele pseudoseqs (~36 aa)    -> ESM-2 35M (frozen) -> 480d per-residue -+- adapter -> cross-attn -> MIL max
```

- **ESM-2 model:** `esm2_t12_35M_UR50D` (35M params, 480-dim output).
  Smallest in the family; runs at >2000 seq/s on a 5090; fits comfortably.
- **Adapter:** 2 transformer encoder layers on each branch operating on
  the ESM features, dim_feedforward=1024. ~3M trainable params.
- **Cross-attention + MIL max:** unchanged from Phase A.

### Why the smallest ESM-2?

- 35M is sufficient: pseudoseqs are 36 residues, peptides are 9 residues —
  short sequences don't benefit much from larger PLMs.
- Per HLAIIPred and Graph-pMHC ablations: 150M only adds ~0.005-0.01 AUC
  over 35M for peptide-binding tasks.
- 35M vs 150M: 4× faster inference, 4× smaller cache.

## Concrete code plan

### 1. Add `backend/app/research/mhc2/esm.py`

Wraps fair-esm (or HuggingFace `facebook/esm2_t12_35M_UR50D`). Public API:

```python
def load_esm2_35m(device="cuda") -> tuple[Module, Tokenizer, int]:
    """Returns (model, tokenizer, embedding_dim=480). Model in eval() with
    requires_grad=False."""

def embed_sequences(model, tokenizer, sequences: list[str], device,
                    batch_size=64) -> dict[str, Tensor]:
    """Embeds in batches. Returns {seq: tensor(L, 480)}. Pads to max length
    in batch, but stores variable-length tensors."""

def cache_embeddings_to_disk(records: Iterable[MHC2Record],
                             pseudosequences: dict[str, str],
                             cache_dir: Path,
                             *, device="cuda") -> None:
    """One-time: enumerate unique 9-mer cores + pseudoseqs, embed,
    save as .pt lookup files (peptide_cores.pt, pseudoseqs.pt)."""

def load_embedding_cache(cache_dir: Path) -> tuple[dict, dict]:
    """Returns (cores_lookup, pseudoseq_lookup): seq -> Tensor(L, 480)."""
```

### 2. Update `backend/app/research/mhc2/model.py`

Add `MHCIIESMModel` (parallel to `MHCIIInteractionModel`), constructor:

```python
MHCIIESMModel(
    esm_dim: int = 480,
    adapter_layers: int = 2,
    adapter_heads: int = 8,
    adapter_hidden: int = 1024,
    dropout: float = 0.1,
    max_pseudoseq_length: int = 64,
)
```

- Takes pre-encoded core/allele features as input (not token IDs)
- Same forward signature: `forward(core_feats, allele_feats, core_mask,
  allele_mask)` returning `(sample_logits, grid)`

### 3. Update training pipeline

- `train.py`: add `model_kind: str = "scratch" | "esm2_35m"` to TrainConfig
- New `_ESMCollator` (parallel to `_Collator`) that looks up cached
  features instead of tokens
- DataLoader yields `(core_feats[B, n_cores, 9, 480], allele_feats[B,
  n_alleles, 64, 480], masks, labels)` — bigger but the only path that's
  GPU-friendly
- Pre-cache step runs ONCE at startup before training begins; takes
  ~10 min on a 5090 (35M model on 1M unique cores + 188 pseudoseqs)

### 4. Update CLI

Add to `scripts/mhc2_train.py`:

```
--model-kind {scratch,esm2_35m}    default: scratch
--esm-cache-dir PATH                default: data/mhc2/esm_cache/
--build-esm-cache                   trigger one-time precompute
```

### 5. Update onstart script

Add ESM cache build before training. The cache itself is reproducible
(deterministic given input), so a single build per cloud run is fine.

## Memory + cost estimate

- **ESM features cache:** ~1M unique 9-mer cores × 9 res × 480 d × 4 B =
  17.3 GB on disk. Allele cache: 188 × 64 × 480 × 4 = 23 MB. Total ~17 GB.
- **VRAM during training:** input tensors are bigger (480d vs 96d), so
  effective memory per batch grows ~5×. Drop batch size to 64 or 96 to be
  safe; expect ~1000 ex/s on the 5090 (50% slower than Phase A but with
  much higher quality features).
- **Per-epoch time:** ~5h (vs 3.87h in Phase A — slower per step, same
  total examples).
- **Cloud time for full Phase B:** 6 epochs × 5h = ~30h × $0.40 = **~$12**.

## Risks + mitigations

1. **ESM cache size on the rented box.** Need a host with >50 GB free
   disk. Spain offer used had 526 GB — fine.
2. **Sequence-length mismatch.** ESM tokenizes with BOS/EOS; need to
   strip them when extracting per-residue features for downstream MIL.
3. **fair-esm install size.** ~1 GB download. Bake into onstart with
   pre-built wheel index.
4. **Out-of-vocabulary tokens.** Pseudosequences contain `X` (gap). ESM-2
   has `<unk>` token; need to remap. Test on a few real pseudoseqs early.
5. **Closure-pickling regression.** New `_ESMCollator` must again be
   module-level. Add a unit test that pickle-roundtrips it before any
   cloud run.

## Acceptance criteria

- val_auc ≥ 0.85 on HLAIIPred valid split — gates declaring Phase B done.
- Per-locus AUC ≥ 0.83 on DR/DP, ≥ 0.80 on DQ.
- Held-out test AUC stays within 0.02 of val (no overfitting blowout).

## What comes after B

- **Phase C** — BA regression head (multi-task) + Racle/HLA-Ligand-Atlas
  data. Expected +0.02-0.04 → ~0.88.
- **Phase D** — Per-allele percentile rank, FRANK metric, cross-tool
  benchmark. No AUC gain; needed for publishability.
- **Phase E** — HLAIIPred-style soft-EM deconvolution loss + cluster-aware
  splits + tail re-weighting. Expected +0.02 → ~0.90+.

## Time + budget summary

| Step | Engineering | GPU time | Cumulative cost |
|---|---|---|---|
| esm.py + cache build | 1 evening | ~30 min | $1 |
| Model + collator wiring | 1 evening | smoke | <$1 |
| Full Phase B run | — | ~30h | ~$12 |
| **Total** | **2-3 evenings** | **~32h** | **~$15** |
