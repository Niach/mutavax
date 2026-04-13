"use client";

import { useCallback, useEffect, useState } from "react";

import { api, MissingToolsError } from "@/lib/api";
import { getDesktopBridge } from "@/lib/desktop";
import type { SampleLane, Workspace } from "@/lib/types";

import { IngestionHeader } from "./ingestion/IngestionHeader";
import { LaneAccordionSection } from "./ingestion/LaneAccordionSection";
import {
  LANES,
  emptyPreviewState,
  sourceFilesForLane,
  type PreviewState,
} from "./ingestion/lane-utils";

interface IngestionStagePanelProps {
  workspace: Workspace;
  onWorkspaceChange: (workspace: Workspace) => void;
}

export default function IngestionStagePanel({
  workspace,
  onWorkspaceChange,
}: IngestionStagePanelProps) {
  const [activeLane, setActiveLane] = useState<SampleLane>("normal");
  const [submittingLane, setSubmittingLane] = useState<SampleLane | null>(null);
  const [laneErrors, setLaneErrors] = useState<Record<SampleLane, string | null>>({
    tumor: null,
    normal: null,
  });
  const [previewStates, setPreviewStates] = useState<Record<SampleLane, PreviewState>>({
    tumor: emptyPreviewState(),
    normal: emptyPreviewState(),
  });
  const [desktopAvailable, setDesktopAvailable] = useState(false);
  const [missingTools, setMissingTools] = useState<MissingToolsError | null>(null);

  useEffect(() => {
    setDesktopAvailable(Boolean(getDesktopBridge()));
  }, []);

  const alignmentState = workspace.ingestion.readyForAlignment ? "unlocked" : "locked";

  useEffect(() => {
    if (!LANES.some((lane) => workspace.ingestion.lanes[lane].status === "normalizing")) {
      return;
    }

    const timer = window.setInterval(() => {
      void api
        .getWorkspace(workspace.id)
        .then(onWorkspaceChange)
        .catch(() => {});
    }, 2200);

    return () => window.clearInterval(timer);
  }, [onWorkspaceChange, workspace.id, workspace.ingestion]);

  useEffect(() => {
    setPreviewStates((current) => {
      const next = { ...current };
      let changed = false;

      for (const lane of LANES) {
        const summary = workspace.ingestion.lanes[lane];
        const existing = current[lane];

        if (!summary.readyForAlignment) {
          if (
            existing.phase !== "idle" ||
            existing.data !== null ||
            existing.error !== null
          ) {
            next[lane] = emptyPreviewState();
            changed = true;
          }
          continue;
        }

        if (existing.data && existing.data.batchId !== summary.activeBatchId) {
          next[lane] = emptyPreviewState();
          changed = true;
        }
      }

      return changed ? next : current;
    });
  }, [workspace.ingestion]);

  const loadLanePreview = useCallback(
    async (sampleLane: SampleLane) => {
      setPreviewStates((current) => ({
        ...current,
        [sampleLane]: {
          phase: "loading",
          data: null,
          error: null,
        },
      }));

      try {
        const preview = await api.getIngestionLanePreview(workspace.id, sampleLane);
        setPreviewStates((current) => ({
          ...current,
          [sampleLane]: {
            phase: "ready",
            data: preview,
            error: null,
          },
        }));
      } catch (error) {
        setPreviewStates((current) => ({
          ...current,
          [sampleLane]: {
            phase: "failed",
            data: null,
            error:
              error instanceof Error
                ? error.message
                : "Unable to load the preview.",
          },
        }));
      }
    },
    [workspace.id]
  );

  useEffect(() => {
    for (const lane of LANES) {
      if (!workspace.ingestion.lanes[lane].readyForAlignment) {
        continue;
      }
      if (previewStates[lane].phase !== "idle") {
        continue;
      }
      void loadLanePreview(lane);
    }
  }, [loadLanePreview, previewStates, workspace.ingestion]);

  async function registerPaths(sampleLane: SampleLane, paths: string[]) {
    if (!paths.length) {
      return;
    }

    setSubmittingLane(sampleLane);
    setLaneErrors((current) => ({ ...current, [sampleLane]: null }));
    setMissingTools(null);
    try {
      const updatedWorkspace = await api.registerLocalLaneFiles(workspace.id, {
        sampleLane,
        paths,
      });
      onWorkspaceChange(updatedWorkspace);
      setPreviewStates((current) => ({
        ...current,
        [sampleLane]: emptyPreviewState(),
      }));
    } catch (error) {
      if (error instanceof MissingToolsError) {
        setMissingTools(error);
      } else {
        setLaneErrors((current) => ({
          ...current,
          [sampleLane]:
            error instanceof Error ? error.message : "Unable to register files.",
        }));
      }
    } finally {
      setSubmittingLane(null);
    }
  }

  async function handlePick(sampleLane: SampleLane) {
    setActiveLane(sampleLane);
    const desktop = getDesktopBridge();
    if (!desktop) {
      setLaneErrors((current) => ({
        ...current,
        [sampleLane]: "Open this workspace in the desktop app to pick local files.",
      }));
      return;
    }
    const selected = await desktop.pickSequencingFiles();
    await registerPaths(
      sampleLane,
      selected.map((file) => file.path)
    );
  }

  return (
    <div className="space-y-3">
      <IngestionHeader alignmentState={alignmentState} />

      {missingTools ? <MissingToolsCallout error={missingTools} /> : null}

      <div className="space-y-2">
        {LANES.map((lane, index) => {
          const summary = workspace.ingestion.lanes[lane];
          const files = sourceFilesForLane(workspace, lane);
          const isActive = activeLane === lane;
          return (
            <LaneAccordionSection
              key={lane}
              lane={lane}
              stepIndex={index}
              workspace={workspace}
              summary={summary}
              files={files}
              isExpanded={isActive}
              onHeaderClick={() => setActiveLane(lane)}
              onPickFiles={() => void handlePick(lane)}
              isSubmitting={submittingLane === lane}
              laneError={laneErrors[lane]}
              previewState={previewStates[lane]}
              onRetryPreview={() => void loadLanePreview(lane)}
              desktopAvailable={desktopAvailable}
              showLegend={isActive && previewStates[lane].phase === "ready"}
            />
          );
        })}
      </div>
    </div>
  );
}

function MissingToolsCallout({ error }: { error: MissingToolsError }) {
  return (
    <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-3 text-[13px] text-amber-900">
      <div className="font-medium">
        {error.tools.length === 1
          ? `${error.tools[0]} is not installed locally.`
          : `These tools are not installed locally: ${error.tools.join(", ")}.`}
      </div>
      <p className="mt-1 text-amber-800">
        Install them and reload, then try again.
      </p>
      <ul className="mt-2 space-y-1">
        {error.hints.map((hint, index) => (
          <li
            key={index}
            className="overflow-x-auto rounded border border-amber-200/70 bg-white/70 px-2 py-1 font-mono text-[11px] leading-5 text-stone-700"
          >
            {hint}
          </li>
        ))}
      </ul>
      <p className="mt-2 text-[12px] text-amber-700">
        See README → System requirements for the full install guide.
      </p>
    </div>
  );
}
