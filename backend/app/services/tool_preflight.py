"""External-binary preflight checks for the live pipeline stages.

The ingestion and alignment routes shell out to ``samtools``, ``bwa-mem2`` and
``pigz``. When any of those is missing the subprocess raises ``FileNotFoundError``
which surfaces to the UI as an unfriendly raw stack trace. This module gives the
API a way to check up-front and raise a structured error the frontend can render
as an actionable callout.
"""

from __future__ import annotations

import os
import shlex
import shutil
from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class ToolRequirement:
    """A single external binary the backend depends on."""

    name: str
    """Human-readable label shown to users (e.g. ``samtools``)."""

    env_var: str | None
    """Optional environment variable that overrides the default binary name."""

    default_binary: str
    """Binary name looked up on PATH when the env override is unset."""

    install_hint: str
    """One-line install command shown to the user when the tool is missing."""

    def resolve_command(self) -> str:
        """Return the binary or command string we'll actually attempt to run.

        Honors the env override if set; otherwise returns the default name.
        """
        if self.env_var:
            configured = os.getenv(self.env_var)
            if configured:
                # Mirror resolve_pigz_command — accept shell-quoted multi-token values
                # and report the head token to shutil.which.
                tokens = shlex.split(configured)
                if tokens:
                    return tokens[0]
        return self.default_binary

    def is_available(self) -> bool:
        return shutil.which(self.resolve_command()) is not None


SAMTOOLS_REQUIREMENT = ToolRequirement(
    name="samtools",
    env_var="SAMTOOLS_BINARY",
    default_binary="samtools",
    install_hint="sudo apt-get install samtools  # or: brew install samtools",
)

BWA_MEM2_REQUIREMENT = ToolRequirement(
    name="bwa-mem2",
    env_var="ALIGNMENT_BWA_BINARY",
    default_binary="bwa-mem2",
    install_hint=(
        "Download the static linux build from "
        "https://github.com/bwa-mem2/bwa-mem2/releases and put bwa-mem2 on PATH "
        "(macOS: brew install bwa-mem2)"
    ),
)

PIGZ_REQUIREMENT = ToolRequirement(
    name="pigz",
    env_var="PIGZ_BINARY",
    default_binary="pigz",
    install_hint="sudo apt-get install pigz  # or: brew install pigz",
)


INGESTION_TOOLS: tuple[ToolRequirement, ...] = (
    SAMTOOLS_REQUIREMENT,
    PIGZ_REQUIREMENT,
)

ALIGNMENT_TOOLS: tuple[ToolRequirement, ...] = (
    SAMTOOLS_REQUIREMENT,
    BWA_MEM2_REQUIREMENT,
)


def ingestion_tools_for_paths(paths: Iterable[str]) -> tuple[ToolRequirement, ...]:
    """Return only the tools the actual ingestion path will exercise.

    The ingestion pipeline only invokes ``samtools`` when normalizing BAM/CRAM
    inputs, and only invokes ``pigz`` when it has to compress raw FASTQ. Already
    compressed ``.fastq.gz``/``.fq.gz`` inputs need neither — fail-up-front
    preflight should match that reality, otherwise tests and end users get
    blocked on tools they don't actually use.
    """
    needs_samtools = False
    needs_pigz = False
    for raw in paths:
        lowered = raw.lower()
        if lowered.endswith((".bam", ".cram")):
            needs_samtools = True
        elif lowered.endswith((".fastq", ".fq")):
            needs_pigz = True
        # .fastq.gz / .fq.gz: nothing extra required at registration time
    required: list[ToolRequirement] = []
    if needs_samtools:
        required.append(SAMTOOLS_REQUIREMENT)
    if needs_pigz:
        required.append(PIGZ_REQUIREMENT)
    return tuple(required)


