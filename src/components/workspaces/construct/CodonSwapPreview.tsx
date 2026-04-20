"use client";

import { Card, CardHead } from "@/components/ui-kit";
import type { ConstructPreview } from "@/lib/types";

interface CodonSwapPreviewProps {
  preview: ConstructPreview;
}

export default function CodonSwapPreview({ preview }: CodonSwapPreviewProps) {
  const codons = preview.codons;
  const swappedCount = codons.filter((c) => c.swapped).length;

  return (
    <Card>
      <CardHead
        eyebrow="One peptide, zoomed in"
        title={
          <>
            {preview.gene} · {preview.mut}
          </>
        }
        subtitle={
          <>
            Same protein, two different DNA recipes. {swappedCount} of {codons.length} codons
            get swapped — same amino acids, faster translation.
          </>
        }
        right={
          <div
            style={{
              fontFamily: "var(--font-mono)",
              fontSize: 11,
              color: "var(--muted)",
              letterSpacing: "0.1em",
            }}
          >
            ↓ 5′ to 3′
          </div>
        }
      />

      <div style={{ padding: "22px 26px" }}>
        <div
          style={{
            display: "grid",
            gridTemplateColumns: `90px repeat(${codons.length}, 1fr)`,
            gap: 3,
            marginBottom: 6,
          }}
        >
          <div
            style={{
              fontFamily: "var(--font-mono)",
              fontSize: 10.5,
              color: "var(--muted-2)",
              letterSpacing: "0.12em",
              textTransform: "uppercase",
              alignSelf: "center",
            }}
          >
            amino acid
          </div>
          {codons.map((c, i) => (
            <div
              key={i}
              style={{
                textAlign: "center",
                fontFamily: "var(--font-display)",
                fontSize: 22,
                color: "var(--ink)",
                letterSpacing: "-0.02em",
              }}
            >
              {c.aa}
            </div>
          ))}
        </div>

        <CodonRow label="Wild-type codons" codons={codons} pick="unopt" />
        <CodonRow label="LinearDesign picks" codons={codons} pick="opt" isOpt />

        <div
          style={{
            marginTop: 14,
            display: "flex",
            gap: 18,
            alignItems: "center",
            fontFamily: "var(--font-mono)",
            fontSize: 11,
            color: "var(--muted)",
            letterSpacing: "0.04em",
            flexWrap: "wrap",
          }}
        >
          <span>
            <span
              style={{
                display: "inline-block",
                width: 10,
                height: 10,
                borderRadius: 2,
                background: "color-mix(in oklch, var(--accent) 18%, transparent)",
                marginRight: 6,
                verticalAlign: "middle",
              }}
            />
            codon swapped
          </span>
          <span>same amino acid, rarer → more common codon for canine translation</span>
        </div>
      </div>
    </Card>
  );
}

function CodonRow({
  label,
  codons,
  pick,
  isOpt,
}: {
  label: string;
  codons: ConstructPreview["codons"];
  pick: "unopt" | "opt";
  isOpt?: boolean;
}) {
  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: `90px repeat(${codons.length}, 1fr)`,
        gap: 3,
        marginBottom: 6,
        alignItems: "center",
      }}
    >
      <div
        style={{
          fontFamily: "var(--font-mono)",
          fontSize: 10.5,
          color: "var(--muted-2)",
          letterSpacing: "0.12em",
          textTransform: "uppercase",
        }}
      >
        {label}
      </div>
      {codons.map((c, i) => {
        const codon = pick === "opt" ? c.opt : c.unopt;
        const highlight = c.swapped;
        const background = highlight && isOpt
          ? "color-mix(in oklch, var(--accent) 18%, transparent)"
          : highlight
            ? "color-mix(in oklch, var(--ink) 6%, transparent)"
            : "var(--surface-sunk)";
        const border = highlight && isOpt
          ? "1px solid color-mix(in oklch, var(--accent) 40%, transparent)"
          : "1px solid var(--line)";
        return (
          <div
            key={i}
            style={{
              padding: "10px 2px",
              borderRadius: 6,
              background,
              border,
              display: "grid",
              gridTemplateColumns: "1fr 1fr 1fr",
              fontFamily: "var(--font-mono)",
              fontSize: 14,
              fontWeight: 600,
              textAlign: "center",
              color: highlight && isOpt ? "var(--accent-ink)" : "var(--ink-2)",
              letterSpacing: "0.02em",
            }}
          >
            {codon.split("").map((base, j) => (
              <span key={j}>{base}</span>
            ))}
          </div>
        );
      })}
    </div>
  );
}
