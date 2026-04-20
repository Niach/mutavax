"use client";

import type { ChromosomeMetricsEntry, TopVariantEntry } from "@/lib/types";

interface KaryogramProps {
  chromosomes: ChromosomeMetricsEntry[];
  topVariants: TopVariantEntry[];
  referenceLabel?: string | null;
}

function hashStr(s: string) {
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}

function densityDots(track: ChromosomeMetricsEntry) {
  const cap = Math.min(140, Math.max(6, Math.round(Math.sqrt(track.total) * 7)));
  let s = hashStr(track.chromosome);
  const rnd = () => {
    s = (s + 0x6d2b79f5) | 0;
    let t = Math.imul(s ^ (s >>> 15), 1 | s);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
  const passShare = track.total > 0 ? track.passCount / track.total : 0;
  const snvShare = track.total > 0 ? track.snvCount / track.total : 1;
  const out: Array<{ cx: number; r: number; fill: string; opacity: number }> = [];
  for (let i = 0; i < cap; i++) {
    const cx = rnd();
    const isPass = rnd() < passShare;
    const isSnv = rnd() < snvShare;
    const r = isPass ? 1.1 + rnd() * 0.8 : 0.8 + rnd() * 0.5;
    const opacity = isPass ? 0.55 + rnd() * 0.3 : 0.25 + rnd() * 0.15;
    const fill = isPass ? (isSnv ? "#34d399" : "#38bdf8") : "#f59e0b";
    out.push({ cx, r, fill, opacity });
  }
  return out;
}

function isCanonicalChromosome(name: string) {
  const stripped = name.toLowerCase().startsWith("chr") ? name.slice(3) : name;
  if (/^\d+$/.test(stripped)) return true;
  return ["x", "y", "m", "mt"].includes(stripped.toLowerCase());
}

export default function Karyogram({
  chromosomes,
  topVariants,
  referenceLabel,
}: KaryogramProps) {
  const canonical = chromosomes.filter((c) => isCanonicalChromosome(c.chromosome));
  const tracks = canonical.length ? canonical : chromosomes;
  if (!tracks.length) return null;

  const TRACK_H = 12;
  const SPACING = 5;
  const LABEL_W = 44;
  const RIGHT_G = 58;
  const PAD_Y = 20;
  const W = 960;
  const trackInner = W - LABEL_W - RIGHT_G;
  const H = PAD_Y * 2 + tracks.length * (TRACK_H + SPACING);
  const maxLen = Math.max(...tracks.map((c) => c.length || 1));

  const varsByChrom = new Map<string, TopVariantEntry[]>();
  for (const v of topVariants) {
    const arr = varsByChrom.get(v.chromosome) ?? [];
    arr.push(v);
    varsByChrom.set(v.chromosome, arr);
  }

  const totalVariants = chromosomes.reduce((a, c) => a + c.total, 0);
  const passCount = chromosomes.reduce((a, c) => a + c.passCount, 0);
  const hiddenContigCount = chromosomes.length - tracks.length;
  const hiddenVariantCount = chromosomes
    .filter((c) => !isCanonicalChromosome(c.chromosome))
    .reduce((a, c) => a + c.total, 0);

  return (
    <div className="cs-karyo">
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "flex-end",
          marginBottom: 18,
          flexWrap: "wrap",
          gap: 12,
        }}
      >
        <div>
          <div
            style={{
              fontFamily: "var(--font-mono)",
              fontSize: 10,
              textTransform: "uppercase",
              letterSpacing: "0.3em",
              color: "rgba(110, 231, 183, 0.7)",
            }}
          >
            Somatic karyogram
            {referenceLabel ? ` · ${referenceLabel}` : null}
          </div>
          <div
            style={{
              fontFamily: "var(--font-display)",
              fontSize: 30,
              fontWeight: 300,
              color: "#f0f5fa",
              marginTop: 6,
              letterSpacing: "-0.01em",
              lineHeight: 1,
            }}
          >
            {totalVariants.toLocaleString()}
            <span
              style={{
                marginLeft: 10,
                fontSize: 14,
                color: "#8b9bac",
                fontWeight: 400,
              }}
            >
              variant calls
            </span>
          </div>
          <div style={{ fontSize: 12, color: "#7a8899", marginTop: 4 }}>
            <span style={{ color: "#6ee7b7" }}>
              {passCount.toLocaleString()} PASS
            </span>
            <span style={{ margin: "0 10px", color: "#38455c" }}>·</span>
            {(totalVariants - passCount).toLocaleString()} filtered
          </div>
        </div>
        <div
          style={{
            display: "flex",
            gap: 16,
            fontSize: 10,
            textTransform: "uppercase",
            letterSpacing: "0.18em",
            color: "#8b9bac",
            fontFamily: "var(--font-mono)",
          }}
        >
          <Legend color="#34d399" glow>
            PASS SNV
          </Legend>
          <Legend color="#38bdf8" glow>
            PASS indel
          </Legend>
          <Legend color="#fbbf24">Filtered</Legend>
        </div>
      </div>

      <svg viewBox={`0 0 ${W} ${H}`} style={{ width: "100%" }}>
        <defs>
          <linearGradient id="cs-karyo-lane" x1="0" x2="1" y1="0" y2="0">
            <stop offset="0" stopColor="#1f2a44" stopOpacity="0.9" />
            <stop offset="1" stopColor="#253355" stopOpacity="0.6" />
          </linearGradient>
        </defs>
        {tracks.map((t, i) => {
          const y = PAD_Y + i * (TRACK_H + SPACING);
          const w = ((t.length || 1) / maxLen) * trackInner;
          const cy = y + TRACK_H / 2;
          const dots = densityDots(t);
          const tops = (varsByChrom.get(t.chromosome) ?? []).slice(0, 14);
          return (
            <g key={t.chromosome}>
              <text
                x={LABEL_W - 10}
                y={cy + 3}
                textAnchor="end"
                fill="#8b9bac"
                fontFamily="var(--font-mono)"
                fontSize="9"
                letterSpacing="0.14em"
              >
                {t.chromosome}
              </text>
              <rect
                x={LABEL_W}
                y={y}
                width={w}
                height={TRACK_H}
                rx={TRACK_H / 2}
                fill="url(#cs-karyo-lane)"
                stroke="rgba(148,163,184,0.12)"
                strokeWidth="0.6"
              />
              {dots.map((d, j) => (
                <circle
                  key={j}
                  cx={LABEL_W + d.cx * w}
                  cy={cy}
                  r={d.r}
                  fill={d.fill}
                  opacity={d.opacity}
                />
              ))}
              {tops.map((v, j) => {
                const relative = Math.min(
                  1,
                  Math.max(0, v.position / (t.length || 1))
                );
                const cx = LABEL_W + relative * w;
                const isIndel = v.variantType !== "snv";
                const fill = v.isPass
                  ? isIndel
                    ? "#7dd3fc"
                    : "#6ee7b7"
                  : "#fbbf24";
                const vafVal = v.tumorVaf ?? 0.2;
                const r = v.isPass ? 2.4 + vafVal * 2.2 : 1.6;
                return (
                  <g key={j}>
                    <circle cx={cx} cy={cy} r={r + 3} fill={fill} opacity={0.25} />
                    <circle
                      cx={cx}
                      cy={cy}
                      r={r}
                      fill={fill}
                      opacity={v.isPass ? 0.95 : 0.6}
                    />
                  </g>
                );
              })}
              <text
                x={LABEL_W + w + 8}
                y={cy + 3}
                fill="#58677a"
                fontFamily="var(--font-mono)"
                fontSize="9"
                letterSpacing="0.1em"
              >
                {t.total > 0 ? t.total : "—"}
              </text>
            </g>
          );
        })}
      </svg>

      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          marginTop: 14,
          fontSize: 11,
          color: "#58677a",
        }}
      >
        <span
          style={{
            fontFamily: "var(--font-mono)",
            textTransform: "uppercase",
            letterSpacing: "0.22em",
          }}
        >
          Chromosome length →
        </span>
        <span style={{ fontFamily: "var(--font-mono)", letterSpacing: "0.14em" }}>
          1px ≈ {Math.round(maxLen / trackInner).toLocaleString()} bp
        </span>
      </div>
      {hiddenContigCount > 0 ? (
        <div
          style={{
            marginTop: 8,
            fontSize: 11,
            color: "#58677a",
            fontFamily: "var(--font-mono)",
            letterSpacing: "0.12em",
          }}
        >
          + {hiddenVariantCount.toLocaleString()} on{" "}
          {hiddenContigCount.toLocaleString()} unplaced contigs (not shown)
        </div>
      ) : null}
    </div>
  );
}

function Legend({
  color,
  glow,
  children,
}: {
  color: string;
  glow?: boolean;
  children: React.ReactNode;
}) {
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 6,
        whiteSpace: "nowrap",
      }}
    >
      <span
        style={{
          display: "inline-block",
          width: 6,
          height: 6,
          borderRadius: 999,
          background: color,
          boxShadow: glow ? `0 0 10px ${color}` : "none",
        }}
      />
      <span>{children}</span>
    </span>
  );
}
