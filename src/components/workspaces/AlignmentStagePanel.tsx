"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  Check,
  ChevronRight,
  Cpu,
  FolderOpen,
  LoaderCircle,
  Play,
  RotateCcw,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { api, InsufficientMemoryError, MissingToolsError } from "@/lib/api";
import { getDesktopBridge } from "@/lib/desktop";
import type {
  AlignmentLaneMetrics,
  AlignmentRun,
  AlignmentSettings,
  AlignmentSettingsPatch,
  AlignmentStageSummary,
  AssayType,
  ChunkProgressState,
  SampleLane,
  SystemMemoryResponse,
  SystemResourcesResponse,
  Workspace,
} from "@/lib/types";
import { cn } from "@/lib/utils";
import {
  formatBytes,
  formatDateTime,
  formatLaneLabel,
  formatReferencePreset,
  getQcVerdictLabel,
} from "@/lib/workspace-utils";

interface AlignmentStagePanelProps {
  workspace: Workspace;
  summary: AlignmentStageSummary;
  onWorkspaceChange: (workspace: Workspace) => void;
  onSummaryChange: (summary: AlignmentStageSummary) => void;
}

const ASSAY_OPTIONS: Array<{ value: AssayType; label: string; hint: string }> = [
  {
    value: "wgs",
    label: "Whole-genome (WGS)",
    hint: "Reads everywhere across the DNA. Slower, most thorough.",
  },
  {
    value: "wes",
    label: "Whole-exome (WES)",
    hint: "Reads only the protein-coding genes. Faster, smaller files.",
  },
];

const METRIC_DEFINITIONS = [
  {
    key: "mappedPercent",
    label: "Mapped",
    format: (value: number | null) =>
      value == null ? "—" : `${value.toFixed(1)}%`,
  },
  {
    key: "properlyPairedPercent",
    label: "Properly paired",
    format: (value: number | null) =>
      value == null ? "—" : `${value.toFixed(1)}%`,
  },
  {
    key: "duplicatePercent",
    label: "Duplicates",
    format: (value: number | null) =>
      value == null ? "—" : `${value.toFixed(1)}%`,
  },
  {
    key: "meanInsertSize",
    label: "Mean insert",
    format: (value: number | null) =>
      value == null ? "—" : `${value.toFixed(0)} bp`,
  },
] as const;

type BannerState = "waiting" | "running" | "passed" | "warning" | "failed";

function bannerStateOf(summary: AlignmentStageSummary): BannerState {
  if (summary.status === "completed") {
    if (summary.latestRun?.qcVerdict === "fail") return "failed";
    if (summary.latestRun?.qcVerdict === "warn") return "warning";
    return "passed";
  }
  if (summary.status === "running") return "running";
  if (summary.status === "failed") return "failed";
  return "waiting";
}

const PILL_TONES: Record<BannerState, { label: string; bg: string; dot: string }> = {
  waiting: { label: "Waiting", bg: "bg-stone-100 text-stone-500", dot: "bg-stone-400" },
  running: { label: "Running", bg: "bg-amber-50 text-amber-700", dot: "bg-amber-500" },
  passed: { label: "Passed", bg: "bg-emerald-50 text-emerald-700", dot: "bg-emerald-500" },
  warning: { label: "Warnings", bg: "bg-amber-50 text-amber-700", dot: "bg-amber-500" },
  failed: { label: "Failed", bg: "bg-rose-50 text-rose-700", dot: "bg-rose-500" },
};

function bannerMessage(state: BannerState, hasRun: boolean) {
  switch (state) {
    case "passed":
      return "Alignment finished. Quality looks good.";
    case "warning":
      return "Alignment finished, but quality has some warnings.";
    case "failed":
      return "Alignment failed. Check the details below.";
    case "running":
      return "Alignment is running…";
    default:
      return hasRun
        ? "Ready to run again when you are."
        : "Confirm the sequencing method, then start the alignment.";
  }
}

function metricValue(
  metrics: AlignmentLaneMetrics | null,
  key: (typeof METRIC_DEFINITIONS)[number]["key"]
) {
  if (!metrics) return null;
  return metrics[key] ?? null;
}

function runtimePhaseLabel(phase?: string | null) {
  if (phase === "preparing_reference") return "Preparing reference";
  if (phase === "aligning") return "Aligning reads";
  if (phase === "finalizing") return "Finalizing files";
  return "Working";
}

