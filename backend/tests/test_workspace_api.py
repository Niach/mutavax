import gzip
import io
from typing import Optional

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete

from app.db import init_db, session_scope
from app.main import app
from app.models.records import IngestionBatchRecord, WorkspaceFileRecord, WorkspaceRecord
from app.services import workspace_store


class FakeStorage:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def upload_fileobj(self, fileobj, key: str, content_type: Optional[str] = None) -> None:
        fileobj.seek(0)
        self.objects[key] = fileobj.read()

    def upload_path(self, path, key: str, content_type: Optional[str] = None) -> None:
        self.objects[key] = path.read_bytes()

    def copy_object(self, source_key: str, destination_key: str) -> None:
        self.objects[destination_key] = self.objects[source_key]

    def download_path(self, key: str, destination) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(self.objects[key])


def gzip_bytes(payload: bytes) -> bytes:
    buffer = io.BytesIO()
    with gzip.GzipFile(fileobj=buffer, mode="wb") as handle:
        handle.write(payload)
    return buffer.getvalue()


@pytest.fixture(autouse=True)
def clean_database():
    init_db()
    with session_scope() as session:
        session.execute(delete(WorkspaceFileRecord))
        session.execute(delete(IngestionBatchRecord))
        session.execute(delete(WorkspaceRecord))
    yield
    with session_scope() as session:
        session.execute(delete(WorkspaceFileRecord))
        session.execute(delete(IngestionBatchRecord))
        session.execute(delete(WorkspaceRecord))


@pytest.fixture
def fake_storage(monkeypatch: pytest.MonkeyPatch) -> FakeStorage:
    storage = FakeStorage()
    monkeypatch.setattr(workspace_store, "get_storage", lambda: storage)
    return storage


@pytest.fixture
def queued_batches(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    batches: list[str] = []
    monkeypatch.setattr(
        workspace_store,
        "enqueue_batch_normalization",
        lambda batch_id: batches.append(batch_id),
    )
    return batches


@pytest.fixture
def client() -> TestClient:
    with TestClient(app) as test_client:
        yield test_client


def create_workspace(client: TestClient, name: str = "Rosie", species: str = "dog") -> dict:
    response = client.post(
        "/api/workspaces",
        json={"display_name": name, "species": species},
    )
    assert response.status_code == 201
    return response.json()


def upload_files(client: TestClient, workspace_id: str, files: list[tuple[str, bytes, str]]) -> dict:
    response = client.post(
        f"/api/workspaces/{workspace_id}/files",
        files=[("files", file_payload) for file_payload in files],
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_creates_workspace_with_minimal_fields(client: TestClient):
    payload = create_workspace(client, name="Feline Case", species="cat")

    assert payload["display_name"] == "Feline Case"
    assert payload["species"] == "cat"
    assert payload["active_stage"] == "ingestion"
    assert payload["ingestion"]["status"] == "empty"
    assert payload["files"] == []


def test_uploading_paired_fastq_gz_becomes_alignment_ready(
    client: TestClient,
    fake_storage: FakeStorage,
    queued_batches: list[str],
):
    workspace = create_workspace(client)
    payload = upload_files(
        client,
        workspace["id"],
        [
            ("sample_R1.fastq.gz", gzip_bytes(b"@r1\nACGT\n+\n!!!!\n"), "application/gzip"),
            ("sample_R2.fastq.gz", gzip_bytes(b"@r2\nTGCA\n+\n!!!!\n"), "application/gzip"),
        ],
    )

    assert queued_batches == []
    assert payload["ingestion"]["status"] == "ready"
    assert payload["ingestion"]["ready_for_alignment"] is True
    assert payload["ingestion"]["canonical_file_count"] == 2
    assert {file["file_role"] for file in payload["files"]} == {"source", "canonical"}
    assert any("canonical/" in key for key in fake_storage.objects)


def test_uncompressed_fastq_batch_queues_then_normalizes(
    client: TestClient,
    fake_storage: FakeStorage,
    queued_batches: list[str],
):
    workspace = create_workspace(client)
    payload = upload_files(
        client,
        workspace["id"],
        [
            ("sample_R1.fastq", b"@r1\nACGT\n+\n!!!!\n", "text/plain"),
            ("sample_R2.fastq", b"@r2\nTGCA\n+\n!!!!\n", "text/plain"),
        ],
    )

    assert payload["ingestion"]["status"] == "normalizing"
    assert len(queued_batches) == 1

    normalized = workspace_store.run_batch_normalization(queued_batches[0])

    assert normalized.ingestion.status == "ready"
    assert normalized.ingestion.ready_for_alignment is True
    assert normalized.ingestion.canonical_file_count == 2
    assert any(file.file_role == "canonical" for file in normalized.files)


def test_unsupported_upload_returns_clear_error(
    client: TestClient,
    fake_storage: FakeStorage,
    queued_batches: list[str],
):
    workspace = create_workspace(client)
    response = client.post(
        f"/api/workspaces/{workspace['id']}/files",
        files=[("files", ("variants.vcf", b"##fileformat=VCFv4.2\n", "text/plain"))],
    )

    assert response.status_code == 400
    assert "Accepted inputs are FASTQ, BAM, and CRAM" in response.text
    assert queued_batches == []


def test_failed_normalization_marks_latest_batch_failed(
    client: TestClient,
    fake_storage: FakeStorage,
    queued_batches: list[str],
    monkeypatch: pytest.MonkeyPatch,
):
    workspace = create_workspace(client)
    payload = upload_files(
        client,
        workspace["id"],
        [("sample.bam", b"bam-placeholder", "application/octet-stream")],
    )

    assert payload["ingestion"]["status"] == "normalizing"
    assert len(queued_batches) == 1

    def fail_samtools(*args, **kwargs):
        raise RuntimeError("samtools conversion failed")

    monkeypatch.setattr(workspace_store, "run_samtools_fastq", fail_samtools)

    with pytest.raises(RuntimeError):
        workspace_store.run_batch_normalization(queued_batches[0])

    failed_workspace = workspace_store.load_workspace(workspace["id"])
    assert failed_workspace.ingestion.status == "failed"
    assert any(file.status == "failed" for file in failed_workspace.files)


def test_latest_batch_controls_ingestion_readiness(
    client: TestClient,
    fake_storage: FakeStorage,
    queued_batches: list[str],
):
    workspace = create_workspace(client)

    first_batch = upload_files(
        client,
        workspace["id"],
        [
            ("sample_R1.fastq.gz", gzip_bytes(b"@r1\nACGT\n+\n!!!!\n"), "application/gzip"),
            ("sample_R2.fastq.gz", gzip_bytes(b"@r2\nTGCA\n+\n!!!!\n"), "application/gzip"),
        ],
    )
    first_batch_id = first_batch["ingestion"]["active_batch_id"]
    assert first_batch["ingestion"]["status"] == "ready"

    second_batch = upload_files(
        client,
        workspace["id"],
        [("sample_repeat_R1.fastq.gz", gzip_bytes(b"@r1\nACGT\n+\n!!!!\n"), "application/gzip")],
    )

    assert second_batch["ingestion"]["active_batch_id"] != first_batch_id
    assert second_batch["ingestion"]["status"] == "uploaded"
    assert second_batch["ingestion"]["ready_for_alignment"] is False
    assert second_batch["ingestion"]["missing_pairs"] == ["R2"]
