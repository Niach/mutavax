import {
  DEMO_ALIGNMENT_SETTINGS,
  DEMO_ALIGNMENT_SUMMARY,
  DEMO_ANNOTATION_SUMMARY,
  DEMO_CONSTRUCT_OUTPUT_SUMMARY,
  DEMO_CONSTRUCT_SUMMARY,
  DEMO_EPITOPE_SUMMARY,
  DEMO_GENE_DOMAINS_RESPONSE,
  DEMO_INGESTION_LANE_PREVIEW,
  DEMO_NEOANTIGEN_SUMMARY,
  DEMO_SYSTEM_MEMORY,
  DEMO_SYSTEM_RESOURCES,
  DEMO_VARIANT_CALLING_SUMMARY,
  DEMO_WORKSPACE,
} from "@/lib/demo-fixtures";
import type {
  AiReviewStageSummary,
  AlignmentSettings,
  AlignmentStageSummary,
  AnnotationStageSummary,
  ConstructOutputStageSummary,
  ConstructStageSummary,
  EpitopeStageSummary,
  GeneDomainsResponse,
  IngestionLanePreview,
  NeoantigenStageSummary,
  PatientAllele,
  SampleLane,
  SystemMemoryResponse,
  SystemResourcesResponse,
  VariantCallingStageSummary,
  Workspace,
} from "@/lib/types";

const DEMO_AI_REVIEW_SUMMARY: AiReviewStageSummary = {
  workspaceId: "demo",
  status: "scaffolded",
  blockingReason:
    "Stage 9 uses Claude Opus 4.7 — configure an API key to try it in a local workspace.",
  model: "anthropic/claude-opus-4-7",
  brief: null,
  result: null,
  decision: null,
  lastError: null,
};

const clone = <T,>(value: T): T =>
  typeof structuredClone === "function" ? structuredClone(value) : JSON.parse(JSON.stringify(value));

async function ok<T>(value: T): Promise<T> {
  return clone(value);
}

