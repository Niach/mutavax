"""Stage 6 validation — DIAMOND self-identity recall + specificity.

The safety claim cancerstudio makes is: *if a candidate peptide is
identical (or near-identical) to a human self-protein, the stage-6
UI will flag it and block release*. This test validates the sensitive
end of that claim — peptides that ARE self-proteins must be flagged —
and, as a companion, the specific end: random 9-mers must mostly not be
flagged.

We would prefer to test against HLA Ligand Atlas (MS-validated
presented peptides from healthy tissue), but their data host is
unreachable from most environments. Sourcing peptides as 9-mer
windows from the same UniProt Swiss-Prot DB we BLAST against gives a
reproducible, offline-independent proxy: by construction, every
sampled peptide is an exact substring of a human reviewed protein, so
DIAMOND *must* find it. If this test fails, either DIAMOND is broken
or our wrapper is not invoking it correctly.

Network-dependent on first run (proteome bootstrap downloads ~11 MB
of Swiss-Prot from UniProt). Subsequent runs are offline — cached
under ``$CANCERSTUDIO_DATA_ROOT/references/proteome/human/``.

Skipped on the host (DIAMOND is container-only). Runs in-container
via `npm run test:validation` or `docker exec ... pytest`.
"""
from __future__ import annotations

import random
import shutil
from pathlib import Path

import pytest

from app.models.schemas import ReferencePreset
from app.services import self_identity


# Deterministic sample — any shuffle gives different peptides, so we
# fix the seed for reproducibility. Draws from different proteins to
# avoid testing "same protein 50 ways".
_SEED = 20260422
_SAMPLE_SIZE = 50
_PEPTIDE_LEN = 9


def _diamond_available() -> bool:
    return shutil.which("diamond") is not None


def _parse_fasta(path: Path) -> list[tuple[str, str]]:
    """Tiny FASTA reader — returns ``[(header, sequence), ...]`` with
    each sequence as one uppercase AA string."""
    entries: list[tuple[str, str]] = []
    header = ""
    seq_parts: list[str] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.rstrip("\n")
            if line.startswith(">"):
                if header:
                    entries.append((header, "".join(seq_parts).upper()))
                header = line[1:]
                seq_parts = []
            else:
                seq_parts.append(line)
    if header:
        entries.append((header, "".join(seq_parts).upper()))
    return entries


def _sample_self_peptides(
    fasta_path: Path, n: int, seed: int
) -> list[tuple[str, str]]:
    """Sample ``n`` distinct 9-mers from the FASTA, one per protein,
    avoiding sequences with non-standard AAs (U, B, Z, X, O)."""
    rng = random.Random(seed)
    entries = _parse_fasta(fasta_path)
    # Shuffle proteins so we don't always sample from the first N.
    rng.shuffle(entries)
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for header, seq in entries:
        if len(seq) < _PEPTIDE_LEN + 20:  # enough runway for sampling
            continue
        start = rng.randrange(10, len(seq) - _PEPTIDE_LEN - 10)
        peptide = seq[start : start + _PEPTIDE_LEN]
        if peptide in seen:
            continue
        if any(aa in "UBZXO*-" for aa in peptide):
            continue
        if not peptide.isalpha():
            continue
        seen.add(peptide)
        # Peptide ID encodes the source protein for diagnostic reports.
        accession = header.split("|")[1] if "|" in header else header[:16]
        out.append((f"self-{accession}-{start}", peptide))
        if len(out) >= n:
            break
    return out


def _random_nonself_peptides(
    n: int, seed: int
) -> list[tuple[str, str]]:
    """Generate ``n`` random 9-mers from a rough AA distribution.
    Frequencies are uniform over the 20 canonical AAs — good enough
    for specificity testing; a random 9-mer has ~(1/20)^9 ≈ 2 × 10⁻¹²
    chance of exactly matching *any* specific self-peptide, so
    genuine false positives should be extremely rare."""
    rng = random.Random(seed)
    aa = "ACDEFGHIKLMNPQRSTVWY"
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    while len(out) < n:
        peptide = "".join(rng.choice(aa) for _ in range(_PEPTIDE_LEN))
        if peptide in seen:
            continue
        seen.add(peptide)
        out.append((f"rand-{len(out):03d}", peptide))
    return out


# ---------------------------------------------------------------------------
# Pure unit tests (always run)
# ---------------------------------------------------------------------------


