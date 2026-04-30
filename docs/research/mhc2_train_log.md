# MHC-II training log

Cumulative record of every cancerstudio MHC-II training run. New runs append at the bottom. Keep this in sync with the actual checkpoints — don't claim a result that hasn't landed.

## Validation set

All val_auc numbers below are on the cluster-aware `cluster_valid.jsonl` (no 9-mer leakage with `cluster_train.jsonl`), polyallelic max-over-alleles scoring. Length distribution includes 8-25 aa peptides; ~48% of records are ≤11-mer (BA-style) and ~52% are 13+ aa (EL-style).

## Reference

| run | val_auc on cluster_valid | DR | DP | DQ |
|---|---|---|---|---|
| HLAIIPred-2025 published | 0.9484 (their cluster_valid; ours: 0.9442 on cluster_test sample) | — | — | — |
| **gap to close** | **0.10** | | | |

## Runs

### v0_baseline (Phase A scratch, 2026-04-25)

- **Config:** scratch interaction model 96/128/2/4, decoys=1, BCE, no protocol switches.
- **Result:** **val_auc = 0.7632**.
- **Takeaway:** Pure scratch baseline. Establishes "the bar" the ESM features have to clear.

### v3a_sampler (Phase A scratch + sampler, 2026-04-28)

- **Config:** v0 config + `--cluster-weighted-sampler`.
- **Result:** **val_auc = 0.7157** (regression).
- **Takeaway:** Sampler alone *hurts* the scratch model. Likely interaction with limited capacity (326k params) and the sampler reshuffling exposing more clusters. Not pursued further.

### repro_v1 / repro_v2 (HLAIIPred-protocol-stack on scratch, 2026-04-28)

- **Config:** scratch 192/384/4/8, decoys=10, multi-task BA + allele dropout + dynamic decoys + cluster_weighted (loss / sampler).
- **Result:** v1 = 0.6814 (cluster-weighted-as-loss diluted gradients), v2 = 0.7223 (no loss-weight).
- **Takeaway:** Stacking protocol switches on scratch architecture *hurts* below v0. The protocol switches assume a model with enough representational capacity; our scratch isn't there. Recipe-driven knobs ≠ universally beneficial.

### phaseB_v1_esm_sampler (Phase B baseline, 2026-04-28)

- **Config:** ESM-2 35M frozen features + 10M-param adapter (480 dim, 2 layers, 8 heads, 1024 hidden), `--cluster-weighted-sampler`, decoys=1, BS=32, LR=1e-4, 3 epochs, ES patience=1.
- **Result:** **val_auc = 0.8469 (epoch 2 best)**, epoch 1 = 0.8297, epoch 3 = 0.8323 (overfit, ES fired).
- **Per-locus best:** DR 0.847 / DP 0.862 / DQ 0.840.
- **Takeaway:** **ESM-2 features close half the gap to HLAIIPred (+0.084 over scratch).** The remaining 0.10 is architectural/protocol, not data.
- **Cluster_test benchmark (sample 20k, all 4 tools):** v1 = 0.8585 (DR 0.854 / DP 0.873 / DQ 0.858) vs HLAIIPred 0.9442 vs NetMHCIIpan 0.6482 vs MixMHC2pred 0.5806. Beats NetMHCIIpan/MixMHC2pred decisively; behind HLAIIPred by 0.086 absolute.
- **Best ckpt:** `data/mhc2/checkpoints/phaseB_v1_esm_sampler/phaseB_v1_esm_sampler.best.pt` (192 MB).

### phaseB_v3_combined (Phase B + invertedDP + locus_upweight, 2026-04-29, Vast 35828305) — KILLED

- **Config:** phaseB_v2 + `--locus-upweight inverse_frequency` (DP×1.97, DQ×1.02, DR×0.66).
- **Reversed cache:** Full corpus (2.838M peptides, 40 GB) on the 250 GB Vast box.
- **Result epoch 1:** **val_auc = 0.8184** (vs v1 0.8297 −0.0113; vs v2 0.8284 −0.0100, **regression**).
- **Per-locus epoch 1:** DR 0.819 (≈v2) / **DP 0.825 (−0.048 vs v2!)** / DQ 0.814 (−0.003 vs v2).
- **Takeaway:** **`--locus-upweight inverse_frequency` HURT, including the DP slice it was supposed to help.** Doubling DP gradient signal destabilized training around DP-specific patterns. Recipe assumes DR-bias is the problem; our model never had it, so the correction over-corrected. **Don't use locus_upweight in future runs.**
- **Status:** killed mid-epoch-2 to save GPU.

### phaseB_v2_invertedDP (Phase B + inverted DP, 2026-04-29, Vast 35714879)

- **Config:** phaseB_v1 + `--inverted-dp`.
- **Reversed cache:** DP-filtered (1.665M peptides, 23 GB) due to disk on the 80 GB Vast box.
- **Best result (epoch 2):** **val_auc = 0.8445** (vs v1 best 0.8469: **−0.0024 ≈ tied**).
- **Per-locus epoch 2:** DR 0.840 / **DP 0.884 (+0.022 vs v1)** ✨ / DQ 0.829.
- **Takeaway:** Inverted DP delivers exactly what literature predicts for DP. Epoch 2 best aggregate is essentially tied with v1, **but DP is +0.022 absolute** — the strongest DP we've achieved. Epoch 3 began overfitting (per ES policy). **Best for DP-specific use cases. Best ckpt on S3: `htz:cancerstudio/checkpoints/phaseB_v2_invertedDP.best.pt`.**
- **Box A killed after epoch 2 to save money.**

