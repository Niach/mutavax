"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import Helix from "@/components/helix/Helix";
import {
  Btn,
  Callout,
  Card,
  CardHead,
  Dot,
  Eyebrow,
  MonoLabel,
  Spinner,
} from "@/components/ui-kit";
import { useTweaks } from "@/components/dev/TweaksProvider";
import {
  api,
  InsufficientMemoryError,
  MissingToolsError,
} from "@/lib/api";
import type {
  AlignmentRun,
  AlignmentStageSummary,
  SampleLane,
  Workspace,
} from "@/lib/types";
import { formatReferencePresetCodename } from "@/lib/workspace-utils";

interface AlignmentStagePanelProps {
  workspace: Workspace;
  summary: AlignmentStageSummary;
  onWorkspaceChange: (workspace: Workspace) => void;
  onSummaryChange: (summary: AlignmentStageSummary) => void;
}

type BannerState = "fresh" | "running" | "paused" | "complete" | "failed";

function bannerStateOf(summary: AlignmentStageSummary): BannerState {
  if (summary.status === "running") return "running";
  if (summary.status === "paused") return "paused";
  if (summary.status === "failed") return "failed";
  if (summary.status === "completed") return "complete";
  return "fresh";
}

function formatElapsedLabel(run: AlignmentRun | null | undefined): string | null {
  if (!run?.startedAt) return null;
  const started = Date.parse(run.startedAt);
  if (!isFinite(started)) return null;
  const end = run.completedAt ? Date.parse(run.completedAt) : Date.now();
  const seconds = Math.max(0, Math.round((end - started) / 1000));
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  if (h > 0) return `${h}h ${m}m`;
  const s = seconds % 60;
  return `${m}m ${s}s`;
}

function formatEta(seconds?: number | null): string | null {
  if (seconds == null || !isFinite(seconds) || seconds <= 0) return null;
  if (seconds < 60) return "<1m";
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  return h > 0 ? `${h}h ${m}m` : `${m}m`;
}

