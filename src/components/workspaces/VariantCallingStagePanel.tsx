"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle,
  ChevronRight,
  FolderOpen,
  LockKeyhole,
  Pause,
  Play,
  RotateCw,
  Square,
  Telescope,
} from "lucide-react";

import Karyogram from "@/components/workspaces/variant-calling/Karyogram";
import MetricsRibbon from "@/components/workspaces/variant-calling/MetricsRibbon";
import FilterBreakdown from "@/components/workspaces/variant-calling/FilterBreakdown";
import VafDistribution from "@/components/workspaces/variant-calling/VafDistribution";
import TopVariantsTable from "@/components/workspaces/variant-calling/TopVariantsTable";

import {
  api,
  InsufficientMemoryError,
  MissingToolsError,
  StageNotActionableError,
} from "@/lib/api";
import { getDesktopBridge } from "@/lib/desktop";
import type {
  VariantCallingArtifact,
  VariantCallingRuntimePhase,
  VariantCallingStageSummary,
  Workspace,
} from "@/lib/types";
import { formatBytes, formatDateTime } from "@/lib/workspace-utils";
import { cn } from "@/lib/utils";

interface VariantCallingStagePanelProps {
  workspace: Workspace;
  initialSummary: VariantCallingStageSummary;
}

type BannerState =
  | "blocked"
  | "ready"
  | "running"
  | "paused"
  | "completed"
  | "failed";

function bannerStateOf(summary: VariantCallingStageSummary): BannerState {
  if (summary.status === "blocked") return "blocked";
  if (summary.status === "running") return "running";
  if (summary.status === "paused") return "paused";
  if (summary.status === "completed") return "completed";
  if (summary.status === "failed") return "failed";
  return "ready";
}

const PILL_TONES: Record<BannerState, { label: string; bg: string; dot: string }> = {
  blocked: { label: "Locked", bg: "bg-stone-100 text-stone-500", dot: "bg-stone-400" },
  ready: { label: "Ready", bg: "bg-sky-50 text-sky-700", dot: "bg-sky-500" },
  running: { label: "Running", bg: "bg-amber-50 text-amber-700", dot: "bg-amber-500" },
  paused: { label: "Paused", bg: "bg-indigo-50 text-indigo-700", dot: "bg-indigo-500" },
  completed: { label: "Complete", bg: "bg-emerald-50 text-emerald-700", dot: "bg-emerald-500" },
  failed: { label: "Failed", bg: "bg-rose-50 text-rose-700", dot: "bg-rose-500" },
};

function artifactKindLabel(kind: VariantCallingArtifact["artifactKind"]) {
  if (kind === "vcf") return "Somatic VCF";
  if (kind === "tbi") return "VCF index";
  return "Mutect2 stats";
}

