<!-- BEGIN:nextjs-agent-rules -->
# This is NOT the Next.js you know

This version has breaking changes — APIs, conventions, and file structure may all differ from your training data. Read the relevant guide in `node_modules/next/dist/docs/` before writing any code. Heed deprecation notices.
<!-- END:nextjs-agent-rules -->

# cancerstudio Agent Guide

## Mission

Build a desktop-first studio for designing personalized mRNA cancer vaccines. Today the shipped product focuses on a guided core workflow: local tumor + normal intake, local alignment, and an honest preview of variant calling, with later stages kept visible as roadmap items. See `CLAUDE.md` for the full scientific context.

## Stack

### Frontend (installed)

- Next.js 15.5, React 19.2.4, TypeScript, App Router
- Tailwind CSS v4, shadcn primitives (`@base-ui/react`)
- `lucide-react` for icons
- `class-variance-authority`, `clsx`, `tailwind-merge`, `tw-animate-css`

### Desktop shell (installed)

- Electron 37

### Backend (installed)

- FastAPI, Pydantic v2, SQLAlchemy 2.0, Biopython
- Local filesystem + SQLite via `backend/app/runtime.py`
- `samtools` for BAM/CRAM -> FASTQ normalization
- `strobealign` + `samtools` for alignment

## Repo Map

```
src/app/page.tsx                          — landing page, workspace creation
src/app/workspaces/[workspaceId]/page.tsx — redirect to active stage
src/app/workspaces/[workspaceId]/[stage]/page.tsx — stage view
src/app/layout.tsx                        — root layout

src/components/workspaces/                — IngestionStagePanel, AlignmentStagePanel,
                                            VariantCallingStagePanel,
                                            WorkspaceStageShell, WorkspaceCreateCard
src/components/ui/                        — button, badge, card, progress, tabs, separator

src/lib/api.ts                            — API client (snake_case → camelCase mapping)
src/lib/desktop.ts                        — Electron bridge typing/helpers
src/lib/types.ts                          — all domain types + PIPELINE_STAGES constant
src/lib/workspace-utils.ts                — workspace helper functions

electron/main.cjs                         — Electron BrowserWindow shell + IPC
electron/preload.cjs                      — safe renderer bridge

backend/app/main.py                       — FastAPI app, CORS, router wiring
backend/app/runtime.py                    — app-data and workspace path helpers
backend/app/db.py                         — SQLAlchemy engine, session, init_db
backend/app/api/workspaces.py             — workspace CRUD, local-file ingestion,
                                            alignment endpoints
backend/app/models/records.py             — ORM: WorkspaceRecord, IngestionBatchRecord,
                                            WorkspaceFileRecord, PipelineRunRecord,
                                            PipelineArtifactRecord
backend/app/models/schemas.py             — Pydantic request/response schemas
backend/app/services/workspace_store.py   — workspace, ingestion, normalization logic
backend/app/services/alignment.py         — local alignment runner + artifacts
backend/app/services/background.py        — ThreadPoolExecutor for async tasks
backend/tests/test_workspace_api.py       — workspace and ingestion API coverage
backend/tests/test_real_data_ingestion.py — real-data smoke coverage
.run/Cancerstudio Electron App.run.xml    — shared JetBrains run config
```

## Routes

| Path | What it does |
|------|-------------|
| `/` | Lists workspaces or shows create card |
| `/workspaces/[workspaceId]` | Redirects to the latest actionable stage in the guided flow |
| `/workspaces/[workspaceId]/[stage]` | Stage panel — ingestion and alignment are live, variant calling is read-only, later stages stay disabled roadmap items |

## API Endpoints

