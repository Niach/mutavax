import concurrent.futures
import gzip
import json
import os
import queue
import re
import shlex
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from urllib.request import urlopen
from typing import Any, Callable, Literal, Optional

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.db import session_scope
from app.runtime import get_app_data_root, get_reference_bundle_root, load_runtime_setting
from app.models.records import (
    PipelineArtifactRecord,
    PipelineRunRecord,
    WorkspaceRecord,
)
from app.models.schemas import (
    AlignmentArtifactKind,
    AlignmentArtifactResponse,
    AlignmentLaneMetricsResponse,
    AlignmentRuntimePhase,
    AlignmentRunResponse,
    AlignmentRunStatus,
    AlignmentStageStatus,
    AlignmentStageSummaryResponse,
    AnalysisAssayType,
    ChunkProgressPhase,
    ChunkProgressStateResponse,
    PipelineStageId,
    QcVerdict,
    ReadPair,
    ReferencePreset,
    SampleLane,
    WorkspaceAnalysisProfileResponse,
)
from app.services.workspace_store import (
    LANES,
    PAIRED_OUTPUT_REQUIRED_ISSUE,
    default_reference_preset_for_species,
    get_workspace_record,
    isoformat,
    latest_batch_for_lane,
    ready_canonical_files_for_batch,
    sanitize_filename,
    serialize_analysis_profile,
    summarize_workspace_ingestion,
    utc_now,
    workspace_file_access_path,
    managed_alignment_artifact_path,
)

ALIGNMENT_STAGE_ID = PipelineStageId.ALIGNMENT.value
REFERENCE_LABELS = {
    ReferencePreset.GRCH38: "GRCh38",
    ReferencePreset.CANFAM4: "CanFam4",
    ReferencePreset.FELCAT9: "felCat9",
}
REFERENCE_ENV_VARS = {
    ReferencePreset.GRCH38: "REFERENCE_GRCH38_FASTA",
    ReferencePreset.CANFAM4: "REFERENCE_CANFAM4_FASTA",
    ReferencePreset.FELCAT9: "REFERENCE_FELCAT9_FASTA",
}
FLAGSTAT_COUNT_PATTERN = re.compile(r"^(?P<count>\d+)\s+\+\s+\d+\s+(?P<label>.+)$")
PERCENT_PATTERN = re.compile(r"\((?P<percent>[\d.]+)%")


@dataclass(frozen=True)
class ReferenceSourceSpec:
    download_url: str
    checksum_url: str
    checksum_type: str
    checksum_filename: str


@dataclass
class ReferenceConfig:
    preset: ReferencePreset
    label: str
    fasta_path: Path
    override: Optional[str] = None
    requires_bootstrap: bool = False
    uses_env_path: bool = False


@dataclass
class AlignmentLaneInput:
    sample_lane: SampleLane
    r1_path: Path
    r2_path: Path
    r1_filename: str
    r2_filename: str


@dataclass
class AlignmentJobInputs:
    workspace_id: str
    workspace_display_name: str
    species: str
    assay_type: AnalysisAssayType
    reference: ReferenceConfig
    lanes: dict[SampleLane, AlignmentLaneInput]


@dataclass
class LaneExecutionOutput:
    sample_lane: SampleLane
    metrics: AlignmentLaneMetricsResponse
    artifact_paths: dict[AlignmentArtifactKind, Path]
    command_log: list[str]


@dataclass
class AlignmentArtifactDownload:
    filename: str
    local_path: Path
    content_type: Optional[str]


class AlignmentArtifactNotFoundError(FileNotFoundError):
    pass


REFERENCE_SOURCES = {
    ReferencePreset.GRCH38: ReferenceSourceSpec(
        download_url=(
            "https://ftp.ensembl.org/pub/current_fasta/homo_sapiens/dna/"
            "Homo_sapiens.GRCh38.dna.primary_assembly.fa.gz"
        ),
        checksum_url=(
            "https://ftp.ensembl.org/pub/current_fasta/homo_sapiens/dna/CHECKSUMS"
        ),
        checksum_type="sum",
        checksum_filename="Homo_sapiens.GRCh38.dna.primary_assembly.fa.gz",
    ),
    ReferencePreset.CANFAM4: ReferenceSourceSpec(
        download_url="https://hgdownload.soe.ucsc.edu/goldenPath/canFam4/bigZips/canFam4.fa.gz",
        checksum_url="https://hgdownload.soe.ucsc.edu/goldenPath/canFam4/bigZips/md5sum.txt",
        checksum_type="md5",
        checksum_filename="canFam4.fa.gz",
    ),
    ReferencePreset.FELCAT9: ReferenceSourceSpec(
        download_url="https://hgdownload.soe.ucsc.edu/goldenPath/felCat9/bigZips/felCat9.fa.gz",
        checksum_url="https://hgdownload.soe.ucsc.edu/goldenPath/felCat9/bigZips/md5sum.txt",
        checksum_type="md5",
        checksum_filename="felCat9.fa.gz",
    ),
}


def default_reference_path(preset: ReferencePreset) -> Path:
    return get_reference_bundle_root() / preset.value / "genome.fa"


def resolve_reference_config(
    species: str,
    analysis_profile: WorkspaceAnalysisProfileResponse,
) -> ReferenceConfig:
    preset = analysis_profile.reference_preset or default_reference_preset_for_species(
        species
    )

    if analysis_profile.reference_override:
        candidate = Path(analysis_profile.reference_override).expanduser()
        if not candidate.exists():
            raise ValueError(f"Reference override does not exist: {candidate}")
        return ReferenceConfig(
            preset=preset,
            label=f"Custom reference ({candidate.name})",
            fasta_path=candidate.resolve(),
            override=str(candidate),
            requires_bootstrap=False,
            uses_env_path=False,
        )

    configured = os.getenv(REFERENCE_ENV_VARS[preset])
    candidate = (
        Path(configured).expanduser()
        if configured
        else default_reference_path(preset)
    )
    return ReferenceConfig(
        preset=preset,
        label=REFERENCE_LABELS[preset],
        fasta_path=candidate,
        override=None,
        requires_bootstrap=not configured and not candidate.exists(),
        uses_env_path=bool(configured),
    )


def quote_command(command: list[str]) -> str:
    return " ".join(shlex.quote(part) for part in command)


def artifact_download_path(workspace_id: str, artifact_id: str) -> str:
    return f"/api/workspaces/{workspace_id}/alignment/artifacts/{artifact_id}/download"


def checksum_line_matches_filename(parts: list[str], filename: str) -> bool:
    for token in parts[1:]:
        if token.lstrip("*") == filename:
            return True
    return False


def parse_remote_checksum(spec: ReferenceSourceSpec) -> str:
    with urlopen(spec.checksum_url, timeout=60) as response:
        text = response.read().decode("utf-8", "replace")

    for line in text.splitlines():
        parts = line.strip().split()
        if not parts or not checksum_line_matches_filename(
            parts, spec.checksum_filename
        ):
            continue
        if spec.checksum_type == "md5":
            return parts[0]
        if spec.checksum_type in {"sum", "cksum"} and len(parts) >= 2:
            return f"{parts[0]} {parts[1]}"

    raise RuntimeError(
        f"Unable to find checksum metadata for {spec.checksum_filename}"
    )


def compute_local_checksum(path: Path, checksum_type: str) -> str:
    if checksum_type == "md5":
        command = ["md5sum", str(path)]
        completed = subprocess.run(command, check=True, capture_output=True, text=True)
        return completed.stdout.strip().split()[0]

    if checksum_type in {"sum", "cksum"}:
        command = [checksum_type, str(path)]
        completed = subprocess.run(command, check=True, capture_output=True, text=True)
        parts = completed.stdout.strip().split()
        return f"{parts[0]} {parts[1]}"

    raise ValueError(f"Unsupported checksum type: {checksum_type}")


def ensure_download_verified(path: Path, spec: ReferenceSourceSpec) -> None:
    expected = parse_remote_checksum(spec)
    actual = compute_local_checksum(path, spec.checksum_type)
    if actual != expected:
        raise RuntimeError(
            "Reference download verification failed for "
            f"{path.name}. Expected {expected}, got {actual}."
        )


def strobealign_index_exists(reference_path: Path) -> bool:
    return any(reference_path.parent.glob(f"{reference_path.name}.r*.sti"))


