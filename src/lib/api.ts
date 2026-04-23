import type {
  AlignmentArtifact,
  AlignmentLaneMetrics,
  AlignmentRuntimePhase,
  AlignmentSettings,
  AlignmentSettingsPatch,
  AlignmentStageSummary,
  AlignmentRun,
  AnalysisProfile,
  AnnotatedVariantEntry,
  AnnotationArtifact,
  AnnotationArtifactKind,
  AnnotationImpactTier,
  AnnotationMetrics,
  AnnotationRun,
  AnnotationRunStatus,
  AnnotationRuntimePhase,
  AnnotationStageStatus,
  AnnotationStageSummary,
  CancerGeneHit,
  ChunkProgressPhase,
  ChunkProgressState,
  CreateWorkspaceInput,
  FastqReadPreview,
  GeneDomainsResponse,
  GeneFocus,
  GeneFocusVariant,
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
  VariantCallingArtifact,
  VariantCallingArtifactKind,
  VariantCallingRun,
  VariantCallingRunStatus,
  VariantCallingRuntimePhase,
  VariantCallingStageStatus,
  VariantCallingStageSummary,
  Workspace,
  WorkspaceFile,
  ReferencePreset,
  SampleLane,
  WorkspaceSpecies,
  NeoantigenArtifact,
  NeoantigenArtifactKind,
  NeoantigenMetrics,
  NeoantigenRun,
  NeoantigenRunStatus,
  NeoantigenRuntimePhase,
  NeoantigenStageStatus,
  NeoantigenStageSummary,
  EpitopeAllele,
  EpitopeCandidate,
  EpitopeSafetyFlag,
  EpitopeStageStatus,
  EpitopeStageSummary,
  ConstructDesignStatus,
  ConstructFlanks,
  ConstructManufacturingCheck,
  ConstructMetrics,
  ConstructPreview,
  ConstructPreviewCodon,
  ConstructSegment,
  ConstructSegmentKind,
  ConstructStageSummary,
  ConstructOutputRun,
  ConstructOutputStageSummary,
  ConstructOutputStatus,
  ConstructRunKind,
  CmoOption,
  DosingScheduleItem,
  AuditEntry,
  PatientAllele,
  BindingBucket,
  BindingTier,
  HeatmapData,
  HeatmapRow,
  FunnelStep,
  TopCandidate,
  MhcClass,
  AlleleTypingKind,
} from "@/lib/types";

// Browser default: same-origin `/backend/*` proxied to the FastAPI container
// by the Next.js rewrite in next.config.ts. Self-hosters only expose port 3000.
// SSR default: direct hop to the backend over the Docker network.
// Host-mode dev (native uvicorn + `next dev`): set NEXT_PUBLIC_API_URL=http://localhost:8000.
const PUBLIC_API_BASE =
  process.env.NEXT_PUBLIC_API_URL ?? "/backend";
const API_BASE =
  typeof window === "undefined"
    ? process.env.INTERNAL_API_URL ?? "http://backend:8000"
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
  recent_log_tail?: string[] | null;
  last_activity_at?: string | null;
  eta_seconds?: number | null;
  progress_components?: Partial<
    Record<"reference_prep" | "aligning" | "finalizing" | "stats", number>
  > | null;
  expected_total_per_lane?: Partial<Record<SampleLane, number>> | null;
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

type ChromosomeMetricsDto = {
  chromosome: string;
  length: number;
  total: number;
  pass_count: number;
  snv_count: number;
  indel_count: number;
};

type FilterBreakdownDto = {
  name: string;
  count: number;
  is_pass: boolean;
};

type VafHistogramBinDto = {
  bin_start: number;
  bin_end: number;
  count: number;
};

type TopVariantEntryDto = {
  chromosome: string;
  position: number;
  ref: string;
  alt: string;
  variant_type: "snv" | "insertion" | "deletion" | "mnv";
  filter: string;
  is_pass: boolean;
  tumor_vaf?: number | null;
  tumor_depth?: number | null;
  normal_depth?: number | null;
};

type VariantCallingMetricsDto = {
  total_variants: number;
  snv_count: number;
  indel_count: number;
  insertion_count: number;
  deletion_count: number;
  mnv_count: number;
  pass_count: number;
  pass_snv_count: number;
  pass_indel_count: number;
  ti_tv_ratio?: number | null;
  transitions: number;
  transversions: number;
  mean_vaf?: number | null;
  median_vaf?: number | null;
  tumor_mean_depth?: number | null;
  normal_mean_depth?: number | null;
  tumor_sample?: string | null;
  normal_sample?: string | null;
  reference_label?: string | null;
  pon_label?: string | null;
  per_chromosome: ChromosomeMetricsDto[];
  filter_breakdown: FilterBreakdownDto[];
  vaf_histogram: VafHistogramBinDto[];
  top_variants: TopVariantEntryDto[];
};

type VariantCallingArtifactDto = {
  id: string;
  artifact_kind: VariantCallingArtifactKind;
  filename: string;
  size_bytes: number;
  download_path: string;
  local_path?: string | null;
};

type VariantCallingRunDto = {
  id: string;
  status: VariantCallingRunStatus;
  progress: number;
  runtime_phase?: VariantCallingRuntimePhase | null;
  created_at: string;
  updated_at: string;
  started_at?: string | null;
  completed_at?: string | null;
  blocking_reason?: string | null;
  error?: string | null;
  command_log: string[];
  metrics?: VariantCallingMetricsDto | null;
  artifacts: VariantCallingArtifactDto[];
  completed_shards?: number;
  total_shards?: number;
  acceleration_mode?: "gpu_parabricks" | "cpu_gatk";
};

type VariantCallingStageSummaryDto = {
  workspace_id: string;
  status: VariantCallingStageStatus;
  blocking_reason?: string | null;
  ready_for_annotation: boolean;
  latest_run?: VariantCallingRunDto | null;
  artifacts: VariantCallingArtifactDto[];
};

type GeneFocusVariantDto = {
  chromosome: string;
  position: number;
  protein_position?: number | null;
  hgvsp?: string | null;
  hgvsc?: string | null;
  consequence: string;
  impact: AnnotationImpactTier;
  tumor_vaf?: number | null;
};

