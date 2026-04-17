#!/usr/bin/env node
// Captures the four README + GitHub Pages screenshots against a mock API so
// the completed alignment / variant-calling states render with realistic
// metrics. Start from repo root: `node scripts/capture-screenshots.mjs`.

import { spawn } from "node:child_process";
import http from "node:http";
import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { chromium } from "playwright";

const REPO_ROOT = path.resolve(new URL("..", import.meta.url).pathname);
const SCREENSHOT_DIR = path.join(REPO_ROOT, "docs", "screenshots");
const STUB_PORT = 7777;
const NEXT_PORT = 3001;
const STUB_URL = `http://127.0.0.1:${STUB_PORT}`;
const NEXT_URL = `http://127.0.0.1:${NEXT_PORT}`;

// ---------- fixtures ----------

const NOW = "2026-04-16T10:24:00Z";
const EARLIER = "2026-04-16T07:58:02Z";
const CREATED = "2026-04-12T09:14:00Z";

function laneSummary(sampleLane, status = "ready") {
  return {
    active_batch_id: `batch-${sampleLane}`,
    sample_lane: sampleLane,
    status,
    ready_for_alignment: status === "ready",
    source_file_count: status === "empty" ? 0 : 2,
    canonical_file_count: status === "ready" ? 2 : 0,
    missing_pairs: [],
    blocking_issues: [],
    read_layout: "paired",
    updated_at: NOW,
    progress: null,
  };
}

function readyIngestion() {
  return {
    status: "ready",
    ready_for_alignment: true,
    lanes: { tumor: laneSummary("tumor"), normal: laneSummary("normal") },
  };
}

function emptyIngestion() {
  return {
    status: "empty",
    ready_for_alignment: false,
    lanes: {
      tumor: laneSummary("tumor", "empty"),
      normal: laneSummary("normal", "empty"),
    },
  };
}

function sourceFile(sampleLane, pair, filename) {
  return {
    id: `${sampleLane}-${pair}`,
    batch_id: `batch-${sampleLane}`,
    source_file_id: null,
    sample_lane: sampleLane,
    filename,
    format: "fastq",
    file_role: "source",
    status: "ready",
    size_bytes: 5_832_191_004,
    uploaded_at: CREATED,
    read_pair: pair,
    source_path: `/Users/danny/sequencing/rosie/${filename}`,
    managed_path: null,
    error: null,
  };
}

const ROSIE = {
  id: "ws-rosie",
  display_name: "Rosie baseline",
  species: "dog",
  analysis_profile: {
    reference_preset: "canfam4",
    reference_override: null,
  },
  active_stage: "variant-calling",
  created_at: CREATED,
  updated_at: NOW,
  ingestion: readyIngestion(),
  files: [
    sourceFile("tumor", "R1", "rosie_tumor_R1.fastq.gz"),
    sourceFile("tumor", "R2", "rosie_tumor_R2.fastq.gz"),
    sourceFile("normal", "R1", "rosie_normal_R1.fastq.gz"),
    sourceFile("normal", "R2", "rosie_normal_R2.fastq.gz"),
  ],
};

const HCC = {
  id: "ws-hcc1395",
  display_name: "HCC1395 benchmark",
  species: "human",
  analysis_profile: {
    reference_preset: "grch38",
    reference_override: null,
  },
  active_stage: "ingestion",
  created_at: "2026-04-15T16:02:00Z",
  updated_at: "2026-04-15T16:45:22Z",
  ingestion: readyIngestion(),
  files: [
    sourceFile("tumor", "R1", "HCC1395_tumor_R1.fastq.gz"),
    sourceFile("tumor", "R2", "HCC1395_tumor_R2.fastq.gz"),
    sourceFile("normal", "R1", "HCC1395BL_normal_R1.fastq.gz"),
    sourceFile("normal", "R2", "HCC1395BL_normal_R2.fastq.gz"),
  ],
};

