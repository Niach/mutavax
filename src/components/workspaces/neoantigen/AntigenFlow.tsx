import { Card, Eyebrow } from "@/components/ui-kit";
import type { FunnelStep } from "@/lib/types";

export default function AntigenFlow({ steps }: { steps: FunnelStep[] }) {
  const max = Math.max(...steps.map((s) => s.count), 1);
  return (
    <Card>
      <div style={{ padding: "18px 22px 10px" }}>
        <Eyebrow>From mutation → neoantigen</Eyebrow>
        <h3
          style={{
            margin: "4px 0 0",
            fontFamily: "var(--font-display)",
            fontWeight: 500,
            fontSize: 20,
            letterSpacing: "-0.02em",
          }}
        >
          The funnel
        </h3>
      </div>
      <div
        style={{
          padding: "8px 22px 22px",
          display: "flex",
          flexDirection: "column",
          gap: 10,
        }}
      >
        {steps.map((s, i) => {
          const pct = (s.count / max) * 100;
          const isLast = i === steps.length - 1;
          return (
            <div key={i}>
              <div
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "baseline",
                  gap: 8,
                }}
              >
                <span style={{ fontSize: 13.5, color: "var(--ink-2)", fontWeight: 500 }}>
                  {s.label}
                </span>
                <span
                  style={{
                    fontFamily: "var(--font-display)",
                    fontSize: 22,
                    fontWeight: 400,
                    color: isLast ? "var(--accent-ink)" : "var(--ink)",
                    fontVariantNumeric: "tabular-nums",
                    letterSpacing: "-0.02em",
                  }}
                >
                  {s.count.toLocaleString()}
                </span>
              </div>
              <div
                style={{
                  marginTop: 4,
                  height: 10,
                  borderRadius: 999,
                  background: "var(--surface-sunk)",
                  overflow: "hidden",
                  border: "1px solid var(--line)",
                }}
              >
                <div
                  style={{
                    height: "100%",
                    width: `${pct}%`,
                    background: isLast
                      ? "linear-gradient(90deg, color-mix(in oklch, var(--accent) 60%, transparent), var(--accent))"
                      : "linear-gradient(90deg, #14b8a680, #14b8a6)",
                    transition: "width 400ms ease",
                  }}
                />
              </div>
              <div
                style={{
                  marginTop: 3,
                  fontFamily: "var(--font-mono)",
                  fontSize: 11,
                  color: "var(--muted-2)",
                  letterSpacing: "0.04em",
                }}
              >
                {s.hint}
              </div>
            </div>
          );
        })}
      </div>
    </Card>
  );
}
