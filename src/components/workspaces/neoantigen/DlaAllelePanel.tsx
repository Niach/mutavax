import { useMemo, useState } from "react";

import { Btn, Card, Eyebrow } from "@/components/ui-kit";
import type { PatientAllele, RejectedAllele } from "@/lib/types";
import { CLASS_I_ACCENT, CLASS_II_ACCENT } from "./colors";

interface DlaAllelePanelProps {
  alleles: PatientAllele[];
  speciesLabel: string;
  editable: boolean;
  onChange: (next: PatientAllele[]) => void | Promise<void>;
  rejectedAlleles?: RejectedAllele[];
}

export default function DlaAllelePanel({
  alleles,
  speciesLabel,
  editable,
  onChange,
  rejectedAlleles,
}: DlaAllelePanelProps) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<PatientAllele[]>(alleles);
  const [newAllele, setNewAllele] = useState("");
  const [newClass, setNewClass] = useState<"I" | "II">("I");

  const classI = useMemo(
    () => (editing ? draft : alleles).filter((a) => a.class === "I"),
    [alleles, draft, editing],
  );
  const classII = useMemo(
    () => (editing ? draft : alleles).filter((a) => a.class === "II"),
    [alleles, draft, editing],
  );

  // Map allele name → skip reason. Hide rejection state while editing
  // so the row is visually editable; backend decides anew on next run.
  const rejectedByName = useMemo(() => {
    if (editing) return new Map<string, string>();
    const map = new Map<string, string>();
    for (const r of rejectedAlleles ?? []) {
      map.set(r.allele, r.reason);
    }
    return map;
  }, [rejectedAlleles, editing]);

  function startEditing() {
    setDraft(alleles);
    setEditing(true);
  }

  function cancelEditing() {
    setEditing(false);
    setDraft(alleles);
    setNewAllele("");
  }

  async function saveEditing() {
    await onChange(draft);
    setEditing(false);
    setNewAllele("");
  }

  function removeAllele(name: string) {
    setDraft((current) => current.filter((a) => a.allele !== name));
  }

  function addAllele() {
    const trimmed = newAllele.trim();
    if (!trimmed) return;
    if (draft.some((a) => a.allele === trimmed)) return;
    setDraft((current) => [
      ...current,
      {
        allele: trimmed,
        class: newClass,
        typing: "inferred",
        frequency: null,
        source: "Manually added",
      },
    ]);
    setNewAllele("");
  }

  return (
    <Card style={{ marginBottom: 18 }}>
      <div
        style={{
          padding: "18px 22px 10px",
          display: "flex",
          alignItems: "flex-start",
          justifyContent: "space-between",
          gap: 16,
          flexWrap: "wrap",
        }}
      >
        <div style={{ maxWidth: "64ch" }}>
          <Eyebrow>Patient MHC typing · {speciesLabel}</Eyebrow>
          <h3
            style={{
              margin: "4px 0 0",
              fontFamily: "var(--font-display)",
              fontWeight: 500,
              fontSize: 21,
              letterSpacing: "-0.02em",
            }}
          >
            {alleles.length} allele{alleles.length === 1 ? "" : "s"} — {classI.length} class I,{" "}
            {classII.length} class II
          </h3>
          <p
            style={{
              margin: "6px 0 0",
              fontSize: 13.5,
              color: "var(--muted)",
              lineHeight: 1.5,
            }}
          >
            Class I presents short peptides (8–11 aa) to killer T cells. Class II presents
            longer peptides (12–18 aa) to helper T cells. Both tracks matter for a vaccine
            response.
          </p>
        </div>
        {editable ? (
          editing ? (
            <div style={{ display: "flex", gap: 8 }}>
              <Btn variant="ghost" size="sm" onClick={cancelEditing}>
                Cancel
              </Btn>
              <Btn size="sm" onClick={() => void saveEditing()}>
                Save alleles
              </Btn>
            </div>
          ) : (
            <Btn variant="ghost" size="sm" onClick={startEditing}>
              Edit alleles
            </Btn>
          )
        ) : null}
      </div>
      <CoverageGapNote
        rejectedAlleles={rejectedAlleles}
        totalAlleles={alleles.length}
        editing={editing}
      />

      <div
        style={{
          padding: "0 22px 20px",
          display: "grid",
          gridTemplateColumns: "1fr 1fr",
          gap: 14,
        }}
      >
        <AlleleBlock
          title="Class I"
          items={classI}
          accent={CLASS_I_ACCENT}
          editing={editing}
          onRemove={removeAllele}
          rejectedByName={rejectedByName}
        />
        <AlleleBlock
          title="Class II"
          items={classII}
          accent={CLASS_II_ACCENT}
          editing={editing}
          onRemove={removeAllele}
          rejectedByName={rejectedByName}
        />
      </div>

      {editing ? (
        <div
          style={{
            padding: "0 22px 18px",
            display: "flex",
            alignItems: "center",
            gap: 8,
            flexWrap: "wrap",
          }}
        >
          <input
            type="text"
            value={newAllele}
            onChange={(e) => setNewAllele(e.target.value)}
            placeholder="e.g. DLA-88*034:01"
            style={{
              flex: "1 1 220px",
              minWidth: 220,
              padding: "8px 10px",
              borderRadius: 6,
              border: "1px solid var(--line)",
              background: "var(--surface-sunk)",
              fontFamily: "var(--font-mono)",
              fontSize: 13,
              color: "var(--ink)",
            }}
          />
          <select
            value={newClass}
            onChange={(e) => setNewClass(e.target.value as "I" | "II")}
            style={{
              padding: "8px 10px",
              borderRadius: 6,
              border: "1px solid var(--line)",
              background: "var(--surface-sunk)",
              fontFamily: "var(--font-mono)",
              fontSize: 13,
              color: "var(--ink)",
            }}
          >
            <option value="I">Class I</option>
            <option value="II">Class II</option>
          </select>
          <Btn variant="ghost" size="sm" onClick={addAllele}>
            Add allele
          </Btn>
        </div>
      ) : null}
    </Card>
  );
}

