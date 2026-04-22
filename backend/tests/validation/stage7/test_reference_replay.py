"""Stage-7 validation — replay our manufacturability checks against two
clinical-grade reference mRNAs (Pfizer-BioNTech BNT162b2, Moderna mRNA-1273).

The question this test answers: *would our stage-7 rules have rejected a
real approved mRNA vaccine?* The per-rule baselines below record what we
observed on real deposits. Any drift is either a regression (bug) or a
conscious rule recalibration (update the baseline + document why).

Observed on 2026-04-22 against current rules:

* **BNT162b2 passes 7/7** — including `furin`. Our regex uses the *canonical*
  R-X-[RK]-R furin consensus; the Spike's native RRAR is a non-canonical,
  weak furin substrate (A at position 3) and is correctly *not* flagged.
  Our rule is biologically right; Pfizer's design is clean on every other
  axis too.
* **mRNA-1273 passes 5/7** — fails `bsai` (a GGTCTC subsequence is present
  in the real clinical mRNA) and `gc` (a 50-nt window with GC outside the
  30–70% band). This divergence means either (a) our rules are stricter
  than Moderna's actual design, or (b) Moderna tolerates features our
  rules forbid. We record the gap here rather than silently loosening —
  see `validation.md` → Stage 7 → findings.

Source records are checked into `./fixtures/`; see `./fixtures/PROVENANCE.md`
for provenance and biology context.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from Bio import SeqIO

from app.services.construct_checks import run_manufacturing_checks

FIXTURES = Path(__file__).parent / "fixtures"

# IUPAC ambiguity codes occasionally appear in vial-sequenced deposits
# (e.g., 5 positions in PP544446 from Illumina assembly noise). Collapse
# them to any concrete base before feeding to DNAchisel, which rejects
# non-ACGT. A handful of positions cannot create or destroy the patterns
# these rules check for.
_IUPAC_TO_CANONICAL = str.maketrans(
    {
        "R": "A", "Y": "C", "S": "G", "W": "A", "K": "G", "M": "A",
        "B": "G", "D": "G", "H": "A", "V": "G", "N": "A", "X": "A",
    }
)


def _sanitize(seq: str) -> str:
    return seq.upper().replace("U", "T").translate(_IUPAC_TO_CANONICAL)


def _extract_bnt162b2_cassette() -> tuple[str, str]:
    """Return (mRNA_nt, cds_nt) for BNT162b2.

    PP544446 is a 7692 bp linearised plasmid. The mRNA cassette is
    bounded by the T7 promoter (..3526) and the end of the BNT162b2 CDS
    (7399). We treat `T7_end+1 .. CDS_end` as the mRNA for scanning
    purposes — the plasmid lacks an explicit poly-A annotation, so
    poly_a_len=0."""
    record = SeqIO.read(FIXTURES / "bnt162b2_PP544446.gb", "genbank")

    cds_feat = next(
        f for f in record.features
        if f.type == "CDS" and f.qualifiers.get("gene") == ["BNT162b2"]
    )
    t7_feat = next(
        f for f in record.features
        if f.type == "regulatory"
        and f.qualifiers.get("regulatory_class") == ["promoter"]
        and int(f.location.start) >= 3400  # the BNT162b2 T7, not the kanR one
    )

    mrna_start = int(t7_feat.location.end)
    mrna_end = int(cds_feat.location.end)
    cds_start = int(cds_feat.location.start)

    full_seq = _sanitize(str(record.seq))
    mrna_nt = full_seq[mrna_start:mrna_end]
    cds_nt = full_seq[cds_start:mrna_end]
    return mrna_nt, cds_nt


def _extract_mrna1273_cassette() -> tuple[str, str]:
    """Return (mRNA_nt, cds_nt) for mRNA-1273.

    OK120841 is the 3828 bp RNA recovered from a vaccine vial, deposited
    as RNA (U instead of T) with no CDS annotation. Locate the ORF by
    scanning for the first in-frame ATG→stop that yields a protein
    starting with M-F-V-F (the spike signal peptide)."""
    record = SeqIO.read(FIXTURES / "mrna1273_OK120841.gb", "genbank")
    full_seq = _sanitize(str(record.seq))

    cds_start = -1
    for i in range(len(full_seq) - 3):
        if full_seq[i : i + 12] == "ATGTTCGTGTTC":  # Met-Phe-Val-Phe
            cds_start = i
            break
    assert cds_start >= 0, "could not locate Spike signal peptide in OK120841"

    cds_end = cds_start
    for j in range(cds_start, len(full_seq) - 2, 3):
        codon = full_seq[j : j + 3]
        if codon in ("TAA", "TAG", "TGA"):
            cds_end = j + 3
            break
    assert cds_end > cds_start, "could not locate stop codon in OK120841"

    mrna_nt = full_seq
    cds_nt = full_seq[cds_start:cds_end]
    return mrna_nt, cds_nt


def _estimate_poly_a_len(full_nt: str) -> int:
    """Count the trailing run of A's (intentional poly-A tail) so scanners
    can exclude it from homopolymer and GC-window rules."""
    n = 0
    for base in reversed(full_nt):
        if base == "A":
            n += 1
        else:
            break
    return n


# ---------------------------------------------------------------------------
# The replay tests
# ---------------------------------------------------------------------------

# Observed per-check status from the 2026-04-22 discovery run. Locked in
# as the regression baseline — any drift means rules changed or upstream
# sequence data changed, and a human should look at why.
BNT162B2_EXPECTED = {
    "bsai":   "pass",
    "bsmbi":  "pass",
    "homop":  "pass",
    "gc":     "pass",
    "hairp":  "pass",
    "repeat": "pass",
    "furin":  "pass",  # RRAR is non-canonical (A at pos 3 ≠ [RK]) — correct
}

MRNA1273_EXPECTED = {
    "bsai":   "fail",  # GGTCTC present in the real clinical mRNA
    "bsmbi":  "pass",
    "homop":  "pass",
    "gc":     "fail",  # 50-nt window outside 30-70% band somewhere
    "hairp":  "pass",
    "repeat": "pass",
    "furin":  "pass",  # same canonical-motif reasoning as BNT162b2
}


def _run_and_summarise(
    mrna_nt: str, cds_nt: str, poly_a_len: int
) -> dict[str, str]:
    checks = run_manufacturing_checks(mrna_nt, cds_nt, poly_a_len=poly_a_len)
    return {c.id: c.status for c in checks}


def test_bnt162b2_matches_expected_check_profile() -> None:
    mrna_nt, cds_nt = _extract_bnt162b2_cassette()
    poly_a_len = _estimate_poly_a_len(mrna_nt)
    got = _run_and_summarise(mrna_nt, cds_nt, poly_a_len)
    assert got == BNT162B2_EXPECTED, (
        f"BNT162b2 check profile drifted from baseline:\n"
        f"  got      : {json.dumps(got, indent=2, sort_keys=True)}\n"
        f"  expected : {json.dumps(BNT162B2_EXPECTED, indent=2, sort_keys=True)}"
    )


def test_mrna1273_matches_expected_check_profile() -> None:
    mrna_nt, cds_nt = _extract_mrna1273_cassette()
    poly_a_len = _estimate_poly_a_len(mrna_nt)
    got = _run_and_summarise(mrna_nt, cds_nt, poly_a_len)
    assert got == MRNA1273_EXPECTED, (
        f"mRNA-1273 check profile drifted from baseline:\n"
        f"  got      : {json.dumps(got, indent=2, sort_keys=True)}\n"
        f"  expected : {json.dumps(MRNA1273_EXPECTED, indent=2, sort_keys=True)}"
    )


def test_bnt162b2_passes_all_seven_checks() -> None:
    """BNT162b2 should clear every stage-7 rule. A regression here means
    either our rules became too strict or the fixture was corrupted."""
    mrna_nt, cds_nt = _extract_bnt162b2_cassette()
    got = _run_and_summarise(mrna_nt, cds_nt, _estimate_poly_a_len(mrna_nt))
    fails = [cid for cid, status in got.items() if status == "fail"]
    assert fails == [], (
        f"BNT162b2 unexpectedly failing rules: {fails}. Expected 7/7 pass."
    )


def test_mrna1273_known_divergences_are_stable() -> None:
    """mRNA-1273 fails `bsai` and `gc` against our current rules — a known,
    documented divergence. This test keeps the *exact* failure set stable
    so a rule tightening (adding a third failure) or relaxation (dropping
    one of the two) surfaces as a test change, not a silent drift."""
    mrna_nt, cds_nt = _extract_mrna1273_cassette()
    got = _run_and_summarise(mrna_nt, cds_nt, _estimate_poly_a_len(mrna_nt))
    fails = sorted(cid for cid, status in got.items() if status == "fail")
    assert fails == ["bsai", "gc"], (
        f"mRNA-1273 failure set drifted from the 2026-04-22 baseline.\n"
        f"  got      : {fails}\n"
        f"  expected : ['bsai', 'gc']\n"
        "If a rule changed intentionally, update the baseline + note it in "
        "validation.md Stage 7 findings."
    )


if __name__ == "__main__":
    # Manual smoke run: print a full per-rule profile so a developer can
    # eyeball what BNT162b2 / mRNA-1273 look like through our rules.
    for name, extractor in (
        ("BNT162b2", _extract_bnt162b2_cassette),
        ("mRNA-1273", _extract_mrna1273_cassette),
    ):
        mrna_nt, cds_nt = extractor()
        poly_a = _estimate_poly_a_len(mrna_nt)
        print(f"\n=== {name} ===")
        print(f"  mRNA length : {len(mrna_nt)} nt")
        print(f"  CDS length  : {len(cds_nt)} nt ({len(cds_nt) // 3} codons)")
        print(f"  poly-A tail : {poly_a} nt")
        for k, v in _run_and_summarise(mrna_nt, cds_nt, poly_a).items():
            print(f"  {k:8s}: {v}")
