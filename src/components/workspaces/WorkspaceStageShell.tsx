"use client";

import Link from "next/link";
import { useEffect, useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { Dna, LockKeyhole, Plus } from "lucide-react";

import IngestionStagePanel from "@/components/workspaces/IngestionStagePanel";
import FutureStagePanel from "@/components/workspaces/FutureStagePanel";
import { Badge } from "@/components/ui/badge";

import type { PipelineStageId, Workspace } from "@/lib/types";
import { PIPELINE_STAGES } from "@/lib/types";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";
import {
  formatLaneLabel,
  formatSpeciesLabel,
  getLaneStatusLabel,
} from "@/lib/workspace-utils";

function mergeWorkspaces(workspaces: Workspace[], workspace: Workspace) {
  const withoutCurrent = workspaces.filter((item) => item.id !== workspace.id);
  return [workspace, ...withoutCurrent].sort((left, right) =>
    right.updatedAt.localeCompare(left.updatedAt)
  );
}

interface WorkspaceStageShellProps {
  workspace: Workspace;
  workspaces: Workspace[];
  currentStageId: PipelineStageId;
}

export default function WorkspaceStageShell({
  workspace: initialWorkspace,
  workspaces: initialWorkspaces,
  currentStageId,
}: WorkspaceStageShellProps) {
  const router = useRouter();
  const [, startTransition] = useTransition();
  const [workspace, setWorkspace] = useState(initialWorkspace);
  const [workspaces, setWorkspaces] = useState(
    mergeWorkspaces(initialWorkspaces, initialWorkspace)
  );

  const alignmentLocked = !workspace.ingestion.readyForAlignment;

  useEffect(() => {
    if (workspace.activeStage === currentStageId) {
      return;
    }
    if (currentStageId === "alignment" && alignmentLocked) {
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
  }, [alignmentLocked, currentStageId, workspace.activeStage, workspace.id]);

  const currentStage = PIPELINE_STAGES.find(
    (stage) => stage.id === currentStageId
  )!;

  function handleWorkspaceChange(updatedWorkspace: Workspace) {
    setWorkspace(updatedWorkspace);
    setWorkspaces((current) => mergeWorkspaces(current, updatedWorkspace));
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
                <span className="text-xs text-muted-foreground">
                  {workspace.ingestion.readyForAlignment
                    ? "Tumor + normal intake ready"
                    : "Ingestion is still blocking alignment"}
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
              className="inline-flex h-9 w-9 items-center justify-center rounded-xl border border-black/10 text-muted-foreground transition hover:bg-muted hover:text-foreground"
            >
              <Plus className="size-4" />
            </Link>
          </div>
        </div>
      </header>

      <div className="mx-auto max-w-[1440px] px-4 py-6 lg:px-6">
        <div className="grid gap-6 lg:grid-cols-[240px_minmax(0,1fr)]">
          <nav className="rounded-[24px] border border-black/5 bg-white/65 p-3 shadow-sm shadow-black/5 backdrop-blur">
            <div className="mb-3 px-2 font-mono text-[10px] font-medium tracking-[0.28em] text-slate-400 uppercase">
              Pipeline
            </div>
            <div className="space-y-1">
              {PIPELINE_STAGES.map((stage, index) => {
                const isActive = stage.id === currentStageId;
                const isAlignmentLocked =
                  stage.id === "alignment" && alignmentLocked;

                const content = (
                  <>
                    <span
                      className={cn(
                        "flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-xs font-semibold",
                        isActive
                          ? "bg-emerald-600 text-white"
                          : isAlignmentLocked
                            ? "bg-slate-200 text-slate-500"
                            : "bg-muted text-muted-foreground"
                      )}
                    >
                      {isAlignmentLocked ? (
                        <LockKeyhole className="size-3.5" />
                      ) : (
                        index + 1
                      )}
                    </span>
                    <div className="min-w-0">
                      <div>{stage.name}</div>
                      {isAlignmentLocked && (
                        <div className="text-xs font-normal text-slate-500">
                          Wait for both lanes
                        </div>
                      )}
                    </div>
                  </>
                );

                if (isAlignmentLocked) {
                  return (
                    <div
                      key={stage.id}
                      aria-disabled="true"
                      className="flex cursor-not-allowed items-center gap-3 rounded-2xl px-3 py-2 text-sm text-slate-400"
                    >
                      {content}
                    </div>
                  );
                }

                return (
                  <Link
                    key={stage.id}
                    href={`/workspaces/${workspace.id}/${stage.id}`}
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
              })}
            </div>
          </nav>

          <main className="space-y-4">
            {currentStageId === "ingestion" ? (
              <div className="border-b border-black/8 pb-4">
                <div className="flex flex-col gap-3 xl:flex-row xl:items-center xl:justify-between">
                  <h2 className="text-3xl font-semibold tracking-tight">
                    {currentStage.name}
                  </h2>

                  <div className="flex flex-wrap items-center gap-2">
                    <span
                      data-testid="alignment-status-indicator"
                      data-state={alignmentLocked ? "locked" : "unlocked"}
                      className={cn(
                        "inline-flex items-center gap-2 rounded-full border px-3 py-1.5 font-mono text-[10px] tracking-[0.2em] uppercase",
                        alignmentLocked
                          ? "border-black/10 bg-white/80 text-slate-500"
                          : "border-emerald-200 bg-emerald-50 text-emerald-700"
                      )}
                    >
                      <span
                        aria-hidden
                        className={cn(
                          "size-1.5 rounded-full",
                          alignmentLocked ? "bg-slate-300" : "bg-emerald-500"
                        )}
                      />
                      {alignmentLocked ? "Alignment locked" : "Alignment ready"}
                    </span>

                    {(["tumor", "normal"] as const).map((lane) => {
                      const summary = workspace.ingestion.lanes[lane];
                      const isReady = summary.status === "ready";
                      const isFailed = summary.status === "failed";

                      return (
                        <span
                          key={lane}
                          className={cn(
                            "inline-flex items-center gap-2 rounded-full border px-3 py-1.5 text-sm",
                            isReady
                              ? "border-emerald-200 bg-emerald-50/80 text-emerald-800"
                              : isFailed
                                ? "border-rose-200 bg-rose-50 text-rose-700"
                                : "border-black/10 bg-white/80 text-slate-600"
                          )}
                        >
                          <span
                            aria-hidden
                            className={cn(
                              "size-1.5 rounded-full",
                              lane === "tumor"
                                ? "bg-[color:var(--lane-tumor)]"
                                : "bg-[color:var(--lane-normal)]"
                            )}
                          />
                          <span className="font-medium">
                            {formatLaneLabel(lane)}
                          </span>
                          <span className="text-slate-500">
                            {getLaneStatusLabel(summary)}
                          </span>
                        </span>
                      );
                    })}
                  </div>
                </div>
              </div>
            ) : (
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
                  <Badge
                    variant="outline"
                    className="border-black/10 bg-slate-50/70 font-mono text-[10px] tracking-[0.18em] text-slate-500 uppercase"
                  >
                    {currentStage.implementationState}
                  </Badge>
                </div>
              </div>
            )}

            {currentStageId === "ingestion" ? (
              <IngestionStagePanel
                workspace={workspace}
                onWorkspaceChange={handleWorkspaceChange}
              />
            ) : (
              <FutureStagePanel
                stageId={currentStageId}
                workspace={workspace}
                lockedReason={
                  currentStageId === "alignment" && alignmentLocked
                    ? "Alignment unlocks once both tumor and normal lanes have canonical paired FASTQ ready."
                    : undefined
                }
              />
            )}
          </main>
        </div>
      </div>
    </div>
  );
}
