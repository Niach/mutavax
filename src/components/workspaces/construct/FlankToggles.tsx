"use client";

import { CONSTRUCT_COLORS } from "./colors";

interface FlankTogglesProps {
  useSignal: boolean;
  useMitd: boolean;
  onSignalChange: (next: boolean) => void;
  onMitdChange: (next: boolean) => void;
}

export default function FlankToggles({
  useSignal,
  useMitd,
  onSignalChange,
  onMitdChange,
}: FlankTogglesProps) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      <FlankToggle
        on={useSignal}
        onChange={onSignalChange}
        name="Signal peptide (tPA)"
        short="SP"
        color={CONSTRUCT_COLORS.signal}
        why="Routes the peptides into the secretory pathway so they get loaded onto MHC molecules."
      />
      <FlankToggle
        on={useMitd}
        onChange={onMitdChange}
        name="MHC-I trafficking tail (MITD)"
        short="MITD"
        color={CONSTRUCT_COLORS.mitd}
        why="Sends peptides through late endosomes — BioNTech's trick to prime both CD8 and CD4 T-cells."
      />
      <div
        style={{
          marginTop: 6,
          padding: "10px 12px",
          borderRadius: 10,
          background: "color-mix(in oklch, var(--accent) 6%, var(--surface-sunk))",
          border: "1px solid var(--line)",
          fontSize: 12.5,
          color: "var(--muted)",
          lineHeight: 1.5,
        }}
      >
        <strong style={{ color: "var(--ink-2)" }}>Linkers:</strong> AAY between class-I
        peptides (preferred proteasome cleavage), GPGPG between class-II peptides (lets MHC-II
        load cleanly).
      </div>
    </div>
  );
}

function FlankToggle({
  on,
  onChange,
  name,
  short,
  color,
  why,
}: {
  on: boolean;
  onChange: (next: boolean) => void;
  name: string;
  short: string;
  color: string;
  why: string;
}) {
  return (
    <label
      style={{
        display: "grid",
        gridTemplateColumns: "auto 1fr auto",
        gap: 12,
        alignItems: "center",
        padding: "12px 14px",
        borderRadius: 12,
        border: "1px solid var(--line)",
        background: on
          ? "color-mix(in oklch, var(--accent) 4%, var(--surface-strong))"
          : "var(--surface-strong)",
        cursor: "pointer",
        transition: "background 0.15s, border-color 0.15s",
      }}
    >
      <div
        style={{
          width: 34,
          height: 34,
          borderRadius: 10,
          background: color,
          color: "white",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          fontFamily: "var(--font-mono)",
          fontSize: 10.5,
          fontWeight: 700,
          letterSpacing: "0.05em",
        }}
      >
        {short}
      </div>
      <div>
        <div style={{ fontSize: 14, fontWeight: 500, color: "var(--ink)" }}>{name}</div>
        <div
          style={{ fontSize: 12, color: "var(--muted)", marginTop: 1, lineHeight: 1.4 }}
        >
          {why}
        </div>
      </div>
      <div
        style={{
          width: 36,
          height: 22,
          borderRadius: 999,
          background: on
            ? "var(--accent)"
            : "color-mix(in oklch, var(--ink) 14%, transparent)",
          position: "relative",
          transition: "background 0.2s",
        }}
      >
        <div
          style={{
            position: "absolute",
            top: 2,
            left: on ? 16 : 2,
            width: 18,
            height: 18,
            borderRadius: 999,
            background: "white",
            transition: "left 0.2s",
            boxShadow: "0 1px 3px rgba(0,0,0,0.2)",
          }}
        />
      </div>
      <input
        type="checkbox"
        checked={on}
        onChange={(e) => onChange(e.target.checked)}
        style={{ display: "none" }}
      />
    </label>
  );
}
