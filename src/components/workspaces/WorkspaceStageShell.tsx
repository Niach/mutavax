"use client";

import Link from "next/link";
import { useEffect, useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { ChevronDown, Dna, LockKeyhole, Plus } from "lucide-react";

import AlignmentStagePanel from "@/components/workspaces/AlignmentStagePanel";
import IngestionStagePanel from "@/components/workspaces/IngestionStagePanel";
import FutureStagePanel from "@/components/workspaces/FutureStagePanel";
import { Badge } from "@/components/ui/badge";

import type {
  AlignmentStageSummary,
  PipelineStage,
  PipelineStageId,
  Workspace,
} from "@/lib/types";
import {
  LATER_RESEARCH_STAGES,
  PIPELINE_STAGES,
  PRIMARY_PIPELINE_STAGES,
} from "@/lib/types";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";
import {
  formatReferencePreset,
  formatSpeciesLabel,
} from "@/lib/workspace-utils";

function mergeWorkspaces(workspaces: Workspace[], workspace: Workspace) {
  const withoutCurrent = workspaces.filter((item) => item.id !== workspace.id);
  return [workspace, ...withoutCurrent].sort((left, right) =>
    right.updatedAt.localeCompare(left.updatedAt)
  );
}

function isStageLocked(
  stageId: PipelineStageId,
  workspace: Workspace,
  alignmentSummary: AlignmentStageSummary
) {
  if (stageId === "ingestion") {
    return false;
  }
  if (stageId === "alignment") {
    return !workspace.ingestion.readyForAlignment;
  }
  return !alignmentSummary.readyForVariantCalling;
}

function stageLockedReason(
  stageId: PipelineStageId,
  workspace: Workspace,
  alignmentSummary: AlignmentStageSummary
) {
  if (stageId === "alignment" && !workspace.ingestion.readyForAlignment) {
    return "Alignment unlocks once both tumor and normal lanes have canonical paired FASTQ ready.";
  }
  if (stageId !== "ingestion" && !alignmentSummary.readyForVariantCalling) {
    return "Variant calling unlocks after a successful alignment run with BAM, BAI, and passing QC.";
  }
  return undefined;
}

function workspaceSubtitle(
  workspace: Workspace,
  alignmentSummary: AlignmentStageSummary
) {
  if (alignmentSummary.readyForVariantCalling) {
    return "Alignment QC complete and variant calling is unlocked";
  }
  if (workspace.ingestion.readyForAlignment) {
    return "Tumor + normal intake ready for alignment";
  }
  return "Ingestion is still blocking alignment";
}

function NavigationStageItem({
  stage,
  label,
  href,
  isActive,
  isLocked,
}: {
  stage: PipelineStage;
  label: string;
  href: string;
  isActive: boolean;
  isLocked: boolean;
}) {
  const content = (
    <>
      <span
        className={cn(
          "flex h-7 min-w-7 shrink-0 items-center justify-center rounded-full px-2 text-xs font-semibold",
          isActive
            ? "bg-emerald-600 text-white"
            : isLocked
              ? "bg-slate-200 text-slate-500"
              : "bg-muted text-muted-foreground"
        )}
      >
        {isLocked ? <LockKeyhole className="size-3.5" /> : label}
      </span>
      <div className="min-w-0">
        <div>{stage.name}</div>
        {isLocked ? (
          <div className="text-xs font-normal text-slate-500">Locked</div>
        ) : null}
      </div>
    </>
  );

  if (isLocked) {
    return (
      <div
        aria-disabled="true"
        className="flex cursor-not-allowed items-center gap-3 rounded-2xl px-3 py-2 text-sm text-slate-400"
      >
        {content}
      </div>
    );
  }

  return (
    <Link
      href={href}
      className={cn(
        "flex items-center gap-3 rounded-2xl px-3 py-2 text-sm transition",
        isActive
          ? "bg-emerald-50 font-medium text-emerald-700"
          : "text-muted-foreground hover:bg-muted hover:text-foreground"
      )}
    >
      {content}
    </Link>
  );
}

interface WorkspaceStageShellProps {
  workspace: Workspace;
  workspaces: Workspace[];
  currentStageId: PipelineStageId;
  initialAlignmentSummary: AlignmentStageSummary;
}

export default function WorkspaceStageShell({
  workspace: initialWorkspace,
  workspaces: initialWorkspaces,
  currentStageId,
  initialAlignmentSummary,
}: WorkspaceStageShellProps) {
  const router = useRouter();
  const [, startTransition] = useTransition();
  const [workspace, setWorkspace] = useState(initialWorkspace);
  const [workspaces, setWorkspaces] = useState(
    mergeWorkspaces(initialWorkspaces, initialWorkspace)
  );
  const [alignmentSummary, setAlignmentSummary] = useState(
    initialAlignmentSummary
  );

  useEffect(() => {
    if (workspace.activeStage === currentStageId) {
      return;
    }
    if (isStageLocked(currentStageId, workspace, alignmentSummary)) {
      return;
    }

    let ignore = false;

    void api
      .updateWorkspaceActiveStage(workspace.id, currentStageId)
      .then((updatedWorkspace) => {
        if (ignore) return;
        setWorkspace(updatedWorkspace);
        setWorkspaces((current) => mergeWorkspaces(current, updatedWorkspace));
      })
      .catch(() => {});

    return () => {
      ignore = true;
    };
  }, [alignmentSummary, currentStageId, workspace]);

  const currentStage = PIPELINE_STAGES.find(
    (stage) => stage.id === currentStageId
  )!;
  const currentStageLocked = isStageLocked(
    currentStageId,
    workspace,
    alignmentSummary
  );
  function handleWorkspaceChange(updatedWorkspace: Workspace) {
    setWorkspace(updatedWorkspace);
    setWorkspaces((current) => mergeWorkspaces(current, updatedWorkspace));
    void api
      .getAlignmentStageSummary(updatedWorkspace.id)
      .then(setAlignmentSummary)
      .catch(() => {});
  }

  return (
    <div className="min-h-screen bg-[radial-gradient(circle_at_top_left,_rgba(21,128,61,0.08),_transparent_22%),radial-gradient(circle_at_bottom_right,_rgba(14,165,233,0.08),_transparent_24%),linear-gradient(180deg,_#f8fbf8_0%,_#f2f6f3_100%)]">
      <header className="border-b border-black/6 bg-white/85 backdrop-blur">
        <div className="mx-auto flex max-w-[1440px] items-center justify-between gap-4 px-4 py-3 lg:px-6">
          <div className="flex items-center gap-3">
            <Link
              href="/"
              className="flex h-10 w-10 items-center justify-center rounded-xl bg-emerald-600 text-white shadow-sm shadow-emerald-900/10"
            >
              <Dna className="size-4" />
            </Link>
            <div className="space-y-1">
              <h1 className="text-lg font-semibold">{workspace.displayName}</h1>
              <div className="flex flex-wrap items-center gap-2">
                <Badge variant="outline">
                  {formatSpeciesLabel(workspace.species)}
                </Badge>
                <Badge
                  variant="outline"
                  className="border-black/10 bg-white/80 font-mono text-[10px] tracking-[0.2em] uppercase text-slate-600"
                >
                  {formatReferencePreset(workspace.analysisProfile.referencePreset)}
                </Badge>
                <span className="text-xs text-muted-foreground">
                  {workspaceSubtitle(workspace, alignmentSummary)}
                </span>
              </div>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <select
              value={workspace.id}
              onChange={(event) =>
                startTransition(() => {
                  router.push(
                    `/workspaces/${event.target.value}/${currentStageId}`
                  );
                })
              }
              className="rounded-xl border border-black/10 bg-white px-3 py-2 text-sm outline-none focus:border-emerald-500 focus:ring-2 focus:ring-emerald-200"
            >
              {workspaces.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.displayName}
                </option>
              ))}
            </select>
            <Link
              href="/"
              aria-label="New workspace"
              className="inline-flex h-9 w-9 items-center justify-center rounded-xl border border-black/10 text-muted-foreground transition hover:bg-muted hover:text-foreground"
            >
              <Plus className="size-4" />
            </Link>
          </div>
        </div>
      </header>

      <div className="mx-auto max-w-[1440px] px-4 py-6 lg:px-6">
        <div className="grid gap-6 lg:grid-cols-[260px_minmax(0,1fr)]">
          <nav className="rounded-[24px] border border-black/5 bg-white/65 p-3 shadow-sm shadow-black/5 backdrop-blur">
            <div className="mb-3 px-2 font-mono text-[10px] font-medium tracking-[0.28em] text-slate-400 uppercase">
              Primary pipeline
            </div>
            <div className="space-y-1">
              {PRIMARY_PIPELINE_STAGES.map((stage, index) => (
                <NavigationStageItem
                  key={stage.id}
                  stage={stage}
                  label={`${index + 1}`}
                  href={`/workspaces/${workspace.id}/${stage.id}`}
                  isActive={stage.id === currentStageId}
                  isLocked={isStageLocked(stage.id, workspace, alignmentSummary)}
                />
              ))}
            </div>

            <details className="mt-5 rounded-2xl border border-black/6 bg-white/60">
              <summary className="flex cursor-pointer list-none items-center justify-between gap-3 px-4 py-3 text-sm font-medium text-slate-700">
                Later research modules
                <ChevronDown className="size-4 transition group-open:rotate-180" />
              </summary>
              <div className="space-y-1 border-t border-black/6 px-2 py-2">
                {LATER_RESEARCH_STAGES.map((stage, index) => (
                  <NavigationStageItem
                    key={stage.id}
                    stage={stage}
                    label={`R${index + 1}`}
                    href={`/workspaces/${workspace.id}/${stage.id}`}
                    isActive={stage.id === currentStageId}
                    isLocked={isStageLocked(stage.id, workspace, alignmentSummary)}
                  />
                ))}
              </div>
            </details>
          </nav>

          <main className="space-y-4">
            {currentStageId === "ingestion" || currentStageId === "alignment" ? null : (
              <div className="rounded-[24px] border border-black/5 bg-white/70 px-6 py-5 shadow-sm shadow-black/5 backdrop-blur">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div>
                    <h2 className="text-2xl font-semibold tracking-tight">
                      {currentStage.name}
                    </h2>
                    <p
                      className="mt-1 max-w-2xl font-display text-[15px] italic text-muted-foreground"
                      style={{ fontOpticalSizing: "auto" }}
                    >
                      {currentStage.description}
                    </p>
                  </div>
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge
                      variant="outline"
                      className="border-black/10 bg-slate-50/70 font-mono text-[10px] tracking-[0.18em] text-slate-500 uppercase"
                    >
                      {currentStage.implementationState}
                    </Badge>
                  </div>
                </div>
              </div>
            )}

            {currentStageId === "ingestion" ? (
              <IngestionStagePanel
                workspace={workspace}
                onWorkspaceChange={handleWorkspaceChange}
              />
            ) : currentStageId === "alignment" ? (
              <AlignmentStagePanel
                workspace={workspace}
                summary={alignmentSummary}
                onWorkspaceChange={handleWorkspaceChange}
                onSummaryChange={setAlignmentSummary}
              />
            ) : (
              <FutureStagePanel
                stageId={currentStageId}
                workspace={workspace}
                lockedReason={stageLockedReason(
                  currentStageId,
                  workspace,
                  alignmentSummary
                )}
                isLocked={currentStageLocked}
              />
            )}
          </main>
        </div>
      </div>
    </div>
  );
}
