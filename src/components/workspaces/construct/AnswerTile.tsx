"use client";

import { Card, MonoLabel } from "@/components/ui-kit";

interface AnswerTileProps {
  eyebrow: string;
  big: string;
  unit: string;
  sub?: string;
  line: string;
  good?: boolean;
}

export default function AnswerTile({ eyebrow, big, unit, sub, line, good }: AnswerTileProps) {
  return (
    <Card pad style={{ position: "relative" }}>
      {good ? (
        <div
          style={{
            position: "absolute",
            top: 16,
            right: 16,
            width: 22,
            height: 22,
            borderRadius: 999,
            background: "var(--accent)",
            color: "white",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            fontSize: 14,
            fontWeight: 700,
          }}
        >
          ✓
        </div>
      ) : null}
      <div style={{ marginBottom: 10 }}>
        <MonoLabel>{eyebrow}</MonoLabel>
      </div>
      <div style={{ display: "flex", alignItems: "baseline", gap: 8 }}>
        <span
          style={{
            fontFamily: "var(--font-display)",
            fontSize: 52,
            lineHeight: 1,
            letterSpacing: "-0.03em",
          }}
        >
          {big}
        </span>
        <span
          style={{
            fontSize: 15,
            color: "var(--muted)",
            fontFamily: "var(--font-mono)",
            letterSpacing: "0.05em",
          }}
        >
          {unit}
        </span>
      </div>
      {sub ? (
        <div
          style={{
            fontSize: 12,
            color: "var(--muted-2)",
            fontFamily: "var(--font-mono)",
            marginTop: 4,
            letterSpacing: "0.03em",
          }}
        >
          {sub}
        </div>
      ) : null}
      <p
        className="cs-tiny"
        style={{
          fontSize: 13.5,
          marginTop: 14,
          marginBottom: 0,
          color: "var(--ink-2)",
          lineHeight: 1.5,
        }}
      >
        {line}
      </p>
    </Card>
  );
}
