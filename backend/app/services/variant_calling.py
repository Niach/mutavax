"""Variant calling stage service (GATK Mutect2).

Runs Mutect2 on the aligned tumor/normal BAMs, filters the raw calls with
FilterMutectCalls, and parses the resulting VCF into rich metrics for the UI
(per-chromosome counts, filter breakdown, VAF histogram, top variants).
Artifacts (somatic VCF, Tabix index, Mutect2 stats) are persisted under the
workspace's ``variant-calling/{run_id}`` directory and exposed via
PipelineArtifactRecord rows.
"""
from __future__ import annotations

import concurrent.futures
import gzip
import json
import math
import os
import shutil
import signal
import statistics
import subprocess
import threading
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.db import session_scope
from app.runtime import get_variant_calling_run_root, resolve_app_data_path
from app.models.records import (
    PipelineArtifactRecord,
    PipelineRunRecord,
)
from app.models.schemas import (
    ChromosomeMetricsEntry,
    FilterBreakdownEntry,
    PipelineStageId,
    SampleLane,
    TopVariantEntry,
    VafHistogramBin,
    VariantCallingArtifactKind,
    VariantCallingArtifactResponse,
    VariantCallingMetricsResponse,
    VariantCallingRunResponse,
    VariantCallingRunStatus,
    VariantCallingRuntimePhase,
    VariantCallingStageStatus,
    VariantCallingStageSummaryResponse,
    VariantTypeKind,
)
from app.services.alignment import (
    AlignmentArtifactKind,
    build_alignment_stage_summary,
    get_latest_alignment_run,
    has_required_alignment_artifacts,
    resolve_reference_config,
)
from app.services.tool_preflight import (
    AccelerationMode,
    current_acceleration_mode,
)
from app.services.workspace_store import (
    get_workspace_record,
    isoformat,
    serialize_analysis_profile,
    utc_now,
)


VARIANT_CALLING_STAGE_ID = PipelineStageId.VARIANT_CALLING.value
NOT_ACTIONABLE_MESSAGE = (
    "Variant calling is visible here, but not available yet. Alignment is the current working step."
)

# VAF histogram uses 20 bins over [0, 1].
VAF_HISTOGRAM_BINS = 20
TOP_VARIANTS_LIMIT = 40
TRANSITION_PAIRS = {("A", "G"), ("G", "A"), ("C", "T"), ("T", "C")}


class VariantCallingArtifactNotFoundError(FileNotFoundError):
    pass


class VariantCallingCancelledError(Exception):
    """Raised when a variant calling run is cancelled via the cancel endpoint."""


@dataclass(frozen=True)
class VariantCallingArtifactDownload:
    filename: str
    local_path: Path
    content_type: Optional[str]


@dataclass
class VariantCallingInputs:
    workspace_id: str
    reference_fasta: Path
    reference_label: Optional[str]
    tumor_bam: Path
    normal_bam: Path
    run_dir: Path


# --------------------------------------------------------------------------- #
# Subprocess + cancel registry (mirrors alignment.py pattern)
# --------------------------------------------------------------------------- #

_subprocess_registry_lock = threading.Lock()
_active_subprocesses: dict[str, list[subprocess.Popen]] = {}
_cancelled_runs: set[str] = set()
_paused_pending_runs: set[str] = set()
_shard_progress: dict[str, tuple[int, int]] = {}
# Durable PID tracking: the in-memory Popen list is lost when the launching
# Python worker dies (e.g. uvicorn --reload), leaving Java children orphaned
# under PID 1. Each live Popen is mirrored as an empty marker file named
# ``{pid}`` inside the run's pid_dir so a fresh backend can still find and
# SIGTERM them on pause/cancel.
_run_pid_dirs: dict[str, Path] = {}


def set_run_pid_dir(run_id: str, pid_dir: Path) -> None:
    pid_dir.mkdir(parents=True, exist_ok=True)
    for entry in pid_dir.iterdir():
        try:
            pid = int(entry.name)
        except ValueError:
            continue
        cmdline = _read_proc_cmdline(pid)
        if cmdline is None or run_id not in cmdline:
            try:
                entry.unlink(missing_ok=True)
            except OSError:
                pass
    with _subprocess_registry_lock:
        _run_pid_dirs[run_id] = pid_dir


def clear_run_pid_dir(run_id: str) -> None:
    with _subprocess_registry_lock:
        _run_pid_dirs.pop(run_id, None)


def _get_run_pid_dir(run_id: str) -> Optional[Path]:
    with _subprocess_registry_lock:
        return _run_pid_dirs.get(run_id)


def _pid_marker_path(pid_dir: Path, pid: int) -> Path:
    return pid_dir / str(pid)


def _write_pid_marker(run_id: str, pid: int) -> None:
    pid_dir = _get_run_pid_dir(run_id)
    if pid_dir is None:
        return
    try:
        _pid_marker_path(pid_dir, pid).touch(exist_ok=True)
    except OSError:
        pass


def _remove_pid_marker(run_id: str, pid: int) -> None:
    pid_dir = _get_run_pid_dir(run_id)
    if pid_dir is None:
        return
    try:
        _pid_marker_path(pid_dir, pid).unlink(missing_ok=True)
    except OSError:
        pass


def _derive_pid_dir_on_disk(workspace_id: str, run_id: str) -> Path:
    """Compute the pid_dir path for a run without mkdir side effects."""
    from app.runtime import get_app_data_root

    return (
        get_app_data_root()
        / "workspaces"
        / workspace_id
        / "variant-calling"
        / run_id
        / "pids"
    )


def register_subprocess(run_id: str, proc: subprocess.Popen) -> None:
    with _subprocess_registry_lock:
        _active_subprocesses.setdefault(run_id, []).append(proc)
    _write_pid_marker(run_id, proc.pid)


def unregister_subprocess(run_id: str, proc: subprocess.Popen) -> None:
    with _subprocess_registry_lock:
        procs = _active_subprocesses.get(run_id)
        if procs:
            try:
                procs.remove(proc)
            except ValueError:
                pass
            if not procs:
                _active_subprocesses.pop(run_id, None)
    _remove_pid_marker(run_id, proc.pid)


def clear_subprocess_registry(run_id: str) -> None:
    with _subprocess_registry_lock:
        _active_subprocesses.pop(run_id, None)


def mark_run_cancelled(run_id: str) -> None:
    with _subprocess_registry_lock:
        _cancelled_runs.add(run_id)


def clear_run_cancelled(run_id: str) -> None:
    with _subprocess_registry_lock:
        _cancelled_runs.discard(run_id)


def is_run_cancelled(run_id: str) -> bool:
    with _subprocess_registry_lock:
        return run_id in _cancelled_runs


def mark_run_paused_pending(run_id: str) -> None:
    with _subprocess_registry_lock:
        _cancelled_runs.add(run_id)
        _paused_pending_runs.add(run_id)


def clear_run_paused_pending(run_id: str) -> None:
    with _subprocess_registry_lock:
        _paused_pending_runs.discard(run_id)


def is_run_paused_pending(run_id: str) -> bool:
    with _subprocess_registry_lock:
        return run_id in _paused_pending_runs


def _signal_process_group(pid: int, sig: int) -> bool:
    """Signal the whole process group led by ``pid``.

    Wrappers like ``pbrun mutectcaller`` spawn a chain of child processes that
    ignore signals sent to the head of the chain — SIGTERMing only the parent
    leaves the grandchild ``mutect`` binary burning cores until docker tears
    the container down. Because we launch with ``start_new_session=True``, the
    child is its own session leader and ``os.killpg(pid, sig)`` delivers the
    signal to every descendant in one shot. Falls back to ``os.kill`` (single
    pid) if the process already left its group or doesn't exist.
    """
    try:
        pgid = os.getpgid(pid)
    except ProcessLookupError:
        return False
    except OSError:
        pgid = pid
    try:
        os.killpg(pgid, sig)
        return True
    except ProcessLookupError:
        return False
    except OSError:
        try:
            os.kill(pid, sig)
            return True
        except OSError:
            return False


def terminate_run_subprocesses(
    run_id: str,
    *,
    grace_seconds: float = 5.0,
    pid_dir: Optional[Path] = None,
) -> int:
    """SIGTERM all registered Popens for ``run_id``, then SIGKILL survivors.

    Also scans ``pid_dir`` (or the registered pid_dir for this run) for PID
    marker files left by a dead launching worker — those are orphans reparented
    to PID 1. We validate each via ``/proc/{pid}/cmdline`` (must contain
    ``run_id``) before killing, so stale marker files from a reused PID don't
    collide with unrelated processes.
    """
    with _subprocess_registry_lock:
        procs = list(_active_subprocesses.get(run_id, []))

    terminated = 0
    for proc in procs:
        if proc.poll() is not None:
            continue
        if _signal_process_group(proc.pid, signal.SIGTERM):
            terminated += 1

    deadline = time.time() + grace_seconds
    for proc in procs:
        remaining = max(0.0, deadline - time.time())
        if proc.poll() is not None:
            continue
        try:
            proc.wait(timeout=remaining)
        except subprocess.TimeoutExpired:
            _signal_process_group(proc.pid, signal.SIGKILL)
            try:
                proc.wait(timeout=2.0)
            except Exception:
                pass
        except Exception:
            pass

    terminated += _terminate_pid_file_survivors(
        run_id,
        pid_dir=pid_dir or _get_run_pid_dir(run_id),
        grace_seconds=grace_seconds,
    )
    return terminated


