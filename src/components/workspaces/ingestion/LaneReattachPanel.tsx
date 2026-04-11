"use client";

import { FileText, Upload } from "lucide-react";

import { cn } from "@/lib/utils";
import type { SampleLane, UploadSession } from "@/lib/types";
import { formatBytes } from "@/lib/workspace-utils";

interface LaneReattachPanelProps {
  sampleLane: SampleLane;
  session: UploadSession;
  dragActive: boolean;
  onBrowse: () => void;
  onDropFiles: (files: FileList | File[]) => void;
  onDiscardSession: () => void;
  setDragActive: (active: boolean) => void;
}

export function LaneReattachPanel({
  sampleLane,
  session,
  dragActive,
  onBrowse,
  onDropFiles,
  onDiscardSession,
  setDragActive,
}: LaneReattachPanelProps) {
  return (
    <div
      data-testid={`${sampleLane}-reattach-panel`}
      className="border-t border-black/8 px-4 py-4 sm:px-6"
    >
      <div className="flex items-baseline justify-between gap-3">
        <p className="text-sm font-medium text-slate-700">
          Reattach files to resume
        </p>
        <p className="font-mono text-[10px] tracking-[0.22em] text-slate-400 uppercase tabular-nums">
          {session.files.length} file{session.files.length === 1 ? "" : "s"}
        </p>
      </div>
      <p className="mt-1 max-w-2xl text-xs leading-5 text-slate-500">
        Pick the same files from your machine — uploads pick up from the next
        missing chunk. Nothing is re-sent.
      </p>

      <ul className="mt-3 space-y-2">
        {session.files.map((file) => {
          const percent =
            file.sizeBytes === 0
              ? 0
              : Math.min(100, (file.uploadedBytes / file.sizeBytes) * 100);
          return (
            <li
              key={file.id}
              className="flex items-center justify-between gap-3 text-sm"
            >
              <p className="flex min-w-0 items-center gap-2 text-slate-700">
                <FileText
                  className="size-3.5 shrink-0 text-slate-400"
                  strokeWidth={1.5}
                />
                <span className="truncate">{file.filename}</span>
              </p>
              <div className="flex shrink-0 items-center gap-3 font-mono text-[10px] text-slate-400 tabular-nums">
                <span className={file.readPair === "unknown" ? "text-slate-300" : "text-slate-600"}>
                  {file.readPair === "unknown" ? "—" : file.readPair}
                </span>
                <span>
                  {formatBytes(file.uploadedBytes)} of {formatBytes(file.sizeBytes)}
                </span>
                <span className="w-9 text-right text-slate-600">
                  {Math.round(percent)}%
                </span>
              </div>
            </li>
          );
        })}
      </ul>

      <div className="mt-3">
        <div
          role="button"
          tabIndex={0}
          onClick={onBrowse}
          onKeyDown={(event) => {
            if (event.key === "Enter" || event.key === " ") {
              event.preventDefault();
              onBrowse();
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
            <span>Drop the same files here, or browse</span>
          </div>
          <span className="font-mono text-[10px] tracking-[0.18em] text-slate-400 uppercase">
            Resume
          </span>
        </div>
      </div>

      <div className="mt-3 flex justify-end">
        <button
          type="button"
          onClick={onDiscardSession}
          data-testid={`${sampleLane}-reattach-discard`}
          className="font-mono text-[10px] tracking-[0.18em] text-slate-400 uppercase transition hover:text-slate-700 focus-visible:text-slate-900 focus-visible:outline-none"
        >
          discard session and start over
        </button>
      </div>
    </div>
  );
}