export default function VariantCallingStagePanel({
  workspace,
  initialSummary,
}: VariantCallingStagePanelProps) {
  const [summary, setSummary] = useState(initialSummary);
  const [actionError, setActionError] = useState<string | null>(null);
  const [missingTools, setMissingTools] = useState<{
    tools: string[];
    hints: string[];
  } | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const isFirstRender = useRef(true);

  // Keep the latest initialSummary available when the user changes workspaces
  // or navigates back into this stage — the parent passes fresh server data
  // each time.
  useEffect(() => {
    if (isFirstRender.current) {
      isFirstRender.current = false;
      return;
    }
    setSummary(initialSummary);
    setActionError(null);
    setMissingTools(null);
  }, [initialSummary]);

  useEffect(() => {
    if (summary.status !== "running" && summary.status !== "paused") {
      return;
    }
    const timer = window.setInterval(() => {
      void api
        .getVariantCallingStageSummary(workspace.id)
        .then(setSummary)
        .catch(() => {});
    }, 2000);
    return () => window.clearInterval(timer);
  }, [summary.status, workspace.id]);

  const bannerState = bannerStateOf(summary);
  const pill = PILL_TONES[bannerState];
  const latestRun = summary.latestRun;
  const metrics = latestRun?.metrics ?? null;

  const handleRun = useCallback(async () => {
    setActionError(null);
    setMissingTools(null);
    setIsSubmitting(true);
    try {
      const next = await api.runVariantCalling(workspace.id);
      setSummary(next);
    } catch (error) {
      if (error instanceof MissingToolsError) {
        setMissingTools({ tools: error.tools, hints: error.hints });
      } else if (error instanceof InsufficientMemoryError) {
        setActionError(error.message);
      } else if (error instanceof StageNotActionableError) {
        setActionError(error.message);
      } else if (error instanceof Error) {
        setActionError(error.message);
      } else {
        setActionError("Unable to start variant calling.");
      }
    } finally {
      setIsSubmitting(false);
    }
  }, [workspace.id]);

  const handleRerun = useCallback(async () => {
    setActionError(null);
    setMissingTools(null);
    setIsSubmitting(true);
    try {
      const next = await api.rerunVariantCalling(workspace.id);
      setSummary(next);
    } catch (error) {
      if (error instanceof MissingToolsError) {
        setMissingTools({ tools: error.tools, hints: error.hints });
      } else if (error instanceof Error) {
        setActionError(error.message);
      } else {
        setActionError("Unable to rerun variant calling.");
      }
    } finally {
      setIsSubmitting(false);
    }
  }, [workspace.id]);

  const handleCancel = useCallback(async () => {
    if (!latestRun) return;
    setActionError(null);
    setIsSubmitting(true);
    try {
      const next = await api.cancelVariantCalling(workspace.id, latestRun.id);
      setSummary(next);
    } catch (error) {
      if (error instanceof Error) {
        setActionError(error.message);
      } else {
        setActionError("Unable to stop the run.");
      }
    } finally {
      setIsSubmitting(false);
    }
  }, [workspace.id, latestRun]);

  const handlePause = useCallback(async () => {
    if (!latestRun) return;
    setActionError(null);
    setIsSubmitting(true);
    try {
      const next = await api.pauseVariantCalling(workspace.id, latestRun.id);
      setSummary(next);
    } catch (error) {
      if (error instanceof Error) {
        setActionError(error.message);
      } else {
        setActionError("Unable to pause the run.");
      }
    } finally {
      setIsSubmitting(false);
    }
  }, [workspace.id, latestRun]);

  const handleResume = useCallback(async () => {
    if (!latestRun) return;
    setActionError(null);
    setIsSubmitting(true);
    try {
      const next = await api.resumeVariantCalling(workspace.id, latestRun.id);
      setSummary(next);
    } catch (error) {
      if (error instanceof Error) {
        setActionError(error.message);
      } else {
        setActionError("Unable to resume the run.");
      }
    } finally {
      setIsSubmitting(false);
    }
  }, [workspace.id, latestRun]);

  const handleOpenArtifact = useCallback(
    async (artifact: VariantCallingArtifact) => {
      const desktop = getDesktopBridge();
      const localPath = artifact.localPath ?? null;
      if (!desktop || !localPath) {
        window.location.href = api.resolveDownloadUrl(artifact.downloadPath);
        return;
      }
      await desktop.openPath(localPath);
    },
    []
  );

  const elapsedLabel = useMemo(() => {
    if (!latestRun?.startedAt) return null;
    const started = new Date(latestRun.startedAt).getTime();
    if (Number.isNaN(started)) return null;
    const referenceTime = latestRun.completedAt
      ? new Date(latestRun.completedAt).getTime()
      : Date.now();
    const elapsedMs = Math.max(0, referenceTime - started);
    const minutes = Math.floor(elapsedMs / 60_000);
    const seconds = Math.floor((elapsedMs % 60_000) / 1000);
    return `${minutes}m ${seconds.toString().padStart(2, "0")}s`;
  }, [latestRun?.startedAt, latestRun?.completedAt]);

  const showDescription =
    bannerState !== "running" &&
    bannerState !== "paused" &&
    bannerState !== "completed";

  return (
    <div className="space-y-3" data-testid="variant-calling-stage-panel">
      <section className="rounded-2xl border border-stone-200 bg-white">
        <div className="space-y-5 px-5 py-4">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div className="min-w-0 max-w-2xl">
              <div className="flex flex-wrap items-center gap-2.5">
                <h3 className="font-display text-[22px] leading-tight font-light text-stone-900">
                  Find the cancer-specific mutations
                </h3>
                <span
                  data-testid="variant-calling-stage-status-strip"
                  data-state={summary.status}
                  className={cn(
                    "inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 font-mono text-[10px] uppercase tracking-[0.2em]",
                    pill.bg
                  )}
                >
                  <span className={cn("inline-block size-1.5 rounded-full", pill.dot)} />
                  {pill.label}
                </span>
                {latestRun?.accelerationMode === "gpu_parabricks" ? (
                  <span
                    data-testid="variant-calling-acceleration-mode"
                    data-mode="gpu_parabricks"
                    className="inline-flex items-center gap-1.5 rounded-full bg-emerald-50 px-2.5 py-0.5 font-mono text-[10px] uppercase tracking-[0.2em] text-emerald-700"
                  >
                    <span className="inline-block size-1.5 rounded-full bg-emerald-500" />
                    GPU
                  </span>
                ) : latestRun ? (
                  <span
                    data-testid="variant-calling-acceleration-mode"
                    data-mode="cpu_gatk"
                    className="inline-flex items-center gap-1.5 rounded-full bg-stone-100 px-2.5 py-0.5 font-mono text-[10px] uppercase tracking-[0.2em] text-stone-600"
                  >
                    CPU
                  </span>
                ) : null}
              </div>
              {showDescription ? (
                <p className="mt-2 text-[13px] leading-6 text-stone-500">
                  We compare the cancer sample to the healthy sample, set aside
                  anything that looks like a sequencing glitch or an inherited
                  genetic variant, and show you what is left — the changes that
                  are only in the cancer.
                </p>
              ) : null}
            </div>

            <div className="flex flex-wrap items-center gap-2">
              {bannerState === "ready" ? (
                <button
                  type="button"
                  data-testid="variant-calling-run-button"
                  disabled={isSubmitting}
                  onClick={handleRun}
                  className="inline-flex items-center gap-1.5 rounded-full bg-emerald-600 px-3 py-1.5 text-[12px] font-medium text-white transition hover:bg-emerald-500 disabled:cursor-not-allowed disabled:opacity-60"
                >
                  <Play className="size-3" />
                  Find mutations
                </button>
              ) : null}
              {bannerState === "running" && latestRun ? (
                <>
                  <button
                    type="button"
                    data-testid="variant-calling-pause-button"
                    disabled={isSubmitting}
                    onClick={handlePause}
                    className="inline-flex items-center gap-1.5 rounded-full border border-amber-300 bg-amber-50 px-3 py-1.5 text-[12px] font-medium text-amber-800 transition hover:bg-amber-100 disabled:cursor-not-allowed disabled:opacity-60"
                  >
                    <Pause className="size-3" />
                    Pause & keep progress
                  </button>
                  <button
                    type="button"
                    disabled={isSubmitting}
                    onClick={handleCancel}
                    className="inline-flex items-center gap-1.5 rounded-full border border-rose-200 bg-white px-3 py-1.5 text-[12px] font-medium text-rose-700 transition hover:bg-rose-50 disabled:cursor-not-allowed disabled:opacity-60"
                  >
                    <Square className="size-3" />
                    Cancel & discard
                  </button>
                </>
              ) : null}
              {bannerState === "paused" && latestRun ? (
                <>
                  <button
                    type="button"
                    disabled={isSubmitting}
                    onClick={handleCancel}
                    className="inline-flex items-center gap-1.5 rounded-full border border-rose-200 bg-white px-3 py-1.5 text-[12px] font-medium text-rose-700 transition hover:bg-rose-50 disabled:cursor-not-allowed disabled:opacity-60"
                  >
                    <Square className="size-3" />
                    Discard & restart
                  </button>
                  <button
                    type="button"
                    data-testid="variant-calling-resume-button"
                    disabled={isSubmitting}
                    onClick={handleResume}
                    className="inline-flex items-center gap-1.5 rounded-full bg-emerald-600 px-3 py-1.5 text-[12px] font-medium text-white transition hover:bg-emerald-500 disabled:cursor-not-allowed disabled:opacity-60"
                  >
                    <Play className="size-3" />
                    Resume search
                  </button>
                </>
              ) : null}
              {(bannerState === "completed" || bannerState === "failed") ? (
                <button
                  type="button"
                  data-testid="variant-calling-rerun-button"
                  disabled={isSubmitting}
                  onClick={handleRerun}
                  className="inline-flex items-center gap-1.5 rounded-full border border-stone-300 bg-white px-3 py-1.5 text-[12px] font-medium text-stone-700 transition hover:bg-stone-50 disabled:cursor-not-allowed disabled:opacity-60"
                >
                  <RotateCw className="size-3" />
                  Search again
                </button>
              ) : null}
            </div>
          </div>

          {bannerState === "blocked" ? (
            <div className="flex items-start gap-2 rounded-lg border border-stone-200 bg-stone-50 px-3 py-2.5 text-[13px] text-stone-600">
              <LockKeyhole className="mt-0.5 size-3.5 shrink-0 text-stone-400" />
              <span>{summary.blockingReason ?? "Locked — finish alignment first."}</span>
            </div>
          ) : null}

          {missingTools ? (
            <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-3 text-[13px] text-amber-900">
              <div className="flex items-center gap-2 font-medium">
                <AlertTriangle className="size-3.5" />
                Install {missingTools.tools.join(" and ")} to continue
              </div>
              <ul className="mt-2 space-y-1 text-[12px] text-amber-800">
                {missingTools.hints.map((hint, index) => (
                  <li key={index} className="font-mono text-[11px] leading-5">
                    {hint}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}

          {actionError ? (
            <div className="flex items-start gap-2 rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-[13px] text-rose-700">
              <AlertTriangle className="mt-0.5 size-3.5 shrink-0" />
              <span>{actionError}</span>
            </div>
          ) : null}

          {bannerState === "running" && latestRun ? (
            <div className="space-y-2.5">
              <div className="flex items-center justify-between gap-3 font-mono text-[10px] uppercase tracking-[0.2em] text-stone-500">
                <span>
                  {latestRun.totalShards > 0
                    ? `${latestRun.completedShards} / ${latestRun.totalShards} chromosomes done`
                    : phaseRunningLabel(latestRun.runtimePhase)}
                </span>
                <span className="flex items-center gap-2">
                  <span>{elapsedLabel}</span>
                  <span className="text-stone-300">·</span>
                  <span>{Math.round(latestRun.progress * 100)}%</span>
                </span>
              </div>
              <div className="h-1 overflow-hidden rounded-full bg-stone-200">
                <div
                  className="h-full rounded-full bg-gradient-to-r from-emerald-500 via-sky-500 to-indigo-500 transition-[width] duration-500"
                  style={{
                    width: `${Math.max(3, Math.round(latestRun.progress * 100))}%`,
                  }}
                />
              </div>
              <PhaseTimeline currentPhase={latestRun.runtimePhase} />
            </div>
          ) : null}

          {bannerState === "paused" && latestRun ? (
            <div className="space-y-3 rounded-xl border border-indigo-200 bg-indigo-50/60 px-4 py-3 text-[13px] text-indigo-900">
              <div className="flex items-start gap-3">
                <Pause className="mt-0.5 size-4 shrink-0 text-indigo-700" />
                <div className="flex-1">
                  <div className="font-medium">
                    Paused
                    {latestRun.totalShards > 0
                      ? ` at ${latestRun.completedShards} / ${latestRun.totalShards} chromosomes`
                      : ""}
                  </div>
                  <p className="mt-1 leading-6 text-indigo-900/80">
                    Work done so far is saved on disk. Resume picks up from the
                    next chromosome — discard wipes the progress and starts
                    fresh.
                  </p>
                </div>
              </div>
              {latestRun.totalShards > 0 ? (
                <div className="h-1 overflow-hidden rounded-full bg-indigo-100">
                  <div
                    className="h-full rounded-full bg-indigo-500"
                    style={{
                      width: `${Math.max(
                        3,
                        Math.round(
                          (latestRun.completedShards / latestRun.totalShards) * 100
                        )
                      )}%`,
                    }}
                  />
                </div>
              ) : null}
            </div>
          ) : null}

          {bannerState === "ready" && !latestRun ? (
            <div className="flex items-start gap-3 rounded-xl border border-emerald-200 bg-emerald-50/60 px-4 py-3 text-[13px] text-emerald-900">
              <Telescope className="mt-0.5 size-4 shrink-0 text-emerald-700" />
              <div>
                <div className="font-medium">Ready to search</div>
                <p className="mt-1 leading-6 text-emerald-800/90">
                  This runs on your computer using the reference genome for
                  your pet&apos;s species. When it finishes, you get a list of
                  mutations you can explore below.
                </p>
              </div>
            </div>
          ) : null}

          {latestRun?.error && bannerState === "failed" ? (
            <div className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-2.5 text-[13px] text-rose-800">
              <div className="flex items-center gap-2 font-medium">
                <AlertTriangle className="size-3.5" />
                The search failed
              </div>
              <p className="mt-1 font-mono text-[11px] leading-5 text-rose-700">
                {latestRun.error}
              </p>
            </div>
          ) : null}
        </div>
      </section>

      {metrics && metrics.totalVariants > 0 ? (
        <>
          <Karyogram
            chromosomes={metrics.perChromosome}
            topVariants={metrics.topVariants}
          />

          <MetricsRibbon metrics={metrics} />

          <div className="grid gap-3 lg:grid-cols-2">
            <FilterBreakdown
              entries={metrics.filterBreakdown}
              totalVariants={metrics.totalVariants}
            />
            <VafDistribution
              bins={metrics.vafHistogram}
              meanVaf={metrics.meanVaf}
              medianVaf={metrics.medianVaf}
            />
          </div>

          <TopVariantsTable variants={metrics.topVariants} />
        </>
      ) : null}

      {bannerState === "completed" && (!metrics || metrics.totalVariants === 0) ? (
        <div className="rounded-2xl border border-stone-200 bg-white px-5 py-6 text-[13px] text-stone-600">
          The search finished without finding any mutations. That is unusual
          on real sequencing data — open the technical details below and
          check the alignment quality for coverage gaps.
        </div>
      ) : null}

      <details className="group rounded-2xl border border-stone-200 bg-white">
        <summary className="flex cursor-pointer list-none items-center justify-between gap-3 px-5 py-3 text-[13px] text-stone-600 transition-colors hover:text-stone-900">
          <div className="flex items-center gap-2">
            <ChevronRight className="size-3 transition-transform duration-200 group-open:rotate-90" />
            <span className="font-medium text-stone-900">Technical details</span>
          </div>
          <span className="font-mono text-[10px] uppercase tracking-[0.16em] text-stone-400">
            run info · artifacts · commands
          </span>
        </summary>

        <div className="space-y-4 border-t border-stone-100 px-5 py-4">
          {latestRun ? (
            <div className="grid gap-3 sm:grid-cols-3">
              <DetailCell
                label="Started"
                value={latestRun.startedAt ? formatDateTime(latestRun.startedAt) : "—"}
              />
              <DetailCell
                label="Completed"
                value={latestRun.completedAt ? formatDateTime(latestRun.completedAt) : "—"}
              />
              <DetailCell label="Status" value={latestRun.status} />
              {metrics?.referenceLabel ? (
                <DetailCell label="Reference" value={metrics.referenceLabel} />
              ) : null}
              {metrics?.tumorSample ? (
                <DetailCell label="Tumor sample" value={metrics.tumorSample} />
              ) : null}
              {metrics?.normalSample ? (
                <DetailCell label="Normal sample" value={metrics.normalSample} />
              ) : null}
            </div>
          ) : (
            <p className="text-[13px] text-stone-500">
              No runs yet. Start the search from the control bar above —
              details, command log, and artifacts will land here.
            </p>
          )}

          {latestRun && latestRun.commandLog.length > 0 ? (
            <div>
              <div className="font-mono text-[10px] uppercase tracking-[0.16em] text-stone-500">
                Command log
              </div>
              <pre className="mt-1.5 max-h-64 overflow-auto rounded-lg border border-stone-200 bg-stone-950 px-3 py-2 font-mono text-[11px] leading-5 text-emerald-200/90">
                {latestRun.commandLog.join("\n")}
              </pre>
            </div>
          ) : null}

          <div>
            <div className="font-mono text-[10px] uppercase tracking-[0.16em] text-stone-500">
              Output files
            </div>
            {summary.artifacts.length > 0 ? (
              <ul className="mt-2 space-y-1.5">
                {summary.artifacts.map((artifact) => (
                  <li
                    key={artifact.id}
                    className="flex items-center justify-between gap-3 rounded-lg border border-stone-200 bg-white px-3 py-2"
                  >
                    <div className="min-w-0">
                      <div className="truncate text-[13px] text-stone-900">
                        {artifact.filename}
                      </div>
                      <div className="mt-0.5 flex items-center gap-2 font-mono text-[10px] uppercase tracking-[0.16em] text-stone-500">
                        <span>{artifactKindLabel(artifact.artifactKind)}</span>
                        <span className="text-stone-300">·</span>
                        <span>{formatBytes(artifact.sizeBytes)}</span>
                      </div>
                    </div>
                    <button
                      type="button"
                      onClick={() => void handleOpenArtifact(artifact)}
                      className="inline-flex shrink-0 items-center gap-1.5 rounded-full border border-stone-200 px-3 py-1 text-[11px] text-stone-700 transition hover:border-stone-300 hover:bg-stone-50"
                    >
                      <FolderOpen className="size-3" />
                      Open
                    </button>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="mt-1.5 text-[13px] text-stone-500">
                Variant-calling output files will appear here once a run
                completes.
              </p>
            )}
          </div>
        </div>
      </details>
    </div>
  );
}

function DetailCell({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="font-mono text-[10px] uppercase tracking-[0.16em] text-stone-500">
        {label}
      </div>
      <div className="mt-0.5 text-[13px] text-stone-900">{value}</div>
    </div>
  );
}

function phaseRunningLabel(phase: VariantCallingRuntimePhase | null | undefined): string {
  switch (phase) {
    case "preparing_reference":
      return "Preparing reference";
    case "calling":
      return "Searching the genome";
    case "filtering":
      return "Filtering variants";
    case "finalizing":
      return "Wrapping up";
    default:
      return "Preparing reference";
  }
}

function PhaseTimeline({ currentPhase }: { currentPhase?: VariantCallingRuntimePhase | null }) {
  const phases: Array<{ id: VariantCallingRuntimePhase; label: string }> = [
    { id: "preparing_reference", label: "Reference" },
    { id: "calling", label: "Searching" },
    { id: "filtering", label: "Filtering" },
    { id: "finalizing", label: "Wrapping up" },
  ];
  const currentIndex = phases.findIndex((phase) => phase.id === currentPhase);

  return (
    <ol className="mt-2 grid grid-cols-4 gap-1.5 text-[10px] font-mono uppercase tracking-[0.18em] text-stone-500">
      {phases.map((phase, index) => {
        const isActive = index === currentIndex;
        const isDone = currentIndex >= 0 && index < currentIndex;
        return (
          <li
            key={phase.id}
            className={cn(
              "flex items-center gap-1.5 rounded-md border px-2 py-1",
              isActive
                ? "border-emerald-200 bg-emerald-50 text-emerald-800"
                : isDone
                  ? "border-stone-200 bg-white text-stone-600"
                  : "border-stone-100 bg-stone-50 text-stone-400"
            )}
          >
            <span
              className={cn(
                "inline-block size-1.5 rounded-full",
                isActive
                  ? "bg-emerald-500 animate-pulse"
                  : isDone
                    ? "bg-stone-400"
                    : "bg-stone-300"
              )}
            />
            <span className="truncate">{phase.label}</span>
          </li>
        );
      })}
    </ol>
  );
}
