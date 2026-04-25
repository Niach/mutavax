# Handoff Prompt: cancerstudio Open MHC-II Predictor On A Bigger Machine

Paste this prompt into the next agent/session on a machine with enough disk and
GPU capacity.

## Prompt

You are taking over cancerstudio's open MHC class II predictor research track.
The goal is to train and benchmark our own public MHC-II presentation predictor,
not merely wrap NetMHCIIpan or MixMHC2pred. The desired outcome is a credible
open research model that can be compared honestly against NetMHCIIpan-4.3/4.3j,
MixMHC2pred-2.0, HLAIIPred, Graph-pMHC, and MHCnuggets where users have the
right to install those tools.

Current repo branch: `codex/mhc2-research-handoff`.

Repository root: `cancerstudio`.

Important context:

- The production cancerstudio neoantigen stage still uses the existing
  pVACseq/NetMHCpan/NetMHCIIpan path. Do not break that path.
- The new implementation lives under `backend/app/research/mhc2` and is a
  research-only scaffold for data curation, training, prediction, and benchmark
  evaluation.
- Large datasets are ignored under `data/`; they are not committed. Re-fetch
  or transfer them explicitly on the big machine.
- We are pursuing the "research-free" track: public research datasets are
  acceptable even when they are not clean for commercial redistribution. Keep
  provenance explicit and do not overclaim license cleanliness for weights.
- Human HLA-II is v1 scope. Dog/cat DLA/FLA class II remains unsupported until
  enough species-specific peptide-ligand evidence exists.

What is already implemented:

- `backend/app/research/mhc2/alleles.py`
  - Normalizes common HLA-II DR/DP/DQ chain and dimer strings.
  - DR normalizes to beta-chain form, e.g. `HLA-DRB1*15:01`.
  - DP/DQ normalize to alpha-beta dimers, e.g.
    `HLA-DQA1*03:01-DQB1*04:01`.

- `backend/app/research/mhc2/data.py`
  - Defines `MHC2Record`.
  - Parses HLAIIPred Zenodo positive CSV files.
  - Parses simple generic CSV/TSV files with peptide and allele columns.
  - Filters peptides to canonical amino acids and 8-30 aa length.
  - Loads pseudosequence files.
  - Reads/writes JSONL.

- `backend/app/research/mhc2/splits.py`
  - Assigns leakage-aware splits by connected components of shared 9-mers.
  - Reports 9-mer overlap leakage between reference and query sets.

- `backend/app/research/mhc2/decoys.py`
  - Generates length-matched human-proteome decoys.
  - Rejects decoys with 9-mer overlap against positives.

- `backend/app/research/mhc2/metrics.py`
  - Implements ROC-AUC, average precision, F1, Spearman, top-k recall, FRANK,
    and motif KL helpers without requiring sklearn.

- `backend/app/research/mhc2/model.py`
  - Optional PyTorch model.
  - Peptide is represented through candidate 9-mer cores.
  - Allele/pseudosequence is encoded separately.
  - Uses transformer encoders and cross-attention.
  - Multiple-instance supervision takes the max over valid allele/core scores.
  - Inference can return score, best core, core offset, and allele.

- `backend/app/research/mhc2/train.py`
  - Optional PyTorch training loop.
  - Trains from JSONL positives plus optional proteome decoys.
  - Saves checkpoint and training history.

- `backend/app/research/mhc2/predict.py`
  - Loads checkpoint and pseudosequences.
  - Predicts presentation scores for peptide/allele pairs.

- `backend/app/research/mhc2/benchmark.py`
  - Evaluates CSV/TSV prediction files with `label` or `target` and `score`
    or `prediction` columns.

- CLI scripts:
  - `scripts/mhc2_fetch_data.py`
  - `scripts/mhc2_prepare_dataset.py`
  - `scripts/mhc2_summarize_dataset.py`
  - `scripts/mhc2_train.py`
  - `scripts/mhc2_predict.py`
  - `scripts/mhc2_benchmark.py`

- Docs:
  - `docs/research/mhc2.md`
  - `docs/research/mhc2_model_card.md`
  - this handoff file

- Optional research dependency file:
  - `backend/requirements-mhc2.txt`
  - It adds `torch>=2.3` on top of the normal backend requirements.

Local smoke data fetched on the small machine:

- `data/mhc2` grew to about 1.1 GB.
- The small machine had only about 12 GiB free, so we intentionally stopped
  before pulling raw PRIDE, Graph-pMHC, SysteMHC, or other heavy sources.
- `data/` is ignored by git; none of these files are committed.

Fetched HLAIIPred Zenodo files:

- Source: `https://zenodo.org/records/15299217`
- `train_positive.csv`
  - size: `205172643`
  - sha256: `ee52c262cd236b227c7c4adc6476309b73e0d73c27b080bf14973a7783221f0e`
  - URL: `https://zenodo.org/api/records/15299217/files/train_positive.csv/content`
- `valid_positive.csv`
  - size: `16299310`
  - sha256: `d1fb245d1882164c05d3bf8136f25455e25a943fb4bc11c2bd531cda85f10861`
  - URL: `https://zenodo.org/api/records/15299217/files/valid_positive.csv/content`
- `test_positive.csv`
  - size: `21292620`
  - sha256: `e2d3ee8a879b4ab300dddd31425df3386cdb1c3c49202344dee5c872080a13f6`
  - URL: `https://zenodo.org/api/records/15299217/files/test_positive.csv/content`

Fetched NetMHCIIpan-4.3 files:

- Source: `https://services.healthtech.dtu.dk/services/NetMHCIIpan-4.3/`
- `NetMHCIIpan_train.tar.gz`
  - size: `396748800`
  - sha256: `bde8e21addba99ed8a2202f5c6aff40d653cddc425aa728fb5b9378c3aaa2261`
  - URL: `https://services.healthtech.dtu.dk/suppl/immunology/NetMHCIIpan-4.3/NetMHCIIpan_train.tar.gz`
- `NetMHCIIpan_eval.fa`
  - size: `836685`
  - sha256: `3cf66db746827d821f22e2cb6528dc4472d966e4ce9eee90bcd3351c6aae9f68`
  - URL: `https://services.healthtech.dtu.dk/suppl/immunology/NetMHCIIpan-4.3/NetMHCIIpan_eval.fa`

HLAIIPred summary after canonical amino-acid filtering:

- Total rows: `1,665,699`
- Train rows: `1,388,552`
- Valid rows: `113,478`
- Test rows: `163,669`
- Unique peptide strings: `704,710`
- Normalized allele/dimer labels: `188`
- The parser encountered at least one non-canonical peptide, e.g.
  `IRVTYCGLUS`; the current policy is to skip non-canonical residues for v1.

Important storage guidance:

- Current laptop is only suitable for smoke/prototype work.
- Curated-only SOTA work should have at least `25-40 GB` free.
- Fully reproducible SOTA from raw sources should have `100-200 GB` minimum.
- A comfortable research machine should have `500 GB+` free, because raw PRIDE
  and extracted intermediates can balloon quickly.

Start by setting up the bigger machine:

```bash
git clone https://github.com/Niach/cancerstudio.git
cd cancerstudio
git fetch origin
git switch codex/mhc2-research-handoff

python3 -m venv .venv
. .venv/bin/activate
pip install -r backend/requirements-mhc2.txt
npm install
```

Run the fast verification:

```bash
npm run test:backend:fast
npm run mhc2:data:list
```

Re-fetch the direct small/core data:

```bash
python3 scripts/mhc2_fetch_data.py hlaiipred_zenodo --out data/mhc2
python3 scripts/mhc2_fetch_data.py netmhciipan_43 --out data/mhc2
```

Curate HLAIIPred:

```bash
python3 scripts/mhc2_prepare_dataset.py \
  data/mhc2/hlaiipred_zenodo/train_positive.csv \
  --out data/mhc2/curated/hlaiipred_train.jsonl

python3 scripts/mhc2_prepare_dataset.py \
  data/mhc2/hlaiipred_zenodo/valid_positive.csv \
  --out data/mhc2/curated/hlaiipred_valid.jsonl

python3 scripts/mhc2_prepare_dataset.py \
  data/mhc2/hlaiipred_zenodo/test_positive.csv \
  --out data/mhc2/curated/hlaiipred_test.jsonl

python3 scripts/mhc2_summarize_dataset.py \
  data/mhc2/hlaiipred_zenodo/train_positive.csv \
  data/mhc2/hlaiipred_zenodo/valid_positive.csv \
  data/mhc2/hlaiipred_zenodo/test_positive.csv
```

Next technical tasks:

1. Inspect `NetMHCIIpan_train.tar.gz` without polluting the repo:

   ```bash
   mkdir -p data/mhc2/netmhciipan_43/extracted
   tar -tzf data/mhc2/netmhciipan_43/NetMHCIIpan_train.tar.gz | sed -n '1,120p'
   tar -xzf data/mhc2/netmhciipan_43/NetMHCIIpan_train.tar.gz \
     -C data/mhc2/netmhciipan_43/extracted
   find data/mhc2/netmhciipan_43/extracted -maxdepth 3 -type f | sort | sed -n '1,200p'
   ```