def ensure_reference_indices(reference_path: Path) -> None:
    aligner_binary = os.getenv("ALIGNMENT_STROBEALIGN_BINARY", "strobealign")
    samtools_binary = os.getenv("SAMTOOLS_BINARY", "samtools")

    if not reference_path.exists():
        raise FileNotFoundError(f"Reference FASTA is not available: {reference_path}")

    if not reference_path.with_name(f"{reference_path.name}.fai").exists():
        subprocess.run(
            [samtools_binary, "faidx", str(reference_path)],
            check=True,
            capture_output=True,
            text=True,
        )

    if not strobealign_index_exists(reference_path):
        # Local import to avoid a service-layer import cycle.
        from app.services.tool_preflight import verify_memory_for_strobealign_index

        verify_memory_for_strobealign_index()
        subprocess.run(
            [aligner_binary, "--create-index", "-r", "150", str(reference_path)],
            check=True,
            capture_output=True,
            text=True,
        )


def bootstrap_reference_bundle(reference: ReferenceConfig) -> Path:
    preset_root = get_reference_bundle_root() / reference.preset.value
    preset_root.mkdir(parents=True, exist_ok=True)
    lock_path = preset_root / ".bootstrap.lock"
    archive_path = preset_root / "source.fa.gz"
    temp_archive = preset_root / "source.fa.gz.part"
    temp_fasta = preset_root / "genome.fa.part"
    final_fasta = preset_root / "genome.fa"

    with lock_path.open("w", encoding="utf-8") as lock_handle:
        import fcntl

        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
        if final_fasta.exists():
            ensure_reference_indices(final_fasta)
            return final_fasta

        spec = REFERENCE_SOURCES[reference.preset]
        with urlopen(spec.download_url, timeout=120) as response, temp_archive.open("wb") as destination:
            shutil.copyfileobj(response, destination)
        ensure_download_verified(temp_archive, spec)
        temp_archive.replace(archive_path)

        with gzip.open(archive_path, "rb") as source_handle, temp_fasta.open("wb") as destination:
            shutil.copyfileobj(source_handle, destination)
        temp_fasta.replace(final_fasta)
        ensure_reference_indices(final_fasta)
        return final_fasta


def ensure_reference_ready(reference: ReferenceConfig) -> Path:
    if reference.override or reference.uses_env_path:
        if not reference.fasta_path.exists():
            raise FileNotFoundError(
                f"{reference.label} reference FASTA is not available at {reference.fasta_path}."
            )
        ensure_reference_indices(reference.fasta_path)
        return reference.fasta_path

    if reference.fasta_path.exists():
        ensure_reference_indices(reference.fasta_path)
        return reference.fasta_path

    if not reference.requires_bootstrap:
        raise FileNotFoundError(
            f"{reference.label} reference FASTA is not available at {reference.fasta_path}."
        )
    return bootstrap_reference_bundle(reference)


def serialize_alignment_artifact(
    record: PipelineArtifactRecord,
) -> AlignmentArtifactResponse:
    return AlignmentArtifactResponse(
        id=record.id,
        artifact_kind=AlignmentArtifactKind(record.artifact_kind),
        sample_lane=SampleLane(record.sample_lane) if record.sample_lane else None,
        filename=record.filename,
        size_bytes=record.size_bytes,
        download_path=artifact_download_path(record.workspace_id, record.id),
        local_path=record.local_path or record.storage_key,
    )


def parse_alignment_result_payload(
    payload_text: Optional[str],
) -> dict[SampleLane, AlignmentLaneMetricsResponse]:
    if not payload_text:
        return {}

    try:
        payload = json.loads(payload_text)
    except json.JSONDecodeError:
        return {}

    lane_metrics: dict[SampleLane, AlignmentLaneMetricsResponse] = {}
    for lane_value, metrics in (payload.get("lane_metrics") or {}).items():
        try:
            sample_lane = SampleLane(lane_value)
        except ValueError:
            continue
        lane_metrics[sample_lane] = AlignmentLaneMetricsResponse(
            sample_lane=sample_lane,
            total_reads=int(metrics.get("total_reads", 0)),
            mapped_reads=int(metrics.get("mapped_reads", 0)),
            mapped_percent=float(metrics.get("mapped_percent", 0.0)),
            properly_paired_percent=(
                float(metrics["properly_paired_percent"])
                if metrics.get("properly_paired_percent") is not None
                else None
            ),
            duplicate_percent=(
                float(metrics["duplicate_percent"])
                if metrics.get("duplicate_percent") is not None
                else None
            ),
            mean_insert_size=(
                float(metrics["mean_insert_size"])
                if metrics.get("mean_insert_size") is not None
                else None
            ),
        )
    return lane_metrics


def serialize_alignment_run(
    record: PipelineRunRecord,
) -> AlignmentRunResponse:
    lane_metrics = parse_alignment_result_payload(record.result_payload)
    chunk_progress_snapshot = get_chunk_progress_snapshot(record.id)
    chunk_progress: dict[SampleLane, ChunkProgressStateResponse] = {}
    for lane_value, state in chunk_progress_snapshot.items():
        try:
            lane_enum = SampleLane(lane_value)
        except ValueError:
            continue
        chunk_progress[lane_enum] = ChunkProgressStateResponse(
            phase=ChunkProgressPhase(state.phase),
            total_chunks=state.total_chunks,
            completed_chunks=state.completed_chunks,
            active_chunks=state.active_chunks,
        )
    return AlignmentRunResponse(
        id=record.id,
        status=AlignmentRunStatus(record.status),
        progress=record.progress / 100,
        assay_type=AnalysisAssayType(record.assay_type) if record.assay_type else None,
        reference_preset=(
            ReferencePreset(record.reference_preset)
            if record.reference_preset
            else None
        ),
        reference_override=record.reference_override,
        reference_label=record.reference_label,
        runtime_phase=(
            AlignmentRuntimePhase(record.runtime_phase)
            if record.runtime_phase
            else None
        ),
        qc_verdict=QcVerdict(record.qc_verdict) if record.qc_verdict else None,
        created_at=isoformat(record.created_at),
        updated_at=isoformat(record.updated_at),
        started_at=isoformat(record.started_at) if record.started_at else None,
        completed_at=isoformat(record.completed_at) if record.completed_at else None,
        blocking_reason=record.blocking_reason,
        error=record.error,
        command_log=record.command_log.splitlines() if record.command_log else [],
        lane_metrics=lane_metrics,
        chunk_progress=chunk_progress,
        artifacts=[serialize_alignment_artifact(artifact) for artifact in record.artifacts],
    )


def get_alignment_run_query():
    return select(PipelineRunRecord).options(
        selectinload(PipelineRunRecord.artifacts),
        selectinload(PipelineRunRecord.workspace),
    )


def get_latest_alignment_run(
    session,
    workspace_id: str,
) -> Optional[PipelineRunRecord]:
    return session.scalar(
        get_alignment_run_query()
        .where(
            PipelineRunRecord.workspace_id == workspace_id,
            PipelineRunRecord.stage_id == ALIGNMENT_STAGE_ID,
        )
        .order_by(PipelineRunRecord.created_at.desc())
        .limit(1)
    )


def get_alignment_run_record(
    session,
    workspace_id: str,
    run_id: str,
) -> PipelineRunRecord:
    run = session.scalar(
        get_alignment_run_query().where(
            PipelineRunRecord.id == run_id,
            PipelineRunRecord.workspace_id == workspace_id,
            PipelineRunRecord.stage_id == ALIGNMENT_STAGE_ID,
        )
    )
    if run is None:
        raise FileNotFoundError(f"Alignment run {run_id} not found")
    return run


def get_alignment_artifact_record(
    session,
    workspace_id: str,
    artifact_id: str,
) -> PipelineArtifactRecord:
    artifact = session.scalar(
        select(PipelineArtifactRecord).where(
            PipelineArtifactRecord.id == artifact_id,
            PipelineArtifactRecord.workspace_id == workspace_id,
            PipelineArtifactRecord.stage_id == ALIGNMENT_STAGE_ID,
        )
    )
    if artifact is None:
        raise AlignmentArtifactNotFoundError(
            f"Alignment artifact {artifact_id} not found"
        )
    return artifact


def latest_ingestion_input_timestamp(workspace: WorkspaceRecord):
    timestamps = []
    for sample_lane in LANES:
        batch = latest_batch_for_lane(workspace, sample_lane)
        if batch is not None:
            timestamps.append(batch.updated_at)
    return max(timestamps) if timestamps else None


