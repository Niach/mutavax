"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { Callout, Card, CardHead, Chip, Dot, Eyebrow } from "@/components/ui-kit";
import { useTweaks } from "@/components/dev/TweaksProvider";
import CandidateDeck, {
  type DeckFilter,
  type DeckSort,
} from "@/components/workspaces/epitope/CandidateDeck";
import CassettePanel from "@/components/workspaces/epitope/CassettePanel";
import CoverageWheel from "@/components/workspaces/epitope/CoverageWheel";
import GoalsStrip from "@/components/workspaces/epitope/GoalsStrip";
import SelectionSummary from "@/components/workspaces/epitope/SelectionSummary";
import { api } from "@/lib/api";
import type { EpitopeStageSummary, Workspace } from "@/lib/types";

const MAX_SLOTS = 8;
const SELECTION_DEBOUNCE_MS = 400;

interface EpitopeSelectionStagePanelProps {
  workspace: Workspace;
  initialSummary: EpitopeStageSummary;
  onSummaryChange?: (summary: EpitopeStageSummary) => void;
}

export default function EpitopeSelectionStagePanel({
  workspace,
  initialSummary,
  onSummaryChange,
}: EpitopeSelectionStagePanelProps) {
  const { tweaks } = useTweaks();
  const [summary, setSummary] = useState(initialSummary);
  const [picks, setPicks] = useState<string[]>(
    initialSummary.selection.length
      ? initialSummary.selection
      : initialSummary.defaultPicks,
  );
  const [filter, setFilter] = useState<DeckFilter>("all");
  const [sort, setSort] = useState<DeckSort>("score");
  const [hoverId, setHoverId] = useState<string | null>(null);

  const pushSummary = useCallback(
    (next: EpitopeStageSummary) => {
      setSummary(next);
      onSummaryChange?.(next);
    },
    [onSummaryChange],
  );

  const persistedRef = useRef<string>(picks.join(","));
  useEffect(() => {
    const key = picks.join(",");
    if (key === persistedRef.current) return;
    const handle = setTimeout(() => {
      persistedRef.current = key;
      api
        .updateEpitopeSelection(workspace.id, picks)
        .then(pushSummary)
        .catch(() => {
          // Surface silently — next GET will reconcile.
        });
    }, SELECTION_DEBOUNCE_MS);
    return () => clearTimeout(handle);
  }, [picks, workspace.id, pushSummary]);

  const byId = useMemo(
    () => Object.fromEntries(summary.candidates.map((c) => [c.id, c])),
    [summary.candidates],
  );
  const picked = useMemo(
    () => picks.map((id) => byId[id]).filter((c) => Boolean(c)),
    [picks, byId],
  );

  const toggle = useCallback((id: string) => {
    setPicks((prev) =>
      prev.includes(id)
        ? prev.filter((x) => x !== id)
        : prev.length < MAX_SLOTS
          ? [...prev, id]
          : prev,
    );
  }, []);
  const remove = useCallback((id: string) => {
    setPicks((prev) => prev.filter((x) => x !== id));
  }, []);
  const reset = useCallback(() => {
    setPicks(summary.defaultPicks.slice());
  }, [summary.defaultPicks]);
  const clear = useCallback(() => {
    setPicks([]);
  }, []);

  const header = (
    <div className="cs-view-head">
      <div>
        <div className="cs-crumb">
          {workspace.displayName} / 06 Epitope selection
        </div>
        <h1 style={{ textWrap: "pretty", margin: "4px 0 0" }}>
          Pick the fragments your vaccine will carry.
        </h1>
        <p
          style={{
            maxWidth: "62ch",
            marginTop: 12,
            fontSize: 16.5,
            lineHeight: 1.6,
            color: "var(--ink-2)",
          }}
        >
          A vaccine carries about seven mutant fragments. The goal: cover a
          few driver genes, reach several alleles, and skip anything that
          looks like a healthy protein.
        </p>
      </div>
      <div style={{ textAlign: "right", minWidth: 200 }}>
        <Chip kind="live">Stage 06 · Live</Chip>
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
          pVACview 5.4 · manual review
        </div>
      </div>
    </div>
  );

  if (summary.status === "blocked") {
    return (
      <>
        {header}
        <Callout tone="warm">
          <Dot style={{ color: "var(--warm)" }} />
          <div style={{ flex: 1 }}>
            <div style={{ fontSize: 15, fontWeight: 500, color: "var(--ink)" }}>
              {summary.blockingReason ??
                "Finish neoantigen prediction before curating the cassette."}
            </div>
            <p className="cs-tiny" style={{ margin: "4px 0 0" }}>
              Epitope selection unlocks once neoantigen prediction is done.
            </p>
          </div>
        </Callout>
      </>
    );
  }

  return (
    <>
      {header}

      <div style={{ marginBottom: 16 }}>
        <CassettePanel
          picked={picked}
          safety={summary.safety}
          hoverId={hoverId}
          onRemove={remove}
          onReset={reset}
          onClear={clear}
          setHoverId={setHoverId}
        />
      </div>

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "1fr 1fr",
          gap: 16,
          marginBottom: 16,
        }}
      >
        <CoverageWheel
          picked={picked}
          alleles={summary.alleles}
          hoverId={hoverId}
          setHoverId={setHoverId}
        />
        <GoalsStrip picked={picked} safety={summary.safety} />
      </div>

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "1.55fr 1fr",
          gap: 16,
          marginTop: 16,
        }}
      >
        <CandidateDeck
          candidates={summary.candidates}
          picks={picks}
          safety={summary.safety}
          filter={filter}
          sort={sort}
          hoverId={hoverId}
          onToggle={toggle}
          setFilter={setFilter}
          setSort={setSort}
          setHoverId={setHoverId}
        />
        <SelectionSummary picked={picked} alleles={summary.alleles} />
      </div>

      {tweaks.expertMode ? (
        <Card style={{ marginTop: 16 }}>
          <CardHead
            eyebrow="Expert · pVACview export"
            title="Shortlist → pVACseq generate_protein_fasta"
          />
          <pre
            style={{
              margin: 0,
              padding: "16px 22px",
              fontFamily: "var(--font-mono)",
              fontSize: 12,
              lineHeight: 1.7,
              color: "var(--muted)",
              background: "var(--surface-sunk)",
              borderBottomLeftRadius: "var(--radius-cs-lg)",
              borderBottomRightRadius: "var(--radius-cs-lg)",
              overflow: "auto",
            }}
          >
{`$ pvacview export-selection selection.tsv \\
    --peptides ${picked.map((p) => p.id).join(",")} \\
    --cassette-length ${picked.reduce((a, p) => a + p.length + 3, 0)}aa \\
    --linkers AAY,GPGPG \\
    --review-notes "Manual curation · safety cleared · ${picked.filter((p) => p.class === "II").length} class II for help"

[pvacview] ${picked.length} peptides selected · ${new Set(picked.map((p) => p.gene)).size} genes · ${new Set(picked.map((p) => p.alleleId)).size} alleles
[pvacview] self-similarity blastp: ${picked.filter((p) => summary.safety[p.id]?.risk === "critical").length} critical, ${picked.filter((p) => summary.safety[p.id]?.risk === "elevated").length} elevated
[pvacview] cassette length: ${picked.reduce((a, p) => a + p.length + 3, 0)}aa (with linkers) — fits target window
[pvacview] handoff → stage 7 mRNA construct design`}
          </pre>
        </Card>
      ) : null}

      <div
        style={{
          marginTop: 22,
          padding: "18px 22px",
          borderRadius: "var(--radius-cs-lg)",
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
            Fold these {picked.length} peptides into a codon-optimized mRNA
            cassette.
          </span>
          <span style={{ fontSize: 13, color: "var(--muted)" }}>
            Signal peptide → {picked.length} epitopes joined by{" "}
            {picked.some((p) => p.class === "II") ? "AAY / GPGPG" : "AAY"}{" "}
            linkers → stop, optimized by LinearDesign + DNAchisel.
          </span>
        </div>
        <Link
          href={`/workspaces/${workspace.id}/construct-design`}
          className="cs-btn cs-btn-primary"
        >
          Open stage 07 →
        </Link>
      </div>
    </>
  );
}
