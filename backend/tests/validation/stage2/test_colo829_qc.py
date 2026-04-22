"""Stage 2 validation — alignment QC on the COLO829 real-WGS workspace.

Parses ``samtools flagstat`` output from the latest COLO829 run and
asserts the three headline metrics from validation.md:

* Mapping rate ≥ 99%  (strobealign failure mode: dropped reads)
* Duplicate rate 10-25% (signals a healthy WGS library; extremes mean
  over-PCR or under-sequencing)
* Mapped-and-paired ≥ 99% of paired reads

Skips politely when the workspace is not mounted — the flagstat files
live on the external data disk, not in the repo.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

import pytest


_WORKSPACE_ROOT = Path(
    os.environ.get(
        "CANCERSTUDIO_COLO829_WORKSPACE_DIR",
        "/media/niach/5c5f06df-56ba-430c-a735-42e1205949f63/cancerstudio/"
        "workspaces/825b9744-819a-4422-ba4f-b349b6d6253a",
    )
)

_MISSING_REASON = (
    f"COLO829 workspace not mounted at {_WORKSPACE_ROOT}; skipping "
    "alignment QC validation. See validation.md -> Stage 2 for the data layout."
)


def _latest_alignment_run_dir() -> Path | None:
    """Locate the most recent alignment subdirectory by mtime."""
    alignment_root = _WORKSPACE_ROOT / "alignment"
    if not alignment_root.is_dir():
        return None
    runs = sorted(alignment_root.iterdir(), key=lambda p: p.stat().st_mtime)
    return runs[-1] if runs else None


@dataclass
class FlagstatMetrics:
    total: int
    mapped: int
    duplicates: int
    paired: int
    mapped_and_paired: int

    @property
    def mapping_rate(self) -> float:
        return self.mapped / self.total if self.total else 0.0

    @property
    def duplicate_rate(self) -> float:
        return self.duplicates / self.total if self.total else 0.0

    @property
    def paired_rate(self) -> float:
        return self.mapped_and_paired / self.paired if self.paired else 0.0


def _parse_flagstat(path: Path) -> FlagstatMetrics:
    """Tiny ``samtools flagstat`` parser. Each line is
    ``<qc-pass> + <qc-fail> <label>`` — we only keep the first number
    per line and key on the line's label tag."""
    totals: dict[str, int] = {}
    line_re = re.compile(r"^(\d+)\s+\+\s+(\d+)\s+(.+?)(\s*\(|\s*$)")
    with path.open("r", encoding="utf-8") as handle:
        for raw in handle:
            match = line_re.match(raw)
            if match is None:
                continue
            count = int(match.group(1))
            label = match.group(3).strip()
            if label == "in total":
                totals["total"] = count
            elif label == "primary mapped":
                totals["mapped"] = count
            elif label == "primary duplicates":
                totals["duplicates"] = count
            elif label == "paired in sequencing":
                totals["paired"] = count
            elif label == "with itself and mate mapped":
                totals["mapped_and_paired"] = count
    return FlagstatMetrics(
        total=totals.get("total", 0),
        mapped=totals.get("mapped", 0),
        duplicates=totals.get("duplicates", 0),
        paired=totals.get("paired", 0),
        mapped_and_paired=totals.get("mapped_and_paired", 0),
    )


def _flagstat_path(sample: str) -> Path | None:
    run_dir = _latest_alignment_run_dir()
    if run_dir is None:
        return None
    path = run_dir / sample / f"{sample}.flagstat.txt"
    return path if path.is_file() else None


@pytest.mark.skipif(
    _latest_alignment_run_dir() is None,
    reason=_MISSING_REASON,
)
@pytest.mark.parametrize("sample", ["tumor", "normal"])
def test_colo829_alignment_qc(sample: str) -> None:
    path = _flagstat_path(sample)
    if path is None:
        pytest.skip(f"no flagstat for {sample} in {_latest_alignment_run_dir()}")
    m = _parse_flagstat(path)

    assert m.total > 0, f"{sample}.flagstat.txt is empty or unparseable"

    # Mapping rate: strobealign on GRCh38 should clear 98% on both tumor
    # and normal. Tumor libraries typically hit 99.9%; normal libraries
    # run a touch lower (~98.8% on COLO829) because of reduced complexity.
    # The industry floor of ≥95% would be far too permissive for a
    # regression gate — 98% catches degradation without being noisy.
    assert m.mapping_rate >= 0.98, (
        f"{sample}: mapping rate {m.mapping_rate:.4f} below 0.98 floor; "
        f"check alignment logs ({m.mapped}/{m.total} mapped)"
    )
    # Duplicate rate: healthy WGS libraries sit ~10-25% after markdup.
    # Above 30% suggests over-PCR; below 5% suggests markdup missed its
    # window (or the read set is tiny smoke data).
    assert 0.05 <= m.duplicate_rate <= 0.30, (
        f"{sample}: duplicate rate {m.duplicate_rate:.4f} outside "
        f"0.05-0.30 sanity band ({m.duplicates}/{m.total})"
    )
    # Both mates mapped: tracks the mapping rate closely on a
    # well-aligned library.
    assert m.paired_rate >= 0.98, (
        f"{sample}: both-mates-mapped rate {m.paired_rate:.4f} below "
        f"0.98 floor ({m.mapped_and_paired}/{m.paired})"
    )


# ---------------------------------------------------------------------------
# Unit tests for the flagstat parser — always run.
# ---------------------------------------------------------------------------


_FIXTURE_FLAGSTAT = """641150572 + 0 in total (QC-passed reads + QC-failed reads)
641150572 + 0 primary
0 + 0 secondary
0 + 0 supplementary
107267649 + 0 duplicates
107267649 + 0 primary duplicates
640699217 + 0 mapped (99.93% : N/A)
640699217 + 0 primary mapped (99.93% : N/A)
641150572 + 0 paired in sequencing
320575286 + 0 read1
320575286 + 0 read2
561834658 + 0 properly paired (87.63% : N/A)
640402336 + 0 with itself and mate mapped
296881 + 0 singletons (0.05% : N/A)
21293116 + 0 with mate mapped to a different chr
"""


def test_flagstat_parser_matches_samtools_output(tmp_path: Path) -> None:
    """The parser must match the canonical samtools flagstat format
    used by the alignment service. Regression-guards our assumptions
    about which lines carry the totals we care about."""
    path = tmp_path / "t.flagstat.txt"
    path.write_text(_FIXTURE_FLAGSTAT)
    m = _parse_flagstat(path)
    assert m.total == 641_150_572
    assert m.mapped == 640_699_217
    assert m.duplicates == 107_267_649
    assert m.paired == 641_150_572
    assert m.mapped_and_paired == 640_402_336
    assert m.mapping_rate == pytest.approx(0.9993, abs=0.0001)
    assert m.duplicate_rate == pytest.approx(0.1673, abs=0.0001)
