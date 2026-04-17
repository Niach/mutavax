import type {
  AlignmentStageSummary,
  ReadPair,
  ReadLayout,
  ReferencePreset,
  SampleLane,
  Workspace,
  WorkspaceSpecies,
} from "@/lib/types";

export function getCompactIssueLabel(issue?: string | null) {
  if (!issue) {
    return null;
  }

  const normalized = issue.trim();
  const lower = normalized.toLowerCase();

  if (lower.includes("matching r1")) {
    return "Missing R1";
  }
  if (lower.includes("matching r2")) {
    return "Missing R2";
  }
  if (lower.includes("at least one r1 and one r2")) {
    return "Missing R1 + R2";
  }
  if (lower.includes("paired-end required") && lower.includes("r2 file")) {
    return "Add R2 file";
  }
  if (lower.includes("paired-end required") && lower.includes("don't encode")) {
    return "Rename with _R1_/_R2_";
  }
  if (lower.includes("paired-end required")) {
    return "Paired-end required";
  }
  if (lower.includes("one format family only")) {
    return "Mixed file types";
  }
  if (lower.includes("exactly one bam or cram")) {
    return "One BAM/CRAM only";
  }
  if (lower.includes("cannot mix")) {
    return "Mixed read naming";
  }
  if (lower.includes("sample family")) {
    return "Mixed samples";
  }
  if (lower.includes("paired or single-end")) {
    return "Read layout unclear";
  }
  if (lower.includes("upload at least one sequencing file")) {
    return "Awaiting files";
  }
  if (lower.includes("malformed sequence preview")) {
    return "Preview malformed";
  }
  if (lower.includes("unable to read sequence preview")) {
    return "Preview unavailable";
  }
  if (lower.includes("unable to decode sequence preview")) {
    return "Preview unavailable";
  }

  return normalized.length <= 28 ? normalized : null;
}

export function getLaneIssueLabel(summary: Workspace["ingestion"]["lanes"]["tumor"]) {
  const missingPairs = summary.missingPairs.filter(
    (pair): pair is Extract<ReadPair, "R1" | "R2"> =>
      pair === "R1" || pair === "R2"
  );

  if (missingPairs.length > 0) {
    return `Need ${missingPairs.join(" + ")}`;
  }

  return getCompactIssueLabel(summary.blockingIssues[0]) ?? "Intake failed";
}

export function getLaneStatusLabel(summary: Workspace["ingestion"]["lanes"]["tumor"]) {
  if (summary.status === "ready") {
    return "2/2 ready";
  }
  if (summary.status === "normalizing") {
    return "Preparing";
  }
  if (summary.status === "uploading" || summary.status === "uploaded") {
    return "Queued";
  }
  if (summary.status === "failed") {
    return getLaneIssueLabel(summary);
  }
  return "Awaiting files";
}

export function formatReadLayoutLabel(readLayout?: ReadLayout | null) {
  if (readLayout === "paired") {
    return "paired";
  }
  if (readLayout === "single") {
    return "single-end";
  }
  return "—";
}

export function formatBytes(bytes: number) {
  if (bytes <= 0) {
    return "0 B";
  }

  const units = ["B", "KB", "MB", "GB", "TB"];
  const exponent = Math.min(
    Math.floor(Math.log(bytes) / Math.log(1024)),
    units.length - 1
  );
  const value = bytes / 1024 ** exponent;

  return `${value.toFixed(value >= 10 || exponent === 0 ? 0 : 1)} ${units[exponent]}`;
}

export function formatDateTime(value: string) {
  return new Intl.DateTimeFormat("en", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

export function formatSpeciesLabel(species: WorkspaceSpecies) {
  if (species === "dog") {
    return "Dog";
  }
  if (species === "human") {
    return "Human";
  }
  return "Cat";
}

export function formatLaneLabel(sampleLane: SampleLane) {
  return sampleLane === "tumor" ? "Tumor" : "Normal";
}

export function formatReferencePreset(referencePreset?: ReferencePreset | null) {
  if (referencePreset === "canfam4") {
    return "Dog reference";
  }
  if (referencePreset === "felcat9") {
    return "Cat reference";
  }
  if (referencePreset === "grch38") {
    return "Human reference";
  }
  return "Custom reference";
}

export function formatReferencePresetCodename(
  referencePreset?: ReferencePreset | null
) {
  if (referencePreset === "canfam4") {
    return "CanFam4";
  }
  if (referencePreset === "felcat9") {
    return "felCat9";
  }
  if (referencePreset === "grch38") {
    return "GRCh38";
  }
  return "Custom";
}

export function getQcVerdictLabel(
  qcVerdict?: AlignmentStageSummary["qcVerdict"] | null
) {
  if (qcVerdict === "pass") {
    return "Pass";
  }
  if (qcVerdict === "warn") {
    return "Warn";
  }
  if (qcVerdict === "fail") {
    return "Fail";
  }
  return "Pending";
}

export function getAlignmentStatusCopy(
  summary?: AlignmentStageSummary | null
) {
  if (!summary) {
    return { label: "Waiting", tone: "warning" as const };
  }

  if (summary.status === "blocked") {
    return { label: "Blocked", tone: "warning" as const };
  }
  if (summary.status === "ready") {
    return { label: "Ready", tone: "success" as const };
  }
  if (summary.status === "running") {
    return { label: "Running", tone: "info" as const };
  }
  if (summary.status === "failed") {
    return { label: "Failed", tone: "warning" as const };
  }
  return {
    label: summary.qcVerdict === "warn" ? "Complete (warn)" : "Complete",
    tone:
      summary.qcVerdict === "warn"
        ? ("warning" as const)
        : ("success" as const),
  };
}
