from __future__ import annotations

import gzip
import shutil
from pathlib import Path

import pytest

from app.services import alignment as alignment_service
from app.services.alignment import (
    ChunkProgressState,
    split_paired_fastq_into_chunks,
    run_chunked_strobealign_pipeline,
    get_chunk_progress_snapshot,
    record_chunk_progress,
    clear_chunk_progress,
)
from app.models.schemas import SampleLane


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


def _count_reads_in_gzipped_fastq(path: Path) -> int:
    count = 0
    with gzip.open(path, "rt") as handle:
        for line in handle:
            if line.startswith("@read"):
                count += 1
    return count


@pytest.mark.skipif(shutil.which("pigz") is None, reason="pigz not installed")
@pytest.mark.skipif(shutil.which("split") is None, reason="split not installed")
def test_split_paired_fastq_produces_matched_chunks(tmp_path: Path) -> None:
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    chunk_dir = tmp_path / "chunks"

    total_reads = 250
    reads_per_chunk = 80
    r1_path, r2_path = _write_synthetic_paired_fastq(input_dir, total_reads)

    chunks, commands = split_paired_fastq_into_chunks(
        r1_path=r1_path,
        r2_path=r2_path,
        chunk_dir=chunk_dir,
        reads_per_chunk=reads_per_chunk,
    )

    assert len(chunks) >= 2
    assert len(commands) == 4

    r1_total = 0
    for idx, (r1_chunk, r2_chunk) in enumerate(chunks):
        r1_count = _count_reads_in_gzipped_fastq(r1_chunk)
        r2_count = _count_reads_in_gzipped_fastq(r2_chunk)
        assert r1_count == r2_count, f"chunk {idx}: R1/R2 count mismatch"
        assert r1_count > 0
        r1_total += r1_count

    assert r1_total == total_reads


@pytest.mark.skipif(shutil.which("pigz") is None, reason="pigz not installed")
@pytest.mark.skipif(shutil.which("split") is None, reason="split not installed")
def test_split_paired_fastq_single_chunk_when_input_smaller_than_chunk(
    tmp_path: Path,
) -> None:
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    chunk_dir = tmp_path / "chunks"

    r1_path, r2_path = _write_synthetic_paired_fastq(input_dir, read_count=40)

    chunks, _ = split_paired_fastq_into_chunks(
        r1_path=r1_path,
        r2_path=r2_path,
        chunk_dir=chunk_dir,
        reads_per_chunk=1_000,
    )

    assert len(chunks) == 1
    r1_count = _count_reads_in_gzipped_fastq(chunks[0][0])
    r2_count = _count_reads_in_gzipped_fastq(chunks[0][1])
    assert r1_count == r2_count == 40


