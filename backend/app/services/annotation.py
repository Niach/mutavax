"""Annotation stage service (Ensembl VEP).

Annotates the somatic VCF produced by stage 3 with gene, consequence, and
impact predictions. The output VCF carries a CSQ INFO field populated with the
exact fields stage 5 (pVACseq / NetMHCpan) requires, so downstream neoantigen
prediction is a drop-in consumer.

Runtime phases:
    installing_cache → annotating → summarizing → finalizing

First run for a given species/assembly downloads the offline VEP cache into
``{app_data}/vep-cache/{species_slug}_{release}/`` and persists it so later
runs skip the download.
"""
from __future__ import annotations

import csv
import gzip
import json
import os
import shutil
import signal
import subprocess
import threading
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.db import session_scope
from app.runtime import (
    get_annotation_run_root,
    get_app_data_root,
    get_vep_cache_root,
    resolve_app_data_path,
)
from app.models.records import PipelineArtifactRecord, PipelineRunRecord
from app.models.schemas import (
    AnnotatedVariantEntry,
    AnnotationArtifactKind,
    AnnotationArtifactResponse,
    AnnotationConsequenceEntry,
    AnnotationMetricsResponse,
    AnnotationRunResponse,
    AnnotationRunStatus,
    AnnotationRuntimePhase,
    AnnotationStageStatus,
    AnnotationStageSummaryResponse,
    CancerGeneHit,
    GeneDomainsResponse,
    GeneFocus,
    GeneFocusVariant,
    PipelineStageId,
    WorkspaceSpecies,
)
from app.services.alignment import resolve_reference_config
from app.services.protein_domains import (
    fetch_domains_for_ensp,
    parse_ensp_from_hgvsp,
)
from app.services.variant_calling import (
    VARIANT_CALLING_STAGE_ID,
    _open_vcf,
    ensure_reference_companions,
    get_latest_variant_calling_run,
)
from app.services.workspace_store import (
    get_workspace_record,
    isoformat,
    serialize_analysis_profile,
    utc_now,
)


ANNOTATION_STAGE_ID = PipelineStageId.ANNOTATION.value
TOP_VARIANTS_LIMIT = 40
MAX_GENE_FOCUS_VARIANTS = 40
IMPACT_ORDER = ("HIGH", "MODERATE", "LOW", "MODIFIER")
IMPACT_RANK = {tier: index for index, tier in enumerate(IMPACT_ORDER)}


# Plain-English labels for the common VEP Sequence Ontology consequence terms.
# Anything not in this map falls through with a humanized version of the SO term.
CONSEQUENCE_LABELS: dict[str, str] = {
    "missense_variant": "Amino-acid change",
    "stop_gained": "Protein cut short",
    "stop_lost": "Stop codon removed",
    "start_lost": "Start codon removed",
    "frameshift_variant": "Reading-frame shift",
    "inframe_insertion": "In-frame insertion",
    "inframe_deletion": "In-frame deletion",
    "protein_altering_variant": "Protein change",
    "splice_acceptor_variant": "Splice site disrupted",
    "splice_donor_variant": "Splice site disrupted",
    "splice_region_variant": "Near a splice site",
    "splice_polypyrimidine_tract_variant": "Near a splice site",
    "splice_donor_region_variant": "Near a splice site",
    "splice_donor_5th_base_variant": "Near a splice site",
    "incomplete_terminal_codon_variant": "Incomplete stop codon",
    "synonymous_variant": "Silent change",
    "start_retained_variant": "Silent change (start)",
    "stop_retained_variant": "Silent change (stop)",
    "coding_sequence_variant": "Coding-sequence change",
    "5_prime_UTR_variant": "5' UTR change",
    "3_prime_UTR_variant": "3' UTR change",
    "intron_variant": "Inside an intron",
    "non_coding_transcript_exon_variant": "Non-coding RNA change",
    "non_coding_transcript_variant": "Non-coding RNA",
    "regulatory_region_variant": "Regulatory region",
    "upstream_gene_variant": "Near a gene (upstream)",
    "downstream_gene_variant": "Near a gene (downstream)",
    "intergenic_variant": "Between genes",
    "TF_binding_site_variant": "TF binding site",
    "mature_miRNA_variant": "miRNA change",
}


def humanize_consequence(term: str) -> str:
    if term in CONSEQUENCE_LABELS:
        return CONSEQUENCE_LABELS[term]
    return term.replace("_", " ").capitalize()


# Species-specific VEP configuration. Matches Ensembl's cache-naming conventions
# at release 111; the species slug must be exact or the cache lookup fails.
@dataclass(frozen=True)
class VepSpeciesConfig:
    species_slug: str
    assembly: str
    label: str
    cache_type: str  # "ensembl" | "refseq" | "merged"
    expected_cache_megabytes: int
    extra_flags: tuple[str, ...] = ()


VEP_RELEASE = os.getenv("CANCERSTUDIO_VEP_RELEASE", "111")


VEP_SPECIES_CONFIG: dict[WorkspaceSpecies, VepSpeciesConfig] = {
    # species_slug is the *plain* species name. The merged/refseq suffix is
    # tacked on for INSTALL.pl (which selects cache flavour via species name)
    # and for the on-disk cache directory; the VEP runtime needs the plain
    # name + an explicit --merged / --refseq flag.
    WorkspaceSpecies.HUMAN: VepSpeciesConfig(
        species_slug="homo_sapiens",
        assembly="GRCh38",
        label="Human (GRCh38)",
        cache_type="merged",
        expected_cache_megabytes=27_000,
        extra_flags=("--mane_select", "--sift", "b", "--polyphen", "b"),
    ),
    WorkspaceSpecies.DOG: VepSpeciesConfig(
        # The GSD-based canine cache at release 111 ships gene/transcript
        # annotation only — no SIFT, no PolyPhen. Requesting --sift fails with
        # "SIFT not available", so we omit it here and note the gap in the UI.
        species_slug="canis_lupus_familiarisgsd",
        assembly="UU_Cfam_GSD_1.0",
        label="Dog (UU_Cfam_GSD_1.0)",
        cache_type="ensembl",
        expected_cache_megabytes=80,
    ),
    WorkspaceSpecies.CAT: VepSpeciesConfig(
        # Felis_catus_9.0 cache similarly lacks SIFT/PolyPhen scores.
        species_slug="felis_catus",
        assembly="Felis_catus_9.0",
        label="Cat (Felis_catus_9.0)",
        cache_type="merged",
        expected_cache_megabytes=552,
    ),
}


def _vep_cache_species_name(vep_config: "VepSpeciesConfig") -> str:
    """Return the species name used by INSTALL.pl and the cache directory
    layout. Merged / RefSeq caches live under a `_merged` / `_refseq`
    suffixed species directory; ensembl caches use the plain slug.
    """
    if vep_config.cache_type == "merged":
        return f"{vep_config.species_slug}_merged"
    if vep_config.cache_type == "refseq":
        return f"{vep_config.species_slug}_refseq"
    return vep_config.species_slug