const FELIX = {
  id: "ws-felix",
  display_name: "Felix intake",
  species: "cat",
  analysis_profile: {
    reference_preset: "felcat9",
    reference_override: null,
  },
  active_stage: "ingestion",
  created_at: "2026-04-16T09:48:00Z",
  updated_at: "2026-04-16T09:48:00Z",
  ingestion: emptyIngestion(),
  files: [],
};

const WORKSPACES = [ROSIE, HCC, FELIX];

function workspaceFor(id) {
  return WORKSPACES.find((workspace) => workspace.id === id) ?? null;
}

function alignmentLaneMetrics(sampleLane, stats) {
  return {
    sample_lane: sampleLane,
    total_reads: stats.totalReads,
    mapped_reads: Math.round(stats.totalReads * (stats.mappedPercent / 100)),
    mapped_percent: stats.mappedPercent,
    properly_paired_percent: stats.properlyPairedPercent,
    duplicate_percent: stats.duplicatePercent,
    mean_insert_size: stats.meanInsertSize,
  };
}

function alignmentArtifact(id, kind, sampleLane, filename, sizeBytes) {
  return {
    id,
    artifact_kind: kind,
    sample_lane: sampleLane,
    filename,
    size_bytes: sizeBytes,
    download_path: `/api/workspaces/ws-rosie/alignment/artifacts/${id}/download`,
    local_path: `/Users/danny/cancerstudio/data/app-data/workspaces/ws-rosie/alignment/run-01/${filename}`,
  };
}

const ROSIE_ALIGNMENT_METRICS = {
  tumor: {
    totalReads: 1_984_723_110,
    mappedPercent: 98.91,
    properlyPairedPercent: 96.32,
    duplicatePercent: 19.4,
    meanInsertSize: 312,
  },
  normal: {
    totalReads: 754_103_228,
    mappedPercent: 98.86,
    properlyPairedPercent: 95.81,
    duplicatePercent: 17.8,
    meanInsertSize: 308,
  },
};

function alignmentSummaryCompleted(workspace) {
  const metrics = ROSIE_ALIGNMENT_METRICS;
  const artifacts = [
    alignmentArtifact("tumor-bam", "bam", "tumor", "rosie_tumor.aligned.bam", 48_200_000_000),
    alignmentArtifact("tumor-bai", "bai", "tumor", "rosie_tumor.aligned.bam.bai", 8_400_000),
    alignmentArtifact("tumor-flagstat", "flagstat", "tumor", "rosie_tumor.flagstat.txt", 520),
    alignmentArtifact("tumor-idxstats", "idxstats", "tumor", "rosie_tumor.idxstats.txt", 1_240),
    alignmentArtifact("tumor-stats", "stats", "tumor", "rosie_tumor.stats.txt", 64_000),
    alignmentArtifact("normal-bam", "bam", "normal", "rosie_normal.aligned.bam", 19_800_000_000),
    alignmentArtifact("normal-bai", "bai", "normal", "rosie_normal.aligned.bam.bai", 7_900_000),
    alignmentArtifact("normal-flagstat", "flagstat", "normal", "rosie_normal.flagstat.txt", 520),
    alignmentArtifact("normal-idxstats", "idxstats", "normal", "rosie_normal.idxstats.txt", 1_240),
    alignmentArtifact("normal-stats", "stats", "normal", "rosie_normal.stats.txt", 63_000),
  ];

  return {
    workspace_id: workspace.id,
    status: "completed",
    blocking_reason: null,
    analysis_profile: workspace.analysis_profile,
    qc_verdict: "pass",
    ready_for_variant_calling: true,
    latest_run: {
      id: "run-01",
      status: "completed",
      progress: 1,
      reference_preset: workspace.analysis_profile.reference_preset,
      reference_override: null,
      reference_label: "CanFam4 (UU_Cfam_GSD_1.0)",
      runtime_phase: "finalizing",
      qc_verdict: "pass",
      created_at: EARLIER,
      updated_at: NOW,
      started_at: EARLIER,
      completed_at: NOW,
      blocking_reason: null,
      error: null,
      command_log: [
        "samtools faidx CanFam4.fa",
        "strobealign --create-index -r 150 CanFam4.fa",
        "strobealign -t 24 -U CanFam4.fa rosie_tumor_R1.fastq.gz rosie_tumor_R2.fastq.gz | samtools sort -@ 8 -m 2G -o rosie_tumor.aligned.bam -",
        "samtools index rosie_tumor.aligned.bam",
        "samtools flagstat rosie_tumor.aligned.bam > rosie_tumor.flagstat.txt",
        "samtools idxstats rosie_tumor.aligned.bam > rosie_tumor.idxstats.txt",
        "samtools stats rosie_tumor.aligned.bam > rosie_tumor.stats.txt",
      ],
      recent_log_tail: null,
      last_activity_at: NOW,
      eta_seconds: null,
      progress_components: {
        reference_prep: 1,
        aligning: 1,
        finalizing: 1,
        stats: 1,
      },
      expected_total_per_lane: { tumor: 24, normal: 12 },
      lane_metrics: {
        tumor: alignmentLaneMetrics("tumor", metrics.tumor),
        normal: alignmentLaneMetrics("normal", metrics.normal),
      },
      chunk_progress: {
        tumor: { phase: "merging", total_chunks: 24, completed_chunks: 24, active_chunks: 0 },
        normal: { phase: "merging", total_chunks: 12, completed_chunks: 12, active_chunks: 0 },
      },
      artifacts,
    },
    lane_metrics: {
      tumor: alignmentLaneMetrics("tumor", metrics.tumor),
      normal: alignmentLaneMetrics("normal", metrics.normal),
    },
    artifacts,
  };
}

