"""IPD-IMGT/HLA allele list lookup for disambiguating concatenated DTU names.

The DTU NetMHCIIpan pseudosequence file uses concatenated allele names like
``HLA-DPA10103-DPB110401`` where the digits are ambiguous: ``10401`` could be
``DPB1*10:401`` or ``DPB1*104:01``. The official IPD-IMGT/HLA allele list
resolves this — exactly one of those candidates is a registered allele.

The list ships at https://github.com/ANHIG/IMGTHLA/Allelelist.txt and is
fetched on demand via ``scripts/mhc2_fetch_data.py ipd_imgt_hla``. Without
the file, ``known_two_field`` returns an empty set and the caller should
fall back to a 2-digit-family default.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

DEFAULT_REPO_DATA_DIR = Path(__file__).resolve().parents[4] / "data" / "mhc2"


def _candidate_paths() -> list[Path]:
    paths: list[Path] = []
    env = os.environ.get("CANCERSTUDIO_IPD_ALLELELIST")
    if env:
        paths.append(Path(env))
    paths.append(DEFAULT_REPO_DATA_DIR / "ipd_imgt_hla" / "Allelelist.txt")
    paths.append(DEFAULT_REPO_DATA_DIR / "references" / "Allelelist.txt")
    return paths


def _read_allele_list(path: Path) -> dict[str, set[str]]:
    by_locus: dict[str, set[str]] = {}
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "," not in line:
                continue
            _, allele = line.split(",", 1)
            if "*" not in allele or ":" not in allele:
                continue
            locus, fields = allele.split("*", 1)
            field_parts = fields.split(":")
            if len(field_parts) < 2:
                continue
            two = f"{field_parts[0]}:{field_parts[1].rstrip('LSQNCAlsqncan')}"
            by_locus.setdefault(locus, set()).add(two)
    return by_locus


@lru_cache(maxsize=1)
def _load() -> dict[str, set[str]]:
    for path in _candidate_paths():
        if path.is_file():
            return _read_allele_list(path)
    return {}


def known_two_field(locus: str) -> set[str]:
    """Return the set of valid 2-field codes (e.g. ``"15:01"``) for a locus."""
    return _load().get(locus, set())


def has_lookup() -> bool:
    """True when an IPD allele list was found on disk."""
    return bool(_load())


def reset_cache() -> None:
    """For tests."""
    _load.cache_clear()
