import { notFound, redirect } from "next/navigation";

import WorkspaceStageShell from "@/components/workspaces/WorkspaceStageShell";
import { api } from "@/lib/api";
import { getLatestActionableStageId, getPipelinePolicy } from "@/lib/pipeline-policy";
import { isPipelineStageId } from "@/lib/types";

export const dynamic = "force-dynamic";

export default async function WorkspaceStagePage({
  params,
  searchParams,
}: {
  params: Promise<{ workspaceId: string; stage: string }>;
  searchParams: Promise<{ comingSoon?: string }>;
}) {
  const { workspaceId, stage } = await params;
  const { comingSoon } = await searchParams;

  if (!isPipelineStageId(stage)) {
    notFound();
  }

  let workspaces;
  let workspace;
  let alignmentSummary;
  let variantCallingSummary;
  let annotationSummary;
  let neoantigenSummary;
  let epitopeSummary;
  let constructSummary;
  let constructOutputSummary;
  let aiReviewSummary;

  try {
    [
      workspaces,
      workspace,
      alignmentSummary,
      variantCallingSummary,
      annotationSummary,
      neoantigenSummary,
      epitopeSummary,
      constructSummary,
      constructOutputSummary,
      aiReviewSummary,
    ] = await Promise.all([
      api.listWorkspaces(),
      api.getWorkspace(workspaceId),
      api.getAlignmentStageSummary(workspaceId),
      api.getVariantCallingStageSummary(workspaceId),
      api.getAnnotationStageSummary(workspaceId),
      api.getNeoantigenStageSummary(workspaceId),
      api.getEpitopeStageSummary(workspaceId),
      api.getConstructStageSummary(workspaceId),
      api.getConstructOutputSummary(workspaceId),
      api.getAiReviewSummary(workspaceId),
    ]);
  } catch (error) {
    if (error instanceof Error && error.message.toLowerCase().includes("not found")) {
      notFound();
    }

    throw error;
  }

  const policy = getPipelinePolicy(
    workspace,
    alignmentSummary,
    variantCallingSummary,
    annotationSummary,
    neoantigenSummary,
    epitopeSummary,
    constructSummary,
    constructOutputSummary,
    aiReviewSummary
  );
  const redirectedFromStageId = comingSoon && isPipelineStageId(comingSoon) ? comingSoon : null;
  if (!policy[stage].enterable) {
    const fallbackStage = getLatestActionableStageId(policy);
    redirect(
      `/workspaces/${workspace.id}/${fallbackStage}?comingSoon=${encodeURIComponent(stage)}`
    );
  }

  return (
    <WorkspaceStageShell
      key={`${workspace.id}:${workspace.updatedAt}:${stage}`}
      workspace={workspace}
      workspaces={workspaces}
      currentStageId={stage}
      initialAlignmentSummary={alignmentSummary}
      initialVariantCallingSummary={variantCallingSummary}
      initialAnnotationSummary={annotationSummary}
      initialNeoantigenSummary={neoantigenSummary}
      initialEpitopeSummary={epitopeSummary}
      initialConstructSummary={constructSummary}
      initialConstructOutputSummary={constructOutputSummary}
      initialAiReviewSummary={aiReviewSummary}
      redirectedFromStageId={redirectedFromStageId}
    />
  );
}