function alignmentSummaryReady(workspace) {
  return {
    workspace_id: workspace.id,
    status: "ready",
    blocking_reason: null,
    analysis_profile: workspace.analysis_profile,
    qc_verdict: null,
    ready_for_variant_calling: false,
    latest_run: null,
    lane_metrics: { tumor: null, normal: null },
    artifacts: [],
  };
}

function alignmentSummaryBlocked(workspace) {
  return {
    workspace_id: workspace.id,
    status: "blocked",
    blocking_reason:
      "Add both the tumor and healthy sample files before alignment can start.",
    analysis_profile: workspace.analysis_profile,
    qc_verdict: null,
    ready_for_variant_calling: false,
    latest_run: null,
    lane_metrics: { tumor: null, normal: null },
    artifacts: [],
  };
}

function alignmentSummaryFor(workspace) {
  if (workspace.id === ROSIE.id) return alignmentSummaryCompleted(workspace);
  if (workspace.id === HCC.id) return alignmentSummaryReady(workspace);
  return alignmentSummaryBlocked(workspace);
}

// ---- variant calling metrics for Rosie ----

const DOG_CHROMS = [
  ["chr1", 122_678_785],
  ["chr2", 85_426_708],
  ["chr3", 91_889_043],
  ["chr4", 88_276_631],
  ["chr5", 88_915_250],
  ["chr6", 77_573_801],
  ["chr7", 80_974_532],
  ["chr8", 74_330_416],
  ["chr9", 61_074_082],
  ["chr10", 69_331_447],
  ["chr11", 74_389_097],
  ["chr12", 72_498_081],
  ["chr13", 63_241_923],
  ["chr14", 60_966_679],
  ["chr15", 64_190_966],
  ["chr16", 59_632_846],
  ["chr17", 64_289_059],
  ["chr18", 55_844_845],
  ["chr19", 53_741_614],
  ["chr20", 58_134_056],
  ["chr21", 50_858_623],
  ["chr22", 61_439_934],
  ["chr23", 52_294_480],
  ["chr24", 47_698_779],
  ["chr25", 51_628_933],
  ["chr26", 38_964_690],
  ["chr27", 45_876_710],
  ["chr28", 41_182_112],
  ["chr29", 41_845_238],
  ["chr30", 40_214_260],
  ["chr31", 39_895_921],
  ["chr32", 38_810_281],
  ["chr33", 31_377_067],
  ["chr34", 42_125_770],
  ["chr35", 26_816_948],
  ["chr36", 30_888_429],
  ["chr37", 30_937_877],
  ["chr38", 23_753_152],
  ["chrX", 123_869_142],
];

