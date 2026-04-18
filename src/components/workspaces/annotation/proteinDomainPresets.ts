import type { ProteinDomain } from "@/lib/types";

// Fallback only. The backend now fetches real protein-feature coordinates
// from Ensembl REST at annotation time and attaches them to
// `GeneFocus.domains`; this preset is consulted by GeneLollipop only when
// the backend's lookup returned nothing (offline / Ensembl 4xx / unknown
// ENSP). Kept small on purpose — do not grow it to every cancer gene.
//
// Curated protein-domain bands for common cancer genes. Coordinates are in
// amino-acid positions and follow canonical UniProt entries for the human
// isoforms (canine/feline orthologs overlap closely for the conserved
// domains shown here). `kind: "catalytic"` flags the business-end domain
// (the one variant hotspots tend to cluster in) so the chart can accent it.
//
// Adding a new gene: drop in UniProt "Domain" features and keep only the
// spans that help tell the cancer story. Narrow sub-repeats (Ig 1-5, EGF
// 1-36) collapse to a single band unless they matter.

export interface ProteinPreset {
  proteinLength: number;
  role?: string;
  domains: ProteinDomain[];
}

export const PROTEIN_DOMAIN_PRESETS: Record<string, ProteinPreset> = {
  KIT: {
    proteinLength: 976,
    role: "Oncogene · tyrosine kinase",
    domains: [
      { start: 27, end: 112, label: "Ig 1", kind: "neutral" },
      { start: 121, end: 205, label: "Ig 2", kind: "neutral" },
      { start: 212, end: 308, label: "Ig 3", kind: "neutral" },
      { start: 317, end: 410, label: "Ig 4", kind: "neutral" },
      { start: 413, end: 507, label: "Ig 5", kind: "neutral" },
      { start: 589, end: 694, label: "Kinase N", kind: "catalytic" },
      { start: 762, end: 935, label: "Kinase C", kind: "catalytic" },
    ],
  },
  TP53: {
    proteinLength: 393,
    role: "Tumor suppressor · DNA damage",
    domains: [
      { start: 6, end: 29, label: "TAD", kind: "neutral" },
      { start: 94, end: 292, label: "DNA-binding", kind: "catalytic" },
      { start: 323, end: 356, label: "Tetramer.", kind: "neutral" },
    ],
  },
  BRAF: {
    proteinLength: 766,
    role: "Oncogene · serine/threonine kinase",
    domains: [
      { start: 155, end: 227, label: "RBD", kind: "neutral" },
      { start: 234, end: 280, label: "C1", kind: "neutral" },
      { start: 457, end: 717, label: "Kinase", kind: "catalytic" },
    ],
  },
  EGFR: {
    proteinLength: 1210,
    role: "Oncogene · receptor tyrosine kinase",
    domains: [
      { start: 57, end: 165, label: "L1", kind: "neutral" },
      { start: 173, end: 338, label: "CR1/S1", kind: "neutral" },
      { start: 362, end: 480, label: "L2", kind: "neutral" },
      { start: 712, end: 979, label: "Kinase", kind: "catalytic" },
    ],
  },
  PIK3CA: {
    proteinLength: 1068,
    role: "Oncogene · PI3K catalytic subunit",
    domains: [
      { start: 16, end: 105, label: "ABD", kind: "neutral" },
      { start: 187, end: 289, label: "RBD", kind: "neutral" },
      { start: 330, end: 487, label: "C2", kind: "neutral" },
      { start: 524, end: 696, label: "Helical", kind: "neutral" },
      { start: 797, end: 1068, label: "Kinase", kind: "catalytic" },
    ],
  },
  NOTCH1: {
    proteinLength: 2555,
    role: "Oncogene · transmembrane receptor",
    domains: [
      { start: 20, end: 1426, label: "EGF repeats", kind: "neutral" },
      { start: 1449, end: 1731, label: "LNR", kind: "neutral" },
      { start: 1861, end: 2089, label: "ANK", kind: "catalytic" },
      { start: 2180, end: 2420, label: "TAD", kind: "neutral" },
      { start: 2460, end: 2555, label: "PEST", kind: "neutral" },
    ],
  },
  ATM: {
    proteinLength: 3056,
    role: "Tumor suppressor · DNA damage kinase",
    domains: [
      { start: 1960, end: 2566, label: "FAT", kind: "neutral" },
      { start: 2712, end: 2962, label: "Kinase", kind: "catalytic" },
      { start: 3024, end: 3056, label: "FATC", kind: "neutral" },
    ],
  },
  BRCA1: {
    proteinLength: 1863,
    role: "Tumor suppressor · DNA repair",
    domains: [
      { start: 1, end: 100, label: "RING", kind: "neutral" },
      { start: 1391, end: 1424, label: "CC", kind: "neutral" },
      { start: 1646, end: 1863, label: "BRCT", kind: "catalytic" },
    ],
  },
  BRCA2: {
    proteinLength: 3418,
    role: "Tumor suppressor · DNA repair",
    domains: [
      { start: 1009, end: 2083, label: "BRC repeats", kind: "catalytic" },
      { start: 2481, end: 3186, label: "DBD", kind: "neutral" },
    ],
  },
  SETD2: {
    proteinLength: 2564,
    role: "Tumor suppressor · histone methyltransferase",
    domains: [
      { start: 1511, end: 1549, label: "AWS", kind: "neutral" },
      { start: 1550, end: 1667, label: "SET", kind: "catalytic" },
      { start: 2392, end: 2421, label: "WW", kind: "neutral" },
    ],
  },
  FBXW7: {
    proteinLength: 707,
    role: "Tumor suppressor · ubiquitin ligase substrate receptor",
    domains: [
      { start: 280, end: 326, label: "F-box", kind: "neutral" },
      { start: 364, end: 707, label: "WD40", kind: "catalytic" },
    ],
  },
  SF3B1: {
    proteinLength: 1304,
    role: "Oncogene · splicing factor",
    domains: [{ start: 452, end: 1304, label: "HEAT repeats", kind: "catalytic" }],
  },
};

export function getProteinDomainPreset(symbol: string): ProteinPreset | null {
  return PROTEIN_DOMAIN_PRESETS[symbol.toUpperCase()] ?? null;
}
