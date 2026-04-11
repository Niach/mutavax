"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { FileText, LoaderCircle, Upload } from "lucide-react";

import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import type {
  IngestionLanePreview,
  SampleLane,
  UploadSession,
  UploadSessionFile,
  Workspace,
} from "@/lib/types";
import { cn } from "@/lib/utils";
import {
  getCompactIssueLabel,
  formatBytes,
  formatLaneLabel,
  formatReadLayoutLabel,
  getLaneIssueLabel,
} from "@/lib/workspace-utils";
import {
  InstrumentTraceRow,
  PreviewLegend,
  SampledReadoutStrip,
  deriveLaneInsight,
  formatPreviewMetric,
  formatPreviewPercent,
} from "./ingestion/ReadPreviewCard";
import { LaneStagingPanel } from "./ingestion/LaneStagingPanel";
import { LaneReattachPanel } from "./ingestion/LaneReattachPanel";
import {
  type DetectedReadPair,
  type LaneStagingValidation,
  inferReadPair,
  validateStagedFiles,
} from "./ingestion/inferReadPair";

const INITIAL_VISIBLE_READS = 2;

interface IngestionStagePanelProps {
  workspace: Workspace;
  onWorkspaceChange: (workspace: Workspace) => void;
}

type LanePhase =
  | "idle"
  | "queued"
  | "uploading"
  | "paused"
  | "normalizing"
  | "ready"
  | "failed";

interface LaneStagingState {
  files: File[];
  detection: Record<string, DetectedReadPair>;
  validation: LaneStagingValidation;
  dragActive: boolean;
  starting: boolean;
}

interface LaneUploadState {
  session: UploadSession | null;
  phase: LanePhase;
  error: string | null;
  message: string | null;
  selectedFiles: Record<string, File>;
  transientBytes: Record<string, number>;
  needsReselect: boolean;
  dragActive: boolean;
  staging: LaneStagingState;
}

type PreviewPhase = "idle" | "loading" | "ready" | "failed";

interface LanePreviewState {
  phase: PreviewPhase;
  data: IngestionLanePreview | null;
  error: string | null;
  autoRetryUsed: boolean;
}

interface LaneDisplayState {
  label: string;
  summary: string;
  detail: string | null;
  tone: "idle" | "active" | "ready" | "failed";
}

const LANES: SampleLane[] = ["tumor", "normal"];

function createInitialStagingState(): LaneStagingState {
  return {
    files: [],
    detection: {},
    validation: { state: "empty", reason: null, sampleStem: null },
    dragActive: false,
    starting: false,
  };
}

function createInitialLaneState(): LaneUploadState {
  return {
    session: null,
    phase: "idle",
    error: null,
    message: null,
    selectedFiles: {},
    transientBytes: {},
    needsReselect: false,
    dragActive: false,
    staging: createInitialStagingState(),
  };
}

function createInitialPreviewState(): LanePreviewState {
  return {
    phase: "idle",
    data: null,
    error: null,
    autoRetryUsed: false,
  };
}

function buildStagingFromFiles(files: File[]): LaneStagingState {
  const detection: Record<string, DetectedReadPair> = {};
  for (const file of files) {
    detection[fingerprintFile(file)] = inferReadPair(file.name);
  }
  return {
    files,
    detection,
    validation: validateStagedFiles(files),
    dragActive: false,
    starting: false,
  };
}

function fingerprintFile(file: File) {
  return `${file.name}:${file.size}:${file.lastModified}`;
}

function filesByFingerprint(files: File[]) {
  return Object.fromEntries(files.map((file) => [fingerprintFile(file), file]));
}

function sessionMatchesFiles(session: UploadSession, files: File[]) {
  if (session.files.length !== files.length) {
    return false;
  }

  const fingerprints = new Set(files.map(fingerprintFile));
  return session.files.every((file) => fingerprints.has(file.fingerprint));
}

function updateSessionFile(
  session: UploadSession,
  fileId: string,
  updater: (file: UploadSessionFile) => UploadSessionFile
): UploadSession {
  return {
    ...session,
    files: session.files.map((file) =>
      file.id === fileId ? updater(file) : file
    ),
  };
}

function getDisplayUploadedBytes(
  sessionFile: UploadSessionFile,
  transientBytes: Record<string, number>
) {
  return Math.min(
    sessionFile.sizeBytes,
    sessionFile.uploadedBytes + (transientBytes[sessionFile.id] ?? 0)
  );
}

function getTransferTotals(laneState: LaneUploadState) {
  if (!laneState.session) {
    return { uploadedBytes: 0, totalBytes: 0, percent: 0 };
  }

  const totalBytes = laneState.session.files.reduce(
    (sum, file) => sum + file.sizeBytes,
    0
  );
  const uploadedBytes = laneState.session.files.reduce(
    (sum, file) => sum + getDisplayUploadedBytes(file, laneState.transientBytes),
    0
  );
  const percent = totalBytes === 0 ? 0 : (uploadedBytes / totalBytes) * 100;

  return { uploadedBytes, totalBytes, percent };
}

function laneAccentVar(lane: SampleLane) {
  return lane === "tumor" ? "var(--lane-tumor)" : "var(--lane-normal)";
}

function joinSummaryParts(parts: Array<string | null | undefined>) {
  return parts.filter(Boolean).join(" · ");
}

function getLaneSourceBytes(workspace: Workspace, sampleLane: SampleLane) {
  const batchId = workspace.ingestion.lanes[sampleLane].activeBatchId;
  if (!batchId) {
    return 0;
  }

  return workspace.files
    .filter(
      (file) =>
        file.batchId === batchId &&
        file.sampleLane === sampleLane &&
        file.fileRole === "source"
    )
    .reduce((sum, file) => sum + file.sizeBytes, 0);
}