export default function AlignmentStagePanel({
  workspace,
  summary,
  onWorkspaceChange,
  onSummaryChange,
}: AlignmentStagePanelProps) {
  const [isSavingProfile, setIsSavingProfile] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [missingTools, setMissingTools] = useState<MissingToolsError | null>(null);
  const [memoryError, setMemoryError] = useState<InsufficientMemoryError | null>(
    null
  );
  const [showQuality, setShowQuality] = useState(false);

  useEffect(() => {
    if (summary.status !== "running") {
      return;
    }

    const timer = window.setInterval(() => {
      void api
        .getAlignmentStageSummary(workspace.id)
        .then(onSummaryChange)
        .catch(() => {});
    }, 2000);

    return () => window.clearInterval(timer);
  }, [onSummaryChange, summary.status, workspace.id]);

  const bannerState = bannerStateOf(summary);
  const pill = PILL_TONES[bannerState];
  const assayType = workspace.analysisProfile.assayType ?? null;
  const latestRun = summary.latestRun;
  const isRunning = summary.status === "running";
  const canRun =
    summary.status === "ready" ||
    summary.status === "completed" ||
    summary.status === "failed";

  async function handleAssaySelect(nextAssayType: AssayType) {
    if (assayType === nextAssayType || isSavingProfile) {
      return;
    }

    setError(null);
    setIsSavingProfile(true);
    try {
      const updatedWorkspace = await api.updateWorkspaceAnalysisProfile(workspace.id, {
        assayType: nextAssayType,
        referencePreset: workspace.analysisProfile.referencePreset,
        referenceOverride: workspace.analysisProfile.referenceOverride,
      });
      onWorkspaceChange(updatedWorkspace);
      onSummaryChange(await api.getAlignmentStageSummary(workspace.id));
    } catch (updateError) {
      setError(
        updateError instanceof Error
          ? updateError.message
          : "Unable to update the assay profile."
      );
    } finally {
      setIsSavingProfile(false);
    }
  }

  async function handleRun() {
    if (!canRun || isSubmitting) {
      return;
    }

    setError(null);
    setMissingTools(null);
    setMemoryError(null);
    setIsSubmitting(true);
    try {
      const nextSummary = latestRun
        ? await api.rerunAlignment(workspace.id)
        : await api.runAlignment(workspace.id);
      onSummaryChange(nextSummary);
    } catch (runError) {
      if (runError instanceof MissingToolsError) {
        setMissingTools(runError);
      } else if (runError instanceof InsufficientMemoryError) {
        setMemoryError(runError);
      } else {
        setError(
          runError instanceof Error ? runError.message : "Unable to start alignment."
        );
      }
    } finally {
      setIsSubmitting(false);
    }
  }

  async function handleOpenArtifact(
    localPath?: string | null,
    downloadPath?: string
  ) {
    if (!localPath && !downloadPath) {
      return;
    }

    const desktop = getDesktopBridge();
    if (!desktop) {
      if (downloadPath) {
        window.open(api.resolveDownloadUrl(downloadPath), "_blank");
      }
      return;
    }
    if (localPath) {
      await desktop.openPath(localPath);
    }
  }

  return (
    <div className="space-y-3" data-testid="alignment-stage-panel">
      <div className="flex flex-wrap items-center justify-between gap-3 px-1 pt-1 pb-2">
        <p className="text-sm text-stone-600">
          {bannerMessage(bannerState, Boolean(latestRun))}
        </p>
        <span
          data-testid="alignment-stage-status-strip"
          data-state={summary.status}
          className={cn(
            "inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 font-mono text-[10px] uppercase tracking-[0.2em]",
            pill.bg
          )}
        >
          <span
            className={cn("inline-block size-1.5 rounded-full", pill.dot)}
          />
          {pill.label}
        </span>
      </div>

      <section className="rounded-2xl border border-stone-200 bg-white">
        <div className="space-y-5 px-5 py-4">
          <div>
            <h3 className="text-[15px] font-semibold text-stone-900">
              Sequencing method
            </h3>
            <p className="mt-0.5 text-[13px] text-stone-500">
              Check the lab report — it usually says WGS or WES.
            </p>
            <div className="mt-3 grid gap-2 sm:grid-cols-2">
              {ASSAY_OPTIONS.map((option) => {
                const selected = assayType === option.value;
                return (
                  <button
                    key={option.value}
                    type="button"
                    data-testid={`alignment-assay-${option.value}`}
                    onClick={() => void handleAssaySelect(option.value)}
                    disabled={isSavingProfile || isRunning}
                    className={cn(
                      "rounded-xl border px-4 py-3 text-left transition disabled:opacity-50",
                      selected
                        ? "border-emerald-300 bg-emerald-50/60"
                        : "border-stone-200 bg-white hover:border-stone-300"
                    )}
                  >
                    <div className="flex items-center gap-2">
                      <span
                        className={cn(
                          "flex size-4 shrink-0 items-center justify-center rounded-full border transition-colors",
                          selected
                            ? "border-emerald-500 bg-emerald-500"
                            : "border-stone-300 bg-white"
                        )}
                        aria-hidden="true"
                      >
                        {selected ? (
                          <Check
                            className="size-2.5 text-white"
                            strokeWidth={4}
                          />
                        ) : null}
                      </span>
                      <span className="text-[13px] font-medium text-stone-900">
                        {option.label}
                      </span>
                    </div>
                    <p className="mt-1.5 pl-6 text-[12px] leading-5 text-stone-500">
                      {option.hint}
                    </p>
                  </button>
                );
              })}
            </div>
          </div>

          <div className="border-t border-stone-100 pt-4">
            {isRunning && latestRun ? (
              <div className="space-y-2">
                <div className="flex items-center justify-between gap-3 text-[13px] text-stone-700">
                  <div className="flex items-center gap-2">
                    <LoaderCircle className="size-3.5 animate-spin" />
                    {runtimePhaseLabel(latestRun.runtimePhase)}
                  </div>
                  <div className="flex items-center gap-2.5">
                    <ElapsedTimer startedAt={latestRun.startedAt} />
                    <span className="font-mono text-[11px] text-stone-500">
                      {Math.round(latestRun.progress * 100)}%
                    </span>
                  </div>
                </div>
                <div className="h-1 overflow-hidden rounded-full bg-stone-200">
                  <div
                    className="h-full rounded-full bg-emerald-500/70 transition-[width] duration-500"
                    style={{
                      width: `${Math.max(3, Math.round(latestRun.progress * 100))}%`,
                    }}
                  />
                </div>
                <MemoryHairline />
                <ChunkProgressStrips run={latestRun} />
              </div>
            ) : (
              <div className="flex flex-wrap items-center justify-between gap-3">
                <p className="text-[13px] text-stone-500">
                  Generates the aligned BAMs and quality files needed for variant calling. Takes a few minutes.
                </p>
                <Button
                  type="button"
                  size="sm"
                  className="rounded-full bg-stone-900 px-4 text-white hover:bg-stone-800"
                  disabled={!canRun || isSubmitting || isSavingProfile}
                  onClick={() => void handleRun()}
                  data-testid="alignment-run-button"
                >
                  {isSubmitting ? (
                    <LoaderCircle className="mr-1.5 size-3.5 animate-spin" />
                  ) : latestRun ? (
                    <RotateCcw className="mr-1.5 size-3.5" />
                  ) : (
                    <Play className="mr-1.5 size-3.5" />
                  )}
                  {latestRun ? "Run again" : "Start alignment"}
                </Button>
              </div>
            )}
          </div>

          {summary.blockingReason ? (
            <div className="flex items-start gap-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-[13px] text-amber-800">
              <AlertTriangle className="mt-0.5 size-3.5 shrink-0" />
              <span>{summary.blockingReason}</span>
            </div>
          ) : null}

          {missingTools ? (
            <MissingToolsCallout error={missingTools} />
          ) : null}

          {memoryError ? (
            <InsufficientMemoryCallout error={memoryError} />
          ) : null}

          {error ? (
            <div className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-[13px] text-rose-700">
              {error}
            </div>
          ) : null}
        </div>
      </section>

      <ComputeSettingsSection disabled={isRunning} />

      {latestRun && !isRunning ? (
        <section className="rounded-2xl border border-stone-200 bg-white">
          <div className="space-y-3 px-5 py-4">
            <div className="flex items-center justify-between gap-3">
              <div>
                <h3 className="text-[15px] font-semibold text-stone-900">
                  Alignment quality
                </h3>
                <p className="mt-0.5 text-[13px] text-stone-500">
                  Quick sanity check before variant calling.
                </p>
              </div>
              <span
                className={cn(
                  "inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 font-mono text-[10px] uppercase tracking-[0.2em]",
                  pill.bg
                )}
              >
                <span
                  className={cn("inline-block size-1.5 rounded-full", pill.dot)}
                />
                {latestRun.qcVerdict
                  ? getQcVerdictLabel(latestRun.qcVerdict)
                  : "Pending"}
              </span>
            </div>

            <button
              type="button"
              onClick={() => setShowQuality((value) => !value)}
              aria-expanded={showQuality}
              className="flex items-center gap-1.5 text-[11px] font-medium text-stone-500 transition hover:text-stone-800"
            >
              <ChevronRight
                className={cn(
                  "size-3 transition-transform duration-200",
                  showQuality && "rotate-90"
                )}
              />
              {showQuality ? "Hide quality details" : "Show quality details"}
            </button>

            {showQuality ? (
              <div className="grid gap-3 border-t border-stone-100 pt-3 sm:grid-cols-2">
                {(["normal", "tumor"] as const).map((sampleLane) => {
                  const metrics = summary.laneMetrics[sampleLane];
                  return (
                    <div
                      key={sampleLane}
                      className="rounded-lg border border-stone-200 bg-stone-50/40 px-3 py-3"
                    >
                      <div className="flex items-center justify-between gap-3">
                        <span className="text-[13px] font-medium text-stone-800">
                          {sampleLane === "normal"
                            ? "Healthy sample"
                            : "Tumor sample"}
                        </span>
                        <span className="font-mono text-[10px] tracking-[0.14em] text-stone-400">
                          {metrics?.totalReads
                            ? `${metrics.totalReads.toLocaleString()} reads`
                            : "—"}
                        </span>
                      </div>
                      <div className="mt-2 grid grid-cols-2 gap-x-3 gap-y-1.5 text-[12px]">
                        {METRIC_DEFINITIONS.map((definition) => (
                          <div
                            key={definition.key}
                            className="flex items-center justify-between gap-2"
                          >
                            <span className="text-stone-500">
                              {definition.label}
                            </span>
                            <span className="font-mono text-stone-800">
                              {definition.format(
                                metricValue(metrics, definition.key)
                              )}
                            </span>
                          </div>
                        ))}
                      </div>
                    </div>
                  );
                })}
              </div>
            ) : null}
          </div>
        </section>
      ) : null}

      <details
        className="group rounded-2xl border border-stone-200 bg-white"
        data-testid="alignment-technical-panel"
      >
        <summary className="flex cursor-pointer list-none items-center justify-between gap-3 px-5 py-3 text-[13px] text-stone-600 transition-colors hover:text-stone-900">
          <span>Technical details</span>
          <ChevronRight className="size-3 shrink-0 text-stone-400 transition-transform duration-200 group-open:rotate-90" />
        </summary>

        <div className="space-y-4 border-t border-stone-100 px-5 py-4 text-[13px]">
          <div className="grid gap-3 sm:grid-cols-3">
            <div>
              <div className="font-mono text-[10px] uppercase tracking-[0.16em] text-stone-400">
                Latest run
              </div>
              <div className="mt-0.5 text-stone-800">
                {latestRun ? formatDateTime(latestRun.updatedAt) : "Not started"}
              </div>
            </div>
            <div>
              <div className="font-mono text-[10px] uppercase tracking-[0.16em] text-stone-400">
                Reference
              </div>
              <div className="mt-0.5 text-stone-800">
                {latestRun?.referenceLabel ??
                  formatReferencePreset(workspace.analysisProfile.referencePreset)}
              </div>
            </div>
            <div>
              <div className="font-mono text-[10px] uppercase tracking-[0.16em] text-stone-400">
                QC verdict
              </div>
              <div className="mt-0.5 text-stone-800">
                {latestRun?.qcVerdict
                  ? getQcVerdictLabel(latestRun.qcVerdict)
                  : "Pending"}
              </div>
            </div>
          </div>

          <div>
            <div className="font-mono text-[10px] uppercase tracking-[0.16em] text-stone-400">
              Commands
            </div>
            <pre className="mt-1.5 overflow-x-auto rounded-lg border border-stone-200 bg-stone-50 px-3 py-2.5 font-mono text-[11px] leading-5 whitespace-pre-wrap text-stone-700">
              {latestRun?.commandLog.length
                ? latestRun.commandLog.join("\n")
                : "Command log will appear here after the first run."}
            </pre>
          </div>

          <div>
            <div className="font-mono text-[10px] uppercase tracking-[0.16em] text-stone-400">
              Output files
            </div>
            {summary.artifacts.length ? (
              <ul className="mt-1.5 space-y-1">
                {summary.artifacts.map((artifact) => (
                  <li
                    key={artifact.id}
                    className="flex items-center justify-between gap-3 rounded-lg border border-stone-200 bg-white px-3 py-2 text-[12px]"
                  >
                    <div className="min-w-0">
                      <div className="truncate font-medium text-stone-800">
                        {artifact.filename}
                      </div>
                      <div className="font-mono text-[10px] text-stone-400">
                        {artifact.sampleLane
                          ? `${formatLaneLabel(artifact.sampleLane)} · ${artifact.artifactKind}`
                          : artifact.artifactKind}
                      </div>
                    </div>
                    <div className="flex shrink-0 items-center gap-2">
                      <span className="font-mono text-[10px] text-stone-400">
                        {formatBytes(artifact.sizeBytes)}
                      </span>
                      <button
                        type="button"
                        onClick={() =>
                          void handleOpenArtifact(
                            artifact.localPath,
                            artifact.downloadPath
                          )
                        }
                        className="inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-[11px] text-stone-500 transition-colors hover:bg-stone-100 hover:text-stone-800"
                      >
                        <FolderOpen className="size-3" />
                        Open
                      </button>
                    </div>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="mt-1.5 text-[12px] text-stone-400">
                BAM, BAI, flagstat, idxstats, and stats files will appear here after alignment finishes.
              </p>
            )}
          </div>
        </div>
      </details>
    </div>
  );
}

function MissingToolsCallout({ error }: { error: MissingToolsError }) {
  return (
    <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-3 text-[13px] text-amber-900">
      <div className="flex items-start gap-2 font-medium">
        <AlertTriangle className="mt-0.5 size-3.5 shrink-0" />
        <div>
          {error.tools.length === 1
            ? `${error.tools[0]} is not installed locally.`
            : `These tools are not installed locally: ${error.tools.join(", ")}.`}
        </div>
      </div>
      <p className="mt-1.5 pl-5 text-amber-800">
        Install them and reload, then try again.
      </p>
      <ul className="mt-2 space-y-1 pl-5">
        {error.hints.map((hint, index) => (
          <li
            key={index}
            className="overflow-x-auto rounded border border-amber-200/70 bg-white/70 px-2 py-1 font-mono text-[11px] leading-5 text-stone-700"
          >
            {hint}
          </li>
        ))}
      </ul>
      <p className="mt-2 pl-5 text-[12px] text-amber-700">
        See README → System requirements for the full install guide.
      </p>
    </div>
  );
}

function formatGiB(bytes: number): string {
  return `${(bytes / (1024 ** 3)).toFixed(0)} GB`;
}

function InsufficientMemoryCallout({
  error,
}: {
  error: InsufficientMemoryError;
}) {
  const availableLabel =
    error.availableBytes != null
      ? `${(error.availableBytes / (1024 ** 3)).toFixed(1)} GB`
      : "unknown";

  return (
    <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-3 text-[13px] text-amber-900">
      <div className="flex items-start gap-2 font-medium">
        <AlertTriangle className="mt-0.5 size-3.5 shrink-0" />
        <div>Not enough free memory for reference indexing.</div>
      </div>
      <p className="mt-1.5 pl-5 text-amber-800">
        strobealign builds the human genome index once on first run and peaks at
        around {formatGiB(error.requiredBytes)} of RAM. Right now only{" "}
        <span className="font-mono text-[12px]">{availableLabel}</span> is
        available.
      </p>
      <p className="mt-2 pl-5 text-amber-800">Two ways to unblock:</p>
      <ol className="mt-1 space-y-1 pl-9 text-amber-800 list-decimal">
        <li>
          Close the browser, IDE, and any heavy apps, then click{" "}
          <strong>Run again</strong>.
        </li>
        <li>
          Or run the standalone indexer in a clean terminal (safer on modest
          machines):
          <div className="mt-1 overflow-x-auto rounded border border-amber-200/70 bg-white/70 px-2 py-1 font-mono text-[11px] leading-5 text-stone-700">
            bash scripts/prepare-reference.sh
          </div>
        </li>
      </ol>
      <p className="mt-2 pl-5 text-[12px] text-amber-700">
        The download and partial indices are already on disk — only the final
        genome.fa.r150.sti file still needs to be built.
      </p>
    </div>
  );
}

function MemoryHairline() {
  const [memory, setMemory] = useState<SystemMemoryResponse | null>(null);
  const [isHovered, setIsHovered] = useState(false);

  useEffect(() => {
    let cancelled = false;
    const fetchMemory = () => {
      void api
        .getSystemMemory()
        .then((response) => {
          if (!cancelled) setMemory(response);
        })
        .catch(() => {});
    };

    fetchMemory();
    const timer = window.setInterval(fetchMemory, 2000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, []);

  if (!memory || memory.availableBytes == null || memory.totalBytes == null) {
    return null;
  }

  const usedBytes = memory.totalBytes - memory.availableBytes;
  const usedRatio = Math.min(1, Math.max(0, usedBytes / memory.totalBytes));
  const availabilityRatio = memory.availableBytes / memory.thresholdBytes;

  const tone =
    availabilityRatio < 1
      ? "rose"
      : availabilityRatio < 1.5
        ? "amber"
        : "stone";

  const fillClass =
    tone === "rose"
      ? "bg-rose-500/80"
      : tone === "amber"
        ? "bg-amber-500/80"
        : "bg-stone-400/60";

  const readoutClass =
    tone === "rose"
      ? "text-rose-700"
      : tone === "amber"
        ? "text-amber-700"
        : "text-stone-500";

  return (
    <div
      className="mt-1"
      onMouseEnter={() => setIsHovered(true)}
      onMouseLeave={() => setIsHovered(false)}
    >
      <div
        className={cn(
          "relative overflow-hidden rounded-full bg-stone-100 transition-all duration-200",
          isHovered ? "h-[3px]" : "h-px"
        )}
      >
        <div
          className={cn("h-full transition-all duration-500", fillClass)}
          style={{ width: `${usedRatio * 100}%` }}
        />
      </div>
      {isHovered ? (
        <div
          className={cn(
            "mt-0.5 text-right font-mono text-[10px] tabular-nums tracking-[0.08em]",
            readoutClass
          )}
        >
          {(usedBytes / 1024 ** 3).toFixed(1)} / {(memory.totalBytes / 1024 ** 3).toFixed(1)} GiB
        </div>
      ) : null}
    </div>
  );
}

function formatElapsed(seconds: number): string {
  if (!isFinite(seconds) || seconds < 0) return "—";
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = Math.floor(seconds % 60);
  if (h > 0) return `${h}h ${m}m elapsed`;
  if (m > 0) return `${m}m ${s}s elapsed`;
  return `${s}s elapsed`;
}

function ElapsedTimer({ startedAt }: { startedAt?: string | null }) {
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, []);

  if (!startedAt) return null;
  const started = Date.parse(startedAt);
  if (!isFinite(started)) return null;
  const elapsedSeconds = (now - started) / 1000;

  return (
    <span className="font-mono text-[11px] tabular-nums text-stone-500">
      {formatElapsed(elapsedSeconds)}
    </span>
  );
}

const LANES: SampleLane[] = ["tumor", "normal"];

const PHASE_LABELS: Record<ChunkProgressState["phase"], string> = {
  splitting: "Splitting",
  aligning: "Aligning",
  merging: "Merging",
};

const PHASE_TONES: Record<ChunkProgressState["phase"], string> = {
  splitting: "bg-stone-100 text-stone-600",
  aligning: "bg-amber-50 text-amber-700",
  merging: "bg-emerald-50 text-emerald-700",
};

function ChunkProgressStrips({ run }: { run: AlignmentRun }) {
  const states = run.chunkProgress ?? {};

  return (
    <div className="mt-2 space-y-1.5">
      {LANES.map((lane) => {
        const state = states[lane];
        return <ChunkProgressStrip key={lane} lane={lane} state={state ?? null} />;
      })}
    </div>
  );
}

function ChunkProgressStrip({
  lane,
  state,
}: {
  lane: SampleLane;
  state: ChunkProgressState | null;
}) {
  const total = state?.totalChunks ?? 0;
  const completed = state?.completedChunks ?? 0;
  const active = state?.activeChunks ?? 0;
  const phase = state?.phase ?? null;

  const cells = total > 0 ? total : 24;
  const completedClamped = Math.min(completed, cells);
  const activeStart = completedClamped;
  const activeEnd = Math.min(cells, completedClamped + active);

  return (
    <div className="flex items-center gap-2.5" data-lane={lane}>
      <span className="w-14 shrink-0 font-mono text-[10px] uppercase tracking-[0.18em] text-stone-500">
        {lane}
      </span>
      {phase ? (
        <span
          className={cn(
            "inline-flex shrink-0 items-center rounded-full px-1.5 py-0 font-mono text-[9px] uppercase tracking-[0.16em]",
            PHASE_TONES[phase]
          )}
        >
          {PHASE_LABELS[phase]}
        </span>
      ) : (
        <span className="inline-flex shrink-0 items-center rounded-full bg-stone-100 px-1.5 py-0 font-mono text-[9px] uppercase tracking-[0.16em] text-stone-400">
          Waiting
        </span>
      )}
      <div className="flex min-w-0 flex-1 items-center gap-2">
        <div className="flex min-w-0 flex-1 gap-[2px]">
          {Array.from({ length: cells }).map((_, index) => {
            let tint = "bg-stone-200";
            if (index < completedClamped) tint = "bg-emerald-500";
            else if (index >= activeStart && index < activeEnd)
              tint = "bg-amber-400";
            return (
              <span
                key={index}
                className={cn("h-1.5 flex-1 rounded-[1px] transition-colors", tint)}
              />
            );
          })}
        </div>
        <span className="shrink-0 font-mono text-[10px] tabular-nums text-stone-500">
          {total > 0 ? `${completed}/${total}` : "—"}
        </span>
      </div>
    </div>
  );
}

function formatReadsLabel(value: number): string {
  if (value >= 1_000_000) {
    return `${(value / 1_000_000).toFixed(value % 1_000_000 === 0 ? 0 : 1)}M reads`;
  }
  if (value >= 1_000) return `${(value / 1_000).toFixed(0)}K reads`;
  return `${value} reads`;
}

function formatGiBShort(bytes: number | null | undefined): string {
  if (bytes == null) return "—";
  return `${(bytes / 1024 ** 3).toFixed(0)} GiB`;
}

function formatTiBShort(bytes: number | null | undefined): string {
  if (bytes == null) return "—";
  if (bytes >= 1024 ** 4) return `${(bytes / 1024 ** 4).toFixed(1)} TB`;
  return `${(bytes / 1024 ** 3).toFixed(0)} GB`;
}

function parseMemoryToGiB(value: string): number | null {
  const match = value.trim().match(/^(\d+)([KMGT]?)$/);
  if (!match) return null;
  const magnitude = Number(match[1]);
  const unit = match[2];
  switch (unit) {
    case "K":
      return magnitude / (1024 * 1024);
    case "M":
      return magnitude / 1024;
    case "G":
    case "":
      return magnitude;
    case "T":
      return magnitude * 1024;
    default:
      return null;
  }
}

function ComputeSettingsSection({ disabled }: { disabled: boolean }) {
  const [resources, setResources] = useState<SystemResourcesResponse | null>(null);
  const [settings, setSettings] = useState<AlignmentSettings | null>(null);
  const [draft, setDraft] = useState<AlignmentSettings | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(async () => {
    try {
      const [resourcesResponse, settingsResponse] = await Promise.all([
        api.getSystemResources(),
        api.getAlignmentSettings(),
      ]);
      setResources(resourcesResponse);
      setSettings(settingsResponse);
      setDraft(settingsResponse);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load settings");
    }
  }, []);

  useEffect(() => {
    void reload();
  }, [reload]);

  const isDirty = useMemo(() => {
    if (!settings || !draft) return false;
    return (
      settings.alignerThreads !== draft.alignerThreads ||
      settings.samtoolsThreads !== draft.samtoolsThreads ||
      settings.samtoolsSortThreads !== draft.samtoolsSortThreads ||
      settings.samtoolsSortMemory !== draft.samtoolsSortMemory ||
      settings.chunkReads !== draft.chunkReads ||
      settings.chunkParallelism !== draft.chunkParallelism
    );
  }, [settings, draft]);

  const isOverrideFromDefaults = useMemo(() => {
    if (!settings) return false;
    const d = settings.defaults;
    return (
      settings.alignerThreads !== d.alignerThreads ||
      settings.samtoolsThreads !== d.samtoolsThreads ||
      settings.samtoolsSortThreads !== d.samtoolsSortThreads ||
      settings.samtoolsSortMemory !== d.samtoolsSortMemory ||
      settings.chunkReads !== d.chunkReads ||
      settings.chunkParallelism !== d.chunkParallelism
    );
  }, [settings]);

  const updateField = useCallback(
    <K extends keyof AlignmentSettings>(key: K, value: AlignmentSettings[K]) => {
      setDraft((prev) => (prev ? { ...prev, [key]: value } : prev));
    },
    []
  );

  const save = useCallback(async () => {
    if (!draft) return;
    setSaving(true);
    setError(null);
    try {
      const patch: AlignmentSettingsPatch = {
        alignerThreads: draft.alignerThreads,
        samtoolsThreads: draft.samtoolsThreads,
        samtoolsSortThreads: draft.samtoolsSortThreads,
        samtoolsSortMemory: draft.samtoolsSortMemory,
        chunkReads: draft.chunkReads,
        chunkParallelism: draft.chunkParallelism,
      };
      const updated = await api.updateAlignmentSettings(patch);
      setSettings(updated);
      setDraft(updated);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save settings");
    } finally {
      setSaving(false);
    }
  }, [draft]);

  const reset = useCallback(async () => {
    setSaving(true);
    setError(null);
    try {
      const updated = await api.updateAlignmentSettings({ reset: true });
      setSettings(updated);
      setDraft(updated);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to reset settings");
    } finally {
      setSaving(false);
    }
  }, []);

  const cpuCount = resources?.cpuCount ?? null;
  const totalMemGiB = resources?.totalMemoryBytes
    ? resources.totalMemoryBytes / 1024 ** 3
    : null;
  const availMemGiB = resources?.availableMemoryBytes
    ? resources.availableMemoryBytes / 1024 ** 3
    : null;

  const estimate = useMemo(() => {
    if (!draft) return null;
    const sortMemGiB = parseMemoryToGiB(draft.samtoolsSortMemory) ?? 2;
    const alignerBytesPerChunk = 8; // ~8 GiB per strobealign chunk
    const sortBytesPerChunk = draft.samtoolsSortThreads * sortMemGiB;
    const perChunk = alignerBytesPerChunk + sortBytesPerChunk;
    const userspace = 18;
    return draft.chunkParallelism * perChunk + userspace;
  }, [draft]);

  const estimateTone = useMemo(() => {
    if (estimate == null) return "stone";
    if (availMemGiB != null && estimate > availMemGiB) return "rose";
    if (totalMemGiB != null && estimate > totalMemGiB * 0.85) return "amber";
    return "stone";
  }, [estimate, availMemGiB, totalMemGiB]);

  const totalThreads = draft
    ? draft.alignerThreads * draft.chunkParallelism
    : null;
  const threadWarning =
    cpuCount != null && totalThreads != null && totalThreads > cpuCount;

  return (
    <details className="group rounded-2xl border border-stone-200 bg-white">
      <summary className="flex cursor-pointer list-none items-center justify-between gap-3 px-5 py-3 text-[13px] text-stone-600 transition-colors hover:text-stone-900">
        <div className="flex items-center gap-2">
          <ChevronRight className="size-3 transition-transform duration-200 group-open:rotate-90" />
          <Cpu className="size-3.5 text-stone-500" />
          <span className="font-medium text-stone-900">Compute settings</span>
          {isOverrideFromDefaults ? (
            <span className="rounded-full bg-emerald-50 px-1.5 py-0 font-mono text-[9px] uppercase tracking-[0.16em] text-emerald-700">
              Custom
            </span>
          ) : null}
        </div>
        <div className="flex items-center gap-2 font-mono text-[10px] uppercase tracking-[0.14em] text-stone-500">
          <span>{cpuCount != null ? `${cpuCount} cores` : "—"}</span>
          <span className="text-stone-300">·</span>
          <span>{formatGiBShort(resources?.totalMemoryBytes)} ram</span>
          <span className="text-stone-300">·</span>
          <span>
            {formatTiBShort(resources?.appDataDiskFreeBytes)} free
          </span>
        </div>
      </summary>
      <div className="space-y-4 border-t border-stone-100 px-5 py-4">
        {draft ? (
          <>
            <div className="grid gap-3 sm:grid-cols-2">
              <ComputeField
                label="Chunk size"
                hint="Smaller = more parallel work & merge overhead."
                defaultValue={formatReadsLabel(draft.defaults.chunkReads)}
              >
                <input
                  type="number"
                  min={1_000_000}
                  max={200_000_000}
                  step={1_000_000}
                  value={draft.chunkReads}
                  disabled={disabled || saving}
                  onChange={(event) =>
                    updateField("chunkReads", Number(event.target.value))
                  }
                  className="w-full rounded-lg border border-stone-200 bg-white px-2 py-1.5 font-mono text-[12px] tabular-nums text-stone-900 focus:border-emerald-400 focus:outline-none disabled:opacity-50"
                />
                <span className="mt-0.5 font-mono text-[10px] text-stone-400">
                  {formatReadsLabel(draft.chunkReads)}
                </span>
              </ComputeField>

              <ComputeField
                label="Parallel chunks"
                hint="2 is safe on 64 GB. Raise only with headroom."
                defaultValue={`${draft.defaults.chunkParallelism}`}
              >
                <input
                  type="number"
                  min={1}
                  max={8}
                  step={1}
                  value={draft.chunkParallelism}
                  disabled={disabled || saving}
                  onChange={(event) =>
                    updateField("chunkParallelism", Number(event.target.value))
                  }
                  className="w-full rounded-lg border border-stone-200 bg-white px-2 py-1.5 font-mono text-[12px] tabular-nums text-stone-900 focus:border-emerald-400 focus:outline-none disabled:opacity-50"
                />
              </ComputeField>

              <ComputeField
                label="Aligner threads per chunk"
                hint="Threads passed to strobealign -t."
                defaultValue={`${draft.defaults.alignerThreads}`}
              >
                <input
                  type="number"
                  min={1}
                  max={256}
                  step={1}
                  value={draft.alignerThreads}
                  disabled={disabled || saving}
                  onChange={(event) =>
                    updateField("alignerThreads", Number(event.target.value))
                  }
                  className="w-full rounded-lg border border-stone-200 bg-white px-2 py-1.5 font-mono text-[12px] tabular-nums text-stone-900 focus:border-emerald-400 focus:outline-none disabled:opacity-50"
                />
                {threadWarning ? (
                  <span className="mt-0.5 font-mono text-[10px] text-amber-600">
                    {totalThreads} total threads &gt; {cpuCount} cores
                  </span>
                ) : null}
              </ComputeField>

              <ComputeField
                label="Sort memory per thread"
                hint="samtools sort -m. Accepts 512M, 2G, 1024K."
                defaultValue={draft.defaults.samtoolsSortMemory}
              >
                <input
                  type="text"
                  value={draft.samtoolsSortMemory}
                  disabled={disabled || saving}
                  onChange={(event) =>
                    updateField("samtoolsSortMemory", event.target.value)
                  }
                  className="w-full rounded-lg border border-stone-200 bg-white px-2 py-1.5 font-mono text-[12px] tabular-nums text-stone-900 focus:border-emerald-400 focus:outline-none disabled:opacity-50"
                />
              </ComputeField>
            </div>

            <div
              className={cn(
                "flex flex-wrap items-center justify-between gap-2 rounded-lg border px-3 py-2 text-[12px]",
                estimateTone === "rose"
                  ? "border-rose-200 bg-rose-50 text-rose-700"
                  : estimateTone === "amber"
                    ? "border-amber-200 bg-amber-50 text-amber-800"
                    : "border-stone-200 bg-stone-50 text-stone-600"
              )}
            >
              <div>
                <span className="font-medium">Expected peak RAM </span>
                <span className="font-mono tabular-nums">
                  ~{estimate?.toFixed(0)} GiB
                </span>
                {totalMemGiB != null ? (
                  <span className="text-stone-500">
                    {" "}
                    of {totalMemGiB.toFixed(0)} GiB total
                  </span>
                ) : null}
              </div>
              <div className="font-mono text-[10px] uppercase tracking-[0.14em] text-stone-500">
                {draft.chunkParallelism} × (strobealign + sort) + userspace
              </div>
            </div>

            {error ? (
              <div className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-[12px] text-rose-700">
                {error}
              </div>
            ) : null}

            <div className="flex items-center justify-between gap-3">
              <button
                type="button"
                onClick={() => void reset()}
                disabled={disabled || saving || !isOverrideFromDefaults}
                className="text-[12px] font-medium text-stone-500 transition hover:text-stone-900 disabled:cursor-not-allowed disabled:opacity-40"
              >
                Reset to defaults
              </button>
              <Button
                type="button"
                size="sm"
                disabled={disabled || saving || !isDirty}
                onClick={() => void save()}
                className="rounded-full bg-stone-900 px-4 text-white hover:bg-stone-800"
              >
                {saving ? (
                  <LoaderCircle className="mr-1.5 size-3.5 animate-spin" />
                ) : null}
                Save
              </Button>
            </div>
          </>
        ) : error ? (
          <div className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-[12px] text-rose-700">
            {error}
          </div>
        ) : (
          <div className="flex items-center gap-2 text-[12px] text-stone-500">
            <LoaderCircle className="size-3 animate-spin" /> Loading…
          </div>
        )}
      </div>
    </details>
  );
}

function ComputeField({
  label,
  hint,
  defaultValue,
  children,
}: {
  label: string;
  hint: string;
  defaultValue: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex flex-col gap-1">
      <div className="flex items-baseline justify-between gap-2">
        <span className="font-mono text-[10px] uppercase tracking-[0.16em] text-stone-500">
          {label}
        </span>
        <span className="font-mono text-[10px] text-stone-400">
          default {defaultValue}
        </span>
      </div>
      {children}
      <span className="text-[11px] leading-4 text-stone-500">{hint}</span>
    </div>
  );
}