def resolve_vep_species_config(species: str) -> VepSpeciesConfig:
    try:
        enum_value = WorkspaceSpecies(species)
    except ValueError as error:
        raise ValueError(f"Unsupported species for annotation: {species!r}") from error
    try:
        return VEP_SPECIES_CONFIG[enum_value]
    except KeyError as error:
        raise ValueError(f"No VEP config registered for species {species!r}") from error


# --------------------------------------------------------------------------- #
# Cancer gene list (bundled)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class CancerGeneEntry:
    symbol: str
    role: str
    tier: int


_cancer_genes_lock = threading.Lock()
_cancer_genes_cache: dict[str, CancerGeneEntry] | None = None


def _cancer_genes_csv_path() -> Path:
    return Path(__file__).resolve().parent.parent / "data" / "cancer_genes.csv"


def load_cancer_genes() -> dict[str, CancerGeneEntry]:
    """Load the bundled cancer gene list, keyed by UPPERCASE symbol."""
    global _cancer_genes_cache
    with _cancer_genes_lock:
        if _cancer_genes_cache is not None:
            return _cancer_genes_cache
        entries: dict[str, CancerGeneEntry] = {}
        path = _cancer_genes_csv_path()
        try:
            with path.open("r", encoding="utf-8") as handle:
                reader = csv.reader(handle)
                header_seen = False
                for row in reader:
                    if not row:
                        continue
                    first = row[0].strip()
                    if not first or first.startswith("#"):
                        continue
                    if not header_seen and first == "symbol":
                        header_seen = True
                        continue
                    if len(row) < 3:
                        continue
                    symbol = first.strip()
                    role = row[1].strip() or "cancer gene"
                    try:
                        tier = int(row[2].strip())
                    except (ValueError, IndexError):
                        tier = 2
                    if not symbol:
                        continue
                    entries[symbol.upper()] = CancerGeneEntry(
                        symbol=symbol, role=role, tier=tier
                    )
        except FileNotFoundError:
            entries = {}
        _cancer_genes_cache = entries
        return entries


# --------------------------------------------------------------------------- #
# Subprocess + cancel registry (mirror of variant_calling.py)
# --------------------------------------------------------------------------- #

_subprocess_registry_lock = threading.Lock()
_active_subprocesses: dict[str, list[subprocess.Popen]] = {}
_cancelled_runs: set[str] = set()
_paused_pending_runs: set[str] = set()
_run_pid_dirs: dict[str, Path] = {}


class AnnotationArtifactNotFoundError(FileNotFoundError):
    pass


class AnnotationCancelledError(Exception):
    """Raised when an annotation run is cancelled."""


@dataclass(frozen=True)
class AnnotationArtifactDownload:
    filename: str
    local_path: Path
    content_type: Optional[str]


@dataclass
class AnnotationInputs:
    workspace_id: str
    run_id: str
    species: str
    reference_fasta: Path
    reference_label: Optional[str]
    input_vcf: Path
    run_dir: Path
    vep_config: VepSpeciesConfig