function getPreviewMetricTokens(previewState: LanePreviewState) {
  if (previewState.phase !== "ready" || !previewState.data?.stats) {
    return [];
  }

  const reads = [
    ...(previewState.data.reads.R1 ?? []),
    ...(previewState.data.reads.R2 ?? []),
    ...(previewState.data.reads.SE ?? []),
  ];
  const insight = deriveLaneInsight(reads);
  const meanQuality =
    insight.meanQualities.length === 0
      ? 0
      : insight.meanQualities.reduce((sum, value) => sum + value, 0) /
        insight.meanQualities.length;

  return [
    `${formatPreviewMetric(previewState.data.stats.averageReadLength)} nt`,
    `${formatPreviewPercent(previewState.data.stats.sampledGcPercent)} GC`,
    `Q${formatPreviewMetric(meanQuality)}`,
  ];
}

function getLaneDisplayState({
  workspace,
  sampleLane,
  laneState,
  previewState,
}: {
  workspace: Workspace;
  sampleLane: SampleLane;
  laneState: LaneUploadState;
  previewState: LanePreviewState;
}): LaneDisplayState {
  const summary = workspace.ingestion.lanes[sampleLane];
  const transfer = getTransferTotals(laneState);
  const fileCount = laneState.session?.files.length ?? summary.sourceFileCount;
  const totalBytes =
    laneState.session?.files.reduce((sum, file) => sum + file.sizeBytes, 0) ??
    getLaneSourceBytes(workspace, sampleLane);
  const metadata = [
    summary.readLayout ? formatReadLayoutLabel(summary.readLayout) : null,
    fileCount > 0 ? `${fileCount} file${fileCount === 1 ? "" : "s"}` : null,
    totalBytes > 0 ? formatBytes(totalBytes) : null,
  ];

  if (laneState.phase === "queued" || laneState.phase === "uploading") {
    return {
      label: "Uploading",
      summary:
        transfer.totalBytes > 0
          ? `${formatBytes(transfer.uploadedBytes)} of ${formatBytes(
              transfer.totalBytes
            )} · ${Math.round(transfer.percent)}%`
          : "Sending files",
      detail: null,
      tone: "active",
    };
  }

  if (laneState.phase === "paused") {
    return {
      label: "Paused",
      summary: laneState.needsReselect
        ? "Reattach files below to resume"
        : transfer.totalBytes > 0
          ? `${formatBytes(transfer.uploadedBytes)} of ${formatBytes(
              transfer.totalBytes
            )} uploaded`
          : "Ready to resume",
      detail: null,
      tone: "active",
    };
  }

  if (laneState.phase === "normalizing") {
    return {
      label: "Preparing",
      summary: "Preparing canonical FASTQ",
      detail: null,
      tone: "active",
    };
  }

  if (laneState.phase === "ready") {
    return {
      label: "Ready",
      summary: joinSummaryParts([
        ...metadata,
        ...getPreviewMetricTokens(previewState),
        previewState.phase === "loading" ? "Sampling QC" : null,
        previewState.phase === "failed" ? "Preview unavailable" : null,
      ]),
      detail:
        previewState.phase === "failed"
          ? previewState.error ?? "Unable to load the sequence preview."
          : null,
      tone: "ready",
    };
  }

  if (laneState.phase === "failed") {
    const detail = laneState.error ?? summary.blockingIssues[0] ?? null;
    const primaryIssue =
      summary.status === "failed"
        ? getLaneIssueLabel(summary)
        : getCompactIssueLabel(detail) ?? "Upload failed";

    return {
      label: primaryIssue,
      summary:
        joinSummaryParts(metadata) || "Upload new files to continue",
      detail:
        detail && detail !== primaryIssue
          ? detail
          : laneState.message && laneState.message !== primaryIssue
            ? laneState.message
            : null,
      tone: "failed",
    };
  }

  return {
    label: "Awaiting files",
    summary: "FASTQ, BAM, or CRAM",
    detail: null,
    tone: "idle",
  };
}

