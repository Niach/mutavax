"use client";

import { FileText, Upload } from "lucide-react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import type { SampleLane } from "@/lib/types";
import { formatBytes } from "@/lib/workspace-utils";

import {
  type DetectedReadPair,
  type LaneStagingValidation,
} from "./inferReadPair";

interface LaneStagingPanelProps {
  sampleLane: SampleLane;
  files: File[];
  detection: Record<string, DetectedReadPair>;
  validation: LaneStagingValidation;
  starting: boolean;
  dragActive: boolean;
  fingerprintOf: (file: File) => string;
  onAddFiles: () => void;
  onDropFiles: (files: FileList | File[]) => void;
  onRemoveFile: (fingerprint: string) => void;
  onStartUpload: () => void;
  onDiscardStaging: () => void;
  setDragActive: (active: boolean) => void;
}

export function LaneStagingPanel({
  sampleLane,
  files,
  detection,
  validation,
  starting,
  dragActive,
  fingerprintOf,
  onAddFiles,
  onDropFiles,
  onRemoveFile,
  onStartUpload,
  onDiscardStaging,
  setDragActive,
}: LaneStagingPanelProps) {
  const ready = validation.state === "ready" && !starting;
  const blocking = validation.state !== "ready" && validation.state !== "empty";
  const stemLabel = validation.sampleStem ? validation.sampleStem : "—";

  return (
    <div
      data-testid={`${sampleLane}-staging-panel`}
      data-validation-state={validation.state}
      className="border-t border-black/8 px-4 py-4 sm:px-6"
    >
      <div className="flex items-baseline justify-between gap-3">
        <p className="font-mono text-[10px] tracking-[0.22em] text-slate-500 uppercase tabular-nums">
          Staging <span className="text-slate-300">·</span>{" "}
          <span className="text-slate-700">{stemLabel}</span>
        </p>
        <button
          type="button"
          onClick={onDiscardStaging}
          className="font-mono text-[10px] tracking-[0.18em] text-slate-400 uppercase transition hover:text-slate-700 focus-visible:text-slate-900 focus-visible:outline-none"
        >
          clear
        </button>
      </div>

      <ul className="mt-3 space-y-2">
        {files.map((file) => {
          const fp = fingerprintOf(file);
          const pair = detection[fp] ?? "unknown";
          return (
            <li
              key={fp}
              className="flex items-center justify-between gap-3 text-sm"
            >
              <p className="flex min-w-0 items-center gap-2 text-slate-700">
                <FileText
                  className="size-3.5 shrink-0 text-slate-400"
                  strokeWidth={1.5}
                />
                <span className="truncate">{file.name}</span>
              </p>
              <div className="flex shrink-0 items-center gap-3 font-mono text-[10px] text-slate-400 tabular-nums">
                <span
                  className={cn(
                    "uppercase",
                    pair === "unknown" ? "text-slate-300" : "text-slate-600"
                  )}
                >
                  {pair === "unknown" ? "—" : pair}
                </span>
                <span>{formatBytes(file.size)}</span>
                <button
                  type="button"
                  onClick={() => onRemoveFile(fp)}
                  className="font-mono text-[10px] tracking-[0.18em] uppercase transition hover:text-slate-700 focus-visible:text-slate-900 focus-visible:outline-none"
                  aria-label={`Remove ${file.name}`}
                >
                  remove
                </button>
              </div>
            </li>
          );
        })}
      </ul>

      <div className="mt-3">
        <div
          role="button"
          tabIndex={0}
          onClick={onAddFiles}
          onKeyDown={(event) => {
            if (event.key === "Enter" || event.key === " ") {
              event.preventDefault();
              onAddFiles();
            }
          }}
          onDragOver={(event) => {
            event.preventDefault();
            setDragActive(true);
          }}
          onDragLeave={(event) => {
            event.preventDefault();
            if (event.currentTarget.contains(event.relatedTarget as Node | null)) {
              return;
            }
            setDragActive(false);
          }}
          onDrop={(event) => {
            event.preventDefault();
            setDragActive(false);
            onDropFiles(event.dataTransfer.files);
          }}
          className={cn(
            "flex items-center justify-between gap-3 rounded-2xl px-3 py-2.5 text-sm transition outline-none",
            dragActive
              ? "bg-slate-50 text-slate-900"
              : "text-slate-500 hover:bg-slate-50/80 hover:text-slate-900",
            "focus-visible:bg-slate-50 focus-visible:text-slate-900"
          )}
        >
          <div className="flex items-center gap-3">
            <Upload className="size-4 shrink-0 text-slate-400" strokeWidth={1.5} />
            <span>Add more files</span>
          </div>
          <span className="font-mono text-[10px] tracking-[0.18em] text-slate-400 uppercase">
            Drop or browse
          </span>
        </div>
      </div>

      <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
        <p
          className={cn(
            "text-xs leading-5",
            blocking ? "text-rose-700" : "text-slate-500"
          )}
        >
          {validation.reason ??
            (ready
              ? `${files.length} file${files.length === 1 ? "" : "s"} ready · paired-end detected`
              : "Add files to begin")}
        </p>
        <Button
          variant="outline"
          size="sm"
          onClick={onStartUpload}
          disabled={!ready}
          data-testid={`${sampleLane}-staging-start-upload`}
        >
          {starting ? "Starting…" : "Start upload"}
        </Button>
      </div>
    </div>
  );
}
