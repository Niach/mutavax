<!-- BEGIN:nextjs-agent-rules -->
# This is NOT the Next.js you know

This version has breaking changes — APIs, conventions, and file structure may all differ from your training data. Read the relevant guide in `node_modules/next/dist/docs/` before writing any code. Heed deprecation notices.
<!-- END:nextjs-agent-rules -->

# cancerstudio Agent Guide

## Mission

Build a web studio for designing personalized mRNA cancer vaccines. Users provide tumor + normal sequencing data, and the pipeline processes it through to an mRNA vaccine construct. See `CLAUDE.md` for the full scientific context.

## Stack

### Frontend (installed)

- Next.js 15.5, React 19.2.4, TypeScript, App Router
- Tailwind CSS v4, shadcn primitives (`@base-ui/react`)
- `lucide-react` for icons
- `class-variance-authority`, `clsx`, `tailwind-merge`, `tw-animate-css`

### Backend (installed)

- FastAPI, Pydantic v2, SQLAlchemy 2.0
- Celery + Redis (task queue)
- boto3 (S3/MinIO storage), Biopython
- PostgreSQL (Docker) or SQLite (local dev fallback)
- samtools (in Docker image, for BAM/CRAM → FASTQ conversion)

## Repo Map

```
src/app/page.tsx                          — landing page, workspace creation
src/app/workspaces/[workspaceId]/page.tsx — redirect to active stage
src/app/workspaces/[workspaceId]/[stage]/page.tsx — stage view
src/app/layout.tsx                        — root layout

src/components/workspaces/                — IngestionStagePanel, FutureStagePanel,
                                            WorkspaceStageShell, WorkspaceCreateCard
src/components/ui/                        — button, badge, card, progress, tabs, separator

src/lib/api.ts                            — API client (snake_case → camelCase mapping)
src/lib/types.ts                          — all domain types + PIPELINE_STAGES constant
src/lib/workspace-utils.ts                — workspace helper functions

backend/app/main.py                       — FastAPI app, CORS, WebSocket
backend/app/db.py                         — SQLAlchemy engine, session, init_db
backend/app/api/workspaces.py             — workspace CRUD + file upload endpoints
backend/app/api/pipeline.py               — pipeline job endpoints (in-memory store)
backend/app/models/records.py             — ORM: WorkspaceRecord, IngestionBatchRecord,
                                            WorkspaceFileRecord
backend/app/models/schemas.py             — Pydantic request/response schemas
backend/app/services/workspace_store.py   — workspace + ingestion business logic
backend/app/services/s3_storage.py        — S3/MinIO storage abstraction
backend/app/tasks/celery_app.py           — Celery configuration
backend/app/tasks/ingestion_tasks.py      — batch normalization task (live)
backend/app/tasks/pipeline_tasks.py       — pipeline stage tasks (all TODO placeholders)
backend/tests/test_workspace_api.py       — ingestion test suite with FakeStorage

docker-compose.yml                        — 7 services: frontend, backend, celery-worker,
                                            redis, postgres, minio, bucket-init
Dockerfile.frontend                       — Node 20 Alpine
backend/Dockerfile                        — Python 3.12 + samtools
```

## Routes

| Path | What it does |
|------|-------------|
| `/` | Lists workspaces or shows create card |
| `/workspaces/[workspaceId]` | Redirects to the workspace's active stage |
| `/workspaces/[workspaceId]/[stage]` | Stage panel — ingestion is live, others show FutureStagePanel |

## API Endpoints

| Method | Path | Notes |
|--------|------|-------|
| GET | `/health` | Health check |
| GET | `/api/workspaces` | List all workspaces |
| POST | `/api/workspaces` | Create workspace |
| GET | `/api/workspaces/{id}` | Get workspace with files and ingestion summary |
| POST | `/api/workspaces/{id}/files` | Upload FASTQ/BAM/CRAM files |
| PATCH | `/api/workspaces/{id}/active-stage` | Update active stage |
| POST | `/api/pipeline/submit` | Submit pipeline job (mock — no Celery dispatch) |
| GET | `/api/pipeline/jobs` | List jobs (in-memory) |
| GET | `/api/pipeline/jobs/{id}` | Get job |
| GET | `/api/pipeline/stages` | List all pipeline stages |
| GET | `/api/pipeline/results/{stage_id}/{workspace_id}` | Not implemented |
| WS | `/ws/jobs` | WebSocket for job updates (skeleton) |

## Data Model

```
Workspace
  ├── id, displayName, species (human | dog | cat), activeStage, createdAt, updatedAt
  ├── ingestion: IngestionSummary (status, readyForAlignment, sourceFileCount, ...)
  └── files: WorkspaceFile[]
        ├── id, batchId, filename, format (fastq | bam | cram)
        ├── fileRole (source | canonical), status (uploaded | normalizing | ready | failed)
        ├── readPair (R1 | R2 | unknown), sizeBytes, storageKey
        └── error?

Pipeline stages: ingestion → alignment → variant-calling → annotation →
  neoantigen-prediction → epitope-selection → construct-design →
  structure-prediction → construct-output → ai-review
```

Frontend uses camelCase, backend uses snake_case. `src/lib/api.ts` handles the mapping.

## Implementation Status

**Live:** Workspace CRUD, file upload, batch normalization (compressed FASTQ copies through, uncompressed gets gzipped, BAM/CRAM converts to paired FASTQ via samtools)

**Mock:** Pipeline job submission — returns a pending job object but does not dispatch Celery tasks

**Planned:** Alignment through AI review — all tasks in `pipeline_tasks.py` are TODO placeholders

## Known Edge Cases

1. **Unpaired readiness bug:** `batch_status_from_files()` checks for *any* ready R1 and *any* ready R2 in the batch without verifying they belong to the same sample pair. See `workspace_store.py` around `summarize_batch`.
2. **Empty workspace names:** The API accepts whitespace-only names, which trim to empty strings. See `workspace_store.py` around `create_workspace`.

## Development Commands

```bash
# Frontend
npm run dev

# Backend API
cd backend && uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

# Celery worker
cd backend && celery -A app.tasks.celery_app worker --loglevel=info

# Full stack (Docker)
docker compose up --build

# Lint
npm run lint

# Backend tests
./backend/venv/bin/pytest backend/tests
```

## Agent Rules

- Before editing Next.js code, read the relevant docs in `node_modules/next/dist/docs/`.
- Preserve the App Router structure under `src/app/`.
- Keep API access centralized in `src/lib/api.ts`.
- Keep shared domain shapes explicit. If frontend and backend contracts drift, align them or document the mismatch in the same change.
- Treat bioinformatics outputs as high-uncertainty, especially for DLA binding predictions.
- Do not present placeholder pipeline stages as fully implemented.
- Prefer shipping vertical slices that keep frontend route, API contract, and backend behavior aligned.
- If a stage is still mock-backed, label it clearly in the UI.
- Favor typed interfaces over ad hoc dictionaries on both TypeScript and Python sides.
