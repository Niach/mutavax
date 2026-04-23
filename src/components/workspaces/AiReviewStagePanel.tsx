"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { Btn, Card, Chip, Eyebrow, MonoLabel } from "@/components/ui-kit";
import {
  REVIEW_CATEGORIES,
  REVIEW_CONTEXT_SOURCES,
  REVIEW_GRADES,
  REVIEW_HUE,
  REVIEW_SEVERITY,
  REVIEW_VERDICTS,
  type ReviewContextSource,
} from "@/components/workspaces/ai-review/constants";
import { api } from "@/lib/api";
import type {
  AiReviewBriefPeptide,
  AiReviewCaseBrief,
  AiReviewCategory,
  AiReviewFinding,
  AiReviewResult,
  AiReviewStageSummary,
  AiReviewVerdict,
  Workspace,
} from "@/lib/types";

type Phase = "idle" | "gathering" | "reviewing" | "done";

const HUE = REVIEW_HUE;

interface AiReviewStagePanelProps {
  workspace: Workspace;
  initialSummary: AiReviewStageSummary;
  onSummaryChange?: (summary: AiReviewStageSummary) => void;
}

export default function AiReviewStagePanel({
  workspace,
  initialSummary,
  onSummaryChange,
}: AiReviewStagePanelProps) {
  const [summary, setSummary] = useState(initialSummary);
  const [phase, setPhase] = useState<Phase>(
    summary.result ? "done" : "idle"
  );
  const [progress, setProgress] = useState(0);
  const [error, setError] = useState<string | null>(summary.lastError ?? null);
  const progressTimer = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    return () => {
      if (progressTimer.current) clearInterval(progressTimer.current);
    };
  }, []);

  const push = useCallback(
    (next: AiReviewStageSummary) => {
      setSummary(next);
      onSummaryChange?.(next);
    },
    [onSummaryChange]
  );

  const runReview = useCallback(async () => {
    setError(null);
    setPhase("gathering");
    setProgress(0);
    // fake progress — advances through context sources every ~500ms while
    // the backend POST is in flight, caps one step shy of the total so the
    // UI doesn't look "done" before the response lands.
    let current = 0;
    if (progressTimer.current) clearInterval(progressTimer.current);
    progressTimer.current = setInterval(() => {
      current += 1;
      if (current >= REVIEW_CONTEXT_SOURCES.length) {
        setProgress(REVIEW_CONTEXT_SOURCES.length - 1);
        setPhase("reviewing");
      } else {
        setProgress(current);
      }
    }, 500);

    try {
      const next = await api.runAiReview(workspace.id);
      if (progressTimer.current) clearInterval(progressTimer.current);
      setProgress(REVIEW_CONTEXT_SOURCES.length);
      push(next);
      setPhase("done");
    } catch (err) {
      if (progressTimer.current) clearInterval(progressTimer.current);
      setError(err instanceof Error ? err.message : String(err));
      setPhase("idle");
    }
  }, [workspace.id, push]);

  const reset = useCallback(async () => {
    try {
      const next = await api.resetAiReview(workspace.id);
      push(next);
      setPhase("idle");
      setProgress(0);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, [workspace.id, push]);

  const accept = useCallback(async () => {
    try {
      const next = await api.acceptAiReview(workspace.id);
      push(next);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, [workspace.id, push]);

  const override = useCallback(
    async (reason: string) => {
      try {
        const next = await api.overrideAiReview(workspace.id, reason);
        push(next);
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      }
    },
    [workspace.id, push]
  );

  const brief = summary.brief;
  const result = summary.result;
  const decision = summary.decision;

  return (
    <div className="cs-view cs-fade-in">
      <div className="cs-view-head">
        <div>
          <div className="cs-crumb">Workspace / 09 Reviewer sign-off</div>
          <h1>A second set of eyes.</h1>
        </div>
        <div style={{ textAlign: "right" }}>
          <Chip kind="live">Stage 09</Chip>
        </div>
      </div>

      {summary.status === "blocked" && (
        <BlockedNotice reason={summary.blockingReason ?? "Upstream stages required."} />
      )}

      {summary.status === "scaffolded" && (
        <BlockedNotice
          reason={summary.blockingReason ?? "Provider key not configured."}
          tone="scaffolded"
        />
      )}

      {summary.status !== "blocked" && summary.status !== "scaffolded" && (
        <>
          {phase === "idle" && (
            <IdleView brief={brief ?? null} error={error} onStart={runReview} />
          )}
          {(phase === "gathering" || phase === "reviewing") && (
            <GatheringView
              progress={progress}
              total={REVIEW_CONTEXT_SOURCES.length}
              sources={REVIEW_CONTEXT_SOURCES}
              phase={phase}
            />
          )}
          {phase === "done" && result && (
            <ReviewReport
              workspaceId={workspace.id}
              result={result}
              decision={decision ?? null}
              error={error}
              onAccept={accept}
              onOverride={override}
              onReset={reset}
            />
          )}
        </>
      )}
    </div>
  );
}

function BlockedNotice({
  reason,
  tone = "blocked",
}: {
  reason: string;
  tone?: "blocked" | "scaffolded";
}) {
  return (
    <Card style={{ marginTop: 8 }}>
      <div style={{ padding: "22px 28px" }}>
        <MonoLabel>{tone === "scaffolded" ? "Setup required" : "Not yet available"}</MonoLabel>
        <p
          style={{
            marginTop: 10,
            marginBottom: 0,
            fontSize: 14,
            lineHeight: 1.55,
            color: "var(--ink-2)",
          }}
        >
          {reason}
        </p>
      </div>
    </Card>
  );
}

// ── IDLE ──────────────────────────────────────────────────────────────────

function IdleView({
  brief,
  error,
  onStart,
}: {
  brief: AiReviewCaseBrief | null;
  error: string | null;
  onStart: () => void;
}) {
  return (
    <Card>
      <div
        style={{
          padding: "28px 32px",
          display: "grid",
          gridTemplateColumns: brief ? "1fr 1fr" : "1fr",
          gap: 32,
          alignItems: "center",
        }}
      >
        <div>
          <Eyebrow>Before release</Eyebrow>
          <h2
            style={{
              fontFamily: "var(--font-display)",
              fontWeight: 400,
              fontSize: 26,
              letterSpacing: "-0.022em",
              margin: "8px 0 10px",
              lineHeight: 1.15,
            }}
          >
            Hand the case to a second reviewer.
          </h2>
          <p
            style={{
              fontSize: 14,
              lineHeight: 1.55,
              color: "var(--muted)",
              margin: "0 0 18px",
              maxWidth: "38ch",
            }}
          >
            Claude Opus 4.7 reviews validity, safety, coverage, and
            manufacturability, then signs a letter.
          </p>
          {error && (
            <div
              style={{
                marginBottom: 14,
                padding: "10px 14px",
                borderRadius: 10,
                border: "1px solid color-mix(in oklch, var(--danger) 30%, transparent)",
                background: "color-mix(in oklch, var(--danger) 8%, transparent)",
                fontSize: 13,
                color: "var(--danger)",
                lineHeight: 1.5,
              }}
            >
              {error}
            </div>
          )}
          <Btn onClick={onStart}>Begin review →</Btn>
        </div>
        {brief && <CaseAtGlance brief={brief} />}
      </div>
    </Card>
  );
}

function CaseAtGlance({ brief }: { brief: AiReviewCaseBrief }) {
  const peptides = brief.shortlist;
  return (
    <div
      style={{
        position: "relative",
        borderRadius: "var(--radius-cs-lg)",
        padding: "22px 22px 26px",
        background: "var(--surface-sunk)",
        border: "1px solid var(--line)",
      }}
    >
      <div className="cs-mono-label" style={{ marginBottom: 12 }}>
        The case · {brief.patientName}
      </div>
      <div style={{ marginBottom: 18 }}>
        <PeptideStrand peptides={peptides} />
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(2, 1fr)", gap: 10 }}>
        <StatPill
          label="Variants · PASS"
          value={`${brief.variants.pass}`}
          sub={`of ${brief.variants.total}`}
        />
        <StatPill
          label="Peptides"
          value={peptides.length}
          sub={`${brief.coverage.uniqueGenes.length} unique genes`}
        />
        <StatPill
          label="MHC alleles"
          value={brief.coverage.alleles.length}
          sub={`${brief.coverage.classI} cls-I · ${brief.coverage.classII} cls-II`}
        />
        <StatPill
          label="Cassette"
          value={`${brief.construct.aaLen} aa`}
          sub={
            brief.construct.cai && brief.construct.gc
              ? `CAI ${brief.construct.cai.toFixed(2)} · GC ${brief.construct.gc.toFixed(0)}%`
              : `${brief.construct.ntLen} nt`
          }
        />
      </div>
    </div>
  );
}

function PeptideStrand({ peptides }: { peptides: AiReviewBriefPeptide[] }) {
  const n = Math.max(peptides.length, 1);
  const height = 48;
  return (
    <div style={{ position: "relative", padding: "6px 0" }}>
      <div
        style={{
          position: "absolute",
          left: 0,
          right: 0,
          top: "50%",
          height: 2,
          transform: "translateY(-1px)",
          background:
            "linear-gradient(90deg, transparent, color-mix(in oklch, var(--accent) 40%, transparent) 8%, color-mix(in oklch, var(--accent) 40%, transparent) 92%, transparent)",
        }}
      />
      <div
        style={{
          position: "relative",
          display: "grid",
          gridTemplateColumns: `repeat(${n}, 1fr)`,
          height,
        }}
      >
        {peptides.map((p, i) => {
          const isDriver = p.driver;
          const color = isDriver
            ? `oklch(0.62 0.14 ${HUE})`
            : `oklch(0.72 0.08 ${(HUE + 180) % 360})`;
          return (
            <div
              key={i}
              style={{
                position: "relative",
                display: "flex",
                justifyContent: "center",
                alignItems: "center",
              }}
            >
              <div
                style={{
                  width: 18,
                  height: 18,
                  borderRadius: 999,
                  background: `radial-gradient(circle at 30% 30%, color-mix(in oklch, ${color} 60%, white), ${color})`,
                  boxShadow: `0 0 0 3px var(--surface-sunk), 0 0 14px -2px ${color}`,
                  border: "1px solid color-mix(in oklch, currentColor 30%, transparent)",
                  color,
                }}
              />
              <div
                style={{
                  position: "absolute",
                  top: "100%",
                  marginTop: 4,
                  fontFamily: "var(--font-mono)",
                  fontSize: 9.5,
                  color: "var(--muted)",
                  letterSpacing: "0.04em",
                  whiteSpace: "nowrap",
                }}
              >
                {p.gene}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function StatPill({
  label,
  value,
  sub,
}: {
  label: string;
  value: string | number;
  sub?: string;
}) {
  return (
    <div
      style={{
        padding: "10px 12px",
        borderRadius: 10,
        background: "var(--surface-strong)",
        border: "1px solid var(--line)",
      }}
    >
      <div className="cs-mono-label" style={{ fontSize: 9.5 }}>
        {label}
      </div>
      <div
        style={{
          fontFamily: "var(--font-display)",
          fontSize: 22,
          fontWeight: 500,
          letterSpacing: "-0.01em",
          marginTop: 2,
          lineHeight: 1.1,
        }}
      >
        {value}
      </div>
      {sub && (
        <div
          style={{
            fontFamily: "var(--font-mono)",
            fontSize: 10.5,
            color: "var(--muted)",
            marginTop: 2,
          }}
        >
          {sub}
        </div>
      )}
    </div>
  );
}

// ── GATHERING ─────────────────────────────────────────────────────────────

function GatheringView({
  progress,
  total,
  sources,
  phase,
}: {
  progress: number;
  total: number;
  sources: ReviewContextSource[];
  phase: Phase;
}) {
  return (
    <Card>
      <div style={{ padding: "22px 28px 28px" }}>
        <div style={{ textAlign: "center", marginBottom: 20 }}>
          <div className="cs-mono-label" style={{ letterSpacing: "0.16em" }}>
            {phase === "gathering" ? "Assembling case brief" : "Claude · reviewing"}
          </div>
        </div>
        <StreamDiagram progress={progress} total={total} sources={sources} phase={phase} />
      </div>
    </Card>
  );
}

function StreamDiagram({
  progress,
  total,
  sources,
  phase,
}: {
  progress: number;
  total: number;
  sources: ReviewContextSource[];
  phase: Phase;
}) {
  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "1fr auto 160px",
        gap: 24,
        alignItems: "center",
        maxWidth: 760,
        margin: "0 auto",
      }}
    >
      <div style={{ display: "grid", gap: 6 }}>
        {sources.map((s, i) => {
          const done = i < progress;
          const active = i === progress - 1;
          return (
            <div
              key={s.step}
              style={{
                display: "grid",
                gridTemplateColumns: "28px 1fr auto",
                gap: 10,
                alignItems: "center",
                padding: "8px 12px",
                borderRadius: 10,
                background: done
                  ? "color-mix(in oklch, var(--accent) 8%, var(--surface-strong))"
                  : "var(--surface-sunk)",
                border:
                  "1px solid " +
                  (done
                    ? "color-mix(in oklch, var(--accent) 26%, var(--line))"
                    : "var(--line)"),
                opacity: done ? 1 : 0.5,
                transform: active ? "translateX(4px)" : "none",
                transition: "all 0.25s ease",
              }}
            >
              <span
                style={{
                  fontFamily: "var(--font-mono)",
                  fontSize: 10,
                  color: "var(--muted-2)",
                  letterSpacing: "0.1em",
                }}
              >
                {s.stage}
              </span>
              <div>
                <div style={{ fontSize: 13.5, color: "var(--ink-2)", fontWeight: 500 }}>
                  {s.label}
                </div>
                <div
                  style={{
                    fontSize: 11,
                    color: "var(--muted)",
                    fontFamily: "var(--font-mono)",
                  }}
                >
                  {s.detail}
                </div>
              </div>
              <span
                style={{
                  width: 14,
                  height: 14,
                  borderRadius: 999,
                  background: done ? "var(--accent)" : "transparent",
                  border:
                    "1.5px solid " + (done ? "var(--accent)" : "var(--line-strong)"),
                  display: "inline-flex",
                  alignItems: "center",
                  justifyContent: "center",
                  color: "white",
                  fontSize: 9,
                  fontWeight: 700,
                }}
              >
                {done ? "✓" : ""}
              </span>
            </div>
          );
        })}
      </div>

      <div style={{ position: "relative", width: 80, height: 300 }}>
        <StreamLines active={phase === "gathering" ? progress / total : 1} />
      </div>

      <div
        style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 10 }}
      >
        <ClaudeMark thinking={phase === "reviewing"} />
        <div style={{ textAlign: "center" }}>
          <div
            style={{
              fontFamily: "var(--font-display)",
              fontSize: 16,
              fontWeight: 500,
              letterSpacing: "-0.01em",
            }}
          >
            Claude Opus 4.7
          </div>
          <div
            style={{
              fontFamily: "var(--font-mono)",
              fontSize: 10,
              color: "var(--muted)",
              letterSpacing: "0.1em",
              marginTop: 2,
            }}
          >
            {phase === "gathering" ? "LISTENING" : phase === "reviewing" ? "READING…" : "READY"}
          </div>
        </div>
      </div>
    </div>
  );
}

function StreamLines({ active }: { active: number }) {
  const lines = [];
  for (let i = 0; i < 8; i += 1) {
    const y1 = 18 + i * (264 / 7);
    const y2 = 150;
    const x1 = 0;
    const x2 = 80;
    const cx1 = 50;
    const cx2 = 20;
    const d = `M ${x1},${y1} C ${cx1},${y1} ${cx2},${y2} ${x2},${y2}`;
    const lit = i < Math.round(active * 8);
    lines.push({ d, lit, key: i });
  }
  return (
    <svg width="80" height="300" viewBox="0 0 80 300" style={{ overflow: "visible" }}>
      <defs>
        <linearGradient id="rvg" x1="0" x2="1" y1="0" y2="0">
          <stop offset="0%" stopColor={`oklch(0.72 0.14 ${HUE})`} stopOpacity="0" />
          <stop offset="40%" stopColor={`oklch(0.72 0.14 ${HUE})`} stopOpacity="0.9" />
          <stop offset="100%" stopColor={`oklch(0.58 0.14 ${HUE})`} stopOpacity="1" />
        </linearGradient>
      </defs>
      {lines.map((l) => (
        <path
          key={l.key}
          d={l.d}
          fill="none"
          stroke={l.lit ? "url(#rvg)" : "color-mix(in oklch, currentColor 15%, transparent)"}
          strokeWidth={l.lit ? 1.6 : 1}
          strokeLinecap="round"
          style={{
            color: "var(--muted)",
            opacity: l.lit ? 1 : 0.3,
            transition: "all 0.4s ease",
            strokeDasharray: l.lit ? "none" : "3 4",
          }}
        />
      ))}
    </svg>
  );
}

function ClaudeMark({ thinking }: { thinking: boolean }) {
  return (
    <div
      style={{
        position: "relative",
        width: 96,
        height: 96,
        borderRadius: 999,
        background:
          "radial-gradient(circle at 30% 30%, color-mix(in oklch, var(--accent) 80%, white), var(--accent))",
        boxShadow:
          "0 0 0 6px color-mix(in oklch, var(--accent) 10%, transparent), 0 20px 40px -15px color-mix(in oklch, var(--accent) 60%, transparent)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        overflow: "hidden",
      }}
    >
      <div
        style={{
          position: "absolute",
          inset: 10,
          borderRadius: 999,
          border: "1px solid rgba(255,255,255,0.35)",
          animation: thinking ? "cmark-pulse 1.6s ease-in-out infinite" : "none",
        }}
      />
      <svg width="40" height="40" viewBox="0 0 40 40">
        <path
          d="M20 2 L23 17 L38 20 L23 23 L20 38 L17 23 L2 20 L17 17 Z"
          fill="white"
          opacity="0.96"
        />
      </svg>
      <style>{`
        @keyframes cmark-pulse {
          0%, 100% { transform: scale(1); opacity: 0.5; }
          50% { transform: scale(1.15); opacity: 0.9; }
        }
      `}</style>
    </div>
  );
}

// ── DONE ──────────────────────────────────────────────────────────────────

function ReviewReport({
  workspaceId,
  result,
  decision,
  error,
  onAccept,
  onOverride,
  onReset,
}: {
  workspaceId: string;
  result: AiReviewResult;
  decision: { kind: "accept" | "override"; at: string; reason?: string | null } | null;
  error: string | null;
  onAccept: () => void;
  onOverride: (reason: string) => void;
  onReset: () => void;
}) {
  const V = REVIEW_VERDICTS[result.verdict];
  return (
    <div className="cs-review-grid">
      <div>
        {error && (
          <div
            style={{
              marginBottom: 14,
              padding: "8px 14px",
              borderRadius: 10,
              background: "var(--surface-sunk)",
              border: "1px solid var(--line)",
              fontSize: 11.5,
              color: "var(--muted)",
              fontFamily: "var(--font-mono)",
              letterSpacing: "0.04em",
            }}
          >
            {error}
          </div>
        )}

        <Card style={{ marginBottom: 16 }}>
          <div
            style={{
              padding: "14px 24px",
              borderBottom: "1px solid var(--line)",
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
            }}
          >
            <span className="cs-mono-label" style={{ fontSize: 10.5 }}>
              Reviewer&apos;s letter
            </span>
            <span
              style={{
                fontFamily: "var(--font-mono)",
                fontSize: 10,
                color: "var(--muted-2)",
                letterSpacing: "0.1em",
              }}
            >
              {result.model}
            </span>
          </div>

          <div
            style={{
              padding: "22px clamp(20px, 3vw, 32px) 24px",
              display: "grid",
              gridTemplateColumns: "auto 1fr",
              gap: 26,
              alignItems: "flex-start",
            }}
          >
            <VerdictArc verdict={result.verdict} value={result.confidence} />
            <div style={{ minWidth: 0 }}>
              <div
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  gap: 8,
                  padding: "4px 10px",
                  borderRadius: 999,
                  background: V.bg,
                  color: V.color,
                  fontFamily: "var(--font-mono)",
                  fontSize: 10,
                  fontWeight: 700,
                  letterSpacing: "0.14em",
                  textTransform: "uppercase",
                }}
              >
                <span
                  style={{
                    width: 6,
                    height: 6,
                    borderRadius: 999,
                    background: V.color,
                  }}
                />
                {V.label}
              </div>
              <h2
                style={{
                  fontFamily: "var(--font-display)",
                  fontWeight: 400,
                  fontSize: 22,
                  lineHeight: 1.2,
                  letterSpacing: "-0.02em",
                  margin: "8px 0 10px",
                  color: "var(--ink)",
                  textWrap: "pretty",
                }}
              >
                {result.headline}
              </h2>
              <div
                style={{
                  fontSize: 13.5,
                  lineHeight: 1.55,
                  color: "var(--ink-2)",
                  whiteSpace: "pre-wrap",
                  textWrap: "pretty",
                }}
              >
                {result.letter}
              </div>
              <div
                style={{
                  marginTop: 14,
                  paddingTop: 12,
                  borderTop: "1px dashed var(--line-strong)",
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                  gap: 12,
                }}
              >
                <div
                  style={{
                    fontFamily: "var(--font-display)",
                    fontStyle: "italic",
                    fontSize: 13.5,
                    color: "var(--ink-2)",
                  }}
                >
                  — Claude Opus 4.7
                </div>
              </div>
            </div>
          </div>
        </Card>

        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(2, minmax(0, 1fr))",
            gap: 14,
            marginBottom: 16,
          }}
        >
          {result.categories.map((c) => (
            <CategoryCard key={c.id} category={c} />
          ))}
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14 }}>
          <Card>
            <div style={{ padding: "14px 18px 4px" }}>
              <MonoLabel>Top risks</MonoLabel>
            </div>
            <div style={{ padding: "4px 18px 16px" }}>
              {result.topRisks.map((r, i) => (
                <div
                  key={i}
                  style={{
                    padding: "8px 0",
                    borderBottom:
                      i < result.topRisks.length - 1 ? "1px solid var(--line)" : "none",
                    fontSize: 13.5,
                    color: "var(--ink-2)",
                    display: "flex",
                    gap: 10,
                    lineHeight: 1.45,
                  }}
                >
                  <span
                    style={{
                      fontFamily: "var(--font-mono)",
                      color: "var(--muted-2)",
                      fontSize: 11,
                      width: 18,
                      flexShrink: 0,
                    }}
                  >
                    {String(i + 1).padStart(2, "0")}
                  </span>
                  <span>{r}</span>
                </div>
              ))}
            </div>
          </Card>
          <Card>
            <div style={{ padding: "14px 18px 4px" }}>
              <MonoLabel>Next actions</MonoLabel>
            </div>
            <div style={{ padding: "4px 18px 16px" }}>
              {result.nextActions.map((a, i) => (
                <div
                  key={i}
                  style={{
                    padding: "8px 0",
                    borderBottom:
                      i < result.nextActions.length - 1
                        ? "1px solid var(--line)"
                        : "none",
                    fontSize: 13.5,
                    color: "var(--ink-2)",
                    display: "flex",
                    gap: 10,
                    lineHeight: 1.45,
                  }}
                >
                  <span
                    style={{
                      color: "var(--accent-ink)",
                      fontSize: 13,
                      width: 18,
                      flexShrink: 0,
                    }}
                  >
                    →
                  </span>
                  <span>{a}</span>
                </div>
              ))}
            </div>
          </Card>
        </div>
      </div>

      <DecisionRail
        workspaceId={workspaceId}
        result={result}
        decision={decision}
        onAccept={onAccept}
        onOverride={onOverride}
        onReset={onReset}
      />
    </div>
  );
}