type CancerGeneHitDto = {
  symbol: string;
  role: string;
  variant_count: number;
  highest_impact: AnnotationImpactTier;
  top_hgvsp?: string | null;
  top_consequence?: string | null;
  transcript_id?: string | null;
  protein_length?: number | null;
  variants?: GeneFocusVariantDto[];
};

type ProteinDomainDto = {
  start: number;
  end: number;
  label: string;
  kind?: "catalytic" | "neutral" | null;
};

type GeneFocusDto = {
  symbol: string;
  role?: string | null;
  transcript_id?: string | null;
  protein_length?: number | null;
  variants: GeneFocusVariantDto[];
  domains?: ProteinDomainDto[] | null;
};

type GeneDomainsDto = {
  symbol: string;
  transcript_id?: string | null;
  protein_length?: number | null;
  domains: ProteinDomainDto[];
};

type AnnotatedVariantEntryDto = {
  chromosome: string;
  position: number;
  ref: string;
  alt: string;
  gene_symbol?: string | null;
  transcript_id?: string | null;
  consequence: string;
  consequence_label: string;
  impact: AnnotationImpactTier;
  hgvsc?: string | null;
  hgvsp?: string | null;
  protein_position?: number | null;
  tumor_vaf?: number | null;
  in_cancer_gene?: boolean;
};

type AnnotationConsequenceEntryDto = {
  term: string;
  label: string;
  count: number;
};

type AnnotationMetricsDto = {
  total_variants: number;
  annotated_variants: number;
  by_impact: Record<string, number>;
  by_consequence: AnnotationConsequenceEntryDto[];
  cancer_gene_hits: CancerGeneHitDto[];
  cancer_gene_variant_count: number;
  top_gene_focus?: GeneFocusDto | null;
  top_variants: AnnotatedVariantEntryDto[];
  reference_label?: string | null;
  species_label?: string | null;
  vep_release?: string | null;
};

type AnnotationArtifactDto = {
  id: string;
  artifact_kind: AnnotationArtifactKind;
  filename: string;
  size_bytes: number;
  download_path: string;
  local_path?: string | null;
};

type AnnotationRunDto = {
  id: string;
  status: AnnotationRunStatus;
  progress: number;
  runtime_phase?: AnnotationRuntimePhase | null;
  created_at: string;
  updated_at: string;
  started_at?: string | null;
  completed_at?: string | null;
  blocking_reason?: string | null;
  error?: string | null;
  command_log: string[];
  metrics?: AnnotationMetricsDto | null;
  artifacts: AnnotationArtifactDto[];
  cache_pending?: boolean;
  cache_species_label?: string | null;
  cache_expected_megabytes?: number | null;
};

type AnnotationStageSummaryDto = {
  workspace_id: string;
  status: AnnotationStageStatus;
  blocking_reason?: string | null;
  ready_for_neoantigen: boolean;
  latest_run?: AnnotationRunDto | null;
  artifacts: AnnotationArtifactDto[];
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
  const components = dto.progress_components ?? {};
  const progressComponents = {
    referencePrep: components.reference_prep ?? 0,
    aligning: components.aligning ?? 0,
    finalizing: components.finalizing ?? 0,
    stats: components.stats ?? 0,
  };
  const expectedTotalPerLane: AlignmentRun["expectedTotalPerLane"] = {};
  if (dto.expected_total_per_lane?.tumor != null) {
    expectedTotalPerLane.tumor = dto.expected_total_per_lane.tumor;
  }
  if (dto.expected_total_per_lane?.normal != null) {
    expectedTotalPerLane.normal = dto.expected_total_per_lane.normal;
  }
  return {
    id: dto.id,
    status: dto.status,
    progress: dto.progress,
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
    recentLogTail: dto.recent_log_tail ?? [],
    lastActivityAt: dto.last_activity_at ?? null,
    etaSeconds: dto.eta_seconds ?? null,
    progressComponents,
    expectedTotalPerLane,
    laneMetrics,
    chunkProgress,
    artifacts: dto.artifacts.map(mapAlignmentArtifact),
  };
}

function mapVariantCallingArtifact(
  dto: VariantCallingArtifactDto
): VariantCallingArtifact {
  return {
    id: dto.id,
    artifactKind: dto.artifact_kind,
    filename: dto.filename,
    sizeBytes: dto.size_bytes,
    downloadPath: dto.download_path,
    localPath: dto.local_path ?? null,
  };
}

function mapVariantCallingRun(dto: VariantCallingRunDto): VariantCallingRun {
  return {
    id: dto.id,
    status: dto.status,
    progress: dto.progress,
    runtimePhase: dto.runtime_phase ?? null,
    createdAt: dto.created_at,
    updatedAt: dto.updated_at,
    startedAt: dto.started_at ?? null,
    completedAt: dto.completed_at ?? null,
    blockingReason: dto.blocking_reason ?? null,
    error: dto.error ?? null,
    commandLog: dto.command_log,
    metrics: dto.metrics
      ? {
          totalVariants: dto.metrics.total_variants,
          snvCount: dto.metrics.snv_count,
          indelCount: dto.metrics.indel_count,
          insertionCount: dto.metrics.insertion_count,
          deletionCount: dto.metrics.deletion_count,
          mnvCount: dto.metrics.mnv_count,
          passCount: dto.metrics.pass_count,
          passSnvCount: dto.metrics.pass_snv_count,
          passIndelCount: dto.metrics.pass_indel_count,
          tiTvRatio: dto.metrics.ti_tv_ratio ?? null,
          transitions: dto.metrics.transitions,
          transversions: dto.metrics.transversions,
          meanVaf: dto.metrics.mean_vaf ?? null,
          medianVaf: dto.metrics.median_vaf ?? null,
          tumorMeanDepth: dto.metrics.tumor_mean_depth ?? null,
          normalMeanDepth: dto.metrics.normal_mean_depth ?? null,
          tumorSample: dto.metrics.tumor_sample ?? null,
          normalSample: dto.metrics.normal_sample ?? null,
          referenceLabel: dto.metrics.reference_label ?? null,
          ponLabel: dto.metrics.pon_label ?? null,
          perChromosome: dto.metrics.per_chromosome.map((entry) => ({
            chromosome: entry.chromosome,
            length: entry.length,
            total: entry.total,
            passCount: entry.pass_count,
            snvCount: entry.snv_count,
            indelCount: entry.indel_count,
          })),
          filterBreakdown: dto.metrics.filter_breakdown.map((entry) => ({
            name: entry.name,
            count: entry.count,
            isPass: entry.is_pass,
          })),
          vafHistogram: dto.metrics.vaf_histogram.map((bin) => ({
            binStart: bin.bin_start,
            binEnd: bin.bin_end,
            count: bin.count,
          })),
          topVariants: dto.metrics.top_variants.map((variant) => ({
            chromosome: variant.chromosome,
            position: variant.position,
            ref: variant.ref,
            alt: variant.alt,
            variantType: variant.variant_type,
            filter: variant.filter,
            isPass: variant.is_pass,
            tumorVaf: variant.tumor_vaf ?? null,
            tumorDepth: variant.tumor_depth ?? null,
            normalDepth: variant.normal_depth ?? null,
          })),
        }
      : null,
    artifacts: dto.artifacts.map(mapVariantCallingArtifact),
    completedShards: dto.completed_shards ?? 0,
    totalShards: dto.total_shards ?? 0,
    accelerationMode: dto.acceleration_mode ?? "cpu_gatk",
  };
}

