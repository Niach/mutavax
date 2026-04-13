# cancerstudio

Two DNA samples in, one mRNA vaccine out. cancerstudio is a desktop-first studio for designing personalized cancer vaccines for humans, dogs, and cats. You point the app at local tumor and matched-normal sequencing files, it prepares alignment-ready inputs on your disk, aligns them against a species reference, and stages the rest of the neoantigen workflow.

Project site: <https://niach.github.io/cancerstudio/>

## Screenshots

| Pick a species | Stage the samples | Run alignment |
| --- | --- | --- |
| ![landing](docs/screenshots/landing.png) | ![ingestion](docs/screenshots/ingestion.png) | ![alignment](docs/screenshots/alignment.png) |

## Pipeline

`Ingestion -> Alignment -> Variant Calling -> Annotation -> Neoantigen Prediction -> Epitope Selection -> mRNA Construct Design -> Construct Output`

Ingestion and alignment are live. The downstream stages are wired into the UI but not implemented yet. Structure Prediction and AI Review live in a separate research track.

## How it works

- Desktop-first runtime: Electron shell + local Next.js renderer + local FastAPI pipeline engine. No cloud, no Docker, no object storage.
- Reference-in-place intake: your source FASTQ/BAM/CRAM files stay where they live. Only derived artifacts (canonical FASTQ, BAM/BAI, QC, reference bundles, SQLite) land in the app-data directory.
- Species presets: human `GRCh38`, dog `CanFam4`, cat `felCat9`. Missing references are downloaded and indexed on first alignment.
- Paired-lane model: tumor and normal are separate lanes. Alignment unlocks only when both lanes are paired-end ready.

## Stack

- Frontend: Next.js 15.5, React 19, TypeScript, Tailwind CSS
- Desktop shell: Electron
- Backend: FastAPI, SQLAlchemy, samtools, pigz, strobealign
- Storage: local filesystem + SQLite

## Local development

Install dependencies once:

```bash
npm install
python -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
```

Run the desktop app in development:

```bash
npm run desktop:dev
```

This starts:

- Next.js on `127.0.0.1:3000`
- FastAPI on `127.0.0.1:8000`
- Electron once both services are healthy

If you want the processes split out manually:

```bash
npm run desktop:frontend
npm run desktop:backend
npm run desktop:electron
```

JetBrains users can run the shared `Cancerstudio Electron App` config from `.run/`.

## Environment

Copy `.env.example` to `.env` for local overrides. The most important settings are:

- `CANCERSTUDIO_APP_DATA_DIR`: managed app-data root for local outputs and cached references
- `LOCAL_SQLITE_PATH`: optional explicit SQLite location
- `SAMTOOLS_REFERENCE_FASTA`: local FASTA used when CRAM normalization needs a reference
- `REFERENCE_*_FASTA`: optional manual override for human/dog/cat references

If you do not set `REFERENCE_*_FASTA`, cancerstudio caches preset references under the app-data directory and prepares them on first alignment.

## System requirements

cancerstudio shells out to three bioinformatics binaries from the FastAPI backend. They must be on `PATH` (or pointed at via the env overrides below) before the live ingestion and alignment stages can run.

| Tool | Purpose | Used by |
|------|---------|---------|
| `samtools` ≥ 1.16 | BAM/CRAM normalization, sort, index, flagstat, idxstats, stats, markdup | Ingestion + Alignment |
| `strobealign` ≥ 0.17 | Reference indexing and paired-end alignment | Alignment |
| `pigz` ≥ 2.6 | Multithreaded FASTQ compression for managed `.fastq.gz` outputs | Ingestion |

If any of these are missing the backend will reject the relevant API call up-front with a structured `503 missing_tools` response, and the UI surfaces a friendly callout listing what to install — no more raw `[Errno 2]` stack traces.

