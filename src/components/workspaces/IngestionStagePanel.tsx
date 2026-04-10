"use client";

import { useEffect, useRef, useState } from "react";
import { CircleAlert, LoaderCircle, Upload } from "lucide-react";

import { api } from "@/lib/api";
import type {
  SampleLane,
  UploadSession,
  UploadSessionFile,
  Workspace,
} from "@/lib/types";
import {
  formatBytes,
  getLaneMissingPairs,
} from "@/lib/workspace-utils";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

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

type PhaseTone = "neutral" | "emerald" | "destructive";

interface LaneUploadState {
  session: UploadSession | null;
  phase: LanePhase;
  error: string | null;
  message: string | null;
  selectedFiles: Record<string, File>;
  transientBytes: Record<string, number>;
  needsReselect: boolean;
  dragActive: boolean;
}

const LANES: SampleLane[] = ["tumor", "normal"];

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

function phaseHeading(phase: LanePhase): string {
  switch (phase) {
    case "queued":
    case "uploading":
      return "Transferring";
    case "paused":
      return "Paused";
    case "normalizing":
      return "Normalizing";
    case "ready":
      return "Ready";
    case "failed":
      return "Needs attention";
    default:
      return "Awaiting samples";
  }
}

function phaseSubhead(phase: LanePhase, fileCount: number): string {
  switch (phase) {
    case "queued":
    case "uploading":
      return fileCount === 1
        ? "Streaming one file in resumable chunks"
        : `Streaming ${fileCount} files in resumable chunks`;
    case "paused":
      return "Transfer paused — resume anytime";
    case "normalizing":
      return "Preparing canonical paired FASTQ";
    case "ready":
      return "Canonical paired FASTQ ready for alignment";
    case "failed":
      return "Resolve the issue below to continue";
    default:
      return "Drop FASTQ, BAM, or CRAM — paired reads only";
  }
}

function phaseTone(phase: LanePhase): PhaseTone {
  if (phase === "ready") return "emerald";
  if (phase === "failed") return "destructive";
  return "neutral";
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

  useEffect(() => {
    setLaneStates({
      tumor: createInitialLaneState(),
      normal: createInitialLaneState(),
    });

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
            message: "Upload finished. Canonical FASTQ is being prepared.",
          };
          continue;
        }

        if (summary.status === "ready") {
          next[lane] = {
            ...state,
            phase: "ready",
            error: null,
            message: "Canonical paired FASTQ is ready for alignment.",
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
            error:
              summary.blockingIssues.join(" ") ||
              state.error ||
              "This lane needs attention before it can continue.",
          };
          continue;
        }

        if (summary.status === "empty" && !state.session) {
          next[lane] = createInitialLaneState();
        }
      }

      return next;
    });
  }, [workspace]);

  function setLaneState(
    sampleLane: SampleLane,
    updater: (state: LaneUploadState) => LaneUploadState
  ) {
    setLaneStates((current) => ({
      ...current,
      [sampleLane]: updater(current[sampleLane]),
    }));
  }

  async function handleFileSelection(
    sampleLane: SampleLane,
    fileList: FileList | File[] | null
  ) {
    const files = Array.from(fileList ?? []);
    if (files.length === 0) {
      return;
    }

    abortControllers.current[sampleLane]?.abort();

    const selectedFiles = filesByFingerprint(files);
    const currentState = laneStates[sampleLane];
    let session =
      currentState.session && sessionMatchesFiles(currentState.session, files)
        ? currentState.session
        : null;

    if (!session) {
      const sessions = await api.listUploadSessions(workspace.id);
      session =
        sessions.find(
          (item) =>
            item.sampleLane === sampleLane && sessionMatchesFiles(item, files)
        ) ?? null;
    }

    if (!session) {
      session = await api.createUploadSession(workspace.id, {
        sampleLane,
        files: files.map((file) => ({
          filename: file.name,
          sizeBytes: file.size,
          lastModifiedMs: file.lastModified,
          contentType: file.type || undefined,
        })),
      });
    }

    setLaneState(sampleLane, (state) => ({
      ...state,
      session,
      phase: "queued",
      error: null,
      message:
        sessionMatchesFiles(session, files) && session.files.some((file) => file.uploadedBytes > 0)
          ? "Resuming the remaining chunks for these files."
          : "Upload queued. Chunk transfer will start now.",
      selectedFiles,
      transientBytes: {},
      needsReselect: false,
    }));

    if (session.status === "uploaded") {
      await finalizeLane(sampleLane, session);
      return;
    }

    await uploadLane(sampleLane, session, selectedFiles);
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

  const unlocked = workspace.ingestion.readyForAlignment;

  return (
    <div className="space-y-10">
      {LANES.map((lane) => (
        <input
          key={lane}
          ref={(node) => {
            fileInputRefs.current[lane] = node;
          }}
          type="file"
          multiple
          accept=".fastq,.fq,.fastq.gz,.fq.gz,.bam,.cram"
          className="hidden"
          onChange={(event) => {
            void handleFileSelection(lane, event.target.files);
            event.target.value = "";
          }}
        />
      ))}

      <div className="flex items-center justify-between border-b border-black/8 pb-3">
        <p className="font-mono text-[11px] tracking-[0.22em] text-slate-500 uppercase">
          Sample intake · tumor &amp; normal
        </p>
        <span
          className={cn(
            "font-mono text-[11px] tracking-[0.18em] uppercase",
            unlocked ? "text-emerald-700" : "text-slate-500"
          )}
        >
          {unlocked ? "● Alignment unlocked" : "○ Alignment locked"}
        </span>
      </div>

      <div className="grid gap-10 xl:grid-cols-2 xl:gap-14">
        {LANES.map((lane, index) => (
          <LaneBlock
            key={lane}
            index={index}
            sampleLane={lane}
            workspace={workspace}
            laneState={laneStates[lane]}
            onBrowse={() => fileInputRefs.current[lane]?.click()}
            onFilesSelected={(files) => void handleFileSelection(lane, files)}
            onPause={() => handlePause(lane)}
            onResume={() => void handleResume(lane)}
            setDragActive={(isActive) =>
              setLaneState(lane, (state) => ({ ...state, dragActive: isActive }))
            }
          />
        ))}
      </div>
    </div>
  );
}

