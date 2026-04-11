// TypeScript port of backend/app/services/workspace_store.py read-pair / sample-stem helpers.
// Keep the regexes in sync with READ_PAIR_PATTERN, UNDERSCORE_PAIR_SUFFIX_PATTERN,
// SEPARATOR_PATTERN, and LANE_SPLIT_TOKEN_PATTERN.

export type DetectedReadPair = "R1" | "R2" | "unknown";

export type StagedFileFormat = "fastq" | "bam" | "cram";

export type LaneStagingValidationState =
  | "empty"
  | "missing-r2"
  | "missing-r1"
  | "unclear"
  | "mixed-stems"
  | "mixed-marked-unmarked"
  | "mixed-formats"
  | "ready";

export interface LaneStagingValidation {
  state: LaneStagingValidationState;
  reason: string | null;
  sampleStem: string | null;
}

const READ_PAIR_PATTERN =
  /(?:^|[_\-.])(R[12])(?:[_\-.]|$)|(?<=[_\-.])([12])(?=\.(?:fastq|fq)(?:\.gz)?$)/i;

const READ_PAIR_TOKEN_PATTERN = /^(R[12]|[12])$/i;

const UNDERSCORE_PAIR_SUFFIX_PATTERN = /[_\-.][12]$/;

const SEPARATOR_PATTERN = /[_\-.]+/;

const LANE_SPLIT_TOKEN_PATTERN = /^(?:L\d{3}|\d{3})$/i;

const COMPRESSED_FASTQ_SUFFIXES = [".fastq.gz", ".fq.gz"] as const;
const FASTQ_SUFFIXES = [...COMPRESSED_FASTQ_SUFFIXES, ".fastq", ".fq"] as const;
const BAM_SUFFIXES = [".bam"] as const;
const CRAM_SUFFIXES = [".cram"] as const;

export function inferReadPair(filename: string): DetectedReadPair {
  const match = READ_PAIR_PATTERN.exec(filename);
  if (!match) {
    return "unknown";
  }
  const token = (match[1] ?? match[2] ?? "").toUpperCase();
  return token.endsWith("1") ? "R1" : "R2";
}

export function detectFormat(filename: string): StagedFileFormat | null {
  const lowered = filename.toLowerCase();
  if (FASTQ_SUFFIXES.some((suffix) => lowered.endsWith(suffix))) {
    return "fastq";
  }
  if (BAM_SUFFIXES.some((suffix) => lowered.endsWith(suffix))) {
    return "bam";
  }
  if (CRAM_SUFFIXES.some((suffix) => lowered.endsWith(suffix))) {
    return "cram";
  }
  return null;
}

function stripKnownSuffix(filename: string): string {
  const lowered = filename.toLowerCase();
  for (const suffix of [...FASTQ_SUFFIXES, ...BAM_SUFFIXES, ...CRAM_SUFFIXES]) {
    if (lowered.endsWith(suffix)) {
      return filename.slice(0, filename.length - suffix.length);
    }
  }
  return filename;
}

export function normalizeFastqSampleStem(filename: string): string {
  let stem = stripKnownSuffix(filename);
  stem = stem.replace(UNDERSCORE_PAIR_SUFFIX_PATTERN, "");
  const tokens = stem.split(SEPARATOR_PATTERN).filter(Boolean);
  const filtered = tokens.filter(
    (token) =>
      !READ_PAIR_TOKEN_PATTERN.test(token) && !LANE_SPLIT_TOKEN_PATTERN.test(token)
  );
  return filtered.join("_").toLowerCase();
}

export function fingerprintFile(file: File): string {
  return `${file.name}:${file.size}:${file.lastModified}`;
}

/**
 * Validates a set of staged File objects against the same rules used by
 * backend `validate_lane_files`. Returns a discriminated state plus an
 * editorial reason string and a detected sample stem.
 *
 * The intent is to keep the user from ever creating an upload session that
 * the backend will reject — paired-end is required, sample stems must match,
 * formats may not be mixed, and so on.
 */
export function validateStagedFiles(files: File[]): LaneStagingValidation {
  if (files.length === 0) {
    return { state: "empty", reason: null, sampleStem: null };
  }

  const formats = new Set<StagedFileFormat>();
  for (const file of files) {
    const format = detectFormat(file.name);
    if (format) {
      formats.add(format);
    }
  }

  if (formats.size === 0) {
    return {
      state: "mixed-formats",
      reason: "Unsupported file type. Use FASTQ, BAM, or CRAM.",
      sampleStem: null,
    };
  }
  if (formats.size > 1) {
    return {
      state: "mixed-formats",
      reason: "Mixed file types — use FASTQ only or a single BAM/CRAM.",
      sampleStem: null,
    };
  }

  const format = formats.values().next().value as StagedFileFormat;

  if (format === "bam" || format === "cram") {
    if (files.length !== 1) {
      return {
        state: "mixed-formats",
        reason: "Upload exactly one BAM or CRAM file for a lane.",
        sampleStem: null,
      };
    }
    return {
      state: "ready",
      reason: null,
      sampleStem: stripKnownSuffix(files[0].name).toLowerCase(),
    };
  }

  // FASTQ branch — paired-end required.
  const r1Files = files.filter((f) => inferReadPair(f.name) === "R1");
  const r2Files = files.filter((f) => inferReadPair(f.name) === "R2");
  const unknownFiles = files.filter((f) => inferReadPair(f.name) === "unknown");

  const stems = new Set(
    files.map((file) => normalizeFastqSampleStem(file.name)).filter(Boolean)
  );
  const sampleStem = stems.size === 1 ? [...stems][0] : null;

  const hasR1 = r1Files.length > 0;
  const hasR2 = r2Files.length > 0;
  const hasUnknown = unknownFiles.length > 0;

  if (hasUnknown && (hasR1 || hasR2)) {
    return {
      state: "mixed-marked-unmarked",
      reason:
        "Mixed naming — every file in this lane must use _R1_/_R2_ markers.",
      sampleStem,
    };
  }

  if (hasUnknown && !hasR1 && !hasR2) {
    return {
      state: "unclear",
      reason: "Read pair unclear — rename with _R1_/_R2_ markers.",
      sampleStem,
    };
  }

  if (hasR1 && !hasR2) {
    return {
      state: "missing-r2",
      reason: "Add the matching R2 file.",
      sampleStem,
    };
  }

  if (hasR2 && !hasR1) {
    return {
      state: "missing-r1",
      reason: "Add the matching R1 file.",
      sampleStem,
    };
  }

  if (stems.size > 1) {
    return {
      state: "mixed-stems",
      reason: "Files belong to different sample families.",
      sampleStem: null,
    };
  }

  return { state: "ready", reason: null, sampleStem };
}
