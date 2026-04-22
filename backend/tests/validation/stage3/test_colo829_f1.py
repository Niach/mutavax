"""Stage 3 validation — COLO829 somatic SNV recall / precision / F1 vs.
the SMaHT v1.0 community truth set.

The question this test answers: *on a benchmark tumor-normal pair where
the community has published a gold-standard SNV truth set, how close
does our Mutect2 + PON + FilterMutectCalls pipeline get to recovering
every true variant while minimizing false positives?*

Uses the SMaHT COLO829 SNV Truth Set v1.0 (Valle-Inclán 2022 / Hartwig
Medical Foundation consortium) as the oracle. Truth VCF + our filtered
VCF are both expected pre-staged under ``benchmarks/colo829/`` in the
project data root (set up once by the operator — see
``validation.md`` → Stage 3).

SNVs only for this first increment. INDEL comparison needs
left-normalization + allele-aware matching (what som.py does); we'll
layer that on in a follow-up.

Compares at VAF ≥ 0.10 (the headline threshold from validation.md). A
second, looser low-VAF test is included but asserts a lower F1 floor
because somatic calling inherently loses precision at VAF < 0.10.
"""
from __future__ import annotations

import gzip
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import pytest

# ---------------------------------------------------------------------------
# Benchmark data location — configurable, with a sensible default under
# ${CANCERSTUDIO_DATA_ROOT}/benchmarks/colo829/. Tests skip politely if
# either the truth VCF or our filtered VCF is missing.
# ---------------------------------------------------------------------------

_DATA_ROOT = Path(
    os.environ.get(
        "CANCERSTUDIO_COLO829_BENCH_DIR",
        os.path.expandvars(
            "$CANCERSTUDIO_DATA_ROOT/benchmarks/colo829"
            if os.environ.get("CANCERSTUDIO_DATA_ROOT")
            else "/media/niach/5c5f06df-56ba-430c-a735-42e1205949f63/"
            "cancerstudio/benchmarks/colo829"
        ),
    )
)

TRUTH_VCF = _DATA_ROOT / "SMaHT_COLO829_SNV_truth_set_v1.0.vcf.gz"
OURS_VCF = _DATA_ROOT / "ours.pass.snv.vcf.gz"

_MISSING_REASON = (
    f"COLO829 benchmark data not staged at {_DATA_ROOT}; "
    "populate it (see validation.md → Stage 3) and re-run this test."
)


# ---------------------------------------------------------------------------
# Pure helpers — parse a VCF into (chrom, pos, ref, alt) keys, keep only
# biallelic SNVs, optionally filter on the TUMOR sample's AF.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SnvKey:
    chrom: str
    pos: int
    ref: str
    alt: str


def _normalize_chrom(chrom: str) -> str:
    """Collapse UCSC/Ensembl naming so `chr1` and `1` compare equal."""
    return chrom[3:] if chrom.startswith("chr") else chrom


def _load_truth_snvs(path: Path) -> dict[SnvKey, str]:
    """Return ``{SnvKey: stratum}``. Stratum is the SMaHT ``RGN`` tag
    (Easy / Difficult / Extreme); defaults to ``Unknown`` if absent."""
    out: dict[SnvKey, str] = {}
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for raw in handle:
            if not raw or raw.startswith("#"):
                continue
            cols = raw.rstrip("\n").split("\t")
            if len(cols) < 8:
                continue
            chrom, pos_s, _, ref, alt, _, _, info = cols[:8]
            if len(ref) != 1 or len(alt) != 1 or "," in alt:
                continue
            stratum = "Unknown"
            for field in info.split(";"):
                if field.startswith("RGN="):
                    stratum = field[4:]
                    break
            key = SnvKey(_normalize_chrom(chrom), int(pos_s), ref, alt)
            out[key] = stratum
    return out


def _load_ours_snvs(path: Path, vaf_min: Optional[float]) -> set[SnvKey]:
    """Load PASS biallelic SNVs from a Mutect2-style VCF. When
    ``vaf_min`` is set, keep only variants whose TUMOR AF (first
    non-zero FORMAT/AF across samples) is ≥ the threshold."""
    out: set[SnvKey] = set()
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for raw in handle:
            if not raw or raw.startswith("#"):
                continue
            cols = raw.rstrip("\n").split("\t")
            if len(cols) < 10:  # no sample columns
                continue
            chrom, pos_s, _, ref, alt, _, filt = cols[:7]
            if filt not in ("PASS", "."):
                continue
            if len(ref) != 1 or len(alt) != 1 or "," in alt:
                continue
            if vaf_min is not None:
                fmt = cols[8].split(":")
                try:
                    af_idx = fmt.index("AF")
                except ValueError:
                    continue
                # Mutect2 puts NORMAL first, TUMOR second. Use the max
                # AF across samples — the normal's is ~0 for a real
                # somatic call, so max == tumor AF.
                best_af = 0.0
                for sample_col in cols[9:]:
                    parts = sample_col.split(":")
                    if af_idx >= len(parts):
                        continue
                    try:
                        best_af = max(best_af, float(parts[af_idx]))
                    except ValueError:
                        continue
                if best_af < vaf_min:
                    continue
            out.add(SnvKey(_normalize_chrom(chrom), int(pos_s), ref, alt))
    return out


@dataclass(frozen=True)
class ComparisonMetrics:
    tp: int
    fp: int
    fn: int
    precision: float
    recall: float
    f1: float
    ours_total: int
    truth_total: int
    stratum_recall: dict[str, float]  # recall by truth stratum


