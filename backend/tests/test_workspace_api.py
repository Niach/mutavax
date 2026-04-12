import gzip
import io
from contextlib import closing
import threading
from pathlib import Path

import httpx
import pytest
from sqlalchemy import delete

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
async def test_alignment_run_persists_local_artifacts_and_unlocks_variant_stage(
    client: httpx.AsyncClient,
    queued_batches: list[tuple[str, str]],
    queued_alignment_runs: list[tuple[str, str]],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
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

    update_profile = await client.patch(
        f"/api/workspaces/{workspace['id']}/analysis-profile",
        json={"assay_type": "wgs"},
    )
    assert update_profile.status_code == 200, update_profile.text

    reference_path = tmp_path / "grch38.fa"
    reference_path.write_text(">chr1\nACGTACGTACGT\n", encoding="utf-8")
    monkeypatch.setattr(
        alignment_service,
        "ensure_reference_ready",
        lambda reference: reference_path,
    )

    def fake_execute_alignment_lane(
        *,
        workspace_display_name: str,
        workspace_id: str,
        sample_lane: SampleLane,
        reference_path: Path,
        r1_path: Path,
        r2_path: Path,
        working_dir: Path,
    ):
        bam_path = working_dir / f"{sample_lane.value}.aligned.bam"
        bai_path = working_dir / f"{sample_lane.value}.aligned.bam.bai"
        flagstat_path = working_dir / f"{sample_lane.value}.flagstat.txt"
        idxstats_path = working_dir / f"{sample_lane.value}.idxstats.txt"
        stats_path = working_dir / f"{sample_lane.value}.stats.txt"
        bam_path.write_text("bam", encoding="utf-8")
        bai_path.write_text("bai", encoding="utf-8")
        flagstat_path.write_text(
            "100 + 0 in total (QC-passed reads + QC-failed reads)\n"
            "95 + 0 mapped (95.00% : N/A)\n"
            "88 + 0 properly paired (88.00% : N/A)\n",
            encoding="utf-8",
        )
        idxstats_path.write_text("chr1\t12\t95\t0\n", encoding="utf-8")
        stats_path.write_text(
            "SN\traw total sequences:\t100\n"
            "SN\treads duplicated:\t20\n"
            "SN\tinsert size average:\t320\n",
            encoding="utf-8",
        )
        return alignment_service.LaneExecutionOutput(
            sample_lane=sample_lane,
            metrics=AlignmentLaneMetricsResponse(
                sample_lane=sample_lane,
                total_reads=100,
                mapped_reads=95,
                mapped_percent=95.0,
                properly_paired_percent=88.0,
                duplicate_percent=20.0,
                mean_insert_size=320.0,
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

    bam_artifact = next(
        artifact
        for artifact in completed["artifacts"]
        if artifact["artifact_kind"] == "bam" and artifact["sample_lane"] == "tumor"
    )
    download_response = await client.get(bam_artifact["download_path"])
    assert download_response.status_code == 200
    assert download_response.text == "bam"


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
