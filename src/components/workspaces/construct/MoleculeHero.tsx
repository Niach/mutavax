"use client";

import { useState, type ReactNode } from "react";

import { Card, MonoLabel } from "@/components/ui-kit";
import type { ConstructFlanks, ConstructSegment } from "@/lib/types";

import { CONSTRUCT_COLORS, segmentColor } from "./colors";

interface HoverInfo {
  kind: string;
  label: string;
  aa: string;
  nt: string;
  why: string;
}

interface MoleculeHeroProps {
  segments: ConstructSegment[];
  aaSeq: string;
  flanks: ConstructFlanks;
  constructId: string;
}

export default function MoleculeHero({
  segments,
  aaSeq,
  flanks,
  constructId,
}: MoleculeHeroProps) {
  const [hover, setHover] = useState<HoverInfo | null>(null);

  const orfNt = aaSeq.length * 3;
  const totalBody = flanks.utr5.length + orfNt + flanks.utr3.length + flanks.polyA;
  const capPct = 5;
  const bodyPct = 100 - capPct;
  const pct = (nt: number) => (totalBody ? (nt / totalBody) * bodyPct : 0);

  return (
    <section aria-label="Complete mRNA molecule">
      <Card style={{ overflow: "visible" }}>
        <div
          className="cs-card-head"
          style={{ flexDirection: "column", alignItems: "stretch", gap: 6, paddingBottom: 10 }}
        >
          <div
            style={{
              display: "flex",
              justifyContent: "space-between",
              alignItems: "flex-start",
              gap: 16,
              flexWrap: "wrap",
            }}
          >
            <div>
              <div style={{ marginBottom: 6 }}>
                <MonoLabel>The molecule</MonoLabel>
              </div>
              <h3 style={{ margin: 0 }}>{constructId} · complete mRNA cassette</h3>
            </div>
            <Legend />
          </div>
        </div>

        <div style={{ padding: "28px 26px 26px" }}>
          <ScaleLabels
            capPct={capPct}
            utr5Pct={pct(flanks.utr5.length)}
            orfPct={pct(orfNt)}
            utr3Pct={pct(flanks.utr3.length)}
            polyAPct={pct(flanks.polyA)}
          />

          <div
            style={{
              display: "flex",
              height: 64,
              borderRadius: 16,
              overflow: "hidden",
              boxShadow: "inset 0 0 0 1px var(--line-strong), var(--shadow-sm)",
              background: "var(--surface-sunk)",
            }}
          >
            <HeroSeg
              width={`${capPct}%`}
              color={CONSTRUCT_COLORS.cap}
              onHover={() =>
                setHover({
                  kind: "cap",
                  label: "m7G cap",
                  aa: "",
                  nt: "m7GpppN…",
                  why: "Ribosome landing pad. Without it, nothing translates.",
                })
              }
              onLeave={() => setHover(null)}
            >
              <CapGlyph />
            </HeroSeg>

            <HeroSeg
              width={`${pct(flanks.utr5.length)}%`}
              color={CONSTRUCT_COLORS.utr5}
              pattern="utr"
              label={flanks.utr5.length > 35 ? "5′ UTR" : ""}
              onHover={() =>
                setHover({
                  kind: "utr5",
                  label: "5′ UTR + Kozak",
                  aa: "",
                  nt: `${flanks.utr5.length} nt`,
                  why: "A well-tuned upstream region that tells the ribosome where to start. Canonical Kozak sequence.",
                })
              }
              onLeave={() => setHover(null)}
            />

            {segments.map((s, i) => {
              const ntLen = s.aa.length * 3;
              const width = orfNt > 0 ? `${(ntLen / orfNt) * pct(orfNt)}%` : "0%";
              const color = segmentColor(s.kind, s.class);
              const label =
                s.kind === "peptide"
                  ? s.label
                  : s.kind === "signal"
                    ? "SP"
                    : s.kind === "mitd"
                      ? "MITD"
                      : "";
              const labelSub = s.kind === "peptide" ? s.sub ?? null : null;
              return (
                <HeroSeg
                  key={i}
                  width={width}
                  color={color}
                  label={label}
                  labelSub={labelSub}
                  isPeptide={s.kind === "peptide"}
                  onHover={() =>
                    setHover({
                      kind: s.kind,
                      label:
                        s.kind === "peptide"
                          ? `${s.label} — ${s.sub ?? ""}`
                          : s.kind === "signal"
                            ? "Signal peptide (tPA)"
                            : s.kind === "mitd"
                              ? "MITD trafficking tail"
                              : `Linker · ${s.label}`,
                      aa: s.aa,
                      nt: `${s.aa.length} aa · ${ntLen} nt`,
                      why:
                        s.kind === "peptide"
                          ? `Class-${s.class ?? "I"} neoantigen. Will be displayed on MHC-${s.class ?? "I"}.`
                          : s.kind === "signal"
                            ? flanks.signalWhy
                            : s.kind === "mitd"
                              ? flanks.mitdWhy
                              : "Flexible spacer — lets each peptide get cleaved out cleanly.",
                    })
                  }
                  onLeave={() => setHover(null)}
                />
              );
            })}

            <HeroSeg
              width={`${pct(flanks.utr3.length)}%`}
              color={CONSTRUCT_COLORS.utr3}
              pattern="utr"
              label={flanks.utr3.length > 35 ? "3′ UTR" : ""}
              onHover={() =>
                setHover({
                  kind: "utr3",
                  label: "3′ UTR",
                  aa: "",
                  nt: `${flanks.utr3.length} nt`,
                  why: "Alpha/beta-globin UTR blend. Keeps the mRNA alive longer in the cytoplasm.",
                })
              }
              onLeave={() => setHover(null)}
            />

            <HeroSeg
              width={`${pct(flanks.polyA)}%`}
              color={CONSTRUCT_COLORS.polyA}
              pattern="polyA"
              label={flanks.polyA > 60 ? `A${subscript(flanks.polyA)}` : ""}
              onHover={() =>
                setHover({
                  kind: "polyA",
                  label: "poly(A) tail",
                  aa: "",
                  nt: `${flanks.polyA} adenines`,
                  why: "The lifespan dial. 120 As keeps this mRNA translating for days inside a cell.",
                })
              }
              onLeave={() => setHover(null)}
            />
          </div>

          <div
            style={{
              display: "flex",
              marginTop: 8,
              fontFamily: "var(--font-mono)",
              fontSize: 10,
              color: "var(--muted-2)",
              letterSpacing: "0.05em",
            }}
          >
            <div style={{ width: `${capPct}%` }}>0</div>
            <div style={{ flex: 1, textAlign: "right" }}>
              {totalBody.toLocaleString()} nt
            </div>
          </div>

          <HoverReadout info={hover} />
        </div>
      </Card>
    </section>
  );
}

