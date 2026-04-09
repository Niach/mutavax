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
export type WorkspaceFileFormat = "fastq" | "bam" | "cram";
export type WorkspaceFileRole = "source" | "canonical";
export type WorkspaceFileStatus =
  | "uploaded"
  | "normalizing"
  | "ready"
  | "failed";
export type IngestionStatus =
  | "empty"
  | "uploaded"
  | "normalizing"
  | "ready"
  | "failed";
export type ReadPair = "R1" | "R2" | "unknown";
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

export interface IngestionSummary {
  activeBatchId?: string | null;
  status: IngestionStatus;
  readyForAlignment: boolean;
  sourceFileCount: number;
  canonicalFileCount: number;
  missingPairs: ReadPair[];
  updatedAt?: string | null;
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

export interface CreateWorkspaceInput {
  displayName: string;
  species: WorkspaceSpecies;
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
      "Upload sequencing files and normalize them into canonical paired FASTQ for alignment",
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
