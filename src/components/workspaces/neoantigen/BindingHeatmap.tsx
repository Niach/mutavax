import { useState } from "react";

import { Card, Eyebrow } from "@/components/ui-kit";
import type { HeatmapData } from "@/lib/types";
import PeptideSeq from "./PeptideSeq";
import { formatIc50, ic50Color } from "./colors";

export default function BindingHeatmap({ heatmap }: { heatmap: HeatmapData }) {
  const { alleles, peptides } = heatmap;
  const [hover, setHover] = useState<string | null>(null);

  if (peptides.length === 0) {
    return null;
  }

  return (
    <Card style={{ marginBottom: 16 }}>
      <div
        style={{
          padding: "18px 22px 10px",
          display: "flex",
          alignItems: "flex-end",
          justifyContent: "space-between",
          gap: 16,
          flexWrap: "wrap",
        }}
      >
        <div style={{ minWidth: 260 }}>
          <Eyebrow>Binding affinity heatmap</Eyebrow>
          <h3
            style={{
              margin: "6px 0 0",
              fontFamily: "var(--font-display)",
              fontWeight: 500,
              fontSize: 22,
              letterSpacing: "-0.02em",
            }}
          >
            How tightly each peptide sticks to each allele
          </h3>
          <p
            style={{
              margin: "6px 0 0",
              fontSize: 13,
              color: "var(--muted)",
              maxWidth: "60ch",
              lineHeight: 1.5,
            }}
          >
            Darker tiles = tighter binding (lower IC50 in nM). A peptide only needs to stick
            to <em>one</em> of the patient&apos;s alleles to be a candidate.
          </p>
        </div>
        <HeatLegend />
      </div>

      <div style={{ padding: "4px 10px 16px", overflowX: "auto" }}>
        <div
          style={{
            display: "grid",
            gridTemplateColumns: `minmax(240px, 1.2fr) repeat(${alleles.length}, minmax(110px, 1fr))`,
            minWidth: 900,
            rowGap: 4,
            columnGap: 4,
            padding: "0 12px",
          }}
        >
          <div />
          {alleles.map((a) => (
            <div
              key={a}
              style={{
                padding: "8px 6px 10px",
                textAlign: "center",
                fontFamily: "var(--font-mono)",
                fontSize: 11,
                fontWeight: 600,
                color: "var(--muted)",
                letterSpacing: "0.04em",
                borderBottom: "1px solid var(--line)",
              }}
            >
              <div
                style={{
                  opacity: 0.7,
                  fontSize: 9.5,
                  textTransform: "uppercase",
                  letterSpacing: "0.18em",
                }}
              >
                {a.toUpperCase().includes("-D") ? "class II" : "class I"}
              </div>
              <div style={{ marginTop: 3 }}>{a}</div>
            </div>
          ))}

          {peptides.map((p, ri) => (
            <PeptideRow
              key={`${p.seq}-${ri}`}
              index={ri}
              peptide={p}
              alleles={alleles}
              hover={hover}
              setHover={setHover}
            />
          ))}
        </div>
      </div>
    </Card>
  );
}

