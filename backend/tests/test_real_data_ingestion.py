from __future__ import annotations

import os
import shlex
import shutil
import time
import uuid
from pathlib import Path

import httpx
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SAMPLE_DIR = REPO_ROOT / "data" / "sample-data" / "seqc2-hcc1395-wes-ll" / "smoke"
DEFAULT_ALIGNMENT_SAMPLE_DIR = REPO_ROOT / "data" / "sample-data" / "htslib-xx-pair" / "smoke"
DEFAULT_API_BASE = "http://127.0.0.1:8000"
POLL_INTERVAL_SECONDS = 0.5
READY_TIMEOUT_SECONDS = 90
ALIGNMENT_TIMEOUT_SECONDS = int(
    os.getenv("REAL_DATA_ALIGNMENT_TIMEOUT_SECONDS", "3600")
)

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


def alignment_sample_dir() -> Path:
    candidate = Path(
        os.getenv("REAL_DATA_ALIGNMENT_SAMPLE_DIR", DEFAULT_ALIGNMENT_SAMPLE_DIR)
    )
    required_files = [
        "tumor.bam",
        "normal.cram",
        "xx.fa",
    ]

    missing = [name for name in required_files if not (candidate / name).exists()]
    if missing:
        pytest.fail(
            "Alignment-container sample files are missing. Expected them in "
            f"{candidate}. Missing: {', '.join(missing)}. "
            "Run `npm run sample-data:alignment` first or set "
            "REAL_DATA_ALIGNMENT_SAMPLE_DIR."
        )

    return candidate


def api_base_url() -> str:
    return os.getenv("REAL_DATA_API_BASE", DEFAULT_API_BASE).rstrip("/")


def resolve_binary_name(env_var: str, default: str) -> str:
    command = os.getenv(env_var, default)
    parts = shlex.split(command)
    return parts[0] if parts else default


def require_live_alignment_prerequisites() -> None:
    enabled = os.getenv("REAL_DATA_RUN_ALIGNMENT", "").strip().lower()
    if enabled not in {"1", "true", "yes"}:
        pytest.skip("Set REAL_DATA_RUN_ALIGNMENT=1 to run the live alignment smoke.")

    missing = [
        binary
        for binary in (
            resolve_binary_name("SAMTOOLS_BINARY", "samtools"),
            resolve_binary_name("ALIGNMENT_STROBEALIGN_BINARY", "strobealign"),
        )
        if shutil.which(binary) is None
    ]
    if missing:
        pytest.skip(
            "Live alignment smoke requires local binaries on PATH: "
            + ", ".join(missing)
        )


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