def profile_matches_run(
    analysis_profile: WorkspaceAnalysisProfileResponse,
    run: PipelineRunRecord,
) -> bool:
    assay_value = analysis_profile.assay_type.value if analysis_profile.assay_type else None
    preset_value = (
        analysis_profile.reference_preset.value
        if analysis_profile.reference_preset
        else None
    )
    return (
        run.assay_type == assay_value
        and run.reference_preset == preset_value
        and (run.reference_override or None) == (analysis_profile.reference_override or None)
    )


def stale_alignment_reason(
    workspace: WorkspaceRecord,
    latest_run: Optional[PipelineRunRecord],
    analysis_profile: WorkspaceAnalysisProfileResponse,
) -> Optional[str]:
    if latest_run is None:
        return None

    if latest_run.status in {
        AlignmentRunStatus.PENDING.value,
        AlignmentRunStatus.RUNNING.value,
    }:
        return None

    if not profile_matches_run(analysis_profile, latest_run):
        return "Analysis settings changed. Rerun alignment to refresh the BAM outputs."

    latest_input_at = latest_ingestion_input_timestamp(workspace)
    if (
        latest_input_at is not None
        and latest_run.completed_at is not None
        and latest_input_at > latest_run.completed_at
    ):
        return "Sequencing inputs changed. Rerun alignment before moving on."

    return None


def has_required_alignment_artifacts(run: PipelineRunRecord) -> bool:
    required = {
        (SampleLane.TUMOR.value, AlignmentArtifactKind.BAM.value),
        (SampleLane.TUMOR.value, AlignmentArtifactKind.BAI.value),
        (SampleLane.NORMAL.value, AlignmentArtifactKind.BAM.value),
        (SampleLane.NORMAL.value, AlignmentArtifactKind.BAI.value),
    }
    present = {
        (artifact.sample_lane, artifact.artifact_kind)
        for artifact in run.artifacts
    }
    return required.issubset(present)


def classify_lane_qc(metrics: AlignmentLaneMetricsResponse) -> QcVerdict:
    if metrics.mapped_percent < 50:
        return QcVerdict.FAIL
    if (
        metrics.duplicate_percent is not None
        and metrics.duplicate_percent > 60
    ):
        return QcVerdict.WARN
    if metrics.mapped_percent >= 85 and (
        metrics.properly_paired_percent is not None
        and metrics.properly_paired_percent >= 75
    ):
        return QcVerdict.PASS
    return QcVerdict.WARN


def classify_run_qc(
    lane_metrics: dict[SampleLane, AlignmentLaneMetricsResponse],
    *,
    has_required_artifacts: bool,
) -> QcVerdict:
    if not has_required_artifacts:
        return QcVerdict.FAIL

    verdicts = [classify_lane_qc(metrics) for metrics in lane_metrics.values()]
    if any(verdict == QcVerdict.FAIL for verdict in verdicts):
        return QcVerdict.FAIL
    if all(verdict == QcVerdict.PASS for verdict in verdicts):
        return QcVerdict.PASS
    return QcVerdict.WARN


def build_alignment_stage_summary(
    workspace: WorkspaceRecord,
    latest_run: Optional[PipelineRunRecord],
) -> AlignmentStageSummaryResponse:
    ingestion_summary = summarize_workspace_ingestion(workspace)
    analysis_profile = serialize_analysis_profile(workspace)
    latest_run_response = (
        serialize_alignment_run(latest_run) if latest_run is not None else None
    )
    lane_metrics = (
        latest_run_response.lane_metrics if latest_run_response else {}
    )
    artifacts = latest_run_response.artifacts if latest_run_response else []
    top_level_metrics = {
        SampleLane.TUMOR: lane_metrics.get(SampleLane.TUMOR),
        SampleLane.NORMAL: lane_metrics.get(SampleLane.NORMAL),
    }

    if not ingestion_summary.ready_for_alignment:
        return AlignmentStageSummaryResponse(
            workspace_id=workspace.id,
            status=AlignmentStageStatus.BLOCKED,
            blocking_reason="Complete tumor and normal ingestion first.",
            analysis_profile=analysis_profile,
            latest_run=latest_run_response,
            qc_verdict=latest_run_response.qc_verdict if latest_run_response else None,
            lane_metrics=top_level_metrics,
            artifacts=artifacts,
        )

    if analysis_profile.assay_type is None:
        return AlignmentStageSummaryResponse(
            workspace_id=workspace.id,
            status=AlignmentStageStatus.BLOCKED,
            blocking_reason="Choose WGS or WES before running alignment.",
            analysis_profile=analysis_profile,
            latest_run=latest_run_response,
            qc_verdict=latest_run_response.qc_verdict if latest_run_response else None,
            lane_metrics=top_level_metrics,
            artifacts=artifacts,
        )

    try:
        reference = resolve_reference_config(workspace.species, analysis_profile)
    except ValueError as error:
        return AlignmentStageSummaryResponse(
            workspace_id=workspace.id,
            status=AlignmentStageStatus.BLOCKED,
            blocking_reason=str(error),
            analysis_profile=analysis_profile,
            latest_run=latest_run_response,
            qc_verdict=latest_run_response.qc_verdict if latest_run_response else None,
            lane_metrics=top_level_metrics,
            artifacts=artifacts,
        )

    if reference.uses_env_path and not reference.fasta_path.exists():
        return AlignmentStageSummaryResponse(
            workspace_id=workspace.id,
            status=AlignmentStageStatus.BLOCKED,
            blocking_reason=(
                f"{reference.label} reference FASTA is not available at {reference.fasta_path}."
            ),
            analysis_profile=analysis_profile,
            latest_run=latest_run_response,
            qc_verdict=latest_run_response.qc_verdict if latest_run_response else None,
            lane_metrics=top_level_metrics,
            artifacts=artifacts,
        )

    if latest_run is None:
        return AlignmentStageSummaryResponse(
            workspace_id=workspace.id,
            status=AlignmentStageStatus.READY,
            analysis_profile=analysis_profile,
            lane_metrics=top_level_metrics,
            artifacts=artifacts,
        )

    if latest_run.status in {
        AlignmentRunStatus.PENDING.value,
        AlignmentRunStatus.RUNNING.value,
    }:
        return AlignmentStageSummaryResponse(
            workspace_id=workspace.id,
            status=AlignmentStageStatus.RUNNING,
            analysis_profile=analysis_profile,
            latest_run=latest_run_response,
            qc_verdict=latest_run_response.qc_verdict if latest_run_response else None,
            lane_metrics=top_level_metrics,
            artifacts=artifacts,
        )

    stale_reason = stale_alignment_reason(workspace, latest_run, analysis_profile)
    if stale_reason is not None:
        return AlignmentStageSummaryResponse(
            workspace_id=workspace.id,
            status=AlignmentStageStatus.READY,
            blocking_reason=stale_reason,
            analysis_profile=analysis_profile,
            latest_run=latest_run_response,
            qc_verdict=latest_run_response.qc_verdict if latest_run_response else None,
            lane_metrics=top_level_metrics,
            artifacts=artifacts,
        )

    if latest_run.status == AlignmentRunStatus.FAILED.value:
        return AlignmentStageSummaryResponse(
            workspace_id=workspace.id,
            status=AlignmentStageStatus.FAILED,
            blocking_reason=latest_run.error or latest_run.blocking_reason,
            analysis_profile=analysis_profile,
            latest_run=latest_run_response,
            qc_verdict=latest_run_response.qc_verdict if latest_run_response else None,
            lane_metrics=top_level_metrics,
            artifacts=artifacts,
        )

    required_artifacts_ready = has_required_alignment_artifacts(latest_run)
    ready_for_variant = (
        latest_run.qc_verdict != QcVerdict.FAIL.value and required_artifacts_ready
    )
    if latest_run.qc_verdict == QcVerdict.FAIL.value or not required_artifacts_ready:
        return AlignmentStageSummaryResponse(
            workspace_id=workspace.id,
            status=AlignmentStageStatus.FAILED,
            blocking_reason=latest_run.blocking_reason
            or "Alignment completed, but the QC verdict failed.",
            analysis_profile=analysis_profile,
            latest_run=latest_run_response,
            qc_verdict=latest_run_response.qc_verdict if latest_run_response else None,
            lane_metrics=top_level_metrics,
            artifacts=artifacts,
        )

    return AlignmentStageSummaryResponse(
        workspace_id=workspace.id,
        status=AlignmentStageStatus.COMPLETED,
        analysis_profile=analysis_profile,
        latest_run=latest_run_response,
        qc_verdict=latest_run_response.qc_verdict if latest_run_response else None,
        ready_for_variant_calling=ready_for_variant,
        lane_metrics=top_level_metrics,
        artifacts=artifacts,
    )