function PeptideRow({
  index,
  peptide,
  alleles,
  hover,
  setHover,
}: {
  index: number;
  peptide: HeatmapData["peptides"][number];
  alleles: string[];
  hover: string | null;
  setHover: (id: string | null) => void;
}) {
  return (
    <>
      <div
        style={{
          padding: "6px 8px",
          display: "flex",
          alignItems: "center",
          gap: 10,
          borderRight: "1px solid var(--line)",
        }}
      >
        <div style={{ minWidth: 0, flex: 1 }}>
          <div
            style={{
              fontFamily: "var(--font-mono)",
              fontSize: 13.5,
              fontWeight: 600,
              color: "var(--ink)",
              letterSpacing: "0.02em",
            }}
          >
            <PeptideSeq seq={peptide.seq} mutPos={peptide.mutPos ?? null} />
          </div>
          <div style={{ marginTop: 2, fontSize: 11.5, color: "var(--muted)" }}>
            <span
              style={{
                fontFamily: "var(--font-display)",
                fontWeight: 600,
                color: "var(--ink-2)",
              }}
            >
              {peptide.gene}
            </span>{" "}
            <span style={{ color: "var(--muted-2)" }}>·</span> {peptide.mut}{" "}
            <span style={{ color: "var(--muted-2)" }}>·</span>{" "}
            <span style={{ fontFamily: "var(--font-mono)" }}>{peptide.length}-mer</span>
          </div>
        </div>
      </div>

      {peptide.ic50.map((v, ci) => {
        const c = ic50Color(v);
        const id = `${index}-${ci}`;
        const isH = hover === id;
        return (
          <div
            key={ci}
            onMouseEnter={() => setHover(id)}
            onMouseLeave={() => setHover(null)}
            style={{
              position: "relative",
              background: c.bg,
              color: c.fg,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              padding: "10px 6px",
              borderRadius: 6,
              fontFamily: "var(--font-mono)",
              fontSize: 12.5,
              fontWeight: 600,
              fontVariantNumeric: "tabular-nums",
              transition: "transform 120ms ease, box-shadow 120ms ease",
              transform: isH ? "scale(1.08)" : "scale(1)",
              boxShadow: isH ? "0 6px 20px -6px rgba(0,0,0,0.25)" : "none",
              zIndex: isH ? 3 : 1,
              cursor: "pointer",
            }}
          >
            {formatIc50(v)}
            {isH ? (
              <div
                style={{
                  position: "absolute",
                  bottom: "calc(100% + 6px)",
                  left: "50%",
                  transform: "translateX(-50%)",
                  padding: "8px 12px",
                  borderRadius: 8,
                  whiteSpace: "nowrap",
                  background: "var(--ink)",
                  color: "var(--surface)",
                  fontFamily: "var(--font-mono)",
                  fontSize: 11,
                  fontWeight: 500,
                  boxShadow: "0 12px 32px -12px rgba(0,0,0,0.4)",
                  zIndex: 10,
                }}
              >
                {peptide.seq} × {alleles[ci]} · {v.toLocaleString()} nM · {c.tier}
              </div>
            ) : null}
          </div>
        );
      })}
    </>
  );
}

function HeatLegend() {
  const stops = [
    { nm: "<50", col: "#0f766e" },
    { nm: "50–150", col: "#14b8a6" },
    { nm: "150–500", col: "#5eead4" },
    { nm: "500–1.5k", col: "#a5f3fc" },
    { nm: "1.5k–5k", col: "#e0f2fe" },
    { nm: ">5k", col: "var(--surface-sunk)" },
  ];
  return (
    <div style={{ display: "flex", alignItems: "flex-end", gap: 2, whiteSpace: "nowrap" }}>
      <div
        style={{
          display: "flex",
          flexDirection: "column",
          gap: 3,
          marginRight: 8,
        }}
      >
        <span
          style={{
            fontFamily: "var(--font-mono)",
            fontSize: 10,
            color: "var(--muted-2)",
            letterSpacing: "0.14em",
            textTransform: "uppercase",
            fontWeight: 600,
          }}
        >
          IC50 nM
        </span>
        <span
          style={{
            fontFamily: "var(--font-mono)",
            fontSize: 10.5,
            color: "var(--muted)",
          }}
        >
          tighter ←→ weaker
        </span>
      </div>
      {stops.map((s, i) => (
        <div
          key={i}
          style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 3 }}
        >
          <div
            style={{
              width: 40,
              height: 14,
              borderRadius: 3,
              background: s.col,
              border: "1px solid var(--line)",
            }}
          />
          <span
            style={{
              fontFamily: "var(--font-mono)",
              fontSize: 10,
              color: "var(--muted)",
              fontVariantNumeric: "tabular-nums",
            }}
          >
            {s.nm}
          </span>
        </div>
      ))}
    </div>
  );
}
