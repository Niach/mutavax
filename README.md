# cancerstudio

cancerstudio is a desktop-first studio for the first guided steps of a personalized cancer vaccine workflow. Today it helps a non-technical operator bring in local tumor and matched-normal sequencing files, prepare alignment-ready inputs on disk, run alignment against a species reference, and search for the cancer-specific mutations with an interactive karyogram and filter view. Downstream vaccine-design stages stay visible as roadmap items, not runnable promises.

Project site: <https://niach.github.io/cancerstudio/>

## Screenshots

| Pick a species | Stage the samples | Run alignment | Find the mutations |
| --- | --- | --- | --- |
| ![landing](docs/screenshots/landing.png) | ![ingestion](docs/screenshots/ingestion.png) | ![alignment](docs/screenshots/alignment.png) | ![variant calling](docs/screenshots/variant-calling.png) |

## Pipeline

`Ingestion → Alignment → Variant Calling → Annotation → Neoantigen Prediction → Epitope Selection → mRNA Construct Design → Construct Output`

| # | Stage | State | Tools |
| --- | --- | --- | --- |
| 1 | Ingestion | **Live** | samtools, pigz, fastp |
| 2 | Alignment | **Live** | strobealign, samtools |
| 3 | Variant Calling | **Live** — GATK Mutect2 + FilterMutectCalls, rendered as karyogram, plain-language filter buckets, VAF histogram, and a top-variants table | GATK Mutect2 |
| 4 | Annotation | Planned | Ensembl VEP |
| 5 | Neoantigen Prediction | Planned | pVACseq, NetMHCpan |
| 6 | Epitope Selection | Planned | pVACview |
| 7 | mRNA Construct Design | Planned | LinearDesign, DNAchisel |
| 8 | Construct Output | Planned | pVACvector, Biopython |

Structure Prediction and AI Review stay in a separate disabled research track.

### Stage 2: chunked alignment on commodity hardware

The alignment pipeline splits each paired FASTQ into ~20M-read chunks and aligns them in parallel with fresh strobealign workers, then merges the per-chunk coord-sorted BAMs. A watcher thread enqueues chunks as they land on disk, so aligners start within ~60 s of the split beginning instead of waiting for the full split pass. A bounded queue back-pressures the splitter. Compute knobs (chunk size, parallelism, aligner threads, sort memory) live under the UI's `Advanced details` section with a live RAM-footprint estimator.

The panel surfaces honest progress for multi-hour runs: blended progress bar (5 % ref prep + 75 % chunk alignment + 15 % finalize + 5 % stats) + per-phase sub-bars, rolling-window ETA, heartbeat + stall detection, live command tail, and a desktop notification on long-run completion.

**Stop and resume.** Every aligned chunk is persisted atomically to `workspaces/{id}/alignment/{run_id}/chunks/{lane}/chunk_NNNN.coord-sorted.bam` with a manifest at `manifest.json`. Two side-by-side buttons surface the choice at decision time: *Stop & keep progress* preserves the manifest and every completed chunk BAM so a subsequent *Resume* skips them and only realigns the rest; *Cancel & discard* wipes the run directory and starts fresh. Finalize steps (markdup, index, flagstat, idxstats, stats) are idempotent — a pause during the tail phase only rebuilds what's missing on resume.

Verified end-to-end on COLO829 100× WGS (~2B tumor + 754M normal read pairs) on a 32-core workstation with 62 GB RAM: alignment finished in ~6h 26m, QC verdict pass, 98.91% tumor mapped / 98.86% normal mapped, 10 artifacts persisted.

### Stage 3: pet-owner-first variant calling

Stage 3 runs GATK Mutect2 + FilterMutectCalls on the aligned tumor/normal BAMs and parses the filtered VCF into four visual payoffs that a non-technical owner can actually read:

- **Karyogram** of every somatic call across the species' chromosomes, sized by VAF, colored by PASS vs. filtered status.
- **Metrics ribbon** — PASS calls, SNV:indel ratio, Ti/Tv, median VAF, and tumor/normal depth.
- **Plain-language filter breakdown** — raw Mutect2 flags (`panel_of_normals`, `strand_bias`, `weak_evidence`, …) are bucketed into four owner-friendly categories (Kept / Probably inherited / Low evidence / Sequencing artifact) with a one-click "Show technical breakdown" toggle for experts.
- **Top variants table** with locus, ref→alt, VAF bars, and T/N depth.

Tool names live in the Technical details drawer. The primary CTA is *Find mutations*, not *Run Mutect2*; the ready callout says "This runs on your computer using the reference genome for your pet's species" instead of "a filtered somatic VCF with its Tabix index and Mutect2 stats file".

## How it works

- Desktop-first runtime: Electron shell + local Next.js renderer + a single all-in-one Docker container that bundles the FastAPI engine and every bioinformatics tool (samtools, pigz, strobealign, GATK, NVIDIA Parabricks). No cloud, no object storage.
- Inbox intake: drop FASTQ/BAM/CRAM files into `<data-root>/inbox/` (the path you pick on first launch) and the app lists them for registration into a workspace — no OS file-picker, no host-path plumbing.
- Species presets: human `GRCh38`, dog `CanFam4`, cat `felCat9`. Missing references are downloaded and indexed on first alignment.
- Paired-lane model: tumor and normal are separate lanes. Alignment unlocks only when both lanes are ready; a QC pass unlocks variant calling, while `warn` or `fail` keeps the workflow blocked in plain language.
- GPU-accelerated variant calling: when the container sees an NVIDIA GPU, stage 3 runs NVIDIA Parabricks `mutectcaller` (5–15× faster than CPU Mutect2 on a single RTX 4090). Without a GPU it falls back to CPU GATK Mutect2 in the same image.

## Stack

- Frontend: Next.js 15.5, React 19, TypeScript, Tailwind CSS
- Desktop shell: Electron
- Backend: FastAPI + SQLAlchemy + samtools, pigz, strobealign, GATK Mutect2, NVIDIA Parabricks (all shipped in one container image)
- Storage: local filesystem + SQLite under a user-chosen data root

## Local development

Install dependencies once:

```bash
npm install
docker compose build       # ~10 GB image, first build is slow
```

Run the desktop app in development:

```bash
docker compose up -d       # backend container on :8000
npm run desktop:frontend   # Next.js on :3000
npm run desktop:electron   # Electron shell
```

Or all three in one go once the image is built:

```bash
npm run desktop:dev
```

The backend container bind-mounts `<data-root>` (defaults to `~/cancerstudio-data`, override via `CANCERSTUDIO_DATA_ROOT` in `.env`) at `/app-data` and `<data-root>/inbox/` at `/inbox`. Backend source in `backend/app` is bind-mounted for `uvicorn --reload`. Python tests run against the container: `docker compose run --rm backend pytest`.

## Environment

Copy `.env.example` to `.env` for local overrides. The most important settings are:

- `CANCERSTUDIO_APP_DATA_DIR`: managed app-data root for local outputs and cached references
- `LOCAL_SQLITE_PATH`: optional explicit SQLite location
- `SAMTOOLS_REFERENCE_FASTA`: local FASTA used when CRAM normalization needs a reference
- `REFERENCE_*_FASTA`: optional manual override for human/dog/cat references

If you do not set `REFERENCE_*_FASTA`, cancerstudio caches preset references under the app-data directory and prepares them on first alignment.

## System requirements

cancerstudio ships the entire backend — FastAPI, samtools, pigz, strobealign, GATK Mutect2, and NVIDIA Parabricks — in a single Docker image built on top of `nvcr.io/nvidia/clara/clara-parabricks:4.7.0-1`. The host only needs Docker (and, for GPU variant calling, the NVIDIA driver + container toolkit).

