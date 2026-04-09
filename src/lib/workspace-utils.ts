import type {
  IngestionStatus,
  PipelineStage,
  Workspace,
  WorkspaceFile,
  WorkspaceSpecies,
} from "@/lib/types";

export type StageTone = "neutral" | "success" | "warning" | "info";

export interface WorkspaceReadiness {
  activeBatchId?: string | null;
  sourceFiles: WorkspaceFile[];
  canonicalFiles: WorkspaceFile[];
  latestR1?: WorkspaceFile;
  latestR2?: WorkspaceFile;
  hasFiles: boolean;
  hasPairedFastq: boolean;
  sourceCount: number;
  canonicalCount: number;
  totalBytes: number;
  missingPairs: Array<"R1" | "R2">;
  status: IngestionStatus;
  readyForAlignment: boolean;
  failedFiles: WorkspaceFile[];
  pendingFiles: WorkspaceFile[];
}

export function analyzeWorkspace(workspace: Workspace): WorkspaceReadiness {
  const activeBatchId = workspace.ingestion.activeBatchId;
  const batchFiles = workspace.files.filter((file) =>
    activeBatchId ? file.batchId === activeBatchId : true
  );
  const sourceFiles = batchFiles.filter((file) => file.fileRole === "source");
  const canonicalFiles = batchFiles.filter(
    (file) => file.fileRole === "canonical"
  );
  const readyCanonicalFiles = canonicalFiles.filter(
    (file) => file.status === "ready"
  );
  const r1Files = readyCanonicalFiles.filter((file) => file.readPair === "R1");
  const r2Files = readyCanonicalFiles.filter((file) => file.readPair === "R2");

  return {
    activeBatchId,
    sourceFiles,
    canonicalFiles,
    latestR1: r1Files[0],
    latestR2: r2Files[0],
    hasFiles: batchFiles.length > 0,
    hasPairedFastq: workspace.ingestion.readyForAlignment,
    sourceCount: sourceFiles.length,
    canonicalCount: canonicalFiles.length,
    totalBytes: batchFiles.reduce((sum, file) => sum + file.sizeBytes, 0),
    missingPairs: workspace.ingestion.missingPairs.filter(
      (pair): pair is "R1" | "R2" => pair === "R1" || pair === "R2"
    ),
    status: workspace.ingestion.status,
    readyForAlignment: workspace.ingestion.readyForAlignment,
    failedFiles: batchFiles.filter((file) => file.status === "failed"),
    pendingFiles: batchFiles.filter((file) => file.status === "normalizing"),
  };
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

export function getImplementationLabel(stage: PipelineStage) {
  if (stage.implementationState === "live") {
    return "Live";
  }
  if (stage.implementationState === "mock") {
    return "Mock";
  }
  return "Planned";
}

export function getStageStatus(stage: PipelineStage, workspace: Workspace) {
  const readiness = analyzeWorkspace(workspace);

  if (stage.id === "ingestion") {
    if (readiness.status === "ready") {
      return { label: "Ready", tone: "success" as const };
    }
    if (readiness.status === "failed") {
      return { label: "Needs review", tone: "warning" as const };
    }
    if (readiness.status === "normalizing") {
      return { label: "Normalizing", tone: "info" as const };
    }
    if (readiness.hasFiles) {
      return { label: "Missing pair", tone: "warning" as const };
    }
    return { label: "Needs files", tone: "warning" as const };
  }

  if (stage.id === "alignment") {
    if (!readiness.readyForAlignment) {
      return { label: "Waiting", tone: "neutral" as const };
    }
    return { label: "Mock", tone: "info" as const };
  }

  if (stage.implementationState === "mock") {
    return { label: "Mock", tone: "info" as const };
  }

  return { label: "Planned", tone: "neutral" as const };
}