| Method | Path | Notes |
|--------|------|-------|
| GET | `/health` | Health check |
| GET | `/api/workspaces` | List all workspaces |
| POST | `/api/workspaces` | Create workspace |
| GET | `/api/workspaces/{id}` | Get workspace with files and ingestion summary |
| PATCH | `/api/workspaces/{id}/analysis-profile` | Set reference preset / override |
| PATCH | `/api/workspaces/{id}/active-stage` | Update active stage |
| POST | `/api/workspaces/{id}/ingestion/local-files` | Register local FASTQ/BAM/CRAM files |
| GET | `/api/workspaces/{id}/ingestion/preview/{sample_lane}` | Preview canonical reads |
| DELETE | `/api/workspaces/{id}/ingestion` | Reset ingestion state |
| GET | `/api/workspaces/{id}/alignment` | Load alignment summary |
| POST | `/api/workspaces/{id}/alignment/run` | Start alignment |
| POST | `/api/workspaces/{id}/alignment/rerun` | Re-run alignment |
| GET | `/api/workspaces/{id}/alignment/artifacts/{artifact_id}/download` | Download BAM/QC artifacts |
| GET | `/api/workspaces/{id}/variant-calling` | Load the read-only scaffold summary |
| POST | `/api/workspaces/{id}/variant-calling/run` | Returns `409 stage_not_actionable` until Mutect2 orchestration exists |
| POST | `/api/workspaces/{id}/variant-calling/rerun` | Returns `409 stage_not_actionable` until Mutect2 orchestration exists |

## Data Model

```
Workspace
  ├── id, displayName, species (human | dog | cat), activeStage, createdAt, updatedAt
  ├── analysisProfile: referencePreset/referenceOverride
  ├── ingestion: IngestionSummary (status, readyForAlignment, sourceFileCount, ...)
  └── files: WorkspaceFile[]
        ├── id, batchId, filename, format (fastq | bam | cram)
        ├── fileRole (source | canonical), status (uploaded | normalizing | ready | failed)
        ├── readPair (R1 | R2 | unknown), sizeBytes
        ├── sourcePath? (original local file)
        ├── managedPath? (app-managed canonical/alignment output)
        └── error?

Pipeline stages: ingestion → alignment → variant-calling → annotation →
  neoantigen-prediction → epitope-selection → construct-design →
  structure-prediction → construct-output → ai-review
```

Frontend uses camelCase, backend uses snake_case. `src/lib/api.ts` handles the mapping.

## Implementation Status

**Live:**

- Workspace CRUD with species-aware reference preset defaults (GRCh38 / CanFam4 / felCat9)
- Paired tumor + normal lane model with local-file registration (FASTQ / BAM / CRAM)
- Canonical FASTQ normalization via `samtools` (BAM/CRAM → paired gzipped FASTQ)
- Lane-level canonical read preview (sampled FASTQ + GC / length stats)
- Alignment stage: strobealign + samtools, per-lane flagstat / idxstats / stats, QC verdict
- First-run reference bootstrap under the app-data directory; custom `REFERENCE_*_FASTA` overrides
- Alignment artifact download (BAM / BAI / flagstat / idxstats / stats)
- Desktop intake via Electron IPC bridge (`src/lib/desktop.ts` ↔ `electron/preload.cjs`)
- Real-data smoke harness: matched SEQC2 FASTQ smoke for ingestion plus opt-in live alignment smoke in `test_real_data_ingestion.py`, and desktop ingestion smoke in `tests/e2e/ingestion-real-data.spec.ts`
- Shared pipeline policy across route redirects, stage chrome, and stage availability

**Scaffolded:** Variant calling is visible as a read-only stage with a stable `stage_not_actionable` API response until Mutect2 orchestration exists.

**Planned:** Annotation through construct output stay visible as disabled roadmap stages. Structure prediction and AI review remain separate disabled research modules.

## Known Edge Cases

1. **Unpaired readiness bug:** `batch_status_from_files()` checks for *any* ready R1 and *any* ready R2 in the batch without verifying they belong to the same sample pair. See `workspace_store.py` around `summarize_batch`.

## Development Commands

```bash
# Desktop app
npm run desktop:dev

# Split-process desktop dev
npm run desktop:frontend
npm run desktop:backend
npm run desktop:electron

# Lint
npm run lint

# Fast local checks
npm run test:fast

# Browser integration checks
npm run test:integration

# Live real-data checks
npm run test:backend:real-data
npm run test:browser:real-data
```

`npm run sample-data:alignment` materializes a tiny BAM/CRAM normalization-only fixture and expects a local `samtools` binary.

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