export default function IngestionStagePanel({
  workspace,
  onWorkspaceChange,
}: IngestionStagePanelProps) {
  const fileInputRefs = useRef<Record<SampleLane, HTMLInputElement | null>>({
    tumor: null,
    normal: null,
  });
  const abortControllers = useRef<Record<SampleLane, AbortController | null>>({
    tumor: null,
    normal: null,
  });

  const [laneStates, setLaneStates] = useState<Record<SampleLane, LaneUploadState>>({
    tumor: createInitialLaneState(),
    normal: createInitialLaneState(),
  });
  const [previewStates, setPreviewStates] = useState<
    Record<SampleLane, LanePreviewState>
  >({
    tumor: createInitialPreviewState(),
    normal: createInitialPreviewState(),
  });
  const [expandedPreviewLane, setExpandedPreviewLane] = useState<SampleLane | null>(
    null
  );
  const tumorLaneSummary = workspace.ingestion.lanes.tumor;
  const normalLaneSummary = workspace.ingestion.lanes.normal;

  useEffect(() => {
    setLaneStates({
      tumor: createInitialLaneState(),
      normal: createInitialLaneState(),
    });
    setPreviewStates({
      tumor: createInitialPreviewState(),
      normal: createInitialPreviewState(),
    });
    setExpandedPreviewLane(null);

    void api
      .listUploadSessions(workspace.id)
      .then((sessions) => {
        setLaneStates((current) => {
          const next = { ...current };
          for (const lane of LANES) {
            const session = sessions.find((item) => item.sampleLane === lane) ?? null;
            if (!session) {
              continue;
            }
            next[lane] = {
              ...next[lane],
              session,
              phase:
                session.status === "failed"
                  ? "failed"
                  : session.status === "uploaded"
                    ? "queued"
                    : "paused",
              error: session.error ?? null,
              message:
                session.status === "uploaded"
                  ? "Transfer finished. Start normalization when ready."
                  : "Reselect the same files to resume the remaining chunks.",
              needsReselect: session.status !== "uploaded",
            };
          }
          return next;
        });
      })
      .catch(() => {});
  }, [workspace.id]);

  useEffect(() => {
    if (!LANES.some((lane) => workspace.ingestion.lanes[lane].status === "normalizing")) {
      return;
    }

    const interval = window.setInterval(() => {
      void api
        .getWorkspace(workspace.id)
        .then((updatedWorkspace) => {
          onWorkspaceChange(updatedWorkspace);
        })
        .catch(() => {});
    }, 2500);

    return () => window.clearInterval(interval);
  }, [onWorkspaceChange, workspace.id, workspace.ingestion]);

  useEffect(() => {
    setLaneStates((current) => {
      const next = { ...current };

      for (const lane of LANES) {
        const summary = workspace.ingestion.lanes[lane];
        const state = current[lane];

        if (summary.status === "normalizing" && state.phase !== "uploading") {
          next[lane] = {
            ...state,
            phase: "normalizing",
            error: null,
            message: "Preparing canonical FASTQ.",
          };
          continue;
        }

        if (summary.status === "ready") {
          next[lane] = {
            ...state,
            phase: "ready",
            error: null,
            message: "Canonical FASTQ is ready.",
          };
          continue;
        }

        if (
          summary.status === "failed" &&
          state.phase !== "uploading" &&
          state.phase !== "paused"
        ) {
          next[lane] = {
            ...state,
            phase: "failed",
            error: summary.blockingIssues.join(" ") || state.error || "Upload failed.",
          };
          continue;
        }

        if (summary.status === "empty" && !state.session) {
          next[lane] = { ...createInitialLaneState(), staging: state.staging };
        }
      }

      return next;
    });
  }, [workspace]);

  useEffect(() => {
    setPreviewStates((current) => {
      const next = { ...current };
      let changed = false;

      for (const lane of LANES) {
        const summary = lane === "tumor" ? tumorLaneSummary : normalLaneSummary;
        const state = current[lane];

        if (summary.status !== "ready") {
          if (
            state.phase !== "idle" ||
            state.data !== null ||
            state.error !== null
          ) {
            next[lane] = createInitialPreviewState();
            changed = true;
          }
          continue;
        }

        if (state.data && state.data.batchId !== summary.activeBatchId) {
          next[lane] = createInitialPreviewState();
          changed = true;
        }
      }

      return changed ? next : current;
    });
  }, [normalLaneSummary, tumorLaneSummary, workspace.id]);

  useEffect(() => {
    if (
      expandedPreviewLane &&
      workspace.ingestion.lanes[expandedPreviewLane].status !== "ready"
    ) {
      setExpandedPreviewLane(null);
    }
  }, [expandedPreviewLane, workspace.ingestion.lanes]);

  function setLaneState(
    sampleLane: SampleLane,
    updater: (state: LaneUploadState) => LaneUploadState
  ) {
    setLaneStates((current) => ({
      ...current,
      [sampleLane]: updater(current[sampleLane]),
    }));
  }

  const loadLanePreview = useCallback(
    async (sampleLane: SampleLane, options: { manual?: boolean } = {}) => {
      setPreviewStates((current) => ({
        ...current,
        [sampleLane]: {
          ...current[sampleLane],
          phase: "loading",
          error: null,
          // A manual retry resets the auto-retry budget so the next failure
          // can again attempt one silent recovery.
          autoRetryUsed: options.manual ? false : current[sampleLane].autoRetryUsed,
        },
      }));

      try {
        const preview = await api.getIngestionLanePreview(workspace.id, sampleLane);
        setPreviewStates((current) => ({
          ...current,
          [sampleLane]: {
            ...current[sampleLane],
            phase: "ready",
            data: preview,
            error: null,
            autoRetryUsed: false,
          },
        }));
      } catch (error) {
        const message =
          error instanceof Error
            ? error.message
            : "Unable to load the sequence preview";

        let shouldAutoRetry = false;
        setPreviewStates((current) => {
          const previous = current[sampleLane];
          if (!previous.autoRetryUsed) {
            shouldAutoRetry = true;
            return {
              ...current,
              [sampleLane]: {
                ...previous,
                phase: "loading",
                error: null,
                autoRetryUsed: true,
              },
            };
          }
          return {
            ...current,
            [sampleLane]: {
              ...previous,
              phase: "failed",
              error: message,
            },
          };
        });

        if (shouldAutoRetry) {
          window.setTimeout(() => {
            void loadLanePreview(sampleLane);
          }, 1000);
        }
      }
    },
    [workspace.id]
  );

  const tumorPreviewPhase = previewStates.tumor.phase;
  const normalPreviewPhase = previewStates.normal.phase;

  useEffect(() => {
    const phaseByLane: Record<SampleLane, PreviewPhase> = {
      tumor: tumorPreviewPhase,
      normal: normalPreviewPhase,
    };

    for (const lane of LANES) {
      if (
        workspace.ingestion.lanes[lane].status === "ready" &&
        phaseByLane[lane] === "idle"
      ) {
        void loadLanePreview(lane);
      }
    }
  }, [
    loadLanePreview,
    normalPreviewPhase,
    tumorPreviewPhase,
    workspace.ingestion.lanes,
  ]);

  function handleStageFiles(
    sampleLane: SampleLane,
    fileList: FileList | File[] | null
  ) {
    const incoming = Array.from(fileList ?? []);
    if (incoming.length === 0) {
      return;
    }

    setLaneState(sampleLane, (state) => {
      // Refuse to mutate staging while an upload-session-bound flow is active.
      if (
        state.session ||
        (state.phase !== "idle" && state.phase !== "failed")
      ) {
        return state;
      }

      const merged = new Map<string, File>();
      for (const file of state.staging.files) {
        merged.set(fingerprintFile(file), file);
      }
      for (const file of incoming) {
        merged.set(fingerprintFile(file), file);
      }
      const orderedFiles = Array.from(merged.values());

      return {
        ...state,
        staging: buildStagingFromFiles(orderedFiles),
      };
    });
  }

  function handleRemoveStaged(sampleLane: SampleLane, fingerprint: string) {
    setLaneState(sampleLane, (state) => {
      const remaining = state.staging.files.filter(
        (file) => fingerprintFile(file) !== fingerprint
      );
      return {
        ...state,
        staging: buildStagingFromFiles(remaining),
      };
    });
  }

  function handleDiscardStaging(sampleLane: SampleLane) {
    setLaneState(sampleLane, (state) => ({
      ...state,
      staging: createInitialStagingState(),
    }));
  }

  function handleStagingDragActive(sampleLane: SampleLane, active: boolean) {
    setLaneState(sampleLane, (state) => ({
      ...state,
      staging: { ...state.staging, dragActive: active },
    }));
  }

  async function handleStartUpload(sampleLane: SampleLane) {
    const currentState = laneStates[sampleLane];
    const stagedFiles = currentState.staging.files;
    if (
      stagedFiles.length === 0 ||
      currentState.staging.validation.state !== "ready" ||
      currentState.staging.starting
    ) {
      return;
    }

    abortControllers.current[sampleLane]?.abort();

    setLaneState(sampleLane, (state) => ({
      ...state,
      staging: { ...state.staging, starting: true },
    }));

    const selectedFiles = filesByFingerprint(stagedFiles);

    let session: UploadSession | null = null;
    try {
      // Reuse a matching open session if one already exists for this lane —
      // covers the case where Start was clicked, the request raced, and the
      // user re-attempted with the same set.
      const sessions = await api.listUploadSessions(workspace.id);
      session =
        sessions.find(
          (item) =>
            item.sampleLane === sampleLane &&
            sessionMatchesFiles(item, stagedFiles)
        ) ?? null;

      if (!session) {
        session = await api.createUploadSession(workspace.id, {
          sampleLane,
          files: stagedFiles.map((file) => ({
            filename: file.name,
            sizeBytes: file.size,
            lastModifiedMs: file.lastModified,
            contentType: file.type || undefined,
          })),
        });
      }
    } catch (error) {
      setLaneState(sampleLane, (state) => ({
        ...state,
        staging: { ...state.staging, starting: false },
        error:
          error instanceof Error
            ? error.message
            : "Unable to start the upload session",
      }));
      return;
    }

    setLaneState(sampleLane, (state) => ({
      ...state,
      session,
      phase: "queued",
      error: null,
      message:
        session && session.files.some((file) => file.uploadedBytes > 0)
          ? "Resuming the remaining chunks for these files."
          : "Upload queued. Chunk transfer will start now.",
      selectedFiles,
      transientBytes: {},
      needsReselect: false,
      staging: createInitialStagingState(),
    }));

    if (session.status === "uploaded") {
      await finalizeLane(sampleLane, session);
      return;
    }

    await uploadLane(sampleLane, session, selectedFiles);
  }

  async function handleReattachFiles(
    sampleLane: SampleLane,
    fileList: FileList | File[] | null
  ) {
    const incoming = Array.from(fileList ?? []);
    if (incoming.length === 0) {
      return;
    }

    const currentState = laneStates[sampleLane];
    const session = currentState.session;
    if (!session) {
      return;
    }

    abortControllers.current[sampleLane]?.abort();

    // Match incoming Files to session entries by fingerprint. Anything that
    // doesn't match is silently ignored — the panel only resumes what the
    // session knows about.
    const sessionFingerprints = new Set(
      session.files.map((file) => file.fingerprint)
    );
    const matched: File[] = [];
    for (const file of incoming) {
      if (sessionFingerprints.has(fingerprintFile(file))) {
        matched.push(file);
      }
    }

    if (matched.length === 0) {
      setLaneState(sampleLane, (state) => ({
        ...state,
        message:
          "Those files don't match this session. Pick the originals to resume.",
      }));
      return;
    }

    const selectedFiles = filesByFingerprint(matched);

    setLaneState(sampleLane, (state) => ({
      ...state,
      selectedFiles: { ...state.selectedFiles, ...selectedFiles },
      needsReselect: false,
      error: null,
      message: null,
    }));

    if (session.status === "uploaded") {
      await finalizeLane(sampleLane, session);
      return;
    }

    await uploadLane(sampleLane, session, {
      ...currentState.selectedFiles,
      ...selectedFiles,
    });
  }

  async function handleDiscardSession(sampleLane: SampleLane) {
    const session = laneStates[sampleLane].session;
    if (!session) {
      return;
    }
    abortControllers.current[sampleLane]?.abort();

    try {
      const updatedWorkspace = await api.deleteUploadSession(
        workspace.id,
        session.id
      );
      onWorkspaceChange(updatedWorkspace);
    } catch (error) {
      // If the backend doesn't expose DELETE yet, fall back to local reset
      // so the user can move forward.
      if (process.env.NODE_ENV !== "production") {
        console.warn("deleteUploadSession failed, resetting locally", error);
      }
    }

    setLaneState(sampleLane, () => createInitialLaneState());
  }

  async function handleRetryNormalization(sampleLane: SampleLane) {
    const session = laneStates[sampleLane].session;
    if (!session) {
      return;
    }
    await finalizeLane(sampleLane, session);
  }

  async function uploadLane(
    sampleLane: SampleLane,
    seedSession: UploadSession,
    selectedFiles: Record<string, File>
  ) {
    const abortController = new AbortController();
    abortControllers.current[sampleLane] = abortController;

    setLaneState(sampleLane, (state) => ({
      ...state,
      phase: "uploading",
      error: null,
      message: null,
    }));

    let session = seedSession;

    try {
      for (const sessionFile of session.files) {
        const file = selectedFiles[sessionFile.fingerprint];
        if (!file) {
          setLaneState(sampleLane, (state) => ({
            ...state,
            phase: "paused",
            needsReselect: true,
            message: "Reselect the same files to continue the remaining chunks.",
          }));
          return;
        }

        const completedParts = new Set(sessionFile.completedPartNumbers);
        for (let partNumber = 1; partNumber <= sessionFile.totalParts; partNumber += 1) {
          if (completedParts.has(partNumber)) {
            continue;
          }

          const start = (partNumber - 1) * session.chunkSizeBytes;
          const end = Math.min(file.size, start + session.chunkSizeBytes);
          const body = file.slice(start, end);

          setLaneState(sampleLane, (state) => ({
            ...state,
            transientBytes: {
              ...state.transientBytes,
              [sessionFile.id]: 0,
            },
          }));

          const result = await api.uploadUploadSessionPart(
            workspace.id,
            session.id,
            sessionFile.id,
            partNumber,
            body,
            {
              signal: abortController.signal,
              onProgress: (loaded) => {
                setLaneState(sampleLane, (state) => ({
                  ...state,
                  transientBytes: {
                    ...state.transientBytes,
                    [sessionFile.id]: loaded,
                  },
                }));
              },
            }
          );

          session = updateSessionFile(session, sessionFile.id, (currentFile) => ({
            ...currentFile,
            uploadedBytes: result.uploadedBytes,
            completedPartNumbers: result.completedPartNumbers,
            status: "uploading",
          }));

          setLaneState(sampleLane, (state) => ({
            ...state,
            session,
            transientBytes: {
              ...state.transientBytes,
              [sessionFile.id]: 0,
            },
          }));
        }

        const completedFile = await api.completeUploadSessionFile(
          workspace.id,
          session.id,
          sessionFile.id
        );
        session = updateSessionFile(session, sessionFile.id, () => completedFile);
        setLaneState(sampleLane, (state) => ({
          ...state,
          session,
          transientBytes: {
            ...state.transientBytes,
            [sessionFile.id]: 0,
          },
        }));
      }

      await finalizeLane(sampleLane, {
        ...session,
        status: "uploaded",
      });
    } catch (error) {
      if (error instanceof DOMException && error.name === "AbortError") {
        setLaneState(sampleLane, (state) => ({
          ...state,
          phase: "paused",
          message: "Upload paused. Resume when you are ready.",
        }));
        return;
      }

      setLaneState(sampleLane, (state) => ({
        ...state,
        phase: "failed",
        error:
          error instanceof Error ? error.message : "Unable to upload this lane",
      }));
    } finally {
      if (abortControllers.current[sampleLane] === abortController) {
        abortControllers.current[sampleLane] = null;
      }
    }
  }

  async function finalizeLane(sampleLane: SampleLane, session: UploadSession) {
    setLaneState(sampleLane, (state) => ({
      ...state,
      session,
      phase: "normalizing",
      error: null,
      message: null,
    }));

    try {
      const updatedWorkspace = await api.commitUploadSession(workspace.id, session.id);
      onWorkspaceChange(updatedWorkspace);
      setLaneState(sampleLane, (state) => ({
        ...state,
        session: {
          ...session,
          status: "committed",
        },
        phase:
          updatedWorkspace.ingestion.lanes[sampleLane].status === "ready"
            ? "ready"
            : "normalizing",
        error: null,
        message: null,
      }));
    } catch (error) {
      setLaneState(sampleLane, (state) => ({
        ...state,
        phase: "failed",
        error:
          error instanceof Error
            ? error.message
            : "Unable to finalize this upload session",
      }));
    }
  }

  function handlePause(sampleLane: SampleLane) {
    abortControllers.current[sampleLane]?.abort();
  }

  async function handleResume(sampleLane: SampleLane) {
    const state = laneStates[sampleLane];
    if (!state.session) {
      return;
    }

    if (state.session.status === "uploaded") {
      await finalizeLane(sampleLane, state.session);
      return;
    }

    if (Object.keys(state.selectedFiles).length === 0) {
      fileInputRefs.current[sampleLane]?.click();
      return;
    }

    await uploadLane(sampleLane, state.session, state.selectedFiles);
  }

  function handlePreviewToggle(sampleLane: SampleLane) {
    const nextLane = expandedPreviewLane === sampleLane ? null : sampleLane;
    setExpandedPreviewLane(nextLane);

    if (nextLane && previewStates[sampleLane].phase === "idle") {
      void loadLanePreview(sampleLane);
    }
  }

  return (
    <div className="space-y-4">
      {LANES.map((lane) => {
        const laneState = laneStates[lane];
        const isReattach =
          laneState.session !== null &&
          ((laneState.phase === "paused" && laneState.needsReselect) ||
            (laneState.phase === "failed" &&
              Object.keys(laneState.selectedFiles).length === 0));
        return (
          <input
            key={lane}
            ref={(node) => {
              fileInputRefs.current[lane] = node;
            }}
            type="file"
            multiple
            accept=".fastq,.fq,.fastq.gz,.fq.gz,.bam,.cram"
            className="hidden"
            data-testid={`${lane}-lane-file-input`}
            onChange={(event) => {
              const files = event.target.files;
              if (isReattach) {
                void handleReattachFiles(lane, files);
              } else {
                handleStageFiles(lane, files);
              }
              event.target.value = "";
            }}
          />
        );
      })}

      <div className="overflow-hidden border-y border-black/8 bg-white/45 backdrop-blur-sm">
        {LANES.map((lane, index) => (
          <LaneSection
            key={lane}
            index={index}
            sampleLane={lane}
            workspace={workspace}
            laneState={laneStates[lane]}
            previewState={previewStates[lane]}
            previewExpanded={expandedPreviewLane === lane}
            fingerprintOf={fingerprintFile}
            onBrowse={() => fileInputRefs.current[lane]?.click()}
            onStageFiles={(files) => handleStageFiles(lane, files)}
            onReattachFiles={(files) => void handleReattachFiles(lane, files)}
            onRemoveStaged={(fingerprint) => handleRemoveStaged(lane, fingerprint)}
            onDiscardStaging={() => handleDiscardStaging(lane)}
            onStartUpload={() => void handleStartUpload(lane)}
            onPause={() => handlePause(lane)}
            onResume={() => void handleResume(lane)}
            onRetryNormalization={() => void handleRetryNormalization(lane)}
            onDiscardSession={() => void handleDiscardSession(lane)}
            onPreviewToggle={() => handlePreviewToggle(lane)}
            onPreviewRetry={() => void loadLanePreview(lane, { manual: true })}
            setDragActive={(isActive) =>
              setLaneState(lane, (state) => ({ ...state, dragActive: isActive }))
            }
            setStagingDragActive={(isActive) =>
              handleStagingDragActive(lane, isActive)
            }
          />
        ))}
      </div>
    </div>
  );
}