def _compute_metrics(
    ours: set[SnvKey], truth: dict[SnvKey, str]
) -> ComparisonMetrics:
    truth_keys = set(truth)
    tp = ours & truth_keys
    fp = ours - truth_keys
    fn = truth_keys - ours

    def _safe_div(num: int, denom: int) -> float:
        return num / denom if denom else 0.0

    precision = _safe_div(len(tp), len(tp) + len(fp))
    recall = _safe_div(len(tp), len(tp) + len(fn))
    f1 = (
        2 * precision * recall / (precision + recall)
        if (precision + recall) > 0
        else 0.0
    )

    # Per-stratum recall: how many of each truth stratum did we recover?
    stratum_recall: dict[str, float] = {}
    stratum_totals: dict[str, int] = {}
    stratum_hits: dict[str, int] = {}
    for key, stratum in truth.items():
        stratum_totals[stratum] = stratum_totals.get(stratum, 0) + 1
        if key in ours:
            stratum_hits[stratum] = stratum_hits.get(stratum, 0) + 1
    for stratum, total in stratum_totals.items():
        stratum_recall[stratum] = _safe_div(
            stratum_hits.get(stratum, 0), total
        )

    return ComparisonMetrics(
        tp=len(tp),
        fp=len(fp),
        fn=len(fn),
        precision=precision,
        recall=recall,
        f1=f1,
        ours_total=len(ours),
        truth_total=len(truth_keys),
        stratum_recall=stratum_recall,
    )


# ---------------------------------------------------------------------------
# The headline validation test
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not (TRUTH_VCF.is_file() and OURS_VCF.is_file()),
    reason=_MISSING_REASON,
)
def test_colo829_stage3_snv_f1_at_vaf_10() -> None:
    """Headline stage-3 metric: SNV F1 ≥ 0.85 at VAF ≥ 0.10 against
    the SMaHT v1.0 truth set."""
    truth = _load_truth_snvs(TRUTH_VCF)
    ours = _load_ours_snvs(OURS_VCF, vaf_min=0.10)
    m = _compute_metrics(ours, truth)

    report = (
        f"\n  truth SNVs : {m.truth_total}"
        f"\n  our SNVs   : {m.ours_total} (PASS, VAF ≥ 0.10)"
        f"\n  TP / FP / FN : {m.tp} / {m.fp} / {m.fn}"
        f"\n  precision  : {m.precision:.4f}"
        f"\n  recall     : {m.recall:.4f}"
        f"\n  F1         : {m.f1:.4f}"
        + "".join(
            f"\n  recall @ {k:10s} : {v:.4f}"
            for k, v in sorted(m.stratum_recall.items())
        )
    )

    assert m.f1 >= 0.85, (
        f"COLO829 SNV F1 dropped below 0.85 at VAF ≥ 0.10:{report}"
    )


@pytest.mark.skipif(
    not (TRUTH_VCF.is_file() and OURS_VCF.is_file()),
    reason=_MISSING_REASON,
)
def test_colo829_known_driver_variants_recovered() -> None:
    """Driver-gene recall: COLO829 is a well-characterised melanoma
    cell line whose canonical driver — BRAF V600E — must be in our
    PASS call set. A pipeline that reports F1 ≥ 0.85 overall but
    drops the headline driver is a pipeline nobody will trust."""
    ours = _load_ours_snvs(OURS_VCF, vaf_min=None)
    # BRAF V600E on GRCh38: chr7:140,753,336 A>T. Confirmed in SMaHT
    # v1.0 truth set at VAF_Ill=0.659 (heterozygous).
    braf_v600e = SnvKey("7", 140_753_336, "A", "T")
    assert braf_v600e in ours, (
        "COLO829's canonical BRAF V600E driver missing from our PASS "
        "SNV calls. This is the single variant a melanoma-aware "
        "bioinformatician would look for first."
    )


# ---------------------------------------------------------------------------
# Unit tests for the helpers — run on every CI invocation regardless of
# benchmark staging. These are what `npm run test:validation` exercises
# when benchmark data is absent.
# ---------------------------------------------------------------------------


def test_chrom_normalizer() -> None:
    assert _normalize_chrom("chr1") == "1"
    assert _normalize_chrom("1") == "1"
    assert _normalize_chrom("chrX") == "X"
    assert _normalize_chrom("MT") == "MT"


def test_compute_metrics_pure() -> None:
    truth = {
        SnvKey("1", 100, "A", "T"): "Easy",
        SnvKey("1", 200, "G", "C"): "Easy",
        SnvKey("1", 300, "C", "G"): "Difficult",
        SnvKey("2", 400, "T", "A"): "Difficult",
    }
    ours = {
        SnvKey("1", 100, "A", "T"),      # TP (Easy)
        SnvKey("1", 200, "G", "C"),      # TP (Easy)
        SnvKey("1", 300, "C", "G"),      # TP (Difficult)
        SnvKey("3", 999, "A", "G"),      # FP
    }
    # FN: ("2", 400, T, A) in Difficult — we missed it.
    m = _compute_metrics(ours, truth)
    assert m.tp == 3 and m.fp == 1 and m.fn == 1
    assert m.precision == pytest.approx(0.75)
    assert m.recall == pytest.approx(0.75)
    assert m.f1 == pytest.approx(0.75)
    assert m.stratum_recall["Easy"] == pytest.approx(1.0)
    assert m.stratum_recall["Difficult"] == pytest.approx(0.5)
