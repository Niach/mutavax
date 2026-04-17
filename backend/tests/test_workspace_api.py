import gzip
import io
from contextlib import closing
import threading
from pathlib import Path

import httpx
import pytest
from sqlalchemy import delete, select

from app.api import workspaces as workspace_routes
from app.db import init_db, session_scope
from app.main import app
from app.models.records import (
    IngestionBatchRecord,
    PipelineArtifactRecord,
    PipelineRunRecord,
    WorkspaceFileRecord,
    WorkspaceRecord,
)
from app.services import alignment as alignment_service
from app.services import workspace_store
from app.models.schemas import AlignmentArtifactKind, AlignmentLaneMetricsResponse, SampleLane


def write_gz_fastq(path: Path, header: str, sequence: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        handle.write(f"@{header}\n{sequence}\n+\n{'!' * len(sequence)}\n")
    return path


def write_fastq(path: Path, header: str, sequence: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"@{header}\n{sequence}\n+\n{'!' * len(sequence)}\n",
        encoding="utf-8",
    )
    return path


@pytest.fixture(autouse=True)
def clean_database():
    init_db()
    with session_scope() as session:
        session.execute(delete(PipelineArtifactRecord))
        session.execute(delete(PipelineRunRecord))
        session.execute(delete(WorkspaceFileRecord))
        session.execute(delete(IngestionBatchRecord))
        session.execute(delete(WorkspaceRecord))
    yield
    with session_scope() as session:
        session.execute(delete(PipelineArtifactRecord))
        session.execute(delete(PipelineRunRecord))
        session.execute(delete(WorkspaceFileRecord))
        session.execute(delete(IngestionBatchRecord))
        session.execute(delete(WorkspaceRecord))


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
def queued_alignment_runs(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str]]:
    runs: list[tuple[str, str]] = []
    monkeypatch.setattr(
        alignment_service,
        "enqueue_alignment_run",
        lambda workspace_id, run_id: runs.append((workspace_id, run_id)),
    )
    return runs


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
    *,
    name: str = "Rosie",
    species: str = "human",
) -> dict:
    response = await client.post(
        "/api/workspaces",
        json={"display_name": name, "species": species},
    )
    assert response.status_code == 201, response.text
    return response.json()


async def register_lane_paths(
    client: httpx.AsyncClient,
    workspace_id: str,
    sample_lane: str,
    paths: list[Path],
) -> dict:
    response = await client.post(
        f"/api/workspaces/{workspace_id}/ingestion/local-files",
        json={"sample_lane": sample_lane, "paths": [str(path) for path in paths]},
    )
    assert response.status_code == 200, response.text
    return response.json()


def run_next_normalization(
    queued_batches: list[tuple[str, str]],
) -> dict:
    workspace_id, batch_id = queued_batches.pop(0)
    return workspace_store.run_batch_normalization(
        workspace_id, batch_id
    ).model_dump(mode="json")


async def prepare_alignment_ready_workspace(
    client: httpx.AsyncClient,
    queued_batches: list[tuple[str, str]],
    tmp_path: Path,
) -> dict:
    workspace = await create_workspace(client)
    for lane in ("tumor", "normal"):
        await register_lane_paths(
            client,
            workspace["id"],
            lane,
            [
                write_gz_fastq(tmp_path / f"{lane}_R1.fastq.gz", f"{lane}-r1", "ACGT"),
                write_gz_fastq(tmp_path / f"{lane}_R2.fastq.gz", f"{lane}-r2", "TGCA"),
            ],
        )
        run_next_normalization(queued_batches)

    return workspace


