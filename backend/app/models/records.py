from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class WorkspaceRecord(Base):
    __tablename__ = "workspaces"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    species: Mapped[str] = mapped_column(String(32), nullable=False)
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
    upload_sessions: Mapped[list["UploadSessionRecord"]] = relationship(
        back_populates="workspace",
        cascade="all, delete-orphan",
        order_by=lambda: UploadSessionRecord.updated_at.desc(),
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
    storage_key: Mapped[str] = mapped_column(String(1024), nullable=False, unique=True)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    workspace: Mapped["WorkspaceRecord"] = relationship(back_populates="files")
    batch: Mapped["IngestionBatchRecord"] = relationship(back_populates="files")
    source_file: Mapped[Optional["WorkspaceFileRecord"]] = relationship(
        remote_side="WorkspaceFileRecord.id",
        uselist=False,
    )


class UploadSessionRecord(Base):
    __tablename__ = "upload_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    sample_lane: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    committed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    workspace: Mapped["WorkspaceRecord"] = relationship(back_populates="upload_sessions")
    files: Mapped[list["UploadSessionFileRecord"]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
        order_by=lambda: UploadSessionFileRecord.created_at.asc(),
    )


class UploadSessionFileRecord(Base):
    __tablename__ = "upload_session_files"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    session_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("upload_sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    workspace_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    sample_lane: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    format: Mapped[str] = mapped_column(String(32), nullable=False)
    read_pair: Mapped[str] = mapped_column(String(32), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    uploaded_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_parts: Mapped[int] = mapped_column(Integer, nullable=False)
    last_modified_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(1024), nullable=False, index=True)
    content_type: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    storage_key: Mapped[str] = mapped_column(String(1024), nullable=False, unique=True)
    multipart_upload_id: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    session: Mapped["UploadSessionRecord"] = relationship(back_populates="files")
    parts: Mapped[list["UploadSessionPartRecord"]] = relationship(
        back_populates="session_file",
        cascade="all, delete-orphan",
        order_by=lambda: UploadSessionPartRecord.part_number.asc(),
    )


class UploadSessionPartRecord(Base):
    __tablename__ = "upload_session_parts"
    __table_args__ = (UniqueConstraint("session_file_id", "part_number", name="uq_upload_session_file_part"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_file_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("upload_session_files.id", ondelete="CASCADE"), nullable=False, index=True
    )
    part_number: Mapped[int] = mapped_column(Integer, nullable=False)
    etag: Mapped[str] = mapped_column(String(255), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    session_file: Mapped["UploadSessionFileRecord"] = relationship(back_populates="parts")
