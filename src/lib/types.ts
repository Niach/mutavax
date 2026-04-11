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

export type JobStatus = "pending" | "running" | "completed" | "failed";
export type WorkspaceSpecies = "human" | "dog" | "cat";
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
export type UploadSessionStatus =
  | "uploading"
  | "uploaded"
  | "failed"
  | "committed";
export type UploadSessionFileStatus =
  | "pending"
  | "uploading"
  | "uploaded"
  | "failed";
export type ReadPair = "R1" | "R2" | "SE" | "unknown";
export type ReadLayout = "paired" | "single";
export type StageImplementationState = "live" | "mock" | "planned";

export interface PipelineStage {
  id: PipelineStageId;
  name: string;
  description: string;
  icon: string;
  tools: string[];
  implementationState: StageImplementationState;
}

export interface Job {
  id: string;
  workspaceId: string | null;
  stageId: PipelineStageId;
  status: JobStatus;
  progress: number;
  createdAt: string;
  updatedAt: string;
  error?: string;
  result?: Record<string, unknown> | null;
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
  storageKey: string;
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
}

export interface IngestionSummary {
  status: IngestionStatus;
  readyForAlignment: boolean;
  lanes: Record<SampleLane, IngestionLaneSummary>;
}

export interface UploadSessionFile {
  id: string;
  sampleLane: SampleLane;
  filename: string;
  format: WorkspaceFileFormat;
  readPair: ReadPair;
  sizeBytes: number;
  uploadedBytes: number;
  totalParts: number;
  lastModifiedMs: number;
  fingerprint: string;
  contentType?: string | null;
  status: UploadSessionFileStatus;
  error?: string | null;
  completedPartNumbers: number[];
}

export interface UploadSession {
  id: string;
  sampleLane: SampleLane;
  status: UploadSessionStatus;
  chunkSizeBytes: number;
  error?: string | null;
  files: UploadSessionFile[];
  createdAt: string;
  updatedAt: string;
}

export interface CreateWorkspaceInput {
  displayName: string;
  species: WorkspaceSpecies;
}

export interface UploadSessionCreateFileInput {
  filename: string;
  sizeBytes: number;
  lastModifiedMs: number;
  contentType?: string;
}

export interface UploadSessionCreateInput {
  sampleLane: SampleLane;
  files: UploadSessionCreateFileInput[];
}

export interface UploadPartResult {
  uploadedBytes: number;
  totalParts: number;
  completedPartNumbers: number[];
}

export interface Workspace {
  id: string;
  displayName: string;
  species: WorkspaceSpecies;
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
      "Upload tumor and normal sequencing files, then normalize them into canonical paired FASTQ",
    icon: "Upload",
    tools: ["samtools", "fastp"],
    implementationState: "live",
  },
  {
    id: "alignment",
    name: "Alignment",
    description: "Consume canonical paired FASTQ reads for reference alignment",
    icon: "GitBranch",
    tools: ["BWA-MEM2", "pysam"],
    implementationState: "mock",
  },
  {
    id: "variant-calling",
    name: "Variant Calling",
    description: "Identify somatic mutations with ensemble callers",
    icon: "Search",
    tools: ["GATK Mutect2", "Strelka2", "DeepSomatic"],
    implementationState: "planned",
  },
  {
    id: "annotation",
    name: "Annotation",
    description: "Annotate variants with functional consequences",
    icon: "Tag",
    tools: ["Ensembl VEP", "SnpEff"],
    implementationState: "planned",
  },
  {
    id: "neoantigen-prediction",
    name: "Neoantigen Prediction",
    description: "Predict MHC binding for mutant peptides against DLA alleles",
    icon: "Target",
    tools: ["pVACseq", "NetMHCpan-4.1", "MHCflurry"],
    implementationState: "planned",
  },
  {
    id: "epitope-selection",
    name: "Epitope Selection",
    description: "Rank and select optimal vaccine targets",
    icon: "ListChecks",
    tools: ["pVACview", "custom scoring"],
    implementationState: "planned",
  },
  {
    id: "construct-design",
    name: "mRNA Construct Design",
    description: "Optimize codons, UTRs, and secondary structure",
    icon: "Dna",
    tools: ["LinearDesign", "DNAchisel", "ViennaRNA"],
    implementationState: "planned",
  },
  {
    id: "structure-prediction",
    name: "Structure Prediction",
    description: "Model peptide-MHC complex 3D structures",
    icon: "Box",
    tools: ["Boltz-2", "ESMFold", "Mol*"],
    implementationState: "planned",
  },
  {
    id: "construct-output",
    name: "Construct Output",
    description: "Generate final mRNA sequence for synthesis",
    icon: "FileOutput",
    tools: ["pVACvector", "Biopython"],
    implementationState: "planned",
  },
  {
    id: "ai-review",
    name: "AI Review",
    description: "AI-guided validation and optimization suggestions",
    icon: "Brain",
    tools: ["Claude API", "ESM-C"],
    implementationState: "planned",
  },
];

export function isPipelineStageId(value: string): value is PipelineStageId {
  return PIPELINE_STAGES.some((stage) => stage.id === value);
}

export function getPipelineStage(stageId: PipelineStageId) {
  return PIPELINE_STAGES.find((stage) => stage.id === stageId);
}
