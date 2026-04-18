from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.runtime import get_local_sqlite_path as get_runtime_sqlite_path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent


class Base(DeclarativeBase):
    pass


def get_local_sqlite_path() -> Path:
    return get_runtime_sqlite_path()


def get_database_url() -> str:
    sqlite_path = get_local_sqlite_path()
    sqlite_path.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{sqlite_path}"


def _create_engine():
    database_url = get_database_url()
    connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
    return create_engine(
        database_url,
        future=True,
        pool_pre_ping=True,
        connect_args=connect_args,
    )


engine = _create_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


@contextmanager
def session_scope():
    session: Session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def init_db() -> None:
    from app.models.records import (
        IngestionBatchRecord,
        PipelineArtifactRecord,
        PipelineRunRecord,
        WorkspaceFileRecord,
        WorkspaceRecord,
    )

    _ = (
        WorkspaceRecord,
        IngestionBatchRecord,
        WorkspaceFileRecord,
        PipelineRunRecord,
        PipelineArtifactRecord,
    )
    Base.metadata.create_all(bind=engine)
    _ensure_schema_updates()


def _ensure_schema_updates() -> None:
    inspector = inspect(engine)

    _ensure_column(
        inspector,
        "ingestion_batches",
        "sample_lane",
        "VARCHAR(16) NOT NULL DEFAULT 'tumor'",
    )
    _ensure_column(
        inspector,
        "ingestion_batches",
        "sample_stem",
        "VARCHAR(255)",
    )
    _ensure_column(
        inspector,
        "ingestion_batches",
        "progress_phase",
        "VARCHAR(64)",
    )
    _ensure_column(
        inspector,
        "ingestion_batches",
        "progress_current_filename",
        "VARCHAR(512)",
    )
    _ensure_column(
        inspector,
        "ingestion_batches",
        "progress_bytes_processed",
        "BIGINT",
    )
    _ensure_column(
        inspector,
        "ingestion_batches",
        "progress_total_bytes",
        "BIGINT",
    )
    _ensure_column(
        inspector,
        "ingestion_batches",
        "progress_throughput_bytes_per_sec",
        "FLOAT",
    )
    _ensure_column(
        inspector,
        "ingestion_batches",
        "progress_eta_seconds",
        "FLOAT",
    )
    _ensure_column(
        inspector,
        "ingestion_batches",
        "progress_percent",
        "FLOAT",
    )
    _ensure_column(
        inspector,
        "workspace_files",
        "sample_lane",
        "VARCHAR(16) NOT NULL DEFAULT 'tumor'",
    )
    _ensure_column(
        inspector,
        "workspaces",
        "reference_preset",
        "VARCHAR(32)",
    )
    _ensure_column(
        inspector,
        "workspaces",
        "reference_override",
        "VARCHAR(1024)",
    )
    _ensure_column(
        inspector,
        "workspace_files",
        "source_path",
        "VARCHAR(4096)",
    )
    _ensure_column(
        inspector,
        "workspace_files",
        "local_path",
        "VARCHAR(4096)",
    )
    _ensure_column(
        inspector,
        "pipeline_artifacts",
        "local_path",
        "VARCHAR(4096)",
    )
    _ensure_column(
        inspector,
        "pipeline_runs",
        "runtime_phase",
        "VARCHAR(64)",
    )
    _ensure_column(
        inspector,
        "workspaces",
        "neoantigen_config",
        "TEXT",
    )
    _ensure_workspace_file_storage_key_not_unique()


def _ensure_column(inspector, table_name: str, column_name: str, definition: str) -> None:
    if table_name not in inspector.get_table_names():
        return

    existing_columns = {column["name"] for column in inspector.get_columns(table_name)}
    if column_name in existing_columns:
        return

    with engine.begin() as connection:
        connection.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}"))


def _ensure_workspace_file_storage_key_not_unique() -> None:
    inspector = inspect(engine)
    if "workspace_files" not in inspector.get_table_names():
        return

    with engine.begin() as connection:
        unique_storage_key_indexes = []
        for index_row in connection.execute(text("PRAGMA index_list('workspace_files')")).mappings():
            if not index_row["unique"]:
                continue
            index_name = index_row["name"]
            columns = [
                column_row["name"]
                for column_row in connection.execute(
                    text(f"PRAGMA index_info('{index_name}')")
                ).mappings()
            ]
            if columns == ["storage_key"]:
                unique_storage_key_indexes.append(index_name)

        if not unique_storage_key_indexes:
            return

        connection.execute(text("PRAGMA foreign_keys=OFF"))
        try:
            connection.execute(
                text(
                    """
                    CREATE TABLE workspace_files__migrated (
                        id VARCHAR(36) NOT NULL PRIMARY KEY,
                        workspace_id VARCHAR(36) NOT NULL,
                        batch_id VARCHAR(36) NOT NULL,
                        source_file_id VARCHAR(36),
                        sample_lane VARCHAR(16) NOT NULL DEFAULT 'tumor',
                        filename VARCHAR(512) NOT NULL,
                        format VARCHAR(32) NOT NULL,
                        file_role VARCHAR(32) NOT NULL,
                        status VARCHAR(32) NOT NULL,
                        read_pair VARCHAR(32) NOT NULL,
                        storage_key VARCHAR(1024) NOT NULL,
                        source_path VARCHAR(4096),
                        local_path VARCHAR(4096),
                        size_bytes BIGINT NOT NULL,
                        uploaded_at DATETIME NOT NULL,
                        error TEXT,
                        FOREIGN KEY(workspace_id) REFERENCES workspaces (id) ON DELETE CASCADE,
                        FOREIGN KEY(batch_id) REFERENCES ingestion_batches (id) ON DELETE CASCADE,
                        FOREIGN KEY(source_file_id) REFERENCES workspace_files (id) ON DELETE SET NULL
                    )
                    """
                )
            )
            connection.execute(
                text(
                    """
                    INSERT INTO workspace_files__migrated (
                        id,
                        workspace_id,
                        batch_id,
                        source_file_id,
                        sample_lane,
                        filename,
                        format,
                        file_role,
                        status,
                        read_pair,
                        storage_key,
                        source_path,
                        local_path,
                        size_bytes,
                        uploaded_at,
                        error
                    )
                    SELECT
                        id,
                        workspace_id,
                        batch_id,
                        source_file_id,
                        sample_lane,
                        filename,
                        format,
                        file_role,
                        status,
                        read_pair,
                        storage_key,
                        source_path,
                        local_path,
                        size_bytes,
                        uploaded_at,
                        error
                    FROM workspace_files
                    """
                )
            )
            connection.execute(text("DROP TABLE workspace_files"))
            connection.execute(
                text("ALTER TABLE workspace_files__migrated RENAME TO workspace_files")
            )
            connection.execute(
                text(
                    "CREATE INDEX ix_workspace_files_workspace_id "
                    "ON workspace_files (workspace_id)"
                )
            )
            connection.execute(
                text(
                    "CREATE INDEX ix_workspace_files_batch_id "
                    "ON workspace_files (batch_id)"
                )
            )
            connection.execute(
                text(
                    "CREATE INDEX ix_workspace_files_source_file_id "
                    "ON workspace_files (source_file_id)"
                )
            )
            connection.execute(
                text(
                    "CREATE INDEX ix_workspace_files_sample_lane "
                    "ON workspace_files (sample_lane)"
                )
            )
        finally:
            connection.execute(text("PRAGMA foreign_keys=ON"))
