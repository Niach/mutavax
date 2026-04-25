# cancerstudio MHC-II Predictor Model Card

## Intended Use

This model predicts human HLA class II peptide presentation for research-grade
neoantigen prioritization. It is not an immunogenicity predictor and must not be
used alone to select a cancer vaccine construct.

## Scope

- Species: human only.
- MHC class: HLA class II, including DR, DP, and DQ where pseudosequences are
  available.
- Peptide lengths: 8-30 amino acids.
- Outputs: presentation score, best 9-mer binding core, core offset, allele or
  heterodimer, and optional percentile rank.

## Training Data

Each released checkpoint must name its track:

- `public_reproduce`: HLAIIPred-scale public positive MS ligand corpus.
- `research_sota`: merged HLAIIPred, NetMHCIIpan-4.3, Racle/MixMHC2pred,
  Strazar/CAPTAn, and HLA Ligand Atlas data.
- `weak_augmented`: any checkpoint using SysteMHC or other predictor-derived
  weak labels.

Each checkpoint must ship a manifest containing source URLs, downloaded file
checksums, row counts, allele counts, peptide counts, split method, and leakage
report.

## Known Limitations

- MS eluted-ligand positives are sample-level observations and can be
  polyallelic. The training objective uses max-over-alleles supervision, which
  is appropriate but still ambiguous.
- Decoys are not true biological non-binders. They are length-matched human
  proteome windows filtered for 9-mer overlap with positives.
- DP/DQ and rare-allele performance must be reported separately from DR.
- SysteMHC weak labels are not independent evidence because some annotations
  depend on existing predictors.
- MHC-II presentation is only one component of vaccine design. Expression,
  variant clonality, self-similarity, manufacturability, and CD4 response
  evidence remain downstream requirements in cancerstudio.

## Required Benchmarks Before Release

- Held-out HLAIIPred split metrics: ROC-AUC, PR-AUC, F1.
- NetMHCIIpan publication evaluation where legally usable.
- Racle 2023 motif/core recovery and DP reverse-binding checks.
- Per-locus DR/DQ/DP breakdown.
- Rare-allele breakdown.
- Comparison table against NetMHCIIpan-4.3/4.3j, MixMHC2pred-2.0, HLAIIPred,
  Graph-pMHC, and MHCnuggets where users have installed the tools legally.
