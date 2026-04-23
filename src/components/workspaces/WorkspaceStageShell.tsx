"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import AiReviewStagePanel from "@/components/workspaces/AiReviewStagePanel";
import AlignmentStagePanel from "@/components/workspaces/AlignmentStagePanel";
import AnnotationStagePanel from "@/components/workspaces/AnnotationStagePanel";
import ConstructDesignStagePanel from "@/components/workspaces/ConstructDesignStagePanel";
import ConstructOutputStagePanel from "@/components/workspaces/ConstructOutputStagePanel";
import EpitopeSelectionStagePanel from "@/components/workspaces/EpitopeSelectionStagePanel";
import IngestionStagePanel from "@/components/workspaces/IngestionStagePanel";
import NeoantigenPredictionStagePanel from "@/components/workspaces/NeoantigenPredictionStagePanel";
import VariantCallingStagePanel from "@/components/workspaces/VariantCallingStagePanel";
import TweaksPanel from "@/components/dev/TweaksPanel";
import { api } from "@/lib/api";
import {
  getPipelinePolicy,
  getVisiblePrimaryStages,
  getVisibleResearchStages,
} from "@/lib/pipeline-policy";
import type {
  AiReviewStageSummary,
  AlignmentStageSummary,
  AnnotationStageSummary,
  ConstructOutputStageSummary,
  ConstructStageSummary,
  EpitopeStageSummary,
  NeoantigenStageSummary,
  PipelineStageId,
  VariantCallingStageSummary,
  Workspace,
} from "@/lib/types";
import { PIPELINE_STAGES } from "@/lib/types";

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
  initialAlignmentSummary: AlignmentStageSummary;
  initialVariantCallingSummary: VariantCallingStageSummary;
  initialAnnotationSummary: AnnotationStageSummary;
  initialNeoantigenSummary: NeoantigenStageSummary;
  initialEpitopeSummary: EpitopeStageSummary;
  initialConstructSummary: ConstructStageSummary;
  initialConstructOutputSummary: ConstructOutputStageSummary;
  initialAiReviewSummary: AiReviewStageSummary;
  redirectedFromStageId: PipelineStageId | null;
}

