import type {
  AlignmentArtifact,
  AlignmentLaneMetrics,
  AlignmentRuntimePhase,
  AlignmentSettings,
  AlignmentSettingsPatch,
  AlignmentStageSummary,
  AlignmentRun,
  AnalysisProfile,
  AssayType,
  ChunkProgressPhase,
  ChunkProgressState,
  CreateWorkspaceInput,
  FastqReadPreview,
  IngestionLaneSummary,
  IngestionLanePreview,
  IngestionLaneProgress,
  IngestionSummary,
  LocalFileRegistrationInput,
  PipelineStageId,
  ReadPair,
  SampledReadStats,
  SystemMemoryResponse,
  SystemResourcesResponse,
  Workspace,
  WorkspaceFile,
  ReferencePreset,
  SampleLane,
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
  source_path?: string | null;
  managed_path?: string | null;
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
  progress?: IngestionLaneProgressDto | null;
};

type IngestionLaneProgressDto = {
  phase: IngestionLaneProgress["phase"];
  current_filename?: string | null;
  bytes_processed?: number | null;
  total_bytes?: number | null;
  throughput_bytes_per_sec?: number | null;
  eta_seconds?: number | null;
  percent?: number | null;
};

type IngestionSummaryDto = {
  status: IngestionSummary["status"];
  ready_for_alignment: boolean;
  lanes: Record<SampleLane, IngestionLaneSummaryDto>;
};

type AnalysisProfileDto = {
  assay_type?: AssayType | null;
  reference_preset?: ReferencePreset | null;
  reference_override?: string | null;
};