export default function AlignmentStagePanel({
  workspace,
  summary,
  onSummaryChange,
}: AlignmentStagePanelProps) {
  const { tweaks } = useTweaks();
  const [submitting, setSubmitting] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [missingTools, setMissingTools] = useState<MissingToolsError | null>(null);
  const [memoryError, setMemoryError] = useState<InsufficientMemoryError | null>(
    null
  );

  useEffect(() => {
    if (summary.status !== "running") return;
    const timer = window.setInterval(() => {
      void api
        .getAlignmentStageSummary(workspace.id)
        .then(onSummaryChange)
        .catch(() => {});
    }, 2000);
    return () => window.clearInterval(timer);
  }, [summary.status, workspace.id, onSummaryChange]);

  const bannerState = bannerStateOf(summary);
  const latestRun = summary.latestRun ?? null;
  const canStart =
    summary.status === "ready" ||
    summary.status === "completed" ||
    summary.status === "failed";

  async function runAction(action: () => Promise<AlignmentStageSummary>) {
    setSubmitting(true);
    setActionError(null);
    setMissingTools(null);
    setMemoryError(null);
    try {
      const next = await action();
      onSummaryChange(next);
    } catch (err) {
      if (err instanceof MissingToolsError) setMissingTools(err);
      else if (err instanceof InsufficientMemoryError) setMemoryError(err);
      else if (err instanceof Error) setActionError(err.message);
      else setActionError("Unable to complete the action.");
    } finally {
      setSubmitting(false);
    }
  }

  const runId = latestRun?.id;

  const referenceCode = formatReferencePresetCodename(
    workspace.analysisProfile.referencePreset
  );

  return (
    <>
      <div className="cs-view-head">
        <div>
          <div className="cs-crumb">{workspace.displayName} / 02 Alignment</div>
          <h1>
            {bannerState === "fresh" && `Align reads to ${referenceCode}.`}
            {bannerState === "running" && "Aligning."}
            {bannerState === "paused" && "Paused. Progress kept."}
            {bannerState === "complete" &&
              (summary.qcVerdict === "warn" ? (
                "Finished with warnings."
              ) : summary.qcVerdict === "fail" ? (
                "QC didn't pass."
              ) : (
                <>
                  QC passed in{" "}
                  <span
                    style={{
                      fontFamily: "var(--font-mono)",
                      fontSize: "0.85em",
                    }}
                  >
                    {formatElapsedLabel(latestRun) ?? "—"}
                  </span>
                  .
                </>
              ))}
            {bannerState === "failed" && "This run needs another try."}
          </h1>
          <p
            style={{
              maxWidth: "58ch",
              marginTop: 12,
              fontSize: 16.5,
              lineHeight: 1.6,
              color: "var(--ink-2)",
            }}
          >
            We match every short piece of DNA to where it belongs in the
            reference genome. It runs in parallel, saves as it goes, and you can
            pause any time without losing work.
          </p>
        </div>
      </div>

      {actionError ? (
        <Callout tone="warm" style={{ marginBottom: 16 }}>
          <Dot style={{ color: "var(--danger)" }} />
          <div style={{ flex: 1, fontSize: 14 }}>{actionError}</div>
        </Callout>
      ) : null}

      {missingTools ? (
        <Callout tone="warm" style={{ marginBottom: 16 }}>
          <Dot style={{ color: "var(--warm)" }} />
          <div style={{ flex: 1, fontSize: 14, color: "var(--ink)" }}>
            Install {missingTools.tools.join(" and ")} to continue.
            <ul
              style={{
                margin: "6px 0 0",
                padding: 0,
                listStyle: "none",
                display: "flex",
                flexDirection: "column",
                gap: 4,
              }}
            >
              {missingTools.hints.map((hint, i) => (
                <li
                  key={i}
                  style={{
                    fontFamily: "var(--font-mono)",
                    fontSize: 11,
                    padding: "4px 8px",
                    background: "var(--surface-sunk)",
                    border: "1px solid var(--line)",
                    borderRadius: 4,
                  }}
                >
                  {hint}
                </li>
              ))}
            </ul>
          </div>
        </Callout>
      ) : null}

      {memoryError ? (
        <Callout tone="warm" style={{ marginBottom: 16 }}>
          <Dot style={{ color: "var(--warm)" }} />
          <div style={{ flex: 1, fontSize: 14 }}>{memoryError.message}</div>
        </Callout>
      ) : null}

      <Card>
        <div style={{ padding: "24px 28px 20px" }}>
          {bannerState === "fresh" ? (
            <div
              style={{
                display: "grid",
                gridTemplateColumns: "1fr auto",
                gap: 24,
                alignItems: "center",
              }}
            >
              <div>
                <Eyebrow>Ready to start</Eyebrow>
                <h2
                  style={{
                    fontFamily: "var(--font-display)",
                    fontSize: 26,
                    fontWeight: 500,
                    margin: "6px 0 10px",
                    letterSpacing: "-0.02em",
                    color: "var(--ink)",
                  }}
                >
                  This runs on your computer using the {referenceCode} reference.
                </h2>
                <p
                  style={{
                    fontSize: 14.5,
                    lineHeight: 1.6,
                    margin: 0,
                    color: "var(--muted)",
                  }}
                >
                  Expect around 6–8 hours for a whole genome on a modern laptop.
                  Pause any time — progress is saved continuously.
                </p>
                <div style={{ display: "flex", gap: 10, marginTop: 18 }}>
                  <Btn
                    onClick={() => void runAction(() => api.runAlignment(workspace.id))}
                    disabled={!canStart || submitting}
                    data-testid="alignment-run-button"
                  >
                    {submitting ? "Starting…" : "Start alignment"}
                  </Btn>
                </div>
              </div>
              <Helix size={180} rungs={16} hue={tweaks.accentHue} speed={32} />
            </div>
          ) : (
            <>
              <div
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                  marginBottom: 12,
                  gap: 12,
                }}
              >
                <div>
                  <MonoLabel>Blended progress</MonoLabel>
                  <div
                    style={{
                      fontFamily: "var(--font-display)",
                      fontSize: 34,
                      fontWeight: 400,
                      letterSpacing: "-0.02em",
                      marginTop: 4,
                      lineHeight: 1,
                      color: "var(--ink)",
                    }}
                  >
                    {Math.round((latestRun?.progress ?? 0) * 100)}%
                  </div>
                </div>
                <div style={{ textAlign: "right" }}>
                  {bannerState === "running" ? (
                    <>
                      <MonoLabel>ETA</MonoLabel>
                      <div
                        style={{
                          fontFamily: "var(--font-mono)",
                          fontSize: 18,
                          marginTop: 4,
                          color: "var(--ink-2)",
                        }}
                      >
                        {formatEta(latestRun?.etaSeconds) ?? "estimating…"}
                      </div>
                    </>
                  ) : bannerState === "paused" ? (
                    <>
                      <MonoLabel>Paused</MonoLabel>
                      <div
                        style={{
                          fontFamily: "var(--font-mono)",
                          fontSize: 14,
                          marginTop: 4,
                          color: "var(--ink-2)",
                        }}
                      >
                        saved to disk
                      </div>
                    </>
                  ) : (
                    <>
                      <MonoLabel>Finished in</MonoLabel>
                      <div
                        style={{
                          fontFamily: "var(--font-mono)",
                          fontSize: 18,
                          marginTop: 4,
                          color: "var(--ink-2)",
                        }}
                      >
                        {formatElapsedLabel(latestRun) ?? "—"}
                      </div>
                    </>
                  )}
                </div>
              </div>

              <div className="cs-progress" style={{ height: 10, marginBottom: 14 }}>
                <div
                  className="cs-progress-fill"
                  style={{
                    width: `${Math.max(2, Math.round((latestRun?.progress ?? 0) * 100))}%`,
                  }}
                />
              </div>

              {latestRun ? <PhaseSubBars run={latestRun} /> : null}

              <div style={{ display: "flex", gap: 10, marginTop: 20, flexWrap: "wrap" }}>
                {bannerState === "running" && runId ? (
                  <>
                    <Btn
                      variant="ghost"
                      disabled={submitting}
                      onClick={() =>
                        void runAction(() => api.pauseAlignment(workspace.id, runId))
                      }
                      data-testid="alignment-pause-button"
                    >
                      ⏸ Pause &amp; keep progress
                    </Btn>
                    <Btn
                      variant="ghost"
                      disabled={submitting}
                      onClick={() =>
                        void runAction(() => api.cancelAlignment(workspace.id, runId))
                      }
                      style={{ color: "var(--danger)" }}
                      data-testid="alignment-cancel-button"
                    >
                      Cancel &amp; discard
                    </Btn>
                  </>
                ) : null}
                {bannerState === "paused" && runId ? (
                  <>
                    <Btn
                      disabled={submitting}
                      onClick={() =>
                        void runAction(() => api.resumeAlignment(workspace.id, runId))
                      }
                      data-testid="alignment-resume-button"
                    >
                      Resume alignment
                    </Btn>
                    <Btn
                      variant="ghost"
                      disabled={submitting}
                      onClick={() =>
                        void runAction(() => api.cancelAlignment(workspace.id, runId))
                      }
                      style={{ color: "var(--danger)" }}
                    >
                      Discard &amp; restart
                    </Btn>
                  </>
                ) : null}
                {bannerState === "complete" ? (
                  <>
                    <Link
                      href={`/workspaces/${workspace.id}/variant-calling`}
                      className="cs-btn cs-btn-primary"
                    >
                      Find mutations →
                    </Link>
                    <Btn
                      variant="ghost"
                      disabled={submitting}
                      onClick={() => void runAction(() => api.runAlignment(workspace.id))}
                    >
                      Re-run alignment
                    </Btn>
                  </>
                ) : null}
                {bannerState === "failed" ? (
                  <Btn
                    disabled={submitting}
                    onClick={() => void runAction(() => api.runAlignment(workspace.id))}
                  >
                    Try again
                  </Btn>
                ) : null}
              </div>
            </>
          )}
        </div>
      </Card>

      {bannerState !== "fresh" ? (
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "1.5fr 1fr",
            gap: 20,
            marginTop: 20,
          }}
        >
          <Card>
            <CardHead
              eyebrow="Chunk grid"
              title="Tumor lane"
              subtitle="Each chunk is about 20M read pairs, persisted atomically."
            />
            <div style={{ padding: "16px 22px" }}>
              <ChunkGrid lane="tumor" run={latestRun} hue={tweaks.accentHue} />
              <div
                style={{
                  marginTop: 18,
                  borderTop: "1px solid var(--line)",
                  paddingTop: 14,
                }}
              >
                <MonoLabel>Normal lane</MonoLabel>
                <div style={{ marginTop: 8 }}>
                  <ChunkGrid
                    lane="normal"
                    run={latestRun}
                    hue={tweaks.accentHue}
                    small
                  />
                </div>
              </div>
            </div>
          </Card>

          <Card>
            <CardHead
              eyebrow="QC verdict"
              title={
                summary.qcVerdict === "pass"
                  ? "Pass"
                  : summary.qcVerdict === "warn"
                    ? "Warn"
                    : summary.qcVerdict === "fail"
                      ? "Fail"
                      : "—"
              }
              subtitle={
                summary.qcVerdict === "pass"
                  ? "Both lanes cleared mapping and depth thresholds."
                  : summary.qcVerdict === "warn"
                    ? "Finished but flagged — review before the next step."
                    : bannerState === "complete"
                      ? "QC thresholds not met."
                      : "QC runs after stats complete."
              }
            />
            <div style={{ padding: "16px 22px" }}>
              {bannerState === "complete" ? (
                <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                  <QcRow
                    label="Tumor mapped"
                    value={
                      summary.laneMetrics.tumor?.mappedPercent != null
                        ? `${summary.laneMetrics.tumor.mappedPercent.toFixed(1)}%`
                        : "—"
                    }
                    good={summary.qcVerdict === "pass"}
                  />
                  <QcRow
                    label="Normal mapped"
                    value={
                      summary.laneMetrics.normal?.mappedPercent != null
                        ? `${summary.laneMetrics.normal.mappedPercent.toFixed(1)}%`
                        : "—"
                    }
                    good={summary.qcVerdict === "pass"}
                  />
                  <QcRow
                    label="Tumor duplicates"
                    value={
                      summary.laneMetrics.tumor?.duplicatePercent != null
                        ? `${summary.laneMetrics.tumor.duplicatePercent.toFixed(1)}%`
                        : "—"
                    }
                    good={summary.qcVerdict === "pass"}
                  />
                  <QcRow
                    label="Insert size (tumor)"
                    value={
                      summary.laneMetrics.tumor?.meanInsertSize != null
                        ? `${Math.round(summary.laneMetrics.tumor.meanInsertSize)} bp`
                        : "—"
                    }
                    good={summary.qcVerdict === "pass"}
                  />
                </div>
              ) : (
                <div
                  style={{
                    display: "flex",
                    flexDirection: "column",
                    alignItems: "center",
                    gap: 12,
                    padding: "24px 0",
                    color: "var(--muted)",
                  }}
                >
                  <Spinner />
                  <span className="cs-tiny">Waiting for alignment to finish…</span>
                </div>
              )}
            </div>
          </Card>
        </div>
      ) : null}

      {tweaks.expertMode && latestRun?.recentLogTail.length ? (
        <Card style={{ marginTop: 20 }}>
          <CardHead
            eyebrow="Expert · command tail"
            title="Recent alignment output"
          />
          <pre
            style={{
              margin: 0,
              padding: "16px 22px",
              fontFamily: "var(--font-mono)",
              fontSize: 11.5,
              lineHeight: 1.7,
              color: "var(--muted)",
              background: "var(--surface-sunk)",
              borderBottomLeftRadius: "var(--radius-cs-lg)",
              borderBottomRightRadius: "var(--radius-cs-lg)",
              overflow: "auto",
              maxHeight: 280,
            }}
          >
            {latestRun.recentLogTail.join("\n")}
          </pre>
        </Card>
      ) : null}
    </>
  );
}

