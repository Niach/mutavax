"""Neoantigen prediction stage service (pVACseq + NetMHCpan / NetMHCIIpan).

Consumes the annotated VCF from stage 4, runs pVACseq twice — once for class I
binding against NetMHCpan 4.1, once for class II binding against NetMHCIIpan 4.3 —
and parses the resulting ``all_epitopes.tsv`` / ``filtered.tsv`` output into a
``NeoantigenMetricsResponse`` that the frontend's binding heatmap, ranking scatter,
antigen funnel, and top-candidates table consume directly.

Runtime phases:
    generating_fasta → running_class_i → running_class_ii → parsing → finalizing

pVACseq binds the class-I and class-II calls to separate output subdirectories so
a paused run can resume with class-II alone without rerunning class-I.
"""
from __future__ import annotations

import csv
import json
import math
import os
import shutil
import signal
import subprocess
import threading
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.db import session_scope
from app.runtime import (
    get_app_data_root,
    get_neoantigen_run_root,
    resolve_app_data_path,
)
from app.models.records import PipelineArtifactRecord, PipelineRunRecord
from app.models.schemas import (
    BindingBucket,
    BindingTier,
    FunnelStep,
    HeatmapData,
    HeatmapRow,
    NeoantigenArtifactKind,
    NeoantigenArtifactResponse,
    NeoantigenMetricsResponse,
    NeoantigenRunResponse,
    NeoantigenRunStatus,
    NeoantigenRuntimePhase,
    NeoantigenStageStatus,
    NeoantigenStageSummaryResponse,
    PatientAllele,
    PipelineStageId,
    TopCandidate,
)
from app.services.annotation import (
    ANNOTATION_STAGE_ID,
    AnnotationRunStatus,
    get_latest_annotation_run,
)
from app.services.workspace_store import (
    get_workspace_record,
    isoformat,
    load_workspace_neoantigen_config,
    store_workspace_neoantigen_config,
    utc_now,
)


NEOANTIGEN_STAGE_ID = PipelineStageId.NEOANTIGEN_PREDICTION.value
PVACSEQ_SAMPLE_NAME = "sample"

# Default pVACseq knobs. Mirror the prototype's Expert drawer copy.
CLASS_I_EPITOPE_LENGTHS = (8, 9, 10, 11)
CLASS_II_EPITOPE_LENGTHS = (12, 13, 14, 15, 16, 17, 18)
BINDING_THRESHOLD_NM = 500.0
STRONG_BINDER_NM = 50.0
MODERATE_BINDER_NM = 500.0
WEAK_BINDER_NM = 5000.0

TOP_CANDIDATES_LIMIT = 10
HEATMAP_PEPTIDE_LIMIT = 12

# Known cancer gene symbols — reused to flag the `cancer_gene` badge. Intentionally
# narrow; the annotation stage ships the full ~700-symbol list in data/cancer_genes.csv.
COMMON_CANCER_GENES = {
    "TP53", "KRAS", "BRAF", "EGFR", "PIK3CA", "PTEN", "RB1", "APC", "ATM",
    "BRCA1", "BRCA2", "KIT", "NOTCH1", "SETD2", "FBXW7", "IDH1", "IDH2",
    "MYC", "NRAS", "HRAS", "SMAD4", "CDKN2A", "VHL", "NF1", "NF2", "MLH1",
    "MSH2", "MSH6", "PMS2", "STK11", "AKT1", "ERBB2", "MET", "ALK", "ROS1",
    "RET", "FLT3", "JAK2", "CTNNB1", "FGFR1", "FGFR2", "FGFR3",
}


# --------------------------------------------------------------------------- #
# Subprocess + cancel registry (mirror of annotation.py)
# --------------------------------------------------------------------------- #

_registry_lock = threading.Lock()
_active_subprocesses: dict[str, list[subprocess.Popen]] = {}
_cancelled_runs: set[str] = set()
_paused_pending_runs: set[str] = set()
_run_pid_dirs: dict[str, Path] = {}


class NeoantigenArtifactNotFoundError(FileNotFoundError):
    pass


class NeoantigenCancelledError(Exception):
    """Raised when a neoantigen run is cancelled."""


@dataclass(frozen=True)
class NeoantigenArtifactDownload:
    filename: str
    local_path: Path
    content_type: Optional[str]


@dataclass
class NeoantigenInputs:
    workspace_id: str
    run_id: str
    species: str
    species_label: Optional[str]
    assembly: Optional[str]
    annotated_vcf: Path
    run_dir: Path
    class_i_alleles: list[PatientAllele]
    class_ii_alleles: list[PatientAllele]
    patient_alleles: list[PatientAllele]


def _derive_pid_dir_on_disk(workspace_id: str, run_id: str) -> Path:
    return (
        get_app_data_root()
        / "workspaces"
        / workspace_id
        / "neoantigen-prediction"
        / run_id
        / "pids"
    )


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
    with _registry_lock:
        _run_pid_dirs[run_id] = pid_dir


def clear_run_pid_dir(run_id: str) -> None:
    with _registry_lock:
        _run_pid_dirs.pop(run_id, None)


def _get_run_pid_dir(run_id: str) -> Optional[Path]:
    with _registry_lock:
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


def register_subprocess(run_id: str, proc: subprocess.Popen) -> None:
    with _registry_lock:
        _active_subprocesses.setdefault(run_id, []).append(proc)
    _write_pid_marker(run_id, proc.pid)


def unregister_subprocess(run_id: str, proc: subprocess.Popen) -> None:
    with _registry_lock:
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
    with _registry_lock:
        _active_subprocesses.pop(run_id, None)


def mark_run_cancelled(run_id: str) -> None:
    with _registry_lock:
        _cancelled_runs.add(run_id)


def clear_run_cancelled(run_id: str) -> None:
    with _registry_lock:
        _cancelled_runs.discard(run_id)


def is_run_cancelled(run_id: str) -> bool:
    with _registry_lock:
        return run_id in _cancelled_runs


def mark_run_paused_pending(run_id: str) -> None:
    with _registry_lock:
        _cancelled_runs.add(run_id)
        _paused_pending_runs.add(run_id)


def clear_run_paused_pending(run_id: str) -> None:
    with _registry_lock:
        _paused_pending_runs.discard(run_id)


def is_run_paused_pending(run_id: str) -> bool:
    with _registry_lock:
        return run_id in _paused_pending_runs


