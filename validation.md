# Validation

> How we prove cancerstudio is doing the right thing, stage by stage.

cancerstudio produces a molecule a manufacturer will synthesize and a vet will
inject into a pet. That bar demands more than "the pipeline didn't crash."
This document is the roadmap for moving every stage from *runs-end-to-end* to
*verified against public ground truth*.

It is a living document. Each stage has a checklist; check items off as the
harness lands. When you close a gap, open the next one.

## What we can and can't prove

| We **can** prove in this repo | We **can't** prove without a clinical partner |
| --- | --- |
| Variant calls match a community truth set on a benchmark cell line | That our specific design would shrink a specific patient's tumor |
| Our ranker surfaces peptides that were experimentally immunogenic in *other* patients (TESLA) | That our pipeline's picks would have been immunogenic in a *new* patient |
| Our construct's codon usage / MFE / manufacturability checks match published clinical mRNAs | That our construct translates + triggers T-cell response in vivo |
| Our determinism: same input → same artifact, byte-identical | |

The honest frame: **validation here means "would a bioinformatician trust this
enough to let a pet owner act on it."** Clinical outcome validation requires
prospective trials, which is outside this repo.

## Validation philosophy

1. **Every stage gets a number that moves.** Not "looks right" — a metric with
   a threshold, persisted per run, that regresses if we break something.
2. **Every validation cites a public dataset.** No fixtures standing in for
   truth. Fixtures are allowed as test inputs; they are not allowed as the
   oracle.
3. **Honest about uncertainty.** If a stage has no public truth source (e.g.,
   canine DLA immunogenicity), say so here, in the UI, and in the audit card.
4. **Validation is part of the release checklist.** A stage is not "Live" in
   the README until at least one public-dataset validation is passing in CI.

---

## Stage 1 — Ingestion

**What correctness means here:** normalization (BAM/CRAM → paired FASTQ) must
preserve every read, its mate, and its quality scores.

| Check | Dataset | Metric | Threshold | Status |
| --- | --- | --- | --- | --- |
| Read-set round-trip | COLO829 smoke fixtures | FASTQ → BAM → FASTQ read-pair count + sha of sorted name set | exact match | [ ] |
| Quality score preservation | COLO829 smoke | mean Phred drift | < 0.01 | [ ] |
| Paired-order invariant | synthetic 10k-pair fixture | `samtools view` order after `sort -n` | R1/R2 alternating 100% | [ ] |

**Harness:** `backend/tests/validation/stage1/` — pytest, runs in seconds.

## Stage 2 — Alignment

**What correctness means here:** strobealign produces a BAM whose
somatic-call downstream behaviour matches an established aligner (BWA-MEM2)
and community truth.

| Check | Dataset | Metric | Threshold | Status |
| --- | --- | --- | --- | --- |
| Mapping rate floor | GIAB HG001 30× WGS | `samtools flagstat` mapped % | ≥ 99.0% | [ ] |
| Duplicate rate sanity | COLO829 30× | `samtools markdup` flagged % | 10–25% | [ ] |
| Mean depth correctness | COLO829 30× | `mosdepth` genome-wide mean | 28–33× | [ ] |
| Concordance vs. BWA-MEM2 | GIAB HG001 chr22 | % reads with identical primary coord | ≥ 99.5% | [ ] |
| QC verdict reproducibility | COLO829 | re-run same FASTQ twice, compare metrics JSON | byte-identical | [ ] |

**Harness:** `backend/tests/validation/stage2/`. Runs overnight on
`npm run test:validation:slow`.

**Datasets to stage under `${CANCERSTUDIO_DATA_ROOT}/validation/`:**

- `giab/HG001/` — ~130 GB, from <https://ftp.ncbi.nlm.nih.gov/ReferenceSamples/giab/>
- `colo829/` — already present as smoke + full

## Stage 3 — Variant Calling (highest-leverage stage for validation)

