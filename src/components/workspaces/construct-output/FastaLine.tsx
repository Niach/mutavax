"use client";

import type { ConstructOutputRun } from "@/lib/types";

import { RUN_COLORS } from "./colors";

interface FastaLineProps {
  start: number;
  text: string;
  runs: ConstructOutputRun[];
  charRun: number[];
}

export default function FastaLine({ start, text, runs, charRun }: FastaLineProps) {
  const segs: { runIdx: number; text: string }[] = [];
  let current: { runIdx: number; text: string } | null = null;
  for (let i = 0; i < text.length; i++) {
    const runIdx = charRun[start + i] ?? 0;
    if (!current || current.runIdx !== runIdx) {
      current = { runIdx, text: "" };
      segs.push(current);
    }
    current.text += text[i];
  }

  const endPos = Math.min(start + text.length, start + 60);

  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "58px 1fr auto",
        gap: 12,
        alignItems: "baseline",
      }}
    >
      <div
        style={{
          textAlign: "right",
          color: "var(--muted-2)",
          userSelect: "none",
          fontSize: 11.5,
        }}
      >
        {(start + 1).toString().padStart(4, " ")}
      </div>
      <div style={{ whiteSpace: "pre", overflowWrap: "anywhere" }}>
        {segs.map((s, i) => {
          const run = runs[s.runIdx];
          const color = RUN_COLORS[run?.kind ?? "linker"] ?? RUN_COLORS.linker;
          const grouped = s.text.match(/.{1,10}/g) ?? [s.text];
          return (
            <span
              key={i}
              title={run?.label}
              style={{
                background: color.bg,
                color: color.fg,
                padding: "2px 2px",
                borderRadius: 3,
                marginRight: 1,
                fontWeight: 500,
              }}
            >
              {grouped.join(" ")}
            </span>
          );
        })}
      </div>
      <div
        style={{
          color: "var(--muted-2)",
          fontSize: 11,
          userSelect: "none",
        }}
      >
        {endPos}
      </div>
    </div>
  );
}