function VerdictArc({ verdict, value }: { verdict: AiReviewVerdict; value: number }) {
  const size = 110;
  const r = 48;
  const c = Math.PI * r;
  const pct = Math.max(0, Math.min(1, value / 100));
  const stroke =
    verdict === "approve" || verdict === "approve_with_notes"
      ? `oklch(0.58 0.14 ${HUE})`
      : verdict === "hold"
        ? "var(--warm)"
        : "var(--danger)";

  return (
    <div style={{ width: size, height: size, position: "relative", flexShrink: 0 }}>
      <svg
        width={size}
        height={size}
        viewBox={`0 0 ${size} ${size}`}
        style={{ transform: "rotate(-90deg)" }}
      >
        <circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          fill="none"
          stroke="color-mix(in oklch, var(--ink) 6%, transparent)"
          strokeWidth={8}
        />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          fill="none"
          stroke={stroke}
          strokeWidth={8}
          strokeLinecap="round"
          strokeDasharray={`${c}`}
          strokeDashoffset={`${c * (1 - pct)}`}
          style={{ transition: "stroke-dashoffset 1s cubic-bezier(0.22, 1, 0.36, 1)" }}
        />
      </svg>
      <div
        style={{
          position: "absolute",
          inset: 0,
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
          gap: 2,
          textAlign: "center",
        }}
      >
        <div
          style={{
            fontFamily: "var(--font-display)",
            fontSize: 26,
            fontWeight: 500,
            letterSpacing: "-0.02em",
            color: "var(--ink)",
            lineHeight: 1,
          }}
        >
          {value}%
        </div>
        <div
          style={{
            fontFamily: "var(--font-mono)",
            fontSize: 9,
            color: "var(--muted)",
            letterSpacing: "0.14em",
            textTransform: "uppercase",
          }}
        >
          confidence
        </div>
      </div>
    </div>
  );
}

