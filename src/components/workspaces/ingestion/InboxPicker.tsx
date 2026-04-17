"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { FolderOpen, RefreshCw, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { api, type InboxEntry } from "@/lib/api";
import { getDesktopBridge } from "@/lib/desktop";
import { formatBytes } from "@/lib/workspace-utils";
import { cn } from "@/lib/utils";

interface InboxPickerProps {
  open: boolean;
  laneLabel: string;
  onClose: () => void;
  onConfirm: (paths: string[]) => void;
}

export default function InboxPicker({
  open,
  laneLabel,
  onClose,
  onConfirm,
}: InboxPickerProps) {
  const [entries, setEntries] = useState<InboxEntry[]>([]);
  const [root, setRoot] = useState<string | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const listing = await api.listInbox();
      setRoot(listing.root);
      setEntries(listing.entries);
      // Drop any selections that no longer exist on disk.
      setSelected((prev) => {
        const next = new Set<string>();
        for (const path of prev) {
          if (listing.entries.some((entry) => entry.path === path)) {
            next.add(path);
          }
        }
        return next;
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to read inbox.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (open) {
      void refresh();
    } else {
      setSelected(new Set());
      setError(null);
    }
  }, [open, refresh]);

  const desktop = useMemo(() => getDesktopBridge(), []);

  const toggle = (path: string) => {
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(path)) next.delete(path);
      else next.add(path);
      return next;
    });
  };

  const handleReveal = useCallback(async () => {
    if (!desktop || !root) return;
    await desktop.openPath(root);
  }, [desktop, root]);

  const handleConfirm = () => {
    if (selected.size === 0) return;
    onConfirm(Array.from(selected));
  };

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-stone-900/40 px-4"
      role="dialog"
      aria-modal="true"
      aria-label={`Pick files from inbox for the ${laneLabel} lane`}
    >
      <div className="w-full max-w-2xl rounded-2xl border border-stone-200 bg-white shadow-xl">
        <header className="flex items-center justify-between border-b border-stone-200 px-5 py-3">
          <div>
            <h2 className="text-[15px] font-semibold text-stone-900">
              Pick files for the {laneLabel} sample
            </h2>
            <p className="mt-0.5 text-[12px] text-stone-500">
              Files in your inbox folder. Drop new files there, then click Refresh.
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="rounded-full p-1 text-stone-400 hover:bg-stone-100 hover:text-stone-600"
          >
            <X className="h-4 w-4" />
          </button>
        </header>

        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-stone-100 px-5 py-2 text-[12px] text-stone-500">
          <span className="truncate font-mono text-[11px] text-stone-500">
            {root ?? "—"}
          </span>
          <div className="flex items-center gap-2">
            <Button
              type="button"
              size="sm"
              variant="ghost"
              onClick={() => void refresh()}
              disabled={loading}
            >
              <RefreshCw className={cn("mr-1.5 h-3.5 w-3.5", loading && "animate-spin")} />
              Refresh
            </Button>
            {desktop && root ? (
              <Button
                type="button"
                size="sm"
                variant="outline"
                onClick={() => void handleReveal()}
              >
                <FolderOpen className="mr-1.5 h-3.5 w-3.5" />
                Reveal in file manager
              </Button>
            ) : null}
          </div>
        </div>

        <div className="max-h-[50vh] overflow-y-auto px-5 py-3">
          {error ? (
            <p className="rounded-md border border-rose-200 bg-rose-50 px-3 py-2 text-[12px] text-rose-700">
              {error}
            </p>
          ) : entries.length === 0 ? (
            <p className="py-8 text-center text-[13px] text-stone-500">
              {loading
                ? "Reading inbox…"
                : "No sequencing files found yet. Drop FASTQ, BAM, or CRAM files into the inbox folder above, then click Refresh."}
            </p>
          ) : (
            <ul className="divide-y divide-stone-100">
              {entries.map((entry) => {
                const isSelected = selected.has(entry.path);
                return (
                  <li key={entry.path}>
                    <label
                      className={cn(
                        "flex cursor-pointer items-center gap-3 rounded-md px-2 py-2 hover:bg-stone-50",
                        isSelected && "bg-emerald-50/60 hover:bg-emerald-50"
                      )}
                    >
                      <input
                        type="checkbox"
                        checked={isSelected}
                        onChange={() => toggle(entry.path)}
                        className="h-4 w-4 accent-emerald-600"
                      />
                      <div className="min-w-0 flex-1">
                        <div className="flex items-baseline gap-2 truncate text-[13px] font-medium text-stone-900">
                          <span className="truncate">{entry.name}</span>
                          <span className="rounded bg-stone-100 px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-wider text-stone-600">
                            {entry.kind}
                          </span>
                        </div>
                        <div className="mt-0.5 truncate font-mono text-[11px] text-stone-500">
                          {formatBytes(entry.sizeBytes)} · {entry.modifiedAt.slice(0, 19).replace("T", " ")}
                        </div>
                      </div>
                    </label>
                  </li>
                );
              })}
            </ul>
          )}
        </div>

        <footer className="flex items-center justify-between gap-3 border-t border-stone-200 px-5 py-3">
          <span className="text-[12px] text-stone-500">
            {selected.size === 0
              ? "Pick one or more files."
              : `${selected.size} file${selected.size === 1 ? "" : "s"} selected.`}
          </span>
          <div className="flex items-center gap-2">
            <Button type="button" variant="ghost" size="sm" onClick={onClose}>
              Cancel
            </Button>
            <Button
              type="button"
              size="sm"
              onClick={handleConfirm}
              disabled={selected.size === 0}
            >
              Use selected
            </Button>
          </div>
        </footer>
      </div>
    </div>
  );
}