class MissingToolError(RuntimeError):
    """Raised when one or more required external binaries are not on PATH."""

    def __init__(self, missing: list[ToolRequirement]) -> None:
        if not missing:
            raise ValueError("MissingToolError requires at least one missing tool")
        self.missing = missing
        names = ", ".join(tool.name for tool in missing)
        super().__init__(
            f"Required external binaries are not available locally: {names}. "
            "See README.md → System requirements for install instructions."
        )

    @property
    def tool_names(self) -> list[str]:
        return [tool.name for tool in self.missing]

    @property
    def install_hints(self) -> list[str]:
        return [tool.install_hint for tool in self.missing]

    def to_payload(self) -> dict[str, object]:
        """Structured payload for the FastAPI ``HTTPException`` detail field."""
        return {
            "code": "missing_tools",
            "tools": self.tool_names,
            "hints": self.install_hints,
            "message": str(self),
        }


def verify_tools(tools: Iterable[ToolRequirement]) -> None:
    """Raise :class:`MissingToolError` if any of *tools* is not available."""
    missing = [tool for tool in tools if not tool.is_available()]
    if missing:
        raise MissingToolError(missing)


# bwa-mem2's README quotes ~28 GB peak for GRCh38 indexing. Add a 2 GB buffer
# so we refuse to start when the OS-reported available memory is under 30 GB.
# This is deliberately pessimistic; freezing the user's box once is a much
# worse UX than a false-positive "insufficient memory" warning.
BWA_MEM2_INDEX_MEMORY_BYTES = 30 * 1024 * 1024 * 1024


def read_available_memory_bytes() -> int | None:
    """Return ``/proc/meminfo``'s ``MemAvailable`` in bytes, or ``None``.

    Returns ``None`` on non-Linux systems, or if the file is unreadable or
    the line is missing — the caller should treat that as "can't check,
    let the operation proceed" rather than blocking.
    """
    try:
        with open("/proc/meminfo", "r", encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("MemAvailable:"):
                    parts = line.split()
                    if len(parts) >= 2:
                        return int(parts[1]) * 1024
    except (OSError, ValueError):
        return None
    return None


class InsufficientMemoryError(RuntimeError):
    """Raised when a memory-intensive step would exceed free RAM."""

    def __init__(
        self,
        *,
        required_bytes: int,
        available_bytes: int | None,
        purpose: str,
    ) -> None:
        self.required_bytes = required_bytes
        self.available_bytes = available_bytes
        self.purpose = purpose
        required_gib = required_bytes / (1024 ** 3)
        if available_bytes is None:
            super().__init__(
                f"{purpose} needs about {required_gib:.0f} GB of free memory. "
                "Couldn't read /proc/meminfo to verify; close heavy apps first."
            )
        else:
            available_gib = available_bytes / (1024 ** 3)
            super().__init__(
                f"{purpose} needs about {required_gib:.0f} GB of free memory, "
                f"but only {available_gib:.1f} GB is available right now. "
                "Close heavy applications (browser, Electron, dev servers) and try again."
            )

    def to_payload(self) -> dict[str, object]:
        return {
            "code": "insufficient_memory",
            "required_bytes": self.required_bytes,
            "available_bytes": self.available_bytes,
            "purpose": self.purpose,
            "message": str(self),
        }


def verify_memory_for_bwa_mem2_index() -> None:
    """Refuse to start ``bwa-mem2 index`` when free RAM is below the threshold.

    Reads ``/proc/meminfo`` and raises :class:`InsufficientMemoryError` with a
    structured payload the API layer can surface as a 503. If ``/proc/meminfo``
    is unreadable (non-Linux, restricted container) we pass through and let
    the subprocess fail on its own — that's still better than silently freezing.
    """
    available = read_available_memory_bytes()
    if available is None:
        return
    if available < BWA_MEM2_INDEX_MEMORY_BYTES:
        raise InsufficientMemoryError(
            required_bytes=BWA_MEM2_INDEX_MEMORY_BYTES,
            available_bytes=available,
            purpose="Reference indexing (bwa-mem2 index)",
        )
