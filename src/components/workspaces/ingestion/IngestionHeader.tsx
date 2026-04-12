import { cn } from "@/lib/utils";

export type AlignmentState = "locked" | "unlocked";

export function IngestionHeader({
  readyOutputCount,
  alignmentState,
}: {
  readyOutputCount: number;
  alignmentState: AlignmentState;
}) {
  const isUnlocked = alignmentState === "unlocked";
  const message = messageFor(readyOutputCount);

  return (
    <div className="flex flex-wrap items-center justify-between gap-3 px-1 pt-1 pb-3">
      <p className="text-sm text-stone-600">{message}</p>
      <span
        data-testid="alignment-status-indicator"
        data-state={alignmentState}
        className={cn(
          "inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 font-mono text-[10px] uppercase tracking-[0.2em]",
          isUnlocked
            ? "bg-emerald-50 text-emerald-700"
            : "bg-stone-100 text-stone-500"
        )}
      >
        <span
          className={cn(
            "inline-block size-1.5 rounded-full",
            isUnlocked ? "bg-emerald-500" : "bg-stone-400"
          )}
        />
        {isUnlocked ? "Ready for alignment" : "Waiting for files"}
      </span>
    </div>
  );
}

function messageFor(readyOutputCount: number) {
  if (readyOutputCount === 0) {
    return "Pick the two sample files to start the analysis.";
  }
  if (readyOutputCount < 4) {
    return "One sample to go.";
  }
  return "Both samples loaded.";
}