// Deterministic, uneven mutation density per chromosome.
function chromosomeMetrics() {
  const weights = [
    8, 5, 6, 4, 5, 3, 4, 3, 2, 3, 3, 2, 3, 2, 4, 2, 3, 2, 2, 2, 2, 3, 2, 2, 1, 1,
    2, 1, 2, 1, 1, 1, 0, 1, 0, 1, 0, 0, 4,
  ];
  return DOG_CHROMS.map(([name, length], index) => {
    const total = weights[index] * 34 + (index % 5) * 3;
    const passCount = Math.round(total * 0.86);
    const snvCount = Math.round(total * 0.82);
    const indelCount = total - snvCount;
    return {
      chromosome: name,
      length,
      total,
      pass_count: passCount,
      snv_count: snvCount,
      indel_count: indelCount,
    };
  });
}

const CHROMS = chromosomeMetrics();
const TOTAL_VARIANTS = CHROMS.reduce((sum, entry) => sum + entry.total, 0);
const PASS_COUNT = CHROMS.reduce((sum, entry) => sum + entry.pass_count, 0);
const SNV_COUNT = CHROMS.reduce((sum, entry) => sum + entry.snv_count, 0);
const INDEL_COUNT = CHROMS.reduce((sum, entry) => sum + entry.indel_count, 0);

const VAF_HISTOGRAM = [
  0, 0, 42, 128, 287, 534, 812, 1043, 1284, 1421, 1360, 1208, 964, 708, 482,
  298, 186, 114, 68, 24,
].map((count, index) => ({
  bin_start: index * 0.05,
  bin_end: (index + 1) * 0.05,
  count,
}));

const FILTER_BREAKDOWN = [
  { name: "PASS", count: PASS_COUNT, is_pass: true },
  { name: "weak_evidence", count: 621, is_pass: false },
  { name: "germline", count: 543, is_pass: false },
  { name: "panel_of_normals", count: 264, is_pass: false },
  { name: "clustered_events", count: 218, is_pass: false },
  { name: "strand_bias", count: 172, is_pass: false },
  { name: "normal_artifact", count: 148, is_pass: false },
  { name: "base_qual", count: 132, is_pass: false },
  { name: "haplotype", count: 96, is_pass: false },
  { name: "map_qual", count: 88, is_pass: false },
  { name: "low_allele_frac", count: 74, is_pass: false },
  { name: "fragment", count: 52, is_pass: false },
  { name: "duplicate", count: 34, is_pass: false },
  { name: "strand_bias;weak_evidence", count: 48, is_pass: false },
];