function normalizeImpactTier(value: string | undefined | null): AnnotationImpactTier {
  if (value === "HIGH" || value === "MODERATE" || value === "LOW" || value === "MODIFIER") {
    return value;
  }
  return "MODIFIER";
}

function mapCancerGeneHit(dto: CancerGeneHitDto): CancerGeneHit {
  return {
    symbol: dto.symbol,
    role: dto.role,
    variantCount: dto.variant_count,
    highestImpact: normalizeImpactTier(dto.highest_impact),
    topHgvsp: dto.top_hgvsp ?? null,
    topConsequence: dto.top_consequence ?? null,
    transcriptId: dto.transcript_id ?? null,
    proteinLength: dto.protein_length ?? null,
    variants: (dto.variants ?? []).map(mapGeneFocusVariant),
  };
}

function mapGeneFocusVariant(dto: GeneFocusVariantDto): GeneFocusVariant {
  return {
    chromosome: dto.chromosome,
    position: dto.position,
    proteinPosition: dto.protein_position ?? null,
    hgvsp: dto.hgvsp ?? null,
    hgvsc: dto.hgvsc ?? null,
    consequence: dto.consequence,
    impact: normalizeImpactTier(dto.impact),
    tumorVaf: dto.tumor_vaf ?? null,
  };
}

function mapGeneFocus(dto: GeneFocusDto | null | undefined): GeneFocus | null {
  if (!dto) return null;
  return {
    symbol: dto.symbol,
    role: dto.role ?? null,
    transcriptId: dto.transcript_id ?? null,
    proteinLength: dto.protein_length ?? null,
    variants: (dto.variants ?? []).map(mapGeneFocusVariant),
    domains:
      dto.domains && dto.domains.length > 0
        ? dto.domains.map((d) => ({
            start: d.start,
            end: d.end,
            label: d.label,
            kind: d.kind ?? undefined,
          }))
        : null,
  };
}

function mapAnnotatedVariant(dto: AnnotatedVariantEntryDto): AnnotatedVariantEntry {
  return {
    chromosome: dto.chromosome,
    position: dto.position,
    ref: dto.ref,
    alt: dto.alt,
    geneSymbol: dto.gene_symbol ?? null,
    transcriptId: dto.transcript_id ?? null,
    consequence: dto.consequence,
    consequenceLabel: dto.consequence_label,
    impact: normalizeImpactTier(dto.impact),
    hgvsc: dto.hgvsc ?? null,
    hgvsp: dto.hgvsp ?? null,
    proteinPosition: dto.protein_position ?? null,
    tumorVaf: dto.tumor_vaf ?? null,
    inCancerGene: Boolean(dto.in_cancer_gene),
  };
}

function mapAnnotationMetrics(dto: AnnotationMetricsDto): AnnotationMetrics {
  const by_impact = dto.by_impact ?? {};
  return {
    totalVariants: dto.total_variants,
    annotatedVariants: dto.annotated_variants,
    byImpact: {
      HIGH: by_impact.HIGH ?? 0,
      MODERATE: by_impact.MODERATE ?? 0,
      LOW: by_impact.LOW ?? 0,
      MODIFIER: by_impact.MODIFIER ?? 0,
    },
    byConsequence: (dto.by_consequence ?? []).map((entry) => ({
      term: entry.term,
      label: entry.label,
      count: entry.count,
    })),
    cancerGeneHits: (dto.cancer_gene_hits ?? []).map(mapCancerGeneHit),
    cancerGeneVariantCount: dto.cancer_gene_variant_count ?? 0,
    topGeneFocus: mapGeneFocus(dto.top_gene_focus ?? null),
    topVariants: (dto.top_variants ?? []).map(mapAnnotatedVariant),
    referenceLabel: dto.reference_label ?? null,
    speciesLabel: dto.species_label ?? null,
    vepRelease: dto.vep_release ?? null,
  };
}

function mapAnnotationArtifact(dto: AnnotationArtifactDto): AnnotationArtifact {
  return {
    id: dto.id,
    artifactKind: dto.artifact_kind,
    filename: dto.filename,
    sizeBytes: dto.size_bytes,
    downloadPath: dto.download_path,
    localPath: dto.local_path ?? null,
  };
}

function mapAnnotationRun(dto: AnnotationRunDto): AnnotationRun {
  return {
    id: dto.id,
    status: dto.status,
    progress: dto.progress,
    runtimePhase: dto.runtime_phase ?? null,
    createdAt: dto.created_at,
    updatedAt: dto.updated_at,
    startedAt: dto.started_at ?? null,
    completedAt: dto.completed_at ?? null,
    blockingReason: dto.blocking_reason ?? null,
    error: dto.error ?? null,
    commandLog: dto.command_log,
    metrics: dto.metrics ? mapAnnotationMetrics(dto.metrics) : null,
    artifacts: (dto.artifacts ?? []).map(mapAnnotationArtifact),
    cachePending: Boolean(dto.cache_pending),
    cacheSpeciesLabel: dto.cache_species_label ?? null,
    cacheExpectedMegabytes: dto.cache_expected_megabytes ?? null,
  };
}