function ScaleLabels({
  capPct,
  utr5Pct,
  orfPct,
  utr3Pct,
  polyAPct,
}: {
  capPct: number;
  utr5Pct: number;
  orfPct: number;
  utr3Pct: number;
  polyAPct: number;
}) {
  const base: React.CSSProperties = {
    fontFamily: "var(--font-mono)",
    fontSize: 10.5,
    color: "var(--muted-2)",
    letterSpacing: "0.08em",
    textTransform: "uppercase",
  };
  return (
    <div style={{ display: "flex", marginBottom: 10 }}>
      <div style={{ ...base, width: `${capPct}%`, textAlign: "center" }}>5′ end</div>
      <div style={{ ...base, width: `${utr5Pct}%`, textAlign: "left", paddingLeft: 4 }}>
        5′ UTR + Kozak
      </div>
      <div style={{ ...base, width: `${orfPct}%`, textAlign: "center" }}>
        ORF — the protein the ribosome builds
      </div>
      <div style={{ ...base, width: `${utr3Pct}%`, textAlign: "right", paddingRight: 4 }}>
        3′ UTR
      </div>
      <div style={{ ...base, width: `${polyAPct}%`, textAlign: "right" }}>poly(A)</div>
    </div>
  );
}

interface HeroSegProps {
  width: string;
  color: string;
  label?: string;
  labelSub?: string | null;
  isPeptide?: boolean;
  pattern?: "utr" | "polyA";
  children?: ReactNode;
  onHover: () => void;
  onLeave: () => void;
}

