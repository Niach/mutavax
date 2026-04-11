from __future__ import annotations

import os
import time
import uuid
from pathlib import Path

import httpx
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SAMPLE_DIR = REPO_ROOT / "data" / "sample-data" / "seqc2-hcc1395-wes-ll" / "smoke"
DEFAULT_API_BASE = "http://127.0.0.1:8000"
POLL_INTERVAL_SECONDS = 0.5
READY_TIMEOUT_SECONDS = 90

pytestmark = [pytest.mark.integration, pytest.mark.real_data]


def sample_dir() -> Path:
    candidate = Path(os.getenv("REAL_DATA_SAMPLE_DIR", DEFAULT_SAMPLE_DIR))
    required_files = [
        "tumor_R1.fastq.gz",
        "tumor_R2.fastq.gz",
        "normal_R1.fastq.gz",
        "normal_R2.fastq.gz",
    ]

    missing = [name for name in required_files if not (candidate / name).exists()]
    if missing:
        pytest.fail(
            "Real-data sample files are missing. Expected them in "
            f"{candidate}. Missing: {', '.join(missing)}. "
            "Run `npm run sample-data:smoke` first or set REAL_DATA_SAMPLE_DIR."
        )

    return candidate


def api_base_url() -> str:
    return os.getenv("REAL_DATA_API_BASE", DEFAULT_API_BASE).rstrip("/")


def wait_for_health(client: httpx.Client, timeout_seconds: int = 30) -> None:
    deadline = time.monotonic() + timeout_seconds
    last_error = "unknown"

    while time.monotonic() < deadline:
        try:
            response = client.get("/health")
            if response.status_code == 200:
                return
            last_error = f"unexpected status {response.status_code}"
        except httpx.HTTPError as error:
            last_error = str(error)

        time.sleep(POLL_INTERVAL_SECONDS)

    pytest.fail(
        "Backend health check did not succeed within "
        f"{timeout_seconds}s at {client.base_url!s}/health: {last_error}"
    )


def file_payload(path: Path) -> dict[str, object]:
    stat = path.stat()
    return {
        "filename": path.name,
        "size_bytes": stat.st_size,
        "last_modified_ms": int(stat.st_mtime * 1000),
        "content_type": "application/gzip",
    }


def create_workspace(client: httpx.Client) -> dict:
    response = client.post(
        "/api/workspaces",
        json={
            "display_name": f"SEQC2 smoke {uuid.uuid4().hex[:8]}",
            "species": "human",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def create_upload_session(
    client: httpx.Client,
    workspace_id: str,
    sample_lane: str,
    files: list[Path],
) -> dict:
    response = client.post(
        f"/api/workspaces/{workspace_id}/ingestion/sessions",
        json={
            "sample_lane": sample_lane,
            "files": [file_payload(path) for path in files],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def upload_session_file(
    client: httpx.Client,
    workspace_id: str,
    session: dict,
    path: Path,
) -> None:
    session_file = next(
        file for file in session["files"] if file["filename"] == path.name
    )
    payload = path.read_bytes()
    chunk_size = session["chunk_size_bytes"]

    for part_number in range(1, session_file["total_parts"] + 1):
        start = (part_number - 1) * chunk_size
        end = min(len(payload), start + chunk_size)
        response = client.put(
            f"/api/workspaces/{workspace_id}/ingestion/sessions/{session['id']}/files/{session_file['id']}/parts/{part_number}",
            content=payload[start:end],
            headers={"content-type": "application/octet-stream"},
        )
        assert response.status_code == 200, response.text

    response = client.post(
        f"/api/workspaces/{workspace_id}/ingestion/sessions/{session['id']}/files/{session_file['id']}/complete"
    )
    assert response.status_code == 200, response.text


def commit_upload_session(client: httpx.Client, workspace_id: str, session_id: str) -> dict:
    response = client.post(
        f"/api/workspaces/{workspace_id}/ingestion/sessions/{session_id}/commit"
    )
    assert response.status_code == 200, response.text
    return response.json()


def load_workspace(client: httpx.Client, workspace_id: str) -> dict:
    response = client.get(f"/api/workspaces/{workspace_id}")
    assert response.status_code == 200, response.text
    return response.json()


def wait_for_workspace(
    client: httpx.Client,
    workspace_id: str,
    *,
    sample_lane: str,
    status: str,
    ready_for_alignment: bool,
    timeout_seconds: int = READY_TIMEOUT_SECONDS,
) -> dict:
    deadline = time.monotonic() + timeout_seconds
    latest_payload: dict | None = None

    while time.monotonic() < deadline:
        latest_payload = load_workspace(client, workspace_id)
        lane_summary = latest_payload["ingestion"]["lanes"][sample_lane]
        if (
            lane_summary["status"] == status
            and latest_payload["ingestion"]["ready_for_alignment"] is ready_for_alignment
        ):
            return latest_payload
        time.sleep(POLL_INTERVAL_SECONDS)

    pytest.fail(
        "Workspace did not reach the expected state within "
        f"{timeout_seconds}s for lane={sample_lane}, status={status}, "
        f"ready_for_alignment={ready_for_alignment}. Latest payload: {latest_payload}"
    )


def test_real_data_ingestion_end_to_end() -> None:
    smoke_dir = sample_dir()
    tumor_files = [smoke_dir / "tumor_R1.fastq.gz", smoke_dir / "tumor_R2.fastq.gz"]
    normal_files = [smoke_dir / "normal_R1.fastq.gz", smoke_dir / "normal_R2.fastq.gz"]

    with httpx.Client(base_url=api_base_url(), follow_redirects=True, timeout=60.0) as client:
        wait_for_health(client)
        workspace = create_workspace(client)

        tumor_session = create_upload_session(
            client,
            workspace["id"],
            "tumor",
            tumor_files,
        )
        for path in tumor_files:
            upload_session_file(client, workspace["id"], tumor_session, path)
        tumor_commit = commit_upload_session(client, workspace["id"], tumor_session["id"])
        assert tumor_commit["ingestion"]["ready_for_alignment"] is False

        tumor_ready = wait_for_workspace(
            client,
            workspace["id"],
            sample_lane="tumor",
            status="ready",
            ready_for_alignment=False,
        )
        assert tumor_ready["ingestion"]["lanes"]["normal"]["status"] == "empty"

        normal_session = create_upload_session(
            client,
            workspace["id"],
            "normal",
            normal_files,
        )
        for path in normal_files:
            upload_session_file(client, workspace["id"], normal_session, path)
        normal_commit = commit_upload_session(client, workspace["id"], normal_session["id"])
        assert normal_commit["ingestion"]["ready_for_alignment"] is False

        fully_ready = wait_for_workspace(
            client,
            workspace["id"],
            sample_lane="normal",
            status="ready",
            ready_for_alignment=True,
        )
        assert fully_ready["ingestion"]["lanes"]["tumor"]["status"] == "ready"

        preview_response = client.get(
            f"/api/workspaces/{workspace['id']}/ingestion/preview/tumor"
        )
        assert preview_response.status_code == 200, preview_response.text
        preview = preview_response.json()

        assert preview["source"] == "canonical-fastq"
        assert preview["stats"]["sampled_read_count"] > 0
        assert preview["reads"]["R1"]
        assert preview["reads"]["R2"]