function CategoryCard({ category: c }: { category: AiReviewCategory }) {
  const meta = REVIEW_CATEGORIES[c.id] ?? { label: c.id, blurb: "" };
  const grade = REVIEW_GRADES[c.grade];
  return (
    <div
      style={{
        padding: "18px 20px",
        borderRadius: "var(--radius-cs-lg)",
        background: "var(--surface-strong)",
        border: "1px solid var(--line)",
        display: "flex",
        flexDirection: "column",
        gap: 14,
      }}
    >
      <div className="cs-spread" style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 12 }}>
        <div>
          <MonoLabel>{meta.label}</MonoLabel>
          <div
            style={{
              fontSize: 13.5,
              color: "var(--ink-2)",
              marginTop: 6,
              lineHeight: 1.45,
              textWrap: "pretty",
            }}
          >
            {c.summary}
          </div>
        </div>
        <span
          style={{
            fontFamily: "var(--font-display)",
            fontWeight: 500,
            fontSize: 22,
            width: 42,
            height: 42,
            borderRadius: 10,
            background: grade.bg,
            color: grade.color,
            display: "inline-flex",
            alignItems: "center",
            justifyContent: "center",
            flexShrink: 0,
          }}
        >
          {c.grade}
        </span>
      </div>

      <div style={{ display: "grid", gap: 4 }}>
        {c.findings.slice(0, 3).map((f, i) => (
          <FindingLine key={i} finding={f} />
        ))}
      </div>
    </div>
  );
}

