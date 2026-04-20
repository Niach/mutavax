// Molecular-biology color conventions for the mRNA cassette viz.
// Not theme tokens — segments are recognisable by hue across all themes.

export const CONSTRUCT_COLORS = {
  cap: "#fbbf24",
  utr5: "#e0c18f",
  kozak: "#d9a15e",
  signal: "#64748b",
  hinge: "#cbd5e1",
  linker: "#cbd5e1",
  classI: "#0f766e",
  classII: "#7c3aed",
  mitd: "#0ea5e9",
  utr3: "#e0c18f",
  polyA: "#1e293b",
} as const;

export function segmentColor(kind: string, cls?: string | null): string {
  if (kind === "peptide") return cls === "II" ? CONSTRUCT_COLORS.classII : CONSTRUCT_COLORS.classI;
  if (kind === "signal") return CONSTRUCT_COLORS.signal;
  if (kind === "mitd") return CONSTRUCT_COLORS.mitd;
  return CONSTRUCT_COLORS.linker;
}
