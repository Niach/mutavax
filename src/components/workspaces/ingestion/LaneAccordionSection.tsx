import { AlertTriangle, ArrowRight, Check, ChevronDown, FolderOpen, LoaderCircle } from "lucide-react";

import { Button } from "@/components/ui/button";
import type { SampleLane, Workspace, WorkspaceFile } from "@/lib/types";
import { formatBytes } from "@/lib/workspace-utils";
import { cn } from "@/lib/utils";

import { LanePreviewPanel } from "./LanePreviewPanel";
import { LaneProgressCard } from "./LaneProgressCard";
import { SourceFileCard } from "./SourceFileCard";
import {
  totalBytes,
  type PreviewState,
} from "./lane-utils";

type LaneSummary = Workspace["ingestion"]["lanes"]["tumor"];

interface LaneAccordionSectionProps {
  lane: SampleLane;
  stepIndex: number;
  workspace: Workspace;
  summary: LaneSummary;
  files: WorkspaceFile[];
  isExpanded: boolean;
  onHeaderClick: () => void;
  onPickFiles: () => void;
  onContinue?: () => void;
  isSubmitting: boolean;
  laneError: string | null;
  previewState: PreviewState;
  onRetryPreview: () => void;
  desktopAvailable: boolean;
  showLegend: boolean;
}

const LANE_TITLES: Record<SampleLane, string> = {
  normal: "Healthy sample",
  tumor: "Tumor sample",
};

const LANE_HINTS: Record<SampleLane, string> = {
  normal: "Reference draw from healthy tissue (e.g. blood).",
  tumor: "Sequencing reads from the tumor biopsy.",
};

const FILE_HINT =
  "Pick the two FASTQ files for this sample — usually named with _R1 and _R2 and ending in .fastq.gz.";

export function LaneAccordionSection({
  lane,
  stepIndex,
  summary,
  files,
  isExpanded,
  onHeaderClick,
  onPickFiles,
  onContinue,
  isSubmitting,
  laneError,
  previewState,
  onRetryPreview,
  desktopAvailable,
  showLegend,
}: LaneAccordionSectionProps) {
  const isReady = summary.readyForAlignment;
  const bodyId = `${lane}-lane-body`;
  const subtitle = files.length > 0
    ? `${files.length} file${files.length === 1 ? "" : "s"} · ${formatBytes(totalBytes(files))}`
    : LANE_HINTS[lane];

  return (
    <section
      data-testid={`${lane}-lane-panel`}
      data-summary-status={summary.status}
      data-lane={lane}
      data-expanded={isExpanded}
      className="overflow-hidden rounded-2xl border border-stone-200 bg-white"
    >
      <div className="flex items-center gap-3 px-5 py-4">
        <button
          type="button"
          onClick={onHeaderClick}
          aria-expanded={isExpanded}
          aria-controls={bodyId}
          className="flex min-w-0 flex-1 items-center gap-3.5 rounded-lg text-left outline-none focus-visible:ring-2 focus-visible:ring-stone-300 focus-visible:ring-offset-2"
        >
          <NumberCircle step={stepIndex + 1} isReady={isReady} />
          <div className="min-w-0 flex-1">
            <h3 className="truncate text-[15px] font-semibold text-stone-900">
              {LANE_TITLES[lane]}
            </h3>
            <p className="mt-0.5 truncate text-[13px] text-stone-500">
              {subtitle}
            </p>
          </div>
          <ChevronDown
            className={cn(
              "size-4 shrink-0 text-stone-300 transition-transform duration-200 motion-reduce:transition-none",
              isExpanded && "rotate-180 text-stone-500"
            )}
          />
        </button>

        <Button
          type="button"
          size="sm"
          onClick={(event) => {
            event.stopPropagation();
            onPickFiles();
          }}
          disabled={isSubmitting || !desktopAvailable}
          data-testid={`${lane}-pick-files`}
          className="rounded-full bg-stone-900 px-4 text-white hover:bg-stone-800"
        >
          {isSubmitting ? (
            <LoaderCircle className="mr-1.5 size-3.5 animate-spin" />
          ) : (
            <FolderOpen className="mr-1.5 size-3.5" />
          )}
          {files.length > 0 ? "Replace" : "Choose files"}
        </Button>
      </div>

      <div
        id={bodyId}
        className={cn(
          "grid transition-[grid-template-rows] duration-300 ease-out motion-reduce:transition-none",
          isExpanded ? "grid-rows-[1fr]" : "grid-rows-[0fr]"
        )}
        aria-hidden={!isExpanded}
      >
        <div className="overflow-hidden">
          <div className="space-y-4 border-t border-stone-100 px-5 py-4">
            {files.length === 0 ? (
              <p className="text-[13px] leading-relaxed text-stone-500">
                {FILE_HINT}
              </p>
            ) : null}

            <SourceFileCard files={files} />

            {isSubmitting || summary.status === "normalizing" || summary.progress ? (
              <LaneProgressCard
                progress={summary.progress ?? null}
                isSubmitting={isSubmitting}
                desktopAvailable={desktopAvailable}
              />
            ) : null}

            {laneError ? (
              <div className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-[13px] leading-5 text-rose-700">
                {laneError}
              </div>
            ) : null}

            {summary.blockingIssues.length ? (
              <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-[13px] text-amber-800">
                <div className="flex items-center gap-1.5 font-medium">
                  <AlertTriangle className="size-3.5" />
                  Needs attention
                </div>
                <ul className="mt-1 space-y-0.5 leading-5">
                  {summary.blockingIssues.map((issue) => (
                    <li key={issue}>{issue}</li>
                  ))}
                </ul>
              </div>
            ) : null}

            {isReady || previewState.phase !== "idle" ? (
              <LanePreviewPanel
                key={previewState.data?.batchId ?? lane}
                lane={lane}
                previewState={previewState}
                onRetry={onRetryPreview}
                showLegend={showLegend}
              />
            ) : null}

            {onContinue ? (
              <div className="flex justify-end pt-1">
                <button
                  type="button"
                  onClick={onContinue}
                  className="inline-flex items-center gap-1.5 rounded-full bg-emerald-600 px-4 py-2 text-[13px] font-medium text-white transition-colors hover:bg-emerald-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-400 focus-visible:ring-offset-2"
                >
                  Continue to tumor sample
                  <ArrowRight className="size-3.5" />
                </button>
              </div>
            ) : null}
          </div>
        </div>
      </div>
    </section>
  );
}

function NumberCircle({ step, isReady }: { step: number; isReady: boolean }) {
  return (
    <div
      className={cn(
        "flex size-7 shrink-0 items-center justify-center rounded-full text-[12px] font-medium transition-colors duration-300",
        isReady
          ? "bg-emerald-100 text-emerald-700"
          : "bg-stone-100 text-stone-600"
      )}
      aria-hidden="true"
    >
      {isReady ? <Check className="size-3.5" strokeWidth={3} /> : step}
    </div>
  );
}
