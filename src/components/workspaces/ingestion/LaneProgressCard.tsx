import { LoaderCircle } from "lucide-react";

import type { IngestionLaneProgress } from "@/lib/types";
import { formatBytes } from "@/lib/workspace-utils";

import { formatEta, formatProgressPhase, formatThroughput } from "./lane-utils";

export function LaneProgressCard({
  progress,
  isSubmitting,
  desktopAvailable,
}: {
  progress: IngestionLaneProgress | null;
  isSubmitting: boolean;
  desktopAvailable: boolean;
}) {
  const percent = progress?.percent ?? null;
  const bytesProcessed = progress?.bytesProcessed ?? null;
  const totalBytes = progress?.totalBytes ?? null;
  const throughput = formatThroughput(progress?.throughputBytesPerSec ?? null);
  const eta = formatEta(progress?.etaSeconds ?? null);

  return (
    <div className="rounded-lg border border-stone-200 bg-stone-50/50 px-3 py-3">
      <div className="flex items-center gap-2 text-[13px] font-medium text-stone-800">
        <LoaderCircle className="size-3.5 animate-spin" />
        {isSubmitting
          ? "Registering file references"
          : progress
            ? formatProgressPhase(progress.phase)
            : "Preparing lane"}
      </div>

      {progress?.currentFilename ? (
        <div className="mt-2 truncate text-[12px] text-stone-500">
          {progress.currentFilename}
        </div>
      ) : (
        <div className="mt-2 text-[12px] text-stone-500">
          {desktopAvailable
            ? "Working locally on the selected files."
            : "Desktop runtime required for local file intake."}
        </div>
      )}

      <div className="mt-3 h-1 overflow-hidden rounded-full bg-stone-200">
        {percent != null ? (
          <div
            className="h-full rounded-full bg-emerald-500/70 transition-[width] duration-500"
            style={{ width: `${Math.max(3, Math.min(percent, 100))}%` }}
          />
        ) : (
          <div className="h-full w-1/2 animate-[pulse_1.2s_ease-in-out_infinite] rounded-full bg-emerald-500/60" />
        )}
      </div>

      <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1 font-mono text-[10px] uppercase tracking-[0.14em] text-stone-400">
        {percent != null ? <span>{Math.round(percent)}%</span> : null}
        {bytesProcessed != null && totalBytes != null ? (
          <span>
            {formatBytes(bytesProcessed)} / {formatBytes(totalBytes)}
          </span>
        ) : null}
        {throughput ? <span>{throughput}</span> : null}
        {eta ? <span>{eta}</span> : null}
      </div>
    </div>
  );
}
