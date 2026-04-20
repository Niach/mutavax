// FASTA block colors per run kind — same molecular-biology conventions
// as stage 7, rendered lighter for background highlight.

export interface RunPalette {
  bg: string;
  fg: string;
  label: string;
}

export const RUN_COLORS: Record<string, RunPalette> = {
  utr5: { bg: "#fef3c7", fg: "#78350f", label: "5′ UTR + Kozak" },
  signal: { bg: "#e2e8f0", fg: "#334155", label: "Signal peptide (tPA)" },
  linker: { bg: "#f1f5f9", fg: "#475569", label: "linker / hinge" },
  classI: { bg: "#ccfbf1", fg: "#0f766e", label: "class-I peptide" },
  classII: { bg: "#ede9fe", fg: "#6d28d9", label: "class-II peptide" },
  mitd: { bg: "#e0f2fe", fg: "#075985", label: "MITD" },
  utr3: { bg: "#fef3c7", fg: "#78350f", label: "3′ UTR" },
  polyA: { bg: "#cbd5e1", fg: "#1e293b", label: "poly(A) tail" },
  stop: { bg: "#fecaca", fg: "#991b1b", label: "stop" },
};
