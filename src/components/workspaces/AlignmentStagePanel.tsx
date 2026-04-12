"use client";

import { useEffect, useState } from "react";
import {
  AlertTriangle,
  Check,
  ChevronRight,
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
  AlignmentStageSummary,
  AssayType,
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
                  <span className="font-mono text-[11px] text-stone-500">
                    {Math.round(latestRun.progress * 100)}%
                  </span>
                </div>
                <div className="h-1 overflow-hidden rounded-full bg-stone-200">
                  <div
                    className="h-full rounded-full bg-emerald-500/70 transition-[width] duration-500"
                    style={{
                      width: `${Math.max(3, Math.round(latestRun.progress * 100))}%`,
                    }}
                  />
                </div>
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
        bwa-mem2 builds the human genome index once on first run and peaks at
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
        genome.fa.bwt.2bit.64 file still needs to be built.
      </p>
    </div>
  );
}