function HeroSeg({
  width,
  color,
  label,
  labelSub,
  isPeptide,
  pattern,
  children,
  onHover,
  onLeave,
}: HeroSegProps) {
  const bg =
    pattern === "utr"
      ? `repeating-linear-gradient(90deg, ${color} 0 6px, color-mix(in oklch, ${color} 60%, white) 6px 12px)`
      : pattern === "polyA"
        ? `repeating-linear-gradient(90deg, ${color} 0 3px, color-mix(in oklch, ${color} 75%, white) 3px 6px)`
        : color;
  return (
    <div
      onMouseEnter={onHover}
      onMouseLeave={onLeave}
      style={{
        width,
        background: bg,
        position: "relative",
        borderRight: "1px solid rgba(255,255,255,0.25)",
        cursor: "pointer",
        transition: "filter 0.15s",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        overflow: "hidden",
      }}
    >
      {children}
      {label ? (
        <div
          style={{
            color: "white",
            fontSize: isPeptide ? 11.5 : 10.5,
            fontWeight: 600,
            fontFamily: isPeptide ? "var(--font-ui)" : "var(--font-mono)",
            textShadow: "0 1px 3px rgba(0,0,0,0.35)",
            letterSpacing: isPeptide ? "-0.01em" : "0.1em",
            textTransform: isPeptide ? "none" : "uppercase",
            textAlign: "center",
            lineHeight: 1.1,
            padding: "0 4px",
            whiteSpace: "nowrap",
            overflow: "hidden",
            textOverflow: "ellipsis",
            maxWidth: "100%",
          }}
        >
          {label}
          {labelSub ? (
            <div
              style={{
                fontSize: 9,
                fontWeight: 500,
                opacity: 0.85,
                marginTop: 1,
                fontFamily: "var(--font-mono)",
              }}
            >
              {labelSub}
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

function CapGlyph() {
  return (
    <svg
      viewBox="0 0 24 24"
      width="28"
      height="28"
      style={{ filter: "drop-shadow(0 1px 2px rgba(0,0,0,0.3))" }}
    >
      <circle cx="12" cy="12" r="8.5" fill="#fff" opacity="0.95" />
      <text
        x="12"
        y="15.5"
        textAnchor="middle"
        fontSize="9"
        fontFamily="var(--font-mono)"
        fontWeight="700"
        fill="#78350f"
      >
        m⁷G
      </text>
    </svg>
  );
}

function Legend() {
  const items: { color: string; label: string }[] = [
    { color: CONSTRUCT_COLORS.cap, label: "cap" },
    { color: CONSTRUCT_COLORS.utr5, label: "UTR" },
    { color: CONSTRUCT_COLORS.signal, label: "signal" },
    { color: CONSTRUCT_COLORS.classI, label: "class-I peptide" },
    { color: CONSTRUCT_COLORS.classII, label: "class-II peptide" },
    { color: CONSTRUCT_COLORS.mitd, label: "trafficking" },
    { color: CONSTRUCT_COLORS.polyA, label: "poly(A)" },
  ];
  return (
    <div
      style={{
        display: "flex",
        gap: 14,
        fontFamily: "var(--font-mono)",
        fontSize: 11.5,
        color: "var(--muted)",
        flexWrap: "wrap",
      }}
    >
      {items.map((item) => (
        <span
          key={item.label}
          style={{ display: "inline-flex", alignItems: "center", gap: 5 }}
        >
          <span
            style={{
              width: 9,
              height: 9,
              borderRadius: 3,
              background: item.color,
              boxShadow: "inset 0 0 0 1px rgba(0,0,0,0.1)",
            }}
          />
          {item.label}
        </span>
      ))}
    </div>
  );
}

function HoverReadout({ info }: { info: HoverInfo | null }) {
  if (!info) {
    return (
      <div
        style={{
          marginTop: 16,
          padding: "14px 18px",
          borderRadius: 12,
          background: "var(--surface-sunk)",
          border: "1px dashed var(--line-strong)",
          fontFamily: "var(--font-mono)",
          fontSize: 12,
          color: "var(--muted)",
          letterSpacing: "0.05em",
        }}
      >
        Hover any segment to inspect its role.
      </div>
    );
  }
  return (
    <div
      style={{
        marginTop: 16,
        padding: "14px 18px",
        borderRadius: 12,
        background: "var(--surface-sunk)",
        border: "1px solid var(--line-strong)",
        display: "grid",
        gridTemplateColumns: "1fr auto",
        gap: 20,
        alignItems: "center",
      }}
    >
      <div>
        <div style={{ display: "flex", gap: 10, alignItems: "baseline", marginBottom: 4 }}>
          <strong style={{ fontSize: 15 }}>{info.label}</strong>
          <MonoLabel style={{ fontSize: 10.5 }}>{info.nt}</MonoLabel>
        </div>
        <div
          className="cs-tiny"
          style={{ color: "var(--ink-2)", fontSize: 13.5, lineHeight: 1.5 }}
        >
          {info.why}
        </div>
      </div>
      {info.aa ? (
        <div
          style={{
            fontFamily: "var(--font-mono)",
            fontSize: 11.5,
            color: "var(--muted-2)",
            maxWidth: 340,
            textAlign: "right",
            letterSpacing: "0.04em",
            wordBreak: "break-all",
          }}
        >
          {info.aa.length > 44 ? `${info.aa.slice(0, 44)}…` : info.aa}
        </div>
      ) : null}
    </div>
  );
}

function subscript(n: number): string {
  const map: Record<string, string> = {
    "0": "₀",
    "1": "₁",
    "2": "₂",
    "3": "₃",
    "4": "₄",
    "5": "₅",
    "6": "₆",
    "7": "₇",
    "8": "₈",
    "9": "₉",
  };
  return String(n)
    .split("")
    .map((c) => map[c] ?? c)
    .join("");
}