def _read_proc_cmdline(pid: int) -> Optional[str]:
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as fh:
            return fh.read().decode("utf-8", errors="replace")
    except (OSError, ValueError):
        return None


def _terminate_pid_file_survivors(
    run_id: str,
    *,
    pid_dir: Optional[Path],
    grace_seconds: float,
) -> int:
    if pid_dir is None or not pid_dir.exists():
        return 0

    candidates: list[int] = []
    for entry in pid_dir.iterdir():
        try:
            pid = int(entry.name)
        except ValueError:
            continue
        cmdline = _read_proc_cmdline(pid)
        if cmdline is None:
            try:
                entry.unlink(missing_ok=True)
            except OSError:
                pass
            continue
        # Safety: only kill PIDs whose cmdline mentions this run (prevents
        # killing an unrelated process that inherited a recycled PID).
        if run_id not in cmdline:
            try:
                entry.unlink(missing_ok=True)
            except OSError:
                pass
            continue
        candidates.append(pid)

    if not candidates:
        return 0

    attempted = list(candidates)
    terminated = 0
    for pid in attempted:
        if _signal_process_group(pid, signal.SIGTERM):
            terminated += 1

    deadline = time.time() + grace_seconds
    survivors = list(attempted)
    while survivors and time.time() < deadline:
        still_alive = [pid for pid in survivors if _read_proc_cmdline(pid) is not None]
        if not still_alive:
            survivors = []
            break
        survivors = still_alive
        time.sleep(0.2)

    for pid in survivors:
        _signal_process_group(pid, signal.SIGKILL)

    # Remove markers for every PID we attempted to kill. Zombies still have a
    # readable /proc entry until their parent reaps them, so we can't rely on
    # cmdline disappearing to decide whether to unlink.
    for pid in attempted:
        try:
            _pid_marker_path(pid_dir, pid).unlink(missing_ok=True)
        except OSError:
            pass

    return terminated


def set_shard_progress(run_id: str, completed: int, total: int) -> None:
    with _subprocess_registry_lock:
        _shard_progress[run_id] = (completed, total)


def get_shard_progress(run_id: str) -> tuple[int, int]:
    with _subprocess_registry_lock:
        return _shard_progress.get(run_id, (0, 0))


def clear_shard_progress(run_id: str) -> None:
    with _subprocess_registry_lock:
        _shard_progress.pop(run_id, None)


# --------------------------------------------------------------------------- #
# Record access helpers
# --------------------------------------------------------------------------- #


def _variant_calling_run_query():
    return select(PipelineRunRecord).options(
        selectinload(PipelineRunRecord.artifacts),
        selectinload(PipelineRunRecord.workspace),
    )


def get_latest_variant_calling_run(
    session,
    workspace_id: str,
) -> Optional[PipelineRunRecord]:
    return session.scalar(
        _variant_calling_run_query()
        .where(
            PipelineRunRecord.workspace_id == workspace_id,
            PipelineRunRecord.stage_id == VARIANT_CALLING_STAGE_ID,
        )
        .order_by(PipelineRunRecord.created_at.desc())
    )


def get_variant_calling_run_record(
    session,
    workspace_id: str,
    run_id: str,
) -> PipelineRunRecord:
    run = session.scalar(
        _variant_calling_run_query().where(
            PipelineRunRecord.id == run_id,
            PipelineRunRecord.workspace_id == workspace_id,
            PipelineRunRecord.stage_id == VARIANT_CALLING_STAGE_ID,
        )
    )
    if run is None:
        raise FileNotFoundError(f"Variant calling run {run_id} not found")
    return run


def get_variant_calling_artifact_record(
    session,
    workspace_id: str,
    artifact_id: str,
) -> PipelineArtifactRecord:
    artifact = session.scalar(
        select(PipelineArtifactRecord).where(
            PipelineArtifactRecord.id == artifact_id,
            PipelineArtifactRecord.workspace_id == workspace_id,
            PipelineArtifactRecord.stage_id == VARIANT_CALLING_STAGE_ID,
        )
    )
    if artifact is None:
        raise VariantCallingArtifactNotFoundError(
            f"Variant calling artifact {artifact_id} not found"
        )
    return artifact


# --------------------------------------------------------------------------- #
# Serializers
# --------------------------------------------------------------------------- #


def _serialize_artifact(record: PipelineArtifactRecord) -> VariantCallingArtifactResponse:
    return VariantCallingArtifactResponse(
        id=record.id,
        artifact_kind=VariantCallingArtifactKind(record.artifact_kind),
        filename=record.filename,
        size_bytes=record.size_bytes,
        download_path=f"/api/workspaces/{record.workspace_id}/variant-calling/artifacts/{record.id}/download",
        local_path=record.local_path,
    )


def _parse_metrics(payload: Optional[str]) -> Optional[VariantCallingMetricsResponse]:
    if not payload:
        return None
    try:
        data = json.loads(payload)
    except (TypeError, ValueError):
        return None
    metrics = data.get("metrics") if isinstance(data, dict) else None
    if not isinstance(metrics, dict):
        return None
    try:
        return VariantCallingMetricsResponse.model_validate(metrics)
    except Exception:
        return None


def _parse_acceleration_mode(payload: Optional[str]) -> AccelerationMode:
    """Pull ``acceleration_mode`` out of ``result_payload``, default to CPU.

    A run is tagged with the mode at start time (via ``start_variant_calling_run``),
    so in-progress runs already carry the right value; completed runs keep the
    tag after ``persist_variant_calling_success`` merges in the metrics.
    """
    if payload:
        try:
            data = json.loads(payload)
        except (TypeError, ValueError):
            data = None
        if isinstance(data, dict):
            raw = data.get("acceleration_mode")
            if raw in ("gpu_parabricks", "cpu_gatk"):
                return raw  # type: ignore[return-value]
    return "cpu_gatk"


def _derive_shard_progress(record: PipelineRunRecord) -> tuple[int, int]:
    """Return (completed_shards, total_shards) for the run.

    While the worker is live we read from the in-memory registry; otherwise we
    count ``.done`` markers on disk so a paused run still reports accurate
    progress across backend restarts. We compute the path directly instead of
    calling :func:`get_variant_calling_run_root`, which would re-create the
    directory as a side effect — unwanted after a cancel wipe.
    """
    live_completed, live_total = get_shard_progress(record.id)
    if live_total > 0:
        return live_completed, live_total

    try:
        from app.runtime import get_app_data_root

        shard_dir = (
            get_app_data_root()
            / "workspaces"
            / record.workspace_id
            / "variant-calling"
            / record.id
            / "shards"
        )
    except Exception:
        return 0, 0
    if not shard_dir.exists():
        return 0, 0
    done_count = sum(1 for _ in shard_dir.glob("*.done"))
    vcf_count = sum(1 for _ in shard_dir.glob("*.vcf.gz"))
    total = max(done_count, vcf_count)
    return done_count, total


def serialize_variant_calling_run(
    record: PipelineRunRecord,
) -> VariantCallingRunResponse:
    completed_shards, total_shards = _derive_shard_progress(record)
    return VariantCallingRunResponse(
        id=record.id,
        status=VariantCallingRunStatus(record.status),
        progress=record.progress / 100,
        runtime_phase=(
            VariantCallingRuntimePhase(record.runtime_phase)
            if record.runtime_phase
            else None
        ),
        created_at=isoformat(record.created_at),
        updated_at=isoformat(record.updated_at),
        started_at=isoformat(record.started_at) if record.started_at else None,
        completed_at=isoformat(record.completed_at) if record.completed_at else None,
        blocking_reason=record.blocking_reason,
        error=record.error,
        command_log=record.command_log.splitlines() if record.command_log else [],
        metrics=_parse_metrics(record.result_payload),
        artifacts=[_serialize_artifact(artifact) for artifact in record.artifacts],
        completed_shards=completed_shards,
        total_shards=total_shards,
        acceleration_mode=_parse_acceleration_mode(record.result_payload),
    )


# --------------------------------------------------------------------------- #
# Stage summary
# --------------------------------------------------------------------------- #


