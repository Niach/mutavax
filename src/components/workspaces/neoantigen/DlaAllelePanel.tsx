import { useMemo, useState } from "react";

import { Btn, Card, Eyebrow } from "@/components/ui-kit";
import type { PatientAllele } from "@/lib/types";
import { CLASS_I_ACCENT, CLASS_II_ACCENT } from "./colors";

interface DlaAllelePanelProps {
  alleles: PatientAllele[];
  speciesLabel: string;
  editable: boolean;
  onChange: (next: PatientAllele[]) => void | Promise<void>;
}

export default function DlaAllelePanel({
  alleles,
  speciesLabel,
  editable,
  onChange,
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
        />
        <AlleleBlock
          title="Class II"
          items={classII}
          accent={CLASS_II_ACCENT}
          editing={editing}
          onRemove={removeAllele}
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

function AlleleBlock({
  title,
  items,
  accent,
  editing,
  onRemove,
}: {
  title: string;
  items: PatientAllele[];
  accent: string;
  editing: boolean;
  onRemove: (allele: string) => void;
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
        {items.map((a) => (
          <div
            key={a.allele}
            style={{
              display: "flex",
              alignItems: "center",
              gap: 10,
              padding: "8px 12px",
              borderRadius: 8,
              background: "var(--surface-sunk)",
              border: "1px solid var(--line)",
            }}
          >
            <span
              style={{
                flex: 1,
                fontFamily: "var(--font-mono)",
                fontSize: 13,
                color: "var(--ink-2)",
                fontWeight: 500,
              }}
            >
              {a.allele}
            </span>
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
        ))}
      </div>
    </div>
  );
}
