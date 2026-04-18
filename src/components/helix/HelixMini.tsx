interface HelixMiniProps {
  size?: number;
  hue?: number;
}

export default function HelixMini({ size = 20, hue = 152 }: HelixMiniProps) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 40 40"
      style={{ display: "inline-block", verticalAlign: "-5px" }}
    >
      {Array.from({ length: 12 }, (_, i) => {
        // Round to 3 decimals so SSR and CSR serialize the same string for
        // SVG attributes — raw floats produce trailing-digit hydration
        // mismatches across Node and V8.
        const round = (n: number) => Math.round(n * 1000) / 1000;
        const y = round((i + 0.5) * (40 / 12));
        const t = i / 11;
        const phase = t * Math.PI * 2.2;
        const x1 = round(20 + Math.cos(phase) * 12);
        const x2 = round(20 - Math.cos(phase) * 12);
        return (
          <g key={i}>
            <line
              x1={x1}
              y1={y}
              x2={x2}
              y2={y}
              stroke={`oklch(0.7 0.07 ${hue})`}
              strokeWidth="0.8"
              opacity="0.45"
            />
            <circle cx={x1} cy={y} r="2" fill={`oklch(0.72 0.14 ${hue})`} />
            <circle cx={x2} cy={y} r="2" fill={`oklch(0.68 0.1 ${(hue + 180) % 360})`} />
          </g>
        );
      })}
    </svg>
  );
}
