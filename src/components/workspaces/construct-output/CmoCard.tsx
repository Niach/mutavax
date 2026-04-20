"use client";

import { Btn, Card, MonoLabel, Spinner } from "@/components/ui-kit";
import type { CmoOption, ConstructOutputOrder } from "@/lib/types";

interface CmoCardProps {
  options: CmoOption[];
  selectedCmo: string | null;
  order: ConstructOutputOrder | null;
  released: boolean;
  submitting: boolean;
  onSelect: (cmoId: string) => void;
  onRelease: () => void;
}

export default function CmoCard({
  options,
  selectedCmo,
  order,
  released,
  submitting,
  onSelect,
  onRelease,
}: CmoCardProps) {
  const picked = options.find((o) => o.id === (selectedCmo ?? options[0]?.id));

  return (
    <Card style={{ display: "flex", flexDirection: "column", overflow: "hidden" }}>
      <div style={{ padding: "18px 20px 14px", borderBottom: "1px solid var(--line)" }}>
        <div style={{ marginBottom: 6 }}>
          <MonoLabel>For the manufacturer</MonoLabel>
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
          Send for synthesis
        </h3>
      </div>

      <div style={{ padding: "14px 18px 16px", flex: 1 }}>
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {options.map((o) => {
            const active = o.id === (selectedCmo ?? options[0]?.id);
            return (
              <button
                key={o.id}
                onClick={() => onSelect(o.id)}
                disabled={released || submitting}
                style={{
                  textAlign: "left",
                  padding: "12px 14px",
                  borderRadius: 12,
                  border: active
                    ? "1.5px solid var(--accent)"
                    : "1px solid var(--line)",
                  background: active
                    ? "color-mix(in oklch, var(--accent) 6%, var(--surface-strong))"
                    : "var(--surface-strong)",
                  cursor: released || submitting ? "default" : "pointer",
                  opacity: released && !active ? 0.6 : 1,
                  transition: "border-color 0.15s, background 0.15s",
                  fontFamily: "inherit",
                  color: "var(--ink)",
                }}
              >
                <div
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "baseline",
                    gap: 10,
                    flexWrap: "wrap",
                  }}
                >
                  <div style={{ fontSize: 13.5, fontWeight: 500, minWidth: 0 }}>
                    {o.name}
                  </div>
                  <div
                    style={{
                      fontFamily: "var(--font-mono)",
                      fontSize: 13,
                      color: active ? "var(--accent-ink)" : "var(--ink-2)",
                      fontWeight: 600,
                      flexShrink: 0,
                    }}
                  >
                    {o.cost}
                  </div>
                </div>
                <div
                  style={{
                    fontSize: 11,
                    color: "var(--muted)",
                    marginTop: 4,
                    display: "flex",
                    gap: 6,
                    fontFamily: "var(--font-mono)",
                    letterSpacing: "0.02em",
                    flexWrap: "wrap",
                  }}
                >
                  <span>{o.type}</span>
                  <span>·</span>
                  <span>{o.tat}</span>
                </div>
              </button>
            );
          })}
        </div>

        {picked ? (
          <div
            style={{
              marginTop: 12,
              padding: "10px 12px",
              borderRadius: 10,
              background: "var(--surface-sunk)",
              border: "1px solid var(--line)",
              fontSize: 12,
              color: "var(--muted)",
              lineHeight: 1.5,
            }}
          >
            <div
              style={{
                fontSize: 11,
                fontFamily: "var(--font-mono)",
                color: "var(--muted-2)",
                textTransform: "uppercase",
                letterSpacing: "0.12em",
                marginBottom: 4,
              }}
            >
              Why
            </div>
            {picked.good.join(" · ")}
          </div>
        ) : null}
      </div>

      <div style={{ padding: "0 18px 18px" }}>
        {released && order ? (
          <div
            style={{
              padding: "12px 14px",
              borderRadius: 12,
              background: "color-mix(in oklch, var(--accent) 10%, var(--surface-sunk))",
              border: "1px solid color-mix(in oklch, var(--accent) 35%, transparent)",
              fontSize: 13,
              color: "var(--ink-2)",
              lineHeight: 1.5,
            }}
          >
            <div
              style={{
                fontSize: 11,
                fontFamily: "var(--font-mono)",
                color: "var(--accent-ink)",
                textTransform: "uppercase",
                letterSpacing: "0.12em",
                marginBottom: 4,
                fontWeight: 600,
              }}
            >
              ✓ Ordered
            </div>
            PO #{order.poNumber} · ETA {picked?.tat} · {picked?.cost}
          </div>
        ) : (
          <Btn
            variant="primary"
            onClick={onRelease}
            disabled={submitting || !picked}
            style={{ width: "100%" }}
          >
            {submitting ? <Spinner /> : null}
            {submitting ? "Releasing…" : `Send ${picked?.name ?? ""}`}
          </Btn>
        )}
      </div>
    </Card>
  );
}