def install_fake_alignment(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    mapped_percent: float = 95.0,
    properly_paired_percent: float = 88.0,
    duplicate_percent: float = 20.0,
    mean_insert_size: float = 320.0,
) -> None:
    reference_path = tmp_path / "grch38.fa"
    reference_path.write_text(">chr1\nACGTACGTACGT\n", encoding="utf-8")
    monkeypatch.setattr(
        alignment_service,
        "ensure_reference_ready",
        lambda reference: reference_path,
    )

    total_reads = 100
    mapped_reads = int(round(total_reads * (mapped_percent / 100)))
    properly_paired_reads = int(round(total_reads * (properly_paired_percent / 100)))

    def fake_execute_alignment_lane(
        *,
        workspace_display_name: str,
        workspace_id: str,
        run_id: str,
        sample_lane: SampleLane,
        reference_path: Path,
        r1_path: Path,
        r2_path: Path,
        working_dir: Path,
        run_dir: Path = None,
    ):
        bam_path = working_dir / f"{sample_lane.value}.aligned.bam"
        bai_path = working_dir / f"{sample_lane.value}.aligned.bam.bai"
        flagstat_path = working_dir / f"{sample_lane.value}.flagstat.txt"
        idxstats_path = working_dir / f"{sample_lane.value}.idxstats.txt"
        stats_path = working_dir / f"{sample_lane.value}.stats.txt"
        bam_path.write_text("bam", encoding="utf-8")
        bai_path.write_text("bai", encoding="utf-8")
        flagstat_path.write_text(
            f"{total_reads} + 0 in total (QC-passed reads + QC-failed reads)\n"
            f"{mapped_reads} + 0 mapped ({mapped_percent:.2f}% : N/A)\n"
            f"{properly_paired_reads} + 0 properly paired ({properly_paired_percent:.2f}% : N/A)\n",
            encoding="utf-8",
        )
        idxstats_path.write_text(f"chr1\t12\t{mapped_reads}\t0\n", encoding="utf-8")
        stats_path.write_text(
            f"SN\traw total sequences:\t{total_reads}\n"
            f"SN\treads duplicated:\t{int(round(total_reads * (duplicate_percent / 100)))}\n"
            f"SN\tinsert size average:\t{mean_insert_size:.0f}\n",
            encoding="utf-8",
        )
        return alignment_service.LaneExecutionOutput(
            sample_lane=sample_lane,
            metrics=AlignmentLaneMetricsResponse(
                sample_lane=sample_lane,
                total_reads=total_reads,
                mapped_reads=mapped_reads,
                mapped_percent=mapped_percent,
                properly_paired_percent=properly_paired_percent,
                duplicate_percent=duplicate_percent,
                mean_insert_size=mean_insert_size,
            ),
            artifact_paths={
                AlignmentArtifactKind.BAM: bam_path,
                AlignmentArtifactKind.BAI: bai_path,
                AlignmentArtifactKind.FLAGSTAT: flagstat_path,
                AlignmentArtifactKind.IDXSTATS: idxstats_path,
                AlignmentArtifactKind.STATS: stats_path,
            },
            command_log=[f"fake align {sample_lane.value}"],
        )

    monkeypatch.setattr(
        alignment_service,
        "execute_alignment_lane",
        fake_execute_alignment_lane,
    )
    monkeypatch.setattr(workspace_routes, "verify_tools", lambda _tools: None)


def test_parse_remote_checksum_requires_an_exact_filename_token(
    monkeypatch: pytest.MonkeyPatch,
):
    checksum_text = "\n".join(
        [
            (
                "11111 22222 /tmp/"
                "Homo_sapiens.GRCh38.dna.primary_assembly.fa.gz.fai "
                "Homo_sapiens.GRCh38.dna.primary_assembly.fa.gz.fai"
            ),
            (
                "22450 861294 /tmp/"
                "Homo_sapiens.GRCh38.dna.primary_assembly.fa.gz "
                "Homo_sapiens.GRCh38.dna.primary_assembly.fa.gz"
            ),
        ]
    )
    spec = alignment_service.ReferenceSourceSpec(
        download_url="https://example.invalid/source.fa.gz",
        checksum_url="https://example.invalid/CHECKSUMS",
        checksum_type="sum",
        checksum_filename="Homo_sapiens.GRCh38.dna.primary_assembly.fa.gz",
    )

    monkeypatch.setattr(
        alignment_service,
        "urlopen",
        lambda *_args, **_kwargs: closing(io.BytesIO(checksum_text.encode("utf-8"))),
    )

    assert alignment_service.parse_remote_checksum(spec) == "22450 861294"