function CoverageGapNote({
  rejectedAlleles,
  totalAlleles,
  editing,
}: {
  rejectedAlleles?: RejectedAllele[];
  totalAlleles: number;
  editing: boolean;
}) {
  const rejected = rejectedAlleles ?? [];
  if (editing || rejected.length === 0) return null;

  const classI = rejected.filter((r) => r.mhcClass === "I");
  const classII = rejected.filter((r) => r.mhcClass === "II");
  const parts: string[] = [];
  if (classI.length > 0) {
    parts.push(
      `${classI.length} class I (${classI.map((r) => r.allele).join(", ")})`,
    );
  }
  if (classII.length > 0) {
    parts.push(
      `${classII.length} class II (${classII.map((r) => r.allele).join(", ")})`,
    );
  }

  return (
    <div
      style={{
        margin: "0 22px 16px",
        padding: "10px 14px",
        borderRadius: 10,
        background: "color-mix(in oklch, var(--warm) 8%, var(--surface-strong))",
        border: "1px solid color-mix(in oklch, var(--warm) 30%, var(--line))",
        display: "flex",
        gap: 10,
        alignItems: "flex-start",
      }}
    >
      <span
        aria-hidden
        style={{
          flexShrink: 0,
          marginTop: 2,
          width: 16,
          height: 16,
          borderRadius: 999,
          background: "color-mix(in oklch, var(--warm) 28%, transparent)",
          color: "var(--warm)",
          fontFamily: "var(--font-mono)",
          fontSize: 11,
          fontWeight: 700,
          display: "inline-flex",
          alignItems: "center",
          justifyContent: "center",
        }}
      >
        !
      </span>
      <div style={{ fontSize: 13, lineHeight: 1.55, color: "var(--ink-2)" }}>
        <strong style={{ color: "var(--ink)" }}>
          {rejected.length} of {totalAlleles} alleles skipped by the predictors.
        </strong>{" "}
        {parts.join(" · ")}. The IEDB-bundled NetMHCpan / NetMHCIIpan tables don&apos;t
        carry these names, so their peptides couldn&apos;t be scored and this run&apos;s
        coverage is reduced. Details per allele below.
      </div>
    </div>
  );
}

