# cancerstudio

You give it two DNA samples — one from the tumor, one from healthy tissue. The pipeline figures out what mutated, predicts which mutations the immune system can target, and designs a personalized mRNA vaccine construct.

The idea is simple: compare tumor DNA against normal DNA, find the differences that matter, and turn those into a vaccine. The pipeline handles upload, alignment, variant calling, neoantigen prediction, epitope selection, and mRNA construct design — all in one workspace.

It's early. Right now the ingestion stage works end-to-end (upload sequencing files, normalize them into paired FASTQ). The rest of the pipeline is being built out stage by stage.

## Backstory

This project started after Paul Conyngham's story about building a personalized mRNA vaccine for his dog Rosie, who had mast cell cancer. That work used BWA-MEM2, Mutect2, VEP, and pVACseq with NetMHCpan to design a seven-target vaccine that achieved 75% tumor shrinkage. His [write-up on X](https://x.com/paul_conyngham/status/2036940410363535823) is worth reading.

The canine case was the starting point, but cancerstudio supports human, dog, and cat — the pipeline adapts to whichever species you're working with.

## What works today

- Create workspaces and switch between them
- Upload FASTQ, BAM, or CRAM files with drag-and-drop
- Batch normalization: compressed FASTQ copies through, uncompressed gets gzipped, BAM/CRAM converts to paired FASTQ via samtools
- Full Docker Compose stack (frontend, backend, worker, Redis, Postgres, MinIO)
- Backend test suite covering the ingestion flow

Alignment is next. Everything downstream (variant calling through construct output) is planned but not yet wired up.

### Create a workspace

![Create a workspace in cancerstudio](docs/screenshots/create-workspace.png)

Start a workspace, choose the species, and name the case before moving into the live ingestion flow.

### Ingestion workspace

![The ingestion stage in cancerstudio](docs/screenshots/ingestion-workspace.png)

Upload FASTQ, BAM, or CRAM files, track normalization, and see when canonical paired FASTQ is ready for alignment.

## Stack

- **Frontend:** Next.js 15.5, React 19, TypeScript, Tailwind CSS
- **Backend:** FastAPI, Celery + Redis, SQLAlchemy
- **Storage:** PostgreSQL (Docker) or SQLite (local dev), MinIO for files
- **Infra:** Docker Compose with 7 services

## Local development

### Frontend

```bash
npm install
npm run dev
```

### Backend

```bash
cd backend
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### Celery worker

```bash
cd backend
source venv/bin/activate
celery -A app.tasks.celery_app worker --loglevel=info
```

### Docker (full stack)

```bash
docker compose up --build
```

Runs frontend at `localhost:3000`, backend at `localhost:8000`, MinIO console at `localhost:9001`.

### Lint and tests

```bash
npm run lint
./backend/venv/bin/pytest backend/tests
```
