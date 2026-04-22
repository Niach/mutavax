# cancerstudio — Domain Brief

## What This Is

A desktop-first pipeline for designing personalized mRNA cancer vaccines. You provide two DNA samples (tumor + normal) by pointing the app at local sequencing files, and the product guides you through intake, alignment, variant calling, annotation, neoantigen prediction, epitope curation, mRNA construct design, and the final FASTA handoff to a manufacturer.

Supports multiple species: human, dog, and cat. The canine case came first, but the architecture is species-flexible.

Runtime today: Docker Compose orchestrates a containerized FastAPI backend; the Next.js frontend runs on the host (`npm run dev`) and is accessed at `http://localhost:3000`. Workspace artifacts and SQLite live under a host directory (default `~/cancerstudio-data`) bind-mounted into the backend container as `/app-data`. No cloud services, no object storage — everything stays on disk.

## Origin

Inspired by Paul Conyngham's work creating a personalized mRNA vaccine for his dog Rosie (mast cell cancer, 2025). His pipeline — BWA-MEM2, Mutect2, VEP, pVACseq with NetMHCpan-4.1 — produced a seven-target vaccine that achieved 75% tumor shrinkage. That case proved the approach works. cancerstudio is an attempt to make it accessible as a guided workspace.

## Pipeline Stages

| # | Stage | Status | Tools | Description |
|---|-------|--------|-------|-------------|
| 1 | Ingestion | **Live** | samtools, fastp | Choose local FASTQ/BAM/CRAM files, normalize to canonical paired FASTQ |
| 2 | Alignment | **Live** | strobealign, samtools | Chunked pipeline with stop-and-resume; aligns canonical tumor/normal FASTQ pairs, persists BAMs, and scores QC |
| 3 | Variant Calling | **Live** | GATK Mutect2 (+ Broad 1000G PON for human) | Runs Mutect2 + FilterMutectCalls on the aligned tumor/normal BAMs; human runs also apply the Broad 1000G panel-of-normals to suppress recurrent artefacts; parses the filtered VCF into per-chromosome counts, filter breakdown, VAF histogram, and top variants; renders a karyogram and metrics console |
| 4 | Annotation | **Live** | Ensembl VEP 111 | Runs VEP against a species-specific offline cache with the pVACseq-ready Frameshift/Wildtype/Downstream plugins; renders cancer-gene cards, a lollipop plot of the top gene, plain-English impact tiles, a consequence donut, and a filterable annotated-variants table |
| 5 | Neoantigen Prediction | **Live** | pVACseq, NetMHCpan-4.2 | Runs pVACseq against the annotated VCF from stage 4 (class I on NetMHCpan 4.2, class II on NetMHCIIpan 4.3) and parses the output into binding buckets, a peptide × allele heatmap, a VAF/binding scatter, an antigen funnel, and a top-candidates table |
| 6 | Epitope Selection | **Live** | pVACview curation, custom scoring, DIAMOND blastp vs. Swiss-Prot | Curation UI on top of stage 5's candidates: 8-slot cassette, radial allele-coverage wheel, six plain-English goals checklist, filterable/sortable deck of peptides, selection summary; picks persist per workspace. Deck is built from pVACseq's top candidates when stage 5 has completed for the workspace; demo workspaces without a real stage-5 run fall back to the 43-peptide fixture deck. Self-identity safety flags come from a real DIAMOND blastp of each candidate against the species-specific UniProt Swiss-Prot proteome (auto-downloaded on first real-data run, cached under `${CANCERSTUDIO_DATA_ROOT}/references/proteome/{species}/`); tiers are critical (100% identity) / elevated (≥80%) / mild (≥60%) and the goals check gates "ready for construct design" on no-critical-hits. Fixture workspaces keep their fixture flags. |
| 7 | mRNA Construct Design | **Live** | LinearDesign, DNAchisel, ViennaRNA | Wraps the stage-6 picks with a tPA signal peptide, AAY/GPGPG linkers, MITD trafficking tail, Kozak, 5′/3′ UTRs, and poly(A); λ slider trades CAI vs. MFE, SP/MITD toggles, per-workspace wild-type→optimized codon-swap preview, manufacturability checks, "Confirm & hand off" locks the design. Two-phase optimization: LinearDesign picks codons against a species-appropriate usage table (human for human workspaces, mouse as mammalian proxy for dog/cat — canine Kazusa not yet in python_codon_tables), then DNAchisel nudges synonymous codons to clear restriction sites / repeats / GC / homopolymer breaches while keeping the protein byte-identical. ViennaRNA folds the optimized mRNA for the MFE pill and the cap-proximal hairpin check. |
| 8 | Construct Output | **Live** | Biopython SeqIO | Assembles the confirmed construct into a color-coded 60-char FASTA hero (+ mini ribbon), offers FASTA/GenBank/JSON downloads, CMO picker (Twist/Aldevron/TriLink) with release flow that stamps a deterministic sha256 checksum + PO number, vet dosing protocol, and a decision-trail audit card built from the workspace's actual PipelineRunRecord + IngestionBatchRecord timestamps plus stage-7 confirm and stage-8 release events. GenBank output is a real Biopython SeqIO record with CDS + /translation, 5'UTR, 3'UTR, polyA_signal, and sig_peptide features. CMO catalog + vet dosing protocol remain fixture-backed (these are policy/business data). pVACvector linker optimization is not yet wired. |
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
- Every live pipeline step should be independently runnable and resumable
- Supported file formats: FASTQ, BAM, CRAM, VCF, BED, GFF3, FASTA, PDB, GenBank