def test_sampler_draws_distinct_peptides_with_valid_aas(tmp_path: Path) -> None:
    """Sampler should produce distinct, in-alphabet 9-mers from a
    realistic FASTA — regression-guards the validation test's inputs."""
    # Distinct, non-repeating sequences so the sampler can't collide
    # on identical motifs from two different proteins.
    (tmp_path / "mini.fasta").write_text(
        ">sp|P00001|A HUMAN\n"
        + "MPFVKKALTACDEGHIKLNRSTWMPFVKKALTACDEGHIKLNRSTWMPFVKKALTACDEGHIKLNRSTW\n"
        + ">sp|P00002|B HUMAN\n"
        + "WQRSTNLKIHGECDATLKKVFPMWQRSTNLKIHGECDATLKKVFPMWQRSTNLKIHGECDATLKKVFPM\n"
    )
    peptides = _sample_self_peptides(tmp_path / "mini.fasta", n=2, seed=1)
    assert len(peptides) == 2
    sequences = [p[1] for p in peptides]
    assert len(set(sequences)) == 2
    for seq in sequences:
        assert len(seq) == _PEPTIDE_LEN
        assert seq.isalpha()
        assert all(aa in "ACDEFGHIKLMNPQRSTVWY" for aa in seq)


def test_sampler_skips_short_proteins(tmp_path: Path) -> None:
    (tmp_path / "mini.fasta").write_text(
        ">sp|P00001|SHORT HUMAN\nACDEFGHIK\n"
        ">sp|P00002|LONG HUMAN\n"
        + ("ACDEFGHIKL" * 10) + "\n"
    )
    peptides = _sample_self_peptides(tmp_path / "mini.fasta", n=5, seed=1)
    # Only the long one contributes; we get whatever windows fit.
    assert len(peptides) <= 5
    for pid, _ in peptides:
        assert "P00002" in pid


def test_random_nonself_generator_is_deterministic() -> None:
    a = _random_nonself_peptides(10, seed=42)
    b = _random_nonself_peptides(10, seed=42)
    assert a == b
    # Distinct peptides requested → all distinct.
    assert len({p[1] for p in a}) == len(a)


# ---------------------------------------------------------------------------
# End-to-end recall + specificity — requires DIAMOND + Swiss-Prot
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not _diamond_available(),
    reason="DIAMOND binary not on PATH (container-only)",
)
def test_self_peptide_recall_is_at_least_95pct() -> None:
    """Peptides sampled as 9-mer windows from UniProt Swiss-Prot must
    all be flagged by DIAMOND — they are literal substrings of human
    reviewed proteins and cannot honestly be called "safe". Allow 5%
    slack for edge cases (DIAMOND's seed+extend can miss ultra-short
    queries with low-complexity flanks)."""
    config = self_identity.ensure_proteome_ready(ReferencePreset.GRCH38)
    if config is None:
        pytest.skip("Proteome bootstrap failed (UniProt unreachable?)")

    peptides = _sample_self_peptides(
        config.fasta_path, n=_SAMPLE_SIZE, seed=_SEED
    )
    assert len(peptides) == _SAMPLE_SIZE, (
        f"Sampler only produced {len(peptides)} / {_SAMPLE_SIZE} peptides"
    )

    flags = self_identity.run_self_identity_check(peptides, ReferencePreset.GRCH38)
    flagged = [pid for pid in flags]
    recall = len(flagged) / _SAMPLE_SIZE

    missed = [p for pid, p in peptides if pid not in flags]
    assert recall >= 0.95, (
        f"Self-identity recall {recall:.2%} below 0.95 floor. "
        f"Missed {len(missed)} of {_SAMPLE_SIZE} known-self 9-mers — "
        f"DIAMOND is failing to match peptides that are exact substrings "
        f"of reviewed human proteins.\n  sample missed: {missed[:5]}"
    )


@pytest.mark.skipif(
    not _diamond_available(),
    reason="DIAMOND binary not on PATH (container-only)",
)
def test_random_peptide_false_positive_rate_below_30pct() -> None:
    """Specificity floor: random 9-mers should *mostly* not match the
    proteome. Some will — random sequences over 20-letter alphabets
    have a non-trivial chance of matching somewhere — but a >30% hit
    rate would mean our match threshold is too loose and every
    candidate peptide will trigger a flag regardless of biology."""
    peptides = _random_nonself_peptides(_SAMPLE_SIZE, seed=_SEED + 1)
    flags = self_identity.run_self_identity_check(peptides, ReferencePreset.GRCH38)
    fp_rate = len(flags) / _SAMPLE_SIZE
    assert fp_rate < 0.30, (
        f"False-positive rate {fp_rate:.2%} on random 9-mers is above "
        "0.30 — the self-identity check is too permissive; every "
        "candidate would be flagged and the check would become useless."
    )


