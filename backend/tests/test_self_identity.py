"""Unit tests for the stage-6 self-identity check.

DIAMOND and the proteome database are not checked into the repo, so the
tests here either:

1. exercise the pure helpers (`_risk_for`, `_gene_label`) directly, or
2. monkeypatch `subprocess.run` and `shutil.which` to simulate a
   successful DIAMOND invocation.

An integration test that actually invokes DIAMOND is out of scope for
the fast suite — it would require the backend image (which ships the
binary) plus network-bootstrapped Swiss-Prot DB, both of which are slow
and flaky.
"""
from __future__ import annotations

import subprocess
import types
from pathlib import Path

import pytest

from app.models.schemas import EpitopeSafetyFlagResponse, ReferencePreset
from app.services import self_identity


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "pident,expected",
    [
        (100.0, "critical"),
        (99.999, "critical"),
        (95.0, "elevated"),
        (80.0, "elevated"),
        (79.999, "mild"),
        (60.0, "mild"),
        (59.999, None),
        (0.0, None),
    ],
)
def test_risk_tier_boundaries(pident: float, expected: str | None) -> None:
    assert self_identity._risk_for(pident) == expected


@pytest.mark.parametrize(
    "stitle,sseqid,expected",
    [
        # UniProt format with GN=
        (
            "sp|P35579|MYH9_HUMAN Myosin-9 OS=Homo sapiens OX=9606 GN=MYH9 PE=1 SV=4",
            "sp|P35579|MYH9_HUMAN",
            "MYH9",
        ),
        # No GN, protein-name fallback with OS/PE/SV trimmed
        (
            "sp|Q7Z4V5|HDGR2_HUMAN Hepatoma-derived growth factor-related protein 2 OS=Homo sapiens",
            "sp|Q7Z4V5|HDGR2_HUMAN",
            "Hepatoma-derived growth factor-related protein 2",
        ),
        # Pathological: title is just the accession
        ("sp|P12345|FOO", "sp|P12345|FOO", "sp|P12345|FOO"),
    ],
)
def test_gene_label_parsing(stitle: str, sseqid: str, expected: str) -> None:
    assert self_identity._gene_label(stitle, sseqid) == expected


# ---------------------------------------------------------------------------
# run_self_identity_check — happy path (monkeypatched DIAMOND)
# ---------------------------------------------------------------------------


def _patch_diamond_available(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        self_identity.shutil, "which",
        lambda name: "/usr/local/bin/diamond" if name == "diamond" else None,
    )


