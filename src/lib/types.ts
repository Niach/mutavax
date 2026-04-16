export type PipelineStageId =
  | "ingestion"
  | "alignment"
  | "variant-calling"
  | "annotation"
  | "neoantigen-prediction"
  | "epitope-selection"
  | "construct-design"
  | "structure-prediction"
  | "construct-output"
  | "ai-review";

export type WorkspaceSpecies = "human" | "dog" | "cat";
export type AssayType = "wgs" | "wes";
export type ReferencePreset = "grch38" | "canfam4" | "felcat9";
export type SampleLane = "tumor" | "normal";
export type WorkspaceFileFormat = "fastq" | "bam" | "cram";
export type WorkspaceFileRole = "source" | "canonical";
export type WorkspaceFileStatus =
  | "uploaded"
  | "normalizing"
  | "ready"
  | "failed";
export type IngestionStatus =
  | "empty"
  | "uploading"
  | "uploaded"
  | "normalizing"
  | "ready"
  | "failed";
export type IngestionProgressPhase =
  | "validating"
  | "referencing"
  | "concatenating"
  | "compressing"
  | "extracting"
  | "finalizing";
export type ReadPair = "R1" | "R2" | "SE" | "unknown";
export type ReadLayout = "paired" | "single";
export type StageImplementationState = "live" | "mock" | "planned";
export type PipelineStageGroup = "primary" | "later";
export type AlignmentStageStatus =
  | "blocked"
  | "ready"
  | "running"
  | "paused"
  | "completed"
  | "failed";
export type AlignmentRunStatus =
  | "pending"
  | "running"
  | "completed"
  | "failed"
  | "cancelled"
  | "paused";
export type AlignmentRuntimePhase =
  | "preparing_reference"
  | "aligning"
  | "finalizing";
export type QcVerdict = "pass" | "warn" | "fail";
export type AlignmentArtifactKind =
  | "bam"
  | "bai"
  | "flagstat"
  | "idxstats"
  | "stats";

export interface PipelineStage {
  id: PipelineStageId;
  name: string;
  description: string;
  icon: string;
  tools: string[];
  implementationState: StageImplementationState;
  group: PipelineStageGroup;
}

export interface WorkspaceFile {
  id: string;
  batchId: string;
  sourceFileId?: string | null;
  sampleLane: SampleLane;
  filename: string;
  format: WorkspaceFileFormat;
  fileRole: WorkspaceFileRole;
  status: WorkspaceFileStatus;
  sizeBytes: number;
  uploadedAt: string;
  readPair: ReadPair;
  sourcePath?: string | null;
  managedPath?: string | null;
  error?: string | null;
}

export interface IngestionLaneSummary {
  activeBatchId?: string | null;
  sampleLane: SampleLane;
  status: IngestionStatus;
  readyForAlignment: boolean;
  sourceFileCount: number;
  canonicalFileCount: number;
  missingPairs: ReadPair[];
  blockingIssues: string[];
  readLayout?: ReadLayout | null;
  updatedAt?: string | null;
  progress?: IngestionLaneProgress | null;
}

export interface IngestionLaneProgress {
  phase: IngestionProgressPhase;
  currentFilename?: string | null;
  bytesProcessed?: number | null;
  totalBytes?: number | null;
  throughputBytesPerSec?: number | null;
  etaSeconds?: number | null;
  percent?: number | null;
}

export interface IngestionSummary {
  status: IngestionStatus;
  readyForAlignment: boolean;
  lanes: Record<SampleLane, IngestionLaneSummary>;
}

export interface CreateWorkspaceInput {
  displayName: string;
  species: WorkspaceSpecies;
}

export interface AnalysisProfile {
  assayType?: AssayType | null;
  referencePreset?: ReferencePreset | null;
  referenceOverride?: string | null;
}

export interface LocalFileRegistrationInput {
  sampleLane: SampleLane;
  paths: string[];
}

export interface Workspace {
  id: string;
  displayName: string;
  species: WorkspaceSpecies;
  analysisProfile: AnalysisProfile;
  activeStage: PipelineStageId;
  ingestion: IngestionSummary;
  files: WorkspaceFile[];
  createdAt: string;
  updatedAt: string;
}

export interface FastqReadPreview {
  header: string;
  sequence: string;
  quality: string;
  length: number;
  gcPercent: number;
  meanQuality: number;
}

export interface SampledReadStats {
  sampledReadCount: number;
  averageReadLength: number;
  sampledGcPercent: number;
}

