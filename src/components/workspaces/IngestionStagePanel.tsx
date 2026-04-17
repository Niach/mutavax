"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { api, MissingToolsError } from "@/lib/api";
import type { SampleLane, Workspace } from "@/lib/types";

import { IngestionHeader } from "./ingestion/IngestionHeader";
import InboxPicker from "./ingestion/InboxPicker";
import { LaneAccordionSection } from "./ingestion/LaneAccordionSection";
import { formatLaneLabel } from "@/lib/workspace-utils";
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
  const [missingTools, setMissingTools] = useState<MissingToolsError | null>(null);
  const [pickerLane, setPickerLane] = useState<SampleLane | null>(null);

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

  function handlePick(sampleLane: SampleLane) {
    setActiveLane(sampleLane);
    setPickerLane(sampleLane);
  }

  async function handlePickerConfirm(paths: string[]) {
    if (!pickerLane) return;
    const lane = pickerLane;
    setPickerLane(null);
    await registerPaths(lane, paths);
  }

  return (
    <div className="space-y-3">
      <IngestionHeader alignmentState={alignmentState} />

      <section className="rounded-2xl border border-stone-200 bg-white px-5 py-4">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="max-w-2xl">
            <h3 className="text-[15px] font-semibold text-stone-900">What you need</h3>
            <ul className="mt-2 space-y-1 text-[13px] leading-6 text-stone-600">
              <li>One tumor sample and one healthy sample.</li>
              <li>For each sample: a paired FASTQ set or a single BAM/CRAM file.</li>
              <li>Everything stays on your machine while we prepare the reads.</li>
            </ul>
          </div>
          {workspace.ingestion.readyForAlignment ? (
            <Link
              href={`/workspaces/${workspace.id}/alignment`}
              data-testid="ingestion-continue-link"
              className="inline-flex items-center rounded-full bg-emerald-600 px-4 py-2 text-sm font-medium text-white transition hover:bg-emerald-500"
            >
              Continue to alignment
            </Link>
          ) : null}
        </div>
      </section>

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
              onPickFiles={() => handlePick(lane)}
              isSubmitting={submittingLane === lane}
              laneError={laneErrors[lane]}
              previewState={previewStates[lane]}
              onRetryPreview={() => void loadLanePreview(lane)}
              desktopAvailable={true}
              showLegend={isActive && previewStates[lane].phase === "ready"}
            />
          );
        })}
      </div>

      <InboxPicker
        open={pickerLane !== null}
        laneLabel={pickerLane ? formatLaneLabel(pickerLane).toLowerCase() : ""}
        onClose={() => setPickerLane(null)}
        onConfirm={(paths) => void handlePickerConfirm(paths)}
      />
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