def register_local_files(
    client: httpx.Client,
    workspace_id: str,
    sample_lane: str,
    files: list[Path],
) -> dict:
    response = client.post(
        f"/api/workspaces/{workspace_id}/ingestion/local-files",
        json={
            "sample_lane": sample_lane,
            "paths": [str(path) for path in files],
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def load_workspace(client: httpx.Client, workspace_id: str) -> dict:
    response = client.get(f"/api/workspaces/{workspace_id}")
    assert response.status_code == 200, response.text
    return response.json()


def load_alignment_summary(client: httpx.Client, workspace_id: str) -> dict:
    response = client.get(f"/api/workspaces/{workspace_id}/alignment")
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


def wait_for_alignment_completion(
    client: httpx.Client,
    workspace_id: str,
    *,
    timeout_seconds: int = ALIGNMENT_TIMEOUT_SECONDS,
) -> dict:
    deadline = time.monotonic() + timeout_seconds
    latest_payload: dict | None = None

    while time.monotonic() < deadline:
        latest_payload = load_alignment_summary(client, workspace_id)
        if latest_payload["status"] in {"completed", "failed"}:
            return latest_payload
        time.sleep(POLL_INTERVAL_SECONDS)

    pytest.fail(
        "Alignment did not finish within "
        f"{timeout_seconds}s. Latest payload: {latest_payload}"
    )


def test_real_data_ingestion_smoke_reaches_alignment_ready() -> None:
    smoke_dir = sample_dir()
    tumor_files = [smoke_dir / "tumor_R1.fastq.gz", smoke_dir / "tumor_R2.fastq.gz"]
    normal_files = [smoke_dir / "normal_R1.fastq.gz", smoke_dir / "normal_R2.fastq.gz"]

    with httpx.Client(base_url=api_base_url(), follow_redirects=True, timeout=60.0) as client:
        wait_for_health(client)
        workspace = create_workspace(client)

        tumor_registration = register_local_files(
            client,
            workspace["id"],
            "tumor",
            tumor_files,
        )
        assert tumor_registration["ingestion"]["ready_for_alignment"] is False

        tumor_ready = wait_for_workspace(
            client,
            workspace["id"],
            sample_lane="tumor",
            status="ready",
            ready_for_alignment=False,
        )
        assert tumor_ready["ingestion"]["lanes"]["normal"]["status"] == "empty"

        normal_registration = register_local_files(
            client,
            workspace["id"],
            "normal",
            normal_files,
        )
        assert normal_registration["ingestion"]["ready_for_alignment"] is False

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


def test_alignment_container_smoke_normalizes_into_alignment_ready_inputs() -> None:
    sample_root = alignment_sample_dir()
    tumor_files = [sample_root / "tumor.bam"]
    normal_files = [sample_root / "normal.cram"]

    with httpx.Client(base_url=api_base_url(), follow_redirects=True, timeout=60.0) as client:
        wait_for_health(client)
        workspace = create_workspace(client)

        register_local_files(client, workspace["id"], "tumor", tumor_files)
        wait_for_workspace(
            client,
            workspace["id"],
            sample_lane="tumor",
            status="ready",
            ready_for_alignment=False,
        )

        register_local_files(client, workspace["id"], "normal", normal_files)
        fully_ready = wait_for_workspace(
            client,
            workspace["id"],
            sample_lane="normal",
            status="ready",
            ready_for_alignment=True,
        )
        assert fully_ready["ingestion"]["lanes"]["tumor"]["status"] == "ready"

        preview_response = client.get(
            f"/api/workspaces/{workspace['id']}/ingestion/preview/normal"
        )
        assert preview_response.status_code == 200, preview_response.text
        preview = preview_response.json()

        assert preview["source"] == "canonical-fastq"
        assert preview["stats"]["sampled_read_count"] > 0
        assert preview["reads"]["R1"]
        assert preview["reads"]["R2"]


def test_real_data_alignment_smoke_completes_with_expected_artifacts() -> None:
    require_live_alignment_prerequisites()

    smoke_dir = sample_dir()
    tumor_files = [smoke_dir / "tumor_R1.fastq.gz", smoke_dir / "tumor_R2.fastq.gz"]
    normal_files = [smoke_dir / "normal_R1.fastq.gz", smoke_dir / "normal_R2.fastq.gz"]
    expected_artifacts = {
        ("tumor", "bam"),
        ("tumor", "bai"),
        ("tumor", "flagstat"),
        ("tumor", "idxstats"),
        ("tumor", "stats"),
        ("normal", "bam"),
        ("normal", "bai"),
        ("normal", "flagstat"),
        ("normal", "idxstats"),
        ("normal", "stats"),
    }

    with httpx.Client(base_url=api_base_url(), follow_redirects=True, timeout=120.0) as client:
        wait_for_health(client)
        workspace = create_workspace(client)

        profile_response = client.patch(
            f"/api/workspaces/{workspace['id']}/analysis-profile",
            json={"assay_type": "wes", "reference_preset": "grch38"},
        )
        assert profile_response.status_code == 200, profile_response.text

        register_local_files(client, workspace["id"], "tumor", tumor_files)
        wait_for_workspace(
            client,
            workspace["id"],
            sample_lane="tumor",
            status="ready",
            ready_for_alignment=False,
        )

        register_local_files(client, workspace["id"], "normal", normal_files)
        wait_for_workspace(
            client,
            workspace["id"],
            sample_lane="normal",
            status="ready",
            ready_for_alignment=True,
        )

        run_response = client.post(f"/api/workspaces/{workspace['id']}/alignment/run")
        assert run_response.status_code == 200, run_response.text

        summary = wait_for_alignment_completion(client, workspace["id"])
        if summary["status"] == "failed":
            pytest.fail(f"Live alignment smoke failed: {summary}")

        assert summary["status"] == "completed"
        assert summary["ready_for_variant_calling"] is True
        assert summary["analysis_profile"]["assay_type"] == "wes"
        assert {
            (artifact["sample_lane"], artifact["artifact_kind"])
            for artifact in summary["artifacts"]
        } == expected_artifacts
        assert all(artifact["local_path"] for artifact in summary["artifacts"])
        assert all(
            Path(artifact["local_path"]).exists()
            for artifact in summary["artifacts"]
        )
