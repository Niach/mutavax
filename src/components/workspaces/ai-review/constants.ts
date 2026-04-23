import type {
  AiReviewCategoryId,
  AiReviewGrade,
  AiReviewSeverity,
  AiReviewVerdict,
} from "@/lib/types";

export interface ReviewContextSource {
  step: number;
  stage: string;
  label: string;
  detail: string;
}

export const REVIEW_CONTEXT_SOURCES: ReviewContextSource[] = [
  { step: 1, stage: "01", label: "Ingestion", detail: "Tumor + normal samples" },
  { step: 2, stage: "02", label: "Alignment", detail: "QC + depth" },
  { step: 3, stage: "03", label: "Variant calling", detail: "PASS variants · VAF" },
  { step: 4, stage: "04", label: "Annotation", detail: "Cancer-gene hits" },
  { step: 5, stage: "05", label: "Neoantigen prediction", detail: "MHC binders" },
  { step: 6, stage: "06", label: "Epitope shortlist", detail: "Driver-diverse picks" },
  { step: 7, stage: "07", label: "mRNA cassette", detail: "CAI · GC · checks" },
  { step: 8, stage: "08", label: "Construct release", detail: "sha256 locked" },
];

export const REVIEW_CATEGORIES: Record<
  AiReviewCategoryId,
  { label: string; blurb: string }
> = {
  validity: {
    label: "Scientific validity",
    blurb: "Drivers vs passengers · hotspot plausibility",
  },
  safety: {
    label: "Safety",
    blurb: "Self-similarity · autoimmune · cross-reactivity",
  },
  coverage: {
    label: "MHC coverage & peptide diversity",
    blurb: "Allele breadth · class I/II balance · gene diversity",
  },
  manufact: {
    label: "Codon opt. & manufacturability",
    blurb: "CAI · GC · cut sites · homopolymers",
  },
};

export const REVIEW_SEVERITY: Record<
  AiReviewSeverity,
  { fg: string; bg: string; label: string }
> = {
  info: {
    fg: "var(--accent-ink)",
    bg: "color-mix(in oklch, var(--accent) 10%, transparent)",
    label: "Info",
  },
  note: {
    fg: "var(--cool)",
    bg: "color-mix(in oklch, var(--cool) 12%, transparent)",
    label: "Note",
  },
  watch: {
    fg: "var(--warm)",
    bg: "color-mix(in oklch, var(--warm) 12%, transparent)",
    label: "Watch",
  },
  concern: {
    fg: "var(--danger)",
    bg: "color-mix(in oklch, var(--danger) 10%, transparent)",
    label: "Concern",
  },
};

export const REVIEW_VERDICTS: Record<
  AiReviewVerdict,
  { label: string; color: string; bg: string }
> = {
  approve: {
    label: "Approve for release",
    color: "var(--accent-ink)",
    bg: "color-mix(in oklch, var(--accent) 14%, transparent)",
  },
  approve_with_notes: {
    label: "Approve with notes",
    color: "var(--accent-ink)",
    bg: "color-mix(in oklch, var(--accent) 10%, transparent)",
  },
  hold: {
    label: "Hold — needs review",
    color: "var(--warm)",
    bg: "color-mix(in oklch, var(--warm) 12%, transparent)",
  },
  block: {
    label: "Block — do not release",
    color: "var(--danger)",
    bg: "color-mix(in oklch, var(--danger) 10%, transparent)",
  },
};

export const REVIEW_GRADES: Record<
  AiReviewGrade,
  { color: string; bg: string }
> = {
  A: {
    color: "var(--accent-ink)",
    bg: "color-mix(in oklch, var(--accent) 16%, transparent)",
  },
  B: {
    color: "var(--cool)",
    bg: "color-mix(in oklch, var(--cool) 14%, transparent)",
  },
  C: {
    color: "var(--warm)",
    bg: "color-mix(in oklch, var(--warm) 14%, transparent)",
  },
  D: {
    color: "var(--danger)",
    bg: "color-mix(in oklch, var(--danger) 12%, transparent)",
  },
};

export const REVIEW_HUE = 165;
