"""On-disk resume manifest for the chunked alignment pipeline.

The manifest lives at ``{run_dir}/manifest.json`` and tracks per-lane split
status + which chunk indices have produced a final coord-sorted BAM. It is
the source of truth for resume: the in-memory ``_chunk_progress_store`` is a
live cache that's rebuilt from the manifest when a run resumes.

Format:

.. code-block:: json

    {
      "version": 1,
      "run_id": "...",
      "chunk_reads_per_chunk": 20000000,
      "lanes": {
        "tumor":  {"split_status": "completed",
                    "total_chunks": 200,
                    "completed_chunks": [0, 1, 2, 5, ...]},
        "normal": {"split_status": "running",
                    "total_chunks": 0,
                    "completed_chunks": []}
      }
    }
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Optional

from app.runtime import atomic_read_json, atomic_write_json

MANIFEST_VERSION = 1
MANIFEST_FILENAME = "manifest.json"

SplitStatus = Literal["pending", "running", "completed"]


@dataclass
class LaneManifestState:
    split_status: SplitStatus = "pending"
    total_chunks: int = 0
    completed_chunks: list[int] = field(default_factory=list)


@dataclass
class ResumeManifest:
    version: int = MANIFEST_VERSION
    run_id: str = ""
    chunk_reads_per_chunk: int = 0
    lanes: dict[str, LaneManifestState] = field(default_factory=dict)

    def lane(self, lane_value: str) -> LaneManifestState:
        state = self.lanes.get(lane_value)
        if state is None:
            state = LaneManifestState()
            self.lanes[lane_value] = state
        return state

    def to_dict(self) -> dict:
        return {
            "version": self.version,
            "run_id": self.run_id,
            "chunk_reads_per_chunk": self.chunk_reads_per_chunk,
            "lanes": {
                lane_value: {
                    "split_status": state.split_status,
                    "total_chunks": state.total_chunks,
                    "completed_chunks": sorted(set(state.completed_chunks)),
                }
                for lane_value, state in self.lanes.items()
            },
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ResumeManifest":
        lanes: dict[str, LaneManifestState] = {}
        for lane_value, lane_data in (data.get("lanes") or {}).items():
            if not isinstance(lane_data, dict):
                continue
            split_status = lane_data.get("split_status", "pending")
            if split_status not in {"pending", "running", "completed"}:
                split_status = "pending"
            completed_raw = lane_data.get("completed_chunks") or []
            completed: list[int] = []
            for idx in completed_raw:
                try:
                    completed.append(int(idx))
                except (TypeError, ValueError):
                    continue
            lanes[lane_value] = LaneManifestState(
                split_status=split_status,
                total_chunks=int(lane_data.get("total_chunks") or 0),
                completed_chunks=sorted(set(completed)),
            )
        return cls(
            version=int(data.get("version") or MANIFEST_VERSION),
            run_id=str(data.get("run_id") or ""),
            chunk_reads_per_chunk=int(data.get("chunk_reads_per_chunk") or 0),
            lanes=lanes,
        )


# Process-wide lock — manifest writes are rare (per chunk completion), so a
# single lock is simpler than per-file locks and correct for the current
# single-run-at-a-time semantics.
_manifest_lock = threading.Lock()


def manifest_path(run_dir: Path) -> Path:
    return run_dir / MANIFEST_FILENAME


def load_manifest(run_dir: Path) -> Optional[ResumeManifest]:
    """Read manifest from run_dir. Returns None if missing or version mismatch."""
    data = atomic_read_json(manifest_path(run_dir))
    if not isinstance(data, dict):
        return None
    try:
        version = int(data.get("version") or 0)
    except (TypeError, ValueError):
        return None
    if version != MANIFEST_VERSION:
        return None
    return ResumeManifest.from_dict(data)


def save_manifest(run_dir: Path, manifest: ResumeManifest) -> None:
    atomic_write_json(manifest_path(run_dir), manifest.to_dict())


def _load_or_init(run_dir: Path, run_id: str, chunk_reads: int) -> ResumeManifest:
    manifest = load_manifest(run_dir)
    if manifest is None:
        manifest = ResumeManifest(
            run_id=run_id, chunk_reads_per_chunk=chunk_reads
        )
    return manifest


def initialize_manifest(
    run_dir: Path, run_id: str, chunk_reads: int, lanes: list[str]
) -> ResumeManifest:
    """Create a manifest for a fresh run, persisting empty per-lane state.

    If an existing manifest is present (resume case), returns it unchanged.
    """
    with _manifest_lock:
        existing = load_manifest(run_dir)
        if existing is not None and existing.run_id == run_id:
            return existing
        manifest = ResumeManifest(
            run_id=run_id,
            chunk_reads_per_chunk=chunk_reads,
            lanes={lane: LaneManifestState() for lane in lanes},
        )
        save_manifest(run_dir, manifest)
        return manifest


def mark_split_status(
    run_dir: Path,
    lane_value: str,
    status: SplitStatus,
    *,
    total_chunks: Optional[int] = None,
) -> None:
    with _manifest_lock:
        manifest = load_manifest(run_dir)
        if manifest is None:
            return
        lane = manifest.lane(lane_value)
        lane.split_status = status
        if total_chunks is not None:
            lane.total_chunks = total_chunks
        save_manifest(run_dir, manifest)


def mark_chunk_complete(run_dir: Path, lane_value: str, chunk_idx: int) -> None:
    """Add chunk_idx to the lane's completed_chunks set. Threadsafe."""
    with _manifest_lock:
        manifest = load_manifest(run_dir)
        if manifest is None:
            return
        lane = manifest.lane(lane_value)
        if chunk_idx in lane.completed_chunks:
            return
        lane.completed_chunks = sorted(set(lane.completed_chunks + [chunk_idx]))
        save_manifest(run_dir, manifest)


def completed_chunk_indices(run_dir: Path, lane_value: str) -> set[int]:
    manifest = load_manifest(run_dir)
    if manifest is None:
        return set()
    return set(manifest.lane(lane_value).completed_chunks)


def lane_split_status(run_dir: Path, lane_value: str) -> SplitStatus:
    manifest = load_manifest(run_dir)
    if manifest is None:
        return "pending"
    return manifest.lane(lane_value).split_status
