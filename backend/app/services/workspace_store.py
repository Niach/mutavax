import gzip
import os
import re
import shutil
import subprocess
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.db import session_scope
from app.models.records import IngestionBatchRecord, WorkspaceFileRecord, WorkspaceRecord
from app.models.schemas import (
    ActiveStageUpdateRequest,
    IngestionStatus,
    IngestionSummaryResponse,
    PipelineStageId,
    ReadPair,
    WorkspaceCreateRequest,
    WorkspaceFileFormat,
    WorkspaceFileResponse,
    WorkspaceFileRole,
    WorkspaceFileStatus,
    WorkspaceResponse,
)
from app.services.s3_storage import get_storage

READ_PAIR_PATTERN = re.compile(r"(?:^|[_\-.])(R[12])(?:[_\-.]|$)", re.IGNORECASE)
COMPRESSED_FASTQ_SUFFIXES = (".fastq.gz", ".fq.gz")
FASTQ_SUFFIXES = COMPRESSED_FASTQ_SUFFIXES + (".fastq", ".fq")
BAM_SUFFIXES = (".bam",)
CRAM_SUFFIXES = (".cram",)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def utc_now_iso() -> str:
    return utc_now().isoformat()


def isoformat(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def sanitize_filename(filename: str) -> str:
    name = Path(filename).name.strip()
    if not name:
        raise ValueError("Filename is required")
    return name


def detect_format(filename: str) -> Optional[WorkspaceFileFormat]:
    lowered = filename.lower()
    if lowered.endswith(FASTQ_SUFFIXES):
        return WorkspaceFileFormat.FASTQ
    if lowered.endswith(BAM_SUFFIXES):
        return WorkspaceFileFormat.BAM
    if lowered.endswith(CRAM_SUFFIXES):
        return WorkspaceFileFormat.CRAM
    return None


def infer_read_pair(filename: str) -> ReadPair:
    match = READ_PAIR_PATTERN.search(filename)
    if not match:
        return ReadPair.UNKNOWN
    return ReadPair.R1 if match.group(1).upper() == "R1" else ReadPair.R2


def is_compressed_fastq(filename: str) -> bool:
    return filename.lower().endswith(COMPRESSED_FASTQ_SUFFIXES)


def strip_known_suffix(filename: str) -> str:
    lowered = filename.lower()
    for suffix in FASTQ_SUFFIXES + BAM_SUFFIXES + CRAM_SUFFIXES:
        if lowered.endswith(suffix):
            return filename[: -len(suffix)]
    return filename


def source_object_key(workspace_id: str, batch_id: str, file_id: str, filename: str) -> str:
    return f"workspaces/{workspace_id}/batches/{batch_id}/source/{file_id}-{sanitize_filename(filename)}"


def canonical_object_key(workspace_id: str, batch_id: str, filename: str) -> str:
    return f"workspaces/{workspace_id}/batches/{batch_id}/canonical/{sanitize_filename(filename)}"


def build_canonical_filename(source_filename: str, read_pair: ReadPair) -> str:
    stem = strip_known_suffix(source_filename)
    if read_pair != ReadPair.UNKNOWN and not READ_PAIR_PATTERN.search(stem):
        stem = f"{stem}_{read_pair.value}"
    return f"{stem}.normalized.fastq.gz"


def upload_size(upload: UploadFile) -> int:
    upload.file.seek(0, os.SEEK_END)
    size = upload.file.tell()
    upload.file.seek(0)
    return size


def get_workspace_query():
    return select(WorkspaceRecord).options(
        selectinload(WorkspaceRecord.files),
        selectinload(WorkspaceRecord.batches).selectinload(IngestionBatchRecord.files),
    )


def get_workspace_record(session, workspace_id: str) -> WorkspaceRecord:
    workspace = session.scalar(
        get_workspace_query().where(WorkspaceRecord.id == workspace_id)
    )
    if workspace is None:
        raise FileNotFoundError(f"Workspace {workspace_id} not found")
    return workspace


def get_batch_record(session, batch_id: str) -> IngestionBatchRecord:
    batch = session.scalar(
        select(IngestionBatchRecord)
        .options(selectinload(IngestionBatchRecord.files), selectinload(IngestionBatchRecord.workspace))
        .where(IngestionBatchRecord.id == batch_id)
    )
    if batch is None:
        raise FileNotFoundError(f"Ingestion batch {batch_id} not found")
    return batch


def serialize_file(record: WorkspaceFileRecord) -> WorkspaceFileResponse:
    return WorkspaceFileResponse(
        id=record.id,
        batch_id=record.batch_id,
        source_file_id=record.source_file_id,
        filename=record.filename,
        format=WorkspaceFileFormat(record.format),
        file_role=WorkspaceFileRole(record.file_role),
        status=WorkspaceFileStatus(record.status),
        size_bytes=record.size_bytes,
        uploaded_at=isoformat(record.uploaded_at),
        read_pair=ReadPair(record.read_pair),
        storage_key=record.storage_key,
        error=record.error,
    )


def summarize_batch(batch: Optional[IngestionBatchRecord]) -> IngestionSummaryResponse:
    if batch is None:
        return IngestionSummaryResponse(status=IngestionStatus.EMPTY)

    source_files = [file for file in batch.files if file.file_role == WorkspaceFileRole.SOURCE.value]
    canonical_files = [
        file
        for file in batch.files
        if file.file_role == WorkspaceFileRole.CANONICAL.value and file.status == WorkspaceFileStatus.READY.value
    ]

    ready_pairs = {file.read_pair for file in canonical_files}
    missing_pairs: list[ReadPair] = []
    if ReadPair.R1.value not in ready_pairs:
        missing_pairs.append(ReadPair.R1)
    if ReadPair.R2.value not in ready_pairs:
        missing_pairs.append(ReadPair.R2)

    status = IngestionStatus(batch.status)
    ready_for_alignment = status == IngestionStatus.READY

    return IngestionSummaryResponse(
        active_batch_id=batch.id,
        status=status,
        ready_for_alignment=ready_for_alignment,
        source_file_count=len(source_files),
        canonical_file_count=len(canonical_files),
        missing_pairs=missing_pairs,
        updated_at=isoformat(batch.updated_at),
    )


def serialize_workspace(workspace: WorkspaceRecord) -> WorkspaceResponse:
    ordered_batches = sorted(
        workspace.batches,
        key=lambda batch: isoformat(batch.created_at),
        reverse=True,
    )
    ordered_files = sorted(
        workspace.files,
        key=lambda file: isoformat(file.uploaded_at),
        reverse=True,
    )
    active_batch = ordered_batches[0] if ordered_batches else None

    return WorkspaceResponse(
        id=workspace.id,
        display_name=workspace.display_name,
        species=workspace.species,
        active_stage=workspace.active_stage,
        created_at=isoformat(workspace.created_at),
        updated_at=isoformat(workspace.updated_at),
        ingestion=summarize_batch(active_batch),
        files=[serialize_file(file) for file in ordered_files],
    )


def list_workspaces() -> list[WorkspaceResponse]:
    with session_scope() as session:
        workspaces = session.scalars(get_workspace_query()).all()
        ordered = sorted(
            workspaces,
            key=lambda workspace: isoformat(workspace.updated_at),
            reverse=True,
        )
        return [serialize_workspace(workspace) for workspace in ordered]


def load_workspace(workspace_id: str) -> WorkspaceResponse:
    with session_scope() as session:
        return serialize_workspace(get_workspace_record(session, workspace_id))


def create_workspace(request: WorkspaceCreateRequest) -> WorkspaceResponse:
    timestamp = utc_now()
    with session_scope() as session:
        workspace = WorkspaceRecord(
            id=str(uuid.uuid4()),
            display_name=request.display_name.strip(),
            species=request.species.value,
            active_stage=PipelineStageId.INGESTION.value,
            created_at=timestamp,
            updated_at=timestamp,
        )
        session.add(workspace)
        session.flush()
        session.refresh(workspace)
        return serialize_workspace(workspace)


def update_workspace_active_stage(
    workspace_id: str, request: ActiveStageUpdateRequest
) -> WorkspaceResponse:
    with session_scope() as session:
        workspace = get_workspace_record(session, workspace_id)
        workspace.active_stage = request.active_stage.value
        workspace.updated_at = utc_now()
        session.add(workspace)
        session.flush()
        return serialize_workspace(workspace)


def batch_status_from_files(batch: IngestionBatchRecord) -> IngestionStatus:
    if not batch.files:
        return IngestionStatus.EMPTY

    if batch.error or any(file.status == WorkspaceFileStatus.FAILED.value for file in batch.files):
        return IngestionStatus.FAILED

    ready_pairs = {
        file.read_pair
        for file in batch.files
        if file.file_role == WorkspaceFileRole.CANONICAL.value
        and file.status == WorkspaceFileStatus.READY.value
    }
    if ReadPair.R1.value in ready_pairs and ReadPair.R2.value in ready_pairs:
        return IngestionStatus.READY

    if any(file.status == WorkspaceFileStatus.NORMALIZING.value for file in batch.files):
        return IngestionStatus.NORMALIZING

    return IngestionStatus.UPLOADED


def refresh_batch_status(batch: IngestionBatchRecord) -> None:
    batch.status = batch_status_from_files(batch).value
    batch.updated_at = utc_now()
    batch.workspace.updated_at = batch.updated_at


def create_canonical_record(
    session,
    *,
    workspace: WorkspaceRecord,
    batch: IngestionBatchRecord,
    source_file: WorkspaceFileRecord,
    filename: str,
    read_pair: ReadPair,
    size_bytes: int,
    storage_key: str,
) -> WorkspaceFileRecord:
    existing = session.scalar(
        select(WorkspaceFileRecord).where(
            WorkspaceFileRecord.batch_id == batch.id,
            WorkspaceFileRecord.file_role == WorkspaceFileRole.CANONICAL.value,
            WorkspaceFileRecord.source_file_id == source_file.id,
            WorkspaceFileRecord.read_pair == read_pair.value,
        )
    )
    if existing is not None:
        existing.filename = filename
        existing.size_bytes = size_bytes
        existing.storage_key = storage_key
        existing.status = WorkspaceFileStatus.READY.value
        existing.error = None
        existing.uploaded_at = utc_now()
        session.add(existing)
        return existing

    canonical = WorkspaceFileRecord(
        id=str(uuid.uuid4()),
        workspace_id=workspace.id,
        batch_id=batch.id,
        source_file_id=source_file.id,
        filename=filename,
        format=WorkspaceFileFormat.FASTQ.value,
        file_role=WorkspaceFileRole.CANONICAL.value,
        status=WorkspaceFileStatus.READY.value,
        read_pair=read_pair.value,
        storage_key=storage_key,
        size_bytes=size_bytes,
        uploaded_at=utc_now(),
        error=None,
    )
    session.add(canonical)
    batch.files.append(canonical)
    workspace.files.append(canonical)
    return canonical


def copy_fastq_source_to_canonical(
    session,
    *,
    workspace: WorkspaceRecord,
    batch: IngestionBatchRecord,
    source_file: WorkspaceFileRecord,
) -> None:
    storage = get_storage()
    canonical_filename = build_canonical_filename(source_file.filename, ReadPair(source_file.read_pair))
    destination_key = canonical_object_key(workspace.id, batch.id, canonical_filename)
    storage.copy_object(source_file.storage_key, destination_key)
    create_canonical_record(
        session,
        workspace=workspace,
        batch=batch,
        source_file=source_file,
        filename=canonical_filename,
        read_pair=ReadPair(source_file.read_pair),
        size_bytes=source_file.size_bytes,
        storage_key=destination_key,
    )
    source_file.status = WorkspaceFileStatus.READY.value
    source_file.error = None
    session.add(source_file)


def source_requires_async_processing(source_file: WorkspaceFileRecord) -> bool:
    if source_file.format == WorkspaceFileFormat.FASTQ.value:
        return not is_compressed_fastq(source_file.filename)
    return source_file.format in {WorkspaceFileFormat.BAM.value, WorkspaceFileFormat.CRAM.value}


def enqueue_batch_normalization(batch_id: str) -> None:
    from app.tasks.ingestion_tasks import normalize_ingestion_batch

    try:
        normalize_ingestion_batch.delay(batch_id)
    except Exception as error:
        mark_batch_failed(batch_id, f"Unable to queue normalization: {error}")


def mark_batch_failed(batch_id: str, error_message: str) -> None:
    with session_scope() as session:
        batch = get_batch_record(session, batch_id)
        batch.error = error_message
        batch.status = IngestionStatus.FAILED.value
        batch.updated_at = utc_now()
        batch.workspace.updated_at = batch.updated_at
        for file in batch.files:
            if file.file_role == WorkspaceFileRole.SOURCE.value and file.status == WorkspaceFileStatus.NORMALIZING.value:
                file.status = WorkspaceFileStatus.FAILED.value
                file.error = error_message
                session.add(file)
        session.add(batch)


def upload_workspace_files(
    workspace_id: str, uploads: list[UploadFile]
) -> WorkspaceResponse:
    if not uploads:
        raise ValueError("At least one file is required")

    batch_id: Optional[str] = None
    should_enqueue = False

    with session_scope() as session:
        workspace = get_workspace_record(session, workspace_id)
        timestamp = utc_now()
        batch = IngestionBatchRecord(
            id=str(uuid.uuid4()),
            workspace_id=workspace.id,
            status=IngestionStatus.UPLOADED.value,
            error=None,
            created_at=timestamp,
            updated_at=timestamp,
        )
        session.add(batch)
        workspace.batches.append(batch)
        batch_id = batch.id

        storage = get_storage()
        source_records: list[WorkspaceFileRecord] = []

        for upload in uploads:
            filename = sanitize_filename(upload.filename or "")
            file_format = detect_format(filename)
            if file_format is None:
                raise ValueError(
                    f"Unsupported file type for {filename}. Accepted inputs are FASTQ, BAM, and CRAM."
                )

            file_id = str(uuid.uuid4())
            object_key = source_object_key(workspace.id, batch.id, file_id, filename)
            size_bytes = upload_size(upload)
            storage.upload_fileobj(upload.file, object_key, content_type=upload.content_type)
            upload.file.close()

            source_record = WorkspaceFileRecord(
                id=file_id,
                workspace_id=workspace.id,
                batch_id=batch.id,
                source_file_id=None,
                filename=filename,
                format=file_format.value,
                file_role=WorkspaceFileRole.SOURCE.value,
                status=WorkspaceFileStatus.UPLOADED.value,
                read_pair=infer_read_pair(filename).value,
                storage_key=object_key,
                size_bytes=size_bytes,
                uploaded_at=timestamp,
                error=None,
            )
            session.add(source_record)
            workspace.files.append(source_record)
            batch.files.append(source_record)
            source_records.append(source_record)

        session.flush()

        for source_record in source_records:
            if source_record.format == WorkspaceFileFormat.FASTQ.value and is_compressed_fastq(source_record.filename):
                copy_fastq_source_to_canonical(
                    session,
                    workspace=workspace,
                    batch=batch,
                    source_file=source_record,
                )
            elif source_requires_async_processing(source_record):
                source_record.status = WorkspaceFileStatus.NORMALIZING.value
                session.add(source_record)
                should_enqueue = True

        refresh_batch_status(batch)
        session.add(batch)
        session.add(workspace)
        session.flush()
        response = serialize_workspace(workspace)

    if should_enqueue and batch_id is not None:
        enqueue_batch_normalization(batch_id)

    return response


def gzip_fastq_source(
    session,
    *,
    workspace: WorkspaceRecord,
    batch: IngestionBatchRecord,
    source_file: WorkspaceFileRecord,
    temp_dir: Path,
) -> None:
    storage = get_storage()
    source_path = temp_dir / source_file.filename
    storage.download_path(source_file.storage_key, source_path)

    canonical_filename = build_canonical_filename(source_file.filename, ReadPair(source_file.read_pair))
    canonical_path = temp_dir / canonical_filename
    with source_path.open("rb") as source_handle, gzip.open(canonical_path, "wb") as destination_handle:
        shutil.copyfileobj(source_handle, destination_handle)

    storage_key = canonical_object_key(workspace.id, batch.id, canonical_filename)
    storage.upload_path(canonical_path, storage_key, content_type="application/gzip")

    create_canonical_record(
        session,
        workspace=workspace,
        batch=batch,
        source_file=source_file,
        filename=canonical_filename,
        read_pair=ReadPair(source_file.read_pair),
        size_bytes=canonical_path.stat().st_size,
        storage_key=storage_key,
    )
    source_file.status = WorkspaceFileStatus.READY.value
    source_file.error = None
    session.add(source_file)


def run_samtools_fastq(source_path: Path, r1_path: Path, r2_path: Path, is_cram: bool) -> None:
    command = [
        "samtools",
        "fastq",
        "-1",
        str(r1_path),
        "-2",
        str(r2_path),
        "-0",
        "/dev/null",
        "-s",
        "/dev/null",
        "-n",
    ]

    reference_path = os.getenv("SAMTOOLS_REFERENCE_FASTA")
    if is_cram and reference_path:
        command.extend(["--reference", reference_path])

    command.append(str(source_path))
    subprocess.run(command, check=True, capture_output=True, text=True)


def normalize_alignment_source(
    session,
    *,
    workspace: WorkspaceRecord,
    batch: IngestionBatchRecord,
    source_file: WorkspaceFileRecord,
    temp_dir: Path,
) -> None:
    storage = get_storage()
    source_path = temp_dir / source_file.filename
    storage.download_path(source_file.storage_key, source_path)

    r1_filename = build_canonical_filename(source_file.filename, ReadPair.R1)
    r2_filename = build_canonical_filename(source_file.filename, ReadPair.R2)
    r1_path = temp_dir / r1_filename
    r2_path = temp_dir / r2_filename

    run_samtools_fastq(
        source_path,
        r1_path,
        r2_path,
        is_cram=source_file.format == WorkspaceFileFormat.CRAM.value,
    )

    if not r1_path.exists() or not r2_path.exists():
        raise RuntimeError(f"samtools did not produce paired FASTQ files for {source_file.filename}")

    for read_pair, canonical_filename, canonical_path in [
        (ReadPair.R1, r1_filename, r1_path),
        (ReadPair.R2, r2_filename, r2_path),
    ]:
        storage_key = canonical_object_key(workspace.id, batch.id, canonical_filename)
        storage.upload_path(canonical_path, storage_key, content_type="application/gzip")
        create_canonical_record(
            session,
            workspace=workspace,
            batch=batch,
            source_file=source_file,
            filename=canonical_filename,
            read_pair=read_pair,
            size_bytes=canonical_path.stat().st_size,
            storage_key=storage_key,
        )

    source_file.status = WorkspaceFileStatus.READY.value
    source_file.error = None
    session.add(source_file)


def run_batch_normalization(batch_id: str) -> WorkspaceResponse:
    with session_scope() as session:
        batch = get_batch_record(session, batch_id)
        workspace = batch.workspace
        batch.error = None
        batch.status = IngestionStatus.NORMALIZING.value
        batch.updated_at = utc_now()
        workspace.updated_at = batch.updated_at
        session.add(batch)

        try:
            with tempfile.TemporaryDirectory(prefix=f"workspace-batch-{batch.id}-") as temp_dir_name:
                temp_dir = Path(temp_dir_name)
                for source_file in batch.files:
                    if source_file.file_role != WorkspaceFileRole.SOURCE.value:
                        continue
                    if source_file.status != WorkspaceFileStatus.NORMALIZING.value:
                        continue

                    if source_file.format == WorkspaceFileFormat.FASTQ.value:
                        gzip_fastq_source(
                            session,
                            workspace=workspace,
                            batch=batch,
                            source_file=source_file,
                            temp_dir=temp_dir,
                        )
                    elif source_file.format in {WorkspaceFileFormat.BAM.value, WorkspaceFileFormat.CRAM.value}:
                        normalize_alignment_source(
                            session,
                            workspace=workspace,
                            batch=batch,
                            source_file=source_file,
                            temp_dir=temp_dir,
                        )
                    else:
                        raise RuntimeError(
                            f"Unsupported normalization source format {source_file.format}"
                        )

            refresh_batch_status(batch)
            session.add(batch)
            session.add(workspace)
            session.flush()
            return serialize_workspace(workspace)
        except Exception as error:
            batch.error = str(error)
            for source_file in batch.files:
                if source_file.file_role == WorkspaceFileRole.SOURCE.value and source_file.status == WorkspaceFileStatus.NORMALIZING.value:
                    source_file.status = WorkspaceFileStatus.FAILED.value
                    source_file.error = str(error)
                    session.add(source_file)
            refresh_batch_status(batch)
            session.add(batch)
            session.add(workspace)
            session.commit()
            raise
