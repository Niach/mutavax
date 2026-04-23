# cancerstudio

> **DISCLAIMER:** This software is provided for research and educational purposes only. Not intended for clinical or veterinary use. No warranty of fitness for any particular purpose.

> Cure your cancer. *Today.*

Sample your DNA. Compute your cure. cancerstudio designs a personalized mRNA vaccine from the mutations in *your* tumor — for dogs, cats, and humans.

**Site:** <https://cancerstudio.org> &nbsp;•&nbsp; **Status:** open source · self-hosted · v0.4

| Pick a species | Stage the samples | Run alignment | Find the mutations | Read what they mean |
| --- | --- | --- | --- | --- |
| ![landing](docs/screenshots/landing.png) | ![ingestion](docs/screenshots/ingestion.png) | ![alignment](docs/screenshots/alignment.png) | ![variant calling](docs/screenshots/variant-calling.png) | ![annotation](docs/screenshots/annotation.png) |

| Score the neoantigens | Curate the cassette | Design the construct | Hand off the vaccine | |
| --- | --- | --- | --- | --- |
| ![neoantigen prediction](docs/screenshots/neoantigen.png) | ![epitope selection](docs/screenshots/epitope-selection.png) | ![mRNA construct design](docs/screenshots/construct-design.png) | ![construct output](docs/screenshots/construct-output.png) | |

## Sample. Compute. Cure.

**Sample.** Sequence the tumor and a matched healthy sample at any standard lab. Two FASTQ files.

**Compute.** Run cancerstudio on *your* machine. Eight guided stages compare tumor vs. healthy, find the cancer-specific *mutations*, and design the molecule. ≈12 hours on a workstation.

**Cure.** Send the resulting FASTA to a GMP manufacturer. A vial arrives roughly ten days later.

## Eight stages. Twelve hours. One molecule.

| # | Stage | State | Tools |
| --- | --- | --- | --- |
| 1 | Ingestion | **Live** | samtools, pigz, fastp |
| 2 | Alignment | **Live** — chunked stop-and-resume on commodity hardware | strobealign, samtools |
| 3 | Variant Calling | **Live** — karyogram + plain-English filter buckets, Broad 1000G panel-of-normals on human runs | GATK Mutect2 (GPU via NVIDIA Parabricks when available) |
| 4 | Annotation | **Live** — cancer-gene cards + lollipop plot | Ensembl VEP 111 |
| 5 | Neoantigen Prediction | **Live** — binding buckets + peptide × allele heatmap + antigen funnel | pVACseq 5.4.0, MHCflurry 2.0 (default, license-free) or NetMHCpan 4.2, NetMHCIIpan 4.3 |
| 6 | Epitope Selection | **Live** — 8-slot cassette curation UI | pVACview + custom scoring |
| 7 | mRNA Construct Design | **Live** — molecule hero + λ slider trading CAI vs. MFE + codon swap preview + 7/7 manufacturability checks | LinearDesign, DNAchisel, ViennaRNA |
| 8 | Construct Output | **Live** — color-coded FASTA with FASTA/GenBank/JSON downloads, CMO release flow, vet dosing, audit trail | pVACvector, Biopython |

Every live stage is pause-and-resumable. Progress is surfaced honestly, tool names live in the expert drawer.

## What you'll need

### Inputs

Tumor + matched-normal sequencing for one patient. **FASTQ, BAM, or CRAM.** ≥30× coverage for confident somatic variant calling.

### Hardware

| | Recommended |
| --- | --- |
| RAM | 64 GB — strobealign indexing peaks around 31 GB free |
| CPU | 16 cores |
| Disk | 1 TB SSD — a 30× human WGS costs ~400 GB (deduped BAMs + FASTQs); multiple cases share the ~55 GB reference + VEP cache + PON footprint |
| GPU | NVIDIA Ampere+ (RTX 3090 / 4090 / A-series / H-series) — Parabricks accelerates stage 3 Mutect2 ~10× (opt-in) |
| OS | Linux |

Everything runs in two Docker containers: the backend image (FastAPI + samtools + strobealign + GATK + VEP + pVACtools + MHCflurry + Parabricks base, ~10 GB) and the frontend image (Next.js standalone, ~300 MB). No cloud, no object storage.

## Getting started

You don't need to clone this repo. Paste the compose file below, run `docker compose up -d`, open the browser.

### 1. Install Docker

Ubuntu / Debian / Linux Mint:

```bash
curl -fsSL https://get.docker.com | sudo bash
sudo usermod -aG docker "$USER"
```

macOS / Windows: install [Docker Desktop](https://www.docker.com/products/docker-desktop). For GPU-accelerated stage 3 variant calling on Linux, also install the [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html).

### 2. Create the compose file

```bash
mkdir ~/cancerstudio && cd ~/cancerstudio
curl -fsSL https://raw.githubusercontent.com/niach/cancerstudio/main/docker-compose.yml -o docker-compose.yml
```

The file pulls pre-built images from GHCR (`ghcr.io/niach/cancerstudio-backend` and `ghcr.io/niach/cancerstudio-web`) — no build step on your machine.

### 3. Create a `.env` (optional)

Most users don't need one. Add it if you want to customize anything:

```bash
cat > .env <<'EOF'
# Where workspace artifacts, references, and the SQLite DB live. Default: ./data
# CANCERSTUDIO_DATA_ROOT=./data

# Stage 9 AI review — only needed if you want the LLM review feature.
# ANTHROPIC_API_KEY=

# Switch the class-I predictor back to DTU NetMHCpan (default is MHCflurry).
# CANCERSTUDIO_CLASS_I_PREDICTOR=NetMHCpan
EOF
```

See [.env.example](.env.example) for the full list of overrides.

### 4. NetMHC binaries (optional for humans)

The compose file ships with **MHCflurry** as the default class-I predictor — a license-free alternative to NetMHCpan, validated to match NetMHCpan AUC = 1.000 on the canonical tumor-antigen benchmark. Human users running stages 1–5 class-I only need nothing else.

Opt in to the DTU NetMHC stack if you want:

- **non-human species** (dog DLA / cat FLA — MHCflurry has no canine or feline training data), **or**
- **class-II neoantigen scoring** (NetMHCIIpan has no license-free equivalent).

Both are free for academic use; commercial usage needs a separate DTU license. Fill the forms, download the Linux tarballs:

- NetMHCpan 4.2 — <https://services.healthtech.dtu.dk/services/NetMHCpan-4.2/>
- NetMHCIIpan 4.3 — <https://services.healthtech.dtu.dk/services/NetMHCIIpan-4.3/>

Extract them so the layout is:

```
./data/netmhc/
├── netMHCpan-4.2/
└── netMHCIIpan-4.3/
```

That dir is mounted at `/tools/src:ro` inside the backend container, which matches the stock DTU wrapper scripts' hardcoded `NMHOME` — no script edits.

### 5. Drop in your DNA

The backend auto-creates `./data/inbox/`, `./data/workspaces/`, `./data/references/`, and `./data/vep-cache/` on first start. Drop your tumor + normal FASTQ / BAM / CRAM pair into `./data/inbox/` and the app registers them into a workspace.

### 6. Start

```bash
docker compose up -d
```

Open <http://localhost:3000>. Create a workspace, pick a species, follow the stages.

**LAN access:** The web UI binds to `0.0.0.0:3000`, so any other machine on your network can hit `http://<server-ip>:3000`. Put it behind Caddy/Traefik if you want TLS.

**GPU-accelerated stage 3 (opt-in):**

```bash
curl -fsSL https://raw.githubusercontent.com/niach/cancerstudio/main/docker-compose.gpu.yml -o docker-compose.gpu.yml
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d
```

Requires NVIDIA drivers + the NVIDIA Container Toolkit.

### Reference genomes

Species reference — GRCh38 (human), UU_Cfam_GSD_1.0 (dog), or Felis_catus_9.0 (cat) — is auto-downloaded on the first alignment run. Cached under `./data/references/`, shared across workspaces.

### Panel-of-normals (human only)

Human workspaces apply the Broad's 1000 Genomes panel-of-normals to Mutect2 to filter recurrent artefacts and low-frequency germline variants. The VCF is auto-downloaded, renamed from UCSC to Ensembl contigs, and indexed on first variant-calling run. Lives under `./data/references/pon/grch38/`. Set `CANCERSTUDIO_PON_GRCH38_VCF=""` in `.env` to disable.

Dog and cat workspaces skip the PON (no curated canine / feline panel exists yet).

## Troubleshooting

**Alignment refuses to start with "insufficient memory."** Indexing the human reference peaks around 31 GB of RAM. Either free some up, or drop a prebuilt index into `./data/references/` (see the contributors section below).

**Stage 5 preflight says a NetMHC binary is missing.** You set `CANCERSTUDIO_CLASS_I_PREDICTOR=NetMHCpan` but didn't drop the tarballs in. Check `ls ./data/netmhc/` — should contain `netMHCpan-4.2/` and `netMHCIIpan-4.3/` as directories, not tarballs.

**Stage 5 finishes with zero peptides.** Your patient alleles weren't recognized by pvacseq. The Patient MHC panel marks these with a strikethrough + `SKIPPED` pill. For dog, pvacseq only recognizes a handful of DLA-88 alleles and zero class II alleles.

**Annotation complains about missing TSL fields.** Rerun stage 4 on the workspace — older annotations predate the `--tsl` flag and need refreshing.

## For contributors

Clone the repo for source-level work:

```bash
git clone https://github.com/niach/cancerstudio.git
cd cancerstudio
npm install
```

Frontend: Next.js 15, React 19, TypeScript, Tailwind. Backend: FastAPI + SQLAlchemy, all bioinformatics tools in one Docker image, SQLite under `./data/`.

Dev workflow — hot-reload the backend from the cloned source, run the Next.js dev server on the host:

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up    # backend with --reload on :8000
npm run dev                                                          # next dev on :3000
```

Set `NEXT_PUBLIC_API_URL=http://localhost:8000` in your `.env` for this workflow so the browser hits the native uvicorn instead of the same-origin `/backend` proxy.

Fast tests (lint + TS + backend non-integration):

```bash
npm run test:fast
```

Browser and live real-data paths:

```bash
npx playwright install chromium
npm run test:integration
npm run sample-data:smoke
npm run test:backend:real-data
npm run test:browser:real-data
```

Sample datasets for smoke and full validation runs:

```bash
npm run sample-data:smoke                 # COLO829 smoke (~50k read pairs per lane)
npm run sample-data:full                  # COLO829 full 100x WGS (~174 GB)
npm run sample-data:alignment             # BAM/CRAM normalization fixture
python3 scripts/fetch_canine_dlbcl_sample_data.py         # canine DLBCL smoke
python3 scripts/fetch_canine_dlbcl_sample_data.py --mode full  # full DLBCL1 pair (~45 GB)
```

Regenerate the screenshots in this README (frontend + backend must be running):

```bash
# Stages 1–5 need a real completed pipeline run; point the script at that workspace.
node scripts/take-screenshots.mjs <workspace-id>

# Stages 6–8 can be captured from a synthetic demo workspace that skips the heavy
# bioinformatics (inserts minimum DB stubs only — not suitable for any real run).
docker cp scripts/seed_demo_workspace.py cancerstudio-backend:/tmp/seed.py
WORKSPACE_ID=$(docker exec cancerstudio-backend python /tmp/seed.py)
node scripts/take-screenshots.mjs --stages=6,7,8 "$WORKSPACE_ID"
```

Alignment compute knobs (chunk size, per-chunk aligner threads, samtools sort memory, parallel chunks) are tunable from the UI's Compute Settings drawer on the alignment stage — no env file edit needed. They persist to `./data/settings.json`.

Full list of env overrides lives in [.env.example](.env.example).

## Credits

cancerstudio is inspired by [Paul Conyngham's 2025 personalized mRNA vaccine for his dog Rosie](https://www.unsw.edu.au/newsroom/news/2025/) (mast cell cancer, 75% tumor shrinkage). His pipeline — BWA-MEM2 → Mutect2 → VEP → pVACseq with NetMHCpan — proved the approach works on a single-patient, single-desktop scale. cancerstudio is an attempt to make that pipeline accessible as a guided workspace, species-flexible by default.

Built on the shoulders of:

- [pVACtools](https://github.com/griffithlab/pVACtools) (Griffith Lab)
- [MHCflurry](https://github.com/openvax/mhcflurry) (openvax) — license-free class-I binding predictor
- [NetMHCpan / NetMHCIIpan](https://services.healthtech.dtu.dk/) (DTU Health Tech)
- [Ensembl VEP](https://www.ensembl.org/info/docs/tools/vep/) + its pVACseq-ready plugins (Frameshift, Wildtype, Downstream)
- [GATK Mutect2](https://gatk.broadinstitute.org/) and [NVIDIA Parabricks](https://www.nvidia.com/en-us/clara/genomics/)
- [strobealign](https://github.com/ksahlin/strobealign), [samtools](https://www.htslib.org/), [pigz](https://zlib.net/pigz/)
