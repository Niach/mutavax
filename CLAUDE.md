# cancerstudio — Domain Brief

## What This Is

A desktop-first pipeline for designing personalized mRNA cancer vaccines. You provide two DNA samples (tumor + normal) by pointing the app at local sequencing files, and the pipeline walks through alignment, variant calling, neoantigen prediction, and mRNA construct design — outputting a vaccine sequence ready for synthesis.

Supports multiple species: human, dog, and cat. The canine case came first, but the architecture is species-flexible.

Runtime today: an Electron shell over a local Next.js renderer and a local FastAPI engine, with workspace artifacts and SQLite stored under an app-data directory. No cloud services, no Docker, no object storage — everything stays on disk.

## Origin

Inspired by Paul Conyngham's work creating a personalized mRNA vaccine for his dog Rosie (mast cell cancer, 2025). His pipeline — BWA-MEM2, Mutect2, VEP, pVACseq with NetMHCpan-4.1 — produced a seven-target vaccine that achieved 75% tumor shrinkage. That case proved the approach works. cancerstudio is an attempt to make it accessible as a guided workspace.

## Pipeline Stages

| # | Stage | Status | Tools | Description |
|---|-------|--------|-------|-------------|
| 1 | Ingestion | **Live** | samtools, fastp | Choose local FASTQ/BAM/CRAM files, normalize to canonical paired FASTQ |
| 2 | Alignment | **Live** | strobealign, samtools | Align canonical tumor/normal FASTQ pairs, persist BAMs, and score QC |
| 3 | Variant Calling | Planned | GATK Mutect2 | Identify somatic mutations from the aligned tumor/normal BAMs |
| 4 | Annotation | Planned | Ensembl VEP | Annotate variants with functional consequences |
| 5 | Neoantigen Prediction | Planned | pVACseq, NetMHCpan-4.1 | Predict MHC binding for mutant peptides |
| 6 | Epitope Selection | Planned | pVACview, custom scoring | Rank and select optimal vaccine targets |
| 7 | mRNA Construct Design | Planned | LinearDesign, DNAchisel, ViennaRNA | Optimize codons, UTRs, and secondary structure |
| 8 | Construct Output | Planned | pVACvector, Biopython | Generate final annotated mRNA sequence |
| 9 | Structure Prediction | Later | Boltz-2, ESMFold, Mol* | Research-only structural follow-up, outside the Paul-core v1 path |
| 10 | AI Review | Later | Claude API, ESM-C | Research-only validation and optimization suggestions |

## Scientific Context

### mRNA Construct Format

5' cap → 5' UTR → Kozak → signal peptide (tPA) → [epitope cassette with linkers] → stop codon → 3' UTR → poly(A) tail (100-120 nt)

### Epitope Linkers

- CTL: `AAY`
- HTL: `GPGPG`
- B-cell: `KK`

### Reference Genomes

- **Human:** GRCh38 (hg38)
- **Dog:** CanFam4 (UU_Cfam_GSD_1.0) — German Shepherd-based, resolves complete DLA region
- **Cat:** felCat9

### MHC Systems

- **Human HLA:** >35,000 named alleles, extensive binding data
- **Dog DLA:** ~455 named alleles, fewer than 5 allotypes with validated binding data — this is the pipeline's largest scientific uncertainty for canine cases
- DLA loci: DLA-88 (class I, 139 alleles), DLA-DRB1 (class II, 160 alleles)

### Regulatory

Veterinary biologics fall under USDA APHIS (9 CFR Parts 101-118), not FDA.

## Known Gaps

1. **DLA binding data scarcity** — only ~5 allotypes with experimental validation
2. **No canine COSMIC** — must cross-reference somatic mutations through human orthologs
3. **No standardized DLA typing service** — research-grade NGS only
4. **Minimal canine immunopeptidome** — MS-based ligand profiling exists for a handful of alleles
5. **NetMHCpan licensing** — free for academic use, commercial license needed from DTU

## Reference Resources

These are external databases, not integrations built into the app:

- **IPD-MHC Database** — 139 DLA-88 class I alleles, 160 DLA-DRB1 class II alleles
- **ICDC** (caninecommons.cancer.gov) — NCI canine cancer multi-omic repository
- **Dog10K** (dog10k.kiz.ac.cn) — SNV browser, scRNA-seq, multi-assembly genome browser
- **DoGA consortium** — >100,000 promoters across 132 tissues mapped to CanFam4
- **Kazusa codon tables** — TaxID 9615 for canine codon usage

## Development Principles

- Every prediction must surface uncertainty — do not present results as clinically definitive
- The app must be usable by veterinary oncologists without CLI expertise
- Use TypeScript strict mode throughout frontend
- All bioinformatics parameters should have sensible defaults with expert-override capability
- Every pipeline step should be independently runnable and resumable
- Supported file formats: FASTQ, BAM, CRAM, VCF, BED, GFF3, FASTA, PDB, GenBank
