import type { WorkspaceFile } from "@/lib/types";

import { filePathForDisplay } from "./lane-utils";

export function SourceFileCard({ files }: { files: WorkspaceFile[] }) {
  if (files.length === 0) {
    return null;
  }

  return (
    <ul className="overflow-hidden rounded-lg border border-stone-200 bg-white">
      {files.map((file) => (
        <li
          key={file.id}
          className="flex items-center justify-between gap-3 border-t border-stone-100 px-3 py-2 first:border-t-0"
        >
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2">
              <span className="truncate text-[13px] font-medium text-stone-800">
                {file.filename}
              </span>
              {file.readPair !== "unknown" ? (
                <span className="font-mono text-[10px] tracking-[0.12em] text-stone-400">
                  {file.readPair}
                </span>
              ) : null}
            </div>
            <div className="mt-0.5 truncate font-mono text-[11px] text-stone-400">
              {filePathForDisplay(file)}
            </div>
          </div>
          <span className="shrink-0 font-mono text-[10px] uppercase tracking-[0.14em] text-stone-400">
            {file.format}
          </span>
        </li>
      ))}
    </ul>
  );
}