export const demoApi = {
  health: async () => ({ status: "ok" }),

  listWorkspaces: async (): Promise<Workspace[]> => ok([DEMO_WORKSPACE]),
  getWorkspace: async (_id: string): Promise<Workspace> => ok(DEMO_WORKSPACE),

  getIngestionLanePreview: async (_wid: string, sampleLane: SampleLane): Promise<IngestionLanePreview> =>
    ok({ ...DEMO_INGESTION_LANE_PREVIEW, sampleLane }),

  createWorkspace: async (): Promise<Workspace> => ok(DEMO_WORKSPACE),
  registerLocalLaneFiles: async (): Promise<Workspace> => ok(DEMO_WORKSPACE),
  resetWorkspaceIngestion: async (): Promise<Workspace> => ok(DEMO_WORKSPACE),
  updateWorkspaceActiveStage: async (): Promise<Workspace> => ok(DEMO_WORKSPACE),
  updateWorkspaceAnalysisProfile: async (): Promise<Workspace> => ok(DEMO_WORKSPACE),

  getAlignmentStageSummary: async (): Promise<AlignmentStageSummary> => ok(DEMO_ALIGNMENT_SUMMARY),
  runAlignment: async (): Promise<AlignmentStageSummary> => ok(DEMO_ALIGNMENT_SUMMARY),
  rerunAlignment: async (): Promise<AlignmentStageSummary> => ok(DEMO_ALIGNMENT_SUMMARY),
  cancelAlignment: async (): Promise<AlignmentStageSummary> => ok(DEMO_ALIGNMENT_SUMMARY),
  pauseAlignment: async (): Promise<AlignmentStageSummary> => ok(DEMO_ALIGNMENT_SUMMARY),
  resumeAlignment: async (): Promise<AlignmentStageSummary> => ok(DEMO_ALIGNMENT_SUMMARY),

  getVariantCallingStageSummary: async (): Promise<VariantCallingStageSummary> => ok(DEMO_VARIANT_CALLING_SUMMARY),
  runVariantCalling: async (): Promise<VariantCallingStageSummary> => ok(DEMO_VARIANT_CALLING_SUMMARY),
  rerunVariantCalling: async (): Promise<VariantCallingStageSummary> => ok(DEMO_VARIANT_CALLING_SUMMARY),
  cancelVariantCalling: async (): Promise<VariantCallingStageSummary> => ok(DEMO_VARIANT_CALLING_SUMMARY),
  pauseVariantCalling: async (): Promise<VariantCallingStageSummary> => ok(DEMO_VARIANT_CALLING_SUMMARY),
  resumeVariantCalling: async (): Promise<VariantCallingStageSummary> => ok(DEMO_VARIANT_CALLING_SUMMARY),

  getAnnotationStageSummary: async (): Promise<AnnotationStageSummary> => ok(DEMO_ANNOTATION_SUMMARY),
  runAnnotation: async (): Promise<AnnotationStageSummary> => ok(DEMO_ANNOTATION_SUMMARY),
  rerunAnnotation: async (): Promise<AnnotationStageSummary> => ok(DEMO_ANNOTATION_SUMMARY),
  cancelAnnotation: async (): Promise<AnnotationStageSummary> => ok(DEMO_ANNOTATION_SUMMARY),
  pauseAnnotation: async (): Promise<AnnotationStageSummary> => ok(DEMO_ANNOTATION_SUMMARY),
  resumeAnnotation: async (): Promise<AnnotationStageSummary> => ok(DEMO_ANNOTATION_SUMMARY),

  getGeneProteinDomains: async (): Promise<GeneDomainsResponse> => ok(DEMO_GENE_DOMAINS_RESPONSE),

  getNeoantigenStageSummary: async (): Promise<NeoantigenStageSummary> => ok(DEMO_NEOANTIGEN_SUMMARY),
  runNeoantigen: async (): Promise<NeoantigenStageSummary> => ok(DEMO_NEOANTIGEN_SUMMARY),
  rerunNeoantigen: async (): Promise<NeoantigenStageSummary> => ok(DEMO_NEOANTIGEN_SUMMARY),
  cancelNeoantigen: async (): Promise<NeoantigenStageSummary> => ok(DEMO_NEOANTIGEN_SUMMARY),
  pauseNeoantigen: async (): Promise<NeoantigenStageSummary> => ok(DEMO_NEOANTIGEN_SUMMARY),
  resumeNeoantigen: async (): Promise<NeoantigenStageSummary> => ok(DEMO_NEOANTIGEN_SUMMARY),
  updateNeoantigenAlleles: async (_wid: string, alleles: PatientAllele[]): Promise<NeoantigenStageSummary> =>
    ok({ ...DEMO_NEOANTIGEN_SUMMARY, alleles }),

  getSystemMemory: async (): Promise<SystemMemoryResponse> => ok(DEMO_SYSTEM_MEMORY),
  getSystemResources: async (): Promise<SystemResourcesResponse> => ok(DEMO_SYSTEM_RESOURCES),

  getAlignmentSettings: async (): Promise<AlignmentSettings> => ok(DEMO_ALIGNMENT_SETTINGS),
  updateAlignmentSettings: async (): Promise<AlignmentSettings> => ok(DEMO_ALIGNMENT_SETTINGS),

  getEpitopeStageSummary: async (): Promise<EpitopeStageSummary> => ok(DEMO_EPITOPE_SUMMARY),
  updateEpitopeSelection: async (_wid: string, selection: string[]): Promise<EpitopeStageSummary> =>
    ok({ ...DEMO_EPITOPE_SUMMARY, selection }),

  getConstructStageSummary: async (): Promise<ConstructStageSummary> => ok(DEMO_CONSTRUCT_SUMMARY),
  updateConstructOptions: async (): Promise<ConstructStageSummary> => ok(DEMO_CONSTRUCT_SUMMARY),

  getConstructOutputSummary: async (): Promise<ConstructOutputStageSummary> => ok(DEMO_CONSTRUCT_OUTPUT_SUMMARY),
  updateConstructOutput: async (): Promise<ConstructOutputStageSummary> => ok(DEMO_CONSTRUCT_OUTPUT_SUMMARY),

  getAiReviewSummary: async (): Promise<AiReviewStageSummary> => ok(DEMO_AI_REVIEW_SUMMARY),
  runAiReview: async (): Promise<AiReviewStageSummary> => ok(DEMO_AI_REVIEW_SUMMARY),
  acceptAiReview: async (): Promise<AiReviewStageSummary> => ok(DEMO_AI_REVIEW_SUMMARY),
  overrideAiReview: async (): Promise<AiReviewStageSummary> => ok(DEMO_AI_REVIEW_SUMMARY),
  resetAiReview: async (): Promise<AiReviewStageSummary> => ok(DEMO_AI_REVIEW_SUMMARY),
};