function LaneBlock({
  index,
  sampleLane,
  workspace,
  laneState,
  onBrowse,
  onFilesSelected,
  onPause,
  onResume,
  setDragActive,
}: {
  index: number;
  sampleLane: SampleLane;
  workspace: Workspace;
  laneState: LaneUploadState;
  onBrowse: () => void;
  onFilesSelected: (files: FileList | File[] | null) => void;
  onPause: () => void;
  onResume: () => void;
  setDragActive: (isActive: boolean) => void;
}) {
  const transfer = getTransferTotals(laneState);
  const summary = workspace.ingestion.lanes[sampleLane];
  const missingPairs = getLaneMissingPairs(workspace, sampleLane);
  const tone = phaseTone(laneState.phase);
  const heading = phaseHeading(laneState.phase);
  const subhead = phaseSubhead(
    laneState.phase,
    laneState.session?.files.length ?? 0
  );
  const hasSession = Boolean(laneState.session);
  const isUploading = laneState.phase === "uploading";
  const showDropzone = !hasSession && !isUploading;
  const blockingIssue =
    summary.blockingIssues[0] ??
    (missingPairs.length > 0 ? `Missing ${missingPairs.join(" and ")}` : null);

  return (
    <section
      className="group ingest-lane flex flex-col"
      style={{ animationDelay: `${index * 90}ms` }}
    >
      <header className="flex items-baseline justify-between">
        <p className="font-mono text-[11px] tracking-[0.28em] text-slate-500 uppercase">
          {sampleLane === "tumor" ? "Lane 01 · Tumor" : "Lane 02 · Normal"}
        </p>
        <span
          className={cn(
            "font-mono text-[10px] tracking-[0.2em] uppercase",
            tone === "emerald"
              ? "text-emerald-700"
              : tone === "destructive"
                ? "text-destructive"
                : "text-slate-400"
          )}
        >
          {laneState.phase}
        </span>
      </header>

      <h3
        className={cn(
          "font-display mt-5 text-[44px] leading-[1.02] tracking-[-0.02em]",
          tone === "emerald"
            ? "text-emerald-800"
            : tone === "destructive"
              ? "text-destructive"
              : "text-slate-900"
        )}
        style={{ fontOpticalSizing: "auto" }}
      >
        {heading}
      </h3>
      <p className="mt-3 max-w-md text-sm text-slate-500">{subhead}</p>

      <div className="mt-8 space-y-2">
        <div className="relative h-px w-full overflow-hidden bg-black/8">
          <div
            className={cn(
              "absolute inset-y-0 left-0 transition-[width] duration-500 ease-out",
              tone === "emerald"
                ? "bg-emerald-600"
                : tone === "destructive"
                  ? "bg-destructive"
                  : "bg-slate-900"
            )}
            style={{
              width: `${Math.max(tone === "emerald" ? 100 : 0, Math.min(100, transfer.percent))}%`,
            }}
          />
        </div>
        <div className="flex items-center justify-between font-mono text-[11px] tracking-wide text-slate-500 tabular-nums">
          <span>
            {transfer.totalBytes > 0
              ? `${formatBytes(transfer.uploadedBytes)} / ${formatBytes(transfer.totalBytes)}`
              : "— / —"}
          </span>
          <span>
            {transfer.totalBytes > 0
              ? `${Math.round(transfer.percent).toString().padStart(2, "0")}%`
              : tone === "emerald"
                ? "100%"
                : "00%"}
          </span>
        </div>
      </div>

      {showDropzone ? (
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
            "mt-8 flex cursor-pointer items-center gap-4 border border-dashed px-5 py-6 transition-colors outline-none",
            laneState.dragActive
              ? "border-slate-900 bg-slate-50"
              : "border-black/15 hover:border-slate-900 hover:bg-slate-50/60",
            "focus-visible:border-slate-900 focus-visible:bg-slate-50"
          )}
        >
          <Upload className="size-4 shrink-0 text-slate-500" strokeWidth={1.5} />
          <div className="min-w-0 flex-1">
            <p className="text-sm text-slate-900">Drop files or click to browse</p>
            <p className="mt-0.5 font-mono text-[10px] tracking-[0.12em] text-slate-400 uppercase">
              fastq · fastq.gz · bam · cram
            </p>
          </div>
        </div>
      ) : null}

      {hasSession && laneState.session ? (
        <ul className="mt-8 divide-y divide-black/8 border-y border-black/8">
          {laneState.session.files.map((file) => {
            const uploadedBytes = getDisplayUploadedBytes(
              file,
              laneState.transientBytes
            );
            const percent =
              file.sizeBytes === 0 ? 0 : (uploadedBytes / file.sizeBytes) * 100;
            const done = percent >= 100;
            return (
              <li
                key={file.id}
                className="grid grid-cols-[1fr_auto] items-baseline gap-x-4 gap-y-1 py-3"
              >
                <p className="truncate text-sm text-slate-900">{file.filename}</p>
                <p className="font-mono text-[11px] text-slate-500 tabular-nums">
                  {formatBytes(file.sizeBytes)}
                </p>
                <div className="relative col-span-2 h-px overflow-hidden bg-black/6">
                  <div
                    className={cn(
                      "absolute inset-y-0 left-0 transition-[width] duration-500 ease-out",
                      done ? "bg-emerald-600" : "bg-slate-900"
                    )}
                    style={{ width: `${Math.min(100, percent)}%` }}
                  />
                </div>
                <p className="font-mono text-[10px] tracking-[0.08em] text-slate-400 uppercase">
                  {file.readPair} · {file.format}
                </p>
                <p className="font-mono text-[10px] text-slate-400 tabular-nums">
                  {Math.round(percent)}%
                </p>
              </li>
            );
          })}
        </ul>
      ) : null}

      <div className="mt-8 flex flex-wrap items-center gap-2">
        <Button variant="outline" size="sm" onClick={onBrowse}>
          {hasSession ? "Replace files" : "Choose files"}
        </Button>
        {isUploading ? (
          <Button variant="ghost" size="sm" onClick={onPause}>
            Pause
          </Button>
        ) : null}
        {!isUploading && hasSession && laneState.phase !== "ready" ? (
          <Button variant="ghost" size="sm" onClick={onResume}>
            {laneState.session?.status === "uploaded"
              ? "Start normalization"
              : laneState.phase === "failed"
                ? "Retry"
                : "Resume"}
          </Button>
        ) : null}
        {isUploading ? (
          <span className="inline-flex items-center gap-1.5 font-mono text-[10px] tracking-[0.16em] text-slate-400 uppercase">
            <LoaderCircle className="size-3 animate-spin" strokeWidth={1.5} />
            streaming
          </span>
        ) : null}
      </div>

      {laneState.error ? (
        <p className="mt-5 flex items-start gap-2 text-sm text-destructive">
          <CircleAlert className="mt-0.5 size-4 shrink-0" strokeWidth={1.5} />
          <span>{laneState.error}</span>
        </p>
      ) : blockingIssue ? (
        <p className="mt-5 flex items-start gap-2 text-sm text-slate-600">
          <CircleAlert className="mt-0.5 size-4 shrink-0 text-slate-400" strokeWidth={1.5} />
          <span>{blockingIssue}</span>
        </p>
      ) : laneState.message ? (
        <p className="mt-5 text-sm text-slate-500">{laneState.message}</p>
      ) : null}
    </section>
  );
}