type WorkspaceDto = {
  id: string;
  display_name: string;
  species: WorkspaceSpecies;
  analysis_profile: AnalysisProfileDto;
  active_stage: PipelineStageId;
  ingestion: IngestionSummaryDto;
  files: WorkspaceFileDto[];
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

type AlignmentLaneMetricsDto = {
  sample_lane: SampleLane;
  total_reads: number;
  mapped_reads: number;
  mapped_percent: number;
  properly_paired_percent?: number | null;
  duplicate_percent?: number | null;
  mean_insert_size?: number | null;
};

type AlignmentArtifactDto = {
  id: string;
  artifact_kind: AlignmentArtifact["artifactKind"];
  sample_lane?: SampleLane | null;
  filename: string;
  size_bytes: number;
  download_path: string;
  local_path?: string | null;
};

type ChunkProgressStateDto = {
  phase: ChunkProgressPhase;
  total_chunks: number;
  completed_chunks: number;
  active_chunks: number;
};

type AlignmentRunDto = {
  id: string;
  status: AlignmentRun["status"];
  progress: number;
  assay_type?: AssayType | null;
  reference_preset?: ReferencePreset | null;
  reference_override?: string | null;
  reference_label?: string | null;
  runtime_phase?: AlignmentRuntimePhase | null;
  qc_verdict?: AlignmentStageSummary["qcVerdict"];
  created_at: string;
  updated_at: string;
  started_at?: string | null;
  completed_at?: string | null;
  blocking_reason?: string | null;
  error?: string | null;
  command_log: string[];
  lane_metrics: Partial<Record<SampleLane, AlignmentLaneMetricsDto>>;
  chunk_progress?: Partial<Record<SampleLane, ChunkProgressStateDto>>;
  artifacts: AlignmentArtifactDto[];
};

type AlignmentStageSummaryDto = {
  workspace_id: string;
  status: AlignmentStageSummary["status"];
  blocking_reason?: string | null;
  analysis_profile: AnalysisProfileDto;
  qc_verdict?: AlignmentStageSummary["qcVerdict"];
  ready_for_variant_calling: boolean;
  latest_run?: AlignmentRunDto | null;
  lane_metrics: Record<SampleLane, AlignmentLaneMetricsDto | null>;
  artifacts: AlignmentArtifactDto[];
};

type SystemMemoryDto = {
  available_bytes: number | null;
  total_bytes: number | null;
  threshold_bytes: number;
};

type SystemResourcesDto = {
  cpu_count: number;
  total_memory_bytes: number | null;
  available_memory_bytes: number | null;
  app_data_disk_total_bytes: number | null;
  app_data_disk_free_bytes: number | null;
  app_data_root: string;
};

type AlignmentSettingsDto = {
  aligner_threads: number;
  samtools_threads: number;
  samtools_sort_threads: number;
  samtools_sort_memory: string;
  chunk_reads: number;
  chunk_parallelism: number;
  defaults: {
    aligner_threads: number;
    samtools_threads: number;
    samtools_sort_threads: number;
    samtools_sort_memory: string;
    chunk_reads: number;
    chunk_parallelism: number;
  };
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
    sourcePath: dto.source_path,
    managedPath: dto.managed_path,
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
    progress: dto.progress
      ? {
          phase: dto.progress.phase,
          currentFilename: dto.progress.current_filename ?? null,
          bytesProcessed: dto.progress.bytes_processed ?? null,
          totalBytes: dto.progress.total_bytes ?? null,
          throughputBytesPerSec: dto.progress.throughput_bytes_per_sec ?? null,
          etaSeconds: dto.progress.eta_seconds ?? null,
          percent: dto.progress.percent ?? null,
        }
      : null,
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

function mapAnalysisProfile(dto: AnalysisProfileDto): AnalysisProfile {
  return {
    assayType: dto.assay_type ?? null,
    referencePreset: dto.reference_preset ?? null,
    referenceOverride: dto.reference_override ?? null,
  };
}

function mapWorkspace(dto: WorkspaceDto): Workspace {
  return {
    id: dto.id,
    displayName: dto.display_name,
    species: dto.species,
    analysisProfile: mapAnalysisProfile(dto.analysis_profile),
    activeStage: dto.active_stage,
    ingestion: mapIngestionSummary(dto.ingestion),
    files: dto.files.map(mapWorkspaceFile),
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

function mapAlignmentLaneMetrics(
  dto: AlignmentLaneMetricsDto
): AlignmentLaneMetrics {
  return {
    sampleLane: dto.sample_lane,
    totalReads: dto.total_reads,
    mappedReads: dto.mapped_reads,
    mappedPercent: dto.mapped_percent,
    properlyPairedPercent: dto.properly_paired_percent ?? null,
    duplicatePercent: dto.duplicate_percent ?? null,
    meanInsertSize: dto.mean_insert_size ?? null,
  };
}

function mapAlignmentArtifact(dto: AlignmentArtifactDto): AlignmentArtifact {
  return {
    id: dto.id,
    artifactKind: dto.artifact_kind,
    sampleLane: dto.sample_lane ?? null,
    filename: dto.filename,
    sizeBytes: dto.size_bytes,
    downloadPath: dto.download_path,
    localPath: dto.local_path ?? null,
  };
}

function mapChunkProgressState(dto: ChunkProgressStateDto): ChunkProgressState {
  return {
    phase: dto.phase,
    totalChunks: dto.total_chunks,
    completedChunks: dto.completed_chunks,
    activeChunks: dto.active_chunks,
  };
}

function mapAlignmentRun(dto: AlignmentRunDto): AlignmentRun {
  const laneMetrics: AlignmentRun["laneMetrics"] = {};
  if (dto.lane_metrics.tumor) {
    laneMetrics.tumor = mapAlignmentLaneMetrics(dto.lane_metrics.tumor);
  }
  if (dto.lane_metrics.normal) {
    laneMetrics.normal = mapAlignmentLaneMetrics(dto.lane_metrics.normal);
  }
  const chunkProgress: AlignmentRun["chunkProgress"] = {};
  if (dto.chunk_progress?.tumor) {
    chunkProgress.tumor = mapChunkProgressState(dto.chunk_progress.tumor);
  }
  if (dto.chunk_progress?.normal) {
    chunkProgress.normal = mapChunkProgressState(dto.chunk_progress.normal);
  }
  return {
    id: dto.id,
    status: dto.status,
    progress: dto.progress,
    assayType: dto.assay_type ?? null,
    referencePreset: dto.reference_preset ?? null,
    referenceOverride: dto.reference_override ?? null,
    referenceLabel: dto.reference_label ?? null,
    runtimePhase: dto.runtime_phase ?? null,
    qcVerdict: dto.qc_verdict ?? null,
    createdAt: dto.created_at,
    updatedAt: dto.updated_at,
    startedAt: dto.started_at ?? null,
    completedAt: dto.completed_at ?? null,
    blockingReason: dto.blocking_reason ?? null,
    error: dto.error ?? null,
    commandLog: dto.command_log,
    laneMetrics,
    chunkProgress,
    artifacts: dto.artifacts.map(mapAlignmentArtifact),
  };
}

function mapAlignmentSettings(dto: AlignmentSettingsDto): AlignmentSettings {
  return {
    alignerThreads: dto.aligner_threads,
    samtoolsThreads: dto.samtools_threads,
    samtoolsSortThreads: dto.samtools_sort_threads,
    samtoolsSortMemory: dto.samtools_sort_memory,
    chunkReads: dto.chunk_reads,
    chunkParallelism: dto.chunk_parallelism,
    defaults: {
      alignerThreads: dto.defaults.aligner_threads,
      samtoolsThreads: dto.defaults.samtools_threads,
      samtoolsSortThreads: dto.defaults.samtools_sort_threads,
      samtoolsSortMemory: dto.defaults.samtools_sort_memory,
      chunkReads: dto.defaults.chunk_reads,
      chunkParallelism: dto.defaults.chunk_parallelism,
    },
  };
}

function mapAlignmentStageSummary(
  dto: AlignmentStageSummaryDto
): AlignmentStageSummary {
  return {
    workspaceId: dto.workspace_id,
    status: dto.status,
    blockingReason: dto.blocking_reason ?? null,
    analysisProfile: mapAnalysisProfile(dto.analysis_profile),
    qcVerdict: dto.qc_verdict ?? null,
    readyForVariantCalling: dto.ready_for_variant_calling,
    latestRun: dto.latest_run ? mapAlignmentRun(dto.latest_run) : null,
    laneMetrics: {
      tumor: dto.lane_metrics.tumor
        ? mapAlignmentLaneMetrics(dto.lane_metrics.tumor)
        : null,
      normal: dto.lane_metrics.normal
        ? mapAlignmentLaneMetrics(dto.lane_metrics.normal)
        : null,
    },
    artifacts: dto.artifacts.map(mapAlignmentArtifact),
  };
}

export class MissingToolsError extends Error {
  readonly tools: string[];
  readonly hints: string[];

  constructor(message: string, tools: string[], hints: string[]) {
    super(message);
    this.name = "MissingToolsError";
    this.tools = tools;
    this.hints = hints;
  }
}

export class InsufficientMemoryError extends Error {
  readonly requiredBytes: number;
  readonly availableBytes: number | null;
  readonly purpose: string;

  constructor(
    message: string,
    requiredBytes: number,
    availableBytes: number | null,
    purpose: string
  ) {
    super(message);
    this.name = "InsufficientMemoryError";
    this.requiredBytes = requiredBytes;
    this.availableBytes = availableBytes;
    this.purpose = purpose;
  }
}

type MissingToolsDetail = {
  code: "missing_tools";
  tools: string[];
  hints: string[];
  message: string;
};

type InsufficientMemoryDetail = {
  code: "insufficient_memory";
  required_bytes: number;
  available_bytes: number | null;
  purpose: string;
  message: string;
};

function parseMissingToolsDetail(payload: string): MissingToolsDetail | null {
  try {
    const parsed = JSON.parse(payload) as { detail?: unknown };
    const detail = parsed.detail;
    if (
      detail &&
      typeof detail === "object" &&
      (detail as { code?: unknown }).code === "missing_tools"
    ) {
      const typed = detail as Partial<MissingToolsDetail>;
      return {
        code: "missing_tools",
        tools: Array.isArray(typed.tools) ? typed.tools.map(String) : [],
        hints: Array.isArray(typed.hints) ? typed.hints.map(String) : [],
        message: typeof typed.message === "string" ? typed.message : "Required tools are missing.",
      };
    }
  } catch {}
  return null;
}

function parseInsufficientMemoryDetail(
  payload: string
): InsufficientMemoryDetail | null {
  try {
    const parsed = JSON.parse(payload) as { detail?: unknown };
    const detail = parsed.detail;
    if (
      detail &&
      typeof detail === "object" &&
      (detail as { code?: unknown }).code === "insufficient_memory"
    ) {
      const typed = detail as Partial<InsufficientMemoryDetail>;
      return {
        code: "insufficient_memory",
        required_bytes:
          typeof typed.required_bytes === "number" ? typed.required_bytes : 0,
        available_bytes:
          typeof typed.available_bytes === "number" ? typed.available_bytes : null,
        purpose:
          typeof typed.purpose === "string" ? typed.purpose : "A pipeline step",
        message:
          typeof typed.message === "string"
            ? typed.message
            : "Not enough free memory to run this step.",
      };
    }
  } catch {}
  return null;
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

    if (res.status === 503) {
      const missing = parseMissingToolsDetail(payload);
      if (missing) {
        throw new MissingToolsError(missing.message, missing.tools, missing.hints);
      }
      const memory = parseInsufficientMemoryDetail(payload);
      if (memory) {
        throw new InsufficientMemoryError(
          memory.message,
          memory.required_bytes,
          memory.available_bytes,
          memory.purpose
        );
      }
    }

    let detail: string | undefined;
    try {
      detail = (JSON.parse(payload) as { detail?: unknown }).detail as
        | string
        | undefined;
    } catch {}

    throw new Error(
      (typeof detail === "string" ? detail : payload) || `API error: ${res.status}`
    );
  }

  if (res.status === 204) {
    return undefined as T;
  }

  return res.json();
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
  registerLocalLaneFiles: async (
    workspaceId: string,
    input: LocalFileRegistrationInput
  ) =>
    mapWorkspace(
      await request<WorkspaceDto>(
        `/api/workspaces/${workspaceId}/ingestion/local-files`,
        {
          method: "POST",
          body: JSON.stringify({
            sample_lane: input.sampleLane,
            paths: input.paths,
          }),
        }
      )
    ),
  resetWorkspaceIngestion: async (workspaceId: string) =>
    mapWorkspace(
      await request<WorkspaceDto>(`/api/workspaces/${workspaceId}/ingestion`, {
        method: "DELETE",
      })
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
  updateWorkspaceAnalysisProfile: async (
    workspaceId: string,
    profile: AnalysisProfile
  ) =>
    mapWorkspace(
      await request<WorkspaceDto>(
        `/api/workspaces/${workspaceId}/analysis-profile`,
        {
          method: "PATCH",
          body: JSON.stringify({
            assay_type: profile.assayType,
            reference_preset: profile.referencePreset,
            reference_override: profile.referenceOverride,
          }),
        }
      )
    ),
  getAlignmentStageSummary: async (workspaceId: string) =>
    mapAlignmentStageSummary(
      await request<AlignmentStageSummaryDto>(
        `/api/workspaces/${workspaceId}/alignment`
      )
    ),
  runAlignment: async (workspaceId: string) =>
    mapAlignmentStageSummary(
      await request<AlignmentStageSummaryDto>(
        `/api/workspaces/${workspaceId}/alignment/run`,
        { method: "POST" }
      )
    ),
  rerunAlignment: async (workspaceId: string) =>
    mapAlignmentStageSummary(
      await request<AlignmentStageSummaryDto>(
        `/api/workspaces/${workspaceId}/alignment/rerun`,
        { method: "POST" }
      )
    ),
  getSystemMemory: async (): Promise<SystemMemoryResponse> => {
    const dto = await request<SystemMemoryDto>("/api/system/memory");
    return {
      availableBytes: dto.available_bytes,
      totalBytes: dto.total_bytes,
      thresholdBytes: dto.threshold_bytes,
    };
  },
  getSystemResources: async (): Promise<SystemResourcesResponse> => {
    const dto = await request<SystemResourcesDto>("/api/system/resources");
    return {
      cpuCount: dto.cpu_count,
      totalMemoryBytes: dto.total_memory_bytes,
      availableMemoryBytes: dto.available_memory_bytes,
      appDataDiskTotalBytes: dto.app_data_disk_total_bytes,
      appDataDiskFreeBytes: dto.app_data_disk_free_bytes,
      appDataRoot: dto.app_data_root,
    };
  },
  getAlignmentSettings: async (): Promise<AlignmentSettings> => {
    const dto = await request<AlignmentSettingsDto>("/api/settings/alignment");
    return mapAlignmentSettings(dto);
  },
  updateAlignmentSettings: async (
    patch: AlignmentSettingsPatch
  ): Promise<AlignmentSettings> => {
    const body: Record<string, unknown> = {};
    if (patch.reset) body.reset = true;
    if (patch.alignerThreads !== undefined) body.aligner_threads = patch.alignerThreads;
    if (patch.samtoolsThreads !== undefined) body.samtools_threads = patch.samtoolsThreads;
    if (patch.samtoolsSortThreads !== undefined)
      body.samtools_sort_threads = patch.samtoolsSortThreads;
    if (patch.samtoolsSortMemory !== undefined)
      body.samtools_sort_memory = patch.samtoolsSortMemory;
    if (patch.chunkReads !== undefined) body.chunk_reads = patch.chunkReads;
    if (patch.chunkParallelism !== undefined)
      body.chunk_parallelism = patch.chunkParallelism;
    const dto = await request<AlignmentSettingsDto>("/api/settings/alignment", {
      method: "PATCH",
      body: JSON.stringify(body),
    });
    return mapAlignmentSettings(dto);
  },
  resolveDownloadUrl: (downloadPath: string) => `${PUBLIC_API_BASE}${downloadPath}`,
};