def build_variant_calling_stage_summary(
    workspace,
    latest_alignment_run: Optional[PipelineRunRecord],
    latest_variant_calling_run: Optional[PipelineRunRecord],
) -> VariantCallingStageSummaryResponse:
    alignment_summary = build_alignment_stage_summary(workspace, latest_alignment_run)
    latest_response = (
        serialize_variant_calling_run(latest_variant_calling_run)
        if latest_variant_calling_run is not None
        else None
    )
    artifacts = latest_response.artifacts if latest_response else []

    if not alignment_summary.ready_for_variant_calling:
        return VariantCallingStageSummaryResponse(
            workspace_id=workspace.id,
            status=VariantCallingStageStatus.BLOCKED,
            blocking_reason=alignment_summary.blocking_reason
            or "Finish alignment before calling variants.",
            ready_for_annotation=False,
            latest_run=latest_response,
            artifacts=artifacts,
        )

    if latest_variant_calling_run is None:
        return VariantCallingStageSummaryResponse(
            workspace_id=workspace.id,
            status=VariantCallingStageStatus.SCAFFOLDED,
            blocking_reason=None,
            ready_for_annotation=False,
            latest_run=None,
            artifacts=[],
        )

    if latest_variant_calling_run.status in {
        VariantCallingRunStatus.PENDING.value,
        VariantCallingRunStatus.RUNNING.value,
    }:
        return VariantCallingStageSummaryResponse(
            workspace_id=workspace.id,
            status=VariantCallingStageStatus.RUNNING,
            blocking_reason=None,
            ready_for_annotation=False,
            latest_run=latest_response,
            artifacts=artifacts,
        )

    if latest_variant_calling_run.status == VariantCallingRunStatus.PAUSED.value:
        return VariantCallingStageSummaryResponse(
            workspace_id=workspace.id,
            status=VariantCallingStageStatus.PAUSED,
            blocking_reason=latest_variant_calling_run.blocking_reason,
            ready_for_annotation=False,
            latest_run=latest_response,
            artifacts=artifacts,
        )

    if latest_variant_calling_run.status == VariantCallingRunStatus.FAILED.value:
        return VariantCallingStageSummaryResponse(
            workspace_id=workspace.id,
            status=VariantCallingStageStatus.FAILED,
            blocking_reason=latest_variant_calling_run.blocking_reason,
            ready_for_annotation=False,
            latest_run=latest_response,
            artifacts=artifacts,
        )

    if latest_variant_calling_run.status == VariantCallingRunStatus.CANCELLED.value:
        return VariantCallingStageSummaryResponse(
            workspace_id=workspace.id,
            status=VariantCallingStageStatus.SCAFFOLDED,
            blocking_reason=None,
            ready_for_annotation=False,
            latest_run=latest_response,
            artifacts=[],
        )

    return VariantCallingStageSummaryResponse(
        workspace_id=workspace.id,
        status=VariantCallingStageStatus.COMPLETED,
        blocking_reason=None,
        ready_for_annotation=True,
        latest_run=latest_response,
        artifacts=artifacts,
    )


def load_variant_calling_stage_summary(
    workspace_id: str,
) -> VariantCallingStageSummaryResponse:
    with session_scope() as session:
        workspace = get_workspace_record(session, workspace_id)
        latest_alignment = get_latest_alignment_run(session, workspace_id)
        latest_variant = get_latest_variant_calling_run(session, workspace_id)
        return build_variant_calling_stage_summary(
            workspace, latest_alignment, latest_variant
        )


# --------------------------------------------------------------------------- #
# Run orchestration
# --------------------------------------------------------------------------- #


def create_variant_calling_run(
    workspace_id: str,
) -> VariantCallingStageSummaryResponse:
    created_run_id: Optional[str] = None
    with session_scope() as session:
        workspace = get_workspace_record(session, workspace_id)
        latest_alignment = get_latest_alignment_run(session, workspace_id)
        latest_variant = get_latest_variant_calling_run(session, workspace_id)

        if latest_variant and latest_variant.status in {
            VariantCallingRunStatus.PENDING.value,
            VariantCallingRunStatus.RUNNING.value,
        }:
            raise ValueError("Variant calling is already running for this workspace.")
        if latest_variant and latest_variant.status == VariantCallingRunStatus.PAUSED.value:
            raise ValueError(
                "A paused variant calling run exists. Resume it, or cancel it, "
                "before starting a new run."
            )

        stage_summary = build_variant_calling_stage_summary(
            workspace, latest_alignment, latest_variant
        )
        if stage_summary.status == VariantCallingStageStatus.BLOCKED:
            raise ValueError(
                stage_summary.blocking_reason or "Variant calling is blocked."
            )

        analysis_profile = serialize_analysis_profile(workspace)
        reference = resolve_reference_config(workspace.species, analysis_profile)

        timestamp = utc_now()
        run = PipelineRunRecord(
            id=str(uuid.uuid4()),
            workspace_id=workspace.id,
            stage_id=VARIANT_CALLING_STAGE_ID,
            status=VariantCallingRunStatus.PENDING.value,
            progress=0,
            qc_verdict=None,
            reference_preset=analysis_profile.reference_preset.value if analysis_profile.reference_preset else None,
            reference_override=analysis_profile.reference_override,
            reference_label=reference.label,
            reference_path=str(reference.fasta_path),
            runtime_phase=VariantCallingRuntimePhase.PREPARING_REFERENCE.value,
            command_log=None,
            result_payload=None,
            blocking_reason=None,
            error=None,
            created_at=timestamp,
            updated_at=timestamp,
            started_at=None,
            completed_at=None,
        )
        session.add(run)
        workspace.updated_at = timestamp
        session.add(workspace)
        session.flush()
        created_run_id = run.id
        summary = build_variant_calling_stage_summary(
            workspace, latest_alignment, run
        )

    if created_run_id is None:
        raise RuntimeError("Variant calling run creation did not produce an id")

    enqueue_variant_calling_run(workspace_id, created_run_id)
    return summary


def rerun_variant_calling(
    workspace_id: str,
) -> VariantCallingStageSummaryResponse:
    return create_variant_calling_run(workspace_id)


def mark_variant_calling_run_cancelled(
    workspace_id: str,
    run_id: str,
    reason: str = "Stopped by user.",
) -> None:
    with session_scope() as session:
        run = get_variant_calling_run_record(session, workspace_id, run_id)
        run.status = VariantCallingRunStatus.CANCELLED.value
        run.progress = 0
        run.runtime_phase = None
        run.blocking_reason = reason
        run.error = None
        run.updated_at = utc_now()
        run.completed_at = run.updated_at
        run.workspace.updated_at = run.updated_at
        session.add(run)
        session.add(run.workspace)


def mark_variant_calling_run_paused(
    workspace_id: str,
    run_id: str,
    reason: str = "Paused by user. Resume to continue.",
) -> None:
    with session_scope() as session:
        run = get_variant_calling_run_record(session, workspace_id, run_id)
        run.status = VariantCallingRunStatus.PAUSED.value
        run.runtime_phase = None
        run.blocking_reason = reason
        run.error = None
        run.updated_at = utc_now()
        # Do not set completed_at — a paused run is not finished.
        run.workspace.updated_at = run.updated_at
        session.add(run)
        session.add(run.workspace)


def _wipe_variant_calling_run_dir(workspace_id: str, run_id: str) -> None:
    try:
        run_dir = get_variant_calling_run_root(workspace_id, run_id)
    except Exception:
        return
    if run_dir.exists():
        shutil.rmtree(run_dir, ignore_errors=True)


def cancel_variant_calling_run(
    workspace_id: str, run_id: str
) -> VariantCallingStageSummaryResponse:
    """Cancel & discard: kill subprocesses, mark CANCELLED, wipe shards."""
    with session_scope() as session:
        run = get_variant_calling_run_record(session, workspace_id, run_id)
        if run.status not in {
            VariantCallingRunStatus.PENDING.value,
            VariantCallingRunStatus.RUNNING.value,
            VariantCallingRunStatus.PAUSED.value,
        }:
            return load_variant_calling_stage_summary(workspace_id)
        was_paused = run.status == VariantCallingRunStatus.PAUSED.value

    if was_paused:
        mark_variant_calling_run_cancelled(workspace_id, run_id)
        _wipe_variant_calling_run_dir(workspace_id, run_id)
        return load_variant_calling_stage_summary(workspace_id)

    mark_run_cancelled(run_id)
    terminate_run_subprocesses(
        run_id,
        pid_dir=_derive_pid_dir_on_disk(workspace_id, run_id),
    )
    mark_variant_calling_run_cancelled(workspace_id, run_id)
    _wipe_variant_calling_run_dir(workspace_id, run_id)
    return load_variant_calling_stage_summary(workspace_id)