def load_alignment_stage_summary(
    workspace_id: str,
) -> AlignmentStageSummaryResponse:
    with session_scope() as session:
        workspace = get_workspace_record(session, workspace_id)
        latest_run = get_latest_alignment_run(session, workspace_id)
        return build_alignment_stage_summary(workspace, latest_run)


def create_alignment_run(
    workspace_id: str,
) -> AlignmentStageSummaryResponse:
    created_run_id: Optional[str] = None
    with session_scope() as session:
        workspace = get_workspace_record(session, workspace_id)
        latest_run = get_latest_alignment_run(session, workspace_id)

        if latest_run and latest_run.status in {
            AlignmentRunStatus.PENDING.value,
            AlignmentRunStatus.RUNNING.value,
        }:
            raise ValueError("Alignment is already running for this workspace.")

        stage_summary = build_alignment_stage_summary(workspace, latest_run)
        if stage_summary.status == AlignmentStageStatus.BLOCKED:
            raise ValueError(stage_summary.blocking_reason or "Alignment is blocked.")

        analysis_profile = serialize_analysis_profile(workspace)
        reference = resolve_reference_config(workspace.species, analysis_profile)
        timestamp = utc_now()
        run = PipelineRunRecord(
            id=str(uuid.uuid4()),
            workspace_id=workspace.id,
            stage_id=ALIGNMENT_STAGE_ID,
            status=AlignmentRunStatus.PENDING.value,
            progress=0,
            qc_verdict=None,
            assay_type=analysis_profile.assay_type.value if analysis_profile.assay_type else None,
            reference_preset=analysis_profile.reference_preset.value if analysis_profile.reference_preset else None,
            reference_override=analysis_profile.reference_override,
            reference_label=reference.label,
            reference_path=str(reference.fasta_path),
            runtime_phase=AlignmentRuntimePhase.PREPARING_REFERENCE.value,
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
        summary = build_alignment_stage_summary(workspace, run)

    if created_run_id is None:
        raise RuntimeError("Alignment run creation did not produce an id")

    enqueue_alignment_run(workspace_id, created_run_id)
    return summary


def rerun_alignment(
    workspace_id: str,
) -> AlignmentStageSummaryResponse:
    return create_alignment_run(workspace_id)


def mark_alignment_run_failed(
    workspace_id: str,
    run_id: str,
    error_message: str,
) -> None:
    with session_scope() as session:
        run = get_alignment_run_record(session, workspace_id, run_id)
        run.status = AlignmentRunStatus.FAILED.value
        run.progress = 100
        run.error = error_message
        run.blocking_reason = error_message
        run.runtime_phase = None
        run.updated_at = utc_now()
        run.completed_at = run.updated_at
        run.workspace.updated_at = run.updated_at
        session.add(run)
        session.add(run.workspace)


def enqueue_alignment_run(
    workspace_id: str,
    run_id: str,
) -> None:
    from app.services import background

    try:
        background.submit(run_alignment, workspace_id, run_id)
    except Exception as error:
        mark_alignment_run_failed(
            workspace_id,
            run_id,
            f"Unable to queue alignment: {error}",
        )


def build_read_group(
    workspace_display_name: str, workspace_id: str, sample_lane: SampleLane
) -> list[str]:
    sample = re.sub(r"[^A-Za-z0-9_.-]+", "-", workspace_display_name.strip()) or workspace_id
    rg_id = f"{workspace_id}.{sample_lane.value}"
    rg_sample = f"{sample}.{sample_lane.value}"
    return [
        f"--rg-id={rg_id}",
        f"--rg=SM:{rg_sample}",
        f"--rg=LB:{workspace_id}",
        "--rg=PL:ILLUMINA",
        f"--rg=PU:{rg_id}",
    ]


def run_command(command: list[str]) -> str:
    completed = subprocess.run(command, check=True, capture_output=True, text=True)
    stderr = completed.stderr.strip()
    return stderr


def _setting_int(key: str, env_var: str, default: int) -> int:
    value = load_runtime_setting(key)
    if value is not None:
        try:
            return max(1, int(value))
        except (TypeError, ValueError):
            pass
    env = os.getenv(env_var)
    if env:
        try:
            return max(1, int(env))
        except ValueError:
            pass
    return max(1, default)


def _setting_str(key: str, env_var: str, default: str) -> str:
    value = load_runtime_setting(key)
    if isinstance(value, str) and value.strip():
        return value.strip()
    env = os.getenv(env_var)
    if env:
        return env
    return default


def get_aligner_thread_count() -> int:
    cpu_count = os.cpu_count() or 4
    return _setting_int("aligner_threads", "ALIGNMENT_STROBEALIGN_THREADS", max(1, cpu_count - 4))


def get_samtools_thread_count() -> int:
    cpu_count = os.cpu_count() or 4
    return _setting_int("samtools_threads", "ALIGNMENT_SAMTOOLS_THREADS", max(1, cpu_count // 4))


def get_samtools_sort_thread_count() -> int:
    return _setting_int("samtools_sort_threads", "ALIGNMENT_SAMTOOLS_SORT_THREADS", 3)


def get_samtools_sort_memory() -> str:
    return _setting_str("samtools_sort_memory", "ALIGNMENT_SAMTOOLS_SORT_MEMORY", "2G")


def get_alignment_chunk_reads() -> int:
    value = load_runtime_setting("chunk_reads")
    if value is not None:
        try:
            return max(1_000_000, int(value))
        except (TypeError, ValueError):
            pass
    env = os.getenv("ALIGNMENT_CHUNK_READS")
    if env:
        try:
            return max(1_000_000, int(env))
        except ValueError:
            pass
    return 20_000_000


def get_alignment_chunk_parallelism() -> int:
    value = load_runtime_setting("chunk_parallelism")
    if value is not None:
        try:
            return max(1, min(8, int(value)))
        except (TypeError, ValueError):
            pass
    env = os.getenv("ALIGNMENT_CHUNK_PARALLELISM")
    if env:
        try:
            return max(1, min(8, int(env)))
        except ValueError:
            pass
    return 2


ChunkPhase = Literal["splitting", "aligning", "merging"]


@dataclass
class ChunkProgressState:
    phase: ChunkPhase = "splitting"
    total_chunks: int = 0
    completed_chunks: int = 0
    active_chunks: int = 0


_chunk_progress_lock = threading.Lock()
_chunk_progress_store: dict[str, dict[str, ChunkProgressState]] = {}


def record_chunk_progress(
    run_id: str,
    sample_lane: SampleLane,
    *,
    phase: ChunkPhase,
    total: int,
    completed: int,
    active: int,
) -> None:
    with _chunk_progress_lock:
        lane_states = _chunk_progress_store.setdefault(run_id, {})
        lane_states[sample_lane.value] = ChunkProgressState(
            phase=phase,
            total_chunks=total,
            completed_chunks=completed,
            active_chunks=active,
        )


def get_chunk_progress_snapshot(run_id: str) -> dict[str, ChunkProgressState]:
    with _chunk_progress_lock:
        lane_states = _chunk_progress_store.get(run_id)
        if not lane_states:
            return {}
        return {lane: ChunkProgressState(**state.__dict__) for lane, state in lane_states.items()}


def clear_chunk_progress(run_id: str) -> None:
    with _chunk_progress_lock:
        _chunk_progress_store.pop(run_id, None)


def _spawn_split_subprocess(
    *,
    r1_path: Path,
    r2_path: Path,
    chunk_dir: Path,
    reads_per_chunk: int,
) -> tuple[list[subprocess.Popen], list[str]]:
    """Launch pigz|split chains for R1 and R2 in the background, non-blocking.

    Returns the live Popen objects (caller must wait on them) plus the quoted
    command strings for the audit log.
    """
    chunk_dir.mkdir(parents=True, exist_ok=True)
    lines_per_chunk = reads_per_chunk * 4

    def _launch(src: Path, prefix: str) -> tuple[list[subprocess.Popen], list[list[str]]]:
        pigz_cmd = ["pigz", "-dc", str(src)]
        split_cmd = [
            "split",
            "-l",
            str(lines_per_chunk),
            "-d",
            "-a",
            "4",
            "--additional-suffix=.fastq.gz",
            "--filter=pigz -c -1 > $FILE",
            "-",
            str(chunk_dir / prefix),
        ]
        pigz_proc = subprocess.Popen(
            pigz_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        split_proc = subprocess.Popen(
            split_cmd,
            stdin=pigz_proc.stdout,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.STDOUT,
        )
        assert pigz_proc.stdout is not None
        pigz_proc.stdout.close()
        return [pigz_proc, split_proc], [pigz_cmd, split_cmd]

    procs: list[subprocess.Popen] = []
    commands: list[list[str]] = []

    try:
        r1_procs, r1_cmds = _launch(r1_path, "r1_")
        procs.extend(r1_procs)
        commands.extend(r1_cmds)
        r2_procs, r2_cmds = _launch(r2_path, "r2_")
        procs.extend(r2_procs)
        commands.extend(r2_cmds)
    except BaseException:
        for proc in procs:
            if proc.poll() is None:
                proc.kill()
                proc.wait()
        raise

    return procs, [quote_command(cmd) for cmd in commands]


def split_paired_fastq_into_chunks(
    *,
    r1_path: Path,
    r2_path: Path,
    chunk_dir: Path,
    reads_per_chunk: int,
) -> tuple[list[tuple[Path, Path]], list[str]]:
    """Split paired gzipped FASTQ into chunks of reads_per_chunk pairs each.

    Thin blocking wrapper around `_spawn_split_subprocess` that waits for the
    split to finish and returns the resulting chunk path pairs. Preserved for
    unit tests and as a simpler API where overlap isn't needed.
    """
    procs, commands = _spawn_split_subprocess(
        r1_path=r1_path,
        r2_path=r2_path,
        chunk_dir=chunk_dir,
        reads_per_chunk=reads_per_chunk,
    )

    try:
        for proc in procs:
            rc = proc.wait()
            if rc != 0:
                raise RuntimeError(
                    f"FASTQ split failed (rc={rc}): command={proc.args!r}"
                )
    except BaseException:
        for proc in procs:
            if proc.poll() is None:
                proc.kill()
                proc.wait()
        raise

    r1_chunks = sorted(chunk_dir.glob("r1_*.fastq.gz"))
    r2_chunks = sorted(chunk_dir.glob("r2_*.fastq.gz"))
    if len(r1_chunks) != len(r2_chunks):
        raise RuntimeError(
            f"FASTQ split produced mismatched chunk counts "
            f"({len(r1_chunks)} R1 vs {len(r2_chunks)} R2)"
        )
    if not r1_chunks:
        raise RuntimeError("FASTQ split produced no chunks (empty input?)")
    return list(zip(r1_chunks, r2_chunks)), commands


def _align_single_chunk(
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
) -> list[str]:
    aligner_stderr_path = output_path.with_suffix(output_path.suffix + ".strobealign.stderr.log")
    fixmate_stderr_path = output_path.with_suffix(output_path.suffix + ".fixmate.stderr.log")
    sort_stderr_path = output_path.with_suffix(output_path.suffix + ".samtools-sort.stderr.log")
    sort_tmp_prefix = output_path.with_suffix(output_path.suffix + ".sort-tmp")

    aligner_command = [
        aligner_binary,
        "-t",
        str(aligner_threads),
        *read_group_flags,
        str(reference_path),
        str(r1_path),
        str(r2_path),
    ]
    fixmate_command = [
        samtools_binary,
        "fixmate",
        "-m",
        "-u",
        "-@",
        "2",
        "-",
        "-",
    ]
    sort_command = [
        samtools_binary,
        "sort",
        "-@",
        str(sort_threads),
        "-m",
        sort_memory,
        "-T",
        str(sort_tmp_prefix),
        "-o",
        str(output_path),
    ]

    procs: list[subprocess.Popen] = []
    try:
        with aligner_stderr_path.open("wb") as aligner_stderr_handle, \
             fixmate_stderr_path.open("wb") as fixmate_stderr_handle, \
             sort_stderr_path.open("wb") as sort_stderr_handle:
            aligner_proc = subprocess.Popen(
                aligner_command,
                stdout=subprocess.PIPE,
                stderr=aligner_stderr_handle,
            )
            procs.append(aligner_proc)

            fixmate_proc = subprocess.Popen(
                fixmate_command,
                stdin=aligner_proc.stdout,
                stdout=subprocess.PIPE,
                stderr=fixmate_stderr_handle,
            )
            procs.append(fixmate_proc)
            assert aligner_proc.stdout is not None
            aligner_proc.stdout.close()

            sort_proc = subprocess.Popen(
                sort_command,
                stdin=fixmate_proc.stdout,
                stdout=subprocess.DEVNULL,
                stderr=sort_stderr_handle,
            )
            procs.append(sort_proc)
            assert fixmate_proc.stdout is not None
            fixmate_proc.stdout.close()

            sort_returncode = sort_proc.wait()
            fixmate_returncode = fixmate_proc.wait()
            aligner_returncode = aligner_proc.wait()
    except BaseException:
        for proc in procs:
            if proc.poll() is None:
                proc.kill()
                proc.wait()
        raise
    finally:
        for leftover in sort_tmp_prefix.parent.glob(f"{sort_tmp_prefix.name}.*.bam"):
            try:
                leftover.unlink()
            except OSError:
                pass

    if aligner_returncode != 0:
        aligner_text = aligner_stderr_path.read_text(errors="replace").strip()
        raise RuntimeError(
            f"strobealign failed (rc={aligner_returncode}): {aligner_text or '<empty>'}"
        )
    if fixmate_returncode != 0:
        fixmate_text = fixmate_stderr_path.read_text(errors="replace").strip()
        raise RuntimeError(
            f"samtools fixmate failed (rc={fixmate_returncode}): {fixmate_text or '<empty>'}"
        )
    if sort_returncode != 0:
        sort_text = sort_stderr_path.read_text(errors="replace").strip()
        raise RuntimeError(
            f"samtools sort failed (rc={sort_returncode}): {sort_text or '<empty>'}"
        )

    return [
        quote_command(aligner_command),
        quote_command(fixmate_command),
        quote_command(sort_command),
    ]


_CHUNK_WATCHER_POLL_SECONDS = 2.0
_CHUNK_RE = re.compile(r"^r1_(\d{4})\.fastq\.gz$")


def _chunk_ready_watcher(
    *,
    chunk_dir: Path,
    split_procs: list[subprocess.Popen],
    chunk_queue: "queue.Queue[Optional[tuple[int, Path, Path]]]",
    parallelism: int,
    on_split_complete: Callable[[int], None],
    on_chunk_discovered: Callable[[int], None],
    stop_event: threading.Event,
) -> None:
    """Poll chunk_dir for newly finished (r1_i, r2_i) pairs and enqueue them.

    A chunk is considered complete when both r1_i.fastq.gz and r2_i.fastq.gz
    exist and have been size-stable for one poll cycle. When all split procs
    exit, does one final sweep and pushes `parallelism` sentinel None values.
    """
    seen_complete: set[int] = set()
    candidate_sizes: dict[int, tuple[int, int]] = {}
    split_done = False

    while True:
        if stop_event.is_set():
            break

        r1_entries: dict[int, Path] = {}
        r2_entries: dict[int, Path] = {}
        try:
            for path in chunk_dir.iterdir():
                match = _CHUNK_RE.match(path.name)
                if match:
                    r1_entries[int(match.group(1))] = path
                    continue
                match = re.match(r"^r2_(\d{4})\.fastq\.gz$", path.name)
                if match:
                    r2_entries[int(match.group(1))] = path
        except FileNotFoundError:
            pass

        split_exit_rcs = [proc.poll() for proc in split_procs]
        all_split_exited = all(rc is not None for rc in split_exit_rcs)

        for idx in sorted(r1_entries):
            if idx in seen_complete:
                continue
            r1_chunk = r1_entries[idx]
            r2_chunk = r2_entries.get(idx)
            if r2_chunk is None:
                continue
            try:
                r1_size = r1_chunk.stat().st_size
                r2_size = r2_chunk.stat().st_size
            except FileNotFoundError:
                continue

            prev = candidate_sizes.get(idx)
            is_last_candidate = all_split_exited and idx == max(r1_entries)
            # A chunk is ready if: stable across two polls, OR split has exited
            # and a later chunk (idx+1) exists (so we know this one is flushed),
            # OR it's the last chunk and split has exited and size is stable.
            next_exists = (idx + 1) in r1_entries and (idx + 1) in r2_entries
            if prev == (r1_size, r2_size) and (next_exists or all_split_exited):
                seen_complete.add(idx)
                on_chunk_discovered(idx)
                chunk_queue.put((idx, r1_chunk, r2_chunk))
            elif next_exists and prev is None:
                # Fast path: if a later chunk already exists, this chunk's
                # writer has moved on. We still need one poll to confirm
                # nothing is actively appending.
                candidate_sizes[idx] = (r1_size, r2_size)
            else:
                candidate_sizes[idx] = (r1_size, r2_size)

        if all_split_exited and not split_done:
            split_done = True
            # Check split return codes
            for rc, proc in zip(split_exit_rcs, split_procs):
                if rc != 0:
                    raise RuntimeError(
                        f"FASTQ split failed (rc={rc}): command={proc.args!r}"
                    )
            on_split_complete(len(r1_entries))

            # One final sweep — catch any chunk we haven't enqueued yet
            for idx in sorted(r1_entries):
                if idx in seen_complete:
                    continue
                r1_chunk = r1_entries[idx]
                r2_chunk = r2_entries.get(idx)
                if r2_chunk is None:
                    continue
                seen_complete.add(idx)
                on_chunk_discovered(idx)
                chunk_queue.put((idx, r1_chunk, r2_chunk))

            # Signal end-of-stream to consumers
            for _ in range(parallelism):
                chunk_queue.put(None)
            return

        time.sleep(_CHUNK_WATCHER_POLL_SECONDS)


def run_chunked_strobealign_pipeline(
    *,
    reference_path: Path,
    read_group_flags: list[str],
    r1_path: Path,
    r2_path: Path,
    output_path: Path,
    aligner_binary: str,
    samtools_binary: str,
    chunk_dir: Path,
    chunk_reads: int,
    parallelism: int,
    aligner_threads_per_chunk: int,
    sort_threads_per_chunk: int,
    sort_memory_per_chunk: str,
    on_progress: Optional[Callable[[ChunkPhase, int, int, int], None]] = None,
    chunk_queue_buffer: int = 2,
) -> list[str]:
    """Chunked strobealign alignment orchestrator with producer/consumer overlap.

    Launches pigz|split as a background subprocess and a watcher thread that
    enqueues (r1_i, r2_i) pairs onto a bounded queue as they finish writing.
    A ThreadPoolExecutor of `parallelism` worker threads pulls pairs from the
    queue and runs `_align_single_chunk`. Once all chunks finish, merges the
    per-chunk coord-sorted BAMs into output_path.

    Returns the flat command log (split + per-chunk pipelines + merge).
    """
    chunk_dir.mkdir(parents=True, exist_ok=True)
    commands: list[str] = []

    def _emit(phase: ChunkPhase, total: int, completed: int, active: int) -> None:
        if on_progress is not None:
            try:
                on_progress(phase, total, completed, active)
            except Exception:
                pass

    _emit("splitting", 0, 0, 0)

    split_procs, split_commands = _spawn_split_subprocess(
        r1_path=r1_path,
        r2_path=r2_path,
        chunk_dir=chunk_dir,
        reads_per_chunk=chunk_reads,
    )
    commands.extend(split_commands)

    chunk_queue: "queue.Queue[Optional[tuple[int, Path, Path]]]" = queue.Queue(
        maxsize=max(1, parallelism) + max(0, chunk_queue_buffer)
    )
    progress_lock = threading.Lock()
    stop_event = threading.Event()
    completed_count = 0
    active_count = 0
    total_chunks_seen = 0
    total_chunks_final: Optional[int] = None
    chunk_commands_by_idx: dict[int, list[str]] = {}
    chunk_bam_by_idx: dict[int, Path] = {}

    def _on_chunk_discovered(idx: int) -> None:
        nonlocal total_chunks_seen
        with progress_lock:
            total_chunks_seen = max(total_chunks_seen, idx + 1)
            _emit("splitting", total_chunks_seen, completed_count, active_count)

    def _on_split_complete(final_count: int) -> None:
        nonlocal total_chunks_final
        with progress_lock:
            total_chunks_final = final_count
            _emit(
                "aligning",
                final_count,
                completed_count,
                active_count,
            )

    watcher_error: list[BaseException] = []

    def _watcher_wrapper() -> None:
        try:
            _chunk_ready_watcher(
                chunk_dir=chunk_dir,
                split_procs=split_procs,
                chunk_queue=chunk_queue,
                parallelism=max(1, parallelism),
                on_split_complete=_on_split_complete,
                on_chunk_discovered=_on_chunk_discovered,
                stop_event=stop_event,
            )
        except BaseException as error:
            watcher_error.append(error)
            # Unblock any waiting consumers on crash
            for _ in range(max(1, parallelism)):
                try:
                    chunk_queue.put_nowait(None)
                except queue.Full:
                    pass

    watcher_thread = threading.Thread(target=_watcher_wrapper, daemon=True)
    watcher_thread.start()

    def _worker() -> None:
        nonlocal completed_count, active_count
        while True:
            item = chunk_queue.get()
            if item is None:
                return
            idx, r1_chunk, r2_chunk = item
            chunk_bam = chunk_dir / f"chunk_{idx:04d}.coord-sorted.bam"

            with progress_lock:
                active_count += 1
                total = total_chunks_final or total_chunks_seen
                _emit(
                    "aligning" if total_chunks_final is not None else "splitting",
                    total,
                    completed_count,
                    active_count,
                )

            try:
                cmds = _align_single_chunk(
                    reference_path=reference_path,
                    read_group_flags=read_group_flags,
                    r1_path=r1_chunk,
                    r2_path=r2_chunk,
                    output_path=chunk_bam,
                    aligner_binary=aligner_binary,
                    samtools_binary=samtools_binary,
                    aligner_threads=aligner_threads_per_chunk,
                    sort_threads=sort_threads_per_chunk,
                    sort_memory=sort_memory_per_chunk,
                )
                with progress_lock:
                    chunk_commands_by_idx[idx] = cmds
                    chunk_bam_by_idx[idx] = chunk_bam
                for chunk_fastq in (r1_chunk, r2_chunk):
                    try:
                        chunk_fastq.unlink()
                    except OSError:
                        pass
            finally:
                with progress_lock:
                    active_count -= 1
                    completed_count += 1
                    total = total_chunks_final or total_chunks_seen
                    _emit(
                        "aligning" if total_chunks_final is not None else "splitting",
                        total,
                        completed_count,
                        active_count,
                    )

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, parallelism)) as executor:
            worker_futures = [
                executor.submit(_worker) for _ in range(max(1, parallelism))
            ]
            # Wait for watcher first (will push sentinels when split exits)
            watcher_thread.join()
            if watcher_error:
                stop_event.set()
                for future in worker_futures:
                    future.cancel()
                raise watcher_error[0]
            for future in worker_futures:
                future.result()
    except BaseException:
        stop_event.set()
        # Kill any surviving split procs
        for proc in split_procs:
            if proc.poll() is None:
                try:
                    proc.kill()
                    proc.wait()
                except Exception:
                    pass
        for leftover in chunk_dir.glob("chunk_*.coord-sorted.bam*"):
            try:
                leftover.unlink()
            except OSError:
                pass
        raise

    # Emit deterministic command log order
    for idx in sorted(chunk_commands_by_idx):
        commands.extend(chunk_commands_by_idx[idx])

    total_chunks = len(chunk_bam_by_idx)
    if total_chunks == 0:
        raise RuntimeError("Chunked alignment produced no chunks")
    chunk_bams = [chunk_bam_by_idx[idx] for idx in sorted(chunk_bam_by_idx)]

    _emit("merging", total_chunks, total_chunks, 0)

    merge_command = [
        samtools_binary,
        "merge",
        "-@",
        str(max(1, sort_threads_per_chunk * 2)),
        "-c",
        "-p",
        "-f",
        str(output_path),
        *[str(path) for path in chunk_bams],
    ]
    merge_stderr_path = output_path.with_suffix(output_path.suffix + ".samtools-merge.stderr.log")
    with merge_stderr_path.open("wb") as merge_stderr_handle:
        merge_proc = subprocess.run(
            merge_command,
            stdout=subprocess.DEVNULL,
            stderr=merge_stderr_handle,
        )
    if merge_proc.returncode != 0:
        merge_text = merge_stderr_path.read_text(errors="replace").strip()
        raise RuntimeError(
            f"samtools merge failed (rc={merge_proc.returncode}): {merge_text or '<empty>'}"
        )
    commands.append(quote_command(merge_command))

    for chunk_bam in chunk_bams:
        try:
            chunk_bam.unlink()
        except OSError:
            pass
        for suffix in (".strobealign.stderr.log", ".fixmate.stderr.log", ".samtools-sort.stderr.log"):
            leftover = chunk_bam.with_suffix(chunk_bam.suffix + suffix)
            try:
                leftover.unlink()
            except OSError:
                pass

    return commands


def parse_flagstat(flagstat_text: str) -> tuple[int, int, float, Optional[float]]:
    total_reads = 0
    mapped_reads = 0
    mapped_percent = 0.0
    properly_paired_percent: Optional[float] = None

    for line in flagstat_text.splitlines():
        count_match = FLAGSTAT_COUNT_PATTERN.match(line.strip())
        if not count_match:
            continue
        count = int(count_match.group("count"))
        label = count_match.group("label")

        if label.startswith("in total"):
            total_reads = count
            continue
        if label.startswith("mapped "):
            mapped_reads = count
            percent_match = PERCENT_PATTERN.search(line)
            if percent_match:
                mapped_percent = float(percent_match.group("percent"))
            continue
        if label.startswith("properly paired"):
            percent_match = PERCENT_PATTERN.search(line)
            if percent_match:
                properly_paired_percent = float(percent_match.group("percent"))

    return total_reads, mapped_reads, mapped_percent, properly_paired_percent


def parse_stats(stats_text: str) -> tuple[Optional[float], Optional[float]]:
    duplicate_percent: Optional[float] = None
    mean_insert_size: Optional[float] = None
    total_sequences: Optional[float] = None
    duplicated_reads: Optional[float] = None

    for line in stats_text.splitlines():
        if not line.startswith("SN\t"):
            continue
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        label = parts[1].rstrip(":")
        value = parts[2]
        if label == "raw total sequences":
            total_sequences = float(value)
        elif label == "reads duplicated":
            duplicated_reads = float(value)
        elif label == "insert size average":
            mean_insert_size = float(value)

    if total_sequences and duplicated_reads is not None and total_sequences > 0:
        duplicate_percent = duplicated_reads / total_sequences * 100

    return duplicate_percent, mean_insert_size


def execute_alignment_lane(
    *,
    workspace_display_name: str,
    workspace_id: str,
    run_id: str,
    sample_lane: SampleLane,
    reference_path: Path,
    r1_path: Path,
    r2_path: Path,
    working_dir: Path,
) -> LaneExecutionOutput:
    aligner_binary = os.getenv("ALIGNMENT_STROBEALIGN_BINARY", "strobealign")
    samtools_binary = os.getenv("SAMTOOLS_BINARY", "samtools")
    read_group_flags = build_read_group(workspace_display_name, workspace_id, sample_lane)

    coordinate_bam = working_dir / f"{sample_lane.value}.coord-sorted.bam"
    final_bam = working_dir / f"{sample_lane.value}.aligned.bam"
    final_bai = working_dir / f"{sample_lane.value}.aligned.bam.bai"
    flagstat_path = working_dir / f"{sample_lane.value}.flagstat.txt"
    idxstats_path = working_dir / f"{sample_lane.value}.idxstats.txt"
    stats_path = working_dir / f"{sample_lane.value}.stats.txt"
    chunk_dir = working_dir / f"{sample_lane.value}.chunks"

    parallelism = get_alignment_chunk_parallelism()
    aligner_threads_per_chunk = max(
        1, get_aligner_thread_count() // max(1, parallelism)
    )

    def _on_progress(phase: ChunkPhase, total: int, completed: int, active: int) -> None:
        record_chunk_progress(
            run_id,
            sample_lane,
            phase=phase,
            total=total,
            completed=completed,
            active=active,
        )

    command_log = run_chunked_strobealign_pipeline(
        reference_path=reference_path,
        read_group_flags=read_group_flags,
        r1_path=r1_path,
        r2_path=r2_path,
        output_path=coordinate_bam,
        aligner_binary=aligner_binary,
        samtools_binary=samtools_binary,
        chunk_dir=chunk_dir,
        chunk_reads=get_alignment_chunk_reads(),
        parallelism=parallelism,
        aligner_threads_per_chunk=aligner_threads_per_chunk,
        sort_threads_per_chunk=get_samtools_sort_thread_count(),
        sort_memory_per_chunk=get_samtools_sort_memory(),
        on_progress=_on_progress,
    )

    samtools_threads_str = str(get_samtools_thread_count())

    markdup_command = [
        samtools_binary,
        "markdup",
        "-@",
        samtools_threads_str,
        str(coordinate_bam),
        str(final_bam),
    ]
    run_command(markdup_command)
    command_log.append(quote_command(markdup_command))

    index_command = [
        samtools_binary,
        "index",
        "-@",
        samtools_threads_str,
        str(final_bam),
    ]
    run_command(index_command)
    command_log.append(quote_command(index_command))

    flagstat_command = [samtools_binary, "flagstat", str(final_bam)]
    flagstat_result = subprocess.run(
        flagstat_command,
        check=True,
        capture_output=True,
        text=True,
    )
    flagstat_path.write_text(flagstat_result.stdout)
    command_log.append(quote_command(flagstat_command))

    idxstats_command = [samtools_binary, "idxstats", str(final_bam)]
    idxstats_result = subprocess.run(
        idxstats_command,
        check=True,
        capture_output=True,
        text=True,
    )
    idxstats_path.write_text(idxstats_result.stdout)
    command_log.append(quote_command(idxstats_command))

    stats_command = [samtools_binary, "stats", str(final_bam)]
    stats_result = subprocess.run(
        stats_command,
        check=True,
        capture_output=True,
        text=True,
    )
    stats_path.write_text(stats_result.stdout)
    command_log.append(quote_command(stats_command))

    total_reads, mapped_reads, mapped_percent, properly_paired_percent = parse_flagstat(
        flagstat_result.stdout
    )
    duplicate_percent, mean_insert_size = parse_stats(stats_result.stdout)

    return LaneExecutionOutput(
        sample_lane=sample_lane,
        metrics=AlignmentLaneMetricsResponse(
            sample_lane=sample_lane,
            total_reads=total_reads,
            mapped_reads=mapped_reads,
            mapped_percent=mapped_percent,
            properly_paired_percent=properly_paired_percent,
            duplicate_percent=duplicate_percent,
            mean_insert_size=mean_insert_size,
        ),
        artifact_paths={
            AlignmentArtifactKind.BAM: final_bam,
            AlignmentArtifactKind.BAI: final_bai,
            AlignmentArtifactKind.FLAGSTAT: flagstat_path,
            AlignmentArtifactKind.IDXSTATS: idxstats_path,
            AlignmentArtifactKind.STATS: stats_path,
        },
        command_log=command_log,
    )


def start_alignment_run(
    workspace_id: str,
    run_id: str,
) -> AlignmentJobInputs:
    with session_scope() as session:
        workspace = get_workspace_record(session, workspace_id)
        run = get_alignment_run_record(session, workspace_id, run_id)
        analysis_profile = serialize_analysis_profile(workspace)

        ingestion_summary = summarize_workspace_ingestion(workspace)
        if not ingestion_summary.ready_for_alignment:
            raise RuntimeError("Alignment inputs are no longer ready.")
        if analysis_profile.assay_type is None:
            raise RuntimeError("Analysis profile is incomplete.")
        if not profile_matches_run(analysis_profile, run):
            raise RuntimeError("Analysis profile changed before alignment started.")

        reference = resolve_reference_config(workspace.species, analysis_profile)
        lane_inputs: dict[SampleLane, AlignmentLaneInput] = {}
        for sample_lane in LANES:
            batch = latest_batch_for_lane(workspace, sample_lane)
            if batch is None:
                raise RuntimeError(f"{sample_lane.value.title()} lane is missing.")
            canonical_files = ready_canonical_files_for_batch(batch)
            if ReadPair.R1 not in canonical_files or ReadPair.R2 not in canonical_files:
                raise RuntimeError(PAIRED_OUTPUT_REQUIRED_ISSUE)
            lane_inputs[sample_lane] = AlignmentLaneInput(
                sample_lane=sample_lane,
                r1_path=workspace_file_access_path(canonical_files[ReadPair.R1]),
                r2_path=workspace_file_access_path(canonical_files[ReadPair.R2]),
                r1_filename=canonical_files[ReadPair.R1].filename,
                r2_filename=canonical_files[ReadPair.R2].filename,
            )

        run.status = AlignmentRunStatus.RUNNING.value
        run.progress = 5
        run.runtime_phase = AlignmentRuntimePhase.PREPARING_REFERENCE.value
        run.started_at = utc_now()
        run.updated_at = run.started_at
        run.error = None
        run.blocking_reason = None
        workspace.updated_at = run.updated_at
        session.add(run)
        session.add(workspace)

        return AlignmentJobInputs(
            workspace_id=workspace.id,
            workspace_display_name=workspace.display_name,
            species=workspace.species,
            assay_type=analysis_profile.assay_type,
            reference=reference,
            lanes=lane_inputs,
        )


def upload_alignment_artifacts(
    *,
    workspace_id: str,
    run_id: str,
    lane_outputs: list[LaneExecutionOutput],
) -> list[PipelineArtifactRecord]:
    timestamp = utc_now()
    artifacts: list[PipelineArtifactRecord] = []

    for output in lane_outputs:
        for artifact_kind, artifact_path in output.artifact_paths.items():
            local_path = managed_alignment_artifact_path(
                workspace_id,
                run_id,
                output.sample_lane,
                artifact_path.name,
            )
            content_type = (
                "text/plain"
                if artifact_kind
                in {
                    AlignmentArtifactKind.FLAGSTAT,
                    AlignmentArtifactKind.IDXSTATS,
                    AlignmentArtifactKind.STATS,
                }
                else "application/octet-stream"
            )
            local_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(artifact_path, local_path)
            artifacts.append(
                PipelineArtifactRecord(
                    id=str(uuid.uuid4()),
                    run_id=run_id,
                    workspace_id=workspace_id,
                    stage_id=ALIGNMENT_STAGE_ID,
                    artifact_kind=artifact_kind.value,
                    sample_lane=output.sample_lane.value,
                    filename=artifact_path.name,
                    storage_key=str(local_path),
                    local_path=str(local_path),
                    content_type=content_type,
                    size_bytes=local_path.stat().st_size,
                    created_at=timestamp,
                )
            )

    return artifacts


def persist_alignment_run_success(
    workspace_id: str,
    run_id: str,
    lane_outputs: list[LaneExecutionOutput],
) -> None:
    lane_metrics = {output.sample_lane: output.metrics for output in lane_outputs}
    uploaded_artifacts = upload_alignment_artifacts(
        workspace_id=workspace_id,
        run_id=run_id,
        lane_outputs=lane_outputs,
    )
    has_artifacts = {
        (artifact.sample_lane, artifact.artifact_kind)
        for artifact in uploaded_artifacts
    }
    required_artifacts_ready = {
        (SampleLane.TUMOR.value, AlignmentArtifactKind.BAM.value),
        (SampleLane.TUMOR.value, AlignmentArtifactKind.BAI.value),
        (SampleLane.NORMAL.value, AlignmentArtifactKind.BAM.value),
        (SampleLane.NORMAL.value, AlignmentArtifactKind.BAI.value),
    }.issubset(has_artifacts)
    qc_verdict = classify_run_qc(
        lane_metrics,
        has_required_artifacts=required_artifacts_ready,
    )
    result_payload = json.dumps(
        {
            "lane_metrics": {
                lane.value: {
                    "sample_lane": metrics.sample_lane.value,
                    "total_reads": metrics.total_reads,
                    "mapped_reads": metrics.mapped_reads,
                    "mapped_percent": metrics.mapped_percent,
                    "properly_paired_percent": metrics.properly_paired_percent,
                    "duplicate_percent": metrics.duplicate_percent,
                    "mean_insert_size": metrics.mean_insert_size,
                }
                for lane, metrics in lane_metrics.items()
            }
        }
    )
    command_log = "\n".join(
        command
        for output in lane_outputs
        for command in output.command_log
    )

    with session_scope() as session:
        run = get_alignment_run_record(session, workspace_id, run_id)
        for artifact in uploaded_artifacts:
            session.add(artifact)
            run.artifacts.append(artifact)

        run.status = AlignmentRunStatus.COMPLETED.value
        run.progress = 100
        run.qc_verdict = qc_verdict.value
        run.result_payload = result_payload
        run.command_log = command_log
        run.runtime_phase = None
        run.blocking_reason = (
            "Alignment completed, but required BAM/BAI artifacts are missing."
            if not required_artifacts_ready
            else (
                "Alignment QC failed because one lane mapped below 50%."
                if qc_verdict == QcVerdict.FAIL
                else None
            )
        )
        run.error = None
        run.updated_at = utc_now()
        run.completed_at = run.updated_at
        run.workspace.updated_at = run.updated_at
        session.add(run)
        session.add(run.workspace)


def update_alignment_run_progress(
    workspace_id: str,
    run_id: str,
    progress: int,
    runtime_phase: Optional[AlignmentRuntimePhase] = None,
) -> None:
    with session_scope() as session:
        run = get_alignment_run_record(session, workspace_id, run_id)
        if run.status not in {
            AlignmentRunStatus.PENDING.value,
            AlignmentRunStatus.RUNNING.value,
        }:
            return
        run.progress = progress
        if runtime_phase is not None:
            run.runtime_phase = runtime_phase.value
        run.updated_at = utc_now()
        run.workspace.updated_at = run.updated_at
        session.add(run)
        session.add(run.workspace)


def run_alignment(
    workspace_id: str,
    run_id: str,
) -> None:
    try:
        inputs = start_alignment_run(workspace_id, run_id)
        reference_path = ensure_reference_ready(inputs.reference)
        update_alignment_run_progress(
            workspace_id,
            run_id,
            20,
            runtime_phase=AlignmentRuntimePhase.ALIGNING,
        )

        lane_outputs: list[LaneExecutionOutput] = []
        alignment_tmp_root = get_app_data_root() / "tmp"
        alignment_tmp_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(
            prefix=f"alignment-{run_id}-",
            dir=str(alignment_tmp_root),
        ) as temp_dir_name:
            temp_dir = Path(temp_dir_name)
            for index, sample_lane in enumerate(LANES, start=1):
                lane_input = inputs.lanes[sample_lane]
                lane_dir = temp_dir / sample_lane.value
                lane_dir.mkdir(parents=True, exist_ok=True)
                lane_outputs.append(
                    execute_alignment_lane(
                        workspace_display_name=inputs.workspace_display_name,
                        workspace_id=inputs.workspace_id,
                        run_id=run_id,
                        sample_lane=sample_lane,
                        reference_path=reference_path,
                        r1_path=lane_input.r1_path,
                        r2_path=lane_input.r2_path,
                        working_dir=lane_dir,
                    )
                )
                update_alignment_run_progress(
                    workspace_id,
                    run_id,
                    35 if index == 1 else 75,
                    runtime_phase=AlignmentRuntimePhase.ALIGNING,
                )
            update_alignment_run_progress(
                workspace_id,
                run_id,
                90,
                runtime_phase=AlignmentRuntimePhase.FINALIZING,
            )
            persist_alignment_run_success(workspace_id, run_id, lane_outputs)
    except Exception as error:
        mark_alignment_run_failed(workspace_id, run_id, str(error))
    finally:
        clear_chunk_progress(run_id)


def load_alignment_artifact_download(
    workspace_id: str,
    artifact_id: str,
) -> AlignmentArtifactDownload:
    with session_scope() as session:
        artifact = get_alignment_artifact_record(session, workspace_id, artifact_id)
        return AlignmentArtifactDownload(
            filename=artifact.filename,
            local_path=Path(artifact.local_path or artifact.storage_key),
            content_type=artifact.content_type,
        )