function mapAnnotationStageSummary(
  dto: AnnotationStageSummaryDto
): AnnotationStageSummary {
  return {
    workspaceId: dto.workspace_id,
    status: dto.status,
    blockingReason: dto.blocking_reason ?? null,
    readyForNeoantigen: Boolean(dto.ready_for_neoantigen),
    latestRun: dto.latest_run ? mapAnnotationRun(dto.latest_run) : null,
    artifacts: (dto.artifacts ?? []).map(mapAnnotationArtifact),
  };
}

// ----------------------------------------------------------------------------- //
// Stage 5 — Neoantigen prediction
// ----------------------------------------------------------------------------- //

type PatientAlleleDto = {
  allele: string;
  class: MhcClass;
  typing: AlleleTypingKind;
  frequency?: number | null;
  source?: string | null;
};

type RejectedAlleleDto = {
  allele: string;
  class: MhcClass;
  reason: string;
};

type BindingBucketDto = {
  key: BindingTier;
  label: string;
  threshold: string;
  plain: string;
  count: number;
};

type HeatmapRowDto = {
  seq: string;
  gene: string;
  mut: string;
  length: number;
  class: MhcClass;
  vaf: number;
  ic50: number[];
  mut_pos?: number | null;
};

type HeatmapDataDto = {
  alleles: string[];
  peptides: HeatmapRowDto[];
};

type FunnelStepDto = {
  label: string;
  count: number;
  hint: string;
};

type TopCandidateDto = {
  seq: string;
  gene: string;
  mut: string;
  length: number;
  class: MhcClass;
  allele: string;
  ic50: number;
  wt_ic50?: number | null;
  agretopicity?: number | null;
  vaf?: number | null;
  tpm?: number | null;
  cancer_gene: boolean;
  strong: boolean;
};

type NeoantigenMetricsDto = {
  pvacseq_version?: string | null;
  netmhcpan_version?: string | null;
  netmhciipan_version?: string | null;
  species_label?: string | null;
  assembly?: string | null;
  alleles: PatientAlleleDto[];
  rejected_alleles?: RejectedAlleleDto[] | null;
  annotated_variants: number;
  protein_changing_variants: number;
  peptides_generated: number;
  visible_candidates: number;
  class_i_count: number;
  class_ii_count: number;
  buckets: BindingBucketDto[];
  heatmap: HeatmapDataDto;
  funnel: FunnelStepDto[];
  top: TopCandidateDto[];
};

type NeoantigenArtifactDto = {
  id: string;
  artifact_kind: NeoantigenArtifactKind;
  filename: string;
  size_bytes: number;
  download_path: string;
  local_path?: string | null;
};

type NeoantigenRunDto = {
  id: string;
  status: NeoantigenRunStatus;
  progress: number;
  runtime_phase?: NeoantigenRuntimePhase | null;
  created_at: string;
  updated_at: string;
  started_at?: string | null;
  completed_at?: string | null;
  blocking_reason?: string | null;
  error?: string | null;
  command_log: string[];
  metrics?: NeoantigenMetricsDto | null;
  artifacts: NeoantigenArtifactDto[];
};

type NeoantigenStageSummaryDto = {
  workspace_id: string;
  status: NeoantigenStageStatus;
  blocking_reason?: string | null;
  ready_for_epitope_selection: boolean;
  alleles: PatientAlleleDto[];
  latest_run?: NeoantigenRunDto | null;
  artifacts: NeoantigenArtifactDto[];
};

function mapPatientAllele(dto: PatientAlleleDto): PatientAllele {
  return {
    allele: dto.allele,
    class: dto.class,
    typing: dto.typing,
    frequency: dto.frequency ?? null,
    source: dto.source ?? null,
  };
}

function mapBindingBucket(dto: BindingBucketDto): BindingBucket {
  return {
    key: dto.key,
    label: dto.label,
    threshold: dto.threshold,
    plain: dto.plain,
    count: dto.count,
  };
}

function mapHeatmapRow(dto: HeatmapRowDto): HeatmapRow {
  return {
    seq: dto.seq,
    gene: dto.gene,
    mut: dto.mut,
    length: dto.length,
    class: dto.class,
    vaf: dto.vaf,
    ic50: dto.ic50 ?? [],
    mutPos: dto.mut_pos ?? null,
  };
}

function mapHeatmap(dto: HeatmapDataDto): HeatmapData {
  return {
    alleles: dto.alleles ?? [],
    peptides: (dto.peptides ?? []).map(mapHeatmapRow),
  };
}

function mapFunnelStep(dto: FunnelStepDto): FunnelStep {
  return { label: dto.label, count: dto.count, hint: dto.hint };
}

function mapTopCandidate(dto: TopCandidateDto): TopCandidate {
  return {
    seq: dto.seq,
    gene: dto.gene,
    mut: dto.mut,
    length: dto.length,
    class: dto.class,
    allele: dto.allele,
    ic50: dto.ic50,
    wtIc50: dto.wt_ic50 ?? null,
    agretopicity: dto.agretopicity ?? null,
    vaf: dto.vaf ?? null,
    tpm: dto.tpm ?? null,
    cancerGene: dto.cancer_gene,
    strong: dto.strong,
  };
}

function mapNeoantigenMetrics(dto: NeoantigenMetricsDto): NeoantigenMetrics {
  return {
    pvacseqVersion: dto.pvacseq_version ?? null,
    netmhcpanVersion: dto.netmhcpan_version ?? null,
    netmhciipanVersion: dto.netmhciipan_version ?? null,
    speciesLabel: dto.species_label ?? null,
    assembly: dto.assembly ?? null,
    alleles: (dto.alleles ?? []).map(mapPatientAllele),
    rejectedAlleles: (dto.rejected_alleles ?? []).map((r) => ({
      allele: r.allele,
      mhcClass: r.class,
      reason: r.reason,
    })),
    annotatedVariants: dto.annotated_variants,
    proteinChangingVariants: dto.protein_changing_variants,
    peptidesGenerated: dto.peptides_generated,
    visibleCandidates: dto.visible_candidates,
    classICount: dto.class_i_count,
    classIICount: dto.class_ii_count,
    buckets: (dto.buckets ?? []).map(mapBindingBucket),
    heatmap: mapHeatmap(dto.heatmap ?? { alleles: [], peptides: [] }),
    funnel: (dto.funnel ?? []).map(mapFunnelStep),
    top: (dto.top ?? []).map(mapTopCandidate),
  };
}

