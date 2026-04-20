"use client";

import { Card, MonoLabel } from "@/components/ui-kit";
import type { DosingProtocol } from "@/lib/types";

interface VetCardProps {
  dosing: DosingProtocol;
}

export default function VetCard({ dosing }: VetCardProps) {
  return (
    <Card style={{ display: "flex", flexDirection: "column", overflow: "hidden" }}>
      <div style={{ padding: "18px 20px 14px", borderBottom: "1px solid var(--line)" }}>
        <div style={{ marginBottom: 6 }}>
          <MonoLabel>For the vet</MonoLabel>
        </div>
        <h3
          style={{
            margin: 0,
            fontFamily: "var(--font-display)",
            fontSize: 20,
            fontWeight: 500,
            letterSpacing: "-0.01em",
          }}
        >
          Dosing protocol
        </h3>
      </div>

      <div
        style={{
          padding: "14px 18px 16px",
          flex: 1,
          display: "flex",
          flexDirection: "column",
          gap: 12,
        }}
      >
        <div
          style={{
            padding: "10px 12px",
            borderRadius: 10,
            background: "var(--surface-sunk)",
            border: "1px solid var(--line)",
            display: "grid",
            gap: 4,
          }}
        >
          <DoseRow k="Formulation" v={dosing.formulation} />
          <DoseRow k="Route" v={dosing.route} />
          <DoseRow k="Dose" v={dosing.dose} />
        </div>

        <div>
          <div
            style={{
              fontSize: 11,
              fontFamily: "var(--font-mono)",
              color: "var(--muted-2)",
              textTransform: "uppercase",
              letterSpacing: "0.14em",
              marginBottom: 8,
            }}
          >
            Schedule
          </div>
          <div style={{ display: "flex", flexDirection: "column" }}>
            {dosing.schedule.map((s, i) => (
              <div
                key={i}
                style={{
                  display: "grid",
                  gridTemplateColumns: "72px 82px 1fr",
                  gap: 8,
                  padding: "6px 0",
                  borderBottom:
                    i < dosing.schedule.length - 1 ? "1px solid var(--line)" : "none",
                  fontSize: 12,
                  alignItems: "baseline",
                }}
              >
                <span
                  style={{
                    fontFamily: "var(--font-mono)",
                    color: "var(--muted)",
                    fontSize: 11,
                    letterSpacing: "0.04em",
                  }}
                >
                  {s.when}
                </span>
                <span style={{ fontWeight: 600, color: "var(--ink-2)" }}>
                  {s.label}
                </span>
                <span style={{ color: "var(--muted)", lineHeight: 1.4 }}>{s.what}</span>
              </div>
            ))}
          </div>
        </div>

        <div
          style={{
            padding: "10px 12px",
            borderRadius: 10,
            background: "color-mix(in oklch, var(--warm) 6%, var(--surface-sunk))",
            border: "1px solid color-mix(in oklch, var(--warm) 18%, var(--line))",
            fontSize: 12,
            color: "var(--ink-2)",
            lineHeight: 1.5,
          }}
        >
          <div
            style={{
              fontSize: 10.5,
              fontFamily: "var(--font-mono)",
              color: "var(--warm)",
              textTransform: "uppercase",
              letterSpacing: "0.14em",
              marginBottom: 6,
              fontWeight: 600,
            }}
          >
            Watch for
          </div>
          <ul style={{ margin: 0, paddingLeft: 14, display: "flex", flexDirection: "column", gap: 3 }}>
            {dosing.watchFor.map((w, i) => (
              <li key={i}>{w}</li>
            ))}
          </ul>
        </div>
      </div>
    </Card>
  );
}

function DoseRow({ k, v }: { k: string; v: string }) {
  return (
    <div style={{ display: "grid", gridTemplateColumns: "90px 1fr", gap: 10, fontSize: 12, lineHeight: 1.5 }}>
      <span
        style={{
          fontFamily: "var(--font-mono)",
          color: "var(--muted-2)",
          fontSize: 10.5,
          textTransform: "uppercase",
          letterSpacing: "0.1em",
          paddingTop: 2,
        }}
      >
        {k}
      </span>
      <span style={{ color: "var(--ink-2)" }}>{v}</span>
    </div>
  );
}
