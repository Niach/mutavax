"""Stage 1 validation — inbox classification + listing invariants.

Stage 1 is a metadata-only stage: the app lists files dropped into
``${CANCERSTUDIO_INBOX_DIR}`` and classifies them by extension. No
FASTQ→BAM→FASTQ round-trip happens here (that would be stage 2 if we
ran strobealign through a BAM input). What *does* need validating is:

* every supported sequencing file extension maps to the expected kind
* the listing skips hidden files, directories, and unknown types
* empty-inbox and missing-inbox paths both return ``[]`` without
  raising

Pure-unit; runs in milliseconds; no external dependencies.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.services.inbox import _classify, list_inbox


@pytest.mark.parametrize(
    "filename,expected",
    [
        ("tumor_R1.fastq.gz", "fastq"),
        ("TUMOR_R1.FASTQ.GZ", "fastq"),  # case-insensitive
        ("normal_R2.fq.gz", "fastq"),
        ("sample.fastq", "fastq"),
        ("sample.fq", "fastq"),
        ("aligned.bam", "bam"),
        ("aligned.cram", "cram"),
        ("README.md", "unknown"),
        ("genome.fa", "unknown"),
        ("config.yaml", "unknown"),
        (".hidden.fastq", "fastq"),  # classifier ignores the dot prefix
    ],
)
def test_classifier_maps_known_extensions(filename: str, expected: str) -> None:
    assert _classify(filename) == expected


def test_inbox_listing_skips_hidden_and_directories(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Only regular files with recognised sequencing extensions should
    make it into the list. Hidden files, directories, and unknown
    extensions must be suppressed."""
    monkeypatch.setattr("app.services.inbox.get_inbox_root", lambda: tmp_path)

    (tmp_path / "tumor_R1.fastq.gz").write_bytes(b"x")
    (tmp_path / "tumor_R2.fastq.gz").write_bytes(b"x")
    (tmp_path / "aligned.bam").write_bytes(b"x")
    (tmp_path / ".DS_Store").write_bytes(b"x")
    (tmp_path / "README.md").write_bytes(b"x")
    (tmp_path / "old_runs").mkdir()

    entries = list_inbox()
    names = {e.name for e in entries}
    assert names == {"tumor_R1.fastq.gz", "tumor_R2.fastq.gz", "aligned.bam"}
    # Kind must be correct for each.
    kinds = {e.name: e.kind for e in entries}
    assert kinds["tumor_R1.fastq.gz"] == "fastq"
    assert kinds["aligned.bam"] == "bam"


def test_inbox_listing_handles_empty_and_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Empty inbox → empty list; missing inbox → empty list (not an
    exception). Either case is a valid initial state before the user
    drops their first file."""
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.setattr("app.services.inbox.get_inbox_root", lambda: empty)
    assert list_inbox() == []

    missing = tmp_path / "does_not_exist"
    monkeypatch.setattr("app.services.inbox.get_inbox_root", lambda: missing)
    assert list_inbox() == []