| Requirement | Why |
|-------------|-----|
| Docker Engine ≥ 24.0 (Linux) or Docker Desktop (macOS / Windows) | Runs the backend container |
| NVIDIA driver ≥ 570 + `nvidia-container-toolkit` (optional) | Enables GPU variant calling via Parabricks `mutectcaller`; without it stage 3 falls back to CPU GATK Mutect2 |
| ≥ 35 GB free RAM at first alignment | `strobealign --create-index` peaks at ~31 GB while building the human index. The backend refuses to start indexing below this threshold so the host doesn't get pushed into swap. |

### Install Docker + NVIDIA toolkit on Ubuntu / Debian / Linux Mint

```bash
# Docker Engine
curl -fsSL https://get.docker.com | sudo bash
sudo usermod -aG docker "$USER"

# NVIDIA Container Toolkit (skip on non-GPU hosts)
distribution=$(. /etc/os-release; echo $ID$VERSION_ID)
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey \
  | sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list \
  | sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' \
  | sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list
sudo apt-get update && sudo apt-get install -y nvidia-container-toolkit
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker
```

### macOS / Windows

Install Docker Desktop. GPU-accelerated variant calling on macOS/Windows is currently not supported — stage 3 will run on CPU. On a GPU-less host everything else (ingestion, alignment, CPU variant calling) still works.

### Verify

```bash
docker --version
nvidia-smi              # optional; only needed for GPU variant calling
docker compose up -d    # pulls/builds the backend image, starts FastAPI on :8000
curl http://127.0.0.1:8000/health
```

Alignment compute is also tunable at runtime from the UI (Compute settings section on the alignment stage) — no env file edit needed. The overrides persist to `{CANCERSTUDIO_APP_DATA_DIR}/settings.json`:

- Chunk size (read pairs per chunk, default 20M)
- Parallel chunks (default 2)
- Aligner threads per chunk
- samtools sort memory per thread

### Standalone reference indexer

If *Start alignment* refuses with an "insufficient memory" callout, or you'd just rather not run the memory-hungry indexing inside the live app:

```bash
bash scripts/prepare-reference.sh
```

Defaults to `~/.local/share/cancerstudio/references/grch38/genome.fa`. Pass a different FASTA as the first argument to index something else. The script checks `MemAvailable`, refuses to start if <35 GB is free, runs `samtools faidx` + `strobealign --create-index -r 150`, then `gatk CreateSequenceDictionary` so Mutect2 can use the reference. Once it finishes, restart the backend — the alignment stage will detect the existing index and skip bootstrapping entirely.

## Tests

Fast / local:

```bash
npm run test:fast
```

That covers lint, TypeScript, and the backend suite that passes without a live server or real sequencing fixtures.

Browser integration:

```bash
npx playwright install chromium
npm run test:integration
```

Live real-data:

```bash
npm run sample-data:smoke
npm run test:backend:real-data
npm run test:browser:real-data
```

The live real-data path uses the COLO829 matched tumor/normal WGS smoke pair by default. Opt-in live alignment still requires local `samtools`, `strobealign`, and `pigz`, downloads and indexes `GRCh38` on first run unless `REFERENCE_GRCH38_FASTA` is already set, and only runs when `REAL_DATA_RUN_ALIGNMENT=1`.

## Sample data

The repo includes helpers for public smoke fixtures:

- COLO829/COLO829BL matched melanoma pair (ENA PRJEB27698) — smoke subset plus the full 100× tumor + 38× normal WGS for validating the chunked alignment pipeline at production scale
- a tiny BAM/CRAM smoke dataset for local normalization checks only

The COLO829 full fetch is ~174 GB compressed. Per-file md5s are checked against ENA-published values on download so silent corruption fails loudly.

Download with:

```bash
npm run sample-data:smoke         # COLO829 smoke (~50k read pairs per lane)
npm run sample-data:full          # COLO829 full 100x WGS (~174 GB)
npm run sample-data:alignment     # BAM/CRAM normalization fixture
```
