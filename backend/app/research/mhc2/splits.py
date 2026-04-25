"""Cluster-aware splitting and leakage reporting for MHC-II peptides."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Iterable

from app.research.mhc2.data import MHC2Record, peptide_9mers


@dataclass(frozen=True)
class LeakageReport:
    query_records: int
    overlapping_records: int
    query_9mers: int
    overlapping_9mers: int

    @property
    def record_fraction(self) -> float:
        return self.overlapping_records / self.query_records if self.query_records else 0.0

    @property
    def nine_mer_fraction(self) -> float:
        return self.overlapping_9mers / self.query_9mers if self.query_9mers else 0.0


def leakage_report(reference: Iterable[MHC2Record], query: Iterable[MHC2Record]) -> LeakageReport:
    reference_9mers = {core for record in reference for core in peptide_9mers(record.peptide)}
    query_records = 0
    overlapping_records = 0
    query_9mers: set[str] = set()
    overlapping_9mers: set[str] = set()
    for record in query:
        query_records += 1
        cores = set(peptide_9mers(record.peptide))
        query_9mers.update(cores)
        overlaps = cores & reference_9mers
        if overlaps:
            overlapping_records += 1
            overlapping_9mers.update(overlaps)
    return LeakageReport(
        query_records=query_records,
        overlapping_records=overlapping_records,
        query_9mers=len(query_9mers),
        overlapping_9mers=len(overlapping_9mers),
    )


def assign_cluster_splits(
    records: list[MHC2Record],
    train_fraction: float = 0.8,
    valid_fraction: float = 0.1,
    seed: str = "cancerstudio-mhc2-v1",
) -> list[MHC2Record]:
    """Assign splits by connected components of shared 9-mers.

    Any peptides sharing a 9-mer are kept in the same component, preventing
    trivial train/test leakage for the binding-core signal.
    """
    if train_fraction <= 0 or valid_fraction < 0 or train_fraction + valid_fraction >= 1:
        raise ValueError("fractions must satisfy 0 < train, 0 <= valid, train + valid < 1")

    parent: dict[str, str] = {}

    def find(item: str) -> str:
        parent.setdefault(item, item)
        while parent[item] != item:
            parent[item] = parent[parent[item]]
            item = parent[item]
        return item

    def union(a: str, b: str) -> None:
        root_a = find(a)
        root_b = find(b)
        if root_a != root_b:
            parent[max(root_a, root_b)] = min(root_a, root_b)

    record_cores: list[tuple[str, ...]] = []
    for record in records:
        cores = peptide_9mers(record.peptide)
        record_cores.append(cores)
        first = cores[0]
        find(first)
        for core in cores[1:]:
            union(first, core)

    assigned: list[MHC2Record] = []
    for record, cores in zip(records, record_cores):
        cluster = find(cores[0])
        bucket = _stable_unit_interval(f"{seed}:{cluster}")
        if bucket < train_fraction:
            split = "train"
        elif bucket < train_fraction + valid_fraction:
            split = "valid"
        else:
            split = "test"
        assigned.append(MHC2Record.from_json({**record.to_json(), "split": split}))
    return assigned


def _stable_unit_interval(value: str) -> float:
    digest = hashlib.sha256(value.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") / 2**64