function mapNeoantigenArtifact(dto: NeoantigenArtifactDto): NeoantigenArtifact {
  return {
    id: dto.id,
    artifactKind: dto.artifact_kind,
    filename: dto.filename,
    sizeBytes: dto.size_bytes,
    downloadPath: dto.download_path,
    localPath: dto.local_path ?? null,
  };
}

function mapNeoantigenRun(dto: NeoantigenRunDto): NeoantigenRun {
  return {
    id: dto.id,
    status: dto.status,
    progress: dto.progress,
    runtimePhase: dto.runtime_phase ?? null,
    createdAt: dto.created_at,
    updatedAt: dto.updated_at,
    startedAt: dto.started_at ?? null,
    completedAt: dto.completed_at ?? null,
    blockingReason: dto.blocking_reason ?? null,
    error: dto.error ?? null,
    commandLog: dto.command_log ?? [],
    metrics: dto.metrics ? mapNeoantigenMetrics(dto.metrics) : null,
    artifacts: (dto.artifacts ?? []).map(mapNeoantigenArtifact),
  };
}

function mapNeoantigenStageSummary(
  dto: NeoantigenStageSummaryDto
): NeoantigenStageSummary {
  return {
    workspaceId: dto.workspace_id,
    status: dto.status,
    blockingReason: dto.blocking_reason ?? null,
    readyForEpitopeSelection: Boolean(dto.ready_for_epitope_selection),
    alleles: (dto.alleles ?? []).map(mapPatientAllele),
    latestRun: dto.latest_run ? mapNeoantigenRun(dto.latest_run) : null,
    artifacts: (dto.artifacts ?? []).map(mapNeoantigenArtifact),
  };
}

type EpitopeCandidateDto = {
  id: string;
  seq: string;
  gene: string;
  mutation: string;
  length: number;
  class: MhcClass;
  allele_id: string;
  ic50_nm: number;
  agretopicity: number;
  vaf: number;
  tpm: number;
  cancer_gene: boolean;
  driver_context?: string | null;
  tier: "strong" | "moderate";
  flags: string[];
};

type EpitopeSafetyFlagDto = {
  peptide_id: string;
  self_hit: string;
  identity: number;
  risk: "critical" | "elevated" | "mild";
  note: string;
};

type EpitopeAlleleDto = {
  id: string;
  class: MhcClass;
  color: string;
};

type EpitopeStageSummaryDto = {
  workspace_id: string;
  status: EpitopeStageStatus;
  blocking_reason?: string | null;
  candidates: EpitopeCandidateDto[];
  safety: Record<string, EpitopeSafetyFlagDto>;
  alleles: EpitopeAlleleDto[];
  default_picks: string[];
  selection: string[];
  ready_for_construct_design: boolean;
};

function mapEpitopeCandidate(dto: EpitopeCandidateDto): EpitopeCandidate {
  return {
    id: dto.id,
    seq: dto.seq,
    gene: dto.gene,
    mutation: dto.mutation,
    length: dto.length,
    class: dto.class,
    alleleId: dto.allele_id,
    ic50Nm: dto.ic50_nm,
    agretopicity: dto.agretopicity,
    vaf: dto.vaf,
    tpm: dto.tpm,
    cancerGene: dto.cancer_gene,
    driverContext: dto.driver_context ?? null,
    tier: dto.tier,
    flags: dto.flags ?? [],
  };
}

function mapEpitopeSafetyFlag(dto: EpitopeSafetyFlagDto): EpitopeSafetyFlag {
  return {
    peptideId: dto.peptide_id,
    selfHit: dto.self_hit,
    identity: dto.identity,
    risk: dto.risk,
    note: dto.note,
  };
}

function mapEpitopeAllele(dto: EpitopeAlleleDto): EpitopeAllele {
  return { id: dto.id, class: dto.class, color: dto.color };
}

function mapEpitopeStageSummary(
  dto: EpitopeStageSummaryDto
): EpitopeStageSummary {
  const safety: Record<string, EpitopeSafetyFlag> = {};
  for (const [key, value] of Object.entries(dto.safety ?? {})) {
    safety[key] = mapEpitopeSafetyFlag(value);
  }
  return {
    workspaceId: dto.workspace_id,
    status: dto.status,
    blockingReason: dto.blocking_reason ?? null,
    candidates: (dto.candidates ?? []).map(mapEpitopeCandidate),
    safety,
    alleles: (dto.alleles ?? []).map(mapEpitopeAllele),
    defaultPicks: dto.default_picks ?? [],
    selection: dto.selection ?? [],
    readyForConstructDesign: Boolean(dto.ready_for_construct_design),
  };
}

// --- Stage 7 — mRNA construct design ----------------------------------------

type ConstructDesignOptionsDto = {
  lambda: number;
  signal: boolean;
  mitd: boolean;
  confirmed: boolean;
};

type ConstructSegmentDto = {
  kind: ConstructSegmentKind;
  label: string;
  sub?: string | null;
  aa: string;
  class?: MhcClass | null;
  peptide_id?: string | null;
  color?: string | null;
};

type ConstructFlanksDto = {
  kozak: string;
  utr5: string;
  utr3: string;
  poly_a: number;
  signal_aa: string;
  mitd_aa: string;
  signal_why: string;
  mitd_why: string;
};

type ConstructMetricsDto = {
  aa_len: number;
  nt_len: number;
  cai: number;
  mfe: number;
  gc: number;
  full_mrna_nt: number;
  mfe_per_nt: number;
};

type ConstructManufacturingCheckDto = {
  id: string;
  label: string;
  why: string;
  status: "pass" | "warn" | "fail";
};

type ConstructPreviewCodonDto = {
  aa: string;
  unopt: string;
  opt: string;
  swapped: boolean;
};