const TOP_VARIANTS = [
  ["chr1", 58_214_991, "C", "T", "snv", "PASS", true, 0.487, 94, 86],
  ["chr2", 31_048_662, "G", "A", "snv", "PASS", true, 0.462, 88, 81],
  ["chr5", 72_930_418, "A", "G", "snv", "PASS", true, 0.441, 76, 72],
  ["chr1", 104_528_119, "T", "C", "snv", "PASS", true, 0.418, 102, 94],
  ["chr7", 18_332_401, "CAG", "C", "deletion", "PASS", true, 0.401, 71, 68],
  ["chr4", 60_914_733, "G", "T", "snv", "PASS", true, 0.389, 68, 64],
  ["chr3", 87_145_226, "A", "AG", "insertion", "PASS", true, 0.377, 64, 60],
  ["chr9", 44_982_103, "C", "T", "snv", "PASS", true, 0.362, 58, 54],
  ["chr12", 38_117_982, "G", "A", "snv", "PASS", true, 0.348, 54, 50],
  ["chr6", 27_448_019, "T", "G", "snv", "PASS", true, 0.332, 62, 58],
  ["chr11", 48_219_773, "C", "CGG", "insertion", "PASS", true, 0.318, 50, 48],
  ["chr8", 25_033_804, "G", "A", "snv", "PASS", true, 0.304, 48, 46],
  ["chr14", 9_988_241, "A", "G", "snv", "PASS", true, 0.289, 44, 42],
  ["chr16", 22_544_187, "T", "C", "snv", "PASS", true, 0.276, 52, 48],
  ["chr20", 12_881_442, "G", "T", "snv", "PASS", true, 0.261, 38, 36],
  ["chr5", 29_002_884, "AAT", "A", "deletion", "PASS", true, 0.248, 42, 40],
  ["chr22", 33_187_601, "C", "T", "snv", "PASS", true, 0.236, 40, 38],
  ["chr18", 15_884_502, "A", "G", "snv", "PASS", true, 0.224, 34, 32],
  ["chrX", 77_129_903, "G", "A", "snv", "PASS", true, 0.211, 48, 46],
].map(([chromosome, position, ref, alt, variantType, filter, isPass, vaf, tD, nD]) => ({
  chromosome,
  position,
  ref,
  alt,
  variant_type: variantType,
  filter,
  is_pass: isPass,
  tumor_vaf: vaf,
  tumor_depth: tD,
  normal_depth: nD,
}));

function variantCallingSummaryCompleted(workspace) {
  const artifacts = [
    {
      id: "vcf",
      artifact_kind: "vcf",
      filename: "rosie.mutect2.filtered.vcf.gz",
      size_bytes: 148_320_000,
      download_path: "/api/workspaces/ws-rosie/variant-calling/artifacts/vcf/download",
      local_path: "/Users/danny/cancerstudio/data/app-data/workspaces/ws-rosie/variant-calling/run-01/rosie.mutect2.filtered.vcf.gz",
    },
    {
      id: "tbi",
      artifact_kind: "tbi",
      filename: "rosie.mutect2.filtered.vcf.gz.tbi",
      size_bytes: 2_800_000,
      download_path: "/api/workspaces/ws-rosie/variant-calling/artifacts/tbi/download",
      local_path: "/Users/danny/cancerstudio/data/app-data/workspaces/ws-rosie/variant-calling/run-01/rosie.mutect2.filtered.vcf.gz.tbi",
    },
    {
      id: "stats",
      artifact_kind: "stats",
      filename: "rosie.mutect2.stats",
      size_bytes: 412_000,
      download_path: "/api/workspaces/ws-rosie/variant-calling/artifacts/stats/download",
      local_path: "/Users/danny/cancerstudio/data/app-data/workspaces/ws-rosie/variant-calling/run-01/rosie.mutect2.stats",
    },
  ];

  return {
    workspace_id: workspace.id,
    status: "completed",
    blocking_reason: null,
    ready_for_annotation: true,
    latest_run: {
      id: "vc-run-01",
      status: "completed",
      progress: 1,
      runtime_phase: "finalizing",
      created_at: NOW,
      updated_at: NOW,
      started_at: NOW,
      completed_at: NOW,
      blocking_reason: null,
      error: null,
      command_log: [
        "gatk Mutect2 -R CanFam4.fa -I rosie_tumor.aligned.bam -I rosie_normal.aligned.bam -normal rosie_normal -O rosie.mutect2.vcf.gz",
        "gatk FilterMutectCalls -V rosie.mutect2.vcf.gz -R CanFam4.fa -O rosie.mutect2.filtered.vcf.gz",
      ],
      metrics: {
        total_variants: TOTAL_VARIANTS,
        snv_count: SNV_COUNT,
        indel_count: INDEL_COUNT,
        insertion_count: Math.round(INDEL_COUNT * 0.44),
        deletion_count: Math.round(INDEL_COUNT * 0.48),
        mnv_count: Math.round(INDEL_COUNT * 0.08),
        pass_count: PASS_COUNT,
        pass_snv_count: Math.round(PASS_COUNT * 0.82),
        pass_indel_count: Math.round(PASS_COUNT * 0.18),
        ti_tv_ratio: 2.18,
        transitions: Math.round(SNV_COUNT * 0.69),
        transversions: Math.round(SNV_COUNT * 0.31),
        mean_vaf: 0.271,
        median_vaf: 0.248,
        tumor_mean_depth: 64.4,
        normal_mean_depth: 38.2,
        tumor_sample: "rosie_tumor",
        normal_sample: "rosie_normal",
        reference_label: "CanFam4 (UU_Cfam_GSD_1.0)",
        per_chromosome: CHROMS,
        filter_breakdown: FILTER_BREAKDOWN,
        vaf_histogram: VAF_HISTOGRAM,
        top_variants: TOP_VARIANTS,
      },
      artifacts,
    },
    artifacts,
  };
}