def pause_variant_calling_run(
    workspace_id: str, run_id: str
) -> VariantCallingStageSummaryResponse:
    """Pause & keep progress: kill subprocesses, mark PAUSED, keep shards.

    Completed shard VCFs and ``.done`` markers stay on disk. A subsequent
    ``resume_variant_calling_run`` picks up where this left off.
    """
    with session_scope() as session:
        run = get_variant_calling_run_record(session, workspace_id, run_id)
        if run.status not in {
            VariantCallingRunStatus.PENDING.value,
            VariantCallingRunStatus.RUNNING.value,
        }:
            return load_variant_calling_stage_summary(workspace_id)

    mark_run_paused_pending(run_id)
    terminate_run_subprocesses(
        run_id,
        pid_dir=_derive_pid_dir_on_disk(workspace_id, run_id),
    )
    mark_variant_calling_run_paused(workspace_id, run_id)
    return load_variant_calling_stage_summary(workspace_id)


def resume_variant_calling_run(
    workspace_id: str, run_id: str
) -> VariantCallingStageSummaryResponse:
    """Resume a paused run: validate state, flip to PENDING, re-enqueue worker."""
    with session_scope() as session:
        run = get_variant_calling_run_record(session, workspace_id, run_id)
        if run.status != VariantCallingRunStatus.PAUSED.value:
            raise ValueError(
                f"Cannot resume a run in status {run.status!r}; "
                "only paused runs are resumable."
            )
        conflict = session.scalar(
            _variant_calling_run_query()
            .where(
                PipelineRunRecord.workspace_id == workspace_id,
                PipelineRunRecord.stage_id == VARIANT_CALLING_STAGE_ID,
                PipelineRunRecord.id != run_id,
                PipelineRunRecord.status.in_(
                    [
                        VariantCallingRunStatus.PENDING.value,
                        VariantCallingRunStatus.RUNNING.value,
                    ]
                ),
            )
            .limit(1)
        )
        if conflict is not None:
            raise ValueError(
                "Another variant calling run is already active on this workspace."
            )

        run_dir = get_variant_calling_run_root(workspace_id, run_id)
        if not run_dir.exists():
            raise ValueError(
                "Resume state is missing on disk; the paused run cannot be resumed. "
                "Use Cancel & discard to start fresh."
            )

        timestamp = utc_now()
        run.status = VariantCallingRunStatus.PENDING.value
        run.runtime_phase = VariantCallingRuntimePhase.PREPARING_REFERENCE.value
        run.blocking_reason = None
        run.error = None
        run.updated_at = timestamp
        run.completed_at = None
        run.workspace.updated_at = timestamp
        session.add(run)
        session.add(run.workspace)

    enqueue_variant_calling_run(workspace_id, run_id)
    return load_variant_calling_stage_summary(workspace_id)


def mark_variant_calling_run_failed(
    workspace_id: str,
    run_id: str,
    error_message: str,
) -> None:
    with session_scope() as session:
        run = get_variant_calling_run_record(session, workspace_id, run_id)
        run.status = VariantCallingRunStatus.FAILED.value
        run.progress = 100
        run.error = error_message
        run.blocking_reason = error_message
        run.runtime_phase = None
        run.updated_at = utc_now()
        run.completed_at = run.updated_at
        run.workspace.updated_at = run.updated_at
        session.add(run)
        session.add(run.workspace)


def enqueue_variant_calling_run(
    workspace_id: str,
    run_id: str,
) -> None:
    from app.services import background

    try:
        background.submit(run_variant_calling, workspace_id, run_id)
    except Exception as error:
        mark_variant_calling_run_failed(
            workspace_id,
            run_id,
            f"Unable to queue variant calling: {error}",
        )


def update_variant_calling_progress(
    workspace_id: str,
    run_id: str,
    progress: int,
    runtime_phase: Optional[VariantCallingRuntimePhase] = None,
) -> None:
    with session_scope() as session:
        run = get_variant_calling_run_record(session, workspace_id, run_id)
        if run.status not in {
            VariantCallingRunStatus.PENDING.value,
            VariantCallingRunStatus.RUNNING.value,
        }:
            return
        run.progress = progress
        if runtime_phase is not None:
            run.runtime_phase = runtime_phase.value
        run.updated_at = utc_now()
        run.workspace.updated_at = run.updated_at
        session.add(run)
        session.add(run.workspace)


def start_variant_calling_run(workspace_id: str, run_id: str) -> VariantCallingInputs:
    """Mark run as running, validate inputs, return the paths the worker needs."""
    with session_scope() as session:
        workspace = get_workspace_record(session, workspace_id)
        run = get_variant_calling_run_record(session, workspace_id, run_id)
        latest_alignment = get_latest_alignment_run(session, workspace_id)
        if latest_alignment is None or not has_required_alignment_artifacts(latest_alignment):
            raise RuntimeError(
                "Alignment outputs are no longer ready."
            )

        tumor_bam = _lane_bam_path(latest_alignment, SampleLane.TUMOR)
        normal_bam = _lane_bam_path(latest_alignment, SampleLane.NORMAL)
        if tumor_bam is None or normal_bam is None:
            raise RuntimeError(
                "Aligned BAM files are missing; rerun alignment first."
            )

        reference_path_str = run.reference_path
        if not reference_path_str:
            raise RuntimeError("Variant calling run is missing a reference path.")
        reference_path = resolve_app_data_path(reference_path_str)
        reference_label = run.reference_label

        run.status = VariantCallingRunStatus.RUNNING.value
        if run.progress < 5:
            run.progress = 5
        if run.runtime_phase is None:
            run.runtime_phase = VariantCallingRuntimePhase.PREPARING_REFERENCE.value
        timestamp = utc_now()
        # Preserve ``started_at`` on resume so total elapsed time stays honest.
        if run.started_at is None:
            run.started_at = timestamp
        run.updated_at = timestamp
        run.completed_at = None
        run.error = None
        run.blocking_reason = None
        # Stamp which acceleration path this attempt is using. Persisted so
        # the UI badge reflects what actually ran, even after the process
        # finishes or the environment changes.
        existing_payload: dict = {}
        if run.result_payload:
            try:
                decoded = json.loads(run.result_payload)
                if isinstance(decoded, dict):
                    existing_payload = decoded
            except (TypeError, ValueError):
                existing_payload = {}
        existing_payload["acceleration_mode"] = current_acceleration_mode()
        run.result_payload = json.dumps(existing_payload)
        workspace.updated_at = run.updated_at
        session.add(run)
        session.add(workspace)

    run_dir = get_variant_calling_run_root(workspace_id, run_id)
    return VariantCallingInputs(
        workspace_id=workspace_id,
        reference_fasta=reference_path,
        reference_label=reference_label,
        tumor_bam=tumor_bam,
        normal_bam=normal_bam,
        run_dir=run_dir,
    )


def _lane_bam_path(run: PipelineRunRecord, lane: SampleLane) -> Optional[Path]:
    for artifact in run.artifacts:
        if (
            artifact.sample_lane == lane.value
            and artifact.artifact_kind == AlignmentArtifactKind.BAM.value
        ):
            candidate = resolve_app_data_path(artifact.local_path or artifact.storage_key)
            if candidate.exists():
                return candidate
    return None


# --------------------------------------------------------------------------- #
# Mutect2 orchestration
# --------------------------------------------------------------------------- #


def _gatk_binary() -> str:
    return os.getenv("GATK_BINARY", "gatk")


def _samtools_binary() -> str:
    return os.getenv("SAMTOOLS_BINARY", "samtools")


def _pbrun_binary() -> str:
    return os.getenv("PARABRICKS_BINARY", "pbrun")


def _run_subprocess(
    command: list[str],
    *,
    cwd: Optional[Path] = None,
    run_id: Optional[str] = None,
) -> subprocess.CompletedProcess:
    """Run a subprocess while tracking it for cancellation.

    If ``run_id`` is provided, the process is registered in the cancel
    registry and polled for cancel/pause signals. A cancelled run raises
    :class:`VariantCallingCancelledError`; a non-zero exit raises
    :class:`subprocess.CalledProcessError` like ``subprocess.run(check=True)``.
    """
    if run_id is None:
        return subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            cwd=cwd,
        )

    proc = subprocess.Popen(
        command,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        # Put the child in its own session so we can later SIGTERM the whole
        # process group. Critical for wrappers like ``pbrun`` that spawn
        # long-running grandchildren (the actual ``mutect`` binary) which
        # don't receive signals sent only to the head of the chain.
        start_new_session=True,
    )
    register_subprocess(run_id, proc)
    try:
        while True:
            if is_run_cancelled(run_id) and proc.poll() is None:
                _signal_process_group(proc.pid, signal.SIGTERM)
                try:
                    proc.wait(timeout=5.0)
                except subprocess.TimeoutExpired:
                    _signal_process_group(proc.pid, signal.SIGKILL)
                    try:
                        proc.wait(timeout=2.0)
                    except Exception:
                        pass
                stdout, stderr = proc.communicate()
                raise VariantCallingCancelledError("Variant calling run was cancelled.")
            try:
                stdout, stderr = proc.communicate(timeout=1.0)
                break
            except subprocess.TimeoutExpired:
                continue
        returncode = proc.returncode
        if returncode != 0:
            if is_run_cancelled(run_id):
                raise VariantCallingCancelledError("Variant calling run was cancelled.")
            raise subprocess.CalledProcessError(returncode, command, stdout, stderr)
        return subprocess.CompletedProcess(command, returncode, stdout, stderr)
    finally:
        unregister_subprocess(run_id, proc)


