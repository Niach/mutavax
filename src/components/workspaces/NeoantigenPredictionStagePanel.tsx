"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";

import AntigenFlow from "@/components/workspaces/neoantigen/AntigenFlow";
import BindingHeatmap from "@/components/workspaces/neoantigen/BindingHeatmap";
import BucketTiles from "@/components/workspaces/neoantigen/BucketTiles";
import CandidatesTable from "@/components/workspaces/neoantigen/CandidatesTable";
import DlaAllelePanel from "@/components/workspaces/neoantigen/DlaAllelePanel";
import ExpertDrawer from "@/components/workspaces/neoantigen/ExpertDrawer";
import RankingScatter from "@/components/workspaces/neoantigen/RankingScatter";
import Helix from "@/components/helix/Helix";
import {
  Btn,
  Callout,
  Card,
  Chip,
  Dot,
  Eyebrow,
  Tnum,
} from "@/components/ui-kit";
import { useTweaks } from "@/components/dev/TweaksProvider";
import {
  api,
  InsufficientMemoryError,
  MissingToolsError,
  StageNotActionableError,
} from "@/lib/api";
import type {
  NeoantigenStageSummary,
  PatientAllele,
  Workspace,
} from "@/lib/types";

interface NeoantigenPredictionStagePanelProps {
  workspace: Workspace;
  initialSummary: NeoantigenStageSummary;
  onSummaryChange?: (summary: NeoantigenStageSummary) => void;
}

const RUNTIME_PHASE_COPY: Record<string, string> = {
  generating_fasta: "Generating peptide fragments from the annotated mutations",
  running_class_i: "Scoring class I peptides against NetMHCpan 4.2",
  running_class_ii: "Scoring class II peptides against NetMHCIIpan 4.3",
  parsing: "Reading pVACseq output",
  finalizing: "Finalizing candidates",
};

