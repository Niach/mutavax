# MHC-II open predictor — smoke run log (2026-04-25)

End-to-end verification of the scaffold introduced in commit `6b6d5e1`
(`codex/mhc2-research-handoff`) on a workstation with an RTX 4090. Goal was
to confirm the architecture trains and the predict/benchmark CLIs work
before committing to a full HLAIIPred-scale run.

## Environment

- Linux 6.14, Python 3.12.3
- `pip install -r backend/requirements-mhc2.txt` resolved to torch 2.11.0+cu130
- CUDA visible, device: `NVIDIA GeForce RTX 4090` (24 GB VRAM)
- `pytest backend/tests/test_mhc2_research.py` — 7/7 passed (5 original + 2 new)

## Data fetched

| Source | Size | Sha256 match handoff manifest |
|---|---|---|
| `hlaiipred_zenodo/train_positive.csv` | 196 MB | ✓ |
| `hlaiipred_zenodo/valid_positive.csv` | 16 MB | ✓ |
| `hlaiipred_zenodo/test_positive.csv` | 20 MB | ✓ |
| `netmhciipan_43/NetMHCIIpan_train.tar.gz` | 379 MB | ✓ |
| `netmhciipan_43/NetMHCIIpan_eval.fa` | 818 KB | ✓ |
| `ipd_imgt_hla/Allelelist.txt` (IPD-IMGT/HLA 3.64.0) | 919 KB | n/a |
| UniProt human reviewed proteome (UP000005640) | 14 MB | n/a (decoy source) |

HLAIIPred curated → JSONL exactly matched the handoff row counts:
1,388,552 / 113,478 / 163,669 (train/valid/test).

## Smoke training

- Subset: 1000 shuffled train rows, 200 shuffled valid rows
  (length distribution 8–26 aa, peak 13–18 aa — realistic for MHC-II)
- 967/1000 train and 191/200 valid records survived pseudosequence-coverage
  filtering. With the allele-normalization fixes below, **178/181 smoke
  alleles** now have pseudosequences (was 142/181 pre-fix).
- 2 epochs, batch size 16, decoys-per-positive 1
- Loss: 0.684 → 0.664 (decreasing, ~1 minute total wall time)

## End-to-end predict + benchmark

30 held-out positives (peptide + one of its real alleles) plus 30
length-matched human-proteome decoys, 9-mer-overlap-rejected.
Prediction emitted score, best core, and offset for every pair.

| Metric | Value |
|---|---|
| ROC-AUC | 0.637 |
| PR-AUC | 0.631 |
| F1 @ 0.5 | 0.49 |

These are barely above random (0.5) — expected for a 2-epoch run on 967
positives. The point was to verify the pipeline runs end-to-end, not
predictor quality at this scale.

## Bugs found and fixed in this commit

1. **`alleles.py` mis-normalized the DTU `DRB1_NNNN` form.**
   `normalize_mhc2_allele("DRB1_0101")` returned `HLA-DRB1*:0101` (empty
   field 1, garbled field 2). Same defect on `HLA-DPA10103-DPB10101`
   returning `HLA-DPA1*0103-DPB1*0101` (no `:` separator). After the fix,
   all DTU forms round-trip to canonical IPD form.

2. **3-digit HLA family codes were unrecoverable from concatenated
   names.** `HLA-DPA10103-DPB110401` could mean `DPB1*10:401` or
   `DPB1*104:01`. Resolved by adding `app.research.mhc2.ipd` which
   consults the official IPD-IMGT/HLA allele list and prefers whichever
   split is registered. Without the lookup the parser falls back to
   the more-common 2-digit-family default. New fetch source
   `ipd_imgt_hla` lazy-downloads `Allelelist.txt`.

3. **`load_pseudosequences` silently dropped 1,666 of 5,641 DTU
   pseudosequence entries** because the regex used the strict 20-AA
   peptide alphabet, rejecting entries containing `X` (the unknown/gap
   placeholder used in MHC-II pseudosequences). Switched to
   `MODEL_AMINO_ACIDS` for pseudoseq validation, peptides still use the
   strict alphabet.

