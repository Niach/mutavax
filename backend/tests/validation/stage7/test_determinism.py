"""Stage 7 — pure-unit validations on the codon optimizer.

* Protein identity: ``translate(optimize(AA))`` must equal the input AA
  byte-for-byte. A silent synonymous-swap that changes the protein is
  the worst manufacturability failure mode — catastrophic and silent
  if not caught at the optimizer boundary.

* Deterministic: same input + same λ + same species → same bytes.
  The product's entire audit story assumes bit-identical re-runs; a
  non-deterministic optimizer would invalidate every stamped checksum.

* CAI floor: the human optimizer should emit codon-usage-adjusted DNA
  with CAI ≥ 0.80 on a generic test cassette.
"""
from __future__ import annotations

import pytest

from app.services import lineardesign

# Representative short cassette — signal peptide + AAY + two class-I
# epitopes + GPGPG + one class-II + MITD fragment. Chosen to include
# every codon-usage-interesting amino acid (W, C, R, K, etc.) without
# being so long that the test takes seconds.
_TEST_AA = "MFVFLVLLPLVSSAAYHFSQAIRRLGPGPGAKVLDERTLHCTAMIVMVTIMLCCMTS"


def _translate(dna: str) -> str:
    """Minimal standard-code translator — duplicates
    ``construct_checks._translate`` but kept here so the test is
    self-contained and independent of that module's evolution."""
    codon_table = {
        "TTT": "F", "TTC": "F", "TTA": "L", "TTG": "L",
        "CTT": "L", "CTC": "L", "CTA": "L", "CTG": "L",
        "ATT": "I", "ATC": "I", "ATA": "I", "ATG": "M",
        "GTT": "V", "GTC": "V", "GTA": "V", "GTG": "V",
        "TCT": "S", "TCC": "S", "TCA": "S", "TCG": "S",
        "CCT": "P", "CCC": "P", "CCA": "P", "CCG": "P",
        "ACT": "T", "ACC": "T", "ACA": "T", "ACG": "T",
        "GCT": "A", "GCC": "A", "GCA": "A", "GCG": "A",
        "TAT": "Y", "TAC": "Y", "TAA": "*", "TAG": "*",
        "CAT": "H", "CAC": "H", "CAA": "Q", "CAG": "Q",
        "AAT": "N", "AAC": "N", "AAA": "K", "AAG": "K",
        "GAT": "D", "GAC": "D", "GAA": "E", "GAG": "E",
        "TGT": "C", "TGC": "C", "TGA": "*", "TGG": "W",
        "CGT": "R", "CGC": "R", "CGA": "R", "CGG": "R",
        "AGT": "S", "AGC": "S", "AGA": "R", "AGG": "R",
        "GGT": "G", "GGC": "G", "GGA": "G", "GGG": "G",
    }
    return "".join(
        codon_table.get(dna[i : i + 3].upper(), "X")
        for i in range(0, len(dna) - 2, 3)
    )


_UNAVAILABLE = lineardesign.availability_reason()


@pytest.mark.skipif(_UNAVAILABLE is not None, reason=f"LinearDesign: {_UNAVAILABLE}")
def test_protein_identity_after_codon_optimization() -> None:
    """Codon optimization must be synonymous — byte-identical protein
    when the optimized DNA is translated back."""
    # Clear cache so we really hit LinearDesign, not a stale entry.
    lineardesign.optimize.cache_clear()
    result = lineardesign.optimize(_TEST_AA, lambda_value=0.65, species="human")
    # Trim the stop codon LinearDesign may or may not emit — we only
    # care about the coding region matching the input AA.
    protein = _translate(result.dna).rstrip("*")
    assert protein == _TEST_AA, (
        f"Codon optimization changed the protein!\n"
        f"  input  : {_TEST_AA}\n"
        f"  output : {protein}\n"
        f"  diff@{next((i for i in range(min(len(_TEST_AA), len(protein))) if _TEST_AA[i] != protein[i]), len(_TEST_AA))}"
    )


@pytest.mark.skipif(_UNAVAILABLE is not None, reason=f"LinearDesign: {_UNAVAILABLE}")
def test_lambda_slider_determinism() -> None:
    """Running LinearDesign twice on the same AA + λ + species must
    produce byte-identical DNA. ``lru_cache`` guarantees this within a
    process; we also clear the cache + re-run to assert the binary
    itself is deterministic."""
    lineardesign.optimize.cache_clear()
    a = lineardesign.optimize(_TEST_AA, lambda_value=0.65, species="human")
    lineardesign.optimize.cache_clear()
    b = lineardesign.optimize(_TEST_AA, lambda_value=0.65, species="human")
    assert a.dna == b.dna, (
        "LinearDesign returned different DNA on the same input; "
        "determinism is required for the checksum audit trail."
    )
    assert a.cai == pytest.approx(b.cai)
    assert a.mfe == pytest.approx(b.mfe)


@pytest.mark.skipif(_UNAVAILABLE is not None, reason=f"LinearDesign: {_UNAVAILABLE}")
def test_human_cai_above_clinical_floor() -> None:
    """Human workspaces should produce CAI ≥ 0.80 on a generic test
    cassette — the validation.md threshold. CAI measures alignment of
    the codon mix to the species' highly-expressed genes; BNT162b2
    and mRNA-1273 both sit around 0.9+."""
    lineardesign.optimize.cache_clear()
    result = lineardesign.optimize(_TEST_AA, lambda_value=0.65, species="human")
    assert result.cai >= 0.80, (
        f"Human CAI {result.cai:.3f} below the 0.80 floor — "
        "the optimizer's codon table may be misconfigured."
    )


def test_empty_input_is_safe() -> None:
    """Empty AA is a valid edge case (no cassette yet). Should not
    crash, should return all zeros."""
    result = lineardesign.optimize("", lambda_value=0.65, species="human")
    assert result.dna == ""
    assert result.rna == ""
    assert result.cai == 0.0
    assert result.mfe == 0.0