function LaneSection({
  index,
  sampleLane,
  workspace,
  laneState,
  previewState,
  previewExpanded,
  fingerprintOf,
  onBrowse,
  onStageFiles,
  onReattachFiles,
  onRemoveStaged,
  onDiscardStaging,
  onStartUpload,
  onPause,
  onResume,
  onRetryNormalization,
  onDiscardSession,
  onPreviewToggle,
  onPreviewRetry,
  setDragActive,
  setStagingDragActive,
}: {
  index: number;
  sampleLane: SampleLane;
  workspace: Workspace;
  laneState: LaneUploadState;
  previewState: LanePreviewState;
  previewExpanded: boolean;
  fingerprintOf: (file: File) => string;
  onBrowse: () => void;
  onStageFiles: (files: FileList | File[] | null) => void;
  onReattachFiles: (files: FileList | File[] | null) => void;
  onRemoveStaged: (fingerprint: string) => void;
  onDiscardStaging: () => void;
  onStartUpload: () => void;
  onPause: () => void;
  onResume: () => void;
  onRetryNormalization: () => void;
  onDiscardSession: () => void;
  onPreviewToggle: () => void;
  onPreviewRetry: () => void;
  setDragActive: (isActive: boolean) => void;
  setStagingDragActive: (isActive: boolean) => void;
}) {
  const summary = workspace.ingestion.lanes[sampleLane];
  const display = getLaneDisplayState({
    workspace,
    sampleLane,
    laneState,
    previewState,
  });
  const hasStaging = laneState.staging.files.length > 0;
  const isIdleEmpty =
    laneState.phase === "idle" && !laneState.session && !hasStaging;
  const isStaging =
    laneState.phase === "idle" && !laneState.session && hasStaging;
  const isReattach =
    laneState.session !== null &&
    ((laneState.phase === "paused" && laneState.needsReselect) ||
      (laneState.phase === "failed" &&
        Object.keys(laneState.selectedFiles).length === 0));
  const isCommitFailure =
    laneState.phase === "failed" && laneState.session !== null && !isReattach;
  const isTransferVisible =
    Boolean(laneState.session) &&
    !isReattach &&
    (laneState.phase === "queued" ||
      laneState.phase === "uploading" ||
      laneState.phase === "paused");
  const canPreview = summary.status === "ready";
  const canReplace =
    laneState.phase === "ready" || laneState.phase === "normalizing";

  const transfer = getTransferTotals(laneState);
  const remainingBytes = Math.max(0, transfer.totalBytes - transfer.uploadedBytes);
  const canResumeInPlace =
    laneState.phase === "paused" &&
    !laneState.needsReselect &&
    Object.keys(laneState.selectedFiles).length > 0;

  return (
    <section
      id={`lane-${sampleLane}`}
      className={cn(
        "animate-in fade-in slide-in-from-bottom-2 fill-mode-both duration-500 ease-out",
        index > 0 ? "border-t border-black/8" : ""
      )}
      style={
        {
          animationDelay: `${index * 80}ms`,
          "--lane-accent": laneAccentVar(sampleLane),
        } as React.CSSProperties
      }
      data-testid={`${sampleLane}-lane-panel`}
      data-lane-phase={laneState.phase}
      data-summary-status={summary.status}
    >
      <div className="grid gap-4 px-4 py-4 sm:px-6 lg:grid-cols-[120px_minmax(0,1fr)_auto] lg:items-start">
        <div className="flex items-center gap-2">
          <span
            aria-hidden
            className="size-2 rounded-full bg-[color:var(--lane-accent)]"
          />
          <span className="font-mono text-[11px] tracking-[0.24em] text-slate-600 uppercase">
            {formatLaneLabel(sampleLane)}
          </span>
        </div>

        <div className="min-w-0 space-y-1">
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
            <span
              data-testid={`${sampleLane}-lane-phase`}
              className={cn(
                "text-sm font-medium",
                display.tone === "ready"
                  ? "text-slate-900"
                  : display.tone === "failed"
                    ? "text-rose-700"
                    : "text-slate-700"
              )}
            >
              {display.label}
            </span>
            {display.summary ? (
              <span className="text-sm text-slate-500">{display.summary}</span>
            ) : null}
          </div>

          {display.detail ? (
            <p className="max-w-3xl text-xs leading-5 text-slate-500">
              {display.detail}
            </p>
          ) : null}
        </div>

        <div className="flex flex-wrap items-center gap-2 lg:justify-end">
          {laneState.phase === "uploading" ? (
            <Button variant="ghost" size="sm" onClick={onPause}>
              Pause
            </Button>
          ) : null}

          {canResumeInPlace ? (
            <Button
              variant="outline"
              size="sm"
              onClick={onResume}
              data-testid={`${sampleLane}-resume-upload`}
            >
              Resume upload
              {remainingBytes > 0 ? (
                <span className="ml-1.5 font-mono text-[10px] text-slate-400 tabular-nums">
                  · {formatBytes(remainingBytes)}
                </span>
              ) : null}
            </Button>
          ) : null}

          {isCommitFailure ? (
            <>
              <Button
                variant="outline"
                size="sm"
                onClick={onRetryNormalization}
                data-testid={`${sampleLane}-retry-normalization`}
              >
                Try normalization again
              </Button>
              <button
                type="button"
                onClick={onDiscardSession}
                className="font-mono text-[10px] tracking-[0.18em] text-slate-400 uppercase transition hover:text-slate-700 focus-visible:text-slate-900 focus-visible:outline-none"
              >
                discard session
              </button>
            </>
          ) : null}

          {canPreview ? (
            <Button
              variant="ghost"
              size="sm"
              onClick={onPreviewToggle}
              data-testid={`${sampleLane}-preview-toggle`}
            >
              {previewExpanded ? "Hide preview" : "Preview"}
            </Button>
          ) : null}

          {isIdleEmpty ? (
            <Button variant="outline" size="sm" onClick={onBrowse}>
              Upload
            </Button>
          ) : null}

          {canReplace ? (
            <Button variant="ghost" size="sm" onClick={onBrowse}>
              Replace
            </Button>
          ) : null}
        </div>
      </div>

      {isIdleEmpty ? (
        <IdleDropSurface
          laneState={laneState}
          onBrowse={onBrowse}
          onFilesSelected={onStageFiles}
          setDragActive={setDragActive}
        />
      ) : null}

      {isStaging ? (
        <LaneStagingPanel
          sampleLane={sampleLane}
          files={laneState.staging.files}
          detection={laneState.staging.detection}
          validation={laneState.staging.validation}
          starting={laneState.staging.starting}
          dragActive={laneState.staging.dragActive}
          fingerprintOf={fingerprintOf}
          onAddFiles={onBrowse}
          onDropFiles={onStageFiles}
          onRemoveFile={onRemoveStaged}
          onStartUpload={onStartUpload}
          onDiscardStaging={onDiscardStaging}
          setDragActive={setStagingDragActive}
        />
      ) : null}

      {isReattach && laneState.session ? (
        <LaneReattachPanel
          sampleLane={sampleLane}
          session={laneState.session}
          dragActive={laneState.dragActive}
          onBrowse={onBrowse}
          onDropFiles={onReattachFiles}
          onDiscardSession={onDiscardSession}
          setDragActive={setDragActive}
        />
      ) : null}

      {isTransferVisible ? (
        <TransferManifest laneState={laneState} />
      ) : null}

      {laneState.phase === "normalizing" ? (
        <div className="border-t border-black/8 px-4 py-3 text-sm text-slate-500 sm:px-6">
          Preparing canonical FASTQ
        </div>
      ) : null}

      {previewExpanded ? (
        <InstrumentTracePanel
          sampleLane={sampleLane}
          previewState={previewState}
          onRetry={onPreviewRetry}
          isFirstLane={sampleLane === "tumor"}
        />
      ) : null}
    </section>
  );
}