function variantCallingSummaryBlocked(workspace, reason) {
  return {
    workspace_id: workspace.id,
    status: "blocked",
    blocking_reason: reason,
    ready_for_annotation: false,
    latest_run: null,
    artifacts: [],
  };
}

function variantCallingSummaryFor(workspace) {
  if (workspace.id === ROSIE.id) return variantCallingSummaryCompleted(workspace);
  return variantCallingSummaryBlocked(
    workspace,
    "Finish alignment cleanly before calling variants."
  );
}

function ingestionLanePreview(workspace, sampleLane) {
  const sequence =
    "AGGCTGAGGCAGGAGGATCACCTGAGGCCAGGAGTTTGAGACCAGCCTGGCCAACATGGTG" +
    "AAACCCCATCTCTACCAAAATACAAAAATTAGCCAGGCGTGGTGGCGCATGCCTGTAATCC";
  const quality = "H".repeat(sequence.length);
  const reads = (pair, stem) =>
    Array.from({ length: 6 }).map((_, index) => ({
      header: `${stem}.${pair}.read${index + 1} length=${sequence.length}`,
      sequence,
      quality,
      length: sequence.length,
      gc_percent: 48.3 + index * 0.4,
      mean_quality: 36.8,
    }));
  return {
    workspace_id: workspace.id,
    sample_lane: sampleLane,
    batch_id: `batch-${sampleLane}`,
    source: "canonical-fastq",
    read_layout: "paired",
    reads: {
      R1: reads("R1", `${workspace.id}_${sampleLane}`),
      R2: reads("R2", `${workspace.id}_${sampleLane}`),
    },
    stats: {
      sampled_read_count: 6,
      average_read_length: sequence.length,
      sampled_gc_percent: 49.1,
    },
  };
}

// ---------- stub HTTP server ----------

function send(res, status, body) {
  res.writeHead(status, {
    "Content-Type": "application/json",
    "Cache-Control": "no-store",
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, POST, PATCH, DELETE, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
  });
  res.end(JSON.stringify(body));
}

function startStub() {
  const server = http.createServer((req, res) => {
    const url = new URL(req.url ?? "/", STUB_URL);
    const parts = url.pathname.replace(/\/+$/, "").split("/");

    if (req.method === "OPTIONS") {
      return send(res, 204, {});
    }
    if (req.method === "GET" && url.pathname === "/health") {
      return send(res, 200, { status: "ok" });
    }
    if (req.method === "GET" && url.pathname === "/api/workspaces") {
      return send(res, 200, WORKSPACES);
    }

    // /api/workspaces/{id}...
    if (parts[1] === "api" && parts[2] === "workspaces" && parts[3]) {
      const workspace = workspaceFor(parts[3]);
      if (!workspace) return send(res, 404, { detail: "Workspace not found" });

      if (req.method === "GET" && parts.length === 4) {
        return send(res, 200, workspace);
      }
      if (req.method === "GET" && parts[4] === "alignment" && parts.length === 5) {
        return send(res, 200, alignmentSummaryFor(workspace));
      }
      if (
        req.method === "GET" &&
        parts[4] === "variant-calling" &&
        parts.length === 5
      ) {
        return send(res, 200, variantCallingSummaryFor(workspace));
      }
      if (
        req.method === "GET" &&
        parts[4] === "ingestion" &&
        parts[5] === "preview" &&
        parts[6]
      ) {
        return send(res, 200, ingestionLanePreview(workspace, parts[6]));
      }
    }

    send(res, 404, { detail: `Unhandled ${req.method} ${url.pathname}` });
  });

  return new Promise((resolve) => server.listen(STUB_PORT, "127.0.0.1", () => resolve(server)));
}

