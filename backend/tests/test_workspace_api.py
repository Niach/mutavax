import gzip
import io
import uuid
from pathlib import Path
from typing import Optional

import httpx
import pytest
from sqlalchemy import delete

from app.db import init_db, session_scope
from app.main import app
from app.models.records import (
    IngestionBatchRecord,
    UploadSessionFileRecord,
    UploadSessionPartRecord,
    UploadSessionRecord,
    WorkspaceFileRecord,
    WorkspaceRecord,
)
from app.services import workspace_store


class FakeStorage:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.multipart_uploads: dict[str, dict[int, bytes]] = {}
        self.deleted_keys: list[str] = []
        self.aborted_uploads: list[tuple[str, str]] = []

    def upload_fileobj(self, fileobj, key: str, content_type: Optional[str] = None) -> None:
        fileobj.seek(0)
        self.objects[key] = fileobj.read()

    def upload_path(self, path: Path, key: str, content_type: Optional[str] = None) -> None:
        self.objects[key] = path.read_bytes()

    def copy_object(self, source_key: str, destination_key: str) -> None:
        self.objects[destination_key] = self.objects[source_key]

    def download_path(self, key: str, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(self.objects[key])

    def open_read_stream(self, key: str):
        if key not in self.objects:
            raise FileNotFoundError(f"Stored object {key} was not found")
        return io.BytesIO(self.objects[key])

    def create_multipart_upload(self, key: str, content_type: Optional[str] = None) -> str:
        upload_id = str(uuid.uuid4())
        self.multipart_uploads[upload_id] = {}
        return upload_id

    def upload_part(self, key: str, upload_id: str, part_number: int, body: bytes) -> str:
        self.multipart_uploads[upload_id][part_number] = body
        return f"etag-{part_number}"

    def complete_multipart_upload(
        self,
        key: str,
        upload_id: str,
        parts: list[dict[str, object]],
    ) -> None:
        ordered = [
            self.multipart_uploads[upload_id][int(part["PartNumber"])]
            for part in parts
        ]
        self.objects[key] = b"".join(ordered)
        self.multipart_uploads.pop(upload_id, None)

    def abort_multipart_upload(self, key: str, upload_id: str) -> None:
        self.multipart_uploads.pop(upload_id, None)
        self.aborted_uploads.append((key, upload_id))

    def delete_object(self, key: str) -> None:
        self.objects.pop(key, None)
        self.deleted_keys.append(key)


def gzip_bytes(payload: bytes) -> bytes:
    buffer = io.BytesIO()
    with gzip.GzipFile(fileobj=buffer, mode="wb") as handle:
        handle.write(payload)
    return buffer.getvalue()


@pytest.fixture(autouse=True)
def clean_database():
    init_db()
    with session_scope() as session:
        session.execute(delete(UploadSessionPartRecord))
        session.execute(delete(UploadSessionFileRecord))
        session.execute(delete(UploadSessionRecord))
        session.execute(delete(WorkspaceFileRecord))
        session.execute(delete(IngestionBatchRecord))
        session.execute(delete(WorkspaceRecord))
    yield
    with session_scope() as session:
        session.execute(delete(UploadSessionPartRecord))
        session.execute(delete(UploadSessionFileRecord))
        session.execute(delete(UploadSessionRecord))
        session.execute(delete(WorkspaceFileRecord))
        session.execute(delete(IngestionBatchRecord))
        session.execute(delete(WorkspaceRecord))


@pytest.fixture
def fake_storage(monkeypatch: pytest.MonkeyPatch) -> FakeStorage:
    storage = FakeStorage()
    monkeypatch.setattr(workspace_store, "get_storage", lambda: storage)
    return storage


@pytest.fixture
def queued_batches(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str]]:
    batches: list[tuple[str, str]] = []
    monkeypatch.setattr(
        workspace_store,
        "enqueue_batch_normalization",
        lambda workspace_id, batch_id: batches.append((workspace_id, batch_id)),
    )
    return batches


@pytest.fixture
async def client():
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
            follow_redirects=True,
        ) as test_client:
            yield test_client


async def create_workspace(
    client: httpx.AsyncClient,
    name: str = "Rosie",
    species: str = "dog",
) -> dict:
    response = await client.post(
        "/api/workspaces",
        json={"display_name": name, "species": species},
    )
    assert response.status_code == 201, response.text
    return response.json()


