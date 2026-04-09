"use client";

import { useEffect, useRef, useState } from "react";
import {
  ArrowUpToLine,
  CircleAlert,
  FileArchive,
  FileCode2,
  FileSpreadsheet,
  LoaderCircle,
  Upload,
} from "lucide-react";

import { api } from "@/lib/api";
import type { Workspace } from "@/lib/types";
import {
  analyzeWorkspace,
  formatBytes,
  formatDateTime,
} from "@/lib/workspace-utils";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";

interface IngestionStagePanelProps {
  workspace: Workspace;
  onWorkspaceChange: (workspace: Workspace) => void;
}

export default function IngestionStagePanel({
  workspace,
  onWorkspaceChange,
}: IngestionStagePanelProps) {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [isDragging, setIsDragging] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const readiness = analyzeWorkspace(workspace);

  useEffect(() => {
    if (workspace.ingestion.status !== "normalizing") {
      return;
    }

    const interval = window.setInterval(() => {
      void api
        .getWorkspace(workspace.id)
        .then((updatedWorkspace) => {
          onWorkspaceChange(updatedWorkspace);
          if (updatedWorkspace.ingestion.status !== "normalizing") {
            window.clearInterval(interval);
          }
        })
        .catch(() => {});
    }, 2500);

    return () => window.clearInterval(interval);
  }, [onWorkspaceChange, workspace.id, workspace.ingestion.status]);

  async function uploadFiles(files: FileList | File[] | null) {
    const selectedFiles = Array.from(files ?? []);
    if (selectedFiles.length === 0) return;

    setError(null);
    setMessage(null);
    setIsUploading(true);

    try {
      const updatedWorkspace = await api.uploadWorkspaceFiles(
        workspace.id,
        selectedFiles
      );
      onWorkspaceChange(updatedWorkspace);
      setMessage(
        `${selectedFiles.length} file${selectedFiles.length === 1 ? "" : "s"} uploaded.`
      );
    } catch (uploadError) {
      setError(
        uploadError instanceof Error
          ? uploadError.message
          : "Unable to upload files"
      );
    } finally {
      setIsUploading(false);
    }
  }

  return (
    <div className="space-y-4">
      <input
        ref={fileInputRef}
        type="file"
        multiple
        accept=".fastq,.fq,.fastq.gz,.fq.gz,.bam,.cram"
        className="hidden"
        onChange={(event) => {
          void uploadFiles(event.target.files);
          event.target.value = "";
        }}
      />

      <div
        role="button"
        tabIndex={0}
        onClick={() => fileInputRef.current?.click()}
        onKeyDown={(event) => {
          if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            fileInputRef.current?.click();
          }
        }}
        onDragOver={(event) => {
          event.preventDefault();
          setIsDragging(true);
        }}
        onDragLeave={(event) => {
          event.preventDefault();
          if (event.currentTarget.contains(event.relatedTarget as Node | null))
            return;
          setIsDragging(false);
        }}
        onDrop={(event) => {
          event.preventDefault();
          setIsDragging(false);
          void uploadFiles(event.dataTransfer.files);
        }}
        className={cn(
          "flex w-full flex-col items-center justify-center gap-4 rounded-[28px] border border-dashed px-6 py-12 text-center transition",
          isDragging
            ? "border-emerald-600 bg-emerald-50"
            : "border-black/12 bg-white"
        )}
      >
        <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-emerald-100 text-emerald-700">
          {isUploading ? (
            <LoaderCircle className="size-5 animate-spin" />
          ) : (
            <Upload className="size-5" />
          )}
        </div>
        <p className="text-lg font-semibold">
          {isUploading
            ? "Uploading your batch..."
            : "Drop sequencing files here or browse"}
        </p>
        <p className="max-w-xl text-sm text-muted-foreground">
          Preferred input is paired FASTQ. We also accept BAM and CRAM, then
          normalize the latest batch into canonical paired FASTQ.gz for
          alignment.
        </p>
        <Button variant="outline" size="sm" disabled={isUploading}>
          <ArrowUpToLine className="size-4" />
          Choose files
        </Button>
      </div>

      <div className="grid gap-4 lg:grid-cols-[1.2fr_0.8fr]">
        <Card className="bg-white">
          <CardHeader>
            <CardTitle>What this step expects</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="flex items-start gap-3 rounded-2xl bg-emerald-50 p-3">
              <FileArchive className="mt-0.5 size-4 text-emerald-700" />
              <div>
                <p className="text-sm font-medium">Preferred: paired FASTQ</p>
                <p className="text-sm text-muted-foreground">
                  `.fastq.gz` and `.fq.gz` can become alignment-ready
                  immediately when both reads are present.
                </p>
              </div>
            </div>
            <div className="flex items-start gap-3 rounded-2xl bg-slate-50 p-3">
              <FileSpreadsheet className="mt-0.5 size-4 text-slate-700" />
              <div>
                <p className="text-sm font-medium">Also accepted: BAM and CRAM</p>
                <p className="text-sm text-muted-foreground">
                  We convert alignment containers into canonical `R1` and `R2`
                  FASTQ.gz outputs in the background.
                </p>
              </div>
            </div>
            <div className="flex items-start gap-3 rounded-2xl bg-amber-50 p-3">
              <FileCode2 className="mt-0.5 size-4 text-amber-700" />
              <div>
                <p className="text-sm font-medium">Next-stage handoff</p>
                <p className="text-sm text-muted-foreground">
                  Alignment only starts from canonical paired FASTQ.gz, so
                  ingestion stays active until both `R1` and `R2` are ready.
                </p>
              </div>
            </div>
          </CardContent>
        </Card>

        <Card className="bg-slate-950 text-slate-100">
          <CardHeader>
            <CardTitle className="text-slate-100">Current batch</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="flex items-center justify-between">
              <span className="text-sm text-slate-300">Status</span>
              <Badge
                variant="secondary"
                className="bg-white/12 text-white hover:bg-white/12"
              >
                {workspace.ingestion.status.replace("-", " ")}
              </Badge>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-sm text-slate-300">Source files</span>
              <span className="text-sm font-medium">
                {workspace.ingestion.sourceFileCount}
              </span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-sm text-slate-300">Canonical FASTQ</span>
              <span className="text-sm font-medium">
                {workspace.ingestion.canonicalFileCount}
              </span>
            </div>
            <div className="rounded-2xl bg-white/8 p-3 text-sm text-slate-200">
              {readiness.readyForAlignment ? (
                "Canonical paired FASTQ is ready for alignment."
              ) : readiness.status === "normalizing" ? (
                "Normalization is running for the latest upload batch."
              ) : readiness.hasFiles ? (
                `Waiting for ${readiness.missingPairs.join(
                  " + "
                )} in canonical FASTQ.`
              ) : (
                "Upload a first batch to start normalization."
              )}
            </div>
            {workspace.ingestion.updatedAt && (
              <p className="text-xs text-slate-400">
                Updated {formatDateTime(workspace.ingestion.updatedAt)}
              </p>
            )}
          </CardContent>
        </Card>
      </div>

      {message && (
        <div className="rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-800">
          {message}
        </div>
      )}
      {error && (
        <div className="rounded-lg border border-destructive/20 bg-destructive/10 px-3 py-2 text-sm text-destructive">
          {error}
        </div>
      )}

      {readiness.failedFiles.length > 0 && (
        <div className="rounded-2xl border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-900">
          <div className="mb-1 flex items-center gap-2 font-medium">
            <CircleAlert className="size-4" />
            Normalization needs attention
          </div>
          <p>
            One or more files in the latest batch failed during conversion.
            Review the file list below for the returned error.
          </p>
        </div>
      )}

      {readiness.hasFiles && (
        <div className="grid gap-4 xl:grid-cols-2">
          <BatchFileGroup
            title="Uploaded source files"
            description="Original files stored for this batch."
            files={readiness.sourceFiles}
            emptyMessage="No source files in the active batch yet."
          />
          <BatchFileGroup
            title="Canonical FASTQ outputs"
            description="Derived paired FASTQ.gz files used by alignment."
            files={readiness.canonicalFiles}
            emptyMessage={
              readiness.pendingFiles.length > 0
                ? "Normalization is still running for this batch."
                : "Canonical FASTQ has not been produced yet."
            }
          />
        </div>
      )}
    </div>
  );
}

