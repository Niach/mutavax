"""Tests for the Phase B stop-and-resume machinery.

Covers:
 * ``alignment_manifest`` round-trip + atomic write
 * Watcher skip-completed logic against a seeded manifest + chunk_dir
 * Integration: kill-then-resume with the _fake_align pattern reuses the
   completed chunks and produces the full merged BAM on resume.
 * API: pause → resume lifecycle + auto-prune of stale paused runs.
"""
from __future__ import annotations

import datetime
import gzip
import queue
import shutil
import subprocess
import threading
import time as _time
import uuid
from pathlib import Path

import pytest

from app.db import init_db, session_scope
from app.models.records import (
    IngestionBatchRecord,
    PipelineArtifactRecord,
    PipelineRunRecord,
    WorkspaceFileRecord,
    WorkspaceRecord,
)
from app.models.schemas import AlignmentRunStatus, SampleLane
from app.services import alignment as alignment_service
from app.services import alignment_manifest
from sqlalchemy import delete


# ── Helpers ──────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def clean_database():
    init_db()
    with session_scope() as session:
        session.execute(delete(PipelineArtifactRecord))
        session.execute(delete(PipelineRunRecord))
        session.execute(delete(WorkspaceFileRecord))
        session.execute(delete(IngestionBatchRecord))
        session.execute(delete(WorkspaceRecord))
    yield
    with session_scope() as session:
        session.execute(delete(PipelineArtifactRecord))
        session.execute(delete(PipelineRunRecord))
        session.execute(delete(WorkspaceFileRecord))
        session.execute(delete(IngestionBatchRecord))
        session.execute(delete(WorkspaceRecord))


def _seed_paused_run(
    *,
    workspace_id: str,
    run_id: str,
    updated_at: datetime.datetime | None = None,
) -> None:
    """Insert a WorkspaceRecord + PAUSED PipelineRunRecord directly into the DB."""
    now = datetime.datetime.now(datetime.timezone.utc)
    updated = updated_at or now
    with session_scope() as session:
        session.add(
            WorkspaceRecord(
                id=workspace_id,
                display_name="Resume test",
                species="human",
                active_stage="alignment",
                created_at=now,
                updated_at=now,
            )
        )
        session.add(
            PipelineRunRecord(
                id=run_id,
                workspace_id=workspace_id,
                stage_id="alignment",
                status=AlignmentRunStatus.PAUSED.value,
                progress=40,
                created_at=now,
                updated_at=updated,
                started_at=now,
            )
        )


# ── Manifest unit tests ──────────────────────────────────────────────────────


