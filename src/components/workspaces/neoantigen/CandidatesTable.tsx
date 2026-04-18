import { useMemo, useState } from "react";

import { Card, Eyebrow } from "@/components/ui-kit";
import type { TopCandidate } from "@/lib/types";
import PeptideSeq from "./PeptideSeq";
import { CLASS_I_ACCENT, CLASS_II_ACCENT } from "./colors";

type FilterKey = "all" | "strong" | "classI" | "classII";

const CHIPS: { key: FilterKey; label: string }[] = [
  { key: "strong", label: "Strong binders" },
  { key: "classI", label: "Class I" },
  { key: "classII", label: "Class II" },
  { key: "all", label: "All" },
];

function matchesFilter(row: TopCandidate, filter: FilterKey): boolean {
  if (filter === "all") return true;
  if (filter === "strong") return row.strong;
  if (filter === "classI") return row.class === "I";
  if (filter === "classII") return row.class === "II";
  return true;
}

export default function CandidatesTable({ rows }: { rows: TopCandidate[] }) {
  const [filter, setFilter] = useState<FilterKey>("strong");

  const counts = useMemo(
    () => ({
      all: rows.length,
      strong: rows.filter((r) => r.strong).length,
      classI: rows.filter((r) => r.class === "I").length,
      classII: rows.filter((r) => r.class === "II").length,
    }),
    [rows],
  );

  const filtered = useMemo(
    () => rows.filter((r) => matchesFilter(r, filter)),
    [rows, filter],
  );

  return (
    <Card style={{ marginTop: 16 }}>
      <div
        style={{
          padding: "18px 22px 12px",
          display: "flex",
          alignItems: "flex-end",
          justifyContent: "space-between",
          gap: 16,
          flexWrap: "wrap",
        }}
      >
        <div style={{ minWidth: 220 }}>
          <Eyebrow>Top candidates</Eyebrow>
          <h3
            style={{
              margin: "6px 0 0",
              fontFamily: "var(--font-display)",
              fontWeight: 500,
              fontSize: 20,
              letterSpacing: "-0.02em",
            }}
          >
            {filtered.length} of {rows.length} · ranked by IC50
          </h3>
        </div>
        <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
          {CHIPS.map((chip) => {
            const active = filter === chip.key;
            return (
              <button
                key={chip.key}
                onClick={() => setFilter(chip.key)}
                style={{
                  padding: "6px 12px",
                  borderRadius: 999,
                  border: active
                    ? "1.5px solid var(--accent)"
                    : "1px solid var(--line)",
                  background: active
                    ? "color-mix(in oklch, var(--accent) 10%, var(--surface-strong))"
                    : "var(--surface-strong)",
                  fontFamily: "var(--font-mono)",
                  fontSize: 11.5,
                  color: active ? "var(--accent-ink)" : "var(--muted)",
                  cursor: "pointer",
                  fontWeight: 600,
                  letterSpacing: "0.08em",
                  textTransform: "uppercase",
                }}
              >
                {chip.label} · {counts[chip.key]}
              </button>
            );
          })}
        </div>
      </div>

      <div style={{ padding: "0 8px 10px" }}>
        <div
          className="cs-data-row cs-data-head"
          style={{
            gridTemplateColumns: "1.7fr 1fr 1fr 0.9fr 0.9fr 0.9fr 0.7fr",
          }}
        >
          <span>Peptide</span>
          <span>Source</span>
          <span>Best allele</span>
          <span style={{ textAlign: "right" }}>IC50 (nM)</span>
          <span style={{ textAlign: "right" }}>vs. wild</span>
          <span style={{ textAlign: "right" }}>TPM · VAF</span>
          <span style={{ textAlign: "right" }}>Class</span>
        </div>
        {filtered.length === 0 ? (
          <div
            style={{
              padding: "16px 16px 22px",
              color: "var(--muted)",
              fontSize: 13.5,
            }}
          >
            No candidates in this filter. Try &ldquo;All&rdquo; above.
          </div>
        ) : null}
        {filtered.map((r, i) => (
          <div
            key={`${r.seq}-${i}`}
            className="cs-data-row"
            style={{
              gridTemplateColumns: "1.7fr 1fr 1fr 0.9fr 0.9fr 0.9fr 0.7fr",
            }}
          >
            <span
              style={{
                display: "flex",
                alignItems: "center",
                gap: 10,
                minWidth: 0,
              }}
            >
              <span
                style={{
                  padding: "4px 8px",
                  borderRadius: 5,
                  background: r.strong
                    ? "color-mix(in oklch, #0f766e 14%, transparent)"
                    : "var(--surface-sunk)",
                  fontFamily: "var(--font-mono)",
                  fontSize: 13.5,
                  fontWeight: 600,
                  color: r.strong ? "#0f766e" : "var(--ink-2)",
                  letterSpacing: "0.04em",
                  whiteSpace: "nowrap",
                }}
              >
                <PeptideSeq
                  seq={r.seq}
                  mutPos={r.class === "II" ? Math.floor(r.length / 2) : Math.floor(r.length * 0.35)}
                />
              </span>
            </span>
            <span style={{ display: "flex", flexDirection: "column", gap: 1 }}>
              <span
                style={{
                  fontFamily: "var(--font-display)",
                  fontSize: 14,
                  fontWeight: 600,
                  color: "var(--ink)",
                }}
              >
                {r.gene}
              </span>
              <span
                style={{
                  fontFamily: "var(--font-mono)",
                  fontSize: 11.5,
                  color: "var(--muted)",
                }}
              >
                {r.mut}
              </span>
            </span>
            <span
              style={{
                fontFamily: "var(--font-mono)",
                fontSize: 12,
                color: "var(--ink-2)",
              }}
            >
              {r.allele}
            </span>
            <span
              style={{
                textAlign: "right",
                fontFamily: "var(--font-mono)",
                fontSize: 13,
                fontVariantNumeric: "tabular-nums",
                color: r.strong ? "#0f766e" : "var(--ink-2)",
                fontWeight: r.strong ? 700 : 500,
              }}
            >
              {r.ic50.toLocaleString(undefined, { maximumFractionDigits: 0 })}
            </span>
            <span
              style={{
                textAlign: "right",
                fontFamily: "var(--font-mono)",
                fontSize: 12,
                color: "var(--muted)",
                fontVariantNumeric: "tabular-nums",
              }}
            >
              {r.agretopicity !== null && r.agretopicity !== undefined
                ? `${r.agretopicity.toFixed(1)}×`
                : "—"}
            </span>
            <span
              style={{
                textAlign: "right",
                fontFamily: "var(--font-mono)",
                fontSize: 12,
                color: "var(--ink-2)",
                fontVariantNumeric: "tabular-nums",
              }}
            >
              {r.tpm !== null && r.tpm !== undefined
                ? r.tpm.toFixed(0)
                : "—"}
              {r.vaf !== null && r.vaf !== undefined
                ? ` · ${Math.round(r.vaf * 100)}%`
                : ""}
            </span>
            <span style={{ textAlign: "right" }}>
              <span
                style={{
                  display: "inline-block",
                  padding: "3px 10px",
                  borderRadius: 6,
                  background:
                    r.class === "I"
                      ? `color-mix(in oklch, ${CLASS_I_ACCENT} 14%, transparent)`
                      : `color-mix(in oklch, ${CLASS_II_ACCENT} 14%, transparent)`,
                  color: r.class === "I" ? CLASS_I_ACCENT : CLASS_II_ACCENT,
                  fontFamily: "var(--font-mono)",
                  fontSize: 11,
                  fontWeight: 700,
                  letterSpacing: "0.12em",
                }}
              >
                {r.class}
              </span>
            </span>
          </div>
        ))}
      </div>
    </Card>
  );
}
