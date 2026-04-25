# Open MHC-II Predictor Research Track

This directory documents cancerstudio's in-house MHC class II predictor work.
The production neoantigen stage still uses the existing pVACseq path; the code
under `backend/app/research/mhc2` is a research sandbox for training our own
public model and benchmarking it against NetMHCIIpan-4.3/4.3j, MixMHC2pred-2.0,
HLAIIPred, Graph-pMHC, and MHCnuggets where licenses allow.

## Data Workflow

List known data sources:

```bash
python3 scripts/mhc2_fetch_data.py --list
```

Fetch direct-download sources with provenance:

```bash
python3 scripts/mhc2_fetch_data.py hlaiipred_zenodo --out data/mhc2
python3 scripts/mhc2_fetch_data.py netmhciipan_43 --out data/mhc2
```

Normalize HLAIIPred positive CSVs into cancerstudio JSONL:

```bash
python3 scripts/mhc2_prepare_dataset.py \
  data/mhc2/hlaiipred_zenodo/train_positive.csv \
  data/mhc2/hlaiipred_zenodo/valid_positive.csv \
  data/mhc2/hlaiipred_zenodo/test_positive.csv \
  --out data/mhc2/curated/hlaiipred_positive.jsonl
```

For merged corpora without trusted partitions, use 9-mer cluster splitting:

```bash
python3 scripts/mhc2_prepare_dataset.py data/mhc2/manual/*.tsv \
  --out data/mhc2/curated/research_sota.jsonl \
  --cluster-split
```

## Training

Install the research environment separately from the production backend:

```bash
python3 -m venv .venv-mhc2
. .venv-mhc2/bin/activate
pip install -r backend/requirements-mhc2.txt
```

Train a checkpoint:

```bash
python3 scripts/mhc2_train.py \
  --train-jsonl data/mhc2/curated/hlaiipred_train.jsonl \
  --valid-jsonl data/mhc2/curated/hlaiipred_valid.jsonl \
  --pseudosequences data/mhc2/netmhciipan_43/pseudosequences.txt \
  --proteome-fasta data/reference/human_proteome.fa \
  --out data/mhc2/checkpoints \
  --track public_reproduce
```

The model scores candidate 9-mer cores for each peptide and each HLA-II allele
or heterodimer, then trains on the max over core/allele scores. Polyallelic MS
rows stay polyallelic rather than being falsely assigned to one allele.

## Prediction And Benchmarking

Predict:

```bash
python3 scripts/mhc2_predict.py \
  --checkpoint data/mhc2/checkpoints/public_reproduce.pt \
  --pseudosequences data/mhc2/netmhciipan_43/pseudosequences.txt \
  --input benchmark_inputs.csv \
  --out benchmark_predictions.csv
```

Evaluate a prediction file with `label`/`score` columns:

```bash
python3 scripts/mhc2_benchmark.py benchmark_predictions.csv \
  --out data/mhc2/benchmarks/public_reproduce.metrics.json
```

## Release Policy

- Release code and weights only with a model card and data provenance manifest.
- Do not redistribute NetMHCIIpan or MixMHC2pred binaries.
- Mark any checkpoint trained with SysteMHC weak labels as `weak_augmented`, not
  an independent benchmark model.
- Human HLA-II is the v1 scope. Dog/cat DLA/FLA class II remains unsupported
  until there is enough species-specific peptide-ligand evidence.