type ConstructPreviewDto = {
  gene: string;
  mut: string;
  codons: ConstructPreviewCodonDto[];
};

type ConstructStageSummaryDto = {
  workspace_id: string;
  status: ConstructDesignStatus;
  blocking_reason?: string | null;
  options: ConstructDesignOptionsDto;
  flanks: ConstructFlanksDto;
  linkers: Record<string, string>;
  segments: ConstructSegmentDto[];
  aa_seq: string;
  metrics: ConstructMetricsDto;
  preview: ConstructPreviewDto;
  manufacturing_checks: ConstructManufacturingCheckDto[];
  peptide_count: number;
  ready_for_output: boolean;
};

function mapConstructSegment(dto: ConstructSegmentDto): ConstructSegment {
  return {
    kind: dto.kind,
    label: dto.label,
    sub: dto.sub ?? null,
    aa: dto.aa,
    class: (dto.class ?? null) as MhcClass | null,
    peptideId: dto.peptide_id ?? null,
    color: dto.color ?? null,
  };
}

function mapConstructFlanks(dto: ConstructFlanksDto): ConstructFlanks {
  return {
    kozak: dto.kozak,
    utr5: dto.utr5,
    utr3: dto.utr3,
    polyA: dto.poly_a,
    signalAa: dto.signal_aa,
    mitdAa: dto.mitd_aa,
    signalWhy: dto.signal_why,
    mitdWhy: dto.mitd_why,
  };
}

function mapConstructMetrics(dto: ConstructMetricsDto): ConstructMetrics {
  return {
    aaLen: dto.aa_len,
    ntLen: dto.nt_len,
    cai: dto.cai,
    mfe: dto.mfe,
    gc: dto.gc,
    fullMrnaNt: dto.full_mrna_nt,
    mfePerNt: dto.mfe_per_nt,
  };
}

function mapConstructPreview(dto: ConstructPreviewDto): ConstructPreview {
  return {
    gene: dto.gene,
    mut: dto.mut,
    codons: (dto.codons ?? []).map(
      (c): ConstructPreviewCodon => ({
        aa: c.aa,
        unopt: c.unopt,
        opt: c.opt,
        swapped: c.swapped,
      })
    ),
  };
}

function mapConstructStageSummary(
  dto: ConstructStageSummaryDto
): ConstructStageSummary {
  return {
    workspaceId: dto.workspace_id,
    status: dto.status,
    blockingReason: dto.blocking_reason ?? null,
    options: {
      lambda: dto.options.lambda,
      signal: dto.options.signal,
      mitd: dto.options.mitd,
      confirmed: dto.options.confirmed,
    },
    flanks: mapConstructFlanks(dto.flanks),
    linkers: dto.linkers ?? {},
    segments: (dto.segments ?? []).map(mapConstructSegment),
    aaSeq: dto.aa_seq,
    metrics: mapConstructMetrics(dto.metrics),
    preview: mapConstructPreview(dto.preview),
    manufacturingChecks: (dto.manufacturing_checks ?? []).map(
      (c): ConstructManufacturingCheck => ({
        id: c.id,
        label: c.label,
        why: c.why,
        status: c.status,
      })
    ),
    peptideCount: dto.peptide_count,
    readyForOutput: Boolean(dto.ready_for_output),
  };
}

// --- Stage 8 — Construct output ---------------------------------------------

type CmoOptionDto = {
  id: string;
  name: string;
  type: string;
  tat: string;
  cost: string;
  good: string[];
};

type DosingScheduleItemDto = {
  when: string;
  label: string;
  what: string;
};

type DosingProtocolDto = {
  formulation: string;
  route: string;
  dose: string;
  schedule: DosingScheduleItemDto[];
  watch_for: string[];
};

type AuditEntryDto = {
  stage: string;
  when: string;
  who: string;
  what: string;
  kind: "auto" | "human";
};

type ConstructOutputRunDto = {
  kind: ConstructRunKind;
  label: string;
  nt: string;
};

type ConstructOutputOrderDto = {
  cmo_id: string;
  po_number: string;
  ordered_at: string;
};

type ConstructOutputStageSummaryDto = {
  workspace_id: string;
  status: ConstructOutputStatus;
  blocking_reason?: string | null;
  construct_id: string;
  species: string;
  version: string;
  checksum: string;
  released_at?: string | null;
  released_by?: string | null;
  runs: ConstructOutputRunDto[];
  full_nt: string;
  total_nt: number;
  genbank: string;
  cmo_options: CmoOptionDto[];
  selected_cmo?: string | null;
  order?: ConstructOutputOrderDto | null;
  dosing: DosingProtocolDto;
  audit_trail: AuditEntryDto[];
};

function mapConstructOutputStageSummary(
  dto: ConstructOutputStageSummaryDto
): ConstructOutputStageSummary {
  return {
    workspaceId: dto.workspace_id,
    status: dto.status,
    blockingReason: dto.blocking_reason ?? null,
    constructId: dto.construct_id,
    species: dto.species,
    version: dto.version,
    checksum: dto.checksum,
    releasedAt: dto.released_at ?? null,
    releasedBy: dto.released_by ?? null,
    runs: (dto.runs ?? []).map(
      (r): ConstructOutputRun => ({ kind: r.kind, label: r.label, nt: r.nt })
    ),
    fullNt: dto.full_nt,
    totalNt: dto.total_nt,
    genbank: dto.genbank ?? "",
    cmoOptions: (dto.cmo_options ?? []).map(
      (o): CmoOption => ({
        id: o.id,
        name: o.name,
        type: o.type,
        tat: o.tat,
        cost: o.cost,
        good: o.good ?? [],
      })
    ),
    selectedCmo: dto.selected_cmo ?? null,
    order: dto.order
      ? {
          cmoId: dto.order.cmo_id,
          poNumber: dto.order.po_number,
          orderedAt: dto.order.ordered_at,
        }
      : null,
    dosing: {
      formulation: dto.dosing.formulation,
      route: dto.dosing.route,
      dose: dto.dosing.dose,
      schedule: (dto.dosing.schedule ?? []).map(
        (s): DosingScheduleItem => ({
          when: s.when,
          label: s.label,
          what: s.what,
        })
      ),
      watchFor: dto.dosing.watch_for ?? [],
    },
    auditTrail: (dto.audit_trail ?? []).map(
      (e): AuditEntry => ({
        stage: e.stage,
        when: e.when,
        who: e.who,
        what: e.what,
        kind: e.kind,
      })
    ),
  };
}

