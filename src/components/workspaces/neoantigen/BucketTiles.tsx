import type { BindingBucket } from "@/lib/types";
import { BUCKET_COLOR } from "./colors";

export default function BucketTiles({ buckets }: { buckets: BindingBucket[] }) {
  const total = buckets.reduce((sum, b) => sum + b.count, 0) || 1;
  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "repeat(4, 1fr)",
        gap: 12,
        marginBottom: 18,
      }}
    >
      {buckets.map((b) => {
        const pct = Math.round((b.count / total) * 100);
        const col = BUCKET_COLOR[b.key];
        return (
          <div
            key={b.key}
            style={{
              position: "relative",
              borderRadius: "var(--radius-lg)",
              border: "1px solid var(--line)",
              background: "var(--surface-strong)",
              padding: "16px 18px",
              overflow: "hidden",
            }}
          >
            <div
              style={{
                fontFamily: "var(--font-mono)",
                fontSize: 11,
                fontWeight: 600,
                textTransform: "uppercase",
                letterSpacing: "0.22em",
                color: col.fill,
              }}
            >
              {col.label}
            </div>
            <div
              style={{
                marginTop: 6,
                display: "flex",
                alignItems: "baseline",
                gap: 10,
              }}
            >
              <div
                style={{
                  fontFamily: "var(--font-display)",
                  fontSize: 38,
                  fontWeight: 400,
                  letterSpacing: "-0.03em",
                  lineHeight: 1,
                  color: "var(--ink)",
                  fontVariantNumeric: "tabular-nums",
                }}
              >
                {b.count.toLocaleString()}
              </div>
              <span
                style={{
                  fontFamily: "var(--font-mono)",
                  fontSize: 12,
                  color: col.fill,
                  fontWeight: 600,
                }}
              >
                {pct}%
              </span>
            </div>
            <div
              style={{
                marginTop: 10,
                fontSize: 13.5,
                fontWeight: 500,
                color: "var(--ink)",
              }}
            >
              {b.plain}
            </div>
            <div
              style={{
                marginTop: 4,
                fontFamily: "var(--font-mono)",
                fontSize: 11.5,
                color: "var(--muted-2)",
                letterSpacing: "0.06em",
              }}
            >
              IC50 {b.threshold}
            </div>
            <div
              style={{
                marginTop: 12,
                height: 5,
                borderRadius: 999,
                background: "var(--surface-sunk)",
                overflow: "hidden",
              }}
            >
              <div
                style={{
                  height: "100%",
                  width: `${Math.max(pct, 2)}%`,
                  background: `linear-gradient(90deg, ${col.fill}80, ${col.fill})`,
                }}
              />
            </div>
          </div>
        );
      })}
    </div>
  );
}
