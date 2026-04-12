import type {
  AlignmentStageSummary,
  IngestionStatus,
  PipelineStage,
  ReadPair,
  ReadLayout,
  ReferencePreset,
  SampleLane,
  Workspace,
  WorkspaceFile,
  WorkspaceSpecies,
} from "@/lib/types";

export type StageTone = "neutral" | "success" | "warning" | "info";

export interface LaneWorkspaceReadiness {
  sampleLane: SampleLane;
  summary: Workspace["ingestion"]["lanes"]["tumor"];
  sourceFiles: WorkspaceFile[];
  canonicalFiles: WorkspaceFile[];
  totalBytes: number;
  hasFiles: boolean;
  failedFiles: WorkspaceFile[];
  pendingFiles: WorkspaceFile[];
}

export interface WorkspaceReadiness {
  lanes: Record<SampleLane, LaneWorkspaceReadiness>;
  status: IngestionStatus;
  readyForAlignment: boolean;
}

export interface RequiredOutputStatus {
  id: `${SampleLane}-${Extract<ReadPair, "R1" | "R2">}`;
  sampleLane: SampleLane;
  readPair: Extract<ReadPair, "R1" | "R2">;
  label: string;
  ready: boolean;
}

function getLaneBatchFiles(
  workspace: Workspace,
  sampleLane: SampleLane
): WorkspaceFile[] {
  const lane = workspace.ingestion.lanes[sampleLane];
  if (!lane.activeBatchId) {
    return [];
  }

  return workspace.files.filter(
    (file) => file.sampleLane === sampleLane && file.batchId === lane.activeBatchId
  );
}

export function getLaneReadyCanonicalPairs(
  workspace: Workspace,
  sampleLane: SampleLane
): Array<Extract<ReadPair, "R1" | "R2">> {
  const summary = workspace.ingestion.lanes[sampleLane];
  if (summary.canonicalFileCount <= 0) {
    return [];
  }

  return (["R1", "R2"] as const).filter(
    (readPair) => !summary.missingPairs.includes(readPair)
  );
}

export function getWorkspaceRequiredOutputs(
  workspace: Workspace
): RequiredOutputStatus[] {
  return (["tumor", "normal"] as const).flatMap((sampleLane) => {
    const readyPairs = new Set(getLaneReadyCanonicalPairs(workspace, sampleLane));
    return (["R1", "R2"] as const).map((readPair) => ({
      id: `${sampleLane}-${readPair}`,
      sampleLane,
      readPair,
      label: `${formatLaneLabel(sampleLane)} ${readPair}`,
      ready: readyPairs.has(readPair),
    }));
  });
}

export function countReadyRequiredOutputs(workspace: Workspace) {
  return getWorkspaceRequiredOutputs(workspace).filter((output) => output.ready)
    .length;
}

export function analyzeWorkspace(workspace: Workspace): WorkspaceReadiness {
  const lanes = {
    tumor: buildLaneReadiness(workspace, "tumor"),
    normal: buildLaneReadiness(workspace, "normal"),
  };

  return {
    lanes,
    status: workspace.ingestion.status,
    readyForAlignment: workspace.ingestion.readyForAlignment,
  };
}

function buildLaneReadiness(
  workspace: Workspace,
  sampleLane: SampleLane
): LaneWorkspaceReadiness {
  const files = getLaneBatchFiles(workspace, sampleLane);
  const sourceFiles = files.filter((file) => file.fileRole === "source");
  const canonicalFiles = files.filter((file) => file.fileRole === "canonical");

  return {
    sampleLane,
    summary: workspace.ingestion.lanes[sampleLane],
    sourceFiles,
    canonicalFiles,
    totalBytes: files.reduce((sum, file) => sum + file.sizeBytes, 0),
    hasFiles: files.length > 0,
    failedFiles: files.filter((file) => file.status === "failed"),
    pendingFiles: files.filter((file) => file.status === "normalizing"),
  };
}

export function getLaneMissingPairs(
  workspace: Workspace,
  sampleLane: SampleLane
): Array<Extract<ReadPair, "R1" | "R2">> {
  return workspace.ingestion.lanes[sampleLane].missingPairs.filter(
    (pair): pair is Extract<ReadPair, "R1" | "R2"> =>
      pair === "R1" || pair === "R2"
  );
}

export function getCompactIssueLabel(issue?: string | null) {
  if (!issue) {
    return null;
  }

  const normalized = issue.trim();
  const lower = normalized.toLowerCase();

  if (lower.includes("matching r1")) {
    return "Missing R1";
  }
  if (lower.includes("matching r2")) {
    return "Missing R2";
  }
  if (lower.includes("at least one r1 and one r2")) {
    return "Missing R1 + R2";
  }
  if (lower.includes("paired-end required") && lower.includes("r2 file")) {
    return "Add R2 file";
  }
  if (lower.includes("paired-end required") && lower.includes("don't encode")) {
    return "Rename with _R1_/_R2_";
  }
  if (lower.includes("paired-end required")) {
    return "Paired-end required";
  }
  if (lower.includes("one format family only")) {
    return "Mixed file types";
  }
  if (lower.includes("exactly one bam or cram")) {
    return "One BAM/CRAM only";
  }
  if (lower.includes("cannot mix")) {
    return "Mixed read naming";
  }
  if (lower.includes("sample family")) {
    return "Mixed samples";
  }
  if (lower.includes("paired or single-end")) {
    return "Read layout unclear";
  }
  if (lower.includes("upload at least one sequencing file")) {
    return "Awaiting files";
  }
  if (lower.includes("malformed sequence preview")) {
    return "Preview malformed";
  }
  if (lower.includes("unable to read sequence preview")) {
    return "Preview unavailable";
  }
  if (lower.includes("unable to decode sequence preview")) {
    return "Preview unavailable";
  }

  return normalized.length <= 28 ? normalized : null;
}

