"use client";

import Link from "next/link";
import { useEffect, useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { Dna, Plus } from "lucide-react";

import IngestionStagePanel from "@/components/workspaces/IngestionStagePanel";
import FutureStagePanel from "@/components/workspaces/FutureStagePanel";
import { Badge } from "@/components/ui/badge";

import type { PipelineStageId, Workspace } from "@/lib/types";
import { PIPELINE_STAGES } from "@/lib/types";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";
import { formatSpeciesLabel } from "@/lib/workspace-utils";

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

  useEffect(() => {
    if (workspace.activeStage === currentStageId) {
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
  }, [currentStageId, workspace.activeStage, workspace.id]);

  const currentStage = PIPELINE_STAGES.find(
    (stage) => stage.id === currentStageId
  )!;

  function handleWorkspaceChange(updatedWorkspace: Workspace) {
    setWorkspace(updatedWorkspace);
    setWorkspaces((current) => mergeWorkspaces(current, updatedWorkspace));
  }

  return (
    <div className="min-h-screen bg-gray-50">
      {/* Header */}
      <header className="border-b bg-white">
        <div className="mx-auto flex max-w-[1400px] items-center justify-between gap-4 px-4 py-3 lg:px-6">
          <div className="flex items-center gap-3">
            <Link
              href="/"
              className="flex h-9 w-9 items-center justify-center rounded-lg bg-primary text-primary-foreground"
            >
              <Dna className="size-4" />
            </Link>
            <div className="space-y-1">
              <h1 className="text-lg font-semibold">{workspace.displayName}</h1>
              <div className="flex items-center gap-2">
                <Badge variant="outline">
                  {formatSpeciesLabel(workspace.species)}
                </Badge>
                <span className="text-xs text-muted-foreground">
                  {workspace.ingestion.readyForAlignment
                    ? "Alignment-ready intake"
                    : "Ingestion in progress"}
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
              className="rounded-lg border px-3 py-2 text-sm outline-none focus:border-primary focus:ring-2 focus:ring-primary/15"
            >
              {workspaces.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.displayName}
                </option>
              ))}
            </select>
            <Link
              href="/"
              className="inline-flex h-8 w-8 items-center justify-center rounded-lg border text-muted-foreground transition hover:bg-muted hover:text-foreground"
            >
              <Plus className="size-4" />
            </Link>
          </div>
        </div>
      </header>

      <div className="mx-auto max-w-[1400px] px-4 py-6 lg:px-6">
        <div className="grid gap-6 lg:grid-cols-[220px_minmax(0,1fr)]">
          {/* Sidebar — compact pipeline nav */}
          <nav className="space-y-1">
            {PIPELINE_STAGES.map((stage, index) => {
              const isActive = stage.id === currentStageId;

              return (
                <Link
                  key={stage.id}
                  href={`/workspaces/${workspace.id}/${stage.id}`}
                  className={cn(
                    "flex items-center gap-3 rounded-lg px-3 py-2 text-sm transition",
                    isActive
                      ? "bg-primary/5 font-medium text-primary"
                      : "text-muted-foreground hover:bg-muted hover:text-foreground"
                  )}
                >
                  <span
                    className={cn(
                      "flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-xs font-semibold",
                      isActive
                        ? "bg-primary text-primary-foreground"
                        : "bg-muted text-muted-foreground"
                    )}
                  >
                    {index + 1}
                  </span>
                  {stage.name}
                </Link>
              );
            })}
          </nav>

          {/* Main content */}
          <main className="space-y-4">
            <div className="mb-2">
              <h2 className="text-xl font-semibold">{currentStage.name}</h2>
              <p className="mt-1 text-sm text-muted-foreground">
                {currentStage.description}
              </p>
            </div>

            {currentStageId === "ingestion" ? (
              <IngestionStagePanel
                workspace={workspace}
                onWorkspaceChange={handleWorkspaceChange}
              />
            ) : (
              <FutureStagePanel
                stageId={currentStageId}
                workspace={workspace}
              />
            )}
          </main>
        </div>
      </div>
    </div>
  );
}