def test_ensure_download_verified_accepts_grch38_sum_checksums(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    archive_path = tmp_path / "reference.fa.gz"
    archive_path.write_bytes(b"test-reference")
    expected = alignment_service.compute_local_checksum(archive_path, "sum")
    spec = alignment_service.ReferenceSourceSpec(
        download_url="https://example.invalid/source.fa.gz",
        checksum_url="https://example.invalid/CHECKSUMS",
        checksum_type="sum",
        checksum_filename=archive_path.name,
    )

    monkeypatch.setattr(alignment_service, "parse_remote_checksum", lambda _spec: expected)

    alignment_service.ensure_download_verified(archive_path, spec)


def test_ensure_download_verified_reports_reference_verification_mismatch(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    archive_path = tmp_path / "reference.fa.gz"
    archive_path.write_bytes(b"test-reference")
    spec = alignment_service.ReferenceSourceSpec(
        download_url="https://example.invalid/source.fa.gz",
        checksum_url="https://example.invalid/CHECKSUMS",
        checksum_type="sum",
        checksum_filename=archive_path.name,
    )

    monkeypatch.setattr(alignment_service, "parse_remote_checksum", lambda _spec: "0 0")

    with pytest.raises(RuntimeError, match="Reference download verification failed"):
        alignment_service.ensure_download_verified(archive_path, spec)


def test_ensure_download_verified_keeps_md5_support(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    archive_path = tmp_path / "reference.fa.gz"
    archive_path.write_bytes(b"test-reference")
    expected = alignment_service.compute_local_checksum(archive_path, "md5")
    spec = alignment_service.ReferenceSourceSpec(
        download_url="https://example.invalid/source.fa.gz",
        checksum_url="https://example.invalid/md5sum.txt",
        checksum_type="md5",
        checksum_filename=archive_path.name,
    )

    monkeypatch.setattr(alignment_service, "parse_remote_checksum", lambda _spec: expected)

    alignment_service.ensure_download_verified(archive_path, spec)


@pytest.mark.anyio
async def test_rejects_whitespace_only_workspace_names(client: httpx.AsyncClient):
    response = await client.post(
        "/api/workspaces",
        json={"display_name": "   ", "species": "dog"},
    )

    assert response.status_code == 400
    assert "cannot be empty" in response.text


@pytest.mark.anyio
async def test_local_file_registration_requires_real_paths(client: httpx.AsyncClient):
    workspace = await create_workspace(client)
    missing_path = Path("/tmp/this-file-does-not-exist.fastq.gz")

    response = await client.post(
        f"/api/workspaces/{workspace['id']}/ingestion/local-files",
        json={"sample_lane": "tumor", "paths": [str(missing_path)]},
    )

    assert response.status_code == 400
    assert "does not exist" in response.text


@pytest.mark.anyio
async def test_local_ingestion_reaches_alignment_ready(
    client: httpx.AsyncClient,
    queued_batches: list[tuple[str, str]],
    tmp_path: Path,
):
    workspace = await create_workspace(client)
    tumor_paths = [
      write_gz_fastq(tmp_path / "tumor_R1.fastq.gz", "tumor-r1", "ACGT"),
      write_gz_fastq(tmp_path / "tumor_R2.fastq.gz", "tumor-r2", "TGCA"),
    ]
    normal_paths = [
      write_gz_fastq(tmp_path / "normal_R1.fastq.gz", "normal-r1", "CCCC"),
      write_gz_fastq(tmp_path / "normal_R2.fastq.gz", "normal-r2", "GGGG"),
    ]

    pending = await register_lane_paths(client, workspace["id"], "tumor", tumor_paths)
    assert pending["ingestion"]["lanes"]["tumor"]["status"] == "normalizing"
    assert pending["ingestion"]["ready_for_alignment"] is False

    tumor_ready = run_next_normalization(queued_batches)
    assert tumor_ready["ingestion"]["lanes"]["tumor"]["status"] == "ready"
    assert tumor_ready["ingestion"]["ready_for_alignment"] is False

    await register_lane_paths(client, workspace["id"], "normal", normal_paths)
    ready = run_next_normalization(queued_batches)

    assert ready["ingestion"]["ready_for_alignment"] is True
    assert ready["ingestion"]["lanes"]["tumor"]["status"] == "ready"
    assert ready["ingestion"]["lanes"]["normal"]["status"] == "ready"

    source_files = [file for file in ready["files"] if file["file_role"] == "source"]
    canonical_files = [file for file in ready["files"] if file["file_role"] == "canonical"]
    assert all(file["source_path"] for file in source_files)
    assert canonical_files == []
    assert all(file["managed_path"] is None for file in source_files)

    preview_response = await client.get(
        f"/api/workspaces/{workspace['id']}/ingestion/preview/tumor"
    )
    assert preview_response.status_code == 200, preview_response.text
    preview = preview_response.json()
    assert preview["reads"]["R1"]
    assert preview["reads"]["R2"]


@pytest.mark.anyio
async def test_multi_chunk_gz_fastqs_materialize_member_concatenated_outputs(
    client: httpx.AsyncClient,
    queued_batches: list[tuple[str, str]],
    tmp_path: Path,
):
    workspace = await create_workspace(client)
    lane_paths = [
        write_gz_fastq(tmp_path / "tumor_L001_R1.fastq.gz", "tumor-r1-a", "ACGT"),
        write_gz_fastq(tmp_path / "tumor_L002_R1.fastq.gz", "tumor-r1-b", "TTAA"),
        write_gz_fastq(tmp_path / "tumor_L001_R2.fastq.gz", "tumor-r2-a", "TGCA"),
        write_gz_fastq(tmp_path / "tumor_L002_R2.fastq.gz", "tumor-r2-b", "CCGG"),
    ]

    await register_lane_paths(client, workspace["id"], "tumor", lane_paths)
    normalized = run_next_normalization(queued_batches)

    canonical_files = [
        file for file in normalized["files"] if file["file_role"] == "canonical"
    ]
    assert len(canonical_files) == 2
    assert all(file["managed_path"] for file in canonical_files)

    r1_path = Path(
        next(file["managed_path"] for file in canonical_files if file["read_pair"] == "R1")
    )
    with gzip.open(r1_path, "rt", encoding="utf-8") as handle:
        merged_text = handle.read()

    assert "@tumor-r1-a" in merged_text
    assert "@tumor-r1-b" in merged_text


@pytest.mark.anyio
async def test_plain_fastqs_are_compressed_into_managed_canonical_outputs(
    client: httpx.AsyncClient,
    queued_batches: list[tuple[str, str]],
    tmp_path: Path,
):
    workspace = await create_workspace(client)
    lane_paths = [
        write_fastq(tmp_path / "tumor_R1.fastq", "tumor-r1", "ACGT"),
        write_fastq(tmp_path / "tumor_R2.fastq", "tumor-r2", "TGCA"),
    ]

    await register_lane_paths(client, workspace["id"], "tumor", lane_paths)
    normalized = run_next_normalization(queued_batches)

    canonical_files = [
        file for file in normalized["files"] if file["file_role"] == "canonical"
    ]
    assert len(canonical_files) == 2
    assert all(file["managed_path"] for file in canonical_files)
    assert all(file["filename"].endswith(".fastq.gz") for file in canonical_files)


@pytest.mark.anyio
async def test_same_source_fastqs_can_be_reused_in_multiple_workspaces(
    client: httpx.AsyncClient,
    queued_batches: list[tuple[str, str]],
    tmp_path: Path,
):
    shared_paths = [
        write_gz_fastq(tmp_path / "shared_R1.fastq.gz", "shared-r1", "ACGT"),
        write_gz_fastq(tmp_path / "shared_R2.fastq.gz", "shared-r2", "TGCA"),
    ]
    first_workspace = await create_workspace(client, name="First reuse")
    second_workspace = await create_workspace(client, name="Second reuse")

    first_response = await register_lane_paths(
        client,
        first_workspace["id"],
        "tumor",
        shared_paths,
    )
    second_response = await register_lane_paths(
        client,
        second_workspace["id"],
        "tumor",
        shared_paths,
    )

    assert first_response["ingestion"]["lanes"]["tumor"]["status"] == "normalizing"
    assert second_response["ingestion"]["lanes"]["tumor"]["status"] == "normalizing"


@pytest.mark.anyio
async def test_alignment_run_persists_local_artifacts_and_exposes_variant_preview(
    client: httpx.AsyncClient,
    queued_batches: list[tuple[str, str]],
    queued_alignment_runs: list[tuple[str, str]],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    workspace = await prepare_alignment_ready_workspace(client, queued_batches, tmp_path)
    install_fake_alignment(monkeypatch, tmp_path)

    summary_response = await client.post(
        f"/api/workspaces/{workspace['id']}/alignment/run"
    )
    assert summary_response.status_code == 200, summary_response.text
    assert queued_alignment_runs

    queued_workspace_id, run_id = queued_alignment_runs.pop(0)
    alignment_service.run_alignment(queued_workspace_id, run_id)

    completed_response = await client.get(f"/api/workspaces/{workspace['id']}/alignment")
    assert completed_response.status_code == 200, completed_response.text
    completed = completed_response.json()

    assert completed["status"] == "completed"
    assert completed["ready_for_variant_calling"] is True
    assert len(completed["artifacts"]) == 10

    variant_summary_response = await client.get(
        f"/api/workspaces/{workspace['id']}/variant-calling"
    )
    assert variant_summary_response.status_code == 200, variant_summary_response.text
    variant_summary = variant_summary_response.json()
    assert variant_summary["status"] == "scaffolded"
    assert variant_summary["blocking_reason"] is None
    assert variant_summary["latest_run"] is None

    bam_artifact = next(
        artifact
        for artifact in completed["artifacts"]
        if artifact["artifact_kind"] == "bam" and artifact["sample_lane"] == "tumor"
    )
    download_response = await client.get(bam_artifact["download_path"])
    assert download_response.status_code == 200
    assert download_response.text == "bam"


@pytest.mark.anyio
async def test_alignment_warn_keeps_variant_preview_blocked(
    client: httpx.AsyncClient,
    queued_batches: list[tuple[str, str]],
    queued_alignment_runs: list[tuple[str, str]],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    workspace = await prepare_alignment_ready_workspace(client, queued_batches, tmp_path)
    install_fake_alignment(monkeypatch, tmp_path, duplicate_percent=72.0)

    summary_response = await client.post(
        f"/api/workspaces/{workspace['id']}/alignment/run"
    )
    assert summary_response.status_code == 200, summary_response.text
    queued_workspace_id, run_id = queued_alignment_runs.pop(0)
    alignment_service.run_alignment(queued_workspace_id, run_id)

    completed_response = await client.get(f"/api/workspaces/{workspace['id']}/alignment")
    assert completed_response.status_code == 200, completed_response.text
    completed = completed_response.json()
    assert completed["status"] == "completed"
    assert completed["qc_verdict"] == "warn"
    assert completed["ready_for_variant_calling"] is False
    assert "quality warnings need review" in (completed["blocking_reason"] or "")

    variant_summary_response = await client.get(
        f"/api/workspaces/{workspace['id']}/variant-calling"
    )
    assert variant_summary_response.status_code == 200, variant_summary_response.text
    variant_summary = variant_summary_response.json()
    assert variant_summary["status"] == "blocked"
    assert "quality warnings need review" in (variant_summary["blocking_reason"] or "")


@pytest.mark.anyio
async def test_reset_removes_managed_outputs_but_keeps_source_files(
    client: httpx.AsyncClient,
    queued_batches: list[tuple[str, str]],
    tmp_path: Path,
):
    workspace = await create_workspace(client)
    source_paths = [
        write_fastq(tmp_path / "tumor_R1.fastq", "tumor-r1", "AAAA"),
        write_fastq(tmp_path / "tumor_R2.fastq", "tumor-r2", "CCCC"),
    ]
    await register_lane_paths(client, workspace["id"], "tumor", source_paths)
    normalized = run_next_normalization(queued_batches)
    managed_paths = [
        Path(file["managed_path"])
        for file in normalized["files"]
        if file["managed_path"]
    ]
    assert managed_paths and all(path.exists() for path in managed_paths)

    reset_response = await client.delete(f"/api/workspaces/{workspace['id']}/ingestion")
    assert reset_response.status_code == 200, reset_response.text

    assert all(path.exists() for path in source_paths)
    assert all(not path.exists() for path in managed_paths)


@pytest.mark.anyio
async def test_ingestion_progress_persists_during_active_work_and_clears_on_ready(
    client: httpx.AsyncClient,
    queued_batches: list[tuple[str, str]],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    workspace = await create_workspace(client)
    source_paths = [
        write_fastq(tmp_path / "tumor_R1.fastq", "tumor-r1", "AAAA"),
        write_fastq(tmp_path / "tumor_R2.fastq", "tumor-r2", "CCCC"),
    ]
    await register_lane_paths(client, workspace["id"], "tumor", source_paths)

    started = threading.Event()
    release = threading.Event()
    original_compress = workspace_store.compress_fastq_sources_to_gzip

    def blocked_compress(*args, **kwargs):
        started.set()
        assert release.wait(timeout=5), "Timed out waiting to resume compression"
        return original_compress(*args, **kwargs)

    monkeypatch.setattr(
        workspace_store,
        "compress_fastq_sources_to_gzip",
        blocked_compress,
    )

    workspace_id, batch_id = queued_batches.pop(0)
    errors: list[Exception] = []

    def run_worker() -> None:
        try:
            workspace_store.run_batch_normalization(workspace_id, batch_id)
        except Exception as error:  # pragma: no cover - surfaced below
            errors.append(error)

    worker = threading.Thread(target=run_worker)
    worker.start()
    assert started.wait(timeout=5), "Normalization never entered compression"

    in_progress_response = await client.get(f"/api/workspaces/{workspace['id']}")
    assert in_progress_response.status_code == 200, in_progress_response.text
    in_progress = in_progress_response.json()
    progress = in_progress["ingestion"]["lanes"]["tumor"]["progress"]
    assert progress is not None
    assert progress["phase"] == "compressing"
    assert progress["current_filename"]
    assert progress["total_bytes"] == sum(path.stat().st_size for path in source_paths)

    release.set()
    worker.join(timeout=10)
    assert not errors

    ready_response = await client.get(f"/api/workspaces/{workspace['id']}")
    assert ready_response.status_code == 200, ready_response.text
    ready = ready_response.json()
    assert ready["ingestion"]["lanes"]["tumor"]["status"] == "ready"
    assert ready["ingestion"]["lanes"]["tumor"]["progress"] is None


@pytest.mark.anyio
async def test_variant_calling_summary_is_blocked_before_alignment_completes(
    client: httpx.AsyncClient,
):
    workspace = await create_workspace(client)
    response = await client.get(
        f"/api/workspaces/{workspace['id']}/variant-calling"
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["status"] == "blocked"
    assert payload["ready_for_annotation"] is False
    assert payload["latest_run"] is None
    assert payload["artifacts"] == []
    assert payload["blocking_reason"]


@pytest.mark.anyio
async def test_variant_calling_run_creates_pending_record_after_alignment(
    client: httpx.AsyncClient,
    queued_batches: list[tuple[str, str]],
    queued_alignment_runs: list[tuple[str, str]],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    from app.services import variant_calling as variant_calling_service

    workspace = await prepare_alignment_ready_workspace(client, queued_batches, tmp_path)
    install_fake_alignment(monkeypatch, tmp_path)

    summary_response = await client.post(
        f"/api/workspaces/{workspace['id']}/alignment/run"
    )
    assert summary_response.status_code == 200, summary_response.text
    queued_workspace_id, alignment_run_id = queued_alignment_runs.pop(0)
    alignment_service.run_alignment(queued_workspace_id, alignment_run_id)

    preview_response = await client.get(
        f"/api/workspaces/{workspace['id']}/variant-calling"
    )
    assert preview_response.status_code == 200, preview_response.text
    preview_payload = preview_response.json()
    assert preview_payload["status"] == "scaffolded"
    assert preview_payload["latest_run"] is None

    # The variant-calling stage is now live. Queue runs without actually
    # invoking GATK so the test exercises the API + DB wiring.
    queued_variant_runs: list[tuple[str, str]] = []
    monkeypatch.setattr(
        variant_calling_service,
        "enqueue_variant_calling_run",
        lambda workspace_id, run_id: queued_variant_runs.append((workspace_id, run_id)),
    )

    run_response = await client.post(
        f"/api/workspaces/{workspace['id']}/variant-calling/run"
    )
    assert run_response.status_code == 200, run_response.text
    payload = run_response.json()
    assert payload["status"] == "running"
    assert payload["latest_run"]["status"] == "pending"
    assert queued_variant_runs and queued_variant_runs[0][0] == workspace["id"]

    rerun_response = await client.post(
        f"/api/workspaces/{workspace['id']}/variant-calling/rerun"
    )
    # A run is already pending/running, so a rerun attempt should be rejected
    # until the first terminates — mirroring the alignment pattern.
    assert rerun_response.status_code == 400, rerun_response.text

    with session_scope() as session:
        variant_run_statuses = session.scalars(
            select(PipelineRunRecord.status).where(
                PipelineRunRecord.workspace_id == workspace["id"],
                PipelineRunRecord.stage_id == "variant-calling",
            )
        ).all()

    assert len(variant_run_statuses) == 1
    assert variant_run_statuses[0] == "pending"


@pytest.mark.anyio
async def test_variant_calling_pause_preserves_shards_and_resume_restores_pending(
    client: httpx.AsyncClient,
    queued_batches: list[tuple[str, str]],
    queued_alignment_runs: list[tuple[str, str]],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    from app.runtime import get_variant_calling_run_root
    from app.services import variant_calling as variant_calling_service

    workspace = await prepare_alignment_ready_workspace(client, queued_batches, tmp_path)
    install_fake_alignment(monkeypatch, tmp_path)

    summary_response = await client.post(
        f"/api/workspaces/{workspace['id']}/alignment/run"
    )
    assert summary_response.status_code == 200, summary_response.text
    queued_workspace_id, alignment_run_id = queued_alignment_runs.pop(0)
    alignment_service.run_alignment(queued_workspace_id, alignment_run_id)

    queued_variant_runs: list[tuple[str, str]] = []
    monkeypatch.setattr(
        variant_calling_service,
        "enqueue_variant_calling_run",
        lambda workspace_id, run_id: queued_variant_runs.append((workspace_id, run_id)),
    )

    run_response = await client.post(
        f"/api/workspaces/{workspace['id']}/variant-calling/run"
    )
    assert run_response.status_code == 200, run_response.text
    variant_run_id = run_response.json()["latest_run"]["id"]

    # Fake a partially-completed run on disk: a few shards done.
    run_dir = get_variant_calling_run_root(workspace["id"], variant_run_id)
    shard_dir = run_dir / "shards"
    shard_dir.mkdir(parents=True, exist_ok=True)
    for contig in ("chr1", "chr2", "chr3"):
        (shard_dir / f"{contig}.vcf.gz").write_bytes(b"x")
        (shard_dir / f"{contig}.done").touch()

    # Flip to RUNNING so pause is a valid transition.
    with session_scope() as session:
        record = session.scalar(
            select(PipelineRunRecord).where(PipelineRunRecord.id == variant_run_id)
        )
        record.status = "running"

    pause_response = await client.post(
        f"/api/workspaces/{workspace['id']}/variant-calling/runs/{variant_run_id}/pause"
    )
    assert pause_response.status_code == 200, pause_response.text
    payload = pause_response.json()
    assert payload["status"] == "paused"
    assert payload["latest_run"]["status"] == "paused"
    assert payload["latest_run"]["completed_shards"] == 3
    assert payload["latest_run"]["total_shards"] == 3
    assert run_dir.exists()
    assert (shard_dir / "chr1.done").exists()

    # Resume flips back to pending and re-enqueues the worker.
    queued_variant_runs.clear()
    resume_response = await client.post(
        f"/api/workspaces/{workspace['id']}/variant-calling/runs/{variant_run_id}/resume"
    )
    assert resume_response.status_code == 200, resume_response.text
    resume_payload = resume_response.json()
    assert resume_payload["latest_run"]["status"] == "pending"
    assert queued_variant_runs == [(workspace["id"], variant_run_id)]
    # Shards survive resume.
    assert (shard_dir / "chr2.done").exists()


@pytest.mark.anyio
async def test_variant_calling_pause_kills_orphaned_subprocesses_via_pid_file(
    client: httpx.AsyncClient,
    queued_batches: list[tuple[str, str]],
    queued_alignment_runs: list[tuple[str, str]],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    """Orphans reparented to PID 1 (from a dead launching worker) must still be
    killed when pause is clicked — the in-memory Popen list is gone, so the
    fallback scans the pid_dir and validates via /proc/{pid}/cmdline."""
    import subprocess
    import time

    from app.services import variant_calling as variant_calling_service

    workspace = await prepare_alignment_ready_workspace(client, queued_batches, tmp_path)
    install_fake_alignment(monkeypatch, tmp_path)

    await client.post(f"/api/workspaces/{workspace['id']}/alignment/run")
    queued_workspace_id, alignment_run_id = queued_alignment_runs.pop(0)
    alignment_service.run_alignment(queued_workspace_id, alignment_run_id)

    monkeypatch.setattr(
        variant_calling_service, "enqueue_variant_calling_run", lambda *a, **k: None
    )
    run_response = await client.post(
        f"/api/workspaces/{workspace['id']}/variant-calling/run"
    )
    variant_run_id = run_response.json()["latest_run"]["id"]

    pid_dir = variant_calling_service._derive_pid_dir_on_disk(
        workspace["id"], variant_run_id
    )
    pid_dir.mkdir(parents=True, exist_ok=True)

    # Simulate an orphaned Mutect2 child: its cmdline must contain the run_id
    # so the fallback's safety check accepts it. ``start_new_session=True``
    # puts the dummy in its own process group — otherwise the killpg in the
    # fallback would also kill pytest.
    proc = subprocess.Popen(
        ["sh", "-c", f"sleep 30 # {variant_run_id}"],
        start_new_session=True,
    )
    try:
        (pid_dir / str(proc.pid)).touch()

        with session_scope() as session:
            record = session.scalar(
                select(PipelineRunRecord).where(PipelineRunRecord.id == variant_run_id)
            )
            record.status = "running"

        pause_response = await client.post(
            f"/api/workspaces/{workspace['id']}/variant-calling/runs/{variant_run_id}/pause"
        )
        assert pause_response.status_code == 200, pause_response.text
        assert pause_response.json()["latest_run"]["status"] == "paused"

        # Process should be dead, marker file cleaned up.
        for _ in range(40):
            if proc.poll() is not None:
                break
            time.sleep(0.1)
        assert proc.poll() is not None, "orphaned subprocess was not killed by pause"
        assert not (pid_dir / str(proc.pid)).exists()
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=2)


@pytest.mark.anyio
async def test_variant_calling_cancel_wipes_shards(
    client: httpx.AsyncClient,
    queued_batches: list[tuple[str, str]],
    queued_alignment_runs: list[tuple[str, str]],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    from app.runtime import get_variant_calling_run_root
    from app.services import variant_calling as variant_calling_service

    workspace = await prepare_alignment_ready_workspace(client, queued_batches, tmp_path)
    install_fake_alignment(monkeypatch, tmp_path)

    await client.post(f"/api/workspaces/{workspace['id']}/alignment/run")
    queued_workspace_id, alignment_run_id = queued_alignment_runs.pop(0)
    alignment_service.run_alignment(queued_workspace_id, alignment_run_id)

    monkeypatch.setattr(
        variant_calling_service, "enqueue_variant_calling_run", lambda *a, **k: None
    )
    run_response = await client.post(
        f"/api/workspaces/{workspace['id']}/variant-calling/run"
    )
    variant_run_id = run_response.json()["latest_run"]["id"]

    run_dir = get_variant_calling_run_root(workspace["id"], variant_run_id)
    (run_dir / "shards").mkdir(parents=True, exist_ok=True)
    (run_dir / "shards" / "chr1.done").touch()

    with session_scope() as session:
        record = session.scalar(
            select(PipelineRunRecord).where(PipelineRunRecord.id == variant_run_id)
        )
        record.status = "running"

    cancel_response = await client.post(
        f"/api/workspaces/{workspace['id']}/variant-calling/runs/{variant_run_id}/cancel"
    )
    assert cancel_response.status_code == 200, cancel_response.text
    payload = cancel_response.json()
    # A cancelled run drops the stage back to scaffolded (ready for a fresh run).
    assert payload["status"] == "scaffolded"
    assert payload["latest_run"]["status"] == "cancelled"
    assert not run_dir.exists()
