import Link from "next/link";

import WorkspaceCreateCard from "@/components/workspaces/WorkspaceCreateCard";
import { Badge } from "@/components/ui/badge";
import { api } from "@/lib/api";
import { PIPELINE_STAGES } from "@/lib/types";
import {
  countReadyRequiredOutputs,
  formatDateTime,
  formatSpeciesLabel,
} from "@/lib/workspace-utils";

export const dynamic = "force-dynamic";

export default async function Home() {
  const workspaces = await api.listWorkspaces().catch(() => []);

  return (
    <div className="min-h-screen bg-[radial-gradient(circle_at_top_left,_rgba(16,185,129,0.14),_transparent_28%),linear-gradient(180deg,_#f7faf7_0%,_#eef3ef_48%,_#e9efeb_100%)] px-4 py-10 lg:px-6">
      <div className="mx-auto grid max-w-[1440px] gap-8 lg:grid-cols-[360px_minmax(0,1fr)]">
        <section className="space-y-5">
          <div className="space-y-2">
            <p className="text-[11px] font-semibold tracking-[0.3em] text-emerald-700 uppercase">
              cancerstudio
            </p>
            <h1 className="font-display text-4xl leading-none text-slate-950">
              Workspaces
            </h1>
          </div>

          <WorkspaceCreateCard title="New workspace" />
        </section>

        <section className="overflow-hidden rounded-[28px] border border-black/6 bg-white/72 shadow-[0_28px_80px_-48px_rgba(24,34,28,0.45)] backdrop-blur-sm">
          <div className="flex items-center justify-between gap-3 border-b border-black/6 px-5 py-4 sm:px-6">
            <div>
              <h2 className="text-lg font-semibold text-slate-950">Open</h2>
              <p className="text-sm text-slate-500">{workspaces.length} total</p>
            </div>
          </div>

          {workspaces.length === 0 ? (
            <div className="px-5 py-12 text-sm text-slate-500 sm:px-6">
              No workspaces yet.
            </div>
          ) : (
            <div className="divide-y divide-black/6">
              {workspaces.map((workspace) => {
                const readyCount = countReadyRequiredOutputs(workspace);
                const activeStage =
                  PIPELINE_STAGES.find(
                    (stage) => stage.id === workspace.activeStage
                  ) ?? PIPELINE_STAGES[0];

                return (
                  <Link
                    key={workspace.id}
                    href={`/workspaces/${workspace.id}/${workspace.activeStage}`}
                    className="flex flex-col gap-3 px-5 py-4 transition hover:bg-white/70 sm:px-6 lg:flex-row lg:items-center lg:justify-between"
                  >
                    <div className="min-w-0 space-y-2">
                      <div className="flex flex-wrap items-center gap-2">
                        <h3 className="truncate text-base font-semibold text-slate-950">
                          {workspace.displayName}
                        </h3>
                        <Badge variant="outline">
                          {formatSpeciesLabel(workspace.species)}
                        </Badge>
                      </div>
                      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-slate-500">
                        <span>{readyCount}/4 paired ready</span>
                        <span>{activeStage.name}</span>
                      </div>
                    </div>

                    <div className="shrink-0 text-sm text-slate-400">
                      {formatDateTime(workspace.updatedAt)}
                    </div>
                  </Link>
                );
              })}
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
