"""Unit tests for the external-binary preflight check."""

from __future__ import annotations

import pytest

from app.services import tool_preflight
from app.services.tool_preflight import (
    ALIGNMENT_TOOLS,
    BWA_MEM2_INDEX_MEMORY_BYTES,
    BWA_MEM2_REQUIREMENT,
    INGESTION_TOOLS,
    InsufficientMemoryError,
    MissingToolError,
    PIGZ_REQUIREMENT,
    SAMTOOLS_REQUIREMENT,
    ToolRequirement,
    ingestion_tools_for_paths,
    verify_memory_for_bwa_mem2_index,
    verify_tools,
)


def _which_factory(missing: set[str]):
    def fake_which(binary: str, *args, **kwargs):
        return None if binary in missing else f"/usr/bin/{binary}"

    return fake_which


def test_verify_tools_passes_when_all_present(monkeypatch):
    monkeypatch.setattr(tool_preflight.shutil, "which", _which_factory(set()))
    verify_tools(ALIGNMENT_TOOLS)
    verify_tools(INGESTION_TOOLS)


def test_verify_tools_raises_listing_missing_binary(monkeypatch):
    monkeypatch.setattr(tool_preflight.shutil, "which", _which_factory({"samtools"}))

    with pytest.raises(MissingToolError) as exc_info:
        verify_tools(ALIGNMENT_TOOLS)

    error = exc_info.value
    assert error.tool_names == ["samtools"]
    assert "samtools" in error.install_hints[0]
    assert "samtools" in str(error)


def test_verify_tools_lists_all_missing_tools(monkeypatch):
    monkeypatch.setattr(
        tool_preflight.shutil,
        "which",
        _which_factory({"samtools", "bwa-mem2"}),
    )

    with pytest.raises(MissingToolError) as exc_info:
        verify_tools(ALIGNMENT_TOOLS)

    assert set(exc_info.value.tool_names) == {"samtools", "bwa-mem2"}


def test_payload_shape_matches_api_contract(monkeypatch):
    monkeypatch.setattr(tool_preflight.shutil, "which", _which_factory({"pigz"}))

    with pytest.raises(MissingToolError) as exc_info:
        verify_tools(INGESTION_TOOLS)

    payload = exc_info.value.to_payload()
    assert payload["code"] == "missing_tools"
    assert payload["tools"] == ["pigz"]
    assert isinstance(payload["hints"], list) and payload["hints"]
    assert "pigz" in payload["message"]


def test_env_override_is_used_for_resolution(monkeypatch):
    monkeypatch.setenv("SAMTOOLS_BINARY", "/opt/custom/samtools")
    # Only the override path is "missing"; the default name resolves fine.
    monkeypatch.setattr(
        tool_preflight.shutil,
        "which",
        _which_factory({"/opt/custom/samtools"}),
    )

    with pytest.raises(MissingToolError) as exc_info:
        verify_tools((SAMTOOLS_REQUIREMENT,))

    assert exc_info.value.tool_names == ["samtools"]


def test_env_override_with_quoted_args(monkeypatch):
    monkeypatch.setenv("PIGZ_BINARY", '"/opt/p/pigz" --custom')
    monkeypatch.setattr(
        tool_preflight.shutil,
        "which",
        _which_factory({"/opt/p/pigz"}),
    )

    with pytest.raises(MissingToolError) as exc_info:
        verify_tools((PIGZ_REQUIREMENT,))

    assert exc_info.value.tool_names == ["pigz"]


def test_missing_tool_error_requires_tools():
    with pytest.raises(ValueError):
        MissingToolError([])


def test_alignment_and_ingestion_tool_sets_overlap_on_samtools():
    # Sanity: a missing samtools should surface from both pipelines.
    align_names = {tool.name for tool in ALIGNMENT_TOOLS}
    ingest_names = {tool.name for tool in INGESTION_TOOLS}
    assert "samtools" in align_names
    assert "samtools" in ingest_names
    assert BWA_MEM2_REQUIREMENT in ALIGNMENT_TOOLS
    assert PIGZ_REQUIREMENT in INGESTION_TOOLS


