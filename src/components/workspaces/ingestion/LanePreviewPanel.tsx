import { useMemo, useState } from "react";
import { ChevronRight, LoaderCircle } from "lucide-react";

import type { SampleLane } from "@/lib/types";
import { cn } from "@/lib/utils";

import {
  InstrumentTraceRow,
  PreviewLegend,
  SampledReadoutStrip,
  deriveLaneInsight,
} from "./ReadPreviewCard";
import { INITIAL_VISIBLE_READS, type PreviewState } from "./lane-utils";

export function LanePreviewPanel({
  lane,
  previewState,
  onRetry,
  showLegend,
}: {
  lane: SampleLane;
  previewState: PreviewState;
  onRetry: () => void;
  showLegend: boolean;
}) {
  const [pairedToggle, setPairedToggle] = useState<"R1" | "R2">("R1");
  const [showAll, setShowAll] = useState(false);
  const [showReads, setShowReads] = useState(false);

  const preview = previewState.data;
  const isPaired = preview?.readLayout === "paired";
  const activePair: "R1" | "R2" | "SE" = isPaired ? pairedToggle : "SE";

  const activeReads =
    activePair === "R1"
      ? preview?.reads.R1 ?? []
      : activePair === "R2"
        ? preview?.reads.R2 ?? []
        : preview?.reads.SE ?? [];
  const mateReads =
    activePair === "R1"
      ? preview?.reads.R2 ?? []
      : activePair === "R2"
        ? preview?.reads.R1 ?? []
        : [];

  const insight = useMemo(() => {
    if (!preview) {
      return deriveLaneInsight([]);
    }
    return deriveLaneInsight([
      ...(preview.reads.R1 ?? []),
      ...(preview.reads.R2 ?? []),
      ...(preview.reads.SE ?? []),
    ]);
  }, [preview]);

  const visibleReads = showAll
    ? activeReads
    : activeReads.slice(0, INITIAL_VISIBLE_READS);
  const hiddenCount = Math.max(0, activeReads.length - visibleReads.length);

  return (
    <div
      data-testid={`${lane}-preview-panel`}
      data-phase={previewState.phase}
      className="rounded-xl border border-stone-200 bg-stone-50/40 px-4 py-3"
    >
      <div className="flex items-center justify-between gap-3">
        <div className="font-mono text-[10px] uppercase tracking-[0.2em] text-stone-500">
          Sample preview
        </div>
        {previewState.phase === "ready" && preview ? (
          <div className="font-mono text-[10px] tracking-[0.16em] text-stone-400">
            {preview.stats.sampledReadCount} reads sampled
          </div>
        ) : null}
      </div>

      {previewState.phase === "loading" ? (
        <div className="mt-3 flex items-center gap-2 text-[13px] text-stone-600">
          <LoaderCircle className="size-3.5 animate-spin" />
          Reading the files…
        </div>
      ) : null}

      {previewState.phase === "failed" ? (
        <div className="mt-3 flex flex-wrap items-center gap-3 text-[13px] text-rose-700">
          <span>{previewState.error ?? "Unable to load the preview."}</span>
          <button
            type="button"
            onClick={onRetry}
            className="text-xs font-medium text-stone-500 underline-offset-2 transition hover:text-stone-900 hover:underline focus-visible:outline-none"
          >
            Retry
          </button>
        </div>
      ) : null}

      {previewState.phase === "ready" && preview ? (
        <div className="mt-3 space-y-3">
          <SampledReadoutStrip
            sampledReadCount={preview.stats.sampledReadCount}
            averageReadLength={preview.stats.averageReadLength}
            sampledGcPercent={preview.stats.sampledGcPercent}
            insight={insight}
          />

          <button
            type="button"
            onClick={() => setShowReads((value) => !value)}
            aria-expanded={showReads}
            className="flex items-center gap-1.5 text-[11px] font-medium text-stone-500 transition hover:text-stone-800 focus-visible:outline-none"
          >
            <ChevronRight
              className={cn(
                "size-3 transition-transform duration-200 motion-reduce:transition-none",
                showReads && "rotate-90"
              )}
            />
            {showReads ? "Hide sample reads" : "Show sample reads"}
          </button>

          {showReads ? (
            <div className="space-y-4 border-t border-stone-200 pt-3">
              {showLegend ? <PreviewLegend /> : null}

              <div className="flex flex-wrap items-baseline justify-between gap-3">
                {isPaired ? (
                  <PairToggle
                    value={pairedToggle}
                    onChange={(next) => {
                      setPairedToggle(next);
                      setShowAll(false);
                    }}
                  />
                ) : (
                  <span className="font-mono text-[10px] uppercase tracking-[0.22em] text-stone-500">
                    SE
                  </span>
                )}

                <span className="font-mono text-[10px] uppercase tracking-[0.18em] text-stone-400">
                  {activeReads.length === 0
                    ? "No reads sampled"
                    : showAll || hiddenCount === 0
                      ? `${activeReads.length} shown`
                      : `${visibleReads.length} of ${activeReads.length} shown`}
                </span>
              </div>

              <div className="space-y-4">
                {visibleReads.map((read, index) => (
                  <InstrumentTraceRow
                    key={`${activePair}-${read.header}-${index}`}
                    read={read}
                    mate={mateReads[index]}
                    index={index}
                  />
                ))}
              </div>

              <div className="flex flex-wrap items-center gap-3">
                {hiddenCount > 0 ? (
                  <button
                    type="button"
                    onClick={() => setShowAll(true)}
                    className="font-mono text-[10px] uppercase tracking-[0.18em] text-stone-500 transition hover:text-stone-900 focus-visible:outline-none"
                  >
                    Show {hiddenCount} more reads
                  </button>
                ) : null}

                {showAll && activeReads.length > INITIAL_VISIBLE_READS ? (
                  <button
                    type="button"
                    onClick={() => setShowAll(false)}
                    className="font-mono text-[10px] uppercase tracking-[0.18em] text-stone-500 transition hover:text-stone-900 focus-visible:outline-none"
                  >
                    Collapse
                  </button>
                ) : null}
              </div>
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

function PairToggle({
  value,
  onChange,
}: {
  value: "R1" | "R2";
  onChange: (next: "R1" | "R2") => void;
}) {
  return (
    <div className="inline-flex rounded-full border border-stone-200 bg-white p-0.5">
      {(["R1", "R2"] as const).map((pair) => (
        <button
          key={pair}
          type="button"
          onClick={() => onChange(pair)}
          className={cn(
            "rounded-full px-2.5 py-0.5 font-mono text-[10px] uppercase tracking-[0.18em] transition focus-visible:outline-none",
            value === pair
              ? "bg-stone-900 text-white"
              : "text-stone-500 hover:text-stone-800"
          )}
        >
          {pair}
        </button>
      ))}
    </div>
  );
}
