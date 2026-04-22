"use client";

import { Card, Eyebrow } from "@/components/ui-kit";
import type { AnnotationConsequenceEntry } from "@/lib/types";

interface ConsequenceDonutProps {
  entries: AnnotationConsequenceEntry[];
  showRawTerms?: boolean;
}

const PALETTE = [
  "#059669",
  "#0284c7",
  "#d97706",
  "#7c3aed",
  "#db2777",
  "#0d9488",
  "#b91c1c",
  "#4338ca",
];

export default function ConsequenceDonut({ entries }: ConsequenceDonutProps) {
  if (!entries.length) return null;

  const total = entries.reduce((a, e) => a + e.count, 0);
  if (total <= 0) return null;

  const size = 180;
  const r = size / 2 - 12;
  const ri = r * 0.62;
  const cx = size / 2;
  const cy = size / 2;

  const slices = entries.reduce<
    Array<{
      e: AnnotationConsequenceEntry;
      pct: number;
      s: number;
      end: number;
      color: string;
    }>
  >((acc, e, i) => {
    const pct = e.count / total;
    const s = acc.length > 0 ? acc[acc.length - 1].end : 0;
    acc.push({ e, pct, s, end: s + pct, color: PALETTE[i % PALETTE.length] });
    return acc;
  }, []);

  const pct2xy = (R: number, pct: number) => {
    const a = pct * Math.PI * 2 - Math.PI / 2;
    return { x: cx + R * Math.cos(a), y: cy + R * Math.sin(a) };
  };

  const slicePath = (sl: (typeof slices)[number]) => {
    const a = pct2xy(r, sl.s);
    const b = pct2xy(r, sl.end);
    const c = pct2xy(ri, sl.end);
    const d = pct2xy(ri, sl.s);
    const large = sl.end - sl.s > 0.5 ? 1 : 0;
    return `M ${a.x} ${a.y} A ${r} ${r} 0 ${large} 1 ${b.x} ${b.y} L ${c.x} ${c.y} A ${ri} ${ri} 0 ${large} 0 ${d.x} ${d.y} Z`;
  };

  return (
    <Card>
      <div style={{ padding: "18px 22px 8px" }}>
        <Eyebrow>What changed</Eyebrow>
        <h3
          style={{
            margin: "4px 0 0",
            fontFamily: "var(--font-display)",
            fontWeight: 500,
            fontSize: 20,
            letterSpacing: "-0.02em",
            color: "var(--ink)",
          }}
        >
          Mutation consequence mix
        </h3>
      </div>
      <div
        style={{
          padding: "10px 22px 20px",
          display: "grid",
          gridTemplateColumns: "180px 1fr",
          gap: 18,
          alignItems: "center",
        }}
      >
        <svg
          viewBox={`0 0 ${size} ${size}`}
          style={{ width: 180, height: 180 }}
        >
          {slices.map((sl, i) => (
            <path key={i} d={slicePath(sl)} fill={sl.color} opacity={0.92} />
          ))}
          <circle cx={cx} cy={cy} r={ri - 2} fill="var(--surface-strong)" />
          <text
            x={cx}
            y={cy - 4}
            textAnchor="middle"
            fill="var(--muted)"
            fontFamily="var(--font-mono)"
            fontSize={10.5}
            letterSpacing="0.2em"
          >
            TOTAL
          </text>
          <text
            x={cx}
            y={cy + 18}
            textAnchor="middle"
            fill="var(--ink)"
            fontFamily="var(--font-display)"
            fontSize={26}
            fontWeight={500}
          >
            {total.toLocaleString()}
          </text>
        </svg>
        <ul
          style={{
            margin: 0,
            padding: 0,
            listStyle: "none",
            display: "flex",
            flexDirection: "column",
            gap: 6,
            maxHeight: 220,
            overflowY: "auto",
            paddingRight: 6,
          }}
        >
          {slices.map((sl, i) => (
            <li
              key={i}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 10,
                fontSize: 13,
              }}
            >
              <span
                style={{
                  width: 10,
                  height: 10,
                  borderRadius: 3,
                  background: sl.color,
                  flexShrink: 0,
                }}
              />
              <span
                style={{
                  flex: 1,
                  color: "var(--ink-2)",
                  minWidth: 0,
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                  whiteSpace: "nowrap",
                }}
                title={sl.e.term}
              >
                {sl.e.label}
              </span>
              <span
                style={{
                  fontFamily: "var(--font-mono)",
                  fontSize: 12,
                  color: "var(--muted)",
                  fontVariantNumeric: "tabular-nums",
                  whiteSpace: "nowrap",
                }}
              >
                {sl.e.count}
                <span style={{ color: "var(--muted-2)", marginLeft: 6 }}>
                  {Math.round(sl.pct * 100)}%
                </span>
              </span>
            </li>
          ))}
        </ul>
      </div>
    </Card>
  );
}
