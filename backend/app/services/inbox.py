"""Inbox listing service.

The app replaces OS file pickers with a fixed inbox directory. The host path
(under the user's chosen data root) is bind-mounted into the container at
``/inbox``. Users drop FASTQ/BAM/CRAM files there; the renderer lists the
folder via ``GET /api/inbox`` and lets the user pick from that list when
registering files into a workspace.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from app.runtime import get_inbox_root


FASTQ_SUFFIXES = (".fastq", ".fq", ".fastq.gz", ".fq.gz")
BAM_SUFFIXES = (".bam",)
CRAM_SUFFIXES = (".cram",)


@dataclass(frozen=True)
class InboxEntry:
    name: str
    path: str  # absolute path inside the container (bind-mount target)
    size_bytes: int
    modified_at: str  # ISO-8601 UTC
    kind: str  # "fastq" | "bam" | "cram" | "unknown"


def _classify(name: str) -> str:
    lowered = name.lower()
    if lowered.endswith(FASTQ_SUFFIXES):
        return "fastq"
    if lowered.endswith(BAM_SUFFIXES):
        return "bam"
    if lowered.endswith(CRAM_SUFFIXES):
        return "cram"
    return "unknown"


def list_inbox() -> list[InboxEntry]:
    """Return entries in the inbox, sorted newest-first by mtime.

    Hidden files, directories, and files of unknown type are skipped — the
    UI only cares about sequencing files. Returns an empty list if the inbox
    directory is empty (or hasn't been populated yet).
    """
    root = get_inbox_root()
    entries: list[InboxEntry] = []
    try:
        iterator = root.iterdir()
    except FileNotFoundError:
        return []
    for child in iterator:
        if child.name.startswith("."):
            continue
        if not child.is_file():
            continue
        kind = _classify(child.name)
        if kind == "unknown":
            continue
        try:
            stat = child.stat()
        except OSError:
            continue
        modified_at = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat()
        entries.append(
            InboxEntry(
                name=child.name,
                path=str(child),
                size_bytes=stat.st_size,
                modified_at=modified_at,
                kind=kind,
            )
        )
    entries.sort(key=lambda e: e.modified_at, reverse=True)
    return entries
