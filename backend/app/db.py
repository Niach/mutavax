import os
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
DEFAULT_SQLITE_PATH = BACKEND_ROOT / "data" / "app.db"


class Base(DeclarativeBase):
    pass


def get_local_sqlite_path() -> Path:
    configured = os.getenv("LOCAL_SQLITE_PATH")
    if not configured:
        return DEFAULT_SQLITE_PATH

    configured_path = Path(configured).expanduser()
    if configured_path.is_absolute():
        return configured_path

    return (REPO_ROOT / configured_path).resolve()


def get_database_url() -> str:
    configured = os.getenv("DATABASE_URL")
    if configured:
        return configured

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
        UploadSessionFileRecord,
        UploadSessionPartRecord,
        UploadSessionRecord,
        WorkspaceFileRecord,
        WorkspaceRecord,
    )

    _ = (
        WorkspaceRecord,
        IngestionBatchRecord,
        WorkspaceFileRecord,
        UploadSessionRecord,
        UploadSessionFileRecord,
        UploadSessionPartRecord,
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
        "workspace_files",
        "sample_lane",
        "VARCHAR(16) NOT NULL DEFAULT 'tumor'",
    )
    _ensure_bigint_column(inspector, "workspace_files", "size_bytes")
    _ensure_bigint_column(inspector, "upload_session_files", "size_bytes")
    _ensure_bigint_column(inspector, "upload_session_files", "uploaded_bytes")
    _ensure_bigint_column(inspector, "upload_session_files", "last_modified_ms")
    _ensure_bigint_column(inspector, "upload_session_parts", "size_bytes")


def _ensure_column(inspector, table_name: str, column_name: str, definition: str) -> None:
    if table_name not in inspector.get_table_names():
        return

    existing_columns = {column["name"] for column in inspector.get_columns(table_name)}
    if column_name in existing_columns:
        return

    with engine.begin() as connection:
        connection.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}"))


def _ensure_bigint_column(inspector, table_name: str, column_name: str) -> None:
    if engine.dialect.name != "postgresql":
        return

    if table_name not in inspector.get_table_names():
        return

    columns = {
        column["name"]: column
        for column in inspector.get_columns(table_name)
    }
    column = columns.get(column_name)
    if column is None:
        return

    type_name = str(column["type"]).upper()
    if "BIGINT" in type_name or "INT8" in type_name:
        return

    with engine.begin() as connection:
        connection.execute(
            text(
                f"ALTER TABLE {table_name} "
                f"ALTER COLUMN {column_name} TYPE BIGINT "
                f"USING {column_name}::bigint"
            )
        )