function IdleDropSurface({
  laneState,
  onBrowse,
  onFilesSelected,
  setDragActive,
}: {
  laneState: LaneUploadState;
  onBrowse: () => void;
  onFilesSelected: (files: FileList | File[] | null) => void;
  setDragActive: (isActive: boolean) => void;
}) {
  return (
    <div className="border-t border-black/8 px-4 py-3 sm:px-6">
      <div
        role="button"
        tabIndex={0}
        onClick={onBrowse}
        onKeyDown={(event) => {
          if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            onBrowse();
          }
        }}
        onDragOver={(event) => {
          event.preventDefault();
          setDragActive(true);
        }}
        onDragLeave={(event) => {
          event.preventDefault();
          if (event.currentTarget.contains(event.relatedTarget as Node | null)) {
            return;
          }
          setDragActive(false);
        }}
        onDrop={(event) => {
          event.preventDefault();
          setDragActive(false);
          onFilesSelected(event.dataTransfer.files);
        }}
        className={cn(
          "flex items-center justify-between gap-3 rounded-2xl px-3 py-3 text-sm transition outline-none",
          laneState.dragActive
            ? "bg-slate-50 text-slate-900"
            : "text-slate-600 hover:bg-slate-50/80 hover:text-slate-900",
          "focus-visible:bg-slate-50 focus-visible:text-slate-900"
        )}
      >
        <div className="flex items-center gap-3">
          <Upload className="size-4 shrink-0 text-slate-400" strokeWidth={1.5} />
          <span>FASTQ, BAM, or CRAM</span>
        </div>
        <span className="font-mono text-[10px] tracking-[0.18em] text-slate-400 uppercase">
          Drop or browse
        </span>
      </div>
    </div>
  );
}

