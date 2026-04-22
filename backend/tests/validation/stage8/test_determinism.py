"""Stage 8 — determinism + audit-trail integrity validations.

GenBank round-trip + CDS / UTR / polyA feature coverage is already
tested in ``backend/tests/test_construct_genbank.py``. This file adds
the *validation-flavoured* checks: the checksum stamped on every
released construct must be deterministic (same input → same hash) and
sensitive (any single-base change in the mRNA flips it).
"""
from __future__ import annotations

import io

import pytest
from Bio import SeqIO

from app.models.schemas import ConstructOutputRun
from app.services.construct_output import _build_genbank, _compute_checksum


_SAMPLE_NT = (
    "GCCACCAAAAAA"
    "ATGGATGCCATGAAGCGGGGCCTG"
    "AACATCATCCAGCTGCTG"
    "TAA"
    "CTGGAGCCTCGG"
    + "A" * 30
)


def test_checksum_is_deterministic() -> None:
    """Same input → exactly the same hash, every time. The audit card
    stamps this value; if it ever drifted on a re-run we would have no
    way to verify a previously-released construct."""
    a = _compute_checksum(_SAMPLE_NT)
    b = _compute_checksum(_SAMPLE_NT)
    assert a == b
    assert a.startswith("sha256:")
    # 16-hex-char short form after the prefix.
    assert len(a) == len("sha256:") + 16


def test_checksum_changes_on_single_base_change() -> None:
    """The checksum must be sensitive — a one-nucleotide edit anywhere
    in the mRNA must flip it. Guards against degenerate hashes (e.g.
    hashing only length or composition)."""
    original = _compute_checksum(_SAMPLE_NT)
    perturbed = _compute_checksum(_SAMPLE_NT[:100] + "G" + _SAMPLE_NT[101:])
    assert original != perturbed, (
        "Checksum unchanged after a single-base edit — not actually "
        "hashing the full sequence."
    )


def test_genbank_round_trip_preserves_sequence() -> None:
    """Belt-and-braces on top of test_construct_genbank.py: confirm
    parse(serialize(...)) yields the identical sequence bytes. If
    Biopython's GenBank writer ever starts wrapping / case-changing /
    trimming the sequence, this catches it immediately."""
    class _Stub:
        pass

    summary = _Stub()
    summary.flanks = _Stub()
    summary.flanks.utr5 = "GCCACCAAA"
    summary.flanks.utr3 = "CTGGAGCCT"
    summary.flanks.poly_a = 30
    summary.aa_seq = "MDAMKRGL"
    summary.segments = []
    runs = [
        ConstructOutputRun(kind="utr5", label="5' UTR", nt="GCCACCAAAAAA"),
        ConstructOutputRun(
            kind="signal", label="SP", nt="ATGGATGCCATGAAGCGGGGCCTG"
        ),
        ConstructOutputRun(kind="classI", label="KIT", nt="AACATCATCCAGCTGCTG"),
        ConstructOutputRun(kind="stop", label="stop", nt="TAA"),
        ConstructOutputRun(kind="utr3", label="3' UTR", nt="CTGGAGCCTCGG"),
        ConstructOutputRun(kind="polyA", label="poly(A)30", nt="A" * 30),
    ]

    gb = _build_genbank(summary, runs, "CS-VAL-001", "Homo sapiens")
    record = SeqIO.read(io.StringIO(gb), "genbank")
    assert str(record.seq).upper() == "".join(r.nt for r in runs).upper()


def test_checksum_deterministic_across_python_sessions() -> None:
    """Pin a specific hash for a canonical input string. If this test
    ever fails, either the hashing algorithm changed (catastrophic for
    audit) or the checksum format changed (breaking change — update
    the audit-card parser)."""
    # Canonical input + expected hash, computed once and baked in.
    pinned_input = "ATGAAACCCGGGTAA" + "A" * 20
    # sha256 of that string's utf-8 bytes, first 16 hex chars:
    assert (
        _compute_checksum(pinned_input)
        == "sha256:cfd25e92124aaa19"
    )