function BatchFileGroup({
  title,
  description,
  files,
  emptyMessage,
}: {
  title: string;
  description: string;
  files: Workspace["files"];
  emptyMessage: string;
}) {
  return (
    <Card className="bg-white">
      <CardHeader>
        <CardTitle>{title}</CardTitle>
        <p className="text-sm text-muted-foreground">{description}</p>
      </CardHeader>
      <CardContent>
        {files.length === 0 ? (
          <div className="rounded-2xl border border-dashed px-4 py-6 text-sm text-muted-foreground">
            {emptyMessage}
          </div>
        ) : (
          <div className="space-y-2">
            {files.map((file) => (
              <div
                key={file.id}
                className="rounded-2xl border border-black/8 px-4 py-3"
              >
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div className="min-w-0">
                    <p className="truncate text-sm font-medium">
                      {file.filename}
                    </p>
                    <p className="text-xs text-muted-foreground">
                      {file.format.toUpperCase()} • uploaded{" "}
                      {formatDateTime(file.uploadedAt)}
                    </p>
                  </div>
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge variant="outline">{file.readPair}</Badge>
                    <Badge variant="secondary">{file.status}</Badge>
                    <span className="text-xs text-muted-foreground">
                      {formatBytes(file.sizeBytes)}
                    </span>
                  </div>
                </div>
                {file.error && (
                  <p className="mt-2 text-xs text-destructive">{file.error}</p>
                )}
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
