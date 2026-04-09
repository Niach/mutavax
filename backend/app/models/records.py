from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
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


class IngestionBatchRecord(Base):
    __tablename__ = "ingestion_batches"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
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
