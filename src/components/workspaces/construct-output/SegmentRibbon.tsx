"use client";

import type { ConstructOutputRun } from "@/lib/types";

import { RUN_COLORS } from "./colors";

interface SegmentRibbonProps {
  runs: ConstructOutputRun[];
  totalNt: number;
}

export default function SegmentRibbon({ runs, totalNt }: SegmentRibbonProps) {
  return (
    <div style={{ padding: "0 26px 18px" }}>
      <div
        style={{
          display: "flex",
          height: 14,
          borderRadius: 7,
          overflow: "hidden",
          border: "1px solid var(--line)",
        }}
      >
        {runs.map((r, i) => {
          const color = RUN_COLORS[r.kind] ?? RUN_COLORS.linker;
          return (
            <div
              key={i}
              title={`${r.label} · ${r.nt.length} nt`}
              style={{
                width: totalNt > 0 ? `${(r.nt.length / totalNt) * 100}%` : "0%",
                background: color.bg,
                borderRight: i < runs.length - 1 ? "1px solid white" : "none",
              }}
            />
          );
        })}
      </div>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          fontFamily: "var(--font-mono)",
          fontSize: 10,
          color: "var(--muted-2)",
          letterSpacing: "0.05em",
          marginTop: 4,
        }}
      >
        <span>1</span>
        <span>{totalNt.toLocaleString()} nt</span>
      </div>
    </div>
  );
}
