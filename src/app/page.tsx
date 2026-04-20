import Link from "next/link";

import Helix from "@/components/helix/Helix";
import TweaksPanel from "@/components/dev/TweaksPanel";
import { Card, CardHead, Chip, Eyebrow, MonoLabel } from "@/components/ui-kit";
import { api } from "@/lib/api";
import { describeWorkspaceProgress } from "@/lib/pipeline-policy";
import { PIPELINE_STAGES } from "@/lib/types";
import { formatDateTime, formatSpeciesLabel } from "@/lib/workspace-utils";

export const dynamic = "force-dynamic";

export default async function Home() {
  const workspaces = await api.listWorkspaces().catch(() => []);
  const alignmentSummaries = await Promise.all(
    workspaces.map(async (workspace) => ({
      workspaceId: workspace.id,
      summary: await api.getAlignmentStageSummary(workspace.id).catch(() => null),
    }))
  );
  const alignmentByWorkspaceId = new Map(
    alignmentSummaries.map((entry) => [entry.workspaceId, entry.summary])
  );

  const firstWorkspace = workspaces[0] ?? null;
  const liveStageCount = PIPELINE_STAGES.filter(
    (stage) => stage.implementationState === "live"
  ).length;

  return (
    <div className="cs-theme">
      <div className="cs-view cs-fade-in">
        <section className="cs-hero">
          <div className="cs-hero-grid">
            <div>
              <Eyebrow>cancerstudio · desktop studio</Eyebrow>
              <h1 className="cs-landing-title">
                Two DNA samples.
                <br />
                One guided path to a personalized cancer vaccine.
              </h1>
              <p className="cs-landing-sub">
                Give us a DNA sample from the tumor and a matched healthy sample.
                We&apos;ll walk you through every step — from raw files to a
                shortlist of mutations your vaccine can target. No command line.
                Works for people, dogs, and cats. Nothing leaves your computer.
              </p>

              <div className="cs-landing-ctas">
                {firstWorkspace ? (
                  <Link
                    href={`/workspaces/${firstWorkspace.id}`}
                    className="cs-btn cs-btn-primary"
                  >
                    Open {firstWorkspace.displayName} →
                  </Link>
                ) : (
                  <Link href="/workspaces/new" className="cs-btn cs-btn-primary">
                    Start your first case →
                  </Link>
                )}
                <Link href="/workspaces/new" className="cs-btn cs-btn-ghost">
                  Start a new case
                </Link>
              </div>

              <div className="cs-landing-stats">
                <Stat
                  label="Species supported"
                  value="3"
                  hint="dog · cat · human"
                />
                <Stat
                  label="Live stages"
                  value={`${liveStageCount} / ${PIPELINE_STAGES.length}`}
                  hint="ingestion → annotation"
                />
                <Stat
                  label="Runs locally"
                  value="100%"
                  hint="no cloud · no upload"
                />
              </div>
            </div>

            <div className="cs-landing-helix">
              <Helix size={320} rungs={24} hue={152} speed={28} />
            </div>
          </div>
        </section>

        <div className="cs-landing-cards">
          <Card>
            <CardHead
              eyebrow="Open"
              title="Workspaces"
              subtitle={
                workspaces.length === 0
                  ? "No workspaces yet."
                  : `${workspaces.length} case${workspaces.length === 1 ? "" : "s"}`
              }
            />
            {workspaces.length === 0 ? (
              <div
                style={{
                  padding: "22px",
                  color: "var(--muted)",
                  fontSize: 14,
                }}
              >
                Create a workspace to give us your first sample.
              </div>
            ) : (
              <div>
                {workspaces.map((workspace) => {
                  const alignmentSummary = alignmentByWorkspaceId.get(workspace.id);
                  const progressLabel = alignmentSummary
                    ? describeWorkspaceProgress(workspace, alignmentSummary)
                    : "Open this workspace to continue.";
                  return (
                    <Link
                      key={workspace.id}
                      href={`/workspaces/${workspace.id}`}
                      style={{
                        display: "block",
                        padding: "16px 22px",
                        textDecoration: "none",
                        color: "inherit",
                        borderBottom: "1px solid var(--line)",
                      }}
                    >
                      <div
                        style={{
                          display: "flex",
                          justifyContent: "space-between",
                          alignItems: "flex-start",
                          gap: 12,
                        }}
                      >
                        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                          <div
                            style={{ display: "flex", alignItems: "center", gap: 10 }}
                          >
                            <span
                              style={{
                                fontFamily: "var(--font-display)",
                                fontSize: 20,
                                fontWeight: 500,
                                letterSpacing: "-0.015em",
                                color: "var(--ink)",
                              }}
                            >
                              {workspace.displayName}
                            </span>
                            <Chip kind="live">
                              {formatSpeciesLabel(workspace.species)}
                            </Chip>
                          </div>
                          <div
                            className="cs-tiny"
                            style={{ fontSize: 13.5, lineHeight: 1.55 }}
                          >
                            {progressLabel}
                          </div>
                        </div>
                        <span className="cs-tiny" style={{ whiteSpace: "nowrap" }}>
                          {formatDateTime(workspace.updatedAt)}
                        </span>
                      </div>
                    </Link>
                  );
                })}
              </div>
            )}
            <div style={{ padding: "14px 22px" }}>
              <Link
                href="/workspaces/new"
                style={{
                  display: "block",
                  width: "100%",
                  padding: "14px 16px",
                  border: "1.5px dashed var(--line-strong)",
                  borderRadius: "var(--radius-cs)",
                  background: "transparent",
                  fontFamily: "inherit",
                  color: "var(--muted)",
                  cursor: "pointer",
                  fontSize: 13.5,
                  textAlign: "center",
                  textDecoration: "none",
                }}
              >
                + New workspace
              </Link>
            </div>
          </Card>

          <Card>
            <CardHead
              eyebrow="The pipeline"
              title={`${PIPELINE_STAGES.length} stages. ${liveStageCount} live today.`}
              subtitle="Roadmap stays visible so the workflow stays honest."
            />
            <ol
              style={{
                listStyle: "none",
                padding: "6px 14px 14px",
                margin: 0,
              }}
            >
              {PIPELINE_STAGES.map((stage, index) => (
                <li
                  key={stage.id}
                  style={{
                    display: "grid",
                    gridTemplateColumns: "30px 1fr auto",
                    gap: 12,
                    alignItems: "center",
                    padding: "8px 8px",
                    borderRadius: 10,
                    opacity: stage.implementationState === "live" ? 1 : 0.72,
                  }}
                >
                  <span
                    style={{
                      fontFamily: "var(--font-mono)",
                      fontSize: 11,
                      color:
                        stage.implementationState === "live"
                          ? "var(--accent-ink)"
                          : "var(--muted-2)",
                      fontWeight: 600,
                    }}
                  >
                    {String(index + 1).padStart(2, "0")}
                  </span>
                  <span style={{ fontSize: 14.5, fontWeight: 500, color: "var(--ink)" }}>
                    {stage.name}
                  </span>
                  <Chip kind={stage.implementationState === "live" ? "live" : "planned"}>
                    {stage.implementationState}
                  </Chip>
                </li>
              ))}
            </ol>
          </Card>
        </div>

        <div
          style={{
            marginTop: 28,
            textAlign: "center",
            fontSize: 12,
            color: "var(--muted-2)",
          }}
        >
          <MonoLabel>Everything stays on your computer.</MonoLabel>
        </div>
      </div>

      <TweaksPanel />
    </div>
  );
}

function Stat({
  label,
  value,
  hint,
}: {
  label: string;
  value: string;
  hint: string;
}) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 4, minWidth: 120 }}>
      <MonoLabel style={{ whiteSpace: "nowrap" }}>{label}</MonoLabel>
      <span
        style={{
          fontFamily: "var(--font-display)",
          fontSize: 26,
          fontWeight: 400,
          letterSpacing: "-0.015em",
          lineHeight: 1,
          color: "var(--ink)",
        }}
      >
        {value}
      </span>
      <span
        className="cs-tiny"
        style={{ fontSize: 12.5, whiteSpace: "nowrap" }}
      >
        {hint}
      </span>
    </div>
  );
}