function FindingLine({ finding: f }: { finding: AiReviewFinding }) {
  const sev = REVIEW_SEVERITY[f.severity] ?? REVIEW_SEVERITY.info;
  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "auto 1fr",
        gap: 8,
        alignItems: "flex-start",
        padding: "5px 0",
      }}
    >
      <span
        style={{
          padding: "2px 7px",
          height: 17,
          borderRadius: 5,
          background: sev.bg,
          color: sev.fg,
          fontFamily: "var(--font-mono)",
          fontSize: 9,
          fontWeight: 700,
          letterSpacing: "0.12em",
          textTransform: "uppercase",
          display: "inline-flex",
          alignItems: "center",
        }}
      >
        {sev.label}
      </span>
      <div>
        <div
          style={{
            fontSize: 12.5,
            fontWeight: 500,
            color: "var(--ink)",
            lineHeight: 1.4,
          }}
        >
          {f.title}
        </div>
        <div
          style={{
            fontSize: 12,
            color: "var(--muted)",
            marginTop: 1,
            lineHeight: 1.45,
            textWrap: "pretty",
          }}
        >
          {f.detail}
        </div>
      </div>
    </div>
  );
}

// ── Decision rail ─────────────────────────────────────────────────────────

function DecisionRail({
  workspaceId,
  result,
  decision,
  onAccept,
  onOverride,
  onReset,
}: {
  workspaceId: string;
  result: AiReviewResult;
  decision: { kind: "accept" | "override"; at: string; reason?: string | null } | null;
  onAccept: () => void;
  onOverride: (reason: string) => void;
  onReset: () => void;
}) {
  const router = useRouter();
  const [mode, setMode] = useState<"idle" | "overriding">("idle");
  const [reason, setReason] = useState("");

  const totalFindings = useMemo(
    () => result.categories.reduce((a, c) => a + c.findings.length, 0),
    [result]
  );

  return (
    <div
      className="cs-review-rail"
      style={{ position: "sticky", top: 20, alignSelf: "flex-start" }}
    >
      <Card>
        <div style={{ padding: "14px 18px", borderBottom: "1px solid var(--line)" }}>
          <MonoLabel>Your decision</MonoLabel>
        </div>
        <div style={{ padding: "14px 18px 18px" }}>
          {!decision && mode === "idle" && (
            <div style={{ display: "grid", gap: 8 }}>
              <Btn onClick={onAccept} size="sm" style={{ width: "100%" }}>
                Accept verdict
              </Btn>
              <Btn
                variant="ghost"
                size="sm"
                onClick={() => setMode("overriding")}
                style={{ width: "100%" }}
              >
                Override with reason
              </Btn>
              <div
                style={{
                  marginTop: 6,
                  fontSize: 12,
                  color: "var(--muted)",
                  lineHeight: 1.5,
                }}
              >
                Logged to the audit trail and attached to release.
              </div>
            </div>
          )}
          {!decision && mode === "overriding" && (
            <div>
              <MonoLabel>Reason</MonoLabel>
              <textarea
                value={reason}
                onChange={(e) => setReason(e.target.value)}
                placeholder="Why proceed despite the reviewer's concerns?"
                style={{
                  marginTop: 6,
                  width: "100%",
                  minHeight: 90,
                  resize: "vertical",
                  padding: "10px 12px",
                  borderRadius: 10,
                  border: "1px solid var(--line-strong)",
                  background: "var(--surface-sunk)",
                  fontFamily: "inherit",
                  fontSize: 13,
                  lineHeight: 1.5,
                  color: "var(--ink)",
                }}
              />
              <div style={{ marginTop: 10, display: "flex", gap: 8 }}>
                <Btn
                  size="sm"
                  onClick={() => {
                    const trimmed = reason.trim();
                    if (!trimmed) return;
                    onOverride(trimmed);
                    setMode("idle");
                  }}
                  style={{ flex: 1 }}
                  disabled={!reason.trim()}
                >
                  Log override
                </Btn>
                <Btn
                  size="sm"
                  variant="ghost"
                  onClick={() => {
                    setMode("idle");
                    setReason("");
                  }}
                >
                  Cancel
                </Btn>
              </div>
            </div>
          )}
          {decision && (
            <div>
              <div
                style={{
                  padding: "12px 14px",
                  borderRadius: 10,
                  background:
                    decision.kind === "accept"
                      ? "color-mix(in oklch, var(--accent) 10%, var(--surface-strong))"
                      : "color-mix(in oklch, var(--warm) 10%, var(--surface-strong))",
                  border:
                    "1px solid " +
                    (decision.kind === "accept"
                      ? "color-mix(in oklch, var(--accent) 28%, var(--line))"
                      : "color-mix(in oklch, var(--warm) 28%, var(--line))"),
                }}
              >
                <div
                  className="cs-mono-label"
                  style={{
                    color:
                      decision.kind === "accept" ? "var(--accent-ink)" : "var(--warm)",
                    fontSize: 10,
                  }}
                >
                  {decision.kind === "accept"
                    ? "Accepted · signed"
                    : "Overridden · signed"}
                </div>
                <div
                  style={{
                    marginTop: 6,
                    fontSize: 13,
                    color: "var(--ink-2)",
                    lineHeight: 1.5,
                  }}
                >
                  {decision.kind === "accept"
                    ? "Reviewer's verdict recorded. Release is cleared."
                    : `Override logged: "${decision.reason ?? ""}"`}
                </div>
                <div
                  style={{
                    marginTop: 6,
                    fontFamily: "var(--font-mono)",
                    fontSize: 10,
                    color: "var(--muted-2)",
                  }}
                >
                  {new Date(decision.at).toLocaleString("en-GB")}
                </div>
              </div>
              <Btn
                size="sm"
                variant="ghost"
                style={{ width: "100%", marginTop: 10 }}
                onClick={() =>
                  router.push(`/workspaces/${workspaceId}/construct-output`)
                }
              >
                Back to construct output →
              </Btn>
            </div>
          )}
        </div>
      </Card>

      <Card style={{ marginTop: 12 }}>
        <div style={{ padding: "14px 18px" }}>
          <MonoLabel>Reviewer</MonoLabel>
          <div
            style={{
              marginTop: 6,
              fontFamily: "var(--font-display)",
              fontSize: 16,
              fontWeight: 500,
              letterSpacing: "-0.01em",
            }}
          >
            Claude Opus 4.7
          </div>
          <div style={{ fontSize: 12, color: "var(--muted)", marginTop: 2 }}>
            Independent second-pass reviewer
          </div>
          <div
            style={{
              marginTop: 10,
              display: "grid",
              gridTemplateColumns: "1fr auto",
              gap: 4,
              fontFamily: "var(--font-mono)",
              fontSize: 11,
              color: "var(--muted)",
            }}
          >
            <span>Categories</span>
            <span style={{ color: "var(--ink-2)" }}>{result.categories.length}</span>
            <span>Total findings</span>
            <span style={{ color: "var(--ink-2)" }}>{totalFindings}</span>
            <span>Confidence</span>
            <span style={{ color: "var(--ink-2)" }}>{result.confidence}%</span>
          </div>
          <Btn
            size="sm"
            variant="ghost"
            style={{ width: "100%", marginTop: 12 }}
            onClick={onReset}
          >
            Re-run review
          </Btn>
        </div>
      </Card>
    </div>
  );
}