# --- contig selection ----------------------------------------------------- #


def _is_primary_contig(name: str) -> bool:
    """Return True for primary assembly contigs (skip alts, decoys, patches).

    Works for GRCh38 (``chr*_alt``, ``chr*_random``, ``HLA-*``, ``chrUn_*``),
    CanFam4 (``chrUn_*``, ``chrM_*``), and felCat9 (``AANG*``, ``Un_*``).
    """
    lower = name.lower()
    bad_substrings = (
        "_random",
        "_alt",
        "_decoy",
        "_fix",
        "_hap",
        "chrun_",
        "un_",
        "hla-",
        "unplaced",
        "unassigned",
        "decoy",
        "ebv",
        "pseudo",
    )
    return not any(sub in lower for sub in bad_substrings)


def _select_primary_contigs(reference_path: Path) -> list[tuple[str, int]]:
    """Read ``{ref}.fai`` and return ``[(contig_name, length)]`` for primary contigs."""
    fai_path = reference_path.with_name(reference_path.name + ".fai")
    contigs: list[tuple[str, int]] = []
    if not fai_path.exists():
        return contigs
    with fai_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            parts = line.rstrip("\n").split("\t")
            if len(parts) < 2:
                continue
            name = parts[0]
            try:
                length = int(parts[1])
            except ValueError:
                continue
            if not _is_primary_contig(name):
                continue
            contigs.append((name, length))
    return contigs


