import { Card, Eyebrow } from "@/components/ui-kit";
import type { TopCandidate } from "@/lib/types";
import { CLASS_I_ACCENT, CLASS_II_ACCENT } from "./colors";

const W = 560;
const H = 320;
const PX = 58;
const PY = 40;

function xScale(ic50: number) {
  const lo = Math.log10(10);
  const hi = Math.log10(5000);
  const v = Math.log10(Math.max(ic50, 10));
  const t = Math.min(Math.max((v - lo) / (hi - lo), 0), 1);
  return PX + (1 - t) * (W - PX - 30);
}

function yScale(tpm: number) {
  const lo = Math.log10(1);
  const hi = Math.log10(200);
  const v = Math.log10(Math.max(tpm, 1));
  const t = Math.min(Math.max((v - lo) / (hi - lo), 0), 1);
  return H - PY - t * (H - PY - 24);
}

function rScale(vaf: number) {
  return 6 + vaf * 16;
}

export default function RankingScatter({ peptides }: { peptides: TopCandidate[] }) {
  const plotted = peptides.filter(
    (p) => typeof p.tpm === "number" && typeof p.vaf === "number",
  );

  return (
    <Card>
      <div style={{ padding: "18px 22px 10px" }}>
        <Eyebrow>Candidate ranking</Eyebrow>
        <h3
          style={{
            margin: "4px 0 0",
            fontFamily: "var(--font-display)",
            fontWeight: 500,
            fontSize: 20,
            letterSpacing: "-0.02em",
          }}
        >
          Tight binding × high expression × high VAF
        </h3>
        <p
          style={{
            margin: "6px 0 0",
            fontSize: 13,
            color: "var(--muted)",
            lineHeight: 1.5,
            maxWidth: "52ch",
          }}
        >
          The best candidates bind tightly, come from a gene the tumor expresses a lot, and
          are present in most tumor cells.
        </p>
      </div>

      <div style={{ padding: "6px 12px 14px" }}>
        {plotted.length === 0 ? (
          <p
            className="cs-tiny"
            style={{ margin: 18, color: "var(--muted)", fontStyle: "italic" }}
          >
            Gene-expression data (TPM) isn&apos;t available for these candidates yet. Add
            tumor RNA-seq input to plot this view.
          </p>
        ) : (
          <svg viewBox={`0 0 ${W} ${H}`} style={{ width: "100%", height: "auto" }}>
            <line
              x1={PX}
              x2={W - 12}
              y1={H - PY}
              y2={H - PY}
              stroke="var(--line-strong)"
              strokeWidth={1}
            />
            <line
              x1={PX}
              x2={PX}
              y1={16}
              y2={H - PY}
              stroke="var(--line-strong)"
              strokeWidth={1}
            />

            {[10, 50, 500, 5000].map((v) => (
              <g key={v}>
                <line
                  x1={xScale(v)}
                  x2={xScale(v)}
                  y1={H - PY}
                  y2={H - PY + 5}
                  stroke="var(--line-strong)"
                />
                <text
                  x={xScale(v)}
                  y={H - PY + 20}
                  textAnchor="middle"
                  fill="var(--muted-2)"
                  fontFamily="var(--font-mono)"
                  fontSize={11}
                >
                  {v < 1000 ? v : v / 1000 + "k"}
                </text>
              </g>
            ))}
            <text
              x={PX + (W - PX) / 2}
              y={H - 8}
              textAnchor="middle"
              fill="var(--muted)"
              fontFamily="var(--font-mono)"
              fontSize={11}
              style={{ letterSpacing: "0.06em" }}
            >
              ← tighter · IC50 (nM) · weaker →
            </text>

            {[1, 10, 50, 200].map((v) => (
              <g key={v}>
                <line
                  x1={PX - 5}
                  x2={PX}
                  y1={yScale(v)}
                  y2={yScale(v)}
                  stroke="var(--line-strong)"
                />
                <text
                  x={PX - 8}
                  y={yScale(v) + 3}
                  textAnchor="end"
                  fill="var(--muted-2)"
                  fontFamily="var(--font-mono)"
                  fontSize={11}
                >
                  {v}
                </text>
              </g>
            ))}
            <text
              x={14}
              y={16 + (H - PY - 16) / 2}
              textAnchor="middle"
              fill="var(--muted)"
              fontFamily="var(--font-mono)"
              fontSize={11}
              transform={`rotate(-90 14 ${16 + (H - PY - 16) / 2})`}
              style={{ letterSpacing: "0.06em" }}
            >
              expression (TPM)
            </text>

            <rect
              x={xScale(50)}
              y={16}
              width={W - 12 - xScale(50)}
              height={H - PY - 16}
              fill={CLASS_I_ACCENT}
              opacity={0.06}
            />
            <text
              x={xScale(50) + 8}
              y={30}
              fill={CLASS_I_ACCENT}
              fontFamily="var(--font-mono)"
              fontSize={10}
              fontWeight={600}
              letterSpacing="0.16em"
            >
              STRONG-BINDER ZONE
            </text>

            {plotted.map((p, i) => {
              const tpm = p.tpm ?? 1;
              const vaf = p.vaf ?? 0;
              const x = xScale(p.ic50);
              const y = yScale(tpm);
              const r = rScale(vaf);
              const col = p.class === "I" ? CLASS_I_ACCENT : CLASS_II_ACCENT;
              return (
                <g key={`${p.seq}-${i}`}>
                  <circle cx={x} cy={y} r={r + 3} fill={col} opacity={0.15} />
                  <circle
                    cx={x}
                    cy={y}
                    r={r}
                    fill={col}
                    stroke="var(--surface-strong)"
                    strokeWidth={1.5}
                    opacity={0.9}
                  />
                  <text
                    x={x}
                    y={y - r - 4}
                    textAnchor="middle"
                    fill="var(--ink)"
                    fontFamily="var(--font-display)"
                    fontWeight={600}
                    fontSize={11}
                  >
                    {p.gene}
                  </text>
                </g>
              );
            })}

            <g transform={`translate(${W - 156}, 20)`}>
              <rect
                x={-8}
                y={-14}
                width={148}
                height={62}
                rx={6}
                fill="var(--surface-strong)"
                stroke="var(--line)"
              />
              <circle cx={6} cy={2} r={5} fill={CLASS_I_ACCENT} />
              <text
                x={18}
                y={5}
                fill="var(--ink-2)"
                fontFamily="var(--font-mono)"
                fontSize={11}
              >
                Class I
              </text>
              <circle cx={6} cy={20} r={5} fill={CLASS_II_ACCENT} />
              <text
                x={18}
                y={23}
                fill="var(--ink-2)"
                fontFamily="var(--font-mono)"
                fontSize={11}
              >
                Class II
              </text>
              <text
                x={-2}
                y={40}
                fill="var(--muted)"
                fontFamily="var(--font-mono)"
                fontSize={9.5}
                letterSpacing="0.08em"
              >
                bubble size = VAF
              </text>
            </g>
          </svg>
        )}
      </div>
    </Card>
  );
}
