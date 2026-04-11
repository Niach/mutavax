import type { FastqReadPreview } from "@/lib/types";

// ─────────────────────────────────────────────────────────────────────────────
// Formatting helpers
// ─────────────────────────────────────────────────────────────────────────────

export function formatPreviewMetric(value: number, digits = 1) {
  return Number.isInteger(value) ? value.toString() : value.toFixed(digits);
}

export function formatPreviewPercent(value: number) {
  return `${formatPreviewMetric(value)}%`;
}

// ─────────────────────────────────────────────────────────────────────────────
// Visual tokens — reused everywhere the instrument trace lives
// ─────────────────────────────────────────────────────────────────────────────

/** Nucleotide color — tied to identity, never to quality or lane. */
export function baseTone(base: string) {
  switch (base.toUpperCase()) {
    case "A":
      return "text-emerald-600";
    case "C":
      return "text-sky-600";
    case "G":
      return "text-amber-600";
    case "T":
      return "text-rose-600";
    default:
      return "text-slate-400";
  }
}

/** Phred score → text color. Thresholds match the Q30 convention in genomics. */
export function phredTone(score: number) {
  if (score >= 30) return "text-emerald-500";
  if (score >= 20) return "text-amber-500";
  return "text-rose-500";
}

/** Phred score → background color for the continuous quality ribbon. */
function phredFill(score: number) {
  if (score >= 30) return "bg-emerald-500/85";
  if (score >= 20) return "bg-amber-500/85";
  return "bg-rose-500/85";
}

const QUALITY_GLYPHS = ["▁", "▂", "▃", "▄", "▅", "▆", "▇", "█"] as const;

/** Bucket a value into a block-character glyph of the right height. */
export function bucketToGlyph(value: number, min: number, max: number): string {
  if (max <= min) return "▄";
  const clamped = Math.min(max, Math.max(min, value));
  const ratio = (clamped - min) / (max - min);
  const index = Math.min(
    QUALITY_GLYPHS.length - 1,
    Math.max(0, Math.round(ratio * (QUALITY_GLYPHS.length - 1)))
  );
  return QUALITY_GLYPHS[index];
}

// ─────────────────────────────────────────────────────────────────────────────
// Derived metrics — computed from FastqReadPreview[] at render time. Pure.
// ─────────────────────────────────────────────────────────────────────────────

export interface DerivedLaneInsight {
  lengths: number[];
  gcPercents: number[];
  meanQualities: number[];
  q30Share: number; // 0..1
  nContent: number; // 0..1
}

export function deriveLaneInsight(
  reads: FastqReadPreview[]
): DerivedLaneInsight {
  if (reads.length === 0) {
    return {
      lengths: [],
      gcPercents: [],
      meanQualities: [],
      q30Share: 0,
      nContent: 0,
    };
  }

  let q30Bases = 0;
  let totalBases = 0;
  let nBases = 0;

  for (const read of reads) {
    for (let i = 0; i < read.quality.length; i += 1) {
      const score = read.quality.charCodeAt(i) - 33;
      if (score >= 30) q30Bases += 1;
      totalBases += 1;
    }
    for (let i = 0; i < read.sequence.length; i += 1) {
      const base = read.sequence.charCodeAt(i);
      // 'N' = 78, 'n' = 110
      if (base === 78 || base === 110) nBases += 1;
    }
  }

  return {
    lengths: reads.map((r) => r.length),
    gcPercents: reads.map((r) => r.gcPercent),
    meanQualities: reads.map((r) => r.meanQuality),
    q30Share: totalBases === 0 ? 0 : q30Bases / totalBases,
    nContent: totalBases === 0 ? 0 : nBases / totalBases,
  };
}

// ─────────────────────────────────────────────────────────────────────────────
// Sampled readout strip — three inline micro-widgets + Q30 / N-content summary
// ─────────────────────────────────────────────────────────────────────────────

interface SampledReadoutStripProps {
  sampledReadCount: number;
  averageReadLength: number;
  sampledGcPercent: number;
  insight: DerivedLaneInsight;
}

