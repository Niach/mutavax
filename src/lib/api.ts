import type {
  CreateWorkspaceInput,
  IngestionSummary,
  Job,
  PipelineStageId,
  Workspace,
  WorkspaceFile,
  WorkspaceSpecies,
} from "@/lib/types";

const PUBLIC_API_BASE =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const API_BASE =
  typeof window === "undefined"
    ? process.env.INTERNAL_API_URL ?? PUBLIC_API_BASE
    : PUBLIC_API_BASE;

type WorkspaceFileDto = {
  id: string;
  batch_id: string;
  source_file_id?: string | null;
  filename: string;
  format: WorkspaceFile["format"];
  file_role: WorkspaceFile["fileRole"];
  status: WorkspaceFile["status"];
  size_bytes: number;
  uploaded_at: string;
  read_pair: WorkspaceFile["readPair"];
  storage_key: string;
  error?: string | null;
};

type IngestionSummaryDto = {
  active_batch_id?: string | null;
  status: IngestionSummary["status"];
  ready_for_alignment: boolean;
  source_file_count: number;
  canonical_file_count: number;
  missing_pairs: IngestionSummary["missingPairs"];
  updated_at?: string | null;
};

type WorkspaceDto = {
  id: string;
  display_name: string;
  species: WorkspaceSpecies;
  active_stage: PipelineStageId;
  ingestion: IngestionSummaryDto;
  files: WorkspaceFileDto[];
  created_at: string;
  updated_at: string;
};

type JobDto = {
  id: string;
  workspace_id: string | null;
  stage_id: PipelineStageId;
  status: Job["status"];
  progress: number;
  created_at: string;
  updated_at: string;
  error?: string;
  result?: Record<string, unknown> | null;
};

function mapWorkspaceFile(dto: WorkspaceFileDto): WorkspaceFile {
  return {
    id: dto.id,
    batchId: dto.batch_id,
    sourceFileId: dto.source_file_id,
    filename: dto.filename,
    format: dto.format,
    fileRole: dto.file_role,
    status: dto.status,
    sizeBytes: dto.size_bytes,
    uploadedAt: dto.uploaded_at,
    readPair: dto.read_pair,
    storageKey: dto.storage_key,
    error: dto.error,
  };
}

function mapIngestionSummary(dto: IngestionSummaryDto): IngestionSummary {
  return {
    activeBatchId: dto.active_batch_id,
    status: dto.status,
    readyForAlignment: dto.ready_for_alignment,
    sourceFileCount: dto.source_file_count,
    canonicalFileCount: dto.canonical_file_count,
    missingPairs: dto.missing_pairs,
    updatedAt: dto.updated_at,
  };
}

function mapWorkspace(dto: WorkspaceDto): Workspace {
  return {
    id: dto.id,
    displayName: dto.display_name,
    species: dto.species,
    activeStage: dto.active_stage,
    ingestion: mapIngestionSummary(dto.ingestion),
    files: dto.files.map(mapWorkspaceFile),
    createdAt: dto.created_at,
    updatedAt: dto.updated_at,
  };
}

function mapJob(dto: JobDto): Job {
  return {
    id: dto.id,
    workspaceId: dto.workspace_id,
    stageId: dto.stage_id,
    status: dto.status,
    progress: dto.progress,
    createdAt: dto.created_at,
    updatedAt: dto.updated_at,
    error: dto.error,
    result: dto.result ?? null,
  };
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const headers = new Headers(options?.headers);
  const isFormData =
    typeof FormData !== "undefined" && options?.body instanceof FormData;

  if (!isFormData && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  const res = await fetch(`${API_BASE}${path}`, {
    cache: options?.cache ?? "no-store",
    headers,
    ...options,
  });
  if (!res.ok) {
    const payload = await res.text();
    let detail: string | undefined;

    try {
      detail = (JSON.parse(payload) as { detail?: string }).detail;
    } catch {}

    throw new Error((detail ?? payload) || `API error: ${res.status}`);
  }
  return res.json();
}

export const api = {
  health: () => request<{ status: string }>("/health"),

  listWorkspaces: async () =>
    (await request<WorkspaceDto[]>("/api/workspaces")).map(mapWorkspace),
  getWorkspace: async (workspaceId: string) =>
    mapWorkspace(await request<WorkspaceDto>(`/api/workspaces/${workspaceId}`)),
  createWorkspace: async (input: CreateWorkspaceInput) =>
    mapWorkspace(
      await request<WorkspaceDto>("/api/workspaces", {
        method: "POST",
        body: JSON.stringify({
          display_name: input.displayName,
          species: input.species,
        }),
      })
    ),
  uploadWorkspaceFiles: async (workspaceId: string, files: File[]) => {
    const formData = new FormData();
    for (const file of files) {
      formData.append("files", file);
    }

    return mapWorkspace(
      await request<WorkspaceDto>(`/api/workspaces/${workspaceId}/files`, {
        method: "POST",
        body: formData,
      })
    );
  },
  updateWorkspaceActiveStage: async (
    workspaceId: string,
    activeStage: PipelineStageId
  ) =>
    mapWorkspace(
      await request<WorkspaceDto>(
        `/api/workspaces/${workspaceId}/active-stage`,
        {
          method: "PATCH",
          body: JSON.stringify({ active_stage: activeStage }),
        }
      )
    ),

  submitJob: async (
    stageId: PipelineStageId,
    workspaceId: string | null,
    params: Record<string, unknown>
  ) =>
    mapJob(
      await request<JobDto>("/api/pipeline/submit", {
        method: "POST",
        body: JSON.stringify({
          stage_id: stageId,
          workspace_id: workspaceId,
          params,
        }),
      })
    ),
  getJobStatus: async (jobId: string) =>
    mapJob(await request<JobDto>(`/api/pipeline/jobs/${jobId}`)),
  getStageResults: (stageId: string, workspaceId: string) =>
    request(`/api/pipeline/results/${stageId}/${workspaceId}`),
};
