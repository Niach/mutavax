from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class WorkspaceRecord(Base):
    __tablename__ = "workspaces"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    species: Mapped[str] = mapped_column(String(32), nullable=False)
    reference_preset: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    reference_override: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    active_stage: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    batches: Mapped[list["IngestionBatchRecord"]] = relationship(
        back_populates="workspace",
        cascade="all, delete-orphan",
        order_by=lambda: IngestionBatchRecord.created_at.desc(),
    )
    files: Mapped[list["WorkspaceFileRecord"]] = relationship(
        back_populates="workspace",
        cascade="all, delete-orphan",
        order_by=lambda: WorkspaceFileRecord.uploaded_at.desc(),
    )
    pipeline_runs: Mapped[list["PipelineRunRecord"]] = relationship(
        back_populates="workspace",
        cascade="all, delete-orphan",
        order_by=lambda: PipelineRunRecord.created_at.desc(),
    )


class IngestionBatchRecord(Base):
    __tablename__ = "ingestion_batches"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    sample_lane: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    sample_stem: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    progress_phase: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    progress_current_filename: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    progress_bytes_processed: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    progress_total_bytes: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    progress_throughput_bytes_per_sec: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True
    )
    progress_eta_seconds: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    progress_percent: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    workspace: Mapped["WorkspaceRecord"] = relationship(back_populates="batches")
    files: Mapped[list["WorkspaceFileRecord"]] = relationship(
        back_populates="batch",
        cascade="all, delete-orphan",
        order_by=lambda: WorkspaceFileRecord.uploaded_at.desc(),
    )


class WorkspaceFileRecord(Base):
    __tablename__ = "workspace_files"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    batch_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("ingestion_batches.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_file_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("workspace_files.id", ondelete="SET NULL"), nullable=True, index=True
    )
    sample_lane: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    format: Mapped[str] = mapped_column(String(32), nullable=False)
    file_role: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    read_pair: Mapped[str] = mapped_column(String(32), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(1024), nullable=False)
    source_path: Mapped[Optional[str]] = mapped_column(String(4096), nullable=True)
    local_path: Mapped[Optional[str]] = mapped_column(String(4096), nullable=True)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    workspace: Mapped["WorkspaceRecord"] = relationship(back_populates="files")
    batch: Mapped["IngestionBatchRecord"] = relationship(back_populates="files")
    source_file: Mapped[Optional["WorkspaceFileRecord"]] = relationship(
        remote_side="WorkspaceFileRecord.id",
        uselist=False,
    )


class PipelineRunRecord(Base):
    __tablename__ = "pipeline_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    stage_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    progress: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    qc_verdict: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    reference_preset: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    reference_override: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    reference_label: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    reference_path: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    runtime_phase: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    command_log: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    result_payload: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    blocking_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    workspace: Mapped["WorkspaceRecord"] = relationship(back_populates="pipeline_runs")
    artifacts: Mapped[list["PipelineArtifactRecord"]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
        order_by=lambda: PipelineArtifactRecord.created_at.asc(),
    )


class PipelineArtifactRecord(Base):
    __tablename__ = "pipeline_artifacts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("pipeline_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    workspace_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    stage_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    artifact_kind: Mapped[str] = mapped_column(String(64), nullable=False)
    sample_lane: Mapped[Optional[str]] = mapped_column(String(16), nullable=True, index=True)
    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(1024), nullable=False, unique=True)
    local_path: Mapped[Optional[str]] = mapped_column(String(4096), nullable=True)
    content_type: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    run: Mapped["PipelineRunRecord"] = relationship(back_populates="artifacts")