export function SampledReadoutStrip({
  sampledReadCount,
  averageReadLength,
  sampledGcPercent,
  insight,
}: SampledReadoutStripProps) {
  const { lengths, gcPercents, meanQualities, q30Share, nContent } = insight;

  const lengthMin = lengths.length ? Math.min(...lengths) : 0;
  const lengthMax = lengths.length ? Math.max(...lengths) : 0;
  const gcMin = 0;
  const gcMax = 100;
  const qMin = 0;
  const qMax = 42;

  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
      <Widget
        label="Length"
        headline={`${formatPreviewMetric(averageReadLength)} nt`}
        sub={
          lengths.length > 1
            ? `${lengthMin}–${lengthMax} nt range`
            : `${sampledReadCount.toLocaleString()} reads sampled`
        }
      >
        <GlyphBar
          values={lengths}
          min={lengthMin === lengthMax ? 0 : lengthMin}
          max={lengthMax}
          tone="slate"
        />
      </Widget>

      <Widget
        label="GC%"
        headline={formatPreviewPercent(sampledGcPercent)}
        sub="50% reference"
      >
        <GlyphBar values={gcPercents} min={gcMin} max={gcMax} tone="slate" reference={50} />
      </Widget>

      <Widget
        label="Q-mean"
        headline={`Q${formatPreviewMetric(
          meanQualities.length
            ? meanQualities.reduce((a, b) => a + b, 0) / meanQualities.length
            : 0
        )}`}
        sub={
          <>
            <span className="text-emerald-700">
              Q30 {formatPreviewPercent(q30Share * 100)}
            </span>
            <span className="text-slate-300"> · </span>
            <span>N {formatPreviewPercent(nContent * 100)}</span>
          </>
        }
      >
        <GlyphBar values={meanQualities} min={qMin} max={qMax} tone="phred" />
      </Widget>
    </div>
  );
}

function Widget({
  label,
  headline,
  sub,
  children,
}: {
  label: string;
  headline: string;
  sub: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <div className="font-mono text-[10px] tracking-[0.22em] text-slate-400 uppercase">
        {label}
      </div>
      <div className="font-mono text-base tabular-nums text-slate-900">
        {headline}
      </div>
      <div className="h-4 leading-none">{children}</div>
      <div className="font-mono text-[10px] tabular-nums text-slate-500">
        {sub}
      </div>
    </div>
  );
}

/**
 * 8-cell block-glyph sparkline rendered in SF Mono. Same vocabulary as the
 * quality strip — zero SVG, native to the typographic system.
 */