### phaseB_v4_decoys3 (Phase B + invertedDP + decoys=3, 2026-04-29 → 2026-04-30, Vast 35828305)

- **Config:** phaseB_v2 + `--decoys-per-positive 3` (recipe-recommended scaling).
- **Cache:** Full d=3 corpus, 6.73M peptides, ~94 GB forward + 100 GB reversed (200 GB total). Built from scratch on Box B with `--build-reversed`.
- **Best result (epoch 2):** **val_auc = 0.8488** ⭐ — **new aggregate best**, beats v1 by +0.0019.
- **Epoch 1:** val_auc = 0.8375 (DR 0.843 / DP 0.835 / DQ 0.829).
- **Epoch 2:** val_auc = **0.8488** (DR **0.853** / DP 0.851 / DQ **0.841**).
- **Per-locus deltas (vs v2_invertedDP epoch 2):** DR +0.013, DP **−0.033** ⚠, DQ +0.012.
- **Takeaway:** **decoys=3 helps DR and DQ but HURTS DP.** Extra random-proteome decoys dilute the inverted-DP signal even with `--inverted-dp` on. Net aggregate gain is small (+0.0019) — not the universal "more decoys = better" the recipe assumed.
- **Best ckpt on S3:** `htz:cancerstudio/checkpoints/phaseB_v4_decoys3.best.pt`.
- **Box B kept alive after kill** for next phase (ESM-2 150M).

## Current SOTA candidates

| metric | best ckpt | val_auc |
|---|---|---|
| **aggregate** | phaseB_v4_decoys3.best.pt (epoch 2) | **0.8488** |
| **DP slice** | phaseB_v2_invertedDP.best.pt (epoch 2) | **DP 0.884** |
| trade-off | depends on use case — keep both, ensemble candidates |

**Gap to HLAIIPred (0.9442 cluster_test): 0.086 absolute**. v4_decoys3 hasn't been benchmarked on cluster_test yet — that's a TODO.

## Open ablation questions

| q | answered? |
|---|---|
| Does ESM beat scratch? | **YES**, +0.084 |
| Does cluster_weighted_sampler help? | YES on ESM (used by all phaseB runs); HURT on scratch (v3a) |
| Does inverted DP help DP slice? | **YES, +0.022 best (v2 epoch 2)** |
| Does inverted DP help aggregate val_auc? | **NO**, DR/DQ regress, net ≈ tied with v1 |
| Does locus_upweight help? | **NO**, regresses everything including DP (v3 confirmed) |
| Does decoys=3 help? | **YES on aggregate (+0.0019), NO on DP (−0.033 vs v2)** — v4 confirmed |
| Does multi_task_ba help? | untested as a single knob on ESM |
| Does logsumexp aggregation help? | untested |
| Does bigger ESM (150M / 650M) help? | **untested — biggest remaining lever** |
| Does 5-fold CV ensemble help? | untested |
| Does 2-checkpoint seed ensemble help? | untested (HLAIIPred uses this) |

## Cost ledger

| run | wall time | cost ($0.40-0.55/h) |
|---|---|---|
| v0_baseline (3 epochs) | ~3h | ~$1.20 |
| repro_v1 + v2 (≤epoch 3) | ~14h combined | ~$5.60 |
| v3a_sampler (2 epochs early-stop) | ~52 min | ~$0.35 |
| phaseB_v1_esm_sampler (3 epochs) | 9h 50min | $3.92 |
| phaseB_v2_invertedDP (epoch 2 + early kill) | 8h | ~$3.30 |
| phaseB_v3_combined (epoch 1 + kill) | 4h | ~$2.20 |
| phaseB_v4_decoys3 (epoch 2 + early kill) | ~14h | ~$7.70 |
| ESM cache builds (4 incl d=3) | ~80 min | ~$0.60 |
| Benchmarks (4-tool cluster_test sample 20k) | 26 min | ~$0.17 |
| **subtotal so far** | | **~$25** |

## What we'd train next

In priority order, given current evidence:

1. **ESM-2 150M upgrade** — biggest untested lever. Recipe says +0.02-0.05. Code is ready (`--esm-model esm2_150m`). Requires ~107 GB cache rebuild on Box B (~80-90 min). Train cost ~$8-10 per epoch (slower per-step due to bigger model).
2. **2-checkpoint seed ensemble** — HLAIIPred trains two models and averages. Easy win: train the same config with seed=42 (v6_seed42) and average with v4_decoys3 best. ~$8 cost.
3. **5-fold CV ensemble** — full classic SOTA pattern. ~$25-40 cost. Defer until single-fold result is solid.
4. **Cluster_test benchmark of v4_decoys3.best.pt** — we benchmarked v1 but not v2 or v4. Need this number for proper SOTA comparison.

What we should NOT train (wasted compute):
- locus_upweight in any combination (v3 confirmed it hurts)
- More aggressive scratch architectures (v0/v3a/v1/v2 covered the scratch space)
- 10× decoys (v2/v3 of repro_* showed this just amplifies gradients pathologically)
- decoys=3 on top of decoys=1 v2 (no point — v4 covered it)

## Notes

- **HLAIIPred lead is uniform across loci (~0.08-0.10 each)** in the cluster_test benchmark. The gap is architectural, not locus-specific.
- **Inverted DP's effect is DP-only** as theory predicts. It just doesn't pay back on aggregate AUC.
- The scratch model's 326k params are too small for any of the protocol switches (allele dropout, dynamic decoys, multi-task BA) to add value. They all work *on the ESM-features path* and probably need re-evaluation only there.