@pytest.mark.skipif(
    not _diamond_available(),
    reason="DIAMOND binary not on PATH (container-only)",
)
def test_self_peptides_hit_critical_risk_tier() -> None:
    """Peptides that are exact substrings of Swiss-Prot should land
    in the 'critical' risk tier (100% identity), not 'elevated' or
    'mild'. A drift to the softer tiers would mean DIAMOND's %-identity
    calculation is off or our tier thresholds drifted."""
    config = self_identity.ensure_proteome_ready(ReferencePreset.GRCH38)
    if config is None:
        pytest.skip("Proteome bootstrap failed")
    peptides = _sample_self_peptides(config.fasta_path, n=20, seed=_SEED)
    flags = self_identity.run_self_identity_check(peptides, ReferencePreset.GRCH38)

    tier_counts: dict[str, int] = {"critical": 0, "elevated": 0, "mild": 0}
    for flag in flags.values():
        tier_counts[flag.risk] = tier_counts.get(flag.risk, 0) + 1

    # At least 80% should be critical — DIAMOND's seed+extend may
    # occasionally pick an alignment that misses a terminal residue
    # and drops one peptide to elevated, but that's the exception.
    critical_ratio = tier_counts.get("critical", 0) / max(len(flags), 1)
    assert critical_ratio >= 0.80, (
        f"Only {critical_ratio:.2%} of self-peptides landed in 'critical' "
        f"tier. Distribution: {tier_counts}. Expected ≥80% critical."
    )


# ---------------------------------------------------------------------------
# Class-II path — ≥14 aa peptides route through DIAMOND.
# ---------------------------------------------------------------------------


_CLASS_II_LENGTHS = (15, 18)


@pytest.mark.skipif(
    not _diamond_available(),
    reason="DIAMOND binary not on PATH (container-only)",
)
@pytest.mark.parametrize("peptide_len", _CLASS_II_LENGTHS)
def test_class_ii_self_peptide_recall(peptide_len: int) -> None:
    """Class-II peptides (≥14 aa) route through DIAMOND rather than
    the Python substring scan. Sampling 25 length-N windows from
    Swiss-Prot, DIAMOND must flag ≥95% as self-matches (they're
    exact substrings by construction). Regression-guards the
    dispatch + DIAMOND invocation for class-II length ranges."""
    config = self_identity.ensure_proteome_ready(ReferencePreset.GRCH38)
    if config is None:
        pytest.skip("Proteome bootstrap failed")
    if config.dmnd_path is None:
        pytest.skip("DIAMOND index absent; bootstrap probably failed to build it")

    rng = random.Random(_SEED + peptide_len)
    entries = _parse_fasta(config.fasta_path)
    rng.shuffle(entries)
    peptides: list[tuple[str, str]] = []
    seen: set[str] = set()
    for header, seq in entries:
        if len(seq) < peptide_len + 20:
            continue
        start = rng.randrange(10, len(seq) - peptide_len - 10)
        pep = seq[start : start + peptide_len]
        if pep in seen or not pep.isalpha() or any(aa in "UBZXO*-" for aa in pep):
            continue
        seen.add(pep)
        accession = header.split("|")[1] if "|" in header else header[:16]
        peptides.append((f"cii-{peptide_len}-{accession}-{start}", pep))
        if len(peptides) >= 25:
            break

    flags = self_identity.run_self_identity_check(peptides, ReferencePreset.GRCH38)
    recall = len(flags) / len(peptides)
    missed = [p for pid, p in peptides if pid not in flags]
    assert recall >= 0.95, (
        f"Class-II {peptide_len}-mer recall {recall:.2%} below 0.95 floor. "
        f"DIAMOND missed {len(missed)} of {len(peptides)} known-self peptides.\n"
        f"  sample missed: {missed[:3]}"
    )


def test_dispatch_routes_by_length(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Short peptides must go through the pure-Python path; long ones
    through DIAMOND. Stub both paths and verify the dispatch allocates
    each peptide to the right backend."""
    fasta = tmp_path / "mini.fasta"
    fasta.write_text(">sp|P0|A HUMAN\n" + "A" * 200 + "\n")
    dmnd = tmp_path / "mini.dmnd"
    dmnd.write_bytes(b"\x00")
    config = self_identity.ProteomeConfig(
        fasta_path=fasta, label="test", dmnd_path=dmnd
    )
    monkeypatch.setattr(self_identity, "ensure_proteome_ready", lambda p: config)

    short_calls: list[int] = []
    long_calls: list[int] = []

    def fake_short(seq: str, proteome):  # noqa: ANN001
        short_calls.append(len(seq))
        return None

    def fake_long(long_items, cfg):  # noqa: ANN001
        long_calls.extend(len(p[1]) for p in long_items)
        return {}

    monkeypatch.setattr(self_identity, "_best_hit_for_peptide", fake_short)
    monkeypatch.setattr(self_identity, "_check_long_via_diamond", fake_long)

    self_identity.run_self_identity_check(
        [
            ("a", "ACDEFGHIK"),           # 9-mer → short
            ("b", "ACDEFGHIKLMN"),        # 12-mer → short
            ("c", "ACDEFGHIKLMNP"),       # 13-mer → short (boundary)
            ("d", "ACDEFGHIKLMNPQ"),      # 14-mer → long (DIAMOND starts)
            ("e", "ACDEFGHIKLMNPQRSTV"),   # 18-mer → long
        ],
        ReferencePreset.GRCH38,
    )

    assert sorted(short_calls) == [9, 12, 13]
    assert sorted(long_calls) == [14, 18]