def _default_shard_concurrency(total_shards: int) -> int:
    """Pick a reasonable number of shards to run in parallel.

    Each Mutect2 shard uses ~2 pair-hmm threads, so budget cores / 2.
    Capped at 8 to avoid saturating I/O and memory on laptops.
    """
    env_override = os.getenv("CANCERSTUDIO_VC_SHARD_CONCURRENCY")
    if env_override:
        try:
            value = int(env_override)
            if value > 0:
                return max(1, min(total_shards, value))
        except ValueError:
            pass
    cores = os.cpu_count() or 4
    return max(1, min(total_shards, cores // 2, 8))


def _shard_pair_hmm_threads() -> int:
    env_override = os.getenv("CANCERSTUDIO_VC_PAIR_HMM_THREADS")
    if env_override:
        try:
            value = int(env_override)
            if value > 0:
                return value
        except ValueError:
            pass
    return 2


def ensure_reference_companions(reference_path: Path) -> list[str]:
    """Guarantee the reference has ``.fai`` and ``.dict`` sidecars required by GATK.

    Returns the list of commands that were actually executed so they can be
    recorded in the run's command log.
    """
    commands: list[str] = []

    fai_path = reference_path.with_name(reference_path.name + ".fai")
    if not fai_path.exists():
        cmd = [_samtools_binary(), "faidx", str(reference_path)]
        _run_subprocess(cmd)
        commands.append(" ".join(cmd))

    dict_path = reference_path.with_suffix(".dict")
    if not dict_path.exists():
        cmd = [
            _gatk_binary(),
            "CreateSequenceDictionary",
            "-R",
            str(reference_path),
            "-O",
            str(dict_path),
        ]
        _run_subprocess(cmd)
        commands.append(" ".join(cmd))

    return commands


def read_bam_sample_name(bam_path: Path) -> Optional[str]:
    """Extract the ``SM`` tag from the BAM header's first @RG line.

    Mutect2 needs the sample name present inside the BAM, not the file name.
    Returns ``None`` if no ``@RG`` is present.
    """
    result = _run_subprocess([_samtools_binary(), "view", "-H", str(bam_path)])
    for line in result.stdout.splitlines():
        if not line.startswith("@RG"):
            continue
        for field in line.split("\t")[1:]:
            if field.startswith("SM:"):
                return field[3:]
    return None


def ensure_bam_index(bam_path: Path) -> Optional[str]:
    bai_candidate_a = bam_path.with_suffix(bam_path.suffix + ".bai")
    bai_candidate_b = bam_path.with_suffix(".bai")
    if bai_candidate_a.exists() or bai_candidate_b.exists():
        return None
    cmd = [_samtools_binary(), "index", str(bam_path)]
    _run_subprocess(cmd)
    return " ".join(cmd)


def _shard_contig_slug(contig: str) -> str:
    """Filesystem-safe slug for a contig name (strip unusual chars)."""
    return "".join(c if c.isalnum() or c in "_-." else "_" for c in contig)


def run_mutect2_pipeline(
    inputs: VariantCallingInputs,
    *,
    run_id: str,
    on_progress: callable,  # type: ignore[valid-type]
    on_shard_progress: callable,  # type: ignore[valid-type]
    command_log: list[str],
) -> tuple[Path, Path, Path, Optional[str], Optional[str]]:
    """Scatter Mutect2 per primary contig, gather, filter.

    Returns paths to the filtered VCF, its Tabix index, the merged Mutect2
    stats file, and the resolved tumor/normal sample names.

    Resume: shards with an existing ``{contig}.done`` marker are skipped, so
    a paused run picks up where it left off on resume.
    """
    reference = inputs.reference_fasta
    run_dir = inputs.run_dir
    run_dir.mkdir(parents=True, exist_ok=True)

    on_progress(8, VariantCallingRuntimePhase.PREPARING_REFERENCE)
    command_log.extend(ensure_reference_companions(reference))

    bai_tumor = ensure_bam_index(inputs.tumor_bam)
    if bai_tumor:
        command_log.append(bai_tumor)
    bai_normal = ensure_bam_index(inputs.normal_bam)
    if bai_normal:
        command_log.append(bai_normal)

    tumor_sample = read_bam_sample_name(inputs.tumor_bam)
    normal_sample = read_bam_sample_name(inputs.normal_bam)

    contigs = _select_primary_contigs(reference)
    if not contigs:
        raise RuntimeError(
            "Could not find any primary contigs in the reference .fai; "
            "variant calling cannot proceed."
        )

    shard_dir = run_dir / "shards"
    shard_dir.mkdir(parents=True, exist_ok=True)

    pair_hmm_threads = _shard_pair_hmm_threads()
    concurrency = _default_shard_concurrency(len(contigs))

    # Build shard plan: (contig, vcf_path, stats_path, done_marker).
    @dataclass
    class ShardPlan:
        contig: str
        vcf: Path
        stats: Path
        done: Path

    plans: list[ShardPlan] = []
    for contig, _length in contigs:
        slug = _shard_contig_slug(contig)
        plans.append(
            ShardPlan(
                contig=contig,
                vcf=shard_dir / f"{slug}.vcf.gz",
                stats=shard_dir / f"{slug}.vcf.gz.stats",
                done=shard_dir / f"{slug}.done",
            )
        )

    total = len(plans)
    completed_initially = sum(1 for p in plans if p.done.exists())
    on_shard_progress(completed_initially, total)
    on_progress(
        _shard_progress_to_overall(completed_initially, total),
        VariantCallingRuntimePhase.CALLING,
    )

    remaining = [p for p in plans if not p.done.exists()]

    if is_run_cancelled(run_id):
        raise VariantCallingCancelledError("Variant calling run was cancelled.")

    completed_counter = {"value": completed_initially}
    completed_lock = threading.Lock()

    def run_shard(plan: ShardPlan) -> None:
        if is_run_cancelled(run_id):
            raise VariantCallingCancelledError("Variant calling run was cancelled.")
        # Clean up partial shard files left over from a prior interrupted run.
        for stale in (plan.vcf, plan.stats, plan.vcf.with_suffix(plan.vcf.suffix + ".tbi")):
            try:
                if stale.exists():
                    stale.unlink()
            except OSError:
                pass
        cmd: list[str] = [
            _gatk_binary(),
            "Mutect2",
            "-R",
            str(reference),
            "-I",
            str(inputs.tumor_bam),
            "-I",
            str(inputs.normal_bam),
        ]
        if normal_sample:
            cmd.extend(["-normal", normal_sample])
        cmd.extend(
            [
                "-L",
                plan.contig,
                "--native-pair-hmm-threads",
                str(pair_hmm_threads),
                "-O",
                str(plan.vcf),
            ]
        )
        _run_subprocess(cmd, run_id=run_id)
        plan.done.touch()

    if remaining:
        command_log.append(
            f"# scatter Mutect2 over {len(remaining)} contigs "
            f"(concurrency={concurrency}, pair-hmm-threads={pair_hmm_threads})"
        )
        # Record a single representative command so users can see the shape.
        sample_plan = remaining[0]
        sample_cmd = [
            _gatk_binary(),
            "Mutect2",
            "-R",
            str(reference),
            "-I",
            str(inputs.tumor_bam),
            "-I",
            str(inputs.normal_bam),
        ]
        if normal_sample:
            sample_cmd.extend(["-normal", normal_sample])
        sample_cmd.extend(
            [
                "-L",
                "<contig>",
                "--native-pair-hmm-threads",
                str(pair_hmm_threads),
                "-O",
                "shards/<contig>.vcf.gz",
            ]
        )
        command_log.append(" ".join(sample_cmd))

        with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as pool:
            futures = {pool.submit(run_shard, plan): plan for plan in remaining}
            try:
                for future in concurrent.futures.as_completed(futures):
                    future.result()
                    with completed_lock:
                        completed_counter["value"] += 1
                        done_now = completed_counter["value"]
                    on_shard_progress(done_now, total)
                    on_progress(
                        _shard_progress_to_overall(done_now, total),
                        VariantCallingRuntimePhase.CALLING,
                    )
            except (VariantCallingCancelledError, subprocess.CalledProcessError):
                for fut in futures:
                    fut.cancel()
                raise

    if is_run_cancelled(run_id):
        raise VariantCallingCancelledError("Variant calling run was cancelled.")

    raw_vcf = run_dir / "somatic.raw.vcf.gz"
    mutect_stats = run_dir / "somatic.raw.vcf.gz.stats"
    filtered_vcf = run_dir / "somatic.filtered.vcf.gz"

    on_progress(68, VariantCallingRuntimePhase.FILTERING)

    gather_cmd: list[str] = [_gatk_binary(), "GatherVcfs"]
    for plan in plans:
        gather_cmd.extend(["-I", str(plan.vcf)])
    gather_cmd.extend(["-O", str(raw_vcf)])
    command_log.append(" ".join(gather_cmd))
    _run_subprocess(gather_cmd, run_id=run_id)

    index_cmd = [_gatk_binary(), "IndexFeatureFile", "-I", str(raw_vcf)]
    command_log.append(" ".join(index_cmd))
    _run_subprocess(index_cmd, run_id=run_id)

    merge_stats_cmd: list[str] = [_gatk_binary(), "MergeMutectStats"]
    for plan in plans:
        merge_stats_cmd.extend(["-stats", str(plan.stats)])
    merge_stats_cmd.extend(["-O", str(mutect_stats)])
    command_log.append(" ".join(merge_stats_cmd))
    _run_subprocess(merge_stats_cmd, run_id=run_id)

    on_progress(75, VariantCallingRuntimePhase.FILTERING)
    filter_cmd = [
        _gatk_binary(),
        "FilterMutectCalls",
        "-R",
        str(reference),
        "-V",
        str(raw_vcf),
        "-O",
        str(filtered_vcf),
    ]
    command_log.append(" ".join(filter_cmd))
    _run_subprocess(filter_cmd, run_id=run_id)

    on_progress(85, VariantCallingRuntimePhase.FINALIZING)
    return (
        filtered_vcf,
        filtered_vcf.with_suffix(filtered_vcf.suffix + ".tbi"),
        mutect_stats,
        tumor_sample,
        normal_sample,
    )


def _shard_progress_to_overall(completed: int, total: int) -> int:
    """Map shard completion to the 15–65% band of the overall progress bar."""
    if total <= 0:
        return 15
    fraction = completed / total
    return int(round(15 + 50 * fraction))


# --------------------------------------------------------------------------- #
# Parabricks GPU orchestration
# --------------------------------------------------------------------------- #


def run_parabricks_pipeline(
    inputs: VariantCallingInputs,
    *,
    run_id: str,
    on_progress: callable,  # type: ignore[valid-type]
    command_log: list[str],
) -> tuple[Path, Path, Path, Optional[str], Optional[str]]:
    """Call Mutect2 on GPU via ``pbrun mutectcaller``, then FilterMutectCalls.

    Single whole-genome invocation — Parabricks' natural mode. No per-contig
    resume (the CPU path keeps that capability). Returns the same 5-tuple
    ``run_mutect2_pipeline`` does so the caller is agnostic to the path.
    """
    reference = inputs.reference_fasta
    run_dir = inputs.run_dir
    run_dir.mkdir(parents=True, exist_ok=True)

    on_progress(8, VariantCallingRuntimePhase.PREPARING_REFERENCE)
    command_log.extend(ensure_reference_companions(reference))

    bai_tumor = ensure_bam_index(inputs.tumor_bam)
    if bai_tumor:
        command_log.append(bai_tumor)
    bai_normal = ensure_bam_index(inputs.normal_bam)
    if bai_normal:
        command_log.append(bai_normal)

    tumor_sample = read_bam_sample_name(inputs.tumor_bam)
    normal_sample = read_bam_sample_name(inputs.normal_bam)
    if not tumor_sample or not normal_sample:
        raise RuntimeError(
            "Parabricks mutectcaller requires @RG SM tags on both BAMs; "
            "rerun alignment to regenerate read groups."
        )

    raw_vcf = run_dir / "somatic.raw.vcf.gz"
    mutect_stats = run_dir / "somatic.raw.vcf.gz.stats"
    filtered_vcf = run_dir / "somatic.filtered.vcf.gz"

    # Clean any stale raw output from a prior run — Parabricks is single-shot
    # and we don't trust partial VCFs.
    for stale in (raw_vcf, mutect_stats, raw_vcf.with_suffix(raw_vcf.suffix + ".tbi")):
        try:
            if stale.exists():
                stale.unlink()
        except OSError:
            pass

    on_progress(15, VariantCallingRuntimePhase.CALLING)
    pb_cmd = [
        _pbrun_binary(),
        "mutectcaller",
        "--ref",
        str(reference),
        "--in-tumor-bam",
        str(inputs.tumor_bam),
        "--tumor-name",
        tumor_sample,
        "--in-normal-bam",
        str(inputs.normal_bam),
        "--normal-name",
        normal_sample,
        "--out-vcf",
        str(raw_vcf),
    ]
    command_log.append(" ".join(pb_cmd))

    # Parabricks is single-shot with no stdout progress hook, so we poll the
    # growing raw VCF size as a proxy. The mapping is logarithmic and clamped
    # into the 15..64 band that the UI reserves for CALLING.
    progress_stop = threading.Event()

    def _poll_parabricks_progress() -> None:
        # Calibrated for human WGS: raw VCF finishes around 80-200 MB, so
        # log-scale against a 200 MB ceiling keeps the bar moving visibly
        # through the first ~30 min and approaches 64% near completion.
        ceiling_bytes = 200_000_000
        ceiling_log = math.log(ceiling_bytes + 1.0)
        last_emitted = 15
        while not progress_stop.is_set():
            try:
                size = raw_vcf.stat().st_size if raw_vcf.exists() else 0
            except OSError:
                size = 0
            if size > 0:
                ratio = min(1.0, math.log(size + 1.0) / ceiling_log)
                mapped = int(15 + 49 * ratio)
                if mapped > last_emitted:
                    last_emitted = mapped
                    try:
                        on_progress(mapped, VariantCallingRuntimePhase.CALLING)
                    except Exception:
                        pass
            progress_stop.wait(3.0)

    progress_thread = threading.Thread(
        target=_poll_parabricks_progress, daemon=True
    )
    progress_thread.start()
    try:
        _run_subprocess(pb_cmd, run_id=run_id)
    finally:
        progress_stop.set()
        progress_thread.join(timeout=5.0)

    if is_run_cancelled(run_id):
        raise VariantCallingCancelledError("Variant calling run was cancelled.")

    on_progress(68, VariantCallingRuntimePhase.FILTERING)
    filter_cmd = [
        _gatk_binary(),
        "FilterMutectCalls",
        "-R",
        str(reference),
        "-V",
        str(raw_vcf),
        "-O",
        str(filtered_vcf),
    ]
    command_log.append(" ".join(filter_cmd))
    _run_subprocess(filter_cmd, run_id=run_id)

    on_progress(85, VariantCallingRuntimePhase.FINALIZING)
    return (
        filtered_vcf,
        filtered_vcf.with_suffix(filtered_vcf.suffix + ".tbi"),
        mutect_stats,
        tumor_sample,
        normal_sample,
    )


# --------------------------------------------------------------------------- #
# VCF parsing & metrics
# --------------------------------------------------------------------------- #


@dataclass
class ParsedVariant:
    chromosome: str
    position: int
    ref: str
    alt: str
    filter_value: str
    is_pass: bool
    variant_type: VariantTypeKind
    tumor_vaf: Optional[float]
    tumor_depth: Optional[int]
    normal_depth: Optional[int]


def _classify_variant(ref: str, alt: str) -> VariantTypeKind:
    if len(ref) == 1 and len(alt) == 1:
        return VariantTypeKind.SNV
    if len(ref) == len(alt) and len(ref) > 1:
        return VariantTypeKind.MNV
    if len(ref) < len(alt):
        return VariantTypeKind.INSERTION
    return VariantTypeKind.DELETION


def _open_vcf(vcf_path: Path):
    if vcf_path.suffix == ".gz":
        return gzip.open(vcf_path, "rt", encoding="utf-8")
    return vcf_path.open("r", encoding="utf-8")


def _chromosome_lengths_from_fai(reference_path: Path) -> dict[str, int]:
    """Read ``{ref}.fai`` and return a mapping of contig → length.

    A karyogram visualization needs these up-front; we read them from the
    sidecar index the backend ensured exists.
    """
    lengths: dict[str, int] = {}
    fai_path = reference_path.with_name(reference_path.name + ".fai")
    try:
        with fai_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                parts = line.rstrip("\n").split("\t")
                if len(parts) >= 2:
                    try:
                        lengths[parts[0]] = int(parts[1])
                    except ValueError:
                        continue
    except OSError:
        return {}
    return lengths


def _parse_sample_columns(format_field: str, sample_fields: list[str]) -> list[dict[str, str]]:
    keys = format_field.split(":")
    parsed: list[dict[str, str]] = []
    for sample in sample_fields:
        values = sample.split(":")
        parsed.append({key: values[i] if i < len(values) else "" for i, key in enumerate(keys)})
    return parsed


def _compute_vaf(ad_field: str) -> Optional[float]:
    if not ad_field or ad_field == "." or "," not in ad_field:
        return None
    tokens = ad_field.split(",")
    try:
        values = [int(t) for t in tokens if t and t != "."]
    except ValueError:
        return None
    if len(values) < 2:
        return None
    total = sum(values)
    if total <= 0:
        return None
    alt_support = sum(values[1:])
    return alt_support / total


def _compute_depth(dp_field: str, ad_field: str) -> Optional[int]:
    if dp_field and dp_field != ".":
        try:
            return int(dp_field)
        except ValueError:
            pass
    if ad_field and "," in ad_field:
        try:
            return sum(int(t) for t in ad_field.split(",") if t and t != ".")
        except ValueError:
            return None
    return None


def _iter_vcf_records(vcf_path: Path, tumor_sample: Optional[str], normal_sample: Optional[str]) -> Iterable[ParsedVariant]:
    with _open_vcf(vcf_path) as handle:
        sample_names: list[str] = []
        for line in handle:
            if line.startswith("##"):
                continue
            if line.startswith("#CHROM"):
                header_cols = line.rstrip("\n").split("\t")
                sample_names = header_cols[9:]
                continue
            if not line.strip():
                continue
            cols = line.rstrip("\n").split("\t")
            if len(cols) < 8:
                continue
            chrom = cols[0]
            try:
                pos = int(cols[1])
            except ValueError:
                continue
            ref = cols[3]
            alt_field = cols[4]
            filter_value = cols[6] or "."

            format_field = cols[8] if len(cols) > 8 else ""
            sample_fields = cols[9:] if len(cols) > 9 else []
            parsed_samples: list[dict[str, str]] = []
            if format_field and sample_fields:
                parsed_samples = _parse_sample_columns(format_field, sample_fields)

            tumor_idx = normal_idx = None
            if tumor_sample and tumor_sample in sample_names:
                tumor_idx = sample_names.index(tumor_sample)
            if normal_sample and normal_sample in sample_names:
                normal_idx = sample_names.index(normal_sample)
            # Fall back to heuristic: first sample = tumor, second = normal,
            # unless only one sample is present.
            if tumor_idx is None and parsed_samples:
                tumor_idx = 0
            if normal_idx is None and len(parsed_samples) > 1:
                normal_idx = 1 if (tumor_idx != 1) else 0

            tumor_sample_data = (
                parsed_samples[tumor_idx]
                if tumor_idx is not None and tumor_idx < len(parsed_samples)
                else None
            )
            normal_sample_data = (
                parsed_samples[normal_idx]
                if normal_idx is not None and normal_idx < len(parsed_samples)
                else None
            )

            tumor_vaf = None
            tumor_depth = None
            if tumor_sample_data:
                if "AF" in tumor_sample_data and tumor_sample_data["AF"] and tumor_sample_data["AF"] != ".":
                    try:
                        tumor_vaf = float(tumor_sample_data["AF"].split(",")[0])
                    except ValueError:
                        tumor_vaf = None
                if tumor_vaf is None:
                    tumor_vaf = _compute_vaf(tumor_sample_data.get("AD", ""))
                tumor_depth = _compute_depth(
                    tumor_sample_data.get("DP", ""),
                    tumor_sample_data.get("AD", ""),
                )

            normal_depth = None
            if normal_sample_data:
                normal_depth = _compute_depth(
                    normal_sample_data.get("DP", ""),
                    normal_sample_data.get("AD", ""),
                )

            is_pass = filter_value in {"PASS", "."}

            for alt_single in alt_field.split(","):
                if alt_single in ("", "."):
                    continue
                yield ParsedVariant(
                    chromosome=chrom,
                    position=pos,
                    ref=ref.upper(),
                    alt=alt_single.upper(),
                    filter_value=filter_value,
                    is_pass=is_pass,
                    variant_type=_classify_variant(ref, alt_single),
                    tumor_vaf=tumor_vaf,
                    tumor_depth=tumor_depth,
                    normal_depth=normal_depth,
                )


def compute_variant_metrics(
    vcf_path: Path,
    reference_path: Path,
    *,
    tumor_sample: Optional[str],
    normal_sample: Optional[str],
    reference_label: Optional[str],
) -> VariantCallingMetricsResponse:
    per_chrom_counts: dict[str, dict[str, int]] = defaultdict(
        lambda: {"total": 0, "pass": 0, "snv": 0, "indel": 0}
    )
    filter_counts: dict[str, int] = defaultdict(int)
    vaf_values: list[float] = []
    tumor_depths: list[int] = []
    normal_depths: list[int] = []
    top_candidates: list[ParsedVariant] = []

    total = snv = indel = insertions = deletions = mnv = pass_count = 0
    pass_snv = pass_indel = transitions = transversions = 0

    for variant in _iter_vcf_records(vcf_path, tumor_sample, normal_sample):
        total += 1
        chrom_bucket = per_chrom_counts[variant.chromosome]
        chrom_bucket["total"] += 1

        if variant.variant_type == VariantTypeKind.SNV:
            snv += 1
            chrom_bucket["snv"] += 1
            pair = (variant.ref, variant.alt)
            if pair in TRANSITION_PAIRS:
                transitions += 1
            elif variant.ref in {"A", "C", "G", "T"} and variant.alt in {"A", "C", "G", "T"}:
                transversions += 1
        else:
            indel += 1
            chrom_bucket["indel"] += 1
            if variant.variant_type == VariantTypeKind.INSERTION:
                insertions += 1
            elif variant.variant_type == VariantTypeKind.DELETION:
                deletions += 1
            else:
                mnv += 1

        if variant.is_pass:
            pass_count += 1
            chrom_bucket["pass"] += 1
            if variant.variant_type == VariantTypeKind.SNV:
                pass_snv += 1
            else:
                pass_indel += 1

        filter_counts[variant.filter_value] += 1

        if variant.tumor_vaf is not None:
            vaf_values.append(variant.tumor_vaf)
        if variant.tumor_depth is not None:
            tumor_depths.append(variant.tumor_depth)
        if variant.normal_depth is not None:
            normal_depths.append(variant.normal_depth)

        if variant.is_pass:
            top_candidates.append(variant)

    chrom_lengths = _chromosome_lengths_from_fai(reference_path)
    per_chromosome = [
        ChromosomeMetricsEntry(
            chromosome=chrom,
            length=chrom_lengths.get(chrom, 0),
            total=bucket["total"],
            pass_count=bucket["pass"],
            snv_count=bucket["snv"],
            indel_count=bucket["indel"],
        )
        for chrom, bucket in per_chrom_counts.items()
    ]
    per_chromosome.sort(key=lambda entry: _chromosome_sort_key(entry.chromosome))

    filter_breakdown = [
        FilterBreakdownEntry(
            name=name,
            count=count,
            is_pass=name in {"PASS", "."},
        )
        for name, count in sorted(filter_counts.items(), key=lambda item: (-item[1], item[0]))
    ]

    # VAF histogram: 20 bins over [0, 1].
    histogram = []
    if vaf_values:
        bin_width = 1.0 / VAF_HISTOGRAM_BINS
        for i in range(VAF_HISTOGRAM_BINS):
            start = i * bin_width
            end = start + bin_width
            if i == VAF_HISTOGRAM_BINS - 1:
                count = sum(1 for v in vaf_values if v >= start and v <= end + 1e-9)
            else:
                count = sum(1 for v in vaf_values if v >= start and v < end)
            histogram.append(
                VafHistogramBin(bin_start=round(start, 4), bin_end=round(end, 4), count=count)
            )

    top_candidates.sort(
        key=lambda v: (v.tumor_vaf if v.tumor_vaf is not None else -1.0),
        reverse=True,
    )
    top_variants = [
        TopVariantEntry(
            chromosome=v.chromosome,
            position=v.position,
            ref=v.ref,
            alt=v.alt,
            variant_type=v.variant_type,
            filter=v.filter_value,
            is_pass=v.is_pass,
            tumor_vaf=v.tumor_vaf,
            tumor_depth=v.tumor_depth,
            normal_depth=v.normal_depth,
        )
        for v in top_candidates[:TOP_VARIANTS_LIMIT]
    ]

    ti_tv = (transitions / transversions) if transversions > 0 else None

    return VariantCallingMetricsResponse(
        total_variants=total,
        snv_count=snv,
        indel_count=indel,
        insertion_count=insertions,
        deletion_count=deletions,
        mnv_count=mnv,
        pass_count=pass_count,
        pass_snv_count=pass_snv,
        pass_indel_count=pass_indel,
        ti_tv_ratio=round(ti_tv, 3) if ti_tv is not None else None,
        transitions=transitions,
        transversions=transversions,
        mean_vaf=round(statistics.fmean(vaf_values), 4) if vaf_values else None,
        median_vaf=round(statistics.median(vaf_values), 4) if vaf_values else None,
        tumor_mean_depth=round(statistics.fmean(tumor_depths), 1) if tumor_depths else None,
        normal_mean_depth=round(statistics.fmean(normal_depths), 1) if normal_depths else None,
        tumor_sample=tumor_sample,
        normal_sample=normal_sample,
        reference_label=reference_label,
        per_chromosome=per_chromosome,
        filter_breakdown=filter_breakdown,
        vaf_histogram=histogram,
        top_variants=top_variants,
    )


def _chromosome_sort_key(chromosome: str) -> tuple[int, int, str]:
    """Sort contigs the way karyogram viewers expect: 1…22, X, Y, MT, then others alphabetical."""
    stripped = chromosome[3:] if chromosome.lower().startswith("chr") else chromosome
    if stripped.isdigit():
        return (0, int(stripped), chromosome)
    lowered = stripped.lower()
    special_order = {"x": 100, "y": 101, "m": 102, "mt": 102}
    if lowered in special_order:
        return (1, special_order[lowered], chromosome)
    return (2, 0, chromosome)


# --------------------------------------------------------------------------- #
# Persistence
# --------------------------------------------------------------------------- #


def _artifact_content_type(kind: VariantCallingArtifactKind) -> str:
    if kind == VariantCallingArtifactKind.STATS:
        return "text/plain"
    return "application/octet-stream"


def persist_variant_calling_success(
    workspace_id: str,
    run_id: str,
    *,
    filtered_vcf: Path,
    tbi_path: Path,
    mutect_stats: Path,
    metrics: VariantCallingMetricsResponse,
    command_log: list[str],
) -> None:
    artifacts: list[PipelineArtifactRecord] = []
    timestamp = utc_now()

    def _record(path: Path, kind: VariantCallingArtifactKind) -> None:
        if not path.exists():
            return
        artifacts.append(
            PipelineArtifactRecord(
                id=str(uuid.uuid4()),
                run_id=run_id,
                workspace_id=workspace_id,
                stage_id=VARIANT_CALLING_STAGE_ID,
                artifact_kind=kind.value,
                sample_lane=None,
                filename=path.name,
                storage_key=str(path),
                local_path=str(path),
                content_type=_artifact_content_type(kind),
                size_bytes=path.stat().st_size,
                created_at=timestamp,
            )
        )

    _record(filtered_vcf, VariantCallingArtifactKind.VCF)
    _record(tbi_path, VariantCallingArtifactKind.VCF_INDEX)
    _record(mutect_stats, VariantCallingArtifactKind.STATS)

    command_log_text = "\n".join(command_log)

    with session_scope() as session:
        run = get_variant_calling_run_record(session, workspace_id, run_id)
        for artifact in artifacts:
            session.add(artifact)
            run.artifacts.append(artifact)
        run.status = VariantCallingRunStatus.COMPLETED.value
        run.progress = 100
        run.runtime_phase = None
        # Preserve the acceleration_mode stamped at start time.
        mode = _parse_acceleration_mode(run.result_payload)
        run.result_payload = json.dumps({
            "acceleration_mode": mode,
            "metrics": metrics.model_dump(mode="json"),
        })
        run.command_log = command_log_text
        run.error = None
        run.blocking_reason = None
        run.updated_at = utc_now()
        run.completed_at = run.updated_at
        run.workspace.updated_at = run.updated_at
        session.add(run)
        session.add(run.workspace)


# --------------------------------------------------------------------------- #
# Worker entry point
# --------------------------------------------------------------------------- #


def run_variant_calling(
    workspace_id: str,
    run_id: str,
) -> None:
    command_log: list[str] = []
    clear_run_cancelled(run_id)
    clear_run_paused_pending(run_id)
    set_run_pid_dir(run_id, _derive_pid_dir_on_disk(workspace_id, run_id))
    try:
        inputs = start_variant_calling_run(workspace_id, run_id)

        def progress_cb(
            progress: int, phase: Optional[VariantCallingRuntimePhase] = None
        ) -> None:
            update_variant_calling_progress(workspace_id, run_id, progress, phase)

        def shard_progress_cb(completed: int, total: int) -> None:
            set_shard_progress(run_id, completed, total)

        if current_acceleration_mode() == "gpu_parabricks":
            # Single-shot whole-genome call on GPU. No per-contig resume;
            # cancel discards the raw VCF and a resume re-runs from scratch.
            command_log.append("# variant calling path: Parabricks mutectcaller (GPU)")
            filtered_vcf, tbi_path, mutect_stats, tumor_sample, normal_sample = run_parabricks_pipeline(
                inputs,
                run_id=run_id,
                on_progress=progress_cb,
                command_log=command_log,
            )
        else:
            command_log.append("# variant calling path: GATK Mutect2 (CPU scatter-gather)")
            filtered_vcf, tbi_path, mutect_stats, tumor_sample, normal_sample = run_mutect2_pipeline(
                inputs,
                run_id=run_id,
                on_progress=progress_cb,
                on_shard_progress=shard_progress_cb,
                command_log=command_log,
            )

        progress_cb(90, VariantCallingRuntimePhase.FINALIZING)
        metrics = compute_variant_metrics(
            filtered_vcf,
            inputs.reference_fasta,
            tumor_sample=tumor_sample,
            normal_sample=normal_sample,
            reference_label=inputs.reference_label,
        )

        persist_variant_calling_success(
            workspace_id,
            run_id,
            filtered_vcf=filtered_vcf,
            tbi_path=tbi_path,
            mutect_stats=mutect_stats,
            metrics=metrics,
            command_log=command_log,
        )
    except VariantCallingCancelledError:
        if is_run_paused_pending(run_id):
            mark_variant_calling_run_paused(workspace_id, run_id)
        else:
            mark_variant_calling_run_cancelled(workspace_id, run_id)
    except subprocess.CalledProcessError as error:
        if is_run_paused_pending(run_id):
            mark_variant_calling_run_paused(workspace_id, run_id)
        elif is_run_cancelled(run_id):
            mark_variant_calling_run_cancelled(workspace_id, run_id)
        else:
            stderr_tail = (error.stderr or "").splitlines()[-20:]
            message = " | ".join(stderr_tail) if stderr_tail else str(error)
            mark_variant_calling_run_failed(
                workspace_id,
                run_id,
                f"{' '.join(error.cmd[:3])} failed: {message}",
            )
    except Exception as error:
        if is_run_paused_pending(run_id):
            mark_variant_calling_run_paused(workspace_id, run_id)
        elif is_run_cancelled(run_id):
            mark_variant_calling_run_cancelled(workspace_id, run_id)
        else:
            mark_variant_calling_run_failed(workspace_id, run_id, str(error))
    finally:
        clear_subprocess_registry(run_id)
        clear_run_cancelled(run_id)
        clear_run_paused_pending(run_id)
        clear_shard_progress(run_id)
        clear_run_pid_dir(run_id)


def load_variant_calling_artifact_download(
    workspace_id: str,
    artifact_id: str,
) -> VariantCallingArtifactDownload:
    with session_scope() as session:
        artifact = get_variant_calling_artifact_record(session, workspace_id, artifact_id)
        return VariantCallingArtifactDownload(
            filename=artifact.filename,
            local_path=resolve_app_data_path(artifact.local_path or artifact.storage_key),
            content_type=artifact.content_type,
        )