// ---------- Next.js dev server ----------

function startNextDev() {
  const env = {
    ...process.env,
    PORT: String(NEXT_PORT),
    NEXT_PUBLIC_API_URL: STUB_URL,
    INTERNAL_API_URL: STUB_URL,
  };
  const proc = spawn("npx", ["next", "dev", "--port", String(NEXT_PORT)], {
    cwd: REPO_ROOT,
    env,
    stdio: ["ignore", "pipe", "pipe"],
    detached: true,
  });
  const prefix = "[next] ";
  proc.stdout.on("data", (chunk) => process.stdout.write(prefix + chunk.toString()));
  proc.stderr.on("data", (chunk) => process.stderr.write(prefix + chunk.toString()));
  return proc;
}

function killNext(proc) {
  if (!proc.pid) return;
  try {
    process.kill(-proc.pid, "SIGTERM");
  } catch {
    try {
      proc.kill("SIGTERM");
    } catch {}
  }
}

async function waitFor(url, timeoutMs = 240_000) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    try {
      const response = await fetch(url, { signal: AbortSignal.timeout(2000) });
      if (response.ok) return;
    } catch {}
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
  throw new Error(`Timeout waiting for ${url}`);
}

// ---------- screenshot plan ----------

const SHOTS = [
  {
    name: "landing",
    path: "/",
    height: 760,
    // Make sure we land before the network finishes so the loading state does
    // not flicker into the shot.
    wait: 600,
  },
  {
    name: "ingestion",
    path: `/workspaces/${HCC.id}/ingestion`,
    height: 860,
    wait: 900,
  },
  {
    name: "alignment",
    path: `/workspaces/${ROSIE.id}/alignment`,
    height: 1100,
    wait: 1200,
  },
  {
    name: "variant-calling",
    path: `/workspaces/${ROSIE.id}/variant-calling`,
    height: 2100,
    wait: 1500,
  },
];

async function capture() {
  await mkdir(SCREENSHOT_DIR, { recursive: true });
  const browser = await chromium.launch({ headless: true });
  try {
    for (const shot of SHOTS) {
      const context = await browser.newContext({
        viewport: { width: 1440, height: shot.height },
        deviceScaleFactor: 1,
        colorScheme: "light",
      });
      const page = await context.newPage();
      await page.goto(`${NEXT_URL}${shot.path}`, { waitUntil: "networkidle" });
      await page.waitForTimeout(shot.wait);
      const outPath = path.join(SCREENSHOT_DIR, `${shot.name}.png`);
      await page.screenshot({ path: outPath, fullPage: false });
      await context.close();
      console.log(`wrote ${path.relative(REPO_ROOT, outPath)}`);
    }
  } finally {
    await browser.close();
  }
}

// ---------- orchestration ----------

async function main() {
  const stub = await startStub();
  console.log(`stub API on ${STUB_URL}`);

  const next = startNextDev();
  console.log(`starting next dev on ${NEXT_URL}...`);

  try {
    await waitFor(`${NEXT_URL}/`);
    console.log("next dev ready");
    await waitFor(`${STUB_URL}/health`);
    await capture();
  } finally {
    killNext(next);
    stub.close();
    await new Promise((resolve) => setTimeout(resolve, 600));
  }
}

main().then(
  () => {
    console.log("done");
    process.exit(0);
  },
  (error) => {
    console.error(error);
    process.exit(1);
  }
);