export function getLaneIssueLabel(summary: Workspace["ingestion"]["lanes"]["tumor"]) {
  const missingPairs = summary.missingPairs.filter(
    (pair): pair is Extract<ReadPair, "R1" | "R2"> =>
      pair === "R1" || pair === "R2"
  );

  if (missingPairs.length > 0) {
    return `Need ${missingPairs.join(" + ")}`;
  }

  return getCompactIssueLabel(summary.blockingIssues[0]) ?? "Intake failed";
}

export function getLaneStatusLabel(summary: Workspace["ingestion"]["lanes"]["tumor"]) {
  if (summary.status === "ready") {
    return "2/2 ready";
  }
  if (summary.status === "normalizing") {
    return "Preparing";
  }
  if (summary.status === "uploading" || summary.status === "uploaded") {
    return "Queued";
  }
  if (summary.status === "failed") {
    return getLaneIssueLabel(summary);
  }
  return "Awaiting files";
}

export function formatReadLayoutLabel(readLayout?: ReadLayout | null) {
  if (readLayout === "paired") {
    return "paired";
  }
  if (readLayout === "single") {
    return "single-end";
  }
  return "—";
}

export function formatBytes(bytes: number) {
  if (bytes <= 0) {
    return "0 B";
  }

  const units = ["B", "KB", "MB", "GB", "TB"];
  const exponent = Math.min(
    Math.floor(Math.log(bytes) / Math.log(1024)),
    units.length - 1
  );
  const value = bytes / 1024 ** exponent;

  return `${value.toFixed(value >= 10 || exponent === 0 ? 0 : 1)} ${units[exponent]}`;
}

export function formatDateTime(value: string) {
  return new Intl.DateTimeFormat("en", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

export function formatSpeciesLabel(species: WorkspaceSpecies) {
  if (species === "dog") {
    return "Dog";
  }
  if (species === "human") {
    return "Human";
  }
  return "Cat";
}

export function formatLaneLabel(sampleLane: SampleLane) {
  return sampleLane === "tumor" ? "Tumor" : "Normal";
}

export function formatAssayType(assayType?: "wgs" | "wes" | null) {
  if (assayType === "wes") {
    return "WES";
  }
  if (assayType === "wgs") {
    return "WGS";
  }
  return "Unset";
}

export function formatReferencePreset(referencePreset?: ReferencePreset | null) {
  if (referencePreset === "canfam4") {
    return "CanFam4";
  }
  if (referencePreset === "felcat9") {
    return "felCat9";
  }
  if (referencePreset === "grch38") {
    return "GRCh38";
  }
  return "Custom";
}

export function getQcVerdictLabel(
  qcVerdict?: AlignmentStageSummary["qcVerdict"] | null
) {
  if (qcVerdict === "pass") {
    return "Pass";
  }
  if (qcVerdict === "warn") {
    return "Warn";
  }
  if (qcVerdict === "fail") {
    return "Fail";
  }
  return "Pending";
}

export function getAlignmentStatusCopy(
  summary?: AlignmentStageSummary | null
) {
  if (!summary) {
    return { label: "Waiting", tone: "warning" as const };
  }

  if (summary.status === "blocked") {
    return { label: "Blocked", tone: "warning" as const };
  }
  if (summary.status === "ready") {
    return { label: "Ready", tone: "success" as const };
  }
  if (summary.status === "running") {
    return { label: "Running", tone: "info" as const };
  }
  if (summary.status === "failed") {
    return { label: "Failed", tone: "warning" as const };
  }
  return {
    label: summary.qcVerdict === "warn" ? "Complete (warn)" : "Complete",
    tone:
      summary.qcVerdict === "warn"
        ? ("warning" as const)
        : ("success" as const),
  };
}

export function getImplementationLabel(stage: PipelineStage) {
  if (stage.implementationState === "live") {
    return "Live";
  }
  if (stage.implementationState === "mock") {
    return "Mock";
  }
  return "Planned";
}

export function getStageStatus(
  stage: PipelineStage,
  workspace: Workspace,
  alignmentSummary?: AlignmentStageSummary | null
) {
  const readiness = analyzeWorkspace(workspace);

  if (stage.id === "ingestion") {
    if (readiness.status === "ready") {
      return { label: "Ready", tone: "success" as const };
    }
    if (readiness.status === "failed") {
      return { label: "Needs review", tone: "warning" as const };
    }
    if (
      readiness.status === "normalizing" ||
      readiness.status === "uploading"
    ) {
      return { label: "In progress", tone: "info" as const };
    }
    return { label: "Waiting", tone: "warning" as const };
  }

  if (stage.id === "alignment") {
    return getAlignmentStatusCopy(alignmentSummary);
  }

  if (stage.id === "variant-calling") {
    if (!alignmentSummary?.readyForVariantCalling) {
      return { label: "Locked", tone: "warning" as const };
    }
    return { label: "Planned", tone: "neutral" as const };
  }

  return { label: "Planned", tone: "neutral" as const };
}
