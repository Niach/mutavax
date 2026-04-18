"use client";

import { useMemo, useState } from "react";

import { Card, Eyebrow, MonoLabel } from "@/components/ui-kit";
import type {
  AnnotationImpactTier,
  GeneFocus,
  ProteinDomain,
} from "@/lib/types";
import { getProteinDomainPreset } from "./proteinDomainPresets";

interface GeneLollipopProps {
  focus: GeneFocus;
}

const IMPACT_COLOR: Record<AnnotationImpactTier, { fill: string; label: string }> = {
  HIGH: { fill: "#e11d48", label: "high impact" },
  MODERATE: { fill: "#d97706", label: "moderate impact" },
  LOW: { fill: "#0284c7", label: "low impact" },
  MODIFIER: { fill: "#78716c", label: "modifier" },
};

const IMPACT_STICK: Record<AnnotationImpactTier, number> = {
  HIGH: 82,
  MODERATE: 58,
  LOW: 38,
  MODIFIER: 24,
};

const DOMAIN_NEUTRAL_FILL = "#a8a29e";
const DOMAIN_CATALYTIC_FILL =
  "color-mix(in oklch, var(--accent) 55%, #a8a29e)";

function domainFill(domain: ProteinDomain): string {
  return domain.kind === "catalytic"
    ? DOMAIN_CATALYTIC_FILL
    : DOMAIN_NEUTRAL_FILL;
}