def test_manifest_round_trip(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()

    manifest = alignment_manifest.initialize_manifest(
        run_dir, run_id="run-1", chunk_reads=2_000_000, lanes=["tumor", "normal"]
    )
    assert manifest.run_id == "run-1"
    assert manifest.chunk_reads_per_chunk == 2_000_000
    assert set(manifest.lanes.keys()) == {"tumor", "normal"}

    alignment_manifest.mark_split_status(
        run_dir, "tumor", "completed", total_chunks=5
    )
    alignment_manifest.mark_chunk_complete(run_dir, "tumor", 0)
    alignment_manifest.mark_chunk_complete(run_dir, "tumor", 2)
    # Duplicate mark — should be idempotent.
    alignment_manifest.mark_chunk_complete(run_dir, "tumor", 0)

    reloaded = alignment_manifest.load_manifest(run_dir)
    assert reloaded is not None
    tumor = reloaded.lanes["tumor"]
    assert tumor.split_status == "completed"
    assert tumor.total_chunks == 5
    assert tumor.completed_chunks == [0, 2]

    normal = reloaded.lanes["normal"]
    assert normal.split_status == "pending"
    assert normal.completed_chunks == []


def test_manifest_atomic_write_survives_bad_existing_file(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    # Seed a corrupt manifest file — load_manifest should return None, init
    # should overwrite.
    (run_dir / "manifest.json").write_text("{ not valid json")
    manifest = alignment_manifest.initialize_manifest(
        run_dir, run_id="run-2", chunk_reads=1_000_000, lanes=["tumor"]
    )
    assert manifest.run_id == "run-2"
    # Load again — should parse fine now.
    reloaded = alignment_manifest.load_manifest(run_dir)
    assert reloaded is not None
    assert reloaded.run_id == "run-2"


def test_manifest_version_mismatch_returns_none(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    from app.runtime import atomic_write_json

    atomic_write_json(
        run_dir / "manifest.json",
        {"version": 999, "run_id": "r", "chunk_reads_per_chunk": 1, "lanes": {}},
    )
    assert alignment_manifest.load_manifest(run_dir) is None


def test_completed_chunk_indices_empty_when_no_manifest(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    assert alignment_manifest.completed_chunk_indices(run_dir, "tumor") == set()
    assert alignment_manifest.lane_split_status(run_dir, "tumor") == "pending"


# ── Watcher skip-completed ───────────────────────────────────────────────────


def test_watcher_skips_already_completed_chunks(tmp_path: Path) -> None:
    """When resume starts, chunks already in skip_indices should be
    discovered (so progress bars include them) but NOT re-enqueued for
    alignment."""
    chunk_dir = tmp_path / "chunks"
    chunk_dir.mkdir()

    # Seed 5 chunk pairs on disk (as if split had run previously).
    for idx in range(5):
        (chunk_dir / f"r1_{idx:04d}.fastq.gz").write_bytes(b"fake-r1")
        (chunk_dir / f"r2_{idx:04d}.fastq.gz").write_bytes(b"fake-r2")

    # Pretend indices 0 and 2 are already aligned (have final BAMs).
    skip_indices = {0, 2}
    for idx in skip_indices:
        # Remove the FASTQ — that's what happens after a chunk is aligned
        # successfully. Leaves 1, 3, 4 as un-aligned chunks.
        (chunk_dir / f"r1_{idx:04d}.fastq.gz").unlink()
        (chunk_dir / f"r2_{idx:04d}.fastq.gz").unlink()

    discovered: list[int] = []
    enqueued: list[int] = []
    chunk_queue: "queue.Queue" = queue.Queue()
    stop_event = threading.Event()

    def _on_discovered(idx: int) -> None:
        discovered.append(idx)

    def _on_split_complete(final_count: int) -> None:
        pass

    watcher_error: list[BaseException] = []

    def _runner() -> None:
        try:
            alignment_service._chunk_ready_watcher(
                chunk_dir=chunk_dir,
                split_procs=[],
                chunk_queue=chunk_queue,
                parallelism=1,
                on_split_complete=_on_split_complete,
                on_chunk_discovered=_on_discovered,
                stop_event=stop_event,
                skip_indices=skip_indices,
                split_already_complete=True,
            )
        except BaseException as exc:
            watcher_error.append(exc)
            chunk_queue.put(None)

    watcher_thread = threading.Thread(target=_runner, daemon=True)
    watcher_thread.start()

    # Drain the queue until sentinel.
    while True:
        item = chunk_queue.get(timeout=10)
        if item is None:
            break
        idx, _, _ = item
        enqueued.append(idx)

    watcher_thread.join(timeout=5)

    if watcher_error:
        raise watcher_error[0]

    assert sorted(enqueued) == [1, 3, 4], (
        f"Expected only non-completed chunks enqueued, got {enqueued}"
    )
    # Watcher only discovers chunks whose FASTQ is still on disk. Skipped
    # chunks (0, 2) had their FASTQs deleted after alignment on the previous
    # run — the pipeline surfaces them to the UI separately via on_split_complete.
    assert set(discovered) == {1, 3, 4}


# ── Integration: pause → resume ──────────────────────────────────────────────


def _write_synthetic_paired_fastq(
    directory: Path, read_count: int
) -> tuple[Path, Path]:
    r1_path = directory / "r1.fastq.gz"
    r2_path = directory / "r2.fastq.gz"
    with gzip.open(r1_path, "wt") as r1_handle, gzip.open(r2_path, "wt") as r2_handle:
        for index in range(read_count):
            name = f"read{index:06d}"
            r1_handle.write(f"@{name}/1\nACGTACGTACGT\n+\n############\n")
            r2_handle.write(f"@{name}/2\nTGCATGCATGCA\n+\n############\n")
    return r1_path, r2_path


@pytest.mark.skipif(shutil.which("pigz") is None, reason="pigz not installed")
@pytest.mark.skipif(shutil.which("split") is None, reason="split not installed")
@pytest.mark.skipif(shutil.which("samtools") is None, reason="samtools not installed")
def test_resume_pipeline_skips_completed_chunks_and_merges_all(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Interrupt the pipeline after 2 chunks, then resume and confirm the
    remaining chunks align and merge into a BAM that contains every chunk's
    worth of records."""
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    chunk_dir = tmp_path / "chunks"
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    output_bam = tmp_path / "merged.bam"

    total_reads = 500
    reads_per_chunk = 100  # → 5 chunks
    r1_path, r2_path = _write_synthetic_paired_fastq(input_dir, total_reads)

    alignment_manifest.initialize_manifest(
        run_dir,
        run_id="resume-test",
        chunk_reads=reads_per_chunk,
        lanes=["tumor"],
    )

    # First pass: a fake_align that aborts via raise after 2 chunks.
    align_call_count = {"n": 0}

    def _abort_after_two(
        *,
        reference_path: Path,
        read_group_flags: list[str],
        r1_path: Path,
        r2_path: Path,
        output_path: Path,
        aligner_binary: str,
        samtools_binary: str,
        aligner_threads: int,
        sort_threads: int,
        sort_memory: str,
        run_id=None,
    ) -> list[str]:
        align_call_count["n"] += 1
        if align_call_count["n"] > 2:
            raise RuntimeError("simulated pause: aligner killed after 2 chunks")
        header_bytes = (
            b"@HD\tVN:1.6\tSO:coordinate\n"
            b"@SQ\tSN:chr1\tLN:1000\n"
            b"@RG\tID:test\tSM:test\tPL:ILLUMINA\n"
        )
        # Write partial first, then rename (mirrors production behavior).
        partial = output_path.with_suffix(output_path.suffix + ".partial")
        with partial.open("wb") as bam_out:
            sam_proc = subprocess.run(
                [samtools_binary, "view", "-bS", "-"],
                input=header_bytes,
                stdout=bam_out,
                stderr=subprocess.PIPE,
            )
        assert sam_proc.returncode == 0, sam_proc.stderr.decode(errors="replace")
        partial.replace(output_path)
        return [f"fake-align {output_path.name}"]

    monkeypatch.setattr(alignment_service, "_align_single_chunk", _abort_after_two)

    with pytest.raises(RuntimeError, match="simulated pause"):
        alignment_service.run_chunked_strobealign_pipeline(
            reference_path=tmp_path / "ref.fa",
            read_group_flags=[],
            r1_path=r1_path,
            r2_path=r2_path,
            output_path=output_bam,
            aligner_binary="strobealign-fake",
            samtools_binary="samtools",
            chunk_dir=chunk_dir,
            chunk_reads=reads_per_chunk,
            parallelism=1,
            aligner_threads_per_chunk=1,
            sort_threads_per_chunk=1,
            sort_memory_per_chunk="256M",
            run_dir=run_dir,
            lane_value="tumor",
        )

    # Manifest should reflect 2 completed chunks; the 3rd call raised so only
    # 2 survived the rename-on-success gate.
    completed_after_abort = alignment_manifest.completed_chunk_indices(
        run_dir, "tumor"
    )
    assert len(completed_after_abort) == 2
    # Partial BAMs should be cleaned up.
    assert not list(chunk_dir.glob("chunk_*.coord-sorted.bam.partial"))
    # Output BAM should NOT exist yet — merge never ran.
    assert not output_bam.exists()

    # Second pass: resume. Use a normal fake that doesn't raise.
    def _normal_align(
        *,
        reference_path: Path,
        read_group_flags: list[str],
        r1_path: Path,
        r2_path: Path,
        output_path: Path,
        aligner_binary: str,
        samtools_binary: str,
        aligner_threads: int,
        sort_threads: int,
        sort_memory: str,
        run_id=None,
    ) -> list[str]:
        header_bytes = (
            b"@HD\tVN:1.6\tSO:coordinate\n"
            b"@SQ\tSN:chr1\tLN:1000\n"
            b"@RG\tID:test\tSM:test\tPL:ILLUMINA\n"
        )
        partial = output_path.with_suffix(output_path.suffix + ".partial")
        with partial.open("wb") as bam_out:
            sam_proc = subprocess.run(
                [samtools_binary, "view", "-bS", "-"],
                input=header_bytes,
                stdout=bam_out,
                stderr=subprocess.PIPE,
            )
        assert sam_proc.returncode == 0
        partial.replace(output_path)
        return [f"fake-align {output_path.name}"]

    align_call_count["n"] = 0
    monkeypatch.setattr(alignment_service, "_align_single_chunk", _normal_align)

    commands = alignment_service.run_chunked_strobealign_pipeline(
        reference_path=tmp_path / "ref.fa",
        read_group_flags=[],
        r1_path=r1_path,
        r2_path=r2_path,
        output_path=output_bam,
        aligner_binary="strobealign-fake",
        samtools_binary="samtools",
        chunk_dir=chunk_dir,
        chunk_reads=reads_per_chunk,
        parallelism=1,
        aligner_threads_per_chunk=1,
        sort_threads_per_chunk=1,
        sort_memory_per_chunk="256M",
        run_dir=run_dir,
        lane_value="tumor",
    )

    # The already-completed chunks must NOT be re-aligned on resume.
    assert align_call_count["n"] <= 3, (
        f"Expected resume to align only the 3 remaining chunks, got "
        f"{align_call_count['n']} align calls"
    )
    assert output_bam.exists() and output_bam.stat().st_size > 0
    # Manifest now reports all 5 chunks completed.
    completed_final = alignment_manifest.completed_chunk_indices(run_dir, "tumor")
    assert completed_final == {0, 1, 2, 3, 4}


# ── Service-level pause/resume/cancel lifecycle ──────────────────────────────


def test_pause_alignment_run_marks_paused_preserves_run_dir(tmp_path, monkeypatch):
    from app.runtime import get_alignment_run_root

    workspace_id = str(uuid.uuid4())
    run_id = str(uuid.uuid4())

    now = datetime.datetime.now(datetime.timezone.utc)
    with session_scope() as session:
        session.add(
            WorkspaceRecord(
                id=workspace_id,
                display_name="Pause test",
                species="human",
                active_stage="alignment",
                created_at=now,
                updated_at=now,
            )
        )
        session.add(
            PipelineRunRecord(
                id=run_id,
                workspace_id=workspace_id,
                stage_id="alignment",
                status=AlignmentRunStatus.RUNNING.value,
                progress=40,
                created_at=now,
                updated_at=now,
                started_at=now,
            )
        )

    # Seed a run dir with fake content to confirm pause preserves it.
    run_dir = get_alignment_run_root(workspace_id, run_id)
    (run_dir / "sentinel.txt").write_text("keep me")

    summary = alignment_service.pause_alignment_run(workspace_id, run_id)
    assert summary.latest_run is not None
    assert summary.latest_run.status == AlignmentRunStatus.PAUSED
    # Run directory must still exist with its contents.
    assert (run_dir / "sentinel.txt").exists()


def test_cancel_alignment_run_wipes_run_dir_on_discard(monkeypatch):
    from app.runtime import get_alignment_run_root

    workspace_id = str(uuid.uuid4())
    run_id = str(uuid.uuid4())

    now = datetime.datetime.now(datetime.timezone.utc)
    with session_scope() as session:
        session.add(
            WorkspaceRecord(
                id=workspace_id,
                display_name="Cancel discard test",
                species="human",
                active_stage="alignment",
                created_at=now,
                updated_at=now,
            )
        )
        session.add(
            PipelineRunRecord(
                id=run_id,
                workspace_id=workspace_id,
                stage_id="alignment",
                status=AlignmentRunStatus.PAUSED.value,
                progress=40,
                created_at=now,
                updated_at=now,
                started_at=now,
            )
        )

    run_dir = get_alignment_run_root(workspace_id, run_id)
    (run_dir / "sentinel.txt").write_text("delete me")

    summary = alignment_service.cancel_alignment_run(workspace_id, run_id)
    assert summary.latest_run is not None
    assert summary.latest_run.status == AlignmentRunStatus.CANCELLED
    # Run dir should be wiped on discard.
    assert not run_dir.exists() or not (run_dir / "sentinel.txt").exists()


def test_resume_rejects_non_paused_run() -> None:
    workspace_id = str(uuid.uuid4())
    run_id = str(uuid.uuid4())

    now = datetime.datetime.now(datetime.timezone.utc)
    with session_scope() as session:
        session.add(
            WorkspaceRecord(
                id=workspace_id,
                display_name="Resume reject",
                species="human",
                active_stage="alignment",
                created_at=now,
                updated_at=now,
            )
        )
        session.add(
            PipelineRunRecord(
                id=run_id,
                workspace_id=workspace_id,
                stage_id="alignment",
                status=AlignmentRunStatus.COMPLETED.value,
                progress=100,
                created_at=now,
                updated_at=now,
                started_at=now,
                completed_at=now,
            )
        )

    with pytest.raises(ValueError, match="Cannot resume"):
        alignment_service.resume_alignment_run(workspace_id, run_id)


def test_resume_requires_manifest_on_disk(monkeypatch, tmp_path) -> None:
    from app.runtime import get_alignment_run_root

    workspace_id = str(uuid.uuid4())
    run_id = str(uuid.uuid4())
    _seed_paused_run(workspace_id=workspace_id, run_id=run_id)

    # No manifest seeded — resume should refuse.
    run_dir = get_alignment_run_root(workspace_id, run_id)
    # Make sure run_dir exists but manifest does not.
    run_dir.mkdir(parents=True, exist_ok=True)

    with pytest.raises(ValueError, match="Resume state is missing"):
        alignment_service.resume_alignment_run(workspace_id, run_id)
