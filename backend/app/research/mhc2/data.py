"""Data loading and leakage-aware dataset utilities for MHC-II training."""

from __future__ import annotations

import csv
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Iterator, Sequence

from app.research.mhc2.alleles import normalize_many, normalize_mhc2_allele
from app.research.mhc2.constants import (
    AMINO_ACIDS,
    MAX_PEPTIDE_LENGTH,
    MIN_PEPTIDE_LENGTH,
    MODEL_AMINO_ACIDS,
)


_PEPTIDE_RE = re.compile(rf"^[{AMINO_ACIDS}]+$")
_PSEUDOSEQ_RE = re.compile(rf"^[{MODEL_AMINO_ACIDS}]+$")


@dataclass(frozen=True)
class MHC2Record:
    peptide: str
    alleles: tuple[str, ...]
    target: float = 1.0
    source: str = "unknown"
    split: str | None = None
    sample_id: str | None = None
    protein_id: str | None = None
    weight: float = 1.0
    peptide_offset: int | None = None  # 0-based start in protein_id (proteome decoys)

    def to_json(self) -> dict:
        payload = asdict(self)
        payload["alleles"] = list(self.alleles)
        return payload

    @classmethod
    def from_json(cls, payload: dict) -> "MHC2Record":
        offset = payload.get("peptide_offset")
        return cls(
            peptide=clean_peptide(payload["peptide"]),
            alleles=tuple(payload.get("alleles") or ()),
            target=float(payload.get("target", 1.0)),
            source=payload.get("source") or "unknown",
            split=payload.get("split"),
            sample_id=payload.get("sample_id"),
            protein_id=payload.get("protein_id"),
            weight=float(payload.get("weight", 1.0)),
            peptide_offset=int(offset) if offset is not None else None,
        )


def clean_peptide(value: str) -> str:
    peptide = value.strip().upper()
    if not peptide or not _PEPTIDE_RE.match(peptide):
        raise ValueError(f"invalid peptide sequence: {value!r}")
    if not MIN_PEPTIDE_LENGTH <= len(peptide) <= MAX_PEPTIDE_LENGTH:
        raise ValueError(
            f"peptide length must be {MIN_PEPTIDE_LENGTH}-{MAX_PEPTIDE_LENGTH}: {value!r}"
        )
    return peptide


def peptide_9mers(peptide: str) -> tuple[str, ...]:
    peptide = clean_peptide(peptide)
    if len(peptide) < 9:
        return (peptide,)
    return tuple(peptide[i : i + 9] for i in range(len(peptide) - 8))


def iter_hlaiipred_positive_csv(
    path: Path, split: str | None = None
) -> Iterator[MHC2Record]:
    """Parse HLAIIPred Zenodo positive CSV files.

    Rows have one peptide and up to fourteen allele columns. Each row is a
    polyallelic sample-level positive, so we keep the allele set together and
    train the model with max-over-alleles multiple-instance supervision.
    """
    split_name = split or _split_from_filename(path)
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        allele_columns = [
            name for name in (reader.fieldnames or ()) if name.startswith("allele")
        ]
        for row in reader:
            if str(row.get("presented", "1")).strip() not in {
                "1",
                "1.0",
                "true",
                "True",
            }:
                continue
            try:
                peptide = clean_peptide(row["peptide"])
            except ValueError:
                continue
            raw_alleles = [
                row[name].strip()
                for name in allele_columns
                if row.get(name) and row[name].strip() not in {"0", "NA", "nan"}
            ]
            if not raw_alleles:
                continue
            try:
                alleles = normalize_many(tuple(raw_alleles))
            except ValueError:
                continue
            yield MHC2Record(
                peptide=peptide,
                alleles=alleles,
                target=1.0,
                source="hlaiipred_zenodo",
                split=split_name,
            )


def load_netmhciipan_allelelist(path: Path) -> dict[str, tuple[str, ...]]:
    """Read the NetMHCIIpan-4.3 ``allelelist`` mapping sample tags to alleles."""
    mapping: dict[str, tuple[str, ...]] = {}
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            if len(parts) < 2:
                continue
            tag = parts[0]
            raw_alleles = [item for item in parts[1].split(",") if item]
            try:
                alleles = normalize_many(tuple(raw_alleles))
            except ValueError:
                continue
            mapping[tag] = alleles
    return mapping