After all three fixes: HLAIIPred full train allele coverage **184/188
(98%)**, up from 78% pre-fix. The four remaining misses
(`DPB1*416:01`, `DPA1*02:07-DPB1*04:01`, `DPA1*02:07-DPB1*19:01`, plus
one more) are real gaps in NetMHCIIpan-4.3's pseudosequence file, not
parser bugs.

## Other architecture caveats not addressed in this commit

- **Cross-attention scales O(n_cores × n_alleles) per sample.** A 22-aa
  peptide with a 14-allele HLAIIPred polyallelic sample expands to 308
  sequences in `cross_attention`. Smoke at batch=16 fit easily in 24 GB,
  but a memory-budget pass is warranted before launching multi-day full
  training.
- **No validation loss / per-locus metrics in the training loop.**
  Already flagged in the original handoff. The history JSON only logs
  train loss per epoch.
- **No percentile rank calibration.** `PercentileRanker` exists in
  `predict.py` but is never populated; predictions emit empty
  `percentile_rank`.

## Reproducer (off this branch + an RTX-class GPU)

```bash
git switch codex/mhc2-research-handoff
python3 -m venv .venv && . .venv/bin/activate
pip install -r backend/requirements-mhc2.txt

# data
python3 scripts/mhc2_fetch_data.py hlaiipred_zenodo --out data/mhc2
python3 scripts/mhc2_fetch_data.py netmhciipan_43   --out data/mhc2
python3 scripts/mhc2_fetch_data.py ipd_imgt_hla     --out data/mhc2
mkdir -p data/mhc2/netmhciipan_43/extracted
tar -xf data/mhc2/netmhciipan_43/NetMHCIIpan_train.tar.gz \
  -C data/mhc2/netmhciipan_43/extracted

# curate HLAIIPred
for split in train valid test; do
  python3 scripts/mhc2_prepare_dataset.py \
    data/mhc2/hlaiipred_zenodo/${split}_positive.csv \
    --out data/mhc2/curated/hlaiipred_${split}.jsonl
done

# proteome (decoys)
mkdir -p data/mhc2/proteome
curl -L "https://rest.uniprot.org/uniprotkb/stream?compressed=true&format=fasta&query=%28proteome%3AUP000005640%29%20AND%20%28reviewed%3Atrue%29" \
  -o data/mhc2/proteome/human_uniprot_sprot.fasta.gz
gunzip data/mhc2/proteome/human_uniprot_sprot.fasta.gz

# smoke train (pseudoseq file consumed directly, no pre-normalizer needed)
python3 scripts/mhc2_train.py \
  --train-jsonl     data/mhc2/curated/hlaiipred_train.smoke.jsonl \
  --valid-jsonl     data/mhc2/curated/hlaiipred_valid.smoke.jsonl \
  --pseudosequences data/mhc2/netmhciipan_43/extracted/pseudosequence.2023.dat \
  --proteome-fasta  data/mhc2/proteome/human_uniprot_sprot.fasta \
  --out             data/mhc2/checkpoints/smoke \
  --track smoke --epochs 2 --batch-size 16
```

## Recommendation

The data pipeline and training loop now run end-to-end on real DTU
pseudosequences with 98% HLAIIPred allele coverage. Before producing a
publishable `public_reproduce` checkpoint:

1. Add validation loss + per-locus metrics to the training loop.
2. Add percentile-rank calibration in `predict.py`.
3. Run a full HLAIIPred training pass (estimate ~2-3 h on the 4090 with
   the current architecture and 1× decoy ratio).
4. Compare against NetMHCIIpan-4.3 published numbers on `NetMHCIIpan_eval.fa`.

SOTA-level work (parsers for Racle/MixMHC2pred PRIDE, Strazar/CAPTAn,
HLA Ligand Atlas, Graph-pMHC; possibly architecture revisions like a
BA regression head and locus-aware encoders) is a separate plan, not a
single-session task.
