"use client";

import type { ConstructMetrics } from "@/lib/types";

interface LambdaSliderProps {
  lambda: number;
  onChange: (value: number) => void;
  metrics: ConstructMetrics;
}

export default function LambdaSlider({ lambda, onChange, metrics }: LambdaSliderProps) {
  const pts = 40;
  const caiN: number[] = [];
  const mfeN: number[] = [];
  for (let i = 0; i <= pts; i++) {
    const t = i / pts;
    const caiRaw = 0.6 + (0.98 - 0.6) * t;
    const mfeRaw = -900 + (-620 - -900) * t;
    caiN.push((caiRaw - 0.55) / (1.0 - 0.55));
    mfeN.push((mfeRaw - -920) / (-600 - -920));
  }

  const W = 520;
  const H = 140;
  const P = 12;
  const x = (i: number) => P + (i / pts) * (W - 2 * P);
  const y = (n: number) => H - P - n * (H - 2 * P);

  const caiPath = caiN
    .map((v, i) => `${i === 0 ? "M" : "L"} ${x(i).toFixed(1)} ${y(v).toFixed(1)}`)
    .join(" ");
  const mfePath = mfeN
    .map((v, i) => `${i === 0 ? "M" : "L"} ${x(i).toFixed(1)} ${y(v).toFixed(1)}`)
    .join(" ");

  const markerIndex = Math.round(lambda * pts);
  const markerX = P + lambda * (W - 2 * P);

  return (
    <div>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "baseline",
          marginBottom: 10,
        }}
      >
        <div>
          <div
            style={{
              fontFamily: "var(--font-mono)",
              fontSize: 11,
              color: "var(--muted)",
              letterSpacing: "0.15em",
              textTransform: "uppercase",
              marginBottom: 2,
            }}
          >
            LinearDesign λ
          </div>
          <div style={{ fontSize: 14, color: "var(--ink-2)" }}>
            Codon optimality vs. RNA folding stability
          </div>
        </div>
        <div
          style={{
            fontFamily: "var(--font-mono)",
            fontSize: 13,
            color: "var(--accent-ink)",
            fontWeight: 600,
          }}
        >
          λ = {lambda.toFixed(2)}
        </div>
      </div>

      <svg
        viewBox={`0 0 ${W} ${H}`}
        style={{
          width: "100%",
          height: "auto",
          background: "var(--surface-sunk)",
          borderRadius: 10,
        }}
      >
        {[0.25, 0.5, 0.75].map((t) => (
          <line
            key={t}
            x1={x(pts * t)}
            y1={P}
            x2={x(pts * t)}
            y2={H - P}
            stroke="var(--line)"
            strokeDasharray="2 3"
          />
        ))}
        <path d={mfePath} fill="none" stroke="#0ea5e9" strokeWidth="2" opacity="0.85" />
        <path d={caiPath} fill="none" stroke="var(--accent)" strokeWidth="2" opacity="0.95" />
        <line
          x1={markerX}
          y1={P}
          x2={markerX}
          y2={H - P}
          stroke="var(--ink)"
          strokeWidth="1.5"
          opacity="0.5"
        />
        <circle
          cx={markerX}
          cy={y(caiN[markerIndex])}
          r="4.5"
          fill="var(--accent)"
          stroke="white"
          strokeWidth="1.5"
        />
        <circle
          cx={markerX}
          cy={y(mfeN[markerIndex])}
          r="4.5"
          fill="#0ea5e9"
          stroke="white"
          strokeWidth="1.5"
        />
        <text
          x={P + 4}
          y={H - 4}
          fontSize="10"
          fill="var(--muted-2)"
          fontFamily="var(--font-mono)"
          letterSpacing="0.08em"
        >
          STRUCTURE-STABLE
        </text>
        <text
          x={W - P - 4}
          y={H - 4}
          textAnchor="end"
          fontSize="10"
          fill="var(--muted-2)"
          fontFamily="var(--font-mono)"
          letterSpacing="0.08em"
        >
          FAST-TRANSLATION
        </text>
      </svg>

      <input
        type="range"
        min="0"
        max="1"
        step="0.01"
        value={lambda}
        onChange={(e) => onChange(parseFloat(e.target.value))}
        style={{ width: "100%", marginTop: 12, accentColor: "var(--accent)" }}
      />

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14, marginTop: 14 }}>
        <MetricPill
          color="var(--accent)"
          label="Codon fit (CAI)"
          value={metrics.cai.toFixed(2)}
          sub={metrics.cai > 0.85 ? "excellent" : metrics.cai > 0.7 ? "good" : "modest"}
        />
        <MetricPill
          color="#0ea5e9"
          label="Folding energy (MFE)"
          value={metrics.mfe.toLocaleString()}
          unit="kcal/mol"
          sub={metrics.mfe < -850 ? "very stable" : metrics.mfe < -750 ? "stable" : "moderate"}
        />
      </div>
    </div>
  );
}

function MetricPill({
  color,
  label,
  value,
  unit,
  sub,
}: {
  color: string;
  label: string;
  value: string;
  unit?: string;
  sub: string;
}) {
  return (
    <div
      style={{
        padding: "12px 14px",
        borderRadius: 12,
        background: "var(--surface-sunk)",
        border: "1px solid var(--line)",
        borderLeft: `3px solid ${color}`,
      }}
    >
      <div
        style={{
          fontFamily: "var(--font-mono)",
          fontSize: 10.5,
          color: "var(--muted)",
          letterSpacing: "0.14em",
          textTransform: "uppercase",
          marginBottom: 4,
        }}
      >
        {label}
      </div>
      <div style={{ display: "flex", gap: 6, alignItems: "baseline" }}>
        <span
          style={{
            fontFamily: "var(--font-display)",
            fontSize: 26,
            letterSpacing: "-0.02em",
          }}
        >
          {value}
        </span>
        {unit ? (
          <span
            style={{ fontSize: 11, color: "var(--muted)", fontFamily: "var(--font-mono)" }}
          >
            {unit}
          </span>
        ) : null}
      </div>
      <div style={{ fontSize: 11.5, color: "var(--muted-2)", marginTop: 2 }}>{sub}</div>
    </div>
  );
}