def iter_netmhciipan_partition_file(
    path: Path,
    *,
    allelelist: dict[str, tuple[str, ...]],
    source: str = "netmhciipan_43_el",
    split: str | None = None,
    positives_only: bool = True,
) -> Iterator[MHC2Record]:
    """Parse a NetMHCIIpan-4.3 EL/BA partition file (``c000_el`` ... ``c004_el``).

    Format is whitespace-separated ``peptide target tag context`` per line, with
    ``target == 1`` for ligands and ``target == 0`` for proteome decoys. The
    ``tag`` column keys into the partner ``allelelist`` file (comma-separated
    alleles per tag). The 16-residue ``context`` column is ignored.
    """
    split_name = split or _split_from_filename(path)
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            if len(parts) < 3:
                continue
            try:
                target = float(parts[1])
            except ValueError:
                continue
            if positives_only and target != 1.0:
                continue
            try:
                peptide = clean_peptide(parts[0])
            except ValueError:
                continue
            tag = parts[2]
            alleles = allelelist.get(tag)
            if not alleles:
                continue
            yield MHC2Record(
                peptide=peptide,
                alleles=alleles,
                target=target,
                source=source,
                split=split_name,
                sample_id=tag,
            )


def iter_generic_records(
    path: Path, source: str, split: str | None = None
) -> Iterator[MHC2Record]:
    """Parse a simple CSV/TSV with peptide, allele/alleles, and optional target."""
    delimiter = "\t" if path.suffix.lower() in {".tsv", ".txt"} else ","
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(_skip_comments(handle), delimiter=delimiter)
        for row in reader:
            peptide = clean_peptide(
                _first(row, ("peptide", "sequence", "ligand", "linear_sequence"))
            )
            allele_value = _first(row, ("alleles", "allele", "mhc", "mhc_restriction"))
            raw_alleles = [item.strip() for item in re.split(r"[;,]", allele_value) if item.strip()]
            alleles = normalize_many(tuple(raw_alleles))
            target_text = row.get("target") or row.get("presented") or row.get("label") or "1"
            yield MHC2Record(
                peptide=peptide,
                alleles=alleles,
                target=float(target_text),
                source=source,
                split=split,
                sample_id=row.get("sample_id") or row.get("sample"),
                protein_id=row.get("protein_id") or row.get("protein"),
            )


def load_pseudosequences(path: Path) -> dict[str, str]:
    """Load allele pseudosequences from common whitespace/CSV formats."""
    sequences: dict[str, str] = {}
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "," in line and "\t" not in line:
                parts = [part.strip() for part in line.split(",")]
            else:
                parts = line.split()
            if len(parts) < 2:
                continue
            try:
                allele = normalize_mhc2_allele(parts[0]).normalized
            except ValueError:
                allele = parts[0]
            sequence = parts[1].upper()
            if _PSEUDOSEQ_RE.match(sequence):
                sequences[allele] = sequence
    return sequences


def write_jsonl(records: Iterable[MHC2Record], path: Path) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record.to_json(), sort_keys=True) + "\n")
            count += 1
    return count


def read_jsonl(path: Path) -> Iterator[MHC2Record]:
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                yield MHC2Record.from_json(json.loads(line))


def load_records(
    path: Path, source: str | None = None, split: str | None = None
) -> list[MHC2Record]:
    if path.suffix.lower() == ".jsonl":
        return list(read_jsonl(path))
    if path.name.endswith("_positive.csv") or "hlaiipred" in (source or ""):
        return list(iter_hlaiipred_positive_csv(path, split=split))
    return list(iter_generic_records(path, source=source or path.stem, split=split))


def deduplicate_records(records: Iterable[MHC2Record]) -> list[MHC2Record]:
    seen: set[tuple[str, tuple[str, ...], float, str | None]] = set()
    deduped: list[MHC2Record] = []
    for record in records:
        key = (record.peptide, record.alleles, record.target, record.split)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(record)
    return deduped


def _split_from_filename(path: Path) -> str | None:
    name = path.name.lower()
    for split in ("train", "valid", "validation", "test"):
        if split in name:
            return "valid" if split == "validation" else split
    return None


def _skip_comments(handle: Iterable[str]) -> Iterator[str]:
    for line in handle:
        if not line.startswith("#"):
            yield line


def _first(row: dict[str, str], names: Sequence[str]) -> str:
    for name in names:
        value = row.get(name)
        if value:
            return value
    raise ValueError(f"missing required column; tried {', '.join(names)}")
