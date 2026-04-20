"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useState } from "react";

import { Btn, Callout, Chip } from "@/components/ui-kit";
import AuditCard from "@/components/workspaces/construct-output/AuditCard";
import CmoCard from "@/components/workspaces/construct-output/CmoCard";
import FastaHero from "@/components/workspaces/construct-output/FastaHero";
import VetCard from "@/components/workspaces/construct-output/VetCard";
import { api } from "@/lib/api";
import type { ConstructOutputStageSummary, Workspace } from "@/lib/types";

interface ConstructOutputStagePanelProps {
  workspace: Workspace;
  initialSummary: ConstructOutputStageSummary;
  onSummaryChange?: (summary: ConstructOutputStageSummary) => void;
}

export default function ConstructOutputStagePanel({
  workspace,
  initialSummary,
  onSummaryChange,
}: ConstructOutputStagePanelProps) {
  const router = useRouter();
  const [summary, setSummary] = useState(initialSummary);
  const [submitting, setSubmitting] = useState(false);

  const push = useCallback(
    (next: ConstructOutputStageSummary) => {
      setSummary(next);
      onSummaryChange?.(next);
    },
    [onSummaryChange]
  );

  const handleSelectCmo = useCallback(
    async (cmoId: string) => {
      try {
        const next = await api.updateConstructOutput(workspace.id, {
          action: "select_cmo",
          cmoId,
        });
        push(next);
      } catch {
        // silent — GET will reconcile
      }
    },
    [workspace.id, push]
  );

  const handleRelease = useCallback(async () => {
    setSubmitting(true);
    try {
      const next = await api.updateConstructOutput(workspace.id, {
        action: "release",
        cmoId: summary.selectedCmo ?? summary.cmoOptions[0]?.id ?? null,
      });
      push(next);
    } finally {
      setSubmitting(false);
    }
  }, [workspace.id, summary.selectedCmo, summary.cmoOptions, push]);

  const handleDownload = useCallback(
    (format: "fasta" | "genbank" | "json") => {
      if (typeof window === "undefined") return;
      const content = renderDownload(summary, format);
      const blob = new Blob([content], { type: mimeFor(format) });
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `${summary.constructId}.${extensionFor(format)}`;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(url);
    },
    [summary]
  );

  const header = (
    <div className="cs-view-head">
      <div>
        <div className="cs-crumb">
          {workspace.displayName} / 08 Construct output
        </div>
        <h1 style={{ textWrap: "pretty", margin: "4px 0 0" }}>
          The vaccine, as a file.
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
          Everything upstream collapses into one {summary.totalNt.toLocaleString()}
          -nucleotide string of text. Hand that text to any CMO with an IVT line and ≈10
          days later it comes back as a vial of mRNA ready to formulate into lipid
          nanoparticles.
        </p>
      </div>
      <div style={{ textAlign: "right", minWidth: 200 }}>
        {summary.status === "released" ? (
          <Chip kind="live">Stage 08 · Released</Chip>
        ) : (
          <Chip kind="scaffold">Stage 08 · Ready</Chip>
        )}
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
          {summary.constructId} · {summary.version}
        </div>
      </div>
    </div>
  );

  if (summary.status === "blocked") {
    return (
      <>
        {header}
        <Callout tone="warm" style={{ marginTop: 12 }}>
          <div>
            <strong>Confirm the construct design first.</strong>
            <p style={{ margin: "6px 0 0", fontSize: 14, color: "var(--ink-2)" }}>
              {summary.blockingReason ??
                "Confirm the construct design before generating the output."}
            </p>
            <div style={{ marginTop: 10 }}>
              <Link href={`/workspaces/${workspace.id}/construct-design`}>
                <Btn variant="primary" size="sm">
                  Go to construct design
                </Btn>
              </Link>
            </div>
          </div>
        </Callout>
      </>
    );
  }

  return (
    <>
      {header}

      <FastaHero summary={summary} onDownload={handleDownload} />

      <div
        style={{
          marginTop: 22,
          display: "grid",
          gridTemplateColumns: "minmax(0, 1.1fr) minmax(0, 1fr) minmax(0, 1fr)",
          gap: 16,
        }}
      >
        <CmoCard
          options={summary.cmoOptions}
          selectedCmo={summary.selectedCmo ?? null}
          order={summary.order ?? null}
          released={summary.status === "released"}
          submitting={submitting}
          onSelect={handleSelectCmo}
          onRelease={handleRelease}
        />
        <VetCard dosing={summary.dosing} />
        <AuditCard trail={summary.auditTrail} onExport={() => handleDownload("json")} />
      </div>

      <div
        style={{
          marginTop: 28,
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          gap: 16,
          flexWrap: "wrap",
        }}
      >
        <Btn
          variant="ghost"
          onClick={() => router.push(`/workspaces/${workspace.id}/construct-design`)}
        >
          ← Back to construct design
        </Btn>
        <div
          style={{
            fontFamily: "var(--font-mono)",
            fontSize: 11,
            color: "var(--muted-2)",
            letterSpacing: "0.08em",
          }}
        >
          End of pipeline · {summary.checksum}
        </div>
      </div>
    </>
  );
}

function renderDownload(
  summary: ConstructOutputStageSummary,
  format: "fasta" | "genbank" | "json"
): string {
  if (format === "fasta") {
    const header = `> ${summary.constructId} | mRNA | ${summary.totalNt} nt | ${summary.species}\n`;
    const lines: string[] = [];
    for (let i = 0; i < summary.fullNt.length; i += 60) {
      lines.push(summary.fullNt.slice(i, i + 60));
    }
    return header + lines.join("\n") + "\n";
  }
  if (format === "json") {
    return JSON.stringify(summary, null, 2);
  }
  // minimal GenBank-style stub — enough to be opened by tooling, not a full record
  let feats = "";
  let cursor = 1;
  summary.runs.forEach((r) => {
    const start = cursor;
    const end = cursor + r.nt.length - 1;
    feats += `     misc_feature    ${start}..${end}\n                     /label="${r.label}"\n`;
    cursor = end + 1;
  });
  const seq = summary.fullNt.toLowerCase().match(/.{1,60}/g) ?? [];
  const seqBlock = seq
    .map((line, idx) => {
      const pos = idx * 60 + 1;
      return `${pos.toString().padStart(9, " ")} ${
        line.match(/.{1,10}/g)?.join(" ") ?? line
      }`;
    })
    .join("\n");
  return (
    `LOCUS       ${summary.constructId.padEnd(16)} ${summary.totalNt} bp    mRNA\n` +
    `DEFINITION  ${summary.constructId} personalized neoantigen cassette\n` +
    `FEATURES             Location/Qualifiers\n${feats}ORIGIN\n${seqBlock}\n//\n`
  );
}

function mimeFor(format: "fasta" | "genbank" | "json"): string {
  if (format === "json") return "application/json";
  return "text/plain";
}

function extensionFor(format: "fasta" | "genbank" | "json"): string {
  if (format === "fasta") return "fasta";
  if (format === "genbank") return "gb";
  return "json";
}