function PhaseSubBars({ run }: { run: AlignmentRun }) {
  const phases = [
    { id: "prep", label: "Prepare reference", pct: run.progressComponents.referencePrep },
    { id: "align", label: "Align chunks", pct: run.progressComponents.aligning },
    { id: "final", label: "Finalize BAM", pct: run.progressComponents.finalizing },
    { id: "stats", label: "QC stats", pct: run.progressComponents.stats },
  ];
  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "repeat(4, 1fr)",
        gap: 12,
      }}
    >
      {phases.map((p) => (
        <div
          key={p.id}
          style={{ display: "flex", flexDirection: "column", gap: 6 }}
        >
          <div
            style={{
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
            }}
          >
            <span style={{ fontSize: 13.5, color: "var(--ink-2)" }}>{p.label}</span>
            <span
              style={{
                fontFamily: "var(--font-mono)",
                fontSize: 12.5,
                color: "var(--muted)",
                fontWeight: 500,
              }}
            >
              {Math.round(p.pct * 100)}%
            </span>
          </div>
          <div className="cs-progress-sub">
            <div
              className="cs-progress-sub-fill"
              style={{ width: `${Math.round(p.pct * 100)}%` }}
            />
          </div>
        </div>
      ))}
    </div>
  );
}

function ChunkGrid({
  lane,
  run,
  hue,
  small,
}: {
  lane: SampleLane;
  run: AlignmentRun | null | undefined;
  hue: number;
  small?: boolean;
}) {
  const progress = run?.chunkProgress?.[lane] ?? null;
  const expected = run?.expectedTotalPerLane?.[lane] ?? 0;
  const total = progress?.totalChunks ?? expected ?? 0;
  const done = progress?.completedChunks ?? 0;
  const active = progress?.activeChunks ?? 0;

  if (total === 0) {
    return (
      <div
        className="cs-tiny"
        style={{
          padding: "12px 0",
          textAlign: "center",
          color: "var(--muted-2)",
        }}
      >
        Chunks will appear once the run starts.
      </div>
    );
  }

  const size = small ? 12 : 16;
  const cols = small ? 18 : 26;
  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: `repeat(${cols}, 1fr)`,
        gap: 3,
      }}
    >
      {Array.from({ length: total }, (_, i) => {
        const state =
          i < done ? "done" : i < done + active ? "running" : "pending";
        const bg =
          state === "done"
            ? `color-mix(in oklch, oklch(0.7 0.14 ${hue}) 85%, transparent)`
            : state === "running"
              ? `color-mix(in oklch, oklch(0.8 0.14 55) 80%, transparent)`
              : "color-mix(in oklch, var(--ink) 8%, transparent)";
        return (
          <div
            key={i}
            style={{
              height: size,
              borderRadius: 3,
              background: bg,
              animation:
                state === "running"
                  ? "cs-chunk-pulse 1.4s ease-in-out infinite"
                  : "none",
            }}
            title={`chunk ${i + 1} · ${state}`}
          />
        );
      })}
    </div>
  );
}

function QcRow({
  label,
  value,
  good,
}: {
  label: string;
  value: string;
  good: boolean;
}) {
  return (
    <div
      style={{
        display: "flex",
        justifyContent: "space-between",
        alignItems: "center",
        padding: "8px 0",
        borderBottom: "1px solid var(--line)",
      }}
    >
      <span style={{ fontSize: 13, color: "var(--ink-2)" }}>{label}</span>
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <span
          style={{
            fontFamily: "var(--font-mono)",
            fontSize: 13,
            fontWeight: 500,
            color: "var(--ink-2)",
          }}
        >
          {value}
        </span>
        <Dot style={{ color: good ? "var(--accent)" : "var(--warm)" }} />
      </div>
    </div>
  );
}