def test_tool_requirement_resolves_default_when_env_unset(monkeypatch):
    monkeypatch.delenv("SAMTOOLS_BINARY", raising=False)
    requirement = ToolRequirement(
        name="samtools",
        env_var="SAMTOOLS_BINARY",
        default_binary="samtools",
        install_hint="install it",
    )
    assert requirement.resolve_command() == "samtools"


def test_ingestion_tools_skipped_for_compressed_fastq():
    # The existing e2e fixtures hand us .fastq.gz files. They need neither
    # samtools (no BAM/CRAM normalization) nor pigz (already compressed).
    needed = ingestion_tools_for_paths(
        [
            "/data/normal_R1.fastq.gz",
            "/data/normal_R2.fastq.gz",
            "/data/tumor_R1.fq.gz",
        ]
    )
    assert needed == ()


def test_ingestion_tools_includes_samtools_for_bam_input():
    needed = ingestion_tools_for_paths(["/data/sample.bam"])
    assert SAMTOOLS_REQUIREMENT in needed
    assert PIGZ_REQUIREMENT not in needed


def test_ingestion_tools_includes_pigz_for_uncompressed_fastq():
    needed = ingestion_tools_for_paths(["/data/sample_R1.fastq", "/data/sample_R2.fq"])
    assert PIGZ_REQUIREMENT in needed
    assert SAMTOOLS_REQUIREMENT not in needed


def test_ingestion_tools_includes_both_for_mixed_input():
    needed = ingestion_tools_for_paths(
        ["/data/sample.cram", "/data/extra_R1.fastq"]
    )
    assert set(needed) == {SAMTOOLS_REQUIREMENT, PIGZ_REQUIREMENT}


def test_memory_preflight_passes_when_enough_free(monkeypatch):
    monkeypatch.setattr(
        tool_preflight,
        "read_available_memory_bytes",
        lambda: BWA_MEM2_INDEX_MEMORY_BYTES + 1024,
    )
    verify_memory_for_bwa_mem2_index()


def test_memory_preflight_raises_when_below_threshold(monkeypatch):
    below = BWA_MEM2_INDEX_MEMORY_BYTES - 1024 * 1024 * 1024  # 1 GB short
    monkeypatch.setattr(
        tool_preflight,
        "read_available_memory_bytes",
        lambda: below,
    )

    with pytest.raises(InsufficientMemoryError) as exc_info:
        verify_memory_for_bwa_mem2_index()

    error = exc_info.value
    assert error.required_bytes == BWA_MEM2_INDEX_MEMORY_BYTES
    assert error.available_bytes == below
    assert "bwa-mem2 index" in error.purpose


def test_memory_preflight_passes_when_proc_unreadable(monkeypatch):
    # On non-Linux hosts /proc/meminfo is missing; don't block the user — let
    # the subprocess try and raise its own error if it runs out.
    monkeypatch.setattr(
        tool_preflight,
        "read_available_memory_bytes",
        lambda: None,
    )
    verify_memory_for_bwa_mem2_index()


def test_insufficient_memory_payload_shape():
    error = InsufficientMemoryError(
        required_bytes=BWA_MEM2_INDEX_MEMORY_BYTES,
        available_bytes=1024 * 1024 * 1024,
        purpose="Reference indexing",
    )
    payload = error.to_payload()
    assert payload["code"] == "insufficient_memory"
    assert payload["required_bytes"] == BWA_MEM2_INDEX_MEMORY_BYTES
    assert payload["available_bytes"] == 1024 * 1024 * 1024
    assert payload["purpose"] == "Reference indexing"
    assert isinstance(payload["message"], str) and payload["message"]


def test_insufficient_memory_payload_handles_unknown_available():
    error = InsufficientMemoryError(
        required_bytes=BWA_MEM2_INDEX_MEMORY_BYTES,
        available_bytes=None,
        purpose="Reference indexing",
    )
    payload = error.to_payload()
    assert payload["available_bytes"] is None
    assert "about 30 GB" in payload["message"]