export default function WorkspaceStageShell({
  workspace: initialWorkspace,
  workspaces: initialWorkspaces,
  currentStageId,
  initialAlignmentSummary,
  initialVariantCallingSummary,
  initialAnnotationSummary,
  initialNeoantigenSummary,
  initialEpitopeSummary,
  initialConstructSummary,
  initialConstructOutputSummary,
  initialAiReviewSummary,
  redirectedFromStageId,
}: WorkspaceStageShellProps) {
  const [workspace, setWorkspace] = useState(initialWorkspace);
  const [, setWorkspaces] = useState(
    mergeWorkspaces(initialWorkspaces, initialWorkspace)
  );
  const [alignmentSummary, setAlignmentSummary] = useState(
    initialAlignmentSummary
  );
  const [variantCallingSummary, setVariantCallingSummary] = useState(
    initialVariantCallingSummary
  );
  const [annotationSummary, setAnnotationSummary] = useState(
    initialAnnotationSummary
  );
  const [neoantigenSummary, setNeoantigenSummary] = useState(
    initialNeoantigenSummary
  );
  const [epitopeSummary, setEpitopeSummary] = useState(
    initialEpitopeSummary
  );
  const [constructSummary, setConstructSummary] = useState(
    initialConstructSummary
  );
  const [constructOutputSummary, setConstructOutputSummary] = useState(
    initialConstructOutputSummary
  );
  const [aiReviewSummary, setAiReviewSummary] = useState(
    initialAiReviewSummary
  );
  const stagePolicy = getPipelinePolicy(
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
  const currentStagePolicy = stagePolicy[currentStageId];
  const primaryStages = getVisiblePrimaryStages(stagePolicy);
  const researchStages = getVisibleResearchStages(stagePolicy);
  const redirectNoticeStage = redirectedFromStageId
    ? PIPELINE_STAGES.find((stage) => stage.id === redirectedFromStageId) ?? null
    : null;

  useEffect(() => {
    if (workspace.activeStage === currentStageId || !currentStagePolicy.enterable) {
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
  }, [currentStageId, currentStagePolicy.enterable, workspace]);

  function handleWorkspaceChange(updatedWorkspace: Workspace) {
    setWorkspace(updatedWorkspace);
    setWorkspaces((current) => mergeWorkspaces(current, updatedWorkspace));
    void api
      .getAlignmentStageSummary(updatedWorkspace.id)
      .then((nextAlignment) => {
        setAlignmentSummary(nextAlignment);
        void api
          .getVariantCallingStageSummary(updatedWorkspace.id)
          .then(setVariantCallingSummary)
          .catch(() => {});
        void api
          .getAnnotationStageSummary(updatedWorkspace.id)
          .then(setAnnotationSummary)
          .catch(() => {});
        void api
          .getNeoantigenStageSummary(updatedWorkspace.id)
          .then(setNeoantigenSummary)
          .catch(() => {});
      })
      .catch(() => {});
  }

  return (
    <div className="cs-theme">
      <div className="cs-app">
        <aside className="cs-sidebar">
          <Link
            href="/"
            className="cs-brand"
            style={{ textDecoration: "none", color: "inherit" }}
          >
            <div className="cs-brand-mark" />
            <div style={{ display: "flex", flexDirection: "column" }}>
              <span className="cs-brand-name">cancerstudio</span>
              <span
                className="cs-mono-label"
                style={{ fontSize: 9, letterSpacing: "0.18em" }}
              >
                v0.4
              </span>
            </div>
          </Link>

          <div>
            <div className="cs-nav-sec-label">Workspace</div>
            <Link
              href="/"
              className={`cs-nav-item`}
              style={{ textDecoration: "none" }}
            >
              <span className="cs-step">↖</span>
              <span>All workspaces</span>
            </Link>
            <Link
              href="/workspaces/new"
              className="cs-nav-item"
              style={{ textDecoration: "none" }}
            >
              <span className="cs-step">+</span>
              <span>New workspace</span>
            </Link>
          </div>

          <div>
            <div
              className="cs-nav-sec-label"
              style={{
                overflow: "hidden",
                textOverflow: "ellipsis",
                whiteSpace: "nowrap",
              }}
              title={workspace.displayName}
            >
              {workspace.displayName}
            </div>
            {primaryStages.map((stage, index) => {
              const policy = stagePolicy[stage.id];
              const step = String(index + 1).padStart(2, "0");
              const isActive = stage.id === currentStageId;
              const isLive = stage.implementationState === "live";
              const enterable = policy.enterable && isLive;

              if (!enterable) {
                return (
                  <div
                    key={stage.id}
                    className={`cs-nav-item is-disabled`}
                    aria-disabled
                    title={policy.blockedReason ?? "Planned stage"}
                  >
                    <span className="cs-step">{step}</span>
                    <span style={{ flex: 1 }}>{stage.name}</span>
                    <span
                      style={{
                        fontSize: 9,
                        fontFamily: "var(--font-mono)",
                        color: "var(--muted-2)",
                        letterSpacing: "0.14em",
                      }}
                    >
                      SOON
                    </span>
                  </div>
                );
              }

              return (
                <Link
                  key={stage.id}
                  href={`/workspaces/${workspace.id}/${stage.id}`}
                  className={`cs-nav-item ${isActive ? "is-active" : ""}`}
                >
                  <span className="cs-step">{step}</span>
                  <span style={{ flex: 1 }}>{stage.name}</span>
                </Link>
              );
            })}
          </div>

          {researchStages.length > 0 ? (
            <div>
              <div className="cs-nav-sec-label">Later research</div>
              {researchStages.map((stage, index) => (
                <div
                  key={stage.id}
                  className="cs-nav-item is-disabled"
                  aria-disabled
                  title="Research-only — not available yet"
                >
                  <span className="cs-step">R{index + 1}</span>
                  <span style={{ flex: 1 }}>{stage.name}</span>
                  <span
                    style={{
                      fontSize: 9,
                      fontFamily: "var(--font-mono)",
                      color: "var(--muted-2)",
                      letterSpacing: "0.14em",
                    }}
                  >
                    R&amp;D
                  </span>
                </div>
              ))}
            </div>
          ) : null}

        </aside>

        <main>
          <div className="cs-view cs-fade-in" key={`${workspace.id}-${currentStageId}`}>
            {redirectNoticeStage ? (
              <div
                className="cs-callout cs-callout-warm"
                style={{ marginBottom: 22 }}
              >
                <div className="cs-dot" style={{ color: "var(--warm)" }} />
                <div style={{ flex: 1 }}>
                  <div
                    style={{ fontSize: 15, fontWeight: 500, color: "var(--ink)" }}
                  >
                    {redirectNoticeStage.name} is on the roadmap, but it is not
                    usable yet.
                  </div>
                  <p
                    className="cs-tiny"
                    style={{ margin: "4px 0 0", fontSize: 13.5 }}
                  >
                    We brought you back to the current working step so the
                    workflow stays simple.
                  </p>
                </div>
              </div>
            ) : null}

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
            ) : currentStageId === "variant-calling" ? (
              <VariantCallingStagePanel
                key={workspace.id}
                workspace={workspace}
                initialSummary={variantCallingSummary}
              />
            ) : currentStageId === "annotation" ? (
              <AnnotationStagePanel
                key={workspace.id}
                workspace={workspace}
                initialSummary={annotationSummary}
              />
            ) : currentStageId === "neoantigen-prediction" ? (
              <NeoantigenPredictionStagePanel
                key={workspace.id}
                workspace={workspace}
                initialSummary={neoantigenSummary}
                onSummaryChange={setNeoantigenSummary}
              />
            ) : currentStageId === "epitope-selection" ? (
              <EpitopeSelectionStagePanel
                key={workspace.id}
                workspace={workspace}
                initialSummary={epitopeSummary}
                onSummaryChange={setEpitopeSummary}
              />
            ) : currentStageId === "construct-design" ? (
              <ConstructDesignStagePanel
                key={workspace.id}
                workspace={workspace}
                initialSummary={constructSummary}
                onSummaryChange={setConstructSummary}
              />
            ) : currentStageId === "construct-output" ? (
              <ConstructOutputStagePanel
                key={workspace.id}
                workspace={workspace}
                initialSummary={constructOutputSummary}
                onSummaryChange={setConstructOutputSummary}
              />
            ) : currentStageId === "ai-review" ? (
              <AiReviewStagePanel
                key={workspace.id}
                workspace={workspace}
                initialSummary={aiReviewSummary}
                onSummaryChange={setAiReviewSummary}
              />
            ) : null}
          </div>
        </main>
      </div>

      <TweaksPanel />
    </div>
  );
}