**What correctness means here:** the somatic VCF's recall and precision
against community truth sets, stratified by VAF.

| Check | Dataset | Metric | Threshold | Status |
| --- | --- | --- | --- | --- |
| SNV F1 | **COLO829** (Craig 2016 + Valle-Inclán 2022) | recall / precision / F1 @ VAF ≥ 0.1 | F1 ≥ 0.85 | [ ] |
| SNV F1, low-VAF | COLO829 | F1 @ VAF 0.05–0.10 | F1 ≥ 0.60 (drop expected) | [ ] |
| INDEL F1 | COLO829 | F1 | ≥ 0.75 | [ ] |
| SNV recall on spike-ins | **DREAM SMC** synthetic tumors | recall at declared VAF | ≥ 0.90 @ VAF ≥ 0.20 | [ ] |
| Cross-tumor generalization | **SEQC2 HCC1395** | F1 | ≥ 0.80 | [ ] |
| PON effect | COLO829 ± PON | % recurrent-artefact calls filtered | ≥ 50% reduction | [ ] |
| Driver-gene recall | COLO829 | known driver SNVs (BRAF V600E, CDKN2A, etc.) captured | 100% | [ ] |

**Tool:** `hap.py` / `som.py` (Illumina) for VCF comparison — industry standard.

**Harness:** `backend/tests/validation/stage3/`. Requires GIAB tool chain; add
`npm run test:validation:stage3` that runs hap.py in a sidecar container.

**Datasets:**

- `colo829/truth/` — somatic SNV + SV VCFs from the published papers
- `dream-smc/` — synthetic tumors, <https://www.synapse.org/Synapse:syn312572>
- `seqc2-hcc1395/` — <https://sites.google.com/view/seqc2/home>

## Stage 4 — Annotation

**What correctness means here:** VEP output is reproducible and the pVACseq
plugins emit wild-type + frameshift + downstream peptides where expected.

| Check | Dataset | Metric | Threshold | Status |
| --- | --- | --- | --- | --- |
| VEP consequence stability | VEP 111 regression set | consequence column agreement vs. canonical | ≥ 99.9% | [ ] |
| TSL tag presence | any annotated VCF | rows with `TSL=` annotation | 100% of protein-coding variants | [ ] |
| Frameshift plugin emits peptides | a known frameshift variant (e.g., synthetic) | non-empty `FrameshiftSequence` column | 100% | [ ] |
| Wildtype plugin emits WT peptides | any missense | non-empty `WildtypeProtein` | 100% of missense | [ ] |
| Cancer-gene card consistency | COLO829 run | cancer-gene cards list ≥ 1 known driver | ≥ 1 | [ ] |

**Harness:** `backend/tests/validation/stage4/`.

## Stage 5 — Neoantigen Prediction (THE stage that most needs validation)

This is where the pipeline's scientific claim lives, and where the weakest
link (predict-then-rank) needs the strongest evidence.

**What correctness means here:** peptides that were experimentally
immunogenic in *published* patients are ranked highly when we run the
pipeline on their sequencing data.

| Check | Dataset | Metric | Threshold | Status |
| --- | --- | --- | --- | --- |
| **TESLA top-100 recall** | **TESLA** (Wells 2020, Cell — 6 patients, WES + experimentally validated immunogenic peptides) | % of experimentally immunogenic peptides present in our top-100 ranked output | ≥ 50% | [ ] |
| TESLA top-50 recall | TESLA | same, top-50 | ≥ 35% | [ ] |
| IEDB binder calibration | IEDB class I human | fraction of known strong binders we rank in top-2% | ≥ 80% | [ ] |
| HLA Ligand Atlas overlap | HLA Ligand Atlas | of our predicted strong binders for an allele, % that match a known MS-presented peptide motif | ≥ 30% | [ ] |
| NetMHCpan calibration | NetMHCpan published benchmark | AUC vs. IEDB held-out set | ≥ 0.90 (what NetMHCpan reports) | [ ] |
| Allele coverage consistency | synthetic workspace with 6 alleles | all 6 alleles appear in the peptide × allele heatmap if they have ≥ 1 bound peptide | 100% | [ ] |
| Skipped-allele reporting | dog workspace with DLA alleles pVACseq doesn't know | SKIPPED pill rendered with reason | 100% | [ ] |
| Rescue-pool behaviour | synthetic VCF with a low-TPM driver | driver appears in final ranked output | 100% | [ ] |