function mapVariantCallingStageSummary(
  dto: VariantCallingStageSummaryDto
): VariantCallingStageSummary {
  return {
    workspaceId: dto.workspace_id,
    status: dto.status,
    blockingReason: dto.blocking_reason ?? null,
    readyForAnnotation: dto.ready_for_annotation,
    latestRun: dto.latest_run ? mapVariantCallingRun(dto.latest_run) : null,
    artifacts: dto.artifacts.map(mapVariantCallingArtifact),
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

export class StageNotActionableError extends Error {
  readonly stage: PipelineStageId;

  constructor(message: string, stage: PipelineStageId) {
    super(message);
    this.name = "StageNotActionableError";
    this.stage = stage;
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

type StageNotActionableDetail = {
  code: "stage_not_actionable";
  stage: PipelineStageId;
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

function parseStageNotActionableDetail(
  payload: string
): StageNotActionableDetail | null {
  try {
    const parsed = JSON.parse(payload) as { detail?: unknown };
    const detail = parsed.detail;
    if (
      detail &&
      typeof detail === "object" &&
      (detail as { code?: unknown }).code === "stage_not_actionable"
    ) {
      const typed = detail as Partial<StageNotActionableDetail>;
      if (typeof typed.stage === "string" && typeof typed.message === "string") {
        return {
          code: "stage_not_actionable",
          stage: typed.stage as PipelineStageId,
          message: typed.message,
        };
      }
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

    const notActionable = parseStageNotActionableDetail(payload);
    if (notActionable) {
      throw new StageNotActionableError(
        notActionable.message,
        notActionable.stage
      );
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

export interface InboxEntry {
  name: string;
  path: string;
  sizeBytes: number;
  modifiedAt: string;
  kind: "fastq" | "bam" | "cram" | "unknown";
}

export interface InboxListing {
  root: string;
  entries: InboxEntry[];
}

type InboxEntryDto = {
  name: string;
  path: string;
  size_bytes: number;
  modified_at: string;
  kind: string;
};

type InboxListingDto = {
  root: string;
  entries: InboxEntryDto[];
};

function mapInboxEntry(dto: InboxEntryDto): InboxEntry {
  const kind: InboxEntry["kind"] =
    dto.kind === "fastq" || dto.kind === "bam" || dto.kind === "cram"
      ? dto.kind
      : "unknown";
  return {
    name: dto.name,
    path: dto.path,
    sizeBytes: dto.size_bytes,
    modifiedAt: dto.modified_at,
    kind,
  };
}

const realApi = {
  health: () => request<{ status: string }>("/health"),

  listInbox: async (): Promise<InboxListing> => {
    const dto = await request<InboxListingDto>("/api/inbox");
    return {
      root: dto.root,
      entries: dto.entries.map(mapInboxEntry),
    };
  },

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
  cancelAlignment: async (workspaceId: string, runId: string) =>
    mapAlignmentStageSummary(
      await request<AlignmentStageSummaryDto>(
        `/api/workspaces/${workspaceId}/alignment/runs/${runId}/cancel`,
        { method: "POST" }
      )
    ),
  pauseAlignment: async (workspaceId: string, runId: string) =>
    mapAlignmentStageSummary(
      await request<AlignmentStageSummaryDto>(
        `/api/workspaces/${workspaceId}/alignment/runs/${runId}/pause`,
        { method: "POST" }
      )
    ),
  resumeAlignment: async (workspaceId: string, runId: string) =>
    mapAlignmentStageSummary(
      await request<AlignmentStageSummaryDto>(
        `/api/workspaces/${workspaceId}/alignment/runs/${runId}/resume`,
        { method: "POST" }
      )
    ),
  getVariantCallingStageSummary: async (workspaceId: string) =>
    mapVariantCallingStageSummary(
      await request<VariantCallingStageSummaryDto>(
        `/api/workspaces/${workspaceId}/variant-calling`
      )
    ),
  runVariantCalling: async (workspaceId: string) =>
    mapVariantCallingStageSummary(
      await request<VariantCallingStageSummaryDto>(
        `/api/workspaces/${workspaceId}/variant-calling/run`,
        { method: "POST" }
      )
    ),
  rerunVariantCalling: async (workspaceId: string) =>
    mapVariantCallingStageSummary(
      await request<VariantCallingStageSummaryDto>(
        `/api/workspaces/${workspaceId}/variant-calling/rerun`,
        { method: "POST" }
      )
    ),
  cancelVariantCalling: async (workspaceId: string, runId: string) =>
    mapVariantCallingStageSummary(
      await request<VariantCallingStageSummaryDto>(
        `/api/workspaces/${workspaceId}/variant-calling/runs/${runId}/cancel`,
        { method: "POST" }
      )
    ),
  pauseVariantCalling: async (workspaceId: string, runId: string) =>
    mapVariantCallingStageSummary(
      await request<VariantCallingStageSummaryDto>(
        `/api/workspaces/${workspaceId}/variant-calling/runs/${runId}/pause`,
        { method: "POST" }
      )
    ),
  resumeVariantCalling: async (workspaceId: string, runId: string) =>
    mapVariantCallingStageSummary(
      await request<VariantCallingStageSummaryDto>(
        `/api/workspaces/${workspaceId}/variant-calling/runs/${runId}/resume`,
        { method: "POST" }
      )
    ),
  getAnnotationStageSummary: async (workspaceId: string) =>
    mapAnnotationStageSummary(
      await request<AnnotationStageSummaryDto>(
        `/api/workspaces/${workspaceId}/annotation`
      )
    ),
  runAnnotation: async (workspaceId: string) =>
    mapAnnotationStageSummary(
      await request<AnnotationStageSummaryDto>(
        `/api/workspaces/${workspaceId}/annotation/run`,
        { method: "POST" }
      )
    ),
  rerunAnnotation: async (workspaceId: string) =>
    mapAnnotationStageSummary(
      await request<AnnotationStageSummaryDto>(
        `/api/workspaces/${workspaceId}/annotation/rerun`,
        { method: "POST" }
      )
    ),
  cancelAnnotation: async (workspaceId: string, runId: string) =>
    mapAnnotationStageSummary(
      await request<AnnotationStageSummaryDto>(
        `/api/workspaces/${workspaceId}/annotation/runs/${runId}/cancel`,
        { method: "POST" }
      )
    ),
  pauseAnnotation: async (workspaceId: string, runId: string) =>
    mapAnnotationStageSummary(
      await request<AnnotationStageSummaryDto>(
        `/api/workspaces/${workspaceId}/annotation/runs/${runId}/pause`,
        { method: "POST" }
      )
    ),
  resumeAnnotation: async (workspaceId: string, runId: string) =>
    mapAnnotationStageSummary(
      await request<AnnotationStageSummaryDto>(
        `/api/workspaces/${workspaceId}/annotation/runs/${runId}/resume`,
        { method: "POST" }
      )
    ),
  getGeneProteinDomains: async (
    workspaceId: string,
    geneSymbol: string,
  ): Promise<GeneDomainsResponse> => {
    const dto = await request<GeneDomainsDto>(
      `/api/workspaces/${workspaceId}/annotation/genes/${encodeURIComponent(
        geneSymbol,
      )}/domains`,
    );
    return {
      symbol: dto.symbol,
      transcriptId: dto.transcript_id ?? null,
      proteinLength: dto.protein_length ?? null,
      domains: (dto.domains ?? []).map((d) => ({
        start: d.start,
        end: d.end,
        label: d.label,
        kind: d.kind ?? undefined,
      })),
    };
  },
  getNeoantigenStageSummary: async (workspaceId: string) =>
    mapNeoantigenStageSummary(
      await request<NeoantigenStageSummaryDto>(
        `/api/workspaces/${workspaceId}/neoantigen`
      )
    ),
  runNeoantigen: async (workspaceId: string) =>
    mapNeoantigenStageSummary(
      await request<NeoantigenStageSummaryDto>(
        `/api/workspaces/${workspaceId}/neoantigen/run`,
        { method: "POST" }
      )
    ),
  rerunNeoantigen: async (workspaceId: string) =>
    mapNeoantigenStageSummary(
      await request<NeoantigenStageSummaryDto>(
        `/api/workspaces/${workspaceId}/neoantigen/rerun`,
        { method: "POST" }
      )
    ),
  cancelNeoantigen: async (workspaceId: string, runId: string) =>
    mapNeoantigenStageSummary(
      await request<NeoantigenStageSummaryDto>(
        `/api/workspaces/${workspaceId}/neoantigen/runs/${runId}/cancel`,
        { method: "POST" }
      )
    ),
  pauseNeoantigen: async (workspaceId: string, runId: string) =>
    mapNeoantigenStageSummary(
      await request<NeoantigenStageSummaryDto>(
        `/api/workspaces/${workspaceId}/neoantigen/runs/${runId}/pause`,
        { method: "POST" }
      )
    ),
  resumeNeoantigen: async (workspaceId: string, runId: string) =>
    mapNeoantigenStageSummary(
      await request<NeoantigenStageSummaryDto>(
        `/api/workspaces/${workspaceId}/neoantigen/runs/${runId}/resume`,
        { method: "POST" }
      )
    ),
  updateNeoantigenAlleles: async (
    workspaceId: string,
    alleles: PatientAllele[]
  ) =>
    mapNeoantigenStageSummary(
      await request<NeoantigenStageSummaryDto>(
        `/api/workspaces/${workspaceId}/neoantigen/alleles`,
        {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            alleles: alleles.map((a) => ({
              allele: a.allele,
              class: a.class,
              typing: a.typing,
              frequency: a.frequency ?? null,
              source: a.source ?? null,
            })),
          }),
        }
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
  getEpitopeStageSummary: async (workspaceId: string) =>
    mapEpitopeStageSummary(
      await request<EpitopeStageSummaryDto>(
        `/api/workspaces/${workspaceId}/epitope`
      )
    ),
  updateEpitopeSelection: async (
    workspaceId: string,
    peptideIds: string[]
  ) =>
    mapEpitopeStageSummary(
      await request<EpitopeStageSummaryDto>(
        `/api/workspaces/${workspaceId}/epitope/selection`,
        {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ peptide_ids: peptideIds }),
        }
      )
    ),
  getConstructStageSummary: async (workspaceId: string) =>
    mapConstructStageSummary(
      await request<ConstructStageSummaryDto>(
        `/api/workspaces/${workspaceId}/construct`
      )
    ),
  updateConstructOptions: async (
    workspaceId: string,
    options: { lambda: number; signal: boolean; mitd: boolean; confirmed: boolean }
  ) =>
    mapConstructStageSummary(
      await request<ConstructStageSummaryDto>(
        `/api/workspaces/${workspaceId}/construct/options`,
        {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            lambda: options.lambda,
            signal: options.signal,
            mitd: options.mitd,
            confirmed: options.confirmed,
          }),
        }
      )
    ),
  getConstructOutputSummary: async (workspaceId: string) =>
    mapConstructOutputStageSummary(
      await request<ConstructOutputStageSummaryDto>(
        `/api/workspaces/${workspaceId}/construct-output`
      )
    ),
  updateConstructOutput: async (
    workspaceId: string,
    payload: { action: "select_cmo" | "release"; cmoId?: string | null }
  ) =>
    mapConstructOutputStageSummary(
      await request<ConstructOutputStageSummaryDto>(
        `/api/workspaces/${workspaceId}/construct-output/action`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            action: payload.action,
            cmo_id: payload.cmoId ?? null,
          }),
        }
      )
    ),
  resolveDownloadUrl: (downloadPath: string) => `${PUBLIC_API_BASE}${downloadPath}`,
};

import { demoApi } from "@/lib/demo-api";

const DEMO_MODE = process.env.NEXT_PUBLIC_DEMO === "1";

export const api: typeof realApi = DEMO_MODE
  ? ({ ...realApi, ...demoApi } as typeof realApi)
  : realApi;