def _fake_proteome(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Make resolve_proteome_config return a concrete path pair without
    requiring any real bootstrap."""
    fasta = tmp_path / "swissprot.fasta"
    dmnd = tmp_path / "swissprot.dmnd"
    fasta.write_text(">sp|P00000|FAKE Fake protein GN=FAKE\nACDEFGHIK\n")
    dmnd.write_bytes(b"\x00" * 16)
    monkeypatch.setattr(
        self_identity, "resolve_proteome_config",
        lambda preset: self_identity.ProteomeConfig(
            fasta_path=fasta, dmnd_path=dmnd, label="test proteome"
        ),
    )
    monkeypatch.setattr(
        self_identity, "ensure_proteome_ready",
        lambda preset: self_identity.ProteomeConfig(
            fasta_path=fasta, dmnd_path=dmnd, label="test proteome"
        ),
    )


def _canned_diamond(stdout: str):
    def fake_run(cmd, **kwargs):  # noqa: ANN001
        assert cmd[0] == "diamond"
        assert cmd[1] == "blastp"
        return subprocess.CompletedProcess(cmd, 0, stdout=stdout, stderr="")
    return fake_run


def test_returns_empty_when_diamond_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fake_proteome(tmp_path, monkeypatch)
    monkeypatch.setattr(self_identity.shutil, "which", lambda _name: None)
    result = self_identity.run_self_identity_check(
        [("ep1", "ACDEFGHIK")], ReferencePreset.GRCH38,
    )
    assert result == {}


def test_returns_empty_when_proteome_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(self_identity, "ensure_proteome_ready", lambda p: None)
    _patch_diamond_available(monkeypatch)
    result = self_identity.run_self_identity_check(
        [("ep1", "ACDEFGHIK")], ReferencePreset.GRCH38,
    )
    assert result == {}


def test_returns_empty_on_empty_input(monkeypatch: pytest.MonkeyPatch) -> None:
    # Should short-circuit before touching subprocess or filesystem.
    result = self_identity.run_self_identity_check([], ReferencePreset.GRCH38)
    assert result == {}


def test_parses_critical_hit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fake_proteome(tmp_path, monkeypatch)
    _patch_diamond_available(monkeypatch)
    # 100% identity over 9 aa → critical
    stdout = (
        "ep30\tsp|P35579|MYH9_HUMAN\t"
        "sp|P35579|MYH9_HUMAN Myosin-9 OS=Homo sapiens GN=MYH9 PE=1 SV=4\t"
        "100.0\t9\n"
    )
    monkeypatch.setattr(subprocess, "run", _canned_diamond(stdout))

    result = self_identity.run_self_identity_check(
        [("ep30", "PLRRLAEEL")], ReferencePreset.GRCH38,
    )

    assert set(result.keys()) == {"ep30"}
    flag = result["ep30"]
    assert isinstance(flag, EpitopeSafetyFlagResponse)
    assert flag.peptide_id == "ep30"
    assert flag.self_hit == "MYH9"
    assert flag.identity == 100
    assert flag.risk == "critical"
    assert "perfect 9-mer match" in flag.note


def test_parses_elevated_and_mild_hits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fake_proteome(tmp_path, monkeypatch)
    _patch_diamond_available(monkeypatch)
    stdout = (
        # elevated
        "ep31\tsp|Q12345|TTN_HUMAN\tTitin OS=Homo sapiens GN=TTN\t85.5\t9\n"
        # mild
        "ep32\tsp|P45678|COL1A1_HUMAN\tCollagen-1 GN=COL1A1\t65.3\t8\n"
        # below floor — should be dropped
        "ep33\tsp|PXXXX|FOO_HUMAN\tFoo GN=FOO\t40.0\t7\n"
    )
    monkeypatch.setattr(subprocess, "run", _canned_diamond(stdout))

    result = self_identity.run_self_identity_check(
        [("ep31", "ABCDEFGHI"), ("ep32", "ABCDEFGHI"), ("ep33", "ABCDEFGHI")],
        ReferencePreset.GRCH38,
    )
    assert set(result.keys()) == {"ep31", "ep32"}
    assert result["ep31"].risk == "elevated"
    assert result["ep31"].self_hit == "TTN"
    assert result["ep32"].risk == "mild"
    assert result["ep32"].self_hit == "COL1A1"


def test_keeps_only_best_hit_per_peptide(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fake_proteome(tmp_path, monkeypatch)
    _patch_diamond_available(monkeypatch)
    # BLAST sorts by E-value within each query; the first row per qseqid
    # is the best hit. The second row should be discarded.
    stdout = (
        "ep1\tsp|P1|A_HUMAN\tProtein A GN=A\t95.0\t9\n"
        "ep1\tsp|P2|B_HUMAN\tProtein B GN=B\t75.0\t9\n"
    )
    monkeypatch.setattr(subprocess, "run", _canned_diamond(stdout))
    result = self_identity.run_self_identity_check(
        [("ep1", "ABCDEFGHI")], ReferencePreset.GRCH38,
    )
    assert result["ep1"].self_hit == "A"
    assert result["ep1"].risk == "elevated"


def test_returns_empty_on_diamond_nonzero_exit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fake_proteome(tmp_path, monkeypatch)
    _patch_diamond_available(monkeypatch)

    def blow_up(cmd, **kwargs):  # noqa: ANN001
        raise subprocess.CalledProcessError(1, cmd, output="", stderr="boom")

    monkeypatch.setattr(subprocess, "run", blow_up)
    result = self_identity.run_self_identity_check(
        [("ep1", "ABCDEFGHI")], ReferencePreset.GRCH38,
    )
    assert result == {}