**Dataset acquisition:**

- **TESLA** — controlled access via dbGaP / the Parker Institute. Requires a
  data-use agreement. This is the single highest-value dataset to get access
  to. Start the DUA now.
- **IEDB** — <https://www.iedb.org/> — public, free.
- **HLA Ligand Atlas** — <https://hla-ligand-atlas.org/> — public, free.

**Harness:** `backend/tests/validation/stage5/`. TESLA-gated tests skip if
`TESLA_DATA_DIR` env var is unset.

## Stage 6 — Epitope Selection

**What correctness means here:** our curation logic (pVACview + custom scoring
+ cancer-gene boost + gene-diversity fallback + allele coverage) produces a
7-peptide cassette that reasonable clinicians would pick, measured against
published vaccine designs.

| Check | Dataset | Metric | Threshold | Status |
| --- | --- | --- | --- | --- |
| Published-vaccine overlap (melanoma) | **Ott 2017** NEJM NeoVax (6 patients, 20 peptides each) — peptide sequences in supplement | gene-level overlap of our 7 picks vs. their 20 | ≥ 40% | [ ] |
| Published-vaccine overlap (BioNTech) | **Sahin 2017** Nature IVAC MUTANOME | same | ≥ 30% | [ ] |
| Pancreatic | **Rojas 2023** Nature autogene cevumeran (16 PDAC patients) | same | ≥ 30% | [ ] |
| Glioblastoma | **Keskin 2019** Nature NeoVax | same | ≥ 30% | [ ] |
| Canine | **Paul Conyngham's Rosie case** — 7 peptides published | gene-level overlap | ≥ 50% | [ ] |
| Self-identity safety | any run | 100% of picked peptides cleared BLAST-to-proteome (requires wiring; currently fixture-only per CLAUDE.md — **this is the #1 safety gap**) | 100% | [ ] |
| Driver representation | any human run | ≥ 1 picked peptide from a gene in our `data/cancer_genes.csv` | ≥ 1 when drivers are in the VCF | [ ] |
| Allele coverage goal | any run with ≥ 2 class-I and ≥ 1 class-II alleles | final cassette covers ≥ 2 class-I + ≥ 1 class-II | 100% | [ ] |
| Gene-diversity fallback | synthetic VCF with only 4 cancer-gene variants | final cassette has ≥ 6 unique genes (the fallback we added) | 100% | [ ] |

**Harness:** `backend/tests/validation/stage6/`.

**Acquisition blockers:** getting raw sequencing data for trial patients is
often impossible. Fallback: compare *peptide sets* against their published
picks, using the trials' patient-reported WES summary tables where available.

## Stage 7 — mRNA Construct Design

**What correctness means here:** the optimized mRNA is manufacturable, has
codon usage and secondary structure within the range of clinical mRNAs, and
the protein is byte-identical to the confirmed epitope cassette.

| Check | Dataset | Metric | Threshold | Status |
| --- | --- | --- | --- | --- |
| Protein identity | any run | translated optimized mRNA == input AA cassette | byte-identical | [ ] |
| CAI (human) | human run | LinearDesign output CAI vs. `python_codon_tables` human | ≥ 0.80 | [ ] |
| CAI (dog, mouse proxy) | dog run | CAI | ≥ 0.75 (looser — mouse proxy) | [ ] |
| MFE sanity | any run | ViennaRNA RNAfold MFE per nt | within 2× of BNT162b2 reference per-nt MFE | [ ] |
| Manufacturability — GC | any | 40–60% | pass | [ ] |
| Manufacturability — homopolymer | any | no run of identical base > 6 | pass | [ ] |
| Manufacturability — repeats | any | no exact repeat > 15 nt | pass | [ ] |
| Manufacturability — restriction sites | any | no BsaI / BsmBI / NheI / AgeI in ORF | pass | [ ] |
| Cap-proximal hairpin | any | no hairpin MFE < −15 kcal/mol in first 60 nt | pass | [ ] |
| Reference replay — BNT162b2 | public Pfizer mRNA sequence | our manufacturability checks all return "pass" | 7/7 pass | [ ] |
| Reference replay — mRNA-1273 | public Moderna mRNA sequence | same | 7/7 pass | [ ] |
| λ slider determinism | any run | same λ → same optimized sequence | byte-identical | [ ] |

**Harness:** `backend/tests/validation/stage7/`.

**Sequences:**

- BNT162b2: GenBank `OR076459` or WHO INN records
- mRNA-1273: WHO INN records; academic reconstructions

## Stage 8 — Construct Output

**What correctness means here:** the final FASTA / GenBank / JSON artifact is
deterministic, round-trippable, and the audit trail is complete.

| Check | Dataset | Metric | Threshold | Status |
| --- | --- | --- | --- | --- |
| Checksum determinism | any run | same input → same sha256 across runs | byte-identical | [ ] |
| FASTA spec compliance | any run | headers match `>name description` spec, 60-char lines | 100% | [ ] |
| GenBank round-trip | any run | Biopython parse → write → parse → compare SeqRecord | byte-identical | [ ] |
| GenBank features present | any run | 5'UTR, CDS (+ /translation), 3'UTR, polyA_signal, sig_peptide features | all 5 | [ ] |
| Audit trail completeness | any run | every stage has a non-null `completed_at`, `run_id`, and tool version | 100% | [ ] |
| CMO release determinism | any run | same release action → same PO number format + sha stamp | 100% | [ ] |
| Vet dosing protocol validity | any dog / cat run | protocol references a species-appropriate dose range | 100% | [ ] |

**Harness:** `backend/tests/validation/stage8/`.

---

## End-to-end validation

Three e2e scenarios that chain stages 1–8 on public (or acquirable) data.

| # | Scenario | Data | Oracle | Status |
| --- | --- | --- | --- | --- |
| E1 | **COLO829 e2e** | COLO829 paired tumor/normal (have it) | stage-3 F1 ≥ 0.85 against Craig+Valle-Inclán truth; stage-5 surfaces BRAF peptide; stage-7 7/7 manufacturability | [ ] |
| E2 | **TESLA patient re-derivation** | TESLA patient WES (needs DUA) | stage-5 recall ≥ 50% on immunogenic peptide set | [ ] |
| E3 | **Rosie re-derivation** | Rosie tumor + normal FASTQ (ask Paul; may not be obtainable) | stage-6 ≥ 50% gene overlap with published 7 picks | [ ] |

E1 is runnable today. E2 is gated on the TESLA DUA. E3 is gated on data
access — if unobtainable, the substitute is "run canine DLBCL1 and measure
driver recall against the published DLBCL driver list."

---

## Infrastructure

### Harness layout

```
backend/tests/validation/
├── stage1/
├── stage2/
├── stage3/
├── stage4/
├── stage5/
├── stage6/
├── stage7/
├── stage8/
├── e2e/
├── datasets.py          # download + verify + cache helpers
├── harness.py           # common fixtures: workspace builder, pipeline driver
└── report.py            # emits JSON + markdown per run
```

### Runners

- `npm run test:validation:fast` — pure-unit validation checks (stages 1, 4, 7, 8 that don't need large datasets) — seconds.
- `npm run test:validation:slow` — stages 2, 3, 5, 6 on prepared datasets — hours; nightly CI.
- `npm run test:validation:e2e` — full-pipeline E1/E2/E3 — overnight; weekly CI.

### Dataset staging

All validation datasets live under `${CANCERSTUDIO_DATA_ROOT}/validation/`
mirroring the production reference layout. A `scripts/fetch_validation_data.py`
script bootstraps each one idempotently (same pattern as `ensure_pon_ready`).

### Results format

Each validation run emits:

```
${CANCERSTUDIO_DATA_ROOT}/validation-runs/{iso-timestamp}/
├── report.json           # every metric + threshold + pass/fail
├── report.md             # human-readable summary
└── artifacts/            # per-stage VCFs, peptide CSVs, etc. for forensics
```

`report.md` becomes the single source of truth — committing it to the repo
on release cuts gives us a historical record of which metrics moved when.

### CI gating

- PR checks: `test:validation:fast` must pass.
- Nightly on main: `test:validation:slow` must pass; a regression on any
  threshold fails the build and opens an issue automatically.
- Release cuts: `test:validation:e2e` must pass and the `report.md` must be
  committed alongside the version bump.

---

## Priority roadmap

Ordered by leverage-per-effort. Each item is one PR-sized unit of work.

1. **Wire COLO829 e2e (E1) with stage-3 F1 against published truth.** Highest
   credibility return; uses data we already have. Unlocks all stage-3
   thresholds.
2. **Implement BLAST-to-proteome self-identity check in stage 6.** The
   biggest *safety* gap in the product — the UI implies we check for
   self-cross-reactivity but we don't. CLAUDE.md flags this.
3. **Stage-7 reference-replay on BNT162b2 / mRNA-1273.** Cheap, public data,
   immediately rebuts "is the construct sensible?"
4. **Apply for TESLA DUA.** Wall-clock long-lead item (weeks); start now so
   stage-5 real validation can land in Q3.
5. **hap.py / som.py integration for stage 3.** Required to make the
   stage-3 metrics precise and reproducible.
6. **Published-vaccine overlap harness for stage 6** (Ott / Sahin / Rojas /
   Keskin peptide sets). Doesn't need patient WES — just the peptide lists.
7. **IEDB + HLA Ligand Atlas cross-reference for stage 5.** Public data;
   valuable even without TESLA.
8. **DREAM SMC + SEQC2 HCC1395 for stage 3.** Deepens the stage-3 story
   beyond a single cell line.
9. **Stages 1 / 4 / 8 determinism harnesses.** Cheap, catches regressions,
   publishable.
10. **Rosie re-derivation (E3) contingent on data access.**

Items 1–3 are the **first milestone** — the "cancerstudio is minimally
self-validating" release.

---

## Known limitations (permanent entries)

- We cannot validate *clinical outcome* without a clinical partner. This doc
  does not pretend to.
- Canine validation is permanently thinner than human — no canine TESLA
  equivalent exists. The best we can do is cross-reference against published
  canine vaccine designs (Rosie) and use IPD-MHC motifs where available.
- Feline validation is thinner still. We may need to ship the product with a
  louder "research-only for feline cases" banner than for canine cases until
  more data exists.
- Expression filtering rescue (our driver-rescue pool) is a design choice,
  not a biologically validated one. It should remain overridable.

---

## How to contribute a validation

1. Pick an unchecked `[ ]` item above.
2. Check if the dataset is stageable under `${CANCERSTUDIO_DATA_ROOT}/validation/`;
   if not, add a fetch recipe in `scripts/fetch_validation_data.py`.
3. Write the test in `backend/tests/validation/stage{N}/`.
4. Make it emit one row into `report.json` with the threshold.
5. Check the box in this document in the same PR.

A validation is not landed until a threshold is passing on real data in CI.
