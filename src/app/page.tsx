import { redirect } from "next/navigation";

import WorkspaceCreateCard from "@/components/workspaces/WorkspaceCreateCard";
import { api } from "@/lib/api";

export const dynamic = "force-dynamic";

export default async function Home() {
  const workspaces = await api.listWorkspaces().catch(() => []);

  if (workspaces.length > 0) {
    redirect(`/workspaces/${workspaces[0].id}/ingestion`);
  }

  return (
    <div className="flex min-h-screen flex-col items-center justify-center bg-[radial-gradient(circle_at_top_left,_rgba(16,185,129,0.14),_transparent_28%),linear-gradient(180deg,_#f7faf7_0%,_#eef3ef_48%,_#e9efeb_100%)] px-4 py-12">
      <div className="w-full max-w-lg space-y-6">
        <p className="text-center text-[11px] font-semibold tracking-[0.3em] text-emerald-700 uppercase">
          cancerstudio
        </p>
        <WorkspaceCreateCard />
        <p className="text-center text-sm text-slate-400">
          <a href="https://your-org.github.io/cancerstudio" className="underline underline-offset-2 hover:text-slate-600">
            How this works
          </a>
        </p>
      </div>
    </div>
  );
}