> **Memory warning for the first alignment run.** `strobealign --create-index` peaks at roughly **31 GB of RAM** while building `genome.fa.r150.sti`. The backend refuses to start indexing if `/proc/meminfo` reports less than 35 GB available, so your box won't get pushed into swap. If you're on a modest machine, close your browser, IDE, and dev servers before hitting *Start alignment* the first time — or run `scripts/prepare-reference.sh` from a clean terminal to finish the index in isolation. Once the index is on disk the backend detects it on subsequent runs and skips bootstrapping entirely.

### Install on Ubuntu / Debian / Linux Mint

A helper script handles all three. It pulls `samtools` + `pigz` + the build toolchain from apt, then builds `strobealign` v0.17.0 from source into `/usr/local/bin` (upstream doesn't ship prebuilt binaries):

```bash
sudo bash scripts/install-bioinformatics-deps.sh
```

Or do it by hand:

```bash
sudo apt-get update
sudo apt-get install -y samtools pigz build-essential cmake zlib1g-dev

curl -fsSL https://github.com/ksahlin/strobealign/archive/refs/tags/v0.17.0.tar.gz -o /tmp/strobealign.tar.gz
tar -xzf /tmp/strobealign.tar.gz -C /tmp
cmake -B /tmp/strobealign-0.17.0/build -S /tmp/strobealign-0.17.0 -DCMAKE_BUILD_TYPE=Release
make -C /tmp/strobealign-0.17.0/build -j"$(nproc)"
sudo install -m 0755 /tmp/strobealign-0.17.0/build/strobealign /usr/local/bin/strobealign
rm -rf /tmp/strobealign.tar.gz /tmp/strobealign-0.17.0
```

### Install on macOS

```bash
brew install samtools pigz strobealign
```

### Verify

```bash
samtools --version | head -1
strobealign --version
pigz --version
```

### Env overrides

Useful when you have non-standard binary locations or want to point at a specific build:

- `SAMTOOLS_BINARY` — absolute path or alternate command name (default `samtools`)
- `ALIGNMENT_STROBEALIGN_BINARY` — absolute path or alternate command name (default `strobealign`)
- `PIGZ_BINARY` — absolute path or alternate command name (default `pigz`)
- `PIGZ_THREADS` — worker count for pigz compression

### Standalone reference indexer

If *Start alignment* refuses with an "insufficient memory" callout, or you'd just rather not run the memory-hungry indexing inside the live app:

```bash
bash scripts/prepare-reference.sh
```

Defaults to `~/.local/share/cancerstudio/references/grch38/genome.fa`. Pass a different FASTA as the first argument to index something else. The script checks `MemAvailable`, refuses to start if <35 GB is free, and runs `samtools faidx` + `strobealign --create-index -r 150` in a clean process. Once it finishes, restart the backend — the alignment stage will detect the existing index and skip bootstrapping entirely.

## Tests

```bash
npm run lint
npm run test:backend:fast
```

Real-data smoke fixtures:

```bash
npm run sample-data:smoke
```

Browser ingestion smoke:

```bash
npx playwright install chromium
npm run test:browser:real-data
```

Backend real-data smoke:

```bash
npm run test:backend:real-data
```

Opt-in live alignment smoke:

- uses the matched SEQC2 tumor/normal FASTQ smoke pair
- requires local `samtools` and `strobealign`
- downloads and indexes `GRCh38` on first run unless `REFERENCE_GRCH38_FASTA` is already set
- runs only when `REAL_DATA_RUN_ALIGNMENT=1`

## Sample data

The repo includes helpers for public smoke fixtures:

- SEQC2 human tumor/normal FASTQ smoke data for ingestion and opt-in live alignment smoke
- a tiny BAM/CRAM smoke dataset for local normalization checks only

There is no full downstream pipeline fixture yet. Variant calling and later stages remain placeholder-backed.

The BAM/CRAM helper expects a local `samtools` binary.

Download them with:

```bash
npm run sample-data:smoke
npm run sample-data:alignment
```
