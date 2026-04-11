import type {
  CreateWorkspaceInput,
  FastqReadPreview,
  IngestionLaneSummary,
  IngestionLanePreview,
  IngestionSummary,
  Job,
  PipelineStageId,
  ReadPair,
  SampledReadStats,
  SampleLane,
  UploadPartResult,
  UploadSession,
  UploadSessionCreateInput,
  UploadSessionFile,
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
  sample_lane: SampleLane;
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

type IngestionLaneSummaryDto = {
  active_batch_id?: string | null;
  sample_lane: SampleLane;
  status: IngestionLaneSummary["status"];
  ready_for_alignment: boolean;
  source_file_count: number;
  canonical_file_count: number;
  missing_pairs: ReadPair[];
  blocking_issues: string[];
  read_layout?: IngestionLaneSummary["readLayout"];
  updated_at?: string | null;
};

type IngestionSummaryDto = {
  status: IngestionSummary["status"];
  ready_for_alignment: boolean;
  lanes: Record<SampleLane, IngestionLaneSummaryDto>;
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

type UploadSessionPartDto = {
  uploaded_bytes: number;
  total_parts: number;
  completed_part_numbers: number[];
};

type UploadSessionFileDto = {
  id: string;
  sample_lane: SampleLane;
  filename: string;
  format: UploadSessionFile["format"];
  read_pair: UploadSessionFile["readPair"];
  size_bytes: number;
  uploaded_bytes: number;
  total_parts: number;
  last_modified_ms: number;
  fingerprint: string;
  content_type?: string | null;
  status: UploadSessionFile["status"];
  error?: string | null;
  completed_part_numbers: number[];
};

type UploadSessionDto = {
  id: string;
  sample_lane: SampleLane;
  status: UploadSession["status"];
  chunk_size_bytes: number;
  error?: string | null;
  files: UploadSessionFileDto[];
  created_at: string;
  updated_at: string;
};

type FastqReadPreviewDto = {
  header: string;
  sequence: string;
  quality: string;
  length: number;
  gc_percent: number;
  mean_quality: number;
};

type SampledReadStatsDto = {
  sampled_read_count: number;
  average_read_length: number;
  sampled_gc_percent: number;
};

type IngestionLanePreviewDto = {
  workspace_id: string;
  sample_lane: SampleLane;
  batch_id: string;
  source: "canonical-fastq";
  read_layout: IngestionLanePreview["readLayout"];
  reads: Partial<
    Record<Extract<ReadPair, "R1" | "R2" | "SE">, FastqReadPreviewDto[]>
  >;
  stats: SampledReadStatsDto;
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
    sampleLane: dto.sample_lane,
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

function mapIngestionLaneSummary(dto: IngestionLaneSummaryDto): IngestionLaneSummary {
  return {
    activeBatchId: dto.active_batch_id,
    sampleLane: dto.sample_lane,
    status: dto.status,
    readyForAlignment: dto.ready_for_alignment,
    sourceFileCount: dto.source_file_count,
    canonicalFileCount: dto.canonical_file_count,
    missingPairs: dto.missing_pairs,
    blockingIssues: dto.blocking_issues,
    readLayout: dto.read_layout ?? null,
    updatedAt: dto.updated_at,
  };
}

function mapIngestionSummary(dto: IngestionSummaryDto): IngestionSummary {
  return {
    status: dto.status,
    readyForAlignment: dto.ready_for_alignment,
    lanes: {
      tumor: mapIngestionLaneSummary(dto.lanes.tumor),
      normal: mapIngestionLaneSummary(dto.lanes.normal),
    },
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

function mapUploadPartResult(dto: UploadSessionPartDto): UploadPartResult {
  return {
    uploadedBytes: dto.uploaded_bytes,
    totalParts: dto.total_parts,
    completedPartNumbers: dto.completed_part_numbers,
  };
}

function mapUploadSessionFile(dto: UploadSessionFileDto): UploadSessionFile {
  return {
    id: dto.id,
    sampleLane: dto.sample_lane,
    filename: dto.filename,
    format: dto.format,
    readPair: dto.read_pair,
    sizeBytes: dto.size_bytes,
    uploadedBytes: dto.uploaded_bytes,
    totalParts: dto.total_parts,
    lastModifiedMs: dto.last_modified_ms,
    fingerprint: dto.fingerprint,
    contentType: dto.content_type,
    status: dto.status,
    error: dto.error,
    completedPartNumbers: dto.completed_part_numbers,
  };
}

function mapUploadSession(dto: UploadSessionDto): UploadSession {
  return {
    id: dto.id,
    sampleLane: dto.sample_lane,
    status: dto.status,
    chunkSizeBytes: dto.chunk_size_bytes,
    error: dto.error,
    files: dto.files.map(mapUploadSessionFile),
    createdAt: dto.created_at,
    updatedAt: dto.updated_at,
  };
}

function mapFastqReadPreview(dto: FastqReadPreviewDto): FastqReadPreview {
  return {
    header: dto.header,
    sequence: dto.sequence,
    quality: dto.quality,
    length: dto.length,
    gcPercent: dto.gc_percent,
    meanQuality: dto.mean_quality,
  };
}

function mapSampledReadStats(dto: SampledReadStatsDto): SampledReadStats {
  return {
    sampledReadCount: dto.sampled_read_count,
    averageReadLength: dto.average_read_length,
    sampledGcPercent: dto.sampled_gc_percent,
  };
}

function mapIngestionLanePreview(
  dto: IngestionLanePreviewDto
): IngestionLanePreview {
  const reads: IngestionLanePreview["reads"] = {};
  if (dto.reads.R1) {
    reads.R1 = dto.reads.R1.map(mapFastqReadPreview);
  }
  if (dto.reads.R2) {
    reads.R2 = dto.reads.R2.map(mapFastqReadPreview);
  }
  if (dto.reads.SE) {
    reads.SE = dto.reads.SE.map(mapFastqReadPreview);
  }
  return {
    workspaceId: dto.workspace_id,
    sampleLane: dto.sample_lane,
    batchId: dto.batch_id,
    source: dto.source,
    readLayout: dto.read_layout,
    reads,
    stats: mapSampledReadStats(dto.stats),
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

  if (!isFormData && !headers.has("Content-Type") && options?.body) {
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

  if (res.status === 204) {
    return undefined as T;
  }

  return res.json();
}

function uploadBinaryWithProgress(
  path: string,
  body: Blob,
  {
    onProgress,
    signal,
  }: {
    onProgress?: (loaded: number, total: number) => void;
    signal?: AbortSignal;
  } = {}
): Promise<UploadPartResult> {
  if (typeof XMLHttpRequest === "undefined") {
    throw new Error("Chunk uploads are only supported in the browser");
  }

  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();

    const cleanup = () => {
      if (signal) {
        signal.removeEventListener("abort", handleAbort);
      }
    };

    const handleAbort = () => {
      xhr.abort();
      cleanup();
      reject(new DOMException("Upload aborted", "AbortError"));
    };

    xhr.open("PUT", `${API_BASE}${path}`);
    xhr.responseType = "json";
    xhr.setRequestHeader("Content-Type", "application/octet-stream");

    xhr.upload.onprogress = (event) => {
      if (!event.lengthComputable) {
        onProgress?.(event.loaded, body.size);
        return;
      }
      onProgress?.(event.loaded, event.total);
    };

    xhr.onerror = () => {
      cleanup();
      reject(new Error("Chunk upload failed"));
    };

    xhr.onabort = () => {
      cleanup();
      reject(new DOMException("Upload aborted", "AbortError"));
    };

    xhr.onload = () => {
      cleanup();
      if (xhr.status < 200 || xhr.status >= 300) {
        const detail =
          typeof xhr.response === "object" && xhr.response?.detail
            ? String(xhr.response.detail)
            : xhr.responseText || `API error: ${xhr.status}`;
        reject(new Error(detail));
        return;
      }

      resolve(mapUploadPartResult(xhr.response as UploadSessionPartDto));
    };

    if (signal) {
      if (signal.aborted) {
        handleAbort();
        return;
      }
      signal.addEventListener("abort", handleAbort, { once: true });
    }

    xhr.send(body);
  });
}

export const api = {
  health: () => request<{ status: string }>("/health"),

  listWorkspaces: async () =>
    (await request<WorkspaceDto[]>("/api/workspaces")).map(mapWorkspace),
  getWorkspace: async (workspaceId: string) =>
    mapWorkspace(await request<WorkspaceDto>(`/api/workspaces/${workspaceId}`)),
  getIngestionLanePreview: async (
    workspaceId: string,
    sampleLane: SampleLane
  ) =>
    mapIngestionLanePreview(
      await request<IngestionLanePreviewDto>(
        `/api/workspaces/${workspaceId}/ingestion/preview/${sampleLane}`
      )
    ),
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
  listUploadSessions: async (workspaceId: string) =>
    (
      await request<UploadSessionDto[]>(
        `/api/workspaces/${workspaceId}/ingestion/sessions`
      )
    ).map(mapUploadSession),
  createUploadSession: async (
    workspaceId: string,
    input: UploadSessionCreateInput
  ) =>
    mapUploadSession(
      await request<UploadSessionDto>(
        `/api/workspaces/${workspaceId}/ingestion/sessions`,
        {
          method: "POST",
          body: JSON.stringify({
            sample_lane: input.sampleLane,
            files: input.files.map((file) => ({
              filename: file.filename,
              size_bytes: file.sizeBytes,
              last_modified_ms: file.lastModifiedMs,
              content_type: file.contentType,
            })),
          }),
        }
      )
    ),
  uploadUploadSessionPart: (
    workspaceId: string,
    sessionId: string,
    fileId: string,
    partNumber: number,
    body: Blob,
    options?: {
      onProgress?: (loaded: number, total: number) => void;
      signal?: AbortSignal;
    }
  ) =>
    uploadBinaryWithProgress(
      `/api/workspaces/${workspaceId}/ingestion/sessions/${sessionId}/files/${fileId}/parts/${partNumber}`,
      body,
      options
    ),
  completeUploadSessionFile: async (
    workspaceId: string,
    sessionId: string,
    fileId: string
  ) =>
    mapUploadSessionFile(
      await request<UploadSessionFileDto>(
        `/api/workspaces/${workspaceId}/ingestion/sessions/${sessionId}/files/${fileId}/complete`,
        { method: "POST" }
      )
    ),
  commitUploadSession: async (workspaceId: string, sessionId: string) =>
    mapWorkspace(
      await request<WorkspaceDto>(
        `/api/workspaces/${workspaceId}/ingestion/sessions/${sessionId}/commit`,
        { method: "POST" }
      )
    ),
  deleteUploadSession: async (workspaceId: string, sessionId: string) =>
    mapWorkspace(
      await request<WorkspaceDto>(
        `/api/workspaces/${workspaceId}/ingestion/sessions/${sessionId}`,
        { method: "DELETE" }
      )
    ),
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
