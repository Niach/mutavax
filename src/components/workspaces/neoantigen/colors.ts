import type { BindingTier, MhcClass } from "@/lib/types";

export const CLASS_I_ACCENT = "#0f766e";
export const CLASS_II_ACCENT = "#7c3aed";

export function classAccent(cls: MhcClass): string {
  return cls === "I" ? CLASS_I_ACCENT : CLASS_II_ACCENT;
}

export function ic50Color(ic50: number): {
  bg: string;
  fg: string;
  tier: BindingTier;
} {
  if (ic50 < 50) return { bg: "#0f766e", fg: "#fff", tier: "strong" };
  if (ic50 < 150) return { bg: "#14b8a6", fg: "#fff", tier: "strong" };
  if (ic50 < 500) return { bg: "#5eead4", fg: "#0f172a", tier: "moderate" };
  if (ic50 < 1500) return { bg: "#a5f3fc", fg: "#0f172a", tier: "moderate" };
  if (ic50 < 5000) return { bg: "#e0f2fe", fg: "#475569", tier: "weak" };
  return { bg: "var(--surface-sunk)", fg: "var(--muted-2)", tier: "none" };
}

export const BUCKET_COLOR: Record<BindingTier, { fill: string; label: string }> = {
  strong: { fill: "#0f766e", label: "Strong" },
  moderate: { fill: "#14b8a6", label: "Moderate" },
  weak: { fill: "#7dd3fc", label: "Weak" },
  none: { fill: "#a8a29e", label: "Non-binder" },
};

export function formatIc50(value: number): string {
  if (value < 10000) return value.toLocaleString(undefined, { maximumFractionDigits: 0 });
  return `${Math.round(value / 1000)}k`;
}
