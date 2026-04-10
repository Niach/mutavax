import Link from "next/link";
import type { PipelineStageId, Workspace } from "@/lib/types";
import { PIPELINE_STAGES } from "@/lib/types";

interface FutureStagePanelProps {
  stageId: PipelineStageId;
  workspace: Workspace;
  lockedReason?: string;
}

export default function FutureStagePanel({
  stageId,
  workspace,
  lockedReason,
}: FutureStagePanelProps) {
  const stage = PIPELINE_STAGES.find((s) => s.id === stageId)!;

  return (
    <div className="flex flex-col items-center justify-center rounded-lg border border-dashed py-16 text-center">
      <p className="text-lg font-medium">{stage.name}</p>
      <p className="mt-1 max-w-md text-sm text-muted-foreground">
        {stage.description}
      </p>
      <p className="mt-4 text-sm text-muted-foreground">
        {lockedReason ??
          "This step is still placeholder-backed while we finish the ingestion and storage foundation."}
      </p>
      <Link
        href={`/workspaces/${workspace.id}/ingestion`}
        className="mt-4 text-sm font-medium text-primary underline underline-offset-4"
      >
        Back to Ingestion
      </Link>
    </div>
  );
}