export interface IngestionLanePreview {
  workspaceId: string;
  sampleLane: SampleLane;
  batchId: string;
  source: "canonical-fastq";
  readLayout: ReadLayout;
  reads: Partial<Record<Extract<ReadPair, "R1" | "R2" | "SE">, FastqReadPreview[]>>;
  stats: SampledReadStats;
}

export interface AlignmentLaneMetrics {
  sampleLane: SampleLane;
  totalReads: number;
  mappedReads: number;
  mappedPercent: number;
  properlyPairedPercent?: number | null;
  duplicatePercent?: number | null;
  meanInsertSize?: number | null;
}

export interface AlignmentArtifact {
  id: string;
  artifactKind: AlignmentArtifactKind;
  sampleLane?: SampleLane | null;
  filename: string;
  sizeBytes: number;
  downloadPath: string;
  localPath?: string | null;
}

export type ChunkProgressPhase = "splitting" | "aligning" | "merging";

export interface ChunkProgressState {
  phase: ChunkProgressPhase;
  totalChunks: number;
  completedChunks: number;
  activeChunks: number;
}

export interface AlignmentProgressComponents {
  referencePrep: number;
  aligning: number;
  finalizing: number;
  stats: number;
}

export interface AlignmentRun {
  id: string;
  status: AlignmentRunStatus;
  progress: number;
  assayType?: AssayType | null;
  referencePreset?: ReferencePreset | null;
  referenceOverride?: string | null;
  referenceLabel?: string | null;
  runtimePhase?: AlignmentRuntimePhase | null;
  qcVerdict?: QcVerdict | null;
  createdAt: string;
  updatedAt: string;
  startedAt?: string | null;
  completedAt?: string | null;
  blockingReason?: string | null;
  error?: string | null;
  commandLog: string[];
  recentLogTail: string[];
  lastActivityAt?: string | null;
  etaSeconds?: number | null;
  progressComponents: AlignmentProgressComponents;
  expectedTotalPerLane: Partial<Record<SampleLane, number>>;
  laneMetrics: Partial<Record<SampleLane, AlignmentLaneMetrics>>;
  chunkProgress: Partial<Record<SampleLane, ChunkProgressState>>;
  artifacts: AlignmentArtifact[];
}

export interface AlignmentStageSummary {
  workspaceId: string;
  status: AlignmentStageStatus;
  blockingReason?: string | null;
  analysisProfile: AnalysisProfile;
  qcVerdict?: QcVerdict | null;
  readyForVariantCalling: boolean;
  latestRun?: AlignmentRun | null;
  laneMetrics: Record<SampleLane, AlignmentLaneMetrics | null>;
  artifacts: AlignmentArtifact[];
}

export interface SystemMemoryResponse {
  availableBytes: number | null;
  totalBytes: number | null;
  thresholdBytes: number;
}

export interface SystemResourcesResponse {
  cpuCount: number;
  totalMemoryBytes: number | null;
  availableMemoryBytes: number | null;
  appDataDiskTotalBytes: number | null;
  appDataDiskFreeBytes: number | null;
  appDataRoot: string;
}

export interface AlignmentSettingsDefaults {
  alignerThreads: number;
  samtoolsThreads: number;
  samtoolsSortThreads: number;
  samtoolsSortMemory: string;
  chunkReads: number;
  chunkParallelism: number;
}

export interface AlignmentSettings extends AlignmentSettingsDefaults {
  defaults: AlignmentSettingsDefaults;
}

export type AlignmentSettingsPatch = Partial<AlignmentSettingsDefaults> & {
  reset?: boolean;
};

export type VariantCallingRunStatus = "pending" | "running" | "completed" | "failed";
export type VariantCallingStageStatus =
  | "blocked"
  | "ready"
  | "running"
  | "completed"
  | "failed";
export type VariantCallingRuntimePhase =
  | "preparing_reference"
  | "calling"
  | "filtering"
  | "finalizing";
export type VariantCallingArtifactKind = "vcf" | "tbi" | "stats";

export interface VariantCallingMetrics {
  totalVariants: number;
  snvCount: number;
  indelCount: number;
  passCount: number;
}

export interface VariantCallingArtifact {
  id: string;
  artifactKind: VariantCallingArtifactKind;
  filename: string;
  sizeBytes: number;
  downloadPath: string;
  localPath?: string | null;
}

export interface VariantCallingRun {
  id: string;
  status: VariantCallingRunStatus;
  progress: number;
  runtimePhase?: VariantCallingRuntimePhase | null;
  createdAt: string;
  updatedAt: string;
  startedAt?: string | null;
  completedAt?: string | null;
  blockingReason?: string | null;
  error?: string | null;
  commandLog: string[];
  metrics?: VariantCallingMetrics | null;
  artifacts: VariantCallingArtifact[];
}

