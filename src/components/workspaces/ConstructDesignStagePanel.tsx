"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";

import { Btn, Callout, Card, CardHead, Chip } from "@/components/ui-kit";
import AnswerTile from "@/components/workspaces/construct/AnswerTile";
import CodonSwapPreview from "@/components/workspaces/construct/CodonSwapPreview";
import FlankToggles from "@/components/workspaces/construct/FlankToggles";
import HandoffBar from "@/components/workspaces/construct/HandoffBar";
import LambdaSlider from "@/components/workspaces/construct/LambdaSlider";
import ManufacturingChecklist from "@/components/workspaces/construct/ManufacturingChecklist";
import MoleculeHero from "@/components/workspaces/construct/MoleculeHero";
import { api } from "@/lib/api";
import type {
  ConstructDesignOptions,
  ConstructStageSummary,
  Workspace,
} from "@/lib/types";

const OPTIONS_DEBOUNCE_MS = 400;

interface ConstructDesignStagePanelProps {
  workspace: Workspace;
  initialSummary: ConstructStageSummary;
  onSummaryChange?: (summary: ConstructStageSummary) => void;
}

export default function ConstructDesignStagePanel({
  workspace,
  initialSummary,
  onSummaryChange,
}: ConstructDesignStagePanelProps) {
  const router = useRouter();
  const [summary, setSummary] = useState(initialSummary);
  const [options, setOptions] = useState<ConstructDesignOptions>(
    initialSummary.options
  );
  const [submitting, setSubmitting] = useState(false);

  const pushSummary = useCallback(
    (next: ConstructStageSummary) => {
      setSummary(next);
      setOptions(next.options);
      onSummaryChange?.(next);
    },
    [onSummaryChange]
  );

  const persistedRef = useRef<string>(serializeOptions(initialSummary.options));
  useEffect(() => {
    if (summary.status === "blocked") return;
    const key = serializeOptions(options);
    if (key === persistedRef.current) return;
    const handle = setTimeout(() => {
      persistedRef.current = key;
      api
        .updateConstructOptions(workspace.id, {
          lambda: options.lambda,
          signal: options.signal,
          mitd: options.mitd,
          confirmed: options.confirmed,
        })
        .then(pushSummary)
        .catch(() => {
          // Reconciled on next GET.
        });
    }, OPTIONS_DEBOUNCE_MS);
    return () => clearTimeout(handle);
  }, [options, workspace.id, pushSummary, summary.status]);

  const setLambda = useCallback((value: number) => {
    setOptions((prev) => ({ ...prev, lambda: value }));
  }, []);
  const setSignal = useCallback((value: boolean) => {
    setOptions((prev) => ({ ...prev, signal: value }));
  }, []);
  const setMitd = useCallback((value: boolean) => {
    setOptions((prev) => ({ ...prev, mitd: value }));
  }, []);

  const handleConfirm = useCallback(async () => {
    setSubmitting(true);
    try {
      const next = await api.updateConstructOptions(workspace.id, {
        lambda: options.lambda,
        signal: options.signal,
        mitd: options.mitd,
        confirmed: true,
      });
      persistedRef.current = serializeOptions(next.options);
      pushSummary(next);
    } finally {
      setSubmitting(false);
    }
  }, [workspace.id, options, pushSummary]);

  const goToOutput = useCallback(() => {
    router.push(`/workspaces/${workspace.id}/construct-output`);
  }, [router, workspace.id]);

  const goBack = useCallback(() => {
    router.push(`/workspaces/${workspace.id}/epitope-selection`);
  }, [router, workspace.id]);

  const header = (
    <div className="cs-view-head">
      <div>
        <div className="cs-crumb">
          {workspace.displayName} / 07 mRNA construct design
        </div>
        <h1 style={{ textWrap: "pretty", margin: "4px 0 0" }}>
          Build the molecule the lab will actually make.
        </h1>
        <p
          style={{
            maxWidth: "62ch",
            marginTop: 12,
            fontSize: 16.5,
            lineHeight: 1.6,
            color: "var(--ink-2)",
          }}
        >
          You picked {summary.peptideCount} peptides. Now we wrap them with the parts every
          mRNA vaccine needs — a signal peptide, linkers, a trafficking tail, UTRs, a
          poly(A) tail — and pick a DNA sequence the ribosome will read efficiently and the
          factory can synthesize.
        </p>
      </div>
      <div style={{ textAlign: "right", minWidth: 200 }}>
        <Chip kind={summary.status === "confirmed" ? "live" : "scaffold"}>
          Stage 07 · {summary.status === "confirmed" ? "Confirmed" : "Live"}
        </Chip>
        <div
          style={{
            marginTop: 8,
            fontSize: 12.5,
            fontFamily: "var(--font-mono)",
            color: "var(--muted)",
            letterSpacing: "0.08em",
            whiteSpace: "nowrap",
          }}
        >
          LinearDesign · DNAchisel · ViennaRNA
        </div>
      </div>
    </div>
  );

  if (summary.status === "blocked") {
    return (
      <>
        {header}
        <Callout tone="warm" style={{ marginTop: 12 }}>
          <div>
            <strong>Finish epitope selection first.</strong>
            <p
              style={{ margin: "6px 0 0", fontSize: 14, color: "var(--ink-2)" }}
            >
              {summary.blockingReason ??
                "Lock the epitope shortlist before designing the construct."}
            </p>
            <div style={{ marginTop: 10 }}>
              <Link href={`/workspaces/${workspace.id}/epitope-selection`}>
                <Btn variant="primary" size="sm">
                  Go to epitope selection
                </Btn>
              </Link>
            </div>
          </div>
        </Callout>
      </>
    );
  }

  const constructId = `${slug(workspace.displayName) || workspace.id.slice(0, 8)}-MCT-001`;

  return (
    <>
      {header}

      <MoleculeHero
        segments={summary.segments}
        aaSeq={summary.aaSeq}
        flanks={summary.flanks}
        constructId={constructId}
      />

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(3, minmax(0, 1fr))",
          gap: 16,
          marginTop: 22,
        }}
      >
        <AnswerTile
          eyebrow="What's in it"
          big={String(summary.peptideCount)}
          unit="peptides"
          line={`${
            summary.segments.filter((s) => s.kind === "peptide").length
          } tumor peptides stitched with ${options.signal ? "signal, " : ""}${
            options.mitd ? "trafficking tail, " : ""
          }linkers and UTRs.`}
        />
        <AnswerTile
          eyebrow="How stable it will be"
          big={summary.metrics.cai.toFixed(2)}
          unit="CAI"
          sub={`${summary.metrics.mfe.toLocaleString()} kcal/mol folding energy`}
          line={
            options.lambda > 0.75
              ? "Tuned for translation speed — ribosomes will rip through it."
              : options.lambda < 0.35
                ? "Tuned for structure — folds tight, resists degradation."
                : "Balanced — reads fast and folds stably."
          }
        />
        <AnswerTile
          eyebrow="Will the factory make it"
          big={`${summary.manufacturingChecks.filter((c) => c.status === "pass").length}/${summary.manufacturingChecks.length}`}
          unit="checks"
          sub={`${summary.metrics.fullMrnaNt.toLocaleString()} nt — fits in a single IVT run`}
          line="No restriction-enzyme sites, no bad GC windows, no repeats. Ready to synthesize."
          good={summary.manufacturingChecks.every((c) => c.status === "pass")}
        />
      </div>

      <section style={{ marginTop: 28 }}>
        <Card>
          <CardHead
            eyebrow="Design choices"
            title="What the codon-optimizer is trading off"
            subtitle={
              <>
                For the same protein there are 10<sup>100+</sup> DNA sequences. LinearDesign
                picks one that balances translation efficiency against RNA folding
                stability.
              </>
            }
          />
          <div
            style={{
              padding: 22,
              display: "grid",
              gridTemplateColumns: "minmax(0, 1.4fr) minmax(0, 1fr)",
              gap: 28,
            }}
          >
            <LambdaSlider
              lambda={options.lambda}
              onChange={setLambda}
              metrics={summary.metrics}
            />
            <FlankToggles
              useSignal={options.signal}
              useMitd={options.mitd}
              onSignalChange={setSignal}
              onMitdChange={setMitd}
            />
          </div>
        </Card>
      </section>

      <section style={{ marginTop: 22 }}>
        <CodonSwapPreview preview={summary.preview} />
      </section>

      <section style={{ marginTop: 22 }}>
        <ManufacturingChecklist checks={summary.manufacturingChecks} />
      </section>

      <section style={{ marginTop: 28, marginBottom: 12 }}>
        <HandoffBar
          fullMrnaNt={summary.metrics.fullMrnaNt}
          peptideCount={summary.peptideCount}
          confirmed={summary.status === "confirmed"}
          submitting={submitting}
          onBack={goBack}
          onConfirm={handleConfirm}
          onContinue={goToOutput}
        />
      </section>
    </>
  );
}

function serializeOptions(options: ConstructDesignOptions): string {
  return `${options.lambda.toFixed(2)}|${options.signal ? 1 : 0}|${
    options.mitd ? 1 : 0
  }|${options.confirmed ? 1 : 0}`;
}

function slug(name: string): string {
  const cleaned = name
    .trim()
    .replace(/[^A-Za-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
  return cleaned.charAt(0).toUpperCase() + cleaned.slice(1);
}