@pytest.mark.skipif(shutil.which("pigz") is None, reason="pigz not installed")
@pytest.mark.skipif(shutil.which("split") is None, reason="split not installed")
@pytest.mark.skipif(shutil.which("samtools") is None, reason="samtools not installed")
def test_run_chunked_strobealign_pipeline_merges_multiple_chunks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """End-to-end test of the split → fake-align → merge orchestrator.

    Replaces _align_single_chunk with a stub that writes a valid minimal BAM
    so we can exercise the split + merge paths without needing strobealign.
    """
    import subprocess

    input_dir = tmp_path / "input"
    input_dir.mkdir()
    chunk_dir = tmp_path / "chunks"
    output_bam = tmp_path / "merged.bam"

    r1_path, r2_path = _write_synthetic_paired_fastq(input_dir, read_count=300)

    def _fake_align(
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
        with output_path.open("wb") as bam_out:
            sam_proc = subprocess.run(
                [samtools_binary, "view", "-bS", "-"],
                input=header_bytes,
                stdout=bam_out,
                stderr=subprocess.PIPE,
            )
        assert sam_proc.returncode == 0, sam_proc.stderr.decode(errors="replace")
        return [f"fake-align {output_path.name}"]

    monkeypatch.setattr(alignment_service, "_align_single_chunk", _fake_align)

    progress_events: list[tuple[str, int, int, int]] = []

    def _on_progress(phase: str, total: int, completed: int, active: int) -> None:
        progress_events.append((phase, total, completed, active))

    commands = run_chunked_strobealign_pipeline(
        reference_path=tmp_path / "ref.fa",
        read_group_flags=[],
        r1_path=r1_path,
        r2_path=r2_path,
        output_path=output_bam,
        aligner_binary="strobealign-fake",
        samtools_binary="samtools",
        chunk_dir=chunk_dir,
        chunk_reads=100,
        parallelism=2,
        aligner_threads_per_chunk=4,
        sort_threads_per_chunk=2,
        sort_memory_per_chunk="256M",
        on_progress=_on_progress,
    )

    assert output_bam.exists()
    assert output_bam.stat().st_size > 0
    assert any(cmd.startswith("pigz -dc") for cmd in commands)
    assert any("samtools merge" in cmd for cmd in commands)

    phases = {event[0] for event in progress_events}
    assert "splitting" in phases
    assert "aligning" in phases
    assert "merging" in phases

    final_aligning = [e for e in progress_events if e[0] == "aligning"]
    last = final_aligning[-1]
    assert last[1] == last[2], f"last aligning event not fully completed: {last}"

    remaining_chunk_bams = list(chunk_dir.glob("chunk_*.coord-sorted.bam"))
    assert remaining_chunk_bams == []
    remaining_chunk_fastqs = list(chunk_dir.glob("r[12]_*.fastq.gz"))
    assert remaining_chunk_fastqs == []


@pytest.mark.skipif(shutil.which("pigz") is None, reason="pigz not installed")
@pytest.mark.skipif(shutil.which("split") is None, reason="split not installed")
@pytest.mark.skipif(shutil.which("samtools") is None, reason="samtools not installed")
def test_run_chunked_strobealign_pipeline_overlaps_split_and_align(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verifies the producer/consumer refactor — aligners start while split runs.

    Uses a fake aligner that sleeps briefly and records its start/end timestamps.
    Asserts the FIRST alignment started BEFORE the LAST chunk was written by split,
    which is the definition of overlap.
    """
    import subprocess
    import threading
    import time as _time

    input_dir = tmp_path / "input"
    input_dir.mkdir()
    chunk_dir = tmp_path / "chunks"
    output_bam = tmp_path / "merged.bam"

    # Enough reads for many small chunks so split takes measurable time
    total_reads = 4000
    r1_path, r2_path = _write_synthetic_paired_fastq(input_dir, total_reads)

    align_events_lock = threading.Lock()
    align_start_times: list[tuple[float, int]] = []
    chunk_mtimes: list[tuple[float, int]] = []

    def _fake_align(
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
        idx = int(r1_path.stem.split("_")[1].split(".")[0])
        with align_events_lock:
            align_start_times.append((_time.monotonic(), idx))
        _time.sleep(0.25)
        header_bytes = (
            b"@HD\tVN:1.6\tSO:coordinate\n"
            b"@SQ\tSN:chr1\tLN:1000\n"
            b"@RG\tID:test\tSM:test\tPL:ILLUMINA\n"
        )
        with output_path.open("wb") as bam_out:
            sam_proc = subprocess.run(
                [samtools_binary, "view", "-bS", "-"],
                input=header_bytes,
                stdout=bam_out,
                stderr=subprocess.PIPE,
            )
        assert sam_proc.returncode == 0, sam_proc.stderr.decode(errors="replace")
        return [f"fake-align chunk={idx}"]

    monkeypatch.setattr(alignment_service, "_align_single_chunk", _fake_align)
    # Make the watcher poll fast for a snappy test
    monkeypatch.setattr(alignment_service, "_CHUNK_WATCHER_POLL_SECONDS", 0.05)

    t0 = _time.monotonic()
    commands = alignment_service.run_chunked_strobealign_pipeline(
        reference_path=tmp_path / "ref.fa",
        read_group_flags=[],
        r1_path=r1_path,
        r2_path=r2_path,
        output_path=output_bam,
        aligner_binary="strobealign-fake",
        samtools_binary="samtools",
        chunk_dir=chunk_dir,
        chunk_reads=500,
        parallelism=2,
        aligner_threads_per_chunk=2,
        sort_threads_per_chunk=1,
        sort_memory_per_chunk="256M",
    )

    assert output_bam.exists() and output_bam.stat().st_size > 0
    assert any("samtools merge" in cmd for cmd in commands)

    # At least 2 aligner invocations with distinguishable start times
    assert len(align_start_times) >= 2
    first_align_start = min(t for t, _ in align_start_times)

    # We can't observe "last chunk written" after-the-fact (chunks are deleted),
    # but the strong check is: first alignment must have started within the
    # first ~half of the total wall time — i.e., not after all splits finished.
    total_elapsed = _time.monotonic() - t0
    first_align_offset = first_align_start - t0
    assert first_align_offset < total_elapsed * 0.75, (
        f"First aligner started at {first_align_offset:.3f}s but total was "
        f"{total_elapsed:.3f}s — split likely blocked before alignment (no overlap)"
    )


def test_chunk_progress_snapshot_round_trip() -> None:
    run_id = "test-run-chunk-progress"
    clear_chunk_progress(run_id)
    try:
        record_chunk_progress(
            run_id,
            SampleLane.TUMOR,
            phase="aligning",
            total=10,
            completed=3,
            active=2,
        )
        record_chunk_progress(
            run_id,
            SampleLane.NORMAL,
            phase="splitting",
            total=0,
            completed=0,
            active=0,
        )

        snapshot = get_chunk_progress_snapshot(run_id)
        assert set(snapshot.keys()) == {"tumor", "normal"}

        tumor = snapshot["tumor"]
        assert isinstance(tumor, ChunkProgressState)
        assert tumor.phase == "aligning"
        assert tumor.total_chunks == 10
        assert tumor.completed_chunks == 3
        assert tumor.active_chunks == 2

        normal = snapshot["normal"]
        assert normal.phase == "splitting"
        assert normal.total_chunks == 0
    finally:
        clear_chunk_progress(run_id)
        assert get_chunk_progress_snapshot(run_id) == {}


def test_compute_progress_components_weighting_stays_blended() -> None:
    from app.models.schemas import (
        AlignmentRunStatus,
        AlignmentRuntimePhase,
        ChunkProgressPhase,
        ChunkProgressStateResponse,
    )

    # Halfway through aligning a 100-chunk run (reference prep done, no
    # finalizing yet).
    chunk_progress = {
        SampleLane.TUMOR: ChunkProgressStateResponse(
            phase=ChunkProgressPhase.ALIGNING,
            total_chunks=50,
            completed_chunks=25,
            active_chunks=2,
        ),
        SampleLane.NORMAL: ChunkProgressStateResponse(
            phase=ChunkProgressPhase.ALIGNING,
            total_chunks=50,
            completed_chunks=25,
            active_chunks=2,
        ),
    }
    components = alignment_service.compute_progress_components(
        status=AlignmentRunStatus.RUNNING,
        runtime_phase=AlignmentRuntimePhase.ALIGNING,
        chunk_progress=chunk_progress,
        expected_total_per_lane={},
    )
    assert components["reference_prep"] == 1.0
    assert components["aligning"] == pytest.approx(0.5, abs=1e-6)
    assert components["finalizing"] == 0.0
    assert components["stats"] == 0.0

    blended = alignment_service.compute_blended_progress(components)
    # 0.05 + 0.75*0.5 + 0 + 0 = 0.425
    assert blended == pytest.approx(0.425, abs=1e-6)


def test_compute_progress_components_finalizing_partial_value() -> None:
    from app.models.schemas import (
        AlignmentRunStatus,
        AlignmentRuntimePhase,
        ChunkProgressPhase,
        ChunkProgressStateResponse,
    )

    chunk_progress = {
        SampleLane.TUMOR: ChunkProgressStateResponse(
            phase=ChunkProgressPhase.MERGING,
            total_chunks=10,
            completed_chunks=10,
            active_chunks=0,
        ),
        SampleLane.NORMAL: ChunkProgressStateResponse(
            phase=ChunkProgressPhase.MERGING,
            total_chunks=10,
            completed_chunks=10,
            active_chunks=0,
        ),
    }
    components = alignment_service.compute_progress_components(
        status=AlignmentRunStatus.RUNNING,
        runtime_phase=AlignmentRuntimePhase.FINALIZING,
        chunk_progress=chunk_progress,
        expected_total_per_lane={},
    )
    # Finalizing at 0.5 keeps the overall bar moving (0.05 + 0.75 + 0.15*0.5 + 0
    # = 0.875) instead of stalling at 0.80.
    blended = alignment_service.compute_blended_progress(components)
    assert blended == pytest.approx(0.875, abs=1e-6)


def test_compute_eta_seconds_requires_warmup() -> None:
    import time as _time

    from app.models.schemas import (
        ChunkProgressPhase,
        ChunkProgressStateResponse,
    )

    # < 60s since started → no ETA yet
    chunk_progress = {
        SampleLane.TUMOR: ChunkProgressStateResponse(
            phase=ChunkProgressPhase.ALIGNING,
            total_chunks=100,
            completed_chunks=1,
            active_chunks=1,
        ),
    }
    raw = {
        "tumor": ChunkProgressState(
            phase="aligning",
            total_chunks=100,
            completed_chunks=1,
            active_chunks=1,
            completion_times=[_time.time()],
        ),
    }
    eta = alignment_service.compute_eta_seconds(
        chunk_progress,
        raw,
        {},
        started_at_epoch=_time.time() - 10,  # only 10s ago
    )
    assert eta is None


def test_compute_eta_seconds_projects_rate() -> None:
    import time as _time

    from app.models.schemas import (
        ChunkProgressPhase,
        ChunkProgressStateResponse,
    )

    now = _time.time()
    # 5 chunks completed in the last 10 minutes, 95 remaining.
    completion_times = [now - t for t in (500, 400, 300, 200, 100)]
    chunk_progress = {
        SampleLane.TUMOR: ChunkProgressStateResponse(
            phase=ChunkProgressPhase.ALIGNING,
            total_chunks=100,
            completed_chunks=5,
            active_chunks=1,
        ),
    }
    raw = {
        "tumor": ChunkProgressState(
            phase="aligning",
            total_chunks=100,
            completed_chunks=5,
            active_chunks=1,
            completion_times=completion_times,
        ),
    }
    eta = alignment_service.compute_eta_seconds(
        chunk_progress,
        raw,
        {},
        started_at_epoch=now - 600,
    )
    # rate = 5 per 600s, remaining 95 → ~11400s ≈ 3h10m
    assert eta is not None
    assert 10_000 < eta < 14_000


def test_cancel_alignment_marks_run_cancelled(tmp_path: Path, monkeypatch) -> None:
    """cancel_alignment_run transitions a running run to CANCELLED state."""
    from app.db import init_db, session_scope
    from app.models.records import (
        IngestionBatchRecord,
        PipelineArtifactRecord,
        PipelineRunRecord,
        WorkspaceFileRecord,
        WorkspaceRecord,
    )
    from app.models.schemas import AlignmentRunStatus
    from sqlalchemy import delete

    init_db()
    with session_scope() as session:
        session.execute(delete(PipelineArtifactRecord))
        session.execute(delete(PipelineRunRecord))
        session.execute(delete(WorkspaceFileRecord))
        session.execute(delete(IngestionBatchRecord))
        session.execute(delete(WorkspaceRecord))

    try:
        from datetime import datetime, timezone
        import uuid as _uuid

        workspace_id = str(_uuid.uuid4())
        run_id = str(_uuid.uuid4())
        now = datetime.now(timezone.utc)

        with session_scope() as session:
            workspace = WorkspaceRecord(
                id=workspace_id,
                display_name="Cancel test",
                species="human",
                active_stage="alignment",
                created_at=now,
                updated_at=now,
            )
            run = PipelineRunRecord(
                id=run_id,
                workspace_id=workspace_id,
                stage_id="alignment",
                status=AlignmentRunStatus.RUNNING.value,
                progress=20,
                created_at=now,
                updated_at=now,
                started_at=now,
            )
            session.add(workspace)
            session.add(run)

        summary = alignment_service.cancel_alignment_run(workspace_id, run_id)
        assert summary.latest_run is not None
        assert summary.latest_run.status == AlignmentRunStatus.CANCELLED
        assert summary.latest_run.blocking_reason == "Stopped by user."
    finally:
        with session_scope() as session:
            session.execute(delete(PipelineArtifactRecord))
            session.execute(delete(PipelineRunRecord))
            session.execute(delete(WorkspaceFileRecord))
            session.execute(delete(IngestionBatchRecord))
            session.execute(delete(WorkspaceRecord))


def test_cancel_alignment_is_idempotent_after_completion() -> None:
    """Cancelling an already-terminal run returns current summary without error."""
    from app.db import init_db, session_scope
    from app.models.records import (
        IngestionBatchRecord,
        PipelineArtifactRecord,
        PipelineRunRecord,
        WorkspaceFileRecord,
        WorkspaceRecord,
    )
    from app.models.schemas import AlignmentRunStatus
    from sqlalchemy import delete

    init_db()
    with session_scope() as session:
        session.execute(delete(PipelineArtifactRecord))
        session.execute(delete(PipelineRunRecord))
        session.execute(delete(WorkspaceFileRecord))
        session.execute(delete(IngestionBatchRecord))
        session.execute(delete(WorkspaceRecord))

    try:
        from datetime import datetime, timezone
        import uuid as _uuid

        workspace_id = str(_uuid.uuid4())
        run_id = str(_uuid.uuid4())
        now = datetime.now(timezone.utc)

        with session_scope() as session:
            workspace = WorkspaceRecord(
                id=workspace_id,
                display_name="Idempotent cancel",
                species="human",
                active_stage="alignment",
                created_at=now,
                updated_at=now,
            )
            run = PipelineRunRecord(
                id=run_id,
                workspace_id=workspace_id,
                stage_id="alignment",
                status=AlignmentRunStatus.FAILED.value,
                progress=100,
                created_at=now,
                updated_at=now,
                started_at=now,
                completed_at=now,
                error="some earlier error",
            )
            session.add(workspace)
            session.add(run)

        # Should not raise and should preserve the FAILED status.
        summary = alignment_service.cancel_alignment_run(workspace_id, run_id)
        assert summary.latest_run is not None
        assert summary.latest_run.status == AlignmentRunStatus.FAILED
    finally:
        with session_scope() as session:
            session.execute(delete(PipelineArtifactRecord))
            session.execute(delete(PipelineRunRecord))
            session.execute(delete(WorkspaceFileRecord))
            session.execute(delete(IngestionBatchRecord))
            session.execute(delete(WorkspaceRecord))