export default function NeoantigenPredictionStagePanel({
  workspace,
  initialSummary,
  onSummaryChange,
}: NeoantigenPredictionStagePanelProps) {
  const { tweaks } = useTweaks();
  const [summary, setSummary] = useState(initialSummary);
  const [submitting, setSubmitting] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [missingTools, setMissingTools] = useState<{
    tools: string[];
    hints: string[];
  } | null>(null);

  const isFirstRender = useRef(true);
  useEffect(() => {
    if (isFirstRender.current) {
      isFirstRender.current = false;
      return;
    }
    setSummary(initialSummary);
    setActionError(null);
    setMissingTools(null);
  }, [initialSummary]);

  const pushSummary = useCallback(
    (next: NeoantigenStageSummary) => {
      setSummary(next);
      onSummaryChange?.(next);
    },
    [onSummaryChange],
  );

  useEffect(() => {
    if (summary.status !== "running" && summary.status !== "paused") return;
    const timer = window.setInterval(() => {
      void api
        .getNeoantigenStageSummary(workspace.id)
        .then((next) => pushSummary(next))
        .catch(() => {});
    }, 2000);
    return () => window.clearInterval(timer);
  }, [summary.status, workspace.id, pushSummary]);

  const latestRun = summary.latestRun;
  const metrics = latestRun?.metrics ?? null;
  const status = summary.status;

  const runAction = useCallback(
    async (action: () => Promise<NeoantigenStageSummary>) => {
      setSubmitting(true);
      setActionError(null);
      setMissingTools(null);
      try {
        const next = await action();
        pushSummary(next);
      } catch (err) {
        if (err instanceof MissingToolsError) {
          setMissingTools({ tools: err.tools, hints: err.hints });
        } else if (err instanceof InsufficientMemoryError) {
          setActionError(err.message);
        } else if (err instanceof StageNotActionableError) {
          setActionError(err.message);
        } else if (err instanceof Error) {
          setActionError(err.message);
        } else {
          setActionError("Unable to complete the action.");
        }
      } finally {
        setSubmitting(false);
      }
    },
    [pushSummary],
  );

  const saveAlleles = useCallback(
    async (next: PatientAllele[]) => {
      try {
        const updated = await api.updateNeoantigenAlleles(workspace.id, next);
        pushSummary(updated);
      } catch (err) {
        if (err instanceof Error) setActionError(err.message);
      }
    },
    [pushSummary, workspace.id],
  );

  const header = (
    <div className="cs-view-head">
      <div>
        <div className="cs-crumb">
          {workspace.displayName} / 05 Neoantigen prediction
        </div>
        <h1 style={{ textWrap: "pretty", margin: "4px 0 0" }}>
          Which mutant fragments can the patient&apos;s immune system see?
        </h1>
        <p
          style={{
            maxWidth: "64ch",
            marginTop: 12,
            fontSize: 16.5,
            lineHeight: 1.6,
            color: "var(--ink-2)",
          }}
        >
          Tumor cells chop mutated proteins into short peptides and display them on their
          surface. For the immune system to spot the tumor, those peptides need to{" "}
          <em>stick</em> to the patient&apos;s specific MHC molecules. We predict which
          ones will.
        </p>
      </div>
      <div style={{ textAlign: "right", minWidth: 200 }}>
        <Chip kind="live">Stage 05 · Live</Chip>
        <div
          style={{
            marginTop: 8,
            fontSize: 12.5,
            fontFamily: "var(--font-mono)",
            color: "var(--muted)",
            letterSpacing: "0.08em",
            whiteSpace: "nowrap",
          }}
        >
          pVACseq · NetMHCpan 4.2
        </div>
      </div>
    </div>
  );

  if (missingTools) {
    return (
      <>
        {header}
        <Callout tone="warm">
          <Dot style={{ color: "var(--warm)" }} />
          <div style={{ flex: 1 }}>
            <div style={{ fontSize: 15, fontWeight: 500, color: "var(--ink)" }}>
              Install the MHC binding predictors to run neoantigen prediction.
            </div>
            <p className="cs-tiny" style={{ margin: "4px 0 0" }}>
              Missing: {missingTools.tools.join(", ")}
            </p>
            {missingTools.hints.map((hint, i) => (
              <p
                key={i}
                className="cs-tiny"
                style={{ margin: "6px 0 0", fontFamily: "var(--font-mono)" }}
              >
                {hint}
              </p>
            ))}
          </div>
          <Btn variant="ghost" onClick={() => setMissingTools(null)}>
            Dismiss
          </Btn>
        </Callout>
      </>
    );
  }

  if (status === "blocked") {
    return (
      <>
        {header}
        <Callout tone="warm">
          <Dot style={{ color: "var(--warm)" }} />
          <div style={{ flex: 1 }}>
            <div style={{ fontSize: 15, fontWeight: 500, color: "var(--ink)" }}>
              {summary.blockingReason ?? "Finish annotation first."}
            </div>
            <p className="cs-tiny" style={{ margin: "4px 0 0" }}>
              Neoantigen prediction unlocks once annotation is done.
            </p>
          </div>
        </Callout>
      </>
    );
  }

  if (status === "scaffolded") {
    return (
      <>
        {header}
        <DlaAllelePanel
          alleles={summary.alleles}
          speciesLabel={speciesLabel(workspace.species)}
          editable={!submitting}
          onChange={saveAlleles}
        />
        <Card>
          <div
            style={{
              padding: "36px 32px",
              display: "grid",
              gridTemplateColumns: "1fr auto",
              gap: 24,
              alignItems: "center",
            }}
          >
            <div>
              <Eyebrow>Next step</Eyebrow>
              <h2
                style={{
                  fontFamily: "var(--font-display)",
                  fontSize: 28,
                  fontWeight: 500,
                  margin: "6px 0 10px",
                  letterSpacing: "-0.02em",
                  color: "var(--ink)",
                }}
              >
                Predict which fragments the immune system can see.
              </h2>
              <p
                style={{
                  fontSize: 16,
                  maxWidth: "54ch",
                  lineHeight: 1.7,
                  color: "var(--ink-2)",
                }}
              >
                We run pVACseq against the annotated VCF, score every possible 8–11 aa
                (class I) and 12–18 aa (class II) peptide against the alleles above, and
                rank the ones that would actually reach the cell surface.
              </p>
              <div style={{ marginTop: 18 }}>
                <Btn
                  data-testid="neoantigen-run-button"
                  disabled={submitting || summary.alleles.length === 0}
                  onClick={() => void runAction(() => api.runNeoantigen(workspace.id))}
                >
                  {submitting ? "Starting…" : "Predict neoantigens"}
                </Btn>
              </div>
              {summary.alleles.length === 0 ? (
                <p
                  className="cs-tiny"
                  style={{ marginTop: 10, color: "var(--warm)" }}
                >
                  Add at least one MHC allele before running.
                </p>
              ) : null}
              {actionError ? (
                <p
                  className="cs-tiny"
                  style={{ marginTop: 10, color: "var(--danger)" }}
                >
                  {actionError}
                </p>
              ) : null}
            </div>
            <Helix size={180} rungs={18} hue={tweaks.accentHue} speed={26} />
          </div>
        </Card>
      </>
    );
  }

  if (status === "running" && latestRun) {
    const phaseCopy = latestRun.runtimePhase
      ? RUNTIME_PHASE_COPY[latestRun.runtimePhase] ?? "Running pVACseq"
      : "Running pVACseq";
    return (
      <>
        {header}
        <Card>
          <div style={{ padding: "36px 32px", textAlign: "center" }}>
            <Helix size={220} rungs={20} hue={tweaks.accentHue} speed={18} />
            <div style={{ marginTop: 20 }}>
              <div
                className="cs-progress"
                style={{ maxWidth: 420, margin: "0 auto", height: 10 }}
              >
                <div
                  className="cs-progress-fill"
                  style={{
                    width: `${Math.max(3, Math.round(latestRun.progress * 100))}%`,
                  }}
                />
              </div>
              <p className="cs-tiny" style={{ marginTop: 14 }}>
                {phaseCopy} · {Math.round(latestRun.progress * 100)}%
              </p>
            </div>
          </div>
        </Card>
      </>
    );
  }

  if (status === "paused" && latestRun) {
    return (
      <>
        {header}
        <Callout>
          <Dot style={{ color: "var(--accent)" }} />
          <div style={{ flex: 1 }}>
            <div style={{ fontSize: 15, fontWeight: 500 }}>Paused.</div>
            <p className="cs-tiny" style={{ margin: "4px 0 0" }}>
              Resume to pick up from {latestRun.runtimePhase ?? "the last phase"}.
            </p>
          </div>
          <Btn
            disabled={submitting}
            onClick={() =>
              void runAction(() => api.resumeNeoantigen(workspace.id, latestRun.id))
            }
          >
            Resume
          </Btn>
        </Callout>
      </>
    );
  }

  if (status === "failed") {
    return (
      <>
        {header}
        <Callout tone="warm">
          <Dot style={{ color: "var(--warm)" }} />
          <div style={{ flex: 1 }}>
            <div style={{ fontSize: 15, fontWeight: 500, color: "var(--ink)" }}>
              Neoantigen prediction failed.
            </div>
            <p className="cs-tiny" style={{ margin: "4px 0 0" }}>
              {latestRun?.error ??
                "Try again, or check the pVACseq log in expert mode."}
            </p>
          </div>
          <Btn
            disabled={submitting}
            onClick={() => void runAction(() => api.rerunNeoantigen(workspace.id))}
          >
            Try again
          </Btn>
        </Callout>
      </>
    );
  }

  if (!metrics) {
    return (
      <>
        {header}
        <Card style={{ padding: "28px 24px", fontSize: 14 }}>
          Prediction finished, but no results are available. Open the expert drawer and
          check the pVACseq log.
        </Card>
      </>
    );
  }

  return (
    <>
      {header}

      <Callout
        tone="accent"
        style={{ marginBottom: 22, alignItems: "flex-start", gap: 16 }}
      >
        <div
          style={{
            width: 42,
            height: 42,
            borderRadius: 12,
            flexShrink: 0,
            background: "color-mix(in oklch, var(--accent) 18%, transparent)",
            border: "1px solid color-mix(in oklch, var(--accent) 38%, transparent)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            fontFamily: "var(--font-display)",
            fontSize: 20,
            color: "var(--accent-ink)",
          }}
        >
          ✦
        </div>
        <div style={{ flex: 1 }}>
          <Eyebrow>Prediction complete · pVACseq + NetMHCpan</Eyebrow>
          <h2
            style={{
              margin: "6px 0 6px",
              fontFamily: "var(--font-display)",
              fontWeight: 400,
              fontSize: 26,
              letterSpacing: "-0.02em",
              lineHeight: 1.3,
              textWrap: "pretty",
              color: "var(--ink)",
            }}
          >
            We made <Tnum>{metrics.peptidesGenerated.toLocaleString()}</Tnum> peptide
            fragments from this patient&apos;s mutations.{" "}
            <span style={{ color: "var(--accent-ink)", fontWeight: 500 }}>
              <Tnum>{metrics.visibleCandidates.toLocaleString()}</Tnum>
            </span>{" "}
            are predicted to be visible to the immune system —{" "}
            <Tnum>{metrics.classICount}</Tnum> via class I MHC,{" "}
            <Tnum>{metrics.classIICount}</Tnum> via class II.
          </h2>
          <p
            style={{
              margin: 0,
              fontSize: 14.5,
              lineHeight: 1.55,
              color: "var(--muted)",
            }}
          >
            Candidates are mutant peptides that bind at least one of the patient&apos;s
            MHC alleles below 500 nM and are absent (or far weaker) in the healthy
            reference.
          </p>
        </div>
        <div style={{ display: "flex", gap: 8, alignSelf: "center" }}>
          <Btn
            variant="ghost"
            disabled={submitting}
            onClick={() => void runAction(() => api.rerunNeoantigen(workspace.id))}
          >
            Rerun
          </Btn>
        </div>
      </Callout>

      <DlaAllelePanel
        alleles={metrics.alleles.length > 0 ? metrics.alleles : summary.alleles}
        speciesLabel={metrics.speciesLabel ?? speciesLabel(workspace.species)}
        editable={!submitting}
        onChange={saveAlleles}
        rejectedAlleles={metrics.rejectedAlleles}
      />

      <BucketTiles buckets={metrics.buckets} />

      <BindingHeatmap heatmap={metrics.heatmap} />

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "1.3fr 1fr",
          gap: 16,
          marginTop: 16,
        }}
      >
        <RankingScatter peptides={metrics.top} />
        <AntigenFlow steps={metrics.funnel} />
      </div>

      <CandidatesTable rows={metrics.top} />

      {tweaks.expertMode ? (
        <ExpertDrawer
          commandLog={latestRun?.commandLog ?? []}
          pvacseqVersion={metrics.pvacseqVersion ?? null}
        />
      ) : null}

      <div
        style={{
          marginTop: 22,
          padding: "18px 22px",
          borderRadius: "var(--radius-lg)",
          border: "1px dashed var(--line-strong)",
          background: "var(--surface-sunk)",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: 16,
          flexWrap: "wrap",
        }}
      >
        <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          <Eyebrow>Next</Eyebrow>
          <span
            style={{ fontSize: 15, fontWeight: 500, color: "var(--ink)" }}
          >
            Curate the cassette — pick 8 peptides for the vaccine.
          </span>
          <span style={{ fontSize: 13, color: "var(--muted)" }}>
            Balances class I / II coverage, diversifies genes and alleles, and
            flags peptides that hit self-proteins.
          </span>
        </div>
        <Link
          href={`/workspaces/${workspace.id}/epitope-selection`}
          className="cs-btn cs-btn-primary"
        >
          Open stage 06 →
        </Link>
      </div>
    </>
  );
}

function speciesLabel(species: string): string {
  if (species === "dog") return "dog (DLA)";
  if (species === "human") return "human (HLA)";
  if (species === "cat") return "cat (FLA)";
  return species;
}