function TransferManifest({
  laneState,
}: {
  laneState: LaneUploadState;
}) {
  const session = laneState.session;
  if (!session) {
    return null;
  }

  const transfer = getTransferTotals(laneState);

  return (
    <div className="border-t border-black/8 px-4 py-3 sm:px-6">
      <div className="relative mb-3 h-px w-full overflow-hidden bg-black/8">
        <div
          className={cn(
            "absolute inset-y-0 left-0 transition-[width] duration-500 ease-out",
            laneState.phase === "paused"
              ? "bg-slate-400"
              : "bg-[color:var(--lane-accent)]"
          )}
          style={{ width: `${Math.min(100, transfer.percent)}%` }}
        />
      </div>

      <ul className="space-y-2">
        {session.files.map((file) => {
          const uploadedBytes = getDisplayUploadedBytes(file, laneState.transientBytes);
          const percent =
            file.sizeBytes === 0 ? 0 : (uploadedBytes / file.sizeBytes) * 100;

          return (
            <li
              key={file.id}
              className="flex items-center justify-between gap-3 text-sm"
            >
              <p className="flex min-w-0 items-center gap-2 text-slate-700">
                <FileText className="size-3.5 shrink-0 text-slate-400" strokeWidth={1.5} />
                <span className="truncate">{file.filename}</span>
              </p>
              <div className="flex shrink-0 items-center gap-3 font-mono text-[10px] text-slate-400 tabular-nums">
                <span>{file.readPair === "unknown" ? "—" : file.readPair}</span>
                <span>{formatBytes(file.sizeBytes)}</span>
                <span className="w-9 text-right text-slate-600">
                  {Math.round(percent)}%
                </span>
              </div>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

function InstrumentTracePanel({
  sampleLane,
  previewState,
  onRetry,
  isFirstLane,
}: {
  sampleLane: SampleLane;
  previewState: LanePreviewState;
  onRetry: () => void;
  isFirstLane: boolean;
}) {
  const [pairedToggle, setPairedToggle] = useState<"R1" | "R2">("R1");
  const [showAll, setShowAll] = useState(false);

  const layoutReady =
    previewState.phase === "ready" && previewState.data && previewState.data.stats;
  const stats = previewState.data?.stats;

  const isPaired = previewState.data?.readLayout === "paired";
  const activePair: "R1" | "R2" | "SE" = isPaired ? pairedToggle : "SE";

  const r1Reads = previewState.data?.reads.R1 ?? [];
  const r2Reads = previewState.data?.reads.R2 ?? [];
  const seReads = previewState.data?.reads.SE ?? [];

  const activeReads =
    activePair === "R1" ? r1Reads : activePair === "R2" ? r2Reads : seReads;
  const mateReads =
    activePair === "R1" ? r2Reads : activePair === "R2" ? r1Reads : [];

  const insight = useMemo(() => {
    if (!previewState.data) {
      return deriveLaneInsight([]);
    }
    const all = [
      ...(previewState.data.reads.R1 ?? []),
      ...(previewState.data.reads.R2 ?? []),
      ...(previewState.data.reads.SE ?? []),
    ];
    return deriveLaneInsight(all);
  }, [previewState.data]);

  const visibleReads = showAll
    ? activeReads
    : activeReads.slice(0, INITIAL_VISIBLE_READS);
  const hiddenCount = activeReads.length - visibleReads.length;

  return (
    <div
      data-testid={`${sampleLane}-preview-panel`}
      data-phase={previewState.phase}
      className="animate-in fade-in slide-in-from-top-2 border-t border-black/8 px-4 py-4 fill-mode-both duration-300 sm:px-6"
    >
      {previewState.phase === "loading" || previewState.phase === "idle" ? (
        <div className="flex items-center gap-2 text-sm text-slate-500">
          <LoaderCircle className="size-4 animate-spin" strokeWidth={1.5} />
          <span>Sampling canonical reads…</span>
        </div>
      ) : null}

      {previewState.phase === "failed" ? (
        <p className="text-sm text-slate-500">
          Couldn&rsquo;t sample reads.{" "}
          <button
            type="button"
            onClick={onRetry}
            data-testid={`${sampleLane}-preview-retry`}
            className="font-mono text-[10px] tracking-[0.18em] uppercase text-slate-400 transition hover:text-slate-700 focus-visible:text-slate-900 focus-visible:outline-none"
          >
            sample again
          </button>
        </p>
      ) : null}

      {layoutReady && stats ? (
        <div className="space-y-5">
          <p className="font-mono text-[10px] tracking-[0.22em] text-slate-500 tabular-nums uppercase">
            {stats.sampledReadCount.toLocaleString()} reads sampled
            <span className="text-slate-300"> · canonical fastq</span>
          </p>

          <SampledReadoutStrip
            sampledReadCount={stats.sampledReadCount}
            averageReadLength={stats.averageReadLength}
            sampledGcPercent={stats.sampledGcPercent}
            insight={insight}
          />

          {isFirstLane ? <PreviewLegend /> : null}

          <div className="space-y-3">
            <div className="flex items-baseline justify-between gap-3">
              {isPaired ? (
                <PairSegmented
                  value={pairedToggle}
                  onChange={(next) => setPairedToggle(next)}
                />
              ) : (
                <span className="font-mono text-[10px] tracking-[0.22em] text-slate-500 uppercase">
                  SE
                </span>
              )}
              <span className="font-mono text-[10px] tabular-nums text-slate-400">
                {activeReads.length === 0
                  ? "no reads"
                  : showAll || hiddenCount === 0
                    ? `${activeReads.length} shown`
                    : `${visibleReads.length} of ${activeReads.length} shown`}
              </span>
            </div>

            <div className="space-y-4">
              {visibleReads.map((read, index) => (
                <InstrumentTraceRow
                  key={`${activePair}-${read.header}-${index}`}
                  read={read}
                  mate={mateReads[index]}
                  index={index}
                />
              ))}
            </div>

            {hiddenCount > 0 ? (
              <button
                type="button"
                onClick={() => setShowAll(true)}
                className="font-mono text-[10px] tracking-[0.18em] text-slate-400 uppercase transition hover:text-slate-700 focus-visible:text-slate-900 focus-visible:outline-none"
              >
                + show {hiddenCount} more
              </button>
            ) : null}

            {showAll && activeReads.length > INITIAL_VISIBLE_READS ? (
              <button
                type="button"
                onClick={() => setShowAll(false)}
                className="font-mono text-[10px] tracking-[0.18em] text-slate-400 uppercase transition hover:text-slate-700 focus-visible:text-slate-900 focus-visible:outline-none"
              >
                − collapse
              </button>
            ) : null}
          </div>
        </div>
      ) : null}
    </div>
  );
}

function PairSegmented({
  value,
  onChange,
}: {
  value: "R1" | "R2";
  onChange: (next: "R1" | "R2") => void;
}) {
  return (
    <div
      role="tablist"
      aria-label="Paired-end read selector"
      onKeyDown={(event) => {
        if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
          event.preventDefault();
          onChange(value === "R1" ? "R2" : "R1");
        }
      }}
      className="inline-flex overflow-hidden rounded-full border border-black/10 bg-white/70 font-mono text-[10px] tracking-[0.22em] uppercase"
    >
      {(["R1", "R2"] as const).map((pair) => {
        const active = value === pair;
        return (
          <button
            key={pair}
            type="button"
            role="tab"
            aria-selected={active}
            tabIndex={active ? 0 : -1}
            onClick={() => onChange(pair)}
            className={cn(
              "px-3 py-1 transition outline-none",
              active
                ? "bg-[color:var(--lane-accent)] text-white shadow-sm"
                : "text-slate-500 hover:text-slate-900"
            )}
          >
            {pair}
          </button>
        );
      })}
    </div>
  );
}