2. Locate and normalize the NetMHCIIpan pseudosequence file. The current
   training script expects a whitespace/CSV file mapping allele/dimer names to
   amino-acid pseudosequences:

   ```bash
   python3 scripts/mhc2_train.py \
     --train-jsonl data/mhc2/curated/hlaiipred_train.jsonl \
     --valid-jsonl data/mhc2/curated/hlaiipred_valid.jsonl \
     --pseudosequences path/to/pseudosequences.txt \
     --proteome-fasta path/to/human_proteome.fa \
     --out data/mhc2/checkpoints \
     --track public_reproduce \
     --epochs 1 \
     --batch-size 16
   ```

3. Do a tiny overfit/smoke run before any full training:

   - Create a tiny JSONL subset of a few hundred records.
   - Train for 1-2 epochs.
   - Confirm loss decreases.
   - Run `scripts/mhc2_predict.py` on a few known positive pairs.
   - Run `scripts/mhc2_benchmark.py` on a small labeled prediction file.

4. Add data-specific parsers for the rest of the research_sota corpus:

   - Racle/MixMHC2pred 2023, including PRIDE `PXD034773`.
   - Strazar/CAPTAn monoallelic HLA-II corpus.
   - HLA Ligand Atlas class-II TSV downloads.
   - Graph-pMHC Zenodo dataset for benchmark/ablation only.
   - SysteMHC v2 only as optional weak labels; do not use it as an independent
     benchmark because some labels are predictor-derived.

5. Strengthen the model/training before claiming performance:

   - Add validation metrics inside the training loop.
   - Save model card fields into checkpoint metadata.
   - Add percentile rank calibration from background human proteome peptides.
   - Add per-locus DR/DQ/DP metrics.
   - Add rare-allele metrics.
   - Add leakage reports for every train/valid/test boundary.
   - Add benchmark adapters for external tool outputs.

6. Benchmark honestly:

   - HLAIIPred held-out split: ROC-AUC, PR-AUC, F1.
   - NetMHCIIpan publication eval FASTA / FRANK where applicable.
   - Racle motif/core recovery and DP reverse-binding checks.
   - Per-locus DR/DQ/DP breakdown.
   - Rare-allele breakdown.
   - Compare against NetMHCIIpan-4.3/4.3j, MixMHC2pred-2.0, HLAIIPred,
     Graph-pMHC, and MHCnuggets only where installed legally.

7. Keep the production app safe:

   - Do not wire this into `backend/app/services/neoantigen.py` until there is
     a trained checkpoint, calibrated ranks, benchmark results, and a clear UI
     label that it is an in-house research predictor.
   - Do not present MHC-II presentation as immunogenicity.
   - Preserve all existing `npm run test:backend:fast` tests.

Key commands available from `package.json`:

```bash
npm run mhc2:data:list
npm run mhc2:data:fetch -- hlaiipred_zenodo --out data/mhc2
npm run mhc2:prepare -- data/mhc2/hlaiipred_zenodo/train_positive.csv --out data/mhc2/curated/hlaiipred_train.jsonl
npm run mhc2:summarize -- data/mhc2/hlaiipred_zenodo/train_positive.csv
npm run mhc2:train -- --train-jsonl ... --pseudosequences ... --out ...
npm run mhc2:predict -- --checkpoint ... --pseudosequences ... --input ... --out ...
npm run mhc2:benchmark -- predictions.csv --out metrics.json
```

Known caveats in the current scaffold:

- `scripts/mhc2_prepare_dataset.py` streams only when not doing cluster split;
  cluster split still loads records into memory because it builds connected
  components over 9-mer overlap. For multi-million record merged corpora, this
  may need a more scalable implementation.
- The model is a first implementation, not a proven architecture. Validate on
  tiny subsets before running a full job.
- The training loop currently focuses on binary presentation with sampled
  decoys. BA regression / mixed BA+EL objectives still need implementation.
- Pseudosequence extraction from the DTU tarball has not been completed in this
  handoff session.
- No weights have been trained yet.
- No large raw PRIDE/Graph/SysteMHC data has been fetched on the laptop.

Definition of done for the next phase:

- A reproducible `public_reproduce` checkpoint trained from HLAIIPred-scale data.
- A metrics JSON/table for held-out HLAIIPred test data.
- A tiny prediction example that returns score/core/offset for peptide/allele.
- A documented manifest showing data checksums, row counts, unique peptides,
  unique alleles, split counts, and leakage report.
- A clear recommendation about whether the current architecture is good enough
  to scale to the `research_sota` corpus or needs architectural revision first.

