"use client";

import { useMemo } from "react";

import { Card, MonoLabel } from "@/components/ui-kit";
import type { ConstructOutputStageSummary } from "@/lib/types";

import FastaLine from "./FastaLine";
import SegmentRibbon from "./SegmentRibbon";
import { RUN_COLORS } from "./colors";

const LINE_WIDTH = 60;

interface FastaHeroProps {
  summary: ConstructOutputStageSummary;
  onDownload: (format: "fasta" | "genbank" | "json") => void;
}

export default function FastaHero({ summary, onDownload }: FastaHeroProps) {
  const { runs, fullNt, constructId, species, totalNt, checksum, releasedAt, releasedBy } =
    summary;

  const charRun = useMemo(() => {
    const out = new Array<number>(fullNt.length);
    let i = 0;
    runs.forEach((r, runIdx) => {
      for (let k = 0; k < r.nt.length; k++) {
        out[i + k] = runIdx;
      }
      i += r.nt.length;
    });
    return out;
  }, [runs, fullNt]);

  const lines = useMemo(() => {
    const out: { start: number; text: string }[] = [];
    for (let i = 0; i < fullNt.length; i += LINE_WIDTH) {
      out.push({ start: i, text: fullNt.slice(i, i + LINE_WIDTH) });
    }
    return out;
  }, [fullNt]);

  return (
    <section>
      <Card style={{ overflow: "hidden" }}>
        <div
          style={{
            padding: "18px 26px 16px",
            borderBottom: "1px solid var(--line)",
            display: "flex",
            gap: 16,
            alignItems: "flex-start",
            justifyContent: "space-between",
            flexWrap: "wrap",
          }}
        >
          <div style={{ minWidth: 0, flex: 1 }}>
            <div style={{ marginBottom: 6 }}>
              <MonoLabel>The artifact</MonoLabel>
            </div>
            <h3
              style={{
                margin: 0,
                fontFamily: "var(--font-mono)",
                fontSize: 16,
                letterSpacing: "0.01em",
                lineHeight: 1.4,
                whiteSpace: "nowrap",
                overflow: "hidden",
                textOverflow: "ellipsis",
              }}
            >
              &gt; {constructId} | mRNA | {totalNt.toLocaleString()} nt | {species}
            </h3>
            <p
              className="cs-tiny"
              style={{
                margin: "6px 0 0",
                fontSize: 12,
                fontFamily: "var(--font-mono)",
                letterSpacing: "0.02em",
              }}
            >
              {checksum}
              {releasedAt ? ` · locked ${releasedAt}` : ""}
              {releasedBy ? ` · by ${releasedBy}` : ""}
            </p>
          </div>
          <div style={{ display: "flex", gap: 8, flexShrink: 0 }}>
            <DownloadBtn label="FASTA" onClick={() => onDownload("fasta")} />
            <DownloadBtn label="GenBank" onClick={() => onDownload("genbank")} />
            <DownloadBtn label="JSON" onClick={() => onDownload("json")} />
          </div>
        </div>

        <SegmentRibbon runs={runs} totalNt={totalNt} />

        <div
          style={{
            padding: "18px 26px 26px",
            background: "var(--surface-sunk)",
            borderTop: "1px solid var(--line)",
            maxHeight: 440,
            overflowY: "auto",
          }}
        >
          <div
            style={{
              fontFamily: "var(--font-mono)",
              fontSize: 13,
              lineHeight: 1.9,
              letterSpacing: "0.04em",
            }}
          >
            {lines.map((ln) => (
              <FastaLine
                key={ln.start}
                start={ln.start}
                text={ln.text}
                runs={runs}
                charRun={charRun}
              />
            ))}
          </div>
        </div>

        <div
          style={{
            padding: "14px 26px 20px",
            borderTop: "1px solid var(--line)",
            display: "flex",
            flexWrap: "wrap",
            gap: 16,
            fontFamily: "var(--font-mono)",
            fontSize: 11.5,
            color: "var(--muted)",
            letterSpacing: "0.05em",
          }}
        >
          {Object.entries(RUN_COLORS).map(([k, v]) => (
            <span
              key={k}
              style={{ display: "inline-flex", alignItems: "center", gap: 6 }}
            >
              <span
                style={{
                  display: "inline-block",
                  width: 12,
                  height: 12,
                  borderRadius: 3,
                  background: v.bg,
                  border: `1px solid color-mix(in oklch, ${v.fg} 30%, transparent)`,
                }}
              />
              {v.label}
            </span>
          ))}
        </div>
      </Card>
    </section>
  );
}

function DownloadBtn({ label, onClick }: { label: string; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      style={{
        height: 32,
        padding: "0 12px",
        borderRadius: 8,
        border: "1px solid var(--line-strong)",
        background: "var(--surface-strong)",
        fontFamily: "var(--font-mono)",
        fontSize: 11.5,
        letterSpacing: "0.1em",
        textTransform: "uppercase",
        color: "var(--ink-2)",
        cursor: "pointer",
        display: "inline-flex",
        alignItems: "center",
        gap: 6,
        fontWeight: 600,
      }}
    >
      ↓ {label}
    </button>
  );
}
