"use client";

import { Btn, Card, MonoLabel, Spinner } from "@/components/ui-kit";

interface HandoffBarProps {
  fullMrnaNt: number;
  peptideCount: number;
  confirmed: boolean;
  submitting: boolean;
  onBack: () => void;
  onConfirm: () => void;
  onContinue: () => void;
}

export default function HandoffBar({
  fullMrnaNt,
  peptideCount,
  confirmed,
  submitting,
  onBack,
  onConfirm,
  onContinue,
}: HandoffBarProps) {
  return (
    <Card
      style={{
        background:
          "linear-gradient(135deg, color-mix(in oklch, var(--accent) 8%, var(--surface-strong)) 0%, var(--surface-strong) 70%)",
        border: "1px solid color-mix(in oklch, var(--accent) 30%, var(--line))",
      }}
    >
      <div
        style={{
          padding: "22px 26px",
          display: "grid",
          gridTemplateColumns: "1fr auto",
          gap: 24,
          alignItems: "center",
        }}
      >
        <div>
          <div style={{ marginBottom: 6 }}>
            <MonoLabel style={{ color: "var(--accent-ink)" }}>
              {confirmed ? "Locked in" : "Next step"}
            </MonoLabel>
          </div>
          <h3
            style={{
              margin: "0 0 4px",
              fontFamily: "var(--font-display)",
              fontWeight: 500,
              fontSize: 22,
              letterSpacing: "-0.015em",
            }}
          >
            {confirmed
              ? `Construct locked — ${fullMrnaNt.toLocaleString()} nt ready for output.`
              : `Hand off ${fullMrnaNt.toLocaleString()} nt to the manufacturer.`}
          </h3>
          <p
            className="cs-tiny"
            style={{ margin: 0, fontSize: 13.5, color: "var(--ink-2)" }}
          >
            Export a FASTA + GenBank bundle. {peptideCount} peptides · 1 molecule · ready
            for IVT synthesis. A CMO like Aldevron or TriLink turns this around in ≈10
            business days.
          </p>
        </div>
        <div style={{ display: "flex", gap: 10, flexShrink: 0, flexWrap: "wrap" }}>
          <Btn variant="ghost" onClick={onBack} disabled={submitting}>
            ← Back to epitopes
          </Btn>
          {confirmed ? (
            <Btn variant="primary" onClick={onContinue}>
              Continue to output →
            </Btn>
          ) : (
            <Btn variant="primary" onClick={onConfirm} disabled={submitting}>
              {submitting ? <Spinner /> : null}
              {submitting ? "Locking…" : "Confirm & hand off"}
            </Btn>
          )}
        </div>
      </div>
    </Card>
  );
}