export default function GeneLollipop({ focus }: GeneLollipopProps) {
  const [hover, setHover] = useState<number | null>(null);

  const preset = useMemo(
    () => getProteinDomainPreset(focus.symbol),
    [focus.symbol],
  );

  const variants = focus.variants.filter(
    (v) => v.proteinPosition != null && v.proteinPosition > 0,
  );

  const variantMaxPos = variants.reduce(
    (acc, v) => Math.max(acc, v.proteinPosition ?? 0),
    0,
  );
  const presetMaxDomain = preset
    ? preset.domains.reduce((acc, d) => Math.max(acc, d.end), 0)
    : 0;
  const vepLength = focus.proteinLength ?? 0;
  const explicitLength = vepLength > 0 ? vepLength : preset?.proteinLength ?? 0;
  const length =
    explicitLength > 0 && explicitLength >= variantMaxPos
      ? explicitLength
      : Math.max(variantMaxPos * 1.1, presetMaxDomain, 100);
  const inferredLength = explicitLength === 0 || explicitLength < variantMaxPos;
  const domains: ProteinDomain[] =
    focus.domains && focus.domains.length > 0
      ? focus.domains
      : preset?.domains ?? [];
  const role =
    focus.role && focus.role.trim().length > 0
      ? focus.role
      : preset?.role ?? null;

  if (!variants.length) return null;

  const W = 900;
  const H = 260;
  const PX = 46;
  const TRACK_Y = H - 72;
  const trackXStart = PX - 4;
  const trackWidth = W - (PX - 4) * 2;

  return (
    <Card style={{ marginBottom: 16 }}>
      <div
        style={{
          padding: "18px 22px 10px",
          display: "flex",
          alignItems: "baseline",
          justifyContent: "space-between",
          gap: 12,
          flexWrap: "wrap",
        }}
      >
        <div>
          <Eyebrow>Mutation map</Eyebrow>
          <h3
            style={{
              margin: "4px 0 0",
              fontFamily: "var(--font-display)",
              fontWeight: 500,
              fontSize: 22,
              letterSpacing: "-0.02em",
              color: "var(--ink)",
            }}
          >
            <span style={{ fontWeight: 600, letterSpacing: "0.02em" }}>
              {focus.symbol}
            </span>{" "}
            <span style={{ color: "var(--muted-2)" }}>·</span>{" "}
            <span
              style={{
                color: "var(--muted)",
                fontSize: 16,
                fontWeight: 400,
              }}
            >
              {variants.length} mutation{variants.length === 1 ? "" : "s"} along the protein
            </span>
          </h3>
          {role ? (
            <div style={{ marginTop: 6, fontSize: 13.5, color: "var(--muted)" }}>
              Role: <span style={{ color: "var(--ink-2)" }}>{role}</span>
              {domains.length > 0 ? (
                <span
                  style={{
                    marginLeft: 12,
                    fontFamily: "var(--font-mono)",
                    fontSize: 11.5,
                    color: "var(--muted-2)",
                    letterSpacing: "0.08em",
                  }}
                >
                  Click cancer-gene cards above to swap
                </span>
              ) : null}
            </div>
          ) : null}
        </div>
        <div style={{ textAlign: "right", minWidth: 110 }}>
          <MonoLabel style={{ fontSize: 11, whiteSpace: "nowrap" }}>
            protein length
          </MonoLabel>
          <div
            style={{
              marginTop: 4,
              fontFamily: "var(--font-mono)",
              fontSize: 14,
              color: "var(--ink-2)",
              fontVariantNumeric: "tabular-nums",
            }}
          >
            {Math.round(length)} aa
            {inferredLength ? (
              <span
                style={{
                  marginLeft: 4,
                  fontSize: 11,
                  color: "var(--muted-2)",
                }}
              >
                (approx)
              </span>
            ) : null}
          </div>
        </div>
      </div>

      <div style={{ position: "relative", padding: "0 12px 18px" }}>
        <svg
          viewBox={`0 0 ${W} ${H}`}
          style={{ width: "100%", height: "auto", display: "block" }}
        >
          <defs>
            <linearGradient id="cs-lolli-track" x1="0" x2="1">
              <stop
                offset="0%"
                stopColor="color-mix(in oklch, var(--ink) 22%, transparent)"
              />
              <stop
                offset="100%"
                stopColor="color-mix(in oklch, var(--ink) 8%, transparent)"
              />
            </linearGradient>
          </defs>

          <rect
            x={trackXStart}
            y={TRACK_Y - 8}
            rx={8}
            ry={8}
            width={trackWidth}
            height={16}
            fill="var(--surface-sunk)"
          />
          <rect
            x={trackXStart}
            y={TRACK_Y - 8}
            rx={8}
            ry={8}
            width={trackWidth}
            height={16}
            fill="url(#cs-lolli-track)"
            opacity={0.6}
          />

          {domains.map((domain, idx) => {
            const startX = PX + (domain.start / length) * (W - PX * 2);
            const endX = PX + (domain.end / length) * (W - PX * 2);
            const bandWidth = Math.max(endX - startX, 6);
            const fill = domainFill(domain);
            const showLabel = bandWidth > 58;
            return (
              <g key={`${domain.label}-${idx}`}>
                <rect
                  x={startX}
                  y={TRACK_Y - 10}
                  rx={6}
                  ry={6}
                  width={bandWidth}
                  height={20}
                  fill={fill}
                  opacity={0.88}
                />
                {showLabel ? (
                  <text
                    x={startX + bandWidth / 2}
                    y={TRACK_Y + 4}
                    textAnchor="middle"
                    fill="#fff"
                    fontFamily="var(--font-mono)"
                    fontSize={10}
                    fontWeight={600}
                    letterSpacing="0.06em"
                    style={{ pointerEvents: "none" }}
                  >
                    {domain.label}
                  </text>
                ) : null}
                <title>{`${domain.label} · ${domain.start}–${domain.end} aa`}</title>
              </g>
            );
          })}

          {[0, 0.25, 0.5, 0.75, 1].map((pct, i) => {
            const x = PX + pct * (W - PX * 2);
            return (
              <g key={i}>
                <line
                  x1={x}
                  x2={x}
                  y1={TRACK_Y + 14}
                  y2={TRACK_Y + 22}
                  stroke="var(--line-strong)"
                  strokeWidth={1}
                />
                <text
                  x={x}
                  y={TRACK_Y + 40}
                  textAnchor="middle"
                  fill="var(--muted-2)"
                  fontFamily="var(--font-mono)"
                  fontSize={11}
                  style={{ fontVariantNumeric: "tabular-nums" }}
                >
                  {Math.round(pct * length)}
                </text>
              </g>
            );
          })}

          <text
            x={PX - 12}
            y={TRACK_Y + 4}
            textAnchor="end"
            fill="var(--muted)"
            fontFamily="var(--font-mono)"
            fontSize={12}
            fontWeight={600}
          >
            N
          </text>
          <text
            x={W - PX + 12}
            y={TRACK_Y + 4}
            textAnchor="start"
            fill="var(--muted)"
            fontFamily="var(--font-mono)"
            fontSize={12}
            fontWeight={600}
          >
            C
          </text>

          {variants.map((v, i) => {
            const pos = v.proteinPosition ?? 0;
            const x = PX + (pos / length) * (W - PX * 2);
            const stick = IMPACT_STICK[v.impact] ?? 30;
            const topY = TRACK_Y - stick;
            const color = IMPACT_COLOR[v.impact].fill;
            const isHover = hover === i;
            const r = isHover ? 9 : 7;
            return (
              <g
                key={i}
                onMouseEnter={() => setHover(i)}
                onMouseLeave={() => setHover(null)}
                style={{ cursor: "pointer" }}
              >
                <line
                  x1={x}
                  x2={x}
                  y1={TRACK_Y - 8}
                  y2={topY}
                  stroke={color}
                  strokeWidth={isHover ? 2.5 : 1.75}
                  opacity={0.75}
                />
                <circle cx={x} cy={topY} r={r + 3} fill={color} opacity={0.15} />
                <circle
                  cx={x}
                  cy={topY}
                  r={r}
                  fill={color}
                  stroke="var(--surface-strong)"
                  strokeWidth={2}
                />
                {isHover && v.hgvsp ? (
                  <text
                    x={x}
                    y={topY - 14}
                    textAnchor="middle"
                    fill="var(--ink)"
                    fontFamily="var(--font-mono)"
                    fontSize={11}
                    fontWeight={600}
                  >
                    {v.hgvsp}
                  </text>
                ) : null}
              </g>
            );
          })}
        </svg>

        {hover != null && variants[hover] ? (
          <div
            style={{
              position: "absolute",
              top: 10,
              right: 20,
              padding: "10px 14px",
              borderRadius: 10,
              background: "var(--surface-strong)",
              border: "1px solid var(--line-strong)",
              boxShadow: "0 12px 32px -12px rgba(0,0,0,0.15)",
              fontSize: 12.5,
              minWidth: 180,
            }}
          >
            <MonoLabel style={{ fontSize: 10.5 }}>
              position {variants[hover].proteinPosition}
            </MonoLabel>
            <div
              style={{
                marginTop: 4,
                fontFamily: "var(--font-mono)",
                fontSize: 13.5,
                color: "var(--ink)",
                fontWeight: 500,
              }}
            >
              {variants[hover].hgvsp ?? "—"}
            </div>
            <div
              style={{ marginTop: 3, fontSize: 12, color: "var(--muted)" }}
            >
              {IMPACT_COLOR[variants[hover].impact].label}
              {variants[hover].tumorVaf != null
                ? ` · ${(variants[hover].tumorVaf * 100).toFixed(1)}% VAF`
                : ""}
            </div>
          </div>
        ) : null}
      </div>

      <div
        style={{
          padding: "10px 22px 18px",
          display: "flex",
          gap: 18,
          flexWrap: "wrap",
          borderTop: "1px solid var(--line)",
        }}
      >
        {(["HIGH", "MODERATE", "LOW", "MODIFIER"] as AnnotationImpactTier[]).map(
          (tier) => (
            <div
              key={tier}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 8,
                whiteSpace: "nowrap",
              }}
            >
              <span
                style={{
                  width: 10,
                  height: 10,
                  borderRadius: 999,
                  background: IMPACT_COLOR[tier].fill,
                  boxShadow: `0 0 10px ${IMPACT_COLOR[tier].fill}40`,
                }}
              />
              <span
                style={{
                  fontFamily: "var(--font-mono)",
                  fontSize: 11.5,
                  color: "var(--muted)",
                  textTransform: "lowercase",
                  letterSpacing: "0.08em",
                }}
              >
                {tier.toLowerCase()}
              </span>
            </div>
          )
        )}
      </div>
    </Card>
  );
}