export interface VariantCallingStageSummary {
  workspaceId: string;
  status: VariantCallingStageStatus;
  blockingReason?: string | null;
  readyForAnnotation: boolean;
  latestRun?: VariantCallingRun | null;
  artifacts: VariantCallingArtifact[];
}

export interface DLAAllele {
  name: string;
  locus: "DLA-88" | "DLA-DRB1" | "DLA-DQA1" | "DLA-DQB1";
  sequence?: string;
  hasBindingData: boolean;
}

export interface Neoantigen {
  id: string;
  gene: string;
  mutation: string;
  peptide: string;
  hlaAllele: string;
  bindingAffinity: number;
  percentileRank: number;
  expression?: number;
  clonalVaf?: number;
}

export interface VaccineConstruct {
  id: string;
  name: string;
  epitopes: Neoantigen[];
  mrnaSequence: string;
  proteinSequence: string;
  fivePrimeUtr: string;
  threePrimeUtr: string;
  polyATailLength: number;
  codonAdaptationIndex: number;
  mfe: number;
  gcContent: number;
}

export const PIPELINE_STAGES: PipelineStage[] = [
  {
    id: "ingestion",
    name: "Ingestion",
    description:
      "Choose local tumor and normal sequencing files, then normalize them into canonical paired FASTQ",
    icon: "Upload",
    tools: ["samtools", "fastp"],
    implementationState: "live",
    group: "primary",
  },
  {
    id: "alignment",
    name: "Alignment",
    description: "Align canonical tumor and normal FASTQ reads, then score BAM quality",
    icon: "GitBranch",
    tools: ["strobealign", "samtools"],
    implementationState: "live",
    group: "primary",
  },
  {
    id: "variant-calling",
    name: "Variant Calling",
    description: "Call somatic variants from the aligned tumor and normal BAMs",
    icon: "Search",
    tools: ["GATK Mutect2"],
    implementationState: "planned",
    group: "primary",
  },
  {
    id: "annotation",
    name: "Annotation",
    description: "Annotate variants with functional consequences",
    icon: "Tag",
    tools: ["Ensembl VEP"],
    implementationState: "planned",
    group: "primary",
  },
  {
    id: "neoantigen-prediction",
    name: "Neoantigen Prediction",
    description: "Predict MHC binding for mutant peptides against DLA alleles",
    icon: "Target",
    tools: ["pVACseq", "NetMHCpan-4.1"],
    implementationState: "planned",
    group: "primary",
  },
  {
    id: "epitope-selection",
    name: "Epitope Selection",
    description: "Rank and select optimal vaccine targets",
    icon: "ListChecks",
    tools: ["pVACview", "custom scoring"],
    implementationState: "planned",
    group: "primary",
  },
  {
    id: "construct-design",
    name: "mRNA Construct Design",
    description: "Optimize codons, UTRs, and secondary structure",
    icon: "Dna",
    tools: ["LinearDesign", "DNAchisel", "ViennaRNA"],
    implementationState: "planned",
    group: "primary",
  },
  {
    id: "structure-prediction",
    name: "Structure Prediction",
    description: "Model peptide-MHC complex 3D structures",
    icon: "Box",
    tools: ["Boltz-2", "ESMFold", "Mol*"],
    implementationState: "planned",
    group: "later",
  },
  {
    id: "construct-output",
    name: "Construct Output",
    description: "Generate final mRNA sequence for synthesis",
    icon: "FileOutput",
    tools: ["pVACvector", "Biopython"],
    implementationState: "planned",
    group: "primary",
  },
  {
    id: "ai-review",
    name: "AI Review",
    description: "AI-guided validation and optimization suggestions",
    icon: "Brain",
    tools: ["Claude API", "ESM-C"],
    implementationState: "planned",
    group: "later",
  },
];

export const PRIMARY_PIPELINE_STAGES = PIPELINE_STAGES.filter(
  (stage) => stage.group === "primary"
);

export const LATER_RESEARCH_STAGES = PIPELINE_STAGES.filter(
  (stage) => stage.group === "later"
);

export function isPipelineStageId(value: string): value is PipelineStageId {
  return PIPELINE_STAGES.some((stage) => stage.id === value);
}

export function getPipelineStage(stageId: PipelineStageId) {
  return PIPELINE_STAGES.find((stage) => stage.id === stageId);
}
