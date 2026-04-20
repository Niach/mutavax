"use client";

import { Card, CardHead } from "@/components/ui-kit";
import type { ConstructManufacturingCheck } from "@/lib/types";

interface ManufacturingChecklistProps {
  checks: ConstructManufacturingCheck[];
}

export default function ManufacturingChecklist({ checks }: ManufacturingChecklistProps) {
  const allPass = checks.every((c) => c.status === "pass");
  return (
    <Card>
      <CardHead
        eyebrow="Factory floor checks"
        title="The manufacturer's synthesis rules — all met"
        subtitle="DNAchisel sweeps the sequence for anything that would break DNA synthesis, Gibson assembly, or in-vitro transcription. Problems here mean a failed batch at the CMO."
        right={
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 8,
              padding: "6px 12px",
              background: allPass
                ? "color-mix(in oklch, var(--accent) 14%, transparent)"
                : "color-mix(in oklch, var(--warm) 16%, transparent)",
              color: allPass ? "var(--accent-ink)" : "var(--warm)",
              borderRadius: 999,
              fontSize: 12,
              fontFamily: "var(--font-mono)",
              fontWeight: 600,
              letterSpacing: "0.08em",
              whiteSpace: "nowrap",
            }}
          >
            <span
              style={{
                width: 8,
                height: 8,
                borderRadius: 999,
                background: allPass ? "var(--accent)" : "var(--warm)",
              }}
            />
            {allPass ? "SYNTHESIS-READY" : "NEEDS REVIEW"}
          </div>
        }
      />

      <div
        style={{
          padding: "18px 22px",
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))",
          gap: 10,
        }}
      >
        {checks.map((c) => {
          const pass = c.status === "pass";
          return (
            <div
              key={c.id}
              style={{
                display: "grid",
                gridTemplateColumns: "auto 1fr",
                gap: 12,
                alignItems: "flex-start",
                padding: "10px 12px",
                borderRadius: 10,
                background: "var(--surface-sunk)",
                border: "1px solid var(--line)",
              }}
            >
              <div
                style={{
                  width: 20,
                  height: 20,
                  borderRadius: 999,
                  background: pass ? "var(--accent)" : "var(--warm)",
                  color: "white",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  fontSize: 12,
                  fontWeight: 700,
                  marginTop: 1,
                  flexShrink: 0,
                }}
              >
                {pass ? "✓" : "!"}
              </div>
              <div>
                <div style={{ fontSize: 13.5, fontWeight: 500, color: "var(--ink-2)" }}>
                  {c.label}
                </div>
                <div
                  style={{
                    fontSize: 11.5,
                    color: "var(--muted)",
                    marginTop: 1,
                    lineHeight: 1.4,
                  }}
                >
                  {c.why}
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </Card>
  );
}