function GlyphBar({
  values,
  min,
  max,
  tone,
  reference,
}: {
  values: number[];
  min: number;
  max: number;
  tone: "slate" | "phred";
  reference?: number;
}) {
  if (values.length === 0) {
    return (
      <span className="font-mono text-[13px] leading-none text-slate-200">
        ▁▁▁▁▁▁▁▁
      </span>
    );
  }

  return (
    <span className="relative inline-flex font-mono text-[13px] leading-none">
      {values.map((value, index) => {
        const glyph = bucketToGlyph(value, min, max);
        const cls =
          tone === "phred" ? phredTone(value) : "text-slate-500";
        return (
          <span key={index} className={cls}>
            {glyph}
          </span>
        );
      })}
      {typeof reference === "number" && max > min ? (
        <span
          aria-hidden
          className="absolute inset-y-0 border-r border-dashed border-slate-300"
          style={{ left: `${((reference - min) / (max - min)) * 100}%` }}
        />
      ) : null}
    </span>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Preview legend — shown once per lane, documents the color / glyph system
// ─────────────────────────────────────────────────────────────────────────────

export function PreviewLegend() {
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1 font-mono text-[10px] tracking-[0.08em] text-slate-400">
      <span className="flex items-center gap-1">
        <span className="text-emerald-600">A</span>
        <span className="text-sky-600">C</span>
        <span className="text-amber-600">G</span>
        <span className="text-rose-600">T</span>
        <span className="text-slate-400">N</span>
      </span>
      <span className="text-slate-300">·</span>
      <span className="flex items-center gap-1.5">
        <span className="inline-block h-2 w-3 rounded-sm bg-emerald-500/85" />
        Q30+
      </span>
      <span className="flex items-center gap-1.5">
        <span className="inline-block h-2 w-3 rounded-sm bg-amber-500/85" />
        Q20+
      </span>
      <span className="flex items-center gap-1.5">
        <span className="inline-block h-2 w-3 rounded-sm bg-rose-500/85" />
        Q&lt;20
      </span>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Instrument trace — chunked bases + continuous quality ribbon + position ruler
// ─────────────────────────────────────────────────────────────────────────────

const CHUNK_SIZE = 10;

interface InstrumentTraceRowProps {
  read: FastqReadPreview;
  mate?: FastqReadPreview;
  index: number;
}

export function InstrumentTraceRow({
  read,
  mate,
  index,
}: InstrumentTraceRowProps) {
  // Strip paired-end suffix like "1/1" or "1/2" so the template id reads cleaner.
  const templateId = read.header.replace(/\s+[12]\/[12]\s*$/, "");

  return (
    <div
      className="animate-in fade-in slide-in-from-bottom-1 fill-mode-both"
      style={{ animationDelay: `${index * 40}ms`, animationDuration: "420ms" }}
    >
      <div className="flex items-baseline justify-between gap-4">
        <p className="min-w-0 truncate font-mono text-[11px] text-slate-600">
          {templateId}
        </p>
        <span className="shrink-0 font-mono text-[10px] tabular-nums text-slate-400">
          {read.length} nt
          <span className="text-slate-300"> · </span>
          Q{formatPreviewMetric(read.meanQuality)}
          {mate ? (
            <>
              <span className="text-slate-300"> · </span>
              mate Q{formatPreviewMetric(mate.meanQuality)}
            </>
          ) : null}
        </span>
      </div>

      <div className="trace-scroll trace-fade-right mt-2 overflow-x-auto">
        <div className="inline-block min-w-full">
          <ChunkedSequence sequence={read.sequence} />
          <QualityRibbon quality={read.quality} />
          <PositionRuler length={read.length} />
        </div>
      </div>

      {/* aria-hidden sr fallback so assistive tech and test snapshots that parse
          text still see per-base glyphs, even though the visual ribbon is a div. */}
      <p aria-hidden="true" className="sr-only">
        <QualityGlyphFallback quality={read.quality} />
      </p>
    </div>
  );
}

/** Chunked fixed-width bases, 10 per group, groups separated by a thin gap. */
function ChunkedSequence({ sequence }: { sequence: string }) {
  const groups: string[] = [];
  for (let i = 0; i < sequence.length; i += CHUNK_SIZE) {
    groups.push(sequence.slice(i, i + CHUNK_SIZE));
  }

  return (
    <p className="font-mono text-[12.5px] leading-5 tracking-[0.02em] whitespace-nowrap">
      {groups.map((group, groupIndex) => (
        <span key={groupIndex}>
          {Array.from(group).map((base, baseIndex) => (
            <span key={baseIndex} className={baseTone(base)}>
              {base}
            </span>
          ))}
          {groupIndex < groups.length - 1 ? (
            <span aria-hidden className="text-transparent select-none">
              {"\u00A0"}
            </span>
          ) : null}
        </span>
      ))}
    </p>
  );
}

/**
 * Continuous 2px tall ribbon, one segment per base, colored by Phred tone.
 * Lives in a flex row so it aligns exactly with the sequence above (same
 * `ch` width) because each segment takes one `1ch` slot + gap.
 */
function QualityRibbon({ quality }: { quality: string }) {
  const scores = Array.from(quality).map((ch) => ch.charCodeAt(0) - 33);

  return (
    <div
      aria-hidden
      className="mt-1 flex h-[2px] leading-none whitespace-nowrap"
      style={{ fontSize: "12.5px" }}
    >
      {scores.map((score, index) => {
        // Use the chunk-group gap so the ribbon breathes in the same rhythm as the sequence.
        const isGroupEnd =
          (index + 1) % CHUNK_SIZE === 0 && index !== scores.length - 1;
        return (
          <span key={index} className="flex items-stretch">
            <span
              className={`${phredFill(score)} inline-block h-[2px]`}
              style={{ width: "1ch" }}
            />
            {isGroupEnd ? (
              <span className="inline-block h-[2px]" style={{ width: "1ch" }} />
            ) : null}
          </span>
        );
      })}
    </div>
  );
}

/** Slate ruler in the exact same monospace rhythm as the chunked sequence. */
function PositionRuler({ length }: { length: number }) {
  // Build ticks at 1, 11, 21 … with exact CHUNK_SIZE+1 character spacing
  // (10 bases in a chunk + 1 inter-chunk spacer).
  const ticks: string[] = [];
  let cursor = 1;
  while (cursor <= length) {
    const label = cursor.toString();
    // Each position-span is CHUNK_SIZE bases + 1 spacer = 11 characters wide.
    // Pad the label to 11 chars so subsequent ticks land on the next chunk boundary.
    ticks.push(label.padEnd(CHUNK_SIZE + 1, " "));
    cursor += CHUNK_SIZE;
  }
  return (
    <p className="mt-1 font-mono text-[10px] leading-none tracking-[0.02em] whitespace-pre text-slate-300">
      {ticks.join("")}
    </p>
  );
}

/** Screen-reader fallback that keeps the old block-glyph vocabulary alive. */
function QualityGlyphFallback({ quality }: { quality: string }) {
  return (
    <>
      {Array.from(quality).map((ch, index) => {
        const score = ch.charCodeAt(0) - 33;
        const glyph = score >= 30 ? "▇" : score >= 20 ? "▅" : "▃";
        return <span key={index}>{glyph}</span>;
      })}
    </>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Backwards-compatible export. Still used nowhere critical but kept so
// accidental imports don't break the build while the refactor settles.
// ─────────────────────────────────────────────────────────────────────────────

export function ReadPreviewList({ reads }: { reads: FastqReadPreview[] }) {
  if (reads.length === 0) {
    return (
      <p className="text-sm text-slate-400">
        No sampled reads were available in this canonical file.
      </p>
    );
  }
  return (
    <ul className="mt-2 space-y-4">
      {reads.map((read, index) => (
        <li key={`${read.header}-${index}`}>
          <InstrumentTraceRow read={read} index={index} />
        </li>
      ))}
    </ul>
  );
}
