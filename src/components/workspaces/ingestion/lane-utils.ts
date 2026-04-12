import type {
  IngestionLaneProgress,
  IngestionLanePreview,
  SampleLane,
  Workspace,
  WorkspaceFile,
} from "@/lib/types";
import { formatBytes } from "@/lib/workspace-utils";

export const LANES: SampleLane[] = ["normal", "tumor"];
export const INITIAL_VISIBLE_READS = 2;

export type PreviewState = {
  phase: "idle" | "loading" | "ready" | "failed";
  data: IngestionLanePreview | null;
  error: string | null;
};

export function emptyPreviewState(): PreviewState {
  return { phase: "idle", data: null, error: null };
}

export function filePathForDisplay(file: WorkspaceFile) {
  return file.sourcePath ?? file.managedPath ?? file.filename;
}

export function sourceFilesForLane(workspace: Workspace, lane: SampleLane) {
  const activeBatchId = workspace.ingestion.lanes[lane].activeBatchId;
  return workspace.files.filter(
    (file) =>
      file.sampleLane === lane &&
      file.fileRole === "source" &&
      file.batchId === activeBatchId
  );
}

export function totalBytes(files: WorkspaceFile[]) {
  return files.reduce((sum, file) => sum + file.sizeBytes, 0);
}

export function formatProgressPhase(phase: IngestionLaneProgress["phase"]) {
  switch (phase) {
    case "validating":
      return "Validating files";
    case "referencing":
      return "Referencing files";
    case "concatenating":
      return "Combining chunks";
    case "compressing":
      return "Compressing reads";
    case "extracting":
      return "Extracting reads";
    case "finalizing":
      return "Finalizing lane";
    default:
      return "Preparing lane";
  }
}

export function formatEta(seconds?: number | null) {
  if (seconds == null || !Number.isFinite(seconds) || seconds < 0) {
    return null;
  }

  const rounded = Math.round(seconds);
  const minutes = Math.floor(rounded / 60);
  const remainingSeconds = rounded % 60;

  if (minutes <= 0) {
    return `${remainingSeconds}s remaining`;
  }
  if (minutes < 60) {
    return `${minutes}m ${remainingSeconds}s remaining`;
  }

  const hours = Math.floor(minutes / 60);
  const remainingMinutes = minutes % 60;
  return `${hours}h ${remainingMinutes}m remaining`;
}

export function formatThroughput(bytesPerSec?: number | null) {
  if (bytesPerSec == null || !Number.isFinite(bytesPerSec) || bytesPerSec <= 0) {
    return null;
  }
  return `${formatBytes(bytesPerSec)}/s`;
}