function AlleleBlock({
  title,
  items,
  accent,
  editing,
  onRemove,
  rejectedByName,
}: {
  title: string;
  items: PatientAllele[];
  accent: string;
  editing: boolean;
  onRemove: (allele: string) => void;
  rejectedByName: Map<string, string>;
}) {
  return (
    <div
      style={{
        padding: "14px 16px",
        borderRadius: "var(--radius-lg)",
        border: "1px solid var(--line)",
        background: "var(--surface-strong)",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 10 }}>
        <span
          style={{ width: 8, height: 8, borderRadius: 2, background: accent }}
        />
        <span
          style={{
            fontFamily: "var(--font-mono)",
            fontSize: 11,
            color: "var(--muted)",
            textTransform: "uppercase",
            letterSpacing: "0.14em",
            fontWeight: 600,
          }}
        >
          {title}
        </span>
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        {items.length === 0 ? (
          <p
            className="cs-tiny"
            style={{ margin: 0, color: "var(--muted-2)", fontStyle: "italic" }}
          >
            No alleles configured.
          </p>
        ) : null}
        {items.map((a) => {
          const skipReason = rejectedByName.get(a.allele);
          const skipped = Boolean(skipReason);
          return (
            <div
              key={a.allele}
              style={{
                display: "flex",
                flexDirection: "column",
                gap: 4,
                padding: "8px 12px",
                borderRadius: 8,
                background: "var(--surface-sunk)",
                border: "1px solid var(--line)",
                opacity: skipped ? 0.6 : 1,
              }}
            >
              <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                <span
                  style={{
                    flex: 1,
                    fontFamily: "var(--font-mono)",
                    fontSize: 13,
                    color: "var(--ink-2)",
                    fontWeight: 500,
                    textDecoration: skipped ? "line-through" : "none",
                  }}
                >
                  {a.allele}
                </span>
                {skipped ? (
                  <span
                    style={{
                      padding: "2px 8px",
                      borderRadius: 4,
                      background: "color-mix(in oklch, var(--danger) 12%, transparent)",
                      color: "var(--danger)",
                      border: "1px solid color-mix(in oklch, var(--danger) 42%, transparent)",
                      fontFamily: "var(--font-mono)",
                      fontSize: 10,
                      textTransform: "uppercase",
                      letterSpacing: "0.16em",
                      fontWeight: 700,
                    }}
                  >
                    Skipped
                  </span>
                ) : (
                  <span
                    style={{
                      padding: "2px 8px",
                      borderRadius: 4,
                      background:
                        a.typing === "typed"
                          ? "color-mix(in oklch, var(--accent) 16%, transparent)"
                          : "var(--surface-strong)",
                      color: a.typing === "typed" ? "var(--accent-ink)" : "var(--muted)",
                      border:
                        "1px solid " +
                        (a.typing === "typed"
                          ? "color-mix(in oklch, var(--accent) 38%, transparent)"
                          : "var(--line-strong)"),
                      fontFamily: "var(--font-mono)",
                      fontSize: 10,
                      textTransform: "uppercase",
                      letterSpacing: "0.16em",
                      fontWeight: 700,
                    }}
                  >
                    {a.typing}
                  </span>
                )}
                {typeof a.frequency === "number" ? (
                  <span
                    style={{
                      fontFamily: "var(--font-mono)",
                      fontSize: 11.5,
                      color: "var(--muted-2)",
                      fontVariantNumeric: "tabular-nums",
                      minWidth: 46,
                      textAlign: "right",
                    }}
                  >
                    {Math.round(a.frequency * 100)}% freq
                  </span>
                ) : null}
                {editing ? (
                  <button
                    onClick={() => onRemove(a.allele)}
                    aria-label={`Remove ${a.allele}`}
                    style={{
                      border: "none",
                      background: "transparent",
                      color: "var(--muted)",
                      cursor: "pointer",
                      fontSize: 14,
                      padding: 2,
                      lineHeight: 1,
                    }}
                  >
                    ×
                  </button>
                ) : null}
              </div>
              {skipped ? (
                <p
                  style={{
                    margin: 0,
                    fontSize: 11.5,
                    lineHeight: 1.4,
                    color: "var(--muted-2)",
                  }}
                >
                  {skipReason}
                </p>
              ) : null}
            </div>
          );
        })}
      </div>
    </div>
  );
}