def _derive_pid_dir_on_disk(workspace_id: str, run_id: str) -> Path:
    return (
        get_app_data_root()
        / "workspaces"
        / workspace_id
        / "annotation"
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
                raise AnnotationCancelledError("Annotation run was cancelled.")
            try:
                stdout, stderr = proc.communicate(timeout=1.0)
                break
            except subprocess.TimeoutExpired:
                continue
        returncode = proc.returncode
        if returncode != 0:
            if is_run_cancelled(run_id):
                raise AnnotationCancelledError("Annotation run was cancelled.")
            raise subprocess.CalledProcessError(returncode, command, stdout, stderr)
        return subprocess.CompletedProcess(command, returncode, stdout, stderr)
    finally:
        unregister_subprocess(run_id, proc)


# --------------------------------------------------------------------------- #
# Record access
# --------------------------------------------------------------------------- #


def _annotation_run_query():
    return select(PipelineRunRecord).options(
        selectinload(PipelineRunRecord.artifacts),
        selectinload(PipelineRunRecord.workspace),
    )


def get_latest_annotation_run(session, workspace_id: str) -> Optional[PipelineRunRecord]:
    return session.scalar(
        _annotation_run_query()
        .where(
            PipelineRunRecord.workspace_id == workspace_id,
            PipelineRunRecord.stage_id == ANNOTATION_STAGE_ID,
        )
        .order_by(PipelineRunRecord.created_at.desc())
    )


def get_annotation_run_record(
    session, workspace_id: str, run_id: str
) -> PipelineRunRecord:
    run = session.scalar(
        _annotation_run_query().where(
            PipelineRunRecord.id == run_id,
            PipelineRunRecord.workspace_id == workspace_id,
            PipelineRunRecord.stage_id == ANNOTATION_STAGE_ID,
        )
    )
    if run is None:
        raise FileNotFoundError(f"Annotation run {run_id} not found")
    return run


def get_annotation_artifact_record(
    session, workspace_id: str, artifact_id: str
) -> PipelineArtifactRecord:
    artifact = session.scalar(
        select(PipelineArtifactRecord).where(
            PipelineArtifactRecord.id == artifact_id,
            PipelineArtifactRecord.workspace_id == workspace_id,
            PipelineArtifactRecord.stage_id == ANNOTATION_STAGE_ID,
        )
    )
    if artifact is None:
        raise AnnotationArtifactNotFoundError(
            f"Annotation artifact {artifact_id} not found"
        )
    return artifact


# --------------------------------------------------------------------------- #
# Serializers
# --------------------------------------------------------------------------- #


def _serialize_artifact(record: PipelineArtifactRecord) -> AnnotationArtifactResponse:
    return AnnotationArtifactResponse(
        id=record.id,
        artifact_kind=AnnotationArtifactKind(record.artifact_kind),
        filename=record.filename,
        size_bytes=record.size_bytes,
        download_path=f"/api/workspaces/{record.workspace_id}/annotation/artifacts/{record.id}/download",
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


def _parse_metrics(payload: Optional[str]) -> Optional[AnnotationMetricsResponse]:
    data = _parse_payload(payload)
    metrics = data.get("metrics")
    if not isinstance(metrics, dict):
        return None
    try:
        return AnnotationMetricsResponse.model_validate(metrics)
    except Exception:
        return None


def serialize_annotation_run(record: PipelineRunRecord) -> AnnotationRunResponse:
    payload = _parse_payload(record.result_payload)
    cache_info = payload.get("cache_info") or {}
    return AnnotationRunResponse(
        id=record.id,
        status=AnnotationRunStatus(record.status),
        progress=record.progress / 100,
        runtime_phase=(
            AnnotationRuntimePhase(record.runtime_phase)
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
        cache_pending=bool(cache_info.get("pending")),
        cache_species_label=cache_info.get("species_label"),
        cache_expected_megabytes=cache_info.get("expected_megabytes"),
    )


# --------------------------------------------------------------------------- #
# Stage summary
# --------------------------------------------------------------------------- #


def build_annotation_stage_summary(
    workspace,
    latest_variant_calling_run: Optional[PipelineRunRecord],
    latest_annotation_run: Optional[PipelineRunRecord],
) -> AnnotationStageSummaryResponse:
    latest_response = (
        serialize_annotation_run(latest_annotation_run)
        if latest_annotation_run is not None
        else None
    )
    artifacts = latest_response.artifacts if latest_response else []

    variant_ready = (
        latest_variant_calling_run is not None
        and latest_variant_calling_run.status == "completed"
    )
    if not variant_ready:
        return AnnotationStageSummaryResponse(
            workspace_id=workspace.id,
            status=AnnotationStageStatus.BLOCKED,
            blocking_reason="Finish variant calling before annotation.",
            ready_for_neoantigen=False,
            latest_run=latest_response,
            artifacts=artifacts,
        )

    if latest_annotation_run is None:
        return AnnotationStageSummaryResponse(
            workspace_id=workspace.id,
            status=AnnotationStageStatus.SCAFFOLDED,
            blocking_reason=None,
            ready_for_neoantigen=False,
            latest_run=None,
            artifacts=[],
        )

    status = latest_annotation_run.status
    if status in {AnnotationRunStatus.PENDING.value, AnnotationRunStatus.RUNNING.value}:
        return AnnotationStageSummaryResponse(
            workspace_id=workspace.id,
            status=AnnotationStageStatus.RUNNING,
            blocking_reason=None,
            ready_for_neoantigen=False,
            latest_run=latest_response,
            artifacts=artifacts,
        )
    if status == AnnotationRunStatus.PAUSED.value:
        return AnnotationStageSummaryResponse(
            workspace_id=workspace.id,
            status=AnnotationStageStatus.PAUSED,
            blocking_reason=latest_annotation_run.blocking_reason,
            ready_for_neoantigen=False,
            latest_run=latest_response,
            artifacts=artifacts,
        )
    if status == AnnotationRunStatus.FAILED.value:
        return AnnotationStageSummaryResponse(
            workspace_id=workspace.id,
            status=AnnotationStageStatus.FAILED,
            blocking_reason=latest_annotation_run.blocking_reason,
            ready_for_neoantigen=False,
            latest_run=latest_response,
            artifacts=artifacts,
        )
    if status == AnnotationRunStatus.CANCELLED.value:
        return AnnotationStageSummaryResponse(
            workspace_id=workspace.id,
            status=AnnotationStageStatus.SCAFFOLDED,
            blocking_reason=None,
            ready_for_neoantigen=False,
            latest_run=latest_response,
            artifacts=[],
        )

    return AnnotationStageSummaryResponse(
        workspace_id=workspace.id,
        status=AnnotationStageStatus.COMPLETED,
        blocking_reason=None,
        ready_for_neoantigen=True,
        latest_run=latest_response,
        artifacts=artifacts,
    )


def load_annotation_stage_summary(workspace_id: str) -> AnnotationStageSummaryResponse:
    with session_scope() as session:
        workspace = get_workspace_record(session, workspace_id)
        latest_variant = get_latest_variant_calling_run(session, workspace_id)
        latest_annotation = get_latest_annotation_run(session, workspace_id)
        return build_annotation_stage_summary(
            workspace, latest_variant, latest_annotation
        )


def load_gene_protein_domains(
    workspace_id: str, gene_symbol: str
) -> GeneDomainsResponse:
    """Return the Ensembl protein-domain bands for ``gene_symbol`` on this
    workspace's latest completed annotation run.

    The UI only ships ``domains`` on ``top_gene_focus`` — this endpoint
    backs the lazy per-gene fetch that fires when the user clicks a
    different cancer-gene card. An empty list is a valid response; the
    frontend falls back to the hand-curated preset in that case.
    """
    lookup_symbol = gene_symbol.strip().upper()
    with session_scope() as session:
        latest_annotation = get_latest_annotation_run(session, workspace_id)
        metrics = (
            _parse_metrics(latest_annotation.result_payload)
            if latest_annotation is not None
            else None
        )

    empty = GeneDomainsResponse(
        symbol=lookup_symbol,
        transcript_id=None,
        protein_length=None,
        domains=[],
    )
    if metrics is None:
        return empty

    # 1) top_gene_focus carries the full variant list + transcript id.
    top_focus = metrics.top_gene_focus
    if top_focus and top_focus.symbol.upper() == lookup_symbol:
        ensp = next(
            (
                candidate
                for candidate in (
                    parse_ensp_from_hgvsp(variant.hgvsp)
                    for variant in top_focus.variants
                )
                if candidate
            ),
            None,
        )
        if ensp:
            return GeneDomainsResponse(
                symbol=top_focus.symbol,
                transcript_id=top_focus.transcript_id,
                protein_length=top_focus.protein_length,
                domains=top_focus.domains or fetch_domains_for_ensp(ensp),
            )

    # 2) Otherwise scan top_variants for the first hgvsp that matches this
    #    symbol. top_variants is capped at TOP_VARIANTS_LIMIT per the metrics
    #    builder, so the scan is cheap.
    for variant in metrics.top_variants:
        if (variant.gene_symbol or "").upper() != lookup_symbol:
            continue
        ensp = parse_ensp_from_hgvsp(variant.hgvsp)
        if not ensp:
            continue
        return GeneDomainsResponse(
            symbol=variant.gene_symbol or lookup_symbol,
            transcript_id=variant.transcript_id,
            protein_length=variant.protein_position,  # best approximation
            domains=fetch_domains_for_ensp(ensp),
        )

    return empty


# --------------------------------------------------------------------------- #
# Run orchestration
# --------------------------------------------------------------------------- #


def _locate_variant_calling_vcf(run: PipelineRunRecord) -> Optional[Path]:
    for artifact in run.artifacts:
        if artifact.artifact_kind == "vcf":
            candidate = resolve_app_data_path(artifact.local_path or artifact.storage_key)
            if candidate.exists():
                return candidate
    return None


def create_annotation_run(workspace_id: str) -> AnnotationStageSummaryResponse:
    created_run_id: Optional[str] = None
    with session_scope() as session:
        workspace = get_workspace_record(session, workspace_id)
        latest_variant = get_latest_variant_calling_run(session, workspace_id)
        latest_annotation = get_latest_annotation_run(session, workspace_id)

        if latest_annotation and latest_annotation.status in {
            AnnotationRunStatus.PENDING.value,
            AnnotationRunStatus.RUNNING.value,
        }:
            raise ValueError("Annotation is already running for this workspace.")
        if latest_annotation and latest_annotation.status == AnnotationRunStatus.PAUSED.value:
            raise ValueError(
                "A paused annotation run exists. Resume it, or discard it, "
                "before starting a new run."
            )

        if latest_variant is None or latest_variant.status != "completed":
            raise ValueError("Finish variant calling before annotation.")

        input_vcf = _locate_variant_calling_vcf(latest_variant)
        if input_vcf is None:
            raise ValueError(
                "The variant calling output VCF is missing on disk; "
                "rerun variant calling first."
            )

        vep_config = resolve_vep_species_config(workspace.species)
        analysis_profile = serialize_analysis_profile(workspace)
        reference = resolve_reference_config(workspace.species, analysis_profile)

        timestamp = utc_now()
        run = PipelineRunRecord(
            id=str(uuid.uuid4()),
            workspace_id=workspace.id,
            stage_id=ANNOTATION_STAGE_ID,
            status=AnnotationRunStatus.PENDING.value,
            progress=0,
            qc_verdict=None,
            reference_preset=(
                analysis_profile.reference_preset.value
                if analysis_profile.reference_preset
                else None
            ),
            reference_override=analysis_profile.reference_override,
            reference_label=reference.label,
            reference_path=str(reference.fasta_path),
            runtime_phase=AnnotationRuntimePhase.INSTALLING_CACHE.value,
            command_log=None,
            result_payload=json.dumps(
                {
                    "species": workspace.species,
                    "vep_release": VEP_RELEASE,
                    "species_label": vep_config.label,
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
        summary = build_annotation_stage_summary(workspace, latest_variant, run)

    if created_run_id is None:
        raise RuntimeError("Annotation run creation did not produce an id")

    enqueue_annotation_run(workspace_id, created_run_id)
    return summary


def rerun_annotation(workspace_id: str) -> AnnotationStageSummaryResponse:
    return create_annotation_run(workspace_id)


def mark_annotation_run_cancelled(
    workspace_id: str, run_id: str, reason: str = "Stopped by user."
) -> None:
    with session_scope() as session:
        run = get_annotation_run_record(session, workspace_id, run_id)
        run.status = AnnotationRunStatus.CANCELLED.value
        run.progress = 0
        run.runtime_phase = None
        run.blocking_reason = reason
        run.error = None
        run.updated_at = utc_now()
        run.completed_at = run.updated_at
        run.workspace.updated_at = run.updated_at
        session.add(run)
        session.add(run.workspace)


def mark_annotation_run_paused(
    workspace_id: str, run_id: str, reason: str = "Paused by user. Resume to continue."
) -> None:
    with session_scope() as session:
        run = get_annotation_run_record(session, workspace_id, run_id)
        run.status = AnnotationRunStatus.PAUSED.value
        run.runtime_phase = None
        run.blocking_reason = reason
        run.error = None
        run.updated_at = utc_now()
        run.workspace.updated_at = run.updated_at
        session.add(run)
        session.add(run.workspace)


def _wipe_annotation_run_dir(workspace_id: str, run_id: str) -> None:
    try:
        run_dir = get_annotation_run_root(workspace_id, run_id)
    except Exception:
        return
    if run_dir.exists():
        shutil.rmtree(run_dir, ignore_errors=True)


def cancel_annotation_run(
    workspace_id: str, run_id: str
) -> AnnotationStageSummaryResponse:
    with session_scope() as session:
        run = get_annotation_run_record(session, workspace_id, run_id)
        if run.status not in {
            AnnotationRunStatus.PENDING.value,
            AnnotationRunStatus.RUNNING.value,
            AnnotationRunStatus.PAUSED.value,
        }:
            return load_annotation_stage_summary(workspace_id)
        was_paused = run.status == AnnotationRunStatus.PAUSED.value

    if was_paused:
        mark_annotation_run_cancelled(workspace_id, run_id)
        _wipe_annotation_run_dir(workspace_id, run_id)
        return load_annotation_stage_summary(workspace_id)

    mark_run_cancelled(run_id)
    terminate_run_subprocesses(
        run_id, pid_dir=_derive_pid_dir_on_disk(workspace_id, run_id)
    )
    mark_annotation_run_cancelled(workspace_id, run_id)
    _wipe_annotation_run_dir(workspace_id, run_id)
    return load_annotation_stage_summary(workspace_id)


def pause_annotation_run(
    workspace_id: str, run_id: str
) -> AnnotationStageSummaryResponse:
    with session_scope() as session:
        run = get_annotation_run_record(session, workspace_id, run_id)
        if run.status not in {
            AnnotationRunStatus.PENDING.value,
            AnnotationRunStatus.RUNNING.value,
        }:
            return load_annotation_stage_summary(workspace_id)

    mark_run_paused_pending(run_id)
    terminate_run_subprocesses(
        run_id, pid_dir=_derive_pid_dir_on_disk(workspace_id, run_id)
    )
    mark_annotation_run_paused(workspace_id, run_id)
    return load_annotation_stage_summary(workspace_id)


def resume_annotation_run(
    workspace_id: str, run_id: str
) -> AnnotationStageSummaryResponse:
    with session_scope() as session:
        run = get_annotation_run_record(session, workspace_id, run_id)
        if run.status != AnnotationRunStatus.PAUSED.value:
            raise ValueError(
                f"Cannot resume a run in status {run.status!r}; "
                "only paused runs are resumable."
            )
        timestamp = utc_now()
        run.status = AnnotationRunStatus.PENDING.value
        run.runtime_phase = AnnotationRuntimePhase.ANNOTATING.value
        run.blocking_reason = None
        run.error = None
        run.updated_at = timestamp
        run.completed_at = None
        run.workspace.updated_at = timestamp
        session.add(run)
        session.add(run.workspace)

    enqueue_annotation_run(workspace_id, run_id)
    return load_annotation_stage_summary(workspace_id)


def mark_annotation_run_failed(
    workspace_id: str, run_id: str, error_message: str
) -> None:
    with session_scope() as session:
        run = get_annotation_run_record(session, workspace_id, run_id)
        run.status = AnnotationRunStatus.FAILED.value
        run.progress = 100
        run.error = error_message
        run.blocking_reason = error_message
        run.runtime_phase = None
        run.updated_at = utc_now()
        run.completed_at = run.updated_at
        run.workspace.updated_at = run.updated_at
        session.add(run)
        session.add(run.workspace)


def enqueue_annotation_run(workspace_id: str, run_id: str) -> None:
    from app.services import background

    try:
        background.submit(run_annotation, workspace_id, run_id)
    except Exception as error:
        mark_annotation_run_failed(
            workspace_id, run_id, f"Unable to queue annotation: {error}"
        )


def update_annotation_progress(
    workspace_id: str,
    run_id: str,
    progress: int,
    runtime_phase: Optional[AnnotationRuntimePhase] = None,
) -> None:
    with session_scope() as session:
        run = get_annotation_run_record(session, workspace_id, run_id)
        if run.status not in {
            AnnotationRunStatus.PENDING.value,
            AnnotationRunStatus.RUNNING.value,
        }:
            return
        run.progress = progress
        if runtime_phase is not None:
            run.runtime_phase = runtime_phase.value
        run.updated_at = utc_now()
        run.workspace.updated_at = run.updated_at
        session.add(run)
        session.add(run.workspace)


def update_annotation_cache_info(
    workspace_id: str,
    run_id: str,
    *,
    pending: bool,
    species_label: str,
    expected_megabytes: Optional[int],
) -> None:
    """Stamp cache_info onto ``result_payload`` so the UI can surface a first-run download hint."""
    with session_scope() as session:
        run = get_annotation_run_record(session, workspace_id, run_id)
        payload = _parse_payload(run.result_payload)
        payload["cache_info"] = {
            "pending": pending,
            "species_label": species_label,
            "expected_megabytes": expected_megabytes,
        }
        run.result_payload = json.dumps(payload)
        run.updated_at = utc_now()
        session.add(run)


def start_annotation_run(workspace_id: str, run_id: str) -> AnnotationInputs:
    with session_scope() as session:
        workspace = get_workspace_record(session, workspace_id)
        run = get_annotation_run_record(session, workspace_id, run_id)
        latest_variant = get_latest_variant_calling_run(session, workspace_id)
        if latest_variant is None or latest_variant.status != "completed":
            raise RuntimeError(
                "Variant calling output is no longer available."
            )
        input_vcf = _locate_variant_calling_vcf(latest_variant)
        if input_vcf is None:
            raise RuntimeError(
                "The variant calling VCF is missing on disk. Rerun variant calling first."
            )

        reference_path_str = run.reference_path
        if not reference_path_str:
            raise RuntimeError("Annotation run is missing a reference path.")
        reference_path = resolve_app_data_path(reference_path_str)

        vep_config = resolve_vep_species_config(workspace.species)

        run.status = AnnotationRunStatus.RUNNING.value
        if run.progress < 5:
            run.progress = 5
        if run.runtime_phase is None:
            run.runtime_phase = AnnotationRuntimePhase.INSTALLING_CACHE.value
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
        reference_label = run.reference_label

    run_dir = get_annotation_run_root(workspace_id, run_id)
    return AnnotationInputs(
        workspace_id=workspace_id,
        run_id=run_id,
        species=species,
        reference_fasta=reference_path,
        reference_label=reference_label,
        input_vcf=input_vcf,
        run_dir=run_dir,
        vep_config=vep_config,
    )


# --------------------------------------------------------------------------- #
# VEP execution
# --------------------------------------------------------------------------- #


def _vep_binary() -> str:
    return os.getenv("VEP_BINARY", "vep")


def _vep_install_command() -> list[str]:
    """Return the argv prefix that invokes VEP's cache installer.

    The upstream ``ensembl-vep`` repo doesn't ship a ``vep_install`` binary —
    cache installs run through ``perl /opt/vep/INSTALL.pl``. The backend image
    creates a thin wrapper at ``/usr/local/bin/vep_install`` for convenience;
    this helper honors a ``VEP_INSTALL_COMMAND`` override for environments that
    invoke the INSTALL.pl path directly.
    """
    override = os.getenv("VEP_INSTALL_COMMAND")
    if override:
        return override.split()
    return ["vep_install"]


def _vep_plugins_dir() -> Path:
    configured = os.getenv("CANCERSTUDIO_VEP_PLUGINS_DIR")
    if configured:
        return Path(configured)
    return Path("/opt/vep-plugins")


def vep_cache_dir_for_species(vep_config: VepSpeciesConfig) -> Path:
    """Return the root directory VEP expects for ``--dir_cache``.

    VEP looks under ``{dir_cache}/{species_slug}/{release}_{assembly}/``.
    We keep a stable parent so multiple species caches can coexist.
    """
    return get_vep_cache_root()


def vep_cache_species_dir(vep_config: VepSpeciesConfig) -> Path:
    return (
        vep_cache_dir_for_species(vep_config)
        / _vep_cache_species_name(vep_config)
        / f"{VEP_RELEASE}_{vep_config.assembly}"
    )


def ensure_vep_cache(
    vep_config: VepSpeciesConfig,
    *,
    run_id: str,
    on_log: callable,  # type: ignore[valid-type]
) -> bool:
    """Ensure the VEP cache for ``vep_config`` is installed.

    Returns True if a download was performed, False if the cache already
    existed. Writes progress + log lines via ``on_log``.
    """
    target = vep_cache_species_dir(vep_config)
    cache_root = vep_cache_dir_for_species(vep_config)
    if target.exists() and any(target.iterdir()):
        on_log(f"# VEP cache already installed at {target}")
        return False

    cache_root.mkdir(parents=True, exist_ok=True)
    on_log(
        f"# downloading VEP {vep_config.cache_type} cache for "
        f"{vep_config.species_slug} / {vep_config.assembly} (~{vep_config.expected_cache_megabytes} MB)"
    )

    # VEP's INSTALL.pl selects cache flavour via a species-name suffix
    # (`homo_sapiens_merged`, `homo_sapiens_refseq`), not a CLI flag. VEP's
    # runtime is the mirror image and wants the plain species name + an
    # explicit --merged/--refseq flag; we keep species_slug in the plain
    # form and synthesise the installer form here.
    cmd = [
        *_vep_install_command(),
        "--AUTO", "cf",
        "--SPECIES", _vep_cache_species_name(vep_config),
        "--ASSEMBLY", vep_config.assembly,
        "--CACHEDIR", str(cache_root),
        "--CACHE_VERSION", VEP_RELEASE,
        "--NO_HTSLIB",
        "--NO_TEST",
        "--NO_UPDATE",
        "--NO_BIOPERL",
    ]
    on_log(" ".join(cmd))
    _run_subprocess(cmd, run_id=run_id)
    return True


def run_vep(
    inputs: AnnotationInputs,
    *,
    command_log: list[str],
    on_progress: callable,  # type: ignore[valid-type]
) -> Path:
    """Run VEP offline annotation. Returns the path to the annotated bgzipped VCF."""
    output_vcf = inputs.run_dir / "annotated.vcf.gz"
    warnings_file = inputs.run_dir / "vep_warnings.txt"
    summary_file = inputs.run_dir / "vep_summary.html"

    # Clean up leftovers from a prior interrupted run. VEP refuses to overwrite.
    for stale in (output_vcf, warnings_file, summary_file):
        try:
            stale.unlink(missing_ok=True)
        except OSError:
            pass

    plugins_dir = _vep_plugins_dir()
    cache_root = vep_cache_dir_for_species(inputs.vep_config)

    cmd: list[str] = [
        _vep_binary(),
        "--input_file", str(inputs.input_vcf),
        "--output_file", str(output_vcf),
        "--format", "vcf",
        "--vcf",
        "--compress_output", "bgzip",
        "--force_overwrite",
        "--offline",
        "--cache",
        "--dir_cache", str(cache_root),
        "--species", inputs.vep_config.species_slug,
        "--assembly", inputs.vep_config.assembly,
        "--cache_version", VEP_RELEASE,
        "--fasta", str(inputs.reference_fasta),
        "--symbol",
        "--terms", "SO",
        "--canonical",
        "--biotype",
        "--hgvs",
        "--numbers",
        "--protein",
        "--pick_allele",
        "--stats_file", str(summary_file),
        "--warning_file", str(warnings_file),
        "--fork", str(_vep_fork_count()),
    ]
    if inputs.vep_config.cache_type == "merged":
        cmd.append("--merged")
    elif inputs.vep_config.cache_type == "refseq":
        cmd.append("--refseq")

    cmd.extend(inputs.vep_config.extra_flags)

    if plugins_dir.exists():
        cmd.extend(["--dir_plugins", str(plugins_dir)])
        if (plugins_dir / "Frameshift.pm").exists():
            cmd.extend(["--plugin", "Frameshift"])
        if (plugins_dir / "Wildtype.pm").exists():
            cmd.extend(["--plugin", "Wildtype"])
        if (plugins_dir / "Downstream.pm").exists():
            cmd.extend(["--plugin", "Downstream"])

    command_log.append(" ".join(cmd))
    on_progress(40, AnnotationRuntimePhase.ANNOTATING)
    _run_subprocess(cmd, run_id=inputs.run_id)
    on_progress(75, AnnotationRuntimePhase.SUMMARIZING)
    return output_vcf


def _vep_fork_count() -> int:
    override = os.getenv("CANCERSTUDIO_VEP_FORKS")
    if override:
        try:
            value = int(override)
            if value > 0:
                return min(value, 8)
        except ValueError:
            pass
    cores = os.cpu_count() or 4
    return max(1, min(cores // 2, 4))


# --------------------------------------------------------------------------- #
# CSQ parsing & metrics
# --------------------------------------------------------------------------- #


@dataclass
class CsqRecord:
    chromosome: str
    position: int
    ref: str
    alt: str
    gene_symbol: Optional[str]
    gene_id: Optional[str]
    transcript_id: Optional[str]
    consequence: str
    impact: str
    canonical: bool
    biotype: Optional[str]
    hgvsc: Optional[str]
    hgvsp: Optional[str]
    protein_position: Optional[int]
    cdna_position: Optional[int]
    cds_position: Optional[int]
    protein_length: Optional[int]
    tumor_vaf: Optional[float]


def _parse_csq_header(vcf_path: Path) -> list[str]:
    with _open_vcf(vcf_path) as handle:
        for line in handle:
            if not line.startswith("#"):
                return []
            if line.startswith("##INFO=<ID=CSQ"):
                marker = "Format: "
                idx = line.find(marker)
                if idx == -1:
                    return []
                tail = line[idx + len(marker) :].rstrip("\n>").rstrip("\"")
                return tail.split("|")
    return []


def _split_pos(value: Optional[str]) -> tuple[Optional[int], Optional[int]]:
    """Parse VEP 'Protein_position' / 'CDS_position' which can be '12' or '12/345'."""
    if not value or value in ("-", "."):
        return None, None
    if "/" in value:
        first, _, second = value.partition("/")
    else:
        first, second = value, ""
    first_stripped = first.split("-")[0]
    try:
        pos = int(first_stripped)
    except ValueError:
        pos = None
    try:
        total = int(second) if second else None
    except ValueError:
        total = None
    return pos, total


def _highest_impact_consequence(entries: list[CsqRecord]) -> Optional[CsqRecord]:
    """Return the CSQ entry with the strongest impact (canonical preferred on ties)."""
    if not entries:
        return None

    def key(entry: CsqRecord) -> tuple[int, int]:
        rank = IMPACT_RANK.get(entry.impact, IMPACT_RANK["MODIFIER"])
        canonical_bias = 0 if entry.canonical else 1
        return (rank, canonical_bias)

    return min(entries, key=key)


def _compute_tumor_vaf(format_field: str, sample_field: str) -> Optional[float]:
    """Best-effort tumor VAF from the first non-reference sample column.

    VEP's output VCF preserves Mutect2 sample columns. When we use ``--pick_allele``
    we get one consequence per variant — VAF is the same across CSQ entries for
    that variant, so we compute it once per record.
    """
    if not format_field or not sample_field:
        return None
    keys = format_field.split(":")
    values = sample_field.split(":")
    data = {key: values[i] if i < len(values) else "" for i, key in enumerate(keys)}
    af = data.get("AF")
    if af and af not in ("", ".", "-"):
        try:
            return float(af.split(",")[0])
        except ValueError:
            pass
    ad = data.get("AD")
    if ad and "," in ad:
        try:
            parts = [int(t) for t in ad.split(",") if t and t != "."]
        except ValueError:
            return None
        total = sum(parts)
        if total <= 0 or len(parts) < 2:
            return None
        return sum(parts[1:]) / total
    return None


def _iter_csq_records(vcf_path: Path) -> Iterable[tuple[list[CsqRecord], str, int, str, str]]:
    """Yield (csq_entries, chrom, pos, ref, alt) per VCF record."""
    csq_format = _parse_csq_header(vcf_path)
    if not csq_format:
        return
    sample_offset = None
    format_index = None
    with _open_vcf(vcf_path) as handle:
        for line in handle:
            if line.startswith("#"):
                if line.startswith("#CHROM"):
                    cols = line.rstrip("\n").split("\t")
                    format_index = 8
                    sample_offset = 9 if len(cols) > 9 else None
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
            info = cols[7]
            filter_value = cols[6] or "."
            if filter_value not in {"PASS", "."}:
                continue
            csq_chunk = None
            for segment in info.split(";"):
                if segment.startswith("CSQ="):
                    csq_chunk = segment[4:]
                    break
            if not csq_chunk:
                continue

            tumor_vaf: Optional[float] = None
            if format_index is not None and sample_offset is not None and len(cols) > sample_offset:
                tumor_vaf = _compute_tumor_vaf(cols[format_index], cols[sample_offset])

            for alt_single in alt_field.split(","):
                if alt_single in ("", "."):
                    continue
                entries: list[CsqRecord] = []
                for raw in csq_chunk.split(","):
                    fields = raw.split("|")
                    data = {
                        csq_format[i]: fields[i] if i < len(fields) else ""
                        for i in range(len(csq_format))
                    }
                    allele = data.get("Allele", "")
                    # VEP emits one CSQ per allele when --pick_allele is on; keep
                    # only the one matching the current alt (string match is usually fine).
                    if allele and alt_single and allele != alt_single:
                        # For indels the Allele field is the padded/trimmed variant
                        # — accept a match on the suffix to be safe.
                        if not alt_single.endswith(allele) and not allele.endswith(alt_single):
                            continue
                    impact = (data.get("IMPACT") or "MODIFIER").upper()
                    if impact not in IMPACT_RANK:
                        impact = "MODIFIER"
                    consequence = data.get("Consequence") or "intergenic_variant"
                    # Multiple SO terms can appear separated by "&"; pick the first.
                    primary_consequence = consequence.split("&")[0].strip() or consequence
                    protein_pos, protein_len = _split_pos(data.get("Protein_position"))
                    cdna_pos, _ = _split_pos(data.get("cDNA_position"))
                    cds_pos, _ = _split_pos(data.get("CDS_position"))
                    entries.append(
                        CsqRecord(
                            chromosome=chrom,
                            position=pos,
                            ref=ref,
                            alt=alt_single,
                            gene_symbol=(data.get("SYMBOL") or "").strip() or None,
                            gene_id=(data.get("Gene") or "").strip() or None,
                            transcript_id=(data.get("Feature") or "").strip() or None,
                            consequence=primary_consequence,
                            impact=impact,
                            canonical=(data.get("CANONICAL") or "").strip().upper() == "YES",
                            biotype=(data.get("BIOTYPE") or "").strip() or None,
                            hgvsc=(data.get("HGVSc") or "").strip() or None,
                            hgvsp=(data.get("HGVSp") or "").strip() or None,
                            protein_position=protein_pos,
                            cdna_position=cdna_pos,
                            cds_position=cds_pos,
                            protein_length=protein_len,
                            tumor_vaf=tumor_vaf,
                        )
                    )
                if entries:
                    yield entries, chrom, pos, ref, alt_single


def compute_annotation_metrics(
    vcf_path: Path,
    *,
    reference_label: Optional[str],
    species_label: Optional[str],
    vep_release: Optional[str],
) -> AnnotationMetricsResponse:
    cancer_genes = load_cancer_genes()

    total = annotated = 0
    cancer_variant_count = 0
    by_impact: dict[str, int] = {tier: 0 for tier in IMPACT_ORDER}
    by_consequence: dict[str, int] = defaultdict(int)

    @dataclass
    class _GeneAccumulator:
        symbol: str
        role: str
        tier: int
        variant_count: int = 0
        highest_impact: str = "MODIFIER"
        top_hgvsp: Optional[str] = None
        top_consequence: Optional[str] = None
        transcript_id: Optional[str] = None
        protein_length: Optional[int] = None
        variants: list[GeneFocusVariant] = field(default_factory=list)

    gene_accumulators: dict[str, _GeneAccumulator] = {}
    top_candidates: list[AnnotatedVariantEntry] = []

    for entries, chrom, pos, ref, alt in _iter_csq_records(vcf_path):
        total += 1
        primary = _highest_impact_consequence(entries)
        if primary is None:
            continue
        annotated += 1
        by_impact[primary.impact] = by_impact.get(primary.impact, 0) + 1
        by_consequence[primary.consequence] += 1

        in_cancer_gene = False
        cancer_entry = None
        if primary.gene_symbol:
            cancer_entry = cancer_genes.get(primary.gene_symbol.upper())
            if cancer_entry is not None:
                in_cancer_gene = True
                cancer_variant_count += 1

        annotated_entry = AnnotatedVariantEntry(
            chromosome=chrom,
            position=pos,
            ref=ref,
            alt=alt,
            gene_symbol=primary.gene_symbol,
            transcript_id=primary.transcript_id,
            consequence=primary.consequence,
            consequence_label=humanize_consequence(primary.consequence),
            impact=primary.impact,  # type: ignore[arg-type]
            hgvsc=primary.hgvsc,
            hgvsp=primary.hgvsp,
            protein_position=primary.protein_position,
            tumor_vaf=primary.tumor_vaf,
            in_cancer_gene=in_cancer_gene,
        )
        top_candidates.append(annotated_entry)

        if cancer_entry is not None and primary.gene_symbol:
            key = cancer_entry.symbol.upper()
            acc = gene_accumulators.get(key)
            if acc is None:
                acc = _GeneAccumulator(
                    symbol=cancer_entry.symbol,
                    role=cancer_entry.role,
                    tier=cancer_entry.tier,
                )
                gene_accumulators[key] = acc
            acc.variant_count += 1
            if IMPACT_RANK.get(primary.impact, 3) < IMPACT_RANK.get(
                acc.highest_impact, 3
            ):
                acc.highest_impact = primary.impact
                acc.top_hgvsp = primary.hgvsp
                acc.top_consequence = primary.consequence
            if acc.transcript_id is None and primary.transcript_id:
                acc.transcript_id = primary.transcript_id
            if acc.protein_length is None and primary.protein_length:
                acc.protein_length = primary.protein_length
            if len(acc.variants) < MAX_GENE_FOCUS_VARIANTS:
                acc.variants.append(
                    GeneFocusVariant(
                        chromosome=chrom,
                        position=pos,
                        protein_position=primary.protein_position,
                        hgvsp=primary.hgvsp,
                        hgvsc=primary.hgvsc,
                        consequence=primary.consequence,
                        impact=primary.impact,  # type: ignore[arg-type]
                        tumor_vaf=primary.tumor_vaf,
                    )
                )

    # Sort top variants by (impact rank, in-cancer-gene, VAF desc).
    def _ranking(entry: AnnotatedVariantEntry) -> tuple[int, int, float]:
        impact_rank = IMPACT_RANK.get(entry.impact, IMPACT_RANK["MODIFIER"])
        cancer_bias = 0 if entry.in_cancer_gene else 1
        vaf = entry.tumor_vaf if entry.tumor_vaf is not None else 0.0
        return (impact_rank, cancer_bias, -vaf)

    top_candidates.sort(key=_ranking)
    top_variants = top_candidates[:TOP_VARIANTS_LIMIT]

    cancer_hits = sorted(
        gene_accumulators.values(),
        key=lambda acc: (
            IMPACT_RANK.get(acc.highest_impact, 3),
            -acc.variant_count,
            acc.tier,
            acc.symbol,
        ),
    )
    cancer_gene_hits = [
        CancerGeneHit(
            symbol=acc.symbol,
            role=acc.role,
            variant_count=acc.variant_count,
            highest_impact=acc.highest_impact,  # type: ignore[arg-type]
            top_hgvsp=acc.top_hgvsp,
            top_consequence=acc.top_consequence,
        )
        for acc in cancer_hits
    ]

    top_focus: Optional[GeneFocus] = None
    if cancer_hits:
        focus_acc = cancer_hits[0]
        top_focus = GeneFocus(
            symbol=focus_acc.symbol,
            role=focus_acc.role,
            transcript_id=focus_acc.transcript_id,
            protein_length=focus_acc.protein_length,
            variants=focus_acc.variants,
        )
        # Best-effort Ensembl protein-feature lookup for the focused gene so
        # the lollipop paints real domain bands (kinase / DNA-binding / etc.)
        # on its first render. The fetcher handles its own errors + caches to
        # disk — a network hiccup leaves top_focus.domains as None and the
        # frontend falls through to the preset / bare-track rendering.
        focus_ensp = next(
            (
                ensp
                for ensp in (
                    parse_ensp_from_hgvsp(variant.hgvsp)
                    for variant in focus_acc.variants
                )
                if ensp
            ),
            None,
        )
        if focus_ensp:
            fetched = fetch_domains_for_ensp(focus_ensp)
            if fetched:
                top_focus.domains = fetched

    consequence_entries = [
        AnnotationConsequenceEntry(
            term=term,
            label=humanize_consequence(term),
            count=count,
        )
        for term, count in sorted(by_consequence.items(), key=lambda kv: (-kv[1], kv[0]))
    ]

    return AnnotationMetricsResponse(
        total_variants=total,
        annotated_variants=annotated,
        by_impact=by_impact,
        by_consequence=consequence_entries,
        cancer_gene_hits=cancer_gene_hits,
        cancer_gene_variant_count=cancer_variant_count,
        top_gene_focus=top_focus,
        top_variants=top_variants,
        reference_label=reference_label,
        species_label=species_label,
        vep_release=vep_release,
    )


# --------------------------------------------------------------------------- #
# Persistence
# --------------------------------------------------------------------------- #


def _artifact_content_type(kind: AnnotationArtifactKind) -> str:
    if kind == AnnotationArtifactKind.VEP_SUMMARY:
        return "text/html"
    if kind == AnnotationArtifactKind.VEP_WARNINGS:
        return "text/plain"
    return "application/octet-stream"


def _ensure_tbi(vcf_path: Path, run_id: str, command_log: list[str]) -> Optional[Path]:
    """Build a Tabix index for the annotated VCF so stage 5 can random-access it."""
    tbi_path = vcf_path.with_suffix(vcf_path.suffix + ".tbi")
    if tbi_path.exists():
        return tbi_path
    cmd = ["tabix", "-p", "vcf", str(vcf_path)]
    command_log.append(" ".join(cmd))
    try:
        _run_subprocess(cmd, run_id=run_id)
    except (FileNotFoundError, subprocess.CalledProcessError):
        return None
    return tbi_path if tbi_path.exists() else None


def persist_annotation_success(
    workspace_id: str,
    run_id: str,
    *,
    annotated_vcf: Path,
    tbi_path: Optional[Path],
    summary_path: Optional[Path],
    warnings_path: Optional[Path],
    metrics: AnnotationMetricsResponse,
    command_log: list[str],
) -> None:
    artifacts: list[PipelineArtifactRecord] = []
    timestamp = utc_now()

    def _record(path: Optional[Path], kind: AnnotationArtifactKind) -> None:
        if path is None or not path.exists():
            return
        artifacts.append(
            PipelineArtifactRecord(
                id=str(uuid.uuid4()),
                run_id=run_id,
                workspace_id=workspace_id,
                stage_id=ANNOTATION_STAGE_ID,
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

    _record(annotated_vcf, AnnotationArtifactKind.ANNOTATED_VCF)
    _record(tbi_path, AnnotationArtifactKind.ANNOTATED_VCF_INDEX)
    _record(summary_path, AnnotationArtifactKind.VEP_SUMMARY)
    _record(warnings_path, AnnotationArtifactKind.VEP_WARNINGS)

    command_log_text = "\n".join(command_log)

    with session_scope() as session:
        run = get_annotation_run_record(session, workspace_id, run_id)
        for artifact in artifacts:
            session.add(artifact)
            run.artifacts.append(artifact)
        run.status = AnnotationRunStatus.COMPLETED.value
        run.progress = 100
        run.runtime_phase = None
        payload = _parse_payload(run.result_payload)
        payload["metrics"] = metrics.model_dump(mode="json")
        payload["cache_info"] = {
            "pending": False,
            "species_label": payload.get("species_label"),
            "expected_megabytes": None,
        }
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


def run_annotation(workspace_id: str, run_id: str) -> None:
    command_log: list[str] = []
    clear_run_cancelled(run_id)
    clear_run_paused_pending(run_id)
    set_run_pid_dir(run_id, _derive_pid_dir_on_disk(workspace_id, run_id))
    try:
        inputs = start_annotation_run(workspace_id, run_id)

        def progress_cb(
            progress: int, phase: Optional[AnnotationRuntimePhase] = None
        ) -> None:
            update_annotation_progress(workspace_id, run_id, progress, phase)

        def log_cb(line: str) -> None:
            command_log.append(line)

        # Stamp cache-info early so the UI can surface "Downloading reference
        # gene-knowledge database" messaging during the cache phase.
        cache_dir = vep_cache_species_dir(inputs.vep_config)
        cache_needs_download = not (cache_dir.exists() and any(cache_dir.iterdir()))
        update_annotation_cache_info(
            workspace_id,
            run_id,
            pending=cache_needs_download,
            species_label=inputs.vep_config.label,
            expected_megabytes=(
                inputs.vep_config.expected_cache_megabytes
                if cache_needs_download
                else None
            ),
        )

        progress_cb(10, AnnotationRuntimePhase.INSTALLING_CACHE)
        ensure_vep_cache(inputs.vep_config, run_id=run_id, on_log=log_cb)
        update_annotation_cache_info(
            workspace_id,
            run_id,
            pending=False,
            species_label=inputs.vep_config.label,
            expected_megabytes=None,
        )

        # Build reference companions (.fai / .dict) — VEP needs .fai for --fasta.
        progress_cb(28, AnnotationRuntimePhase.ANNOTATING)
        companion_cmds = ensure_reference_companions(inputs.reference_fasta)
        command_log.extend(companion_cmds)

        annotated_vcf = run_vep(
            inputs,
            command_log=command_log,
            on_progress=progress_cb,
        )
        tbi_path = _ensure_tbi(annotated_vcf, run_id, command_log)

        progress_cb(85, AnnotationRuntimePhase.SUMMARIZING)
        metrics = compute_annotation_metrics(
            annotated_vcf,
            reference_label=inputs.reference_label,
            species_label=inputs.vep_config.label,
            vep_release=VEP_RELEASE,
        )

        progress_cb(95, AnnotationRuntimePhase.FINALIZING)
        persist_annotation_success(
            workspace_id,
            run_id,
            annotated_vcf=annotated_vcf,
            tbi_path=tbi_path,
            summary_path=inputs.run_dir / "vep_summary.html",
            warnings_path=inputs.run_dir / "vep_warnings.txt",
            metrics=metrics,
            command_log=command_log,
        )
    except AnnotationCancelledError:
        if is_run_paused_pending(run_id):
            mark_annotation_run_paused(workspace_id, run_id)
        else:
            mark_annotation_run_cancelled(workspace_id, run_id)
    except subprocess.CalledProcessError as error:
        if is_run_paused_pending(run_id):
            mark_annotation_run_paused(workspace_id, run_id)
        elif is_run_cancelled(run_id):
            mark_annotation_run_cancelled(workspace_id, run_id)
        else:
            stderr_tail = (error.stderr or "").splitlines()[-20:]
            message = " | ".join(stderr_tail) if stderr_tail else str(error)
            mark_annotation_run_failed(
                workspace_id,
                run_id,
                f"{' '.join(error.cmd[:3])} failed: {message}",
            )
    except Exception as error:
        if is_run_paused_pending(run_id):
            mark_annotation_run_paused(workspace_id, run_id)
        elif is_run_cancelled(run_id):
            mark_annotation_run_cancelled(workspace_id, run_id)
        else:
            mark_annotation_run_failed(workspace_id, run_id, str(error))
    finally:
        clear_subprocess_registry(run_id)
        clear_run_cancelled(run_id)
        clear_run_paused_pending(run_id)
        clear_run_pid_dir(run_id)


def load_annotation_artifact_download(
    workspace_id: str, artifact_id: str
) -> AnnotationArtifactDownload:
    with session_scope() as session:
        artifact = get_annotation_artifact_record(session, workspace_id, artifact_id)
        return AnnotationArtifactDownload(
            filename=artifact.filename,
            local_path=resolve_app_data_path(artifact.local_path or artifact.storage_key),
            content_type=artifact.content_type,
        )