def _signal_process_group(pid: int, sig: int) -> bool:
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


def _read_proc_cmdline(pid: int) -> Optional[str]:
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as fh:
            return fh.read().decode("utf-8", errors="replace")
    except (OSError, ValueError):
        return None


def _terminate_pid_file_survivors(
    run_id: str, *, pid_dir: Optional[Path], grace_seconds: float
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
        if cmdline is None or run_id not in cmdline:
            try:
                entry.unlink(missing_ok=True)
            except OSError:
                pass
            continue
        candidates.append(pid)
    if not candidates:
        return 0
    terminated = 0
    for pid in candidates:
        if _signal_process_group(pid, signal.SIGTERM):
            terminated += 1
    deadline = time.time() + grace_seconds
    while time.time() < deadline:
        alive = [pid for pid in candidates if _read_proc_cmdline(pid) is not None]
        if not alive:
            break
        time.sleep(0.2)
    for pid in candidates:
        if _read_proc_cmdline(pid) is not None:
            _signal_process_group(pid, signal.SIGKILL)
        try:
            _pid_marker_path(pid_dir, pid).unlink(missing_ok=True)
        except OSError:
            pass
    return terminated


def terminate_run_subprocesses(
    run_id: str, *, grace_seconds: float = 5.0, pid_dir: Optional[Path] = None
) -> int:
    with _registry_lock:
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


def _run_subprocess(
    command: list[str],
    *,
    cwd: Optional[Path] = None,
    run_id: Optional[str] = None,
    env: Optional[dict[str, str]] = None,
) -> subprocess.CompletedProcess:
    if run_id is None:
        return subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            cwd=cwd,
            env=env,
        )
    proc = subprocess.Popen(
        command,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
        env=env,
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
                proc.communicate()
                raise NeoantigenCancelledError("Neoantigen run was cancelled.")
            try:
                stdout, stderr = proc.communicate(timeout=1.0)
                break
            except subprocess.TimeoutExpired:
                continue
        returncode = proc.returncode
        if returncode != 0:
            if is_run_cancelled(run_id):
                raise NeoantigenCancelledError("Neoantigen run was cancelled.")
            raise subprocess.CalledProcessError(returncode, command, stdout, stderr)
        return subprocess.CompletedProcess(command, returncode, stdout, stderr)
    finally:
        unregister_subprocess(run_id, proc)


# --------------------------------------------------------------------------- #
# Record access
# --------------------------------------------------------------------------- #


def _run_query():
    return select(PipelineRunRecord).options(
        selectinload(PipelineRunRecord.artifacts),
        selectinload(PipelineRunRecord.workspace),
    )


def get_latest_neoantigen_run(session, workspace_id: str) -> Optional[PipelineRunRecord]:
    return session.scalar(
        _run_query()
        .where(
            PipelineRunRecord.workspace_id == workspace_id,
            PipelineRunRecord.stage_id == NEOANTIGEN_STAGE_ID,
        )
        .order_by(PipelineRunRecord.created_at.desc())
    )


def get_neoantigen_run_record(
    session, workspace_id: str, run_id: str
) -> PipelineRunRecord:
    run = session.scalar(
        _run_query().where(
            PipelineRunRecord.id == run_id,
            PipelineRunRecord.workspace_id == workspace_id,
            PipelineRunRecord.stage_id == NEOANTIGEN_STAGE_ID,
        )
    )
    if run is None:
        raise FileNotFoundError(f"Neoantigen run {run_id} not found")
    return run


def get_neoantigen_artifact_record(
    session, workspace_id: str, artifact_id: str
) -> PipelineArtifactRecord:
    artifact = session.scalar(
        select(PipelineArtifactRecord).where(
            PipelineArtifactRecord.id == artifact_id,
            PipelineArtifactRecord.workspace_id == workspace_id,
            PipelineArtifactRecord.stage_id == NEOANTIGEN_STAGE_ID,
        )
    )
    if artifact is None:
        raise NeoantigenArtifactNotFoundError(
            f"Neoantigen artifact {artifact_id} not found"
        )
    return artifact


# --------------------------------------------------------------------------- #
# Serializers
# --------------------------------------------------------------------------- #


def _serialize_artifact(record: PipelineArtifactRecord) -> NeoantigenArtifactResponse:
    return NeoantigenArtifactResponse(
        id=record.id,
        artifact_kind=NeoantigenArtifactKind(record.artifact_kind),
        filename=record.filename,
        size_bytes=record.size_bytes,
        download_path=f"/api/workspaces/{record.workspace_id}/neoantigen/artifacts/{record.id}/download",
        local_path=record.local_path,
    )


def _parse_payload(payload: Optional[str]) -> dict:
    if not payload:
        return {}
    try:
        data = json.loads(payload)
    except (TypeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _parse_metrics(payload: Optional[str]) -> Optional[NeoantigenMetricsResponse]:
    data = _parse_payload(payload)
    metrics = data.get("metrics")
    if not isinstance(metrics, dict):
        return None
    try:
        return NeoantigenMetricsResponse.model_validate(metrics)
    except Exception:
        return None


def serialize_neoantigen_run(record: PipelineRunRecord) -> NeoantigenRunResponse:
    return NeoantigenRunResponse(
        id=record.id,
        status=NeoantigenRunStatus(record.status),
        progress=record.progress / 100,
        runtime_phase=(
            NeoantigenRuntimePhase(record.runtime_phase)
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
    )


# --------------------------------------------------------------------------- #
# Stage summary
# --------------------------------------------------------------------------- #


def _patient_alleles_from_config(config: dict) -> list[PatientAllele]:
    alleles: list[PatientAllele] = []
    for raw in config.get("alleles", []) or []:
        if not isinstance(raw, dict):
            continue
        name = raw.get("allele")
        mhc_class = raw.get("class")
        if not name or mhc_class not in ("I", "II"):
            continue
        alleles.append(
            PatientAllele(
                allele=name,
                **{"class": mhc_class},
                typing=raw.get("typing") or "inferred",
                frequency=raw.get("frequency"),
                source=raw.get("source"),
            )
        )
    return alleles


def build_neoantigen_stage_summary(
    workspace,
    latest_annotation_run: Optional[PipelineRunRecord],
    latest_neoantigen_run: Optional[PipelineRunRecord],
) -> NeoantigenStageSummaryResponse:
    config = load_workspace_neoantigen_config(workspace)
    alleles = _patient_alleles_from_config(config)

    latest_response = (
        serialize_neoantigen_run(latest_neoantigen_run)
        if latest_neoantigen_run is not None
        else None
    )
    artifacts = latest_response.artifacts if latest_response else []

    annotation_ready = (
        latest_annotation_run is not None
        and latest_annotation_run.status == AnnotationRunStatus.COMPLETED.value
    )
    if not annotation_ready:
        return NeoantigenStageSummaryResponse(
            workspace_id=workspace.id,
            status=NeoantigenStageStatus.BLOCKED,
            blocking_reason="Finish annotation before we can predict neoantigens.",
            ready_for_epitope_selection=False,
            alleles=alleles,
            latest_run=latest_response,
            artifacts=artifacts,
        )

    if latest_neoantigen_run is None:
        return NeoantigenStageSummaryResponse(
            workspace_id=workspace.id,
            status=NeoantigenStageStatus.SCAFFOLDED,
            blocking_reason=None,
            ready_for_epitope_selection=False,
            alleles=alleles,
            latest_run=None,
            artifacts=[],
        )

    status = latest_neoantigen_run.status
    if status in {NeoantigenRunStatus.PENDING.value, NeoantigenRunStatus.RUNNING.value}:
        return NeoantigenStageSummaryResponse(
            workspace_id=workspace.id,
            status=NeoantigenStageStatus.RUNNING,
            blocking_reason=None,
            ready_for_epitope_selection=False,
            alleles=alleles,
            latest_run=latest_response,
            artifacts=artifacts,
        )
    if status == NeoantigenRunStatus.PAUSED.value:
        return NeoantigenStageSummaryResponse(
            workspace_id=workspace.id,
            status=NeoantigenStageStatus.PAUSED,
            blocking_reason=latest_neoantigen_run.blocking_reason,
            ready_for_epitope_selection=False,
            alleles=alleles,
            latest_run=latest_response,
            artifacts=artifacts,
        )
    if status == NeoantigenRunStatus.FAILED.value:
        return NeoantigenStageSummaryResponse(
            workspace_id=workspace.id,
            status=NeoantigenStageStatus.FAILED,
            blocking_reason=latest_neoantigen_run.blocking_reason,
            ready_for_epitope_selection=False,
            alleles=alleles,
            latest_run=latest_response,
            artifacts=artifacts,
        )
    if status == NeoantigenRunStatus.CANCELLED.value:
        return NeoantigenStageSummaryResponse(
            workspace_id=workspace.id,
            status=NeoantigenStageStatus.SCAFFOLDED,
            blocking_reason=None,
            ready_for_epitope_selection=False,
            alleles=alleles,
            latest_run=latest_response,
            artifacts=[],
        )

    return NeoantigenStageSummaryResponse(
        workspace_id=workspace.id,
        status=NeoantigenStageStatus.COMPLETED,
        blocking_reason=None,
        ready_for_epitope_selection=True,
        alleles=alleles,
        latest_run=latest_response,
        artifacts=artifacts,
    )


def load_neoantigen_stage_summary(workspace_id: str) -> NeoantigenStageSummaryResponse:
    with session_scope() as session:
        workspace = get_workspace_record(session, workspace_id)
        latest_annotation = get_latest_annotation_run(session, workspace_id)
        latest_neoantigen = get_latest_neoantigen_run(session, workspace_id)
        return build_neoantigen_stage_summary(
            workspace, latest_annotation, latest_neoantigen
        )


def update_neoantigen_alleles(
    workspace_id: str, alleles: list[PatientAllele]
) -> NeoantigenStageSummaryResponse:
    with session_scope() as session:
        workspace = get_workspace_record(session, workspace_id)
        existing = load_workspace_neoantigen_config(workspace)
        existing["alleles"] = [
            {
                "allele": allele.allele,
                "class": allele.mhc_class,
                "typing": allele.typing,
                "frequency": allele.frequency,
                "source": allele.source,
            }
            for allele in alleles
        ]
        store_workspace_neoantigen_config(workspace, existing)
        workspace.updated_at = utc_now()
        session.add(workspace)
    return load_neoantigen_stage_summary(workspace_id)


# --------------------------------------------------------------------------- #
# Run orchestration
# --------------------------------------------------------------------------- #


def _locate_annotated_vcf(run: PipelineRunRecord) -> Optional[Path]:
    for artifact in run.artifacts:
        if artifact.artifact_kind == "annotated_vcf":
            candidate = resolve_app_data_path(artifact.local_path or artifact.storage_key)
            if candidate.exists():
                return candidate
    return None


def create_neoantigen_run(workspace_id: str) -> NeoantigenStageSummaryResponse:
    created_run_id: Optional[str] = None
    with session_scope() as session:
        workspace = get_workspace_record(session, workspace_id)
        latest_annotation = get_latest_annotation_run(session, workspace_id)
        latest_neoantigen = get_latest_neoantigen_run(session, workspace_id)

        if latest_neoantigen and latest_neoantigen.status in {
            NeoantigenRunStatus.PENDING.value,
            NeoantigenRunStatus.RUNNING.value,
        }:
            raise ValueError("Neoantigen prediction is already running for this workspace.")
        if latest_neoantigen and latest_neoantigen.status == NeoantigenRunStatus.PAUSED.value:
            raise ValueError(
                "A paused neoantigen run exists. Resume it, or discard it, before starting a new run."
            )

        if (
            latest_annotation is None
            or latest_annotation.status != AnnotationRunStatus.COMPLETED.value
        ):
            raise ValueError("Finish annotation before we can predict neoantigens.")

        annotated_vcf = _locate_annotated_vcf(latest_annotation)
        if annotated_vcf is None:
            raise ValueError(
                "The annotated VCF from stage 4 is missing on disk; rerun annotation first."
            )

        config = load_workspace_neoantigen_config(workspace)
        alleles = _patient_alleles_from_config(config)
        if not alleles:
            raise ValueError(
                "No MHC alleles configured. Add at least one DLA/HLA allele before running."
            )

        annotation_payload = _parse_payload(latest_annotation.result_payload)

        timestamp = utc_now()
        run = PipelineRunRecord(
            id=str(uuid.uuid4()),
            workspace_id=workspace.id,
            stage_id=NEOANTIGEN_STAGE_ID,
            status=NeoantigenRunStatus.PENDING.value,
            progress=0,
            qc_verdict=None,
            reference_preset=latest_annotation.reference_preset,
            reference_override=latest_annotation.reference_override,
            reference_label=latest_annotation.reference_label,
            reference_path=latest_annotation.reference_path,
            runtime_phase=NeoantigenRuntimePhase.GENERATING_FASTA.value,
            command_log=None,
            result_payload=json.dumps(
                {
                    "species": workspace.species,
                    "species_label": annotation_payload.get("species_label")
                    or config.get("species_label"),
                    "assembly": _assembly_for_annotation(annotation_payload),
                }
            ),
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
        summary = build_neoantigen_stage_summary(workspace, latest_annotation, run)

    if created_run_id is None:
        raise RuntimeError("Neoantigen run creation did not produce an id")

    enqueue_neoantigen_run(workspace_id, created_run_id)
    return summary


def _assembly_for_annotation(annotation_payload: dict) -> Optional[str]:
    label = annotation_payload.get("species_label")
    if isinstance(label, str) and "(" in label and ")" in label:
        inside = label[label.index("(") + 1 : label.rindex(")")].strip()
        return inside or None
    return None


def rerun_neoantigen(workspace_id: str) -> NeoantigenStageSummaryResponse:
    return create_neoantigen_run(workspace_id)


def mark_neoantigen_run_cancelled(
    workspace_id: str, run_id: str, reason: str = "Stopped by user."
) -> None:
    with session_scope() as session:
        run = get_neoantigen_run_record(session, workspace_id, run_id)
        run.status = NeoantigenRunStatus.CANCELLED.value
        run.progress = 0
        run.runtime_phase = None
        run.blocking_reason = reason
        run.error = None
        run.updated_at = utc_now()
        run.completed_at = run.updated_at
        run.workspace.updated_at = run.updated_at
        session.add(run)
        session.add(run.workspace)


def mark_neoantigen_run_paused(
    workspace_id: str, run_id: str, reason: str = "Paused by user. Resume to continue."
) -> None:
    with session_scope() as session:
        run = get_neoantigen_run_record(session, workspace_id, run_id)
        run.status = NeoantigenRunStatus.PAUSED.value
        run.runtime_phase = None
        run.blocking_reason = reason
        run.error = None
        run.updated_at = utc_now()
        run.workspace.updated_at = run.updated_at
        session.add(run)
        session.add(run.workspace)


def _wipe_neoantigen_run_dir(workspace_id: str, run_id: str) -> None:
    try:
        run_dir = get_neoantigen_run_root(workspace_id, run_id)
    except Exception:
        return
    if run_dir.exists():
        shutil.rmtree(run_dir, ignore_errors=True)


def cancel_neoantigen_run(
    workspace_id: str, run_id: str
) -> NeoantigenStageSummaryResponse:
    with session_scope() as session:
        run = get_neoantigen_run_record(session, workspace_id, run_id)
        if run.status not in {
            NeoantigenRunStatus.PENDING.value,
            NeoantigenRunStatus.RUNNING.value,
            NeoantigenRunStatus.PAUSED.value,
        }:
            return load_neoantigen_stage_summary(workspace_id)
        was_paused = run.status == NeoantigenRunStatus.PAUSED.value

    if was_paused:
        mark_neoantigen_run_cancelled(workspace_id, run_id)
        _wipe_neoantigen_run_dir(workspace_id, run_id)
        return load_neoantigen_stage_summary(workspace_id)

    mark_run_cancelled(run_id)
    terminate_run_subprocesses(
        run_id, pid_dir=_derive_pid_dir_on_disk(workspace_id, run_id)
    )
    mark_neoantigen_run_cancelled(workspace_id, run_id)
    _wipe_neoantigen_run_dir(workspace_id, run_id)
    return load_neoantigen_stage_summary(workspace_id)


def pause_neoantigen_run(
    workspace_id: str, run_id: str
) -> NeoantigenStageSummaryResponse:
    with session_scope() as session:
        run = get_neoantigen_run_record(session, workspace_id, run_id)
        if run.status not in {
            NeoantigenRunStatus.PENDING.value,
            NeoantigenRunStatus.RUNNING.value,
        }:
            return load_neoantigen_stage_summary(workspace_id)

    mark_run_paused_pending(run_id)
    terminate_run_subprocesses(
        run_id, pid_dir=_derive_pid_dir_on_disk(workspace_id, run_id)
    )
    mark_neoantigen_run_paused(workspace_id, run_id)
    return load_neoantigen_stage_summary(workspace_id)


def resume_neoantigen_run(
    workspace_id: str, run_id: str
) -> NeoantigenStageSummaryResponse:
    with session_scope() as session:
        run = get_neoantigen_run_record(session, workspace_id, run_id)
        if run.status != NeoantigenRunStatus.PAUSED.value:
            raise ValueError(
                f"Cannot resume a run in status {run.status!r}; only paused runs are resumable."
            )
        timestamp = utc_now()
        run.status = NeoantigenRunStatus.PENDING.value
        run.runtime_phase = NeoantigenRuntimePhase.RUNNING_CLASS_I.value
        run.blocking_reason = None
        run.error = None
        run.updated_at = timestamp
        run.completed_at = None
        run.workspace.updated_at = timestamp
        session.add(run)
        session.add(run.workspace)

    enqueue_neoantigen_run(workspace_id, run_id)
    return load_neoantigen_stage_summary(workspace_id)


def mark_neoantigen_run_failed(
    workspace_id: str, run_id: str, error_message: str
) -> None:
    with session_scope() as session:
        run = get_neoantigen_run_record(session, workspace_id, run_id)
        run.status = NeoantigenRunStatus.FAILED.value
        run.progress = 100
        run.error = error_message
        run.blocking_reason = error_message
        run.runtime_phase = None
        run.updated_at = utc_now()
        run.completed_at = run.updated_at
        run.workspace.updated_at = run.updated_at
        session.add(run)
        session.add(run.workspace)


def enqueue_neoantigen_run(workspace_id: str, run_id: str) -> None:
    from app.services import background

    try:
        background.submit(run_neoantigen, workspace_id, run_id)
    except Exception as error:
        mark_neoantigen_run_failed(
            workspace_id, run_id, f"Unable to queue neoantigen prediction: {error}"
        )


def update_neoantigen_progress(
    workspace_id: str,
    run_id: str,
    progress: int,
    runtime_phase: Optional[NeoantigenRuntimePhase] = None,
) -> None:
    with session_scope() as session:
        run = get_neoantigen_run_record(session, workspace_id, run_id)
        if run.status not in {
            NeoantigenRunStatus.PENDING.value,
            NeoantigenRunStatus.RUNNING.value,
        }:
            return
        run.progress = progress
        if runtime_phase is not None:
            run.runtime_phase = runtime_phase.value
        run.updated_at = utc_now()
        run.workspace.updated_at = run.updated_at
        session.add(run)
        session.add(run.workspace)


def start_neoantigen_run(workspace_id: str, run_id: str) -> NeoantigenInputs:
    with session_scope() as session:
        workspace = get_workspace_record(session, workspace_id)
        run = get_neoantigen_run_record(session, workspace_id, run_id)
        latest_annotation = get_latest_annotation_run(session, workspace_id)
        if (
            latest_annotation is None
            or latest_annotation.status != AnnotationRunStatus.COMPLETED.value
        ):
            raise RuntimeError("Annotation output is no longer available.")
        annotated_vcf = _locate_annotated_vcf(latest_annotation)
        if annotated_vcf is None:
            raise RuntimeError(
                "The annotated VCF is missing on disk. Rerun annotation first."
            )

        config = load_workspace_neoantigen_config(workspace)
        alleles = _patient_alleles_from_config(config)
        class_i = [a for a in alleles if a.mhc_class == "I"]
        class_ii = [a for a in alleles if a.mhc_class == "II"]

        payload = _parse_payload(run.result_payload)
        species_label = payload.get("species_label")
        assembly = payload.get("assembly")

        run.status = NeoantigenRunStatus.RUNNING.value
        if run.progress < 5:
            run.progress = 5
        if run.runtime_phase is None:
            run.runtime_phase = NeoantigenRuntimePhase.GENERATING_FASTA.value
        timestamp = utc_now()
        if run.started_at is None:
            run.started_at = timestamp
        run.updated_at = timestamp
        run.completed_at = None
        run.error = None
        run.blocking_reason = None
        workspace.updated_at = timestamp
        session.add(run)
        session.add(workspace)

        species = workspace.species

    run_dir = get_neoantigen_run_root(workspace_id, run_id)
    return NeoantigenInputs(
        workspace_id=workspace_id,
        run_id=run_id,
        species=species,
        species_label=species_label,
        assembly=assembly,
        annotated_vcf=annotated_vcf,
        run_dir=run_dir,
        class_i_alleles=class_i,
        class_ii_alleles=class_ii,
        patient_alleles=alleles,
    )


# --------------------------------------------------------------------------- #
# pVACseq execution
# --------------------------------------------------------------------------- #


def _pvacseq_binary() -> str:
    return os.getenv("PVACSEQ_BINARY", "pvacseq")


def _netmhcpan_version() -> str:
    return os.getenv("CANCERSTUDIO_NETMHCPAN_VERSION", "NetMHCpan 4.1")


def _netmhciipan_version() -> str:
    return os.getenv("CANCERSTUDIO_NETMHCIIPAN_VERSION", "NetMHCIIpan 4.3")


def _pvacseq_version(run_id: Optional[str] = None) -> Optional[str]:
    try:
        result = subprocess.run(
            [_pvacseq_binary(), "--version"],
            check=True,
            capture_output=True,
            text=True,
            timeout=10.0,
        )
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return None
    return result.stdout.strip() or result.stderr.strip() or None


def _run_pvacseq(
    *,
    inputs: NeoantigenInputs,
    alleles: list[PatientAllele],
    predictor: str,
    output_dir: Path,
    epitope_flag: str,
    epitope_lengths: tuple[int, ...],
    command_log: list[str],
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    allele_string = ",".join(a.allele for a in alleles)
    command: list[str] = [
        _pvacseq_binary(),
        "run",
        str(inputs.annotated_vcf),
        PVACSEQ_SAMPLE_NAME,
        allele_string,
        predictor,
        str(output_dir),
        epitope_flag,
        ",".join(str(length) for length in epitope_lengths),
        "--binding-threshold",
        str(int(BINDING_THRESHOLD_NM)),
    ]
    command_log.append(" ".join(command))
    _run_subprocess(command, run_id=inputs.run_id)


# --------------------------------------------------------------------------- #
# pVACseq output parsing
# --------------------------------------------------------------------------- #


def _find_tsv(root: Path, pattern: str) -> Optional[Path]:
    if not root.exists():
        return None
    matches = list(root.rglob(pattern))
    matches.sort(key=lambda p: len(p.parts))
    return matches[0] if matches else None


def _read_tsv_rows(path: Path) -> list[dict[str, str]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle, delimiter="\t")
            return [row for row in reader]
    except (FileNotFoundError, OSError):
        return []


def _float_or_none(value: Optional[str]) -> Optional[float]:
    if value is None:
        return None
    trimmed = value.strip()
    if not trimmed or trimmed.upper() in {"NA", "NAN", "."}:
        return None
    try:
        return float(trimmed)
    except ValueError:
        return None


def _canonical_ic50(row: dict[str, str]) -> Optional[float]:
    # pVACseq renames this column across its many predictors. Accept the most
    # common spellings.
    for key in (
        "Best MT IC50 Score",
        "Best MT Score",
        "MT IC50 Score",
        "Median MT IC50 Score",
        "Median MT Score",
        "MT Score",
    ):
        value = row.get(key)
        if value is None:
            continue
        result = _float_or_none(value)
        if result is not None:
            return result
    return None


def _canonical_wt_ic50(row: dict[str, str]) -> Optional[float]:
    for key in (
        "Best WT IC50 Score",
        "Best WT Score",
        "WT IC50 Score",
        "Median WT IC50 Score",
        "Median WT Score",
        "WT Score",
    ):
        value = row.get(key)
        if value is None:
            continue
        result = _float_or_none(value)
        if result is not None:
            return result
    return None


def _canonical_allele(row: dict[str, str]) -> str:
    return (row.get("HLA Allele") or row.get("Allele") or "").strip()


def _canonical_peptide(row: dict[str, str]) -> str:
    return (row.get("MT Epitope Seq") or row.get("MT Epitope") or "").strip()


def _canonical_wt_peptide(row: dict[str, str]) -> str:
    return (row.get("WT Epitope Seq") or row.get("WT Epitope") or "").strip()


def _canonical_gene(row: dict[str, str]) -> str:
    return (row.get("Gene Name") or row.get("Gene") or "").strip()


def _canonical_mutation(row: dict[str, str]) -> str:
    return (
        row.get("Mutation")
        or row.get("Protein Position")
        or row.get("Transcript")
        or ""
    ).strip()


def _canonical_vaf(row: dict[str, str]) -> Optional[float]:
    for key in ("Tumor DNA VAF", "Tumor VAF", "VAF"):
        value = row.get(key)
        result = _float_or_none(value)
        if result is not None:
            if result > 1.0:
                return result / 100.0
            return result
    return None


def _canonical_tpm(row: dict[str, str]) -> Optional[float]:
    for key in ("Gene Expression", "Transcript Expression", "Tumor RNA Depth"):
        value = row.get(key)
        result = _float_or_none(value)
        if result is not None:
            return result
    return None


def _mutation_position(row: dict[str, str], peptide: str) -> Optional[int]:
    mt = peptide
    wt = _canonical_wt_peptide(row)
    if mt and wt and len(mt) == len(wt):
        for index, (m, w) in enumerate(zip(mt, wt)):
            if m != w:
                return index
    if mt:
        return max(0, len(mt) // 2 - 1)
    return None


def _bucket_for_ic50(ic50: float) -> BindingTier:
    if ic50 < STRONG_BINDER_NM:
        return "strong"
    if ic50 < MODERATE_BINDER_NM:
        return "moderate"
    if ic50 < WEAK_BINDER_NM:
        return "weak"
    return "none"


def _humanize_mut(row: dict[str, str]) -> str:
    mut = (row.get("Protein Position") or "").strip()
    ref = (row.get("Reference") or "").strip()
    var = (row.get("Variant") or "").strip()
    if ref and var and mut:
        return f"p.{ref}{mut}{var}"
    return _canonical_mutation(row) or "variant"


def _tier_counts_to_buckets(counts: dict[BindingTier, int]) -> list[BindingBucket]:
    return [
        BindingBucket(
            key="strong",
            label="Strong binders",
            threshold=f"< {int(STRONG_BINDER_NM)} nM",
            plain="Almost certainly visible to the immune system",
            count=counts.get("strong", 0),
        ),
        BindingBucket(
            key="moderate",
            label="Moderate binders",
            threshold=f"{int(STRONG_BINDER_NM)} – {int(MODERATE_BINDER_NM)} nM",
            plain="Likely to trigger a response",
            count=counts.get("moderate", 0),
        ),
        BindingBucket(
            key="weak",
            label="Weak binders",
            threshold=f"{int(MODERATE_BINDER_NM)} – {int(WEAK_BINDER_NM):,} nM",
            plain="Fragment is made but unlikely to stick to MHC",
            count=counts.get("weak", 0),
        ),
        BindingBucket(
            key="none",
            label="Non-binders",
            threshold=f"> {int(WEAK_BINDER_NM):,} nM",
            plain="Never reach the cell surface",
            count=counts.get("none", 0),
        ),
    ]


@dataclass
class ParsedEpitope:
    peptide: str
    gene: str
    mutation: str
    length: int
    mhc_class: str
    allele: str
    ic50: float
    wt_ic50: Optional[float]
    vaf: Optional[float]
    tpm: Optional[float]
    mut_pos: Optional[int]


def _parse_all_epitopes(path: Path, mhc_class: str) -> list[ParsedEpitope]:
    rows = _read_tsv_rows(path)
    parsed: list[ParsedEpitope] = []
    for row in rows:
        peptide = _canonical_peptide(row)
        ic50 = _canonical_ic50(row)
        allele = _canonical_allele(row)
        if not peptide or ic50 is None or not allele:
            continue
        parsed.append(
            ParsedEpitope(
                peptide=peptide,
                gene=_canonical_gene(row) or "?",
                mutation=_humanize_mut(row),
                length=len(peptide),
                mhc_class=mhc_class,
                allele=allele,
                ic50=ic50,
                wt_ic50=_canonical_wt_ic50(row),
                vaf=_canonical_vaf(row),
                tpm=_canonical_tpm(row),
                mut_pos=_mutation_position(row, peptide),
            )
        )
    return parsed


def _build_heatmap(
    class_i: list[ParsedEpitope],
    class_ii: list[ParsedEpitope],
    all_alleles: list[PatientAllele],
) -> HeatmapData:
    allele_order = [a.allele for a in all_alleles]

    by_peptide: dict[tuple[str, str], ParsedEpitope] = {}
    for entry in class_i + class_ii:
        key = (entry.peptide, entry.mhc_class)
        existing = by_peptide.get(key)
        if existing is None or entry.ic50 < existing.ic50:
            by_peptide[key] = entry

    best_per_peptide: dict[tuple[str, str], dict[str, float]] = defaultdict(dict)
    for entry in class_i + class_ii:
        key = (entry.peptide, entry.mhc_class)
        prior = best_per_peptide[key].get(entry.allele)
        if prior is None or entry.ic50 < prior:
            best_per_peptide[key][entry.allele] = entry.ic50

    # Top peptides by IC50 across both classes, capped to HEATMAP_PEPTIDE_LIMIT.
    ranked = sorted(by_peptide.values(), key=lambda e: e.ic50)[:HEATMAP_PEPTIDE_LIMIT]

    rows: list[HeatmapRow] = []
    for entry in ranked:
        affinities = best_per_peptide[(entry.peptide, entry.mhc_class)]
        ic50_row: list[float] = []
        for allele_name in allele_order:
            ic50_row.append(affinities.get(allele_name, 99_999.0))
        rows.append(
            HeatmapRow(
                seq=entry.peptide,
                gene=entry.gene,
                mut=entry.mutation,
                length=entry.length,
                **{"class": entry.mhc_class},
                vaf=entry.vaf if entry.vaf is not None else 0.0,
                ic50=ic50_row,
                mut_pos=entry.mut_pos,
            )
        )
    return HeatmapData(alleles=allele_order, peptides=rows)


def _build_top_candidates(
    class_i: list[ParsedEpitope], class_ii: list[ParsedEpitope]
) -> list[TopCandidate]:
    # Best binder per (peptide, class) combination.
    by_peptide: dict[tuple[str, str], ParsedEpitope] = {}
    for entry in class_i + class_ii:
        key = (entry.peptide, entry.mhc_class)
        existing = by_peptide.get(key)
        if existing is None or entry.ic50 < existing.ic50:
            by_peptide[key] = entry

    ranked = sorted(by_peptide.values(), key=lambda e: e.ic50)[:TOP_CANDIDATES_LIMIT]
    out: list[TopCandidate] = []
    for entry in ranked:
        agretopicity: Optional[float] = None
        if entry.wt_ic50 and entry.wt_ic50 > 0 and entry.ic50 > 0:
            agretopicity = round(entry.wt_ic50 / entry.ic50, 1)
        out.append(
            TopCandidate(
                seq=entry.peptide,
                gene=entry.gene,
                mut=entry.mutation,
                length=entry.length,
                **{"class": entry.mhc_class},
                allele=entry.allele,
                ic50=entry.ic50,
                wt_ic50=entry.wt_ic50,
                agretopicity=agretopicity,
                vaf=entry.vaf,
                tpm=entry.tpm,
                cancer_gene=entry.gene.upper() in COMMON_CANCER_GENES,
                strong=entry.ic50 < STRONG_BINDER_NM,
            )
        )
    return out


def _count_annotated_variants(path: Path) -> tuple[int, int]:
    """Return (total, protein_changing) by scanning the annotated VCF CSQ field.

    Cheap line-scan — good enough for the funnel hint; the frontend doesn't use
    these counts to gate anything.
    """
    from app.services.variant_calling import _open_vcf  # type: ignore

    total = 0
    protein_changing = 0
    protein_terms = {
        "missense_variant",
        "frameshift_variant",
        "stop_gained",
        "stop_lost",
        "start_lost",
        "inframe_insertion",
        "inframe_deletion",
        "protein_altering_variant",
    }
    try:
        with _open_vcf(path) as handle:
            for line in handle:
                if line.startswith("#"):
                    continue
                fields = line.rstrip().split("\t")
                if len(fields) < 8:
                    continue
                filter_column = fields[6]
                if filter_column not in ("PASS", "."):
                    continue
                total += 1
                info_column = fields[7]
                if any(term in info_column for term in protein_terms):
                    protein_changing += 1
    except (FileNotFoundError, OSError):
        return 0, 0
    return total, protein_changing


def compute_neoantigen_metrics(
    inputs: NeoantigenInputs,
    *,
    class_i_all_path: Optional[Path],
    class_ii_all_path: Optional[Path],
    class_i_filtered_path: Optional[Path],
    class_ii_filtered_path: Optional[Path],
) -> NeoantigenMetricsResponse:
    class_i = _parse_all_epitopes(class_i_all_path, "I") if class_i_all_path else []
    class_ii = _parse_all_epitopes(class_ii_all_path, "II") if class_ii_all_path else []

    # Count each peptide once per class for buckets.
    best_per_peptide: dict[tuple[str, str], float] = {}
    for entry in class_i + class_ii:
        key = (entry.peptide, entry.mhc_class)
        existing = best_per_peptide.get(key)
        if existing is None or entry.ic50 < existing:
            best_per_peptide[key] = entry.ic50

    tier_counts: dict[BindingTier, int] = defaultdict(int)
    for ic50 in best_per_peptide.values():
        tier_counts[_bucket_for_ic50(ic50)] += 1

    total_peptides = len(best_per_peptide)

    # Filtered rows = pVACseq's official "passed" list. Fall back to our own
    # threshold if the file is missing.
    filtered_class_i = _parse_all_epitopes(class_i_filtered_path, "I") if class_i_filtered_path else []
    filtered_class_ii = _parse_all_epitopes(class_ii_filtered_path, "II") if class_ii_filtered_path else []
    if not filtered_class_i and not filtered_class_ii:
        filtered_class_i = [e for e in class_i if e.ic50 < BINDING_THRESHOLD_NM]
        filtered_class_ii = [e for e in class_ii if e.ic50 < BINDING_THRESHOLD_NM]

    # Unique peptides per class in the filtered set
    unique_class_i = {e.peptide for e in filtered_class_i}
    unique_class_ii = {e.peptide for e in filtered_class_ii}
    visible = len(unique_class_i) + len(unique_class_ii)

    annotated_total, protein_changing = _count_annotated_variants(inputs.annotated_vcf)

    funnel = [
        FunnelStep(
            label="Annotated variants",
            count=annotated_total,
            hint="from stage 4",
        ),
        FunnelStep(
            label="Protein-changing",
            count=protein_changing,
            hint="missense + frameshift + stop gained",
        ),
        FunnelStep(
            label="Peptide fragments",
            count=total_peptides,
            hint="8–11 aa (class I) + 12–18 aa (class II)",
        ),
        FunnelStep(
            label="Bind one of the patient's alleles",
            count=visible,
            hint=f"IC50 < {int(BINDING_THRESHOLD_NM)} nM",
        ),
    ]

    heatmap = _build_heatmap(class_i, class_ii, inputs.patient_alleles)
    top = _build_top_candidates(filtered_class_i, filtered_class_ii)

    return NeoantigenMetricsResponse(
        pvacseq_version=_pvacseq_version(),
        netmhcpan_version=_netmhcpan_version() if inputs.class_i_alleles else None,
        netmhciipan_version=_netmhciipan_version() if inputs.class_ii_alleles else None,
        species_label=inputs.species_label,
        assembly=inputs.assembly,
        alleles=inputs.patient_alleles,
        annotated_variants=annotated_total,
        protein_changing_variants=protein_changing,
        peptides_generated=total_peptides,
        visible_candidates=visible,
        class_i_count=len(unique_class_i),
        class_ii_count=len(unique_class_ii),
        buckets=_tier_counts_to_buckets(tier_counts),
        heatmap=heatmap,
        funnel=funnel,
        top=top,
    )


# --------------------------------------------------------------------------- #
# Persistence
# --------------------------------------------------------------------------- #


def _artifact_content_type(kind: NeoantigenArtifactKind) -> str:
    if kind == NeoantigenArtifactKind.PVACSEQ_LOG:
        return "text/plain"
    return "text/tab-separated-values"


def persist_neoantigen_success(
    workspace_id: str,
    run_id: str,
    *,
    class_i_all: Optional[Path],
    class_i_filtered: Optional[Path],
    class_ii_all: Optional[Path],
    class_ii_filtered: Optional[Path],
    log_path: Optional[Path],
    metrics: NeoantigenMetricsResponse,
    command_log: list[str],
) -> None:
    artifacts: list[PipelineArtifactRecord] = []
    timestamp = utc_now()

    def _record(path: Optional[Path], kind: NeoantigenArtifactKind) -> None:
        if path is None or not path.exists():
            return
        artifacts.append(
            PipelineArtifactRecord(
                id=str(uuid.uuid4()),
                run_id=run_id,
                workspace_id=workspace_id,
                stage_id=NEOANTIGEN_STAGE_ID,
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

    _record(class_i_all, NeoantigenArtifactKind.ALL_EPITOPES_CLASS_I)
    _record(class_i_filtered, NeoantigenArtifactKind.FILTERED_CLASS_I)
    _record(class_ii_all, NeoantigenArtifactKind.ALL_EPITOPES_CLASS_II)
    _record(class_ii_filtered, NeoantigenArtifactKind.FILTERED_CLASS_II)
    _record(log_path, NeoantigenArtifactKind.PVACSEQ_LOG)

    command_log_text = "\n".join(command_log)

    with session_scope() as session:
        run = get_neoantigen_run_record(session, workspace_id, run_id)
        for artifact in artifacts:
            session.add(artifact)
            run.artifacts.append(artifact)
        run.status = NeoantigenRunStatus.COMPLETED.value
        run.progress = 100
        run.runtime_phase = None
        payload = _parse_payload(run.result_payload)
        payload["metrics"] = metrics.model_dump(mode="json", by_alias=True)
        run.result_payload = json.dumps(payload)
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


def run_neoantigen(workspace_id: str, run_id: str) -> None:
    command_log: list[str] = []
    clear_run_cancelled(run_id)
    clear_run_paused_pending(run_id)
    set_run_pid_dir(run_id, _derive_pid_dir_on_disk(workspace_id, run_id))
    try:
        inputs = start_neoantigen_run(workspace_id, run_id)

        def progress_cb(
            progress: int, phase: Optional[NeoantigenRuntimePhase] = None
        ) -> None:
            update_neoantigen_progress(workspace_id, run_id, progress, phase)

        class_i_dir = inputs.run_dir / "class-i"
        class_ii_dir = inputs.run_dir / "class-ii"

        progress_cb(10, NeoantigenRuntimePhase.GENERATING_FASTA)

        if inputs.class_i_alleles:
            progress_cb(20, NeoantigenRuntimePhase.RUNNING_CLASS_I)
            _run_pvacseq(
                inputs=inputs,
                alleles=inputs.class_i_alleles,
                predictor="NetMHCpan",
                output_dir=class_i_dir,
                epitope_flag="-e1",
                epitope_lengths=CLASS_I_EPITOPE_LENGTHS,
                command_log=command_log,
            )

        if inputs.class_ii_alleles:
            progress_cb(55, NeoantigenRuntimePhase.RUNNING_CLASS_II)
            _run_pvacseq(
                inputs=inputs,
                alleles=inputs.class_ii_alleles,
                predictor="NetMHCIIpan",
                output_dir=class_ii_dir,
                epitope_flag="-e2",
                epitope_lengths=CLASS_II_EPITOPE_LENGTHS,
                command_log=command_log,
            )

        progress_cb(85, NeoantigenRuntimePhase.PARSING)
        class_i_all = _find_tsv(class_i_dir, "*.all_epitopes.tsv")
        class_i_filtered = _find_tsv(class_i_dir, "*.filtered.tsv")
        class_ii_all = _find_tsv(class_ii_dir, "*.all_epitopes.tsv")
        class_ii_filtered = _find_tsv(class_ii_dir, "*.filtered.tsv")

        metrics = compute_neoantigen_metrics(
            inputs,
            class_i_all_path=class_i_all,
            class_ii_all_path=class_ii_all,
            class_i_filtered_path=class_i_filtered,
            class_ii_filtered_path=class_ii_filtered,
        )

        progress_cb(95, NeoantigenRuntimePhase.FINALIZING)
        log_path = inputs.run_dir / "pvacseq.log"
        if command_log:
            try:
                log_path.write_text("\n".join(command_log), encoding="utf-8")
            except OSError:
                log_path = None  # type: ignore[assignment]

        persist_neoantigen_success(
            workspace_id,
            run_id,
            class_i_all=class_i_all,
            class_i_filtered=class_i_filtered,
            class_ii_all=class_ii_all,
            class_ii_filtered=class_ii_filtered,
            log_path=log_path,
            metrics=metrics,
            command_log=command_log,
        )
    except NeoantigenCancelledError:
        if is_run_paused_pending(run_id):
            mark_neoantigen_run_paused(workspace_id, run_id)
        else:
            mark_neoantigen_run_cancelled(workspace_id, run_id)
    except subprocess.CalledProcessError as error:
        if is_run_paused_pending(run_id):
            mark_neoantigen_run_paused(workspace_id, run_id)
        elif is_run_cancelled(run_id):
            mark_neoantigen_run_cancelled(workspace_id, run_id)
        else:
            stderr_tail = (error.stderr or "").splitlines()[-20:]
            message = " | ".join(stderr_tail) if stderr_tail else str(error)
            mark_neoantigen_run_failed(
                workspace_id,
                run_id,
                f"{' '.join(error.cmd[:3])} failed: {message}",
            )
    except Exception as error:
        if is_run_paused_pending(run_id):
            mark_neoantigen_run_paused(workspace_id, run_id)
        elif is_run_cancelled(run_id):
            mark_neoantigen_run_cancelled(workspace_id, run_id)
        else:
            mark_neoantigen_run_failed(workspace_id, run_id, str(error))
    finally:
        clear_subprocess_registry(run_id)
        clear_run_cancelled(run_id)
        clear_run_paused_pending(run_id)
        clear_run_pid_dir(run_id)


def load_neoantigen_artifact_download(
    workspace_id: str, artifact_id: str
) -> NeoantigenArtifactDownload:
    with session_scope() as session:
        artifact = get_neoantigen_artifact_record(session, workspace_id, artifact_id)
        return NeoantigenArtifactDownload(
            filename=artifact.filename,
            local_path=resolve_app_data_path(artifact.local_path or artifact.storage_key),
            content_type=artifact.content_type,
        )
