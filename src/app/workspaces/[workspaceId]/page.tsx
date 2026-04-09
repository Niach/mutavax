import { notFound, redirect } from "next/navigation";

import { api } from "@/lib/api";

export const dynamic = "force-dynamic";

export default async function WorkspaceIndexPage({
  params,
}: {
  params: Promise<{ workspaceId: string }>;
}) {
  const { workspaceId } = await params;

  try {
    const workspace = await api.getWorkspace(workspaceId);
    redirect(`/workspaces/${workspace.id}/${workspace.activeStage}`);
  } catch (error) {
    if (error instanceof Error && error.message.toLowerCase().includes("not found")) {
      notFound();
    }

    throw error;
  }
}
