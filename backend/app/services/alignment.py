import gzip
import json
import os
import re
import shlex
import shutil
import subprocess
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path
from urllib.request import urlopen
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.db import session_scope
from app.runtime import get_reference_bundle_root
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


def bwa_index_exists(reference_path: Path) -> bool:
    suffixes = [".amb", ".ann", ".pac", ".0123"]
    has_core = all((reference_path.with_name(reference_path.name + suffix)).exists() for suffix in suffixes)
    has_bwt = any(reference_path.parent.glob(f"{reference_path.name}.bwt*"))
    return has_core and has_bwt


def ensure_reference_indices(reference_path: Path) -> None:
    bwa_binary = os.getenv("ALIGNMENT_BWA_BINARY", "bwa-mem2")
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

    if not bwa_index_exists(reference_path):
        # Local import to avoid a service-layer import cycle.
        from app.services.tool_preflight import verify_memory_for_bwa_mem2_index

        verify_memory_for_bwa_mem2_index()
        subprocess.run(
            [bwa_binary, "index", str(reference_path)],
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


def build_read_group(workspace_display_name: str, workspace_id: str, sample_lane: SampleLane) -> str:
    sample = re.sub(r"[^A-Za-z0-9_.-]+", "-", workspace_display_name.strip()) or workspace_id
    rg_id = f"{workspace_id}.{sample_lane.value}"
    rg_sample = f"{sample}.{sample_lane.value}"
    return (
        f"@RG\\tID:{rg_id}\\tSM:{rg_sample}\\tLB:{workspace_id}"
        f"\\tPL:ILLUMINA\\tPU:{rg_id}"
    )


def run_command(command: list[str]) -> str:
    completed = subprocess.run(command, check=True, capture_output=True, text=True)
    stderr = completed.stderr.strip()
    return stderr


def run_bwa_name_sort_pipeline(
    *,
    reference_path: Path,
    read_group: str,
    r1_path: Path,
    r2_path: Path,
    output_path: Path,
    bwa_binary: str,
    samtools_binary: str,
) -> list[str]:
    bwa_command = [
        bwa_binary,
        "mem",
        "-R",
        read_group,
        str(reference_path),
        str(r1_path),
        str(r2_path),
    ]
    sort_command = [
        samtools_binary,
        "sort",
        "-n",
        "-o",
        str(output_path),
        "-",
    ]

    bwa_process = subprocess.Popen(
        bwa_command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        sort_result = subprocess.run(
            sort_command,
            stdin=bwa_process.stdout,
            capture_output=True,
            text=True,
            check=False,
        )
    finally:
        if bwa_process.stdout is not None:
            bwa_process.stdout.close()

    bwa_stderr = b""
    if bwa_process.stderr is not None:
        bwa_stderr = bwa_process.stderr.read()
        bwa_process.stderr.close()
    bwa_returncode = bwa_process.wait()
    if bwa_returncode != 0:
        raise RuntimeError(
            f"bwa-mem2 mem failed: {bwa_stderr.decode(errors='replace').strip()}"
        )
    if sort_result.returncode != 0:
        raise RuntimeError(
            f"samtools sort failed: {sort_result.stderr.strip()}"
        )

    return [quote_command(bwa_command), quote_command(sort_command)]


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
    sample_lane: SampleLane,
    reference_path: Path,
    r1_path: Path,
    r2_path: Path,
    working_dir: Path,
) -> LaneExecutionOutput:
    bwa_binary = os.getenv("ALIGNMENT_BWA_BINARY", "bwa-mem2")
    samtools_binary = os.getenv("SAMTOOLS_BINARY", "samtools")
    read_group = build_read_group(workspace_display_name, workspace_id, sample_lane)

    name_sorted_bam = working_dir / f"{sample_lane.value}.name-sorted.bam"
    fixmate_bam = working_dir / f"{sample_lane.value}.fixmate.bam"
    coordinate_bam = working_dir / f"{sample_lane.value}.coord-sorted.bam"
    final_bam = working_dir / f"{sample_lane.value}.aligned.bam"
    final_bai = working_dir / f"{sample_lane.value}.aligned.bam.bai"
    flagstat_path = working_dir / f"{sample_lane.value}.flagstat.txt"
    idxstats_path = working_dir / f"{sample_lane.value}.idxstats.txt"
    stats_path = working_dir / f"{sample_lane.value}.stats.txt"

    command_log = run_bwa_name_sort_pipeline(
        reference_path=reference_path,
        read_group=read_group,
        r1_path=r1_path,
        r2_path=r2_path,
        output_path=name_sorted_bam,
        bwa_binary=bwa_binary,
        samtools_binary=samtools_binary,
    )

    fixmate_command = [
        samtools_binary,
        "fixmate",
        "-m",
        str(name_sorted_bam),
        str(fixmate_bam),
    ]
    run_command(fixmate_command)
    command_log.append(quote_command(fixmate_command))

    sort_command = [
        samtools_binary,
        "sort",
        "-o",
        str(coordinate_bam),
        str(fixmate_bam),
    ]
    run_command(sort_command)
    command_log.append(quote_command(sort_command))

    markdup_command = [
        samtools_binary,
        "markdup",
        str(coordinate_bam),
        str(final_bam),
    ]
    run_command(markdup_command)
    command_log.append(quote_command(markdup_command))

    index_command = [samtools_binary, "index", str(final_bam)]
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
        with tempfile.TemporaryDirectory(prefix=f"alignment-{run_id}-") as temp_dir_name:
            temp_dir = Path(temp_dir_name)
            for index, sample_lane in enumerate(LANES, start=1):
                lane_input = inputs.lanes[sample_lane]
                lane_dir = temp_dir / sample_lane.value
                lane_dir.mkdir(parents=True, exist_ok=True)
                lane_outputs.append(
                    execute_alignment_lane(
                        workspace_display_name=inputs.workspace_display_name,
                        workspace_id=inputs.workspace_id,
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
