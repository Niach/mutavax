import { notFound } from "next/navigation";

import WorkspaceStageShell from "@/components/workspaces/WorkspaceStageShell";
import { api } from "@/lib/api";
import { isPipelineStageId } from "@/lib/types";

export const dynamic = "force-dynamic";

export default async function WorkspaceStagePage({
  params,
}: {
  params: Promise<{ workspaceId: string; stage: string }>;
}) {
  const { workspaceId, stage } = await params;

  if (!isPipelineStageId(stage)) {
    notFound();
  }

  let workspaces;
  let workspace;

  try {
    [workspaces, workspace] = await Promise.all([
      api.listWorkspaces(),
      api.getWorkspace(workspaceId),
    ]);
  } catch (error) {
    if (error instanceof Error && error.message.toLowerCase().includes("not found")) {
      notFound();
    }

    throw error;
  }

  return (
    <WorkspaceStageShell
      key={`${workspace.id}:${workspace.updatedAt}:${stage}`}
      workspace={workspace}
      workspaces={workspaces}
      currentStageId={stage}
    />
  );
}
