"use client";

import { Card, MonoLabel } from "@/components/ui-kit";
import type { AuditEntry } from "@/lib/types";

interface AuditCardProps {
  trail: AuditEntry[];
  onExport: () => void;
}

export default function AuditCard({ trail, onExport }: AuditCardProps) {
  return (
    <Card style={{ display: "flex", flexDirection: "column", overflow: "hidden" }}>
      <div style={{ padding: "18px 20px 14px", borderBottom: "1px solid var(--line)" }}>
        <div style={{ marginBottom: 6 }}>
          <MonoLabel>For the record</MonoLabel>
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
          Decision trail
        </h3>
        <p className="cs-tiny" style={{ margin: "4px 0 0", fontSize: 12 }}>
          Every call made, by whom, and when. Export-ready for USDA APHIS review.
        </p>
      </div>

      <div
        style={{
          padding: "10px 16px 14px",
          flex: 1,
          maxHeight: 420,
          overflowY: "auto",
          fontSize: 12,
        }}
      >
        {trail.map((e, i) => (
          <div
            key={i}
            style={{
              display: "grid",
              gridTemplateColumns: "26px 1fr",
              gap: 8,
              padding: "8px 0",
              borderBottom: i < trail.length - 1 ? "1px solid var(--line)" : "none",
              alignItems: "flex-start",
            }}
          >
            <div
              style={{
                width: 22,
                height: 22,
                borderRadius: 6,
                background:
                  e.kind === "human"
                    ? "color-mix(in oklch, var(--accent) 16%, transparent)"
                    : "var(--surface-sunk)",
                color: e.kind === "human" ? "var(--accent-ink)" : "var(--muted)",
                fontFamily: "var(--font-mono)",
                fontSize: 10,
                fontWeight: 600,
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                border: "1px solid var(--line)",
              }}
            >
              {e.stage}
            </div>
            <div>
              <div style={{ color: "var(--ink-2)", lineHeight: 1.45 }}>{e.what}</div>
              <div
                style={{
                  fontSize: 10.5,
                  color: "var(--muted-2)",
                  fontFamily: "var(--font-mono)",
                  marginTop: 2,
                  letterSpacing: "0.02em",
                }}
              >
                {e.when} · {e.who}
              </div>
            </div>
          </div>
        ))}
      </div>

      <div style={{ padding: "0 18px 18px" }}>
        <button
          onClick={onExport}
          style={{
            width: "100%",
            padding: "10px 0",
            borderRadius: 10,
            border: "1px solid var(--line-strong)",
            background: "var(--surface-sunk)",
            fontFamily: "var(--font-mono)",
            fontSize: 11.5,
            letterSpacing: "0.12em",
            textTransform: "uppercase",
            color: "var(--ink-2)",
            cursor: "pointer",
            fontWeight: 600,
          }}
        >
          ↓ Export audit bundle
        </button>
      </div>
    </Card>
  );
}