async def create_session(
    client: httpx.AsyncClient,
    workspace_id: str,
    sample_lane: str,
    files: list[tuple[str, bytes, str, int]],
) -> dict:
    response = await client.post(
        f"/api/workspaces/{workspace_id}/ingestion/sessions",
        json={
            "sample_lane": sample_lane,
            "files": [
                {
                    "filename": filename,
                    "size_bytes": len(payload),
                    "last_modified_ms": last_modified_ms,
                    "content_type": content_type,
                }
                for filename, payload, content_type, last_modified_ms in files
            ],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


async def upload_parts_for_file(
    client: httpx.AsyncClient,
    workspace_id: str,
    session: dict,
    filename: str,
    payload: bytes,
) -> None:
    session_file = next(file for file in session["files"] if file["filename"] == filename)
    for part_number in range(1, session_file["total_parts"] + 1):
        start = (part_number - 1) * session["chunk_size_bytes"]
        end = min(len(payload), start + session["chunk_size_bytes"])
        response = await client.put(
            f"/api/workspaces/{workspace_id}/ingestion/sessions/{session['id']}/files/{session_file['id']}/parts/{part_number}",
            content=payload[start:end],
        )
        assert response.status_code == 200, response.text

    response = await client.post(
        f"/api/workspaces/{workspace_id}/ingestion/sessions/{session['id']}/files/{session_file['id']}/complete"
    )
    assert response.status_code == 200, response.text


async def commit_session(
    client: httpx.AsyncClient,
    workspace_id: str,
    session_id: str,
) -> dict:
    response = await client.post(
        f"/api/workspaces/{workspace_id}/ingestion/sessions/{session_id}/commit"
    )
    assert response.status_code == 200, response.text
    return response.json()


async def load_workspace(client: httpx.AsyncClient, workspace_id: str) -> dict:
    response = await client.get(f"/api/workspaces/{workspace_id}")
    assert response.status_code == 200, response.text
    return response.json()


async def normalize_lane(
    client: httpx.AsyncClient,
    workspace_id: str,
    sample_lane: str,
    files: list[tuple[str, bytes, str, int]],
    queued_batches: list[tuple[str, str]],
) -> dict:
    session = await create_session(client, workspace_id, sample_lane, files)
    for filename, payload, _content_type, _last_modified in files:
        await upload_parts_for_file(client, workspace_id, session, filename, payload)
    await commit_session(client, workspace_id, session["id"])
    queued_workspace_id, queued_batch_id = queued_batches.pop(0)
    return workspace_store.run_batch_normalization(queued_workspace_id, queued_batch_id).model_dump()


@pytest.mark.anyio
async def test_rejects_whitespace_only_workspace_names(client: httpx.AsyncClient):
    response = await client.post(
        "/api/workspaces",
        json={"display_name": "   ", "species": "dog"},
    )

    assert response.status_code == 400
    assert "cannot be empty" in response.text


@pytest.mark.anyio
async def test_lane_uploads_require_both_tumor_and_normal_before_alignment_ready(
    client: httpx.AsyncClient,
    fake_storage: FakeStorage,
    queued_batches: list[tuple[str, str]],
):
    workspace = await create_workspace(client)

    tumor_files = [
        ("tumor_S1_L001_R1_001.fastq.gz", gzip_bytes(b"@r1\nACGT\n+\n!!!!\n"), "application/gzip", 1),
        ("tumor_S1_L001_R2_001.fastq.gz", gzip_bytes(b"@r2\nTGCA\n+\n!!!!\n"), "application/gzip", 2),
    ]
    tumor_session = await create_session(client, workspace["id"], "tumor", tumor_files)
    for filename, payload, _content_type, _last_modified in tumor_files:
        await upload_parts_for_file(client, workspace["id"], tumor_session, filename, payload)

    payload = await commit_session(client, workspace["id"], tumor_session["id"])
    assert payload["ingestion"]["ready_for_alignment"] is False
    assert payload["ingestion"]["lanes"]["tumor"]["status"] == "normalizing"
    assert payload["ingestion"]["lanes"]["normal"]["status"] == "empty"

    tumor_workspace_id, tumor_batch_id = queued_batches.pop(0)
    normalized = workspace_store.run_batch_normalization(tumor_workspace_id, tumor_batch_id)
    assert normalized.ingestion.lanes["tumor"].status == "ready"
    assert normalized.ingestion.ready_for_alignment is False

    normal_files = [
        ("normal_S1_L001_R1_001.fastq.gz", gzip_bytes(b"@n1\nCCCC\n+\n!!!!\n"), "application/gzip", 3),
        ("normal_S1_L001_R2_001.fastq.gz", gzip_bytes(b"@n2\nGGGG\n+\n!!!!\n"), "application/gzip", 4),
    ]
    normal_session = await create_session(client, workspace["id"], "normal", normal_files)
    for filename, payload, _content_type, _last_modified in normal_files:
        await upload_parts_for_file(client, workspace["id"], normal_session, filename, payload)

    payload = await commit_session(client, workspace["id"], normal_session["id"])
    assert payload["ingestion"]["ready_for_alignment"] is False
    normal_workspace_id, normal_batch_id = queued_batches.pop(0)
    normalized = workspace_store.run_batch_normalization(normal_workspace_id, normal_batch_id)

    assert normalized.ingestion.ready_for_alignment is True
    assert normalized.ingestion.lanes["tumor"].status == "ready"
    assert normalized.ingestion.lanes["normal"].status == "ready"
    assert {
        file.sample_lane for file in normalized.files if file.file_role == "canonical"
    } == {"tumor", "normal"}


@pytest.mark.anyio
async def test_resumable_session_preserves_uploaded_bytes(
    client: httpx.AsyncClient,
    fake_storage: FakeStorage,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(workspace_store, "CHUNK_SIZE_BYTES", 8)

    workspace = await create_workspace(client)
    payload = b"ABCDEFGHIJKL"
    session = await create_session(
        client,
        workspace["id"],
        "tumor",
        [("tumor_R1.fastq.gz", payload, "application/gzip", 10)],
    )
    session_file = session["files"][0]

    response = await client.put(
        f"/api/workspaces/{workspace['id']}/ingestion/sessions/{session['id']}/files/{session_file['id']}/parts/1",
        content=payload[:8],
    )
    assert response.status_code == 200, response.text
    assert response.json()["uploaded_bytes"] == 8

    sessions = await client.get(f"/api/workspaces/{workspace['id']}/ingestion/sessions")
    assert sessions.status_code == 200
    restored = sessions.json()[0]
    assert restored["files"][0]["uploaded_bytes"] == 8
    assert restored["files"][0]["completed_part_numbers"] == [1]


@pytest.mark.anyio
async def test_upload_session_accepts_large_timestamps_and_file_sizes(
    client: httpx.AsyncClient,
    fake_storage: FakeStorage,
):
    workspace = await create_workspace(client)

    response = await client.post(
        f"/api/workspaces/{workspace['id']}/ingestion/sessions",
        json={
            "sample_lane": "tumor",
            "files": [
                {
                    "filename": "tumor_R1.fastq.gz",
                    "size_bytes": 3 * 1024 * 1024 * 1024,
                    "last_modified_ms": 1775842214346,
                    "content_type": "application/gzip",
                },
                {
                    "filename": "tumor_R2.fastq.gz",
                    "size_bytes": 3 * 1024 * 1024 * 1024 + 512,
                    "last_modified_ms": 1775842217632,
                    "content_type": "application/gzip",
                },
            ],
        },
    )

    assert response.status_code == 201, response.text
    payload = response.json()
    assert [file["last_modified_ms"] for file in payload["files"]] == [
        1775842214346,
        1775842217632,
    ]
    assert [file["size_bytes"] for file in payload["files"]] == [
        3 * 1024 * 1024 * 1024,
        3 * 1024 * 1024 * 1024 + 512,
    ]


@pytest.mark.anyio
async def test_parts_can_arrive_out_of_order_and_duplicate_or_oversized_parts_fail(
    client: httpx.AsyncClient,
    fake_storage: FakeStorage,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(workspace_store, "CHUNK_SIZE_BYTES", 4)

    workspace = await create_workspace(client)
    payload = b"ABCDEFGHIJ"
    session = await create_session(
        client,
        workspace["id"],
        "tumor",
        [("tumor_R1.fastq.gz", payload, "application/gzip", 11)],
    )
    session_file = session["files"][0]
    base_path = (
        f"/api/workspaces/{workspace['id']}/ingestion/sessions/{session['id']}"
        f"/files/{session_file['id']}/parts"
    )

    response = await client.put(f"{base_path}/3", content=payload[8:10])
    assert response.status_code == 200, response.text
    response = await client.put(f"{base_path}/2", content=payload[4:8])
    assert response.status_code == 200, response.text
    response = await client.put(f"{base_path}/1", content=payload[0:4])
    assert response.status_code == 200, response.text

    duplicate = await client.put(f"{base_path}/1", content=payload[0:4])
    assert duplicate.status_code == 400
    assert "already uploaded" in duplicate.text

    oversized = await client.put(f"{base_path}/2", content=b"TOO-LONG")
    assert oversized.status_code == 400

    complete = await client.post(
        f"/api/workspaces/{workspace['id']}/ingestion/sessions/{session['id']}/files/{session_file['id']}/complete"
    )
    assert complete.status_code == 200, complete.text


@pytest.mark.anyio
async def test_multi_file_fastq_lane_merges_into_one_canonical_pair(
    client: httpx.AsyncClient,
    fake_storage: FakeStorage,
    queued_batches: list[tuple[str, str]],
):
    workspace = await create_workspace(client)
    files = [
        ("tumor_S1_L001_R1_001.fastq.gz", gzip_bytes(b"@r1a\nAAAA\n+\n!!!!\n"), "application/gzip", 20),
        ("tumor_S1_L002_R1_001.fastq.gz", gzip_bytes(b"@r1b\nCCCC\n+\n!!!!\n"), "application/gzip", 21),
        ("tumor_S1_L001_R2_001.fastq.gz", gzip_bytes(b"@r2a\nTTTT\n+\n!!!!\n"), "application/gzip", 22),
        ("tumor_S1_L002_R2_001.fastq.gz", gzip_bytes(b"@r2b\nGGGG\n+\n!!!!\n"), "application/gzip", 23),
    ]
    session = await create_session(client, workspace["id"], "tumor", files)
    for filename, payload, _content_type, _last_modified in files:
        await upload_parts_for_file(client, workspace["id"], session, filename, payload)

    await commit_session(client, workspace["id"], session["id"])
    workspace_id, batch_id = queued_batches.pop(0)
    normalized = workspace_store.run_batch_normalization(workspace_id, batch_id)

    canonical_files = [file for file in normalized.files if file.file_role == "canonical"]
    assert len(canonical_files) == 2
    assert {file.filename for file in canonical_files} == {
        "tumor_R1.normalized.fastq.gz",
        "tumor_R2.normalized.fastq.gz",
    }

    r1_key = next(file.storage_key for file in canonical_files if file.read_pair == "R1")
    with gzip.GzipFile(fileobj=io.BytesIO(fake_storage.objects[r1_key]), mode="rb") as handle:
        assert handle.read() == b"@r1a\nAAAA\n+\n!!!!\n@r1b\nCCCC\n+\n!!!!\n"


@pytest.mark.anyio
async def test_mixed_fastq_and_bam_in_one_lane_fails_validation(
    client: httpx.AsyncClient,
    fake_storage: FakeStorage,
):
    workspace = await create_workspace(client)
    files = [
        ("tumor_R1.fastq.gz", gzip_bytes(b"@r1\nAAAA\n+\n!!!!\n"), "application/gzip", 30),
        ("tumor.bam", b"bam-placeholder", "application/octet-stream", 31),
    ]
    session = await create_session(client, workspace["id"], "tumor", files)
    for filename, payload, _content_type, _last_modified in files:
        await upload_parts_for_file(client, workspace["id"], session, filename, payload)

    response = await client.post(
        f"/api/workspaces/{workspace['id']}/ingestion/sessions/{session['id']}/commit"
    )
    assert response.status_code == 400
    assert "format family" in response.text

    current = await load_workspace(client, workspace["id"])
    assert current["ingestion"]["lanes"]["tumor"]["status"] == "failed"


@pytest.mark.anyio
async def test_unnamed_fastq_lane_rejected_as_paired_required(
    client: httpx.AsyncClient,
    fake_storage: FakeStorage,
):
    workspace = await create_workspace(client)
    files = [("tumor.fastq.gz", gzip_bytes(b"@r1\nAAAA\n+\n!!!!\n"), "application/gzip", 40)]
    session = await create_session(client, workspace["id"], "tumor", files)
    for filename, payload, _content_type, _last_modified in files:
        await upload_parts_for_file(client, workspace["id"], session, filename, payload)

    response = await client.post(
        f"/api/workspaces/{workspace['id']}/ingestion/sessions/{session['id']}/commit"
    )
    assert response.status_code == 400
    assert "Paired-end required" in response.text

    current = await load_workspace(client, workspace["id"])
    assert current["ingestion"]["lanes"]["tumor"]["status"] == "failed"


@pytest.mark.anyio
async def test_ena_style_underscore_fastq_names_normalize_as_paired(
    client: httpx.AsyncClient,
    fake_storage: FakeStorage,
    queued_batches: list[tuple[str, str]],
):
    workspace = await create_workspace(client)
    files = [
        ("SRR7890850_1.fastq.gz", gzip_bytes(b"@r1\nAAAA\n+\n!!!!\n"), "application/gzip", 41),
        ("SRR7890850_2.fastq.gz", gzip_bytes(b"@r2\nCCCC\n+\n!!!!\n"), "application/gzip", 42),
    ]
    normalized = await normalize_lane(
        client, workspace["id"], "tumor", files, queued_batches
    )
    tumor_lane = normalized["ingestion"]["lanes"]["tumor"]
    assert tumor_lane["status"] == "ready"
    assert tumor_lane["read_layout"] == "paired"
    assert tumor_lane["ready_for_alignment"] is True


@pytest.mark.anyio
async def test_single_r1_fastq_lane_rejected_as_paired_required(
    client: httpx.AsyncClient,
    fake_storage: FakeStorage,
):
    workspace = await create_workspace(client)
    files = [
        ("rosie_tumor_R1.fastq.gz", gzip_bytes(b"@r1\nAAAA\n+\n!!!!\n"), "application/gzip", 43),
    ]
    session = await create_session(client, workspace["id"], "tumor", files)
    await upload_parts_for_file(client, workspace["id"], session, files[0][0], files[0][1])

    response = await client.post(
        f"/api/workspaces/{workspace['id']}/ingestion/sessions/{session['id']}/commit"
    )
    assert response.status_code == 400
    assert "Paired-end required" in response.text
    assert "R2 file" in response.text

    current = await load_workspace(client, workspace["id"])
    assert current["ingestion"]["lanes"]["tumor"]["status"] == "failed"


@pytest.mark.anyio
async def test_r2_only_fastq_lane_fails_validation(
    client: httpx.AsyncClient,
    fake_storage: FakeStorage,
):
    workspace = await create_workspace(client)
    files = [
        ("rosie_tumor_R2.fastq.gz", gzip_bytes(b"@r2\nCCCC\n+\n!!!!\n"), "application/gzip", 44),
    ]
    session = await create_session(client, workspace["id"], "tumor", files)
    await upload_parts_for_file(client, workspace["id"], session, files[0][0], files[0][1])

    response = await client.post(
        f"/api/workspaces/{workspace['id']}/ingestion/sessions/{session['id']}/commit"
    )
    assert response.status_code == 400
    assert "R2 files need matching R1" in response.text


@pytest.mark.anyio
async def test_mixed_marked_and_unmarked_fastq_fails_validation(
    client: httpx.AsyncClient,
    fake_storage: FakeStorage,
):
    workspace = await create_workspace(client)
    files = [
        ("rosie_tumor_R1.fastq.gz", gzip_bytes(b"@r1\nAAAA\n+\n!!!!\n"), "application/gzip", 45),
        ("tumor.fastq.gz", gzip_bytes(b"@r1\nGGGG\n+\n!!!!\n"), "application/gzip", 46),
    ]
    session = await create_session(client, workspace["id"], "tumor", files)
    for filename, payload, _content_type, _last_modified in files:
        await upload_parts_for_file(client, workspace["id"], session, filename, payload)

    response = await client.post(
        f"/api/workspaces/{workspace['id']}/ingestion/sessions/{session['id']}/commit"
    )
    assert response.status_code == 400
    assert "Cannot mix" in response.text


@pytest.mark.anyio
async def test_multi_stem_fastq_lane_fails_validation(
    client: httpx.AsyncClient,
    fake_storage: FakeStorage,
):
    workspace = await create_workspace(client)
    files = [
        ("sampleA_R1.fastq.gz", gzip_bytes(b"@r1\nAAAA\n+\n!!!!\n"), "application/gzip", 50),
        ("sampleB_R2.fastq.gz", gzip_bytes(b"@r2\nCCCC\n+\n!!!!\n"), "application/gzip", 51),
    ]
    session = await create_session(client, workspace["id"], "tumor", files)
    for filename, payload, _content_type, _last_modified in files:
        await upload_parts_for_file(client, workspace["id"], session, filename, payload)

    response = await client.post(
        f"/api/workspaces/{workspace['id']}/ingestion/sessions/{session['id']}/commit"
    )
    assert response.status_code == 400
    assert "exactly one sample family" in response.text


@pytest.mark.anyio
async def test_delete_upload_session_clears_lane_state(
    client: httpx.AsyncClient,
    fake_storage: FakeStorage,
):
    workspace = await create_workspace(client)
    files = [
        ("rosie_tumor_R1.fastq.gz", gzip_bytes(b"@r1\nAAAA\n+\n!!!!\n"), "application/gzip", 70),
        ("rosie_tumor_R2.fastq.gz", gzip_bytes(b"@r2\nCCCC\n+\n!!!!\n"), "application/gzip", 71),
    ]
    session = await create_session(client, workspace["id"], "tumor", files)
    # Upload only the first file's parts to simulate a mid-upload abandon.
    await upload_parts_for_file(client, workspace["id"], session, files[0][0], files[0][1])

    pending = await load_workspace(client, workspace["id"])
    assert pending["ingestion"]["lanes"]["tumor"]["status"] == "uploading"

    response = await client.delete(
        f"/api/workspaces/{workspace['id']}/ingestion/sessions/{session['id']}"
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["ingestion"]["lanes"]["tumor"]["status"] == "empty"

    sessions = await client.get(
        f"/api/workspaces/{workspace['id']}/ingestion/sessions"
    )
    assert sessions.status_code == 200
    assert sessions.json() == []


@pytest.mark.anyio
async def test_reset_workspace_ingestion_clears_batches_files_and_sessions(
    client: httpx.AsyncClient,
    fake_storage: FakeStorage,
    queued_batches: list[tuple[str, str]],
):
    workspace = await create_workspace(client)
    tumor_files = [
        ("tumor_R1.fastq.gz", gzip_bytes(b"@tr1\nAAAA\n+\n!!!!\n"), "application/gzip", 72),
        ("tumor_R2.fastq.gz", gzip_bytes(b"@tr2\nCCCC\n+\n!!!!\n"), "application/gzip", 73),
    ]
    tumor_session = await create_session(client, workspace["id"], "tumor", tumor_files)
    for filename, payload, _content_type, _last_modified in tumor_files:
        await upload_parts_for_file(client, workspace["id"], tumor_session, filename, payload)
    await commit_session(client, workspace["id"], tumor_session["id"])
    queued_workspace_id, queued_batch_id = queued_batches.pop(0)
    normalized = workspace_store.run_batch_normalization(
        queued_workspace_id, queued_batch_id
    ).model_dump()

    pending_session = await create_session(
        client,
        workspace["id"],
        "normal",
        [
            ("normal_R1.fastq.gz", gzip_bytes(b"@nr1\nGGGG\n+\n!!!!\n"), "application/gzip", 74),
            ("normal_R2.fastq.gz", gzip_bytes(b"@nr2\nTTTT\n+\n!!!!\n"), "application/gzip", 75),
        ],
    )

    stage_response = await client.patch(
        f"/api/workspaces/{workspace['id']}/active-stage",
        json={"active_stage": "alignment"},
    )
    assert stage_response.status_code == 200, stage_response.text

    response = await client.delete(f"/api/workspaces/{workspace['id']}/ingestion")
    assert response.status_code == 200, response.text
    payload = response.json()

    assert payload["active_stage"] == "ingestion"
    assert payload["files"] == []
    assert payload["ingestion"]["status"] == "empty"
    assert payload["ingestion"]["ready_for_alignment"] is False
    assert payload["ingestion"]["lanes"]["tumor"]["status"] == "empty"
    assert payload["ingestion"]["lanes"]["normal"]["status"] == "empty"

    sessions = await client.get(f"/api/workspaces/{workspace['id']}/ingestion/sessions")
    assert sessions.status_code == 200
    assert sessions.json() == []

    deleted_keys = set(fake_storage.deleted_keys)
    for file in normalized["files"]:
        assert file["storage_key"] in deleted_keys
    assert len(fake_storage.aborted_uploads) == len(pending_session["files"])


@pytest.mark.anyio
async def test_bam_lane_normalizes_to_paired_fastq(
    client: httpx.AsyncClient,
    fake_storage: FakeStorage,
    queued_batches: list[tuple[str, str]],
    monkeypatch: pytest.MonkeyPatch,
):
    def fake_run_samtools_fastq(
        source_path: Path,
        r1_path: Path,
        r2_path: Path,
        se_path: Path,
        is_cram: bool,
    ) -> None:
        r1_path.write_text("@bam-r1\nACGT\n+\n!!!!\n", encoding="utf-8")
        r2_path.write_text("@bam-r2\nTGCA\n+\n!!!!\n", encoding="utf-8")

    monkeypatch.setattr(workspace_store, "run_samtools_fastq", fake_run_samtools_fastq)

    workspace = await create_workspace(client)
    session = await create_session(
        client,
        workspace["id"],
        "tumor",
        [("tumor.bam", b"bam-placeholder", "application/octet-stream", 101)],
    )
    await upload_parts_for_file(client, workspace["id"], session, "tumor.bam", b"bam-placeholder")
    await commit_session(client, workspace["id"], session["id"])
    queued_workspace_id, queued_batch_id = queued_batches.pop(0)

    normalized = workspace_store.run_batch_normalization(
        queued_workspace_id, queued_batch_id
    ).model_dump()

    tumor_lane = normalized["ingestion"]["lanes"]["tumor"]
    assert tumor_lane["status"] == "ready"
    assert tumor_lane["ready_for_alignment"] is True
    assert normalized["ingestion"]["ready_for_alignment"] is False
    assert {
        file["read_pair"]
        for file in normalized["files"]
        if file["sample_lane"] == "tumor" and file["file_role"] == "canonical"
    } == {"R1", "R2"}


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("filename", "content_type", "is_cram"),
    [
        ("tumor.bam", "application/octet-stream", False),
        ("tumor.cram", "application/octet-stream", True),
    ],
)
async def test_alignment_container_single_end_output_fails_paired_requirement(
    client: httpx.AsyncClient,
    fake_storage: FakeStorage,
    queued_batches: list[tuple[str, str]],
    monkeypatch: pytest.MonkeyPatch,
    filename: str,
    content_type: str,
    is_cram: bool,
):
    expected_is_cram = is_cram

    def fake_run_samtools_fastq(
        source_path: Path,
        r1_path: Path,
        r2_path: Path,
        se_path: Path,
        is_cram: bool,
    ) -> None:
        assert is_cram is expected_is_cram
        se_path.write_text("@single\nACGT\n+\n!!!!\n", encoding="utf-8")

    monkeypatch.setattr(workspace_store, "run_samtools_fastq", fake_run_samtools_fastq)

    workspace = await create_workspace(client)
    session = await create_session(
        client,
        workspace["id"],
        "tumor",
        [(filename, b"alignment-placeholder", content_type, 102)],
    )
    await upload_parts_for_file(
        client,
        workspace["id"],
        session,
        filename,
        b"alignment-placeholder",
    )
    await commit_session(client, workspace["id"], session["id"])
    queued_workspace_id, queued_batch_id = queued_batches.pop(0)

    with pytest.raises(RuntimeError, match="did not produce both R1 and R2"):
        workspace_store.run_batch_normalization(queued_workspace_id, queued_batch_id)

    current = await load_workspace(client, workspace["id"])
    tumor_lane = current["ingestion"]["lanes"]["tumor"]
    assert tumor_lane["status"] == "failed"
    assert tumor_lane["ready_for_alignment"] is False
    assert current["ingestion"]["ready_for_alignment"] is False
    assert "did not produce both R1 and R2" in " ".join(tumor_lane["blocking_issues"])
    assert tumor_lane["missing_pairs"] == ["R1", "R2"]


@pytest.mark.anyio
async def test_legacy_single_end_canonical_lane_serializes_as_failed(
    client: httpx.AsyncClient,
):
    timestamp = workspace_store.utc_now()
    workspace_id = str(uuid.uuid4())
    batch_id = str(uuid.uuid4())

    with session_scope() as session:
        workspace = WorkspaceRecord(
            id=workspace_id,
            display_name="Legacy single-end",
            species="human",
            active_stage="ingestion",
            created_at=timestamp,
            updated_at=timestamp,
        )
        batch = IngestionBatchRecord(
            id=batch_id,
            workspace_id=workspace_id,
            sample_lane="tumor",
            sample_stem="legacy",
            status="ready",
            error=None,
            created_at=timestamp,
            updated_at=timestamp,
        )
        canonical = WorkspaceFileRecord(
            id=str(uuid.uuid4()),
            workspace_id=workspace_id,
            batch_id=batch_id,
            source_file_id=None,
            sample_lane="tumor",
            filename="tumor_SE.normalized.fastq.gz",
            format="fastq",
            file_role="canonical",
            status="ready",
            read_pair="SE",
            storage_key="workspaces/legacy/tumor_SE.normalized.fastq.gz",
            size_bytes=12,
            uploaded_at=timestamp,
            error=None,
        )
        session.add(workspace)
        session.add(batch)
        session.add(canonical)

    payload = await load_workspace(client, workspace_id)
    tumor_lane = payload["ingestion"]["lanes"]["tumor"]
    assert tumor_lane["status"] == "failed"
    assert tumor_lane["ready_for_alignment"] is False
    assert payload["ingestion"]["ready_for_alignment"] is False
    assert tumor_lane["missing_pairs"] == ["R1", "R2"]
    assert "did not produce both R1 and R2" in " ".join(tumor_lane["blocking_issues"])


@pytest.mark.anyio
async def test_new_tumor_upload_blocks_alignment_without_erasing_ready_normal_lane(
    client: httpx.AsyncClient,
    fake_storage: FakeStorage,
    queued_batches: list[tuple[str, str]],
):
    workspace = await create_workspace(client)

    baseline_files = {
        "tumor": [
            ("tumor_R1.fastq.gz", gzip_bytes(b"@tr1\nAAAA\n+\n!!!!\n"), "application/gzip", 60),
            ("tumor_R2.fastq.gz", gzip_bytes(b"@tr2\nCCCC\n+\n!!!!\n"), "application/gzip", 61),
        ],
        "normal": [
            ("normal_R1.fastq.gz", gzip_bytes(b"@nr1\nGGGG\n+\n!!!!\n"), "application/gzip", 62),
            ("normal_R2.fastq.gz", gzip_bytes(b"@nr2\nTTTT\n+\n!!!!\n"), "application/gzip", 63),
        ],
    }

    for lane, files in baseline_files.items():
        session = await create_session(client, workspace["id"], lane, files)
        for filename, payload, _content_type, _last_modified in files:
            await upload_parts_for_file(client, workspace["id"], session, filename, payload)
        await commit_session(client, workspace["id"], session["id"])
        queued_workspace_id, queued_batch_id = queued_batches.pop(0)
        workspace_store.run_batch_normalization(queued_workspace_id, queued_batch_id)

    ready_workspace = await load_workspace(client, workspace["id"])
    assert ready_workspace["ingestion"]["ready_for_alignment"] is True

    replacement_session = await create_session(
        client,
        workspace["id"],
        "tumor",
        [("tumor_refresh_R1.fastq.gz", gzip_bytes(b"@new\nACAC\n+\n!!!!\n"), "application/gzip", 64)],
    )

    refreshed = await load_workspace(client, workspace["id"])
    assert refreshed["ingestion"]["ready_for_alignment"] is False
    assert refreshed["ingestion"]["lanes"]["tumor"]["status"] == "uploading"
    assert refreshed["ingestion"]["lanes"]["normal"]["status"] == "ready"
    assert replacement_session["sample_lane"] == "tumor"


@pytest.mark.anyio
async def test_ready_lane_preview_returns_sampled_reads_and_stats(
    client: httpx.AsyncClient,
    fake_storage: FakeStorage,
    queued_batches: list[tuple[str, str]],
):
    workspace = await create_workspace(client)
    tumor_files = [
        (
            "tumor_R1.fastq.gz",
            gzip_bytes(
                b"@r1a\nACGT\n+\nIIII\n@r1b\nGGGG\n+\nIIII\n"
            ),
            "application/gzip",
            70,
        ),
        (
            "tumor_R2.fastq.gz",
            gzip_bytes(
                b"@r2a\nTTTT\n+\nIIII\n@r2b\nCCCC\n+\nIIII\n"
            ),
            "application/gzip",
            71,
        ),
    ]

    normalized = await normalize_lane(
        client,
        workspace["id"],
        "tumor",
        tumor_files,
        queued_batches,
    )
    assert normalized["ingestion"]["lanes"]["tumor"]["status"] == "ready"

    response = await client.get(
        f"/api/workspaces/{workspace['id']}/ingestion/preview/tumor"
    )
    assert response.status_code == 200, response.text

    payload = response.json()
    assert payload["workspace_id"] == workspace["id"]
    assert payload["sample_lane"] == "tumor"
    assert payload["source"] == "canonical-fastq"
    assert payload["stats"] == {
        "sampled_read_count": 4,
        "average_read_length": 4.0,
        "sampled_gc_percent": 62.5,
    }
    assert [read["header"] for read in payload["reads"]["R1"]] == ["@r1a", "@r1b"]
    assert [read["sequence"] for read in payload["reads"]["R2"]] == ["TTTT", "CCCC"]
    assert payload["reads"]["R1"][0]["gc_percent"] == 50.0
    assert payload["reads"]["R1"][0]["mean_quality"] == 40.0


@pytest.mark.anyio
async def test_lane_preview_requires_ready_canonical_fastq(
    client: httpx.AsyncClient,
    fake_storage: FakeStorage,
    queued_batches: list[tuple[str, str]],
):
    workspace = await create_workspace(client)
    tumor_files = [
        ("tumor_R1.fastq.gz", gzip_bytes(b"@r1\nACGT\n+\nIIII\n"), "application/gzip", 80),
        ("tumor_R2.fastq.gz", gzip_bytes(b"@r2\nTGCA\n+\nIIII\n"), "application/gzip", 81),
    ]
    session = await create_session(client, workspace["id"], "tumor", tumor_files)
    for filename, payload, _content_type, _last_modified in tumor_files:
        await upload_parts_for_file(client, workspace["id"], session, filename, payload)
    await commit_session(client, workspace["id"], session["id"])

    response = await client.get(
        f"/api/workspaces/{workspace['id']}/ingestion/preview/tumor"
    )
    assert response.status_code == 409
    assert "becomes available" in response.text


@pytest.mark.anyio
async def test_lane_preview_returns_404_when_canonical_storage_object_is_missing(
    client: httpx.AsyncClient,
    fake_storage: FakeStorage,
    queued_batches: list[tuple[str, str]],
):
    workspace = await create_workspace(client)
    tumor_files = [
        ("tumor_R1.fastq.gz", gzip_bytes(b"@r1\nACGT\n+\nIIII\n"), "application/gzip", 90),
        ("tumor_R2.fastq.gz", gzip_bytes(b"@r2\nTGCA\n+\nIIII\n"), "application/gzip", 91),
    ]

    normalized = await normalize_lane(
        client,
        workspace["id"],
        "tumor",
        tumor_files,
        queued_batches,
    )
    canonical_r2_key = next(
        file["storage_key"]
        for file in normalized["files"]
        if file["sample_lane"] == "tumor"
        and file["file_role"] == "canonical"
        and file["read_pair"] == "R2"
    )
    fake_storage.objects.pop(canonical_r2_key)

    response = await client.get(
        f"/api/workspaces/{workspace['id']}/ingestion/preview/tumor"
    )
    assert response.status_code == 404
    assert "Stored object" in response.text


@pytest.mark.anyio
async def test_lane_preview_rejects_malformed_canonical_fastq(
    client: httpx.AsyncClient,
    fake_storage: FakeStorage,
    queued_batches: list[tuple[str, str]],
):
    workspace = await create_workspace(client)
    tumor_files = [
        ("tumor_R1.fastq.gz", gzip_bytes(b"@r1\nACGT\n+\nIIII\n"), "application/gzip", 92),
        ("tumor_R2.fastq.gz", gzip_bytes(b"@r2\nTGCA\n+\nIIII\n"), "application/gzip", 93),
    ]

    normalized = await normalize_lane(
        client,
        workspace["id"],
        "tumor",
        tumor_files,
        queued_batches,
    )
    canonical_r1_key = next(
        file["storage_key"]
        for file in normalized["files"]
        if file["sample_lane"] == "tumor"
        and file["file_role"] == "canonical"
        and file["read_pair"] == "R1"
    )
    fake_storage.objects[canonical_r1_key] = gzip_bytes(b"@broken\nACGT\n+\n")

    response = await client.get(
        f"/api/workspaces/{workspace['id']}/ingestion/preview/tumor"
    )
    assert response.status_code == 400
    assert "Malformed canonical FASTQ preview" in response.text
