"""External-binary preflight checks for the live pipeline stages.

The ingestion and alignment routes shell out to ``samtools``, ``strobealign`` and
``pigz``. When any of those is missing the subprocess raises ``FileNotFoundError``
which surfaces to the UI as an unfriendly raw stack trace. This module gives the
API a way to check up-front and raise a structured error the frontend can render
as an actionable callout.
"""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
from dataclasses import dataclass
from functools import lru_cache
from typing import Iterable, Literal


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

STROBEALIGN_REQUIREMENT = ToolRequirement(
    name="strobealign",
    env_var="ALIGNMENT_STROBEALIGN_BINARY",
    default_binary="strobealign",
    install_hint=(
        "Build from source: git clone https://github.com/ksahlin/strobealign "
        "&& cmake -B build -S strobealign -DCMAKE_BUILD_TYPE=Release "
        "&& make -C build && install build/strobealign on PATH "
        "(macOS: brew install strobealign; bioconda: conda install -c bioconda strobealign)"
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
    STROBEALIGN_REQUIREMENT,
)


GATK_REQUIREMENT = ToolRequirement(
    name="gatk",
    env_var="GATK_BINARY",
    default_binary="gatk",
    install_hint=(
        "Install GATK 4: bash scripts/install-bioinformatics-deps.sh  "
        "(requires OpenJDK 17+). Manual: download gatk-4.x.zip from "
        "https://github.com/broadinstitute/gatk/releases and put the `gatk` wrapper on PATH."
    ),
)


VARIANT_CALLING_TOOLS: tuple[ToolRequirement, ...] = (
    SAMTOOLS_REQUIREMENT,
    GATK_REQUIREMENT,
)


VEP_REQUIREMENT = ToolRequirement(
    name="vep",
    env_var="VEP_BINARY",
    default_binary="vep",
    install_hint=(
        "Install Ensembl VEP: git clone https://github.com/Ensembl/ensembl-vep "
        "&& cd ensembl-vep && perl INSTALL.pl --AUTO a  "
        "(requires Perl + Bio::DB::HTS). The cancerstudio backend image installs "
        "VEP release 111 automatically — if you see this message you are running "
        "the backend natively outside the container."
    ),
)


ANNOTATION_TOOLS: tuple[ToolRequirement, ...] = (
    VEP_REQUIREMENT,
)


PVACSEQ_REQUIREMENT = ToolRequirement(
    name="pvacseq",
    env_var="PVACSEQ_BINARY",
    default_binary="pvacseq",
    install_hint=(
        "Install pVACtools: python -m pip install pvactools. The cancerstudio "
        "backend image installs it automatically — if you see this message you "
        "are running the backend natively outside the container."
    ),
)


NETMHCPAN_REQUIREMENT = ToolRequirement(
    name="NetMHCpan 4.1",
    env_var="CANCERSTUDIO_NETMHCPAN_BIN",
    default_binary="netMHCpan",
    install_hint=(
        "NetMHCpan 4.1 requires a free academic license from DTU (https://services.healthtech.dtu.dk/). "
        "Download the linux tarball, extract it under ${CANCERSTUDIO_DATA_ROOT}/netmhc/netMHCpan-4.1/, "
        "and edit its top-level wrapper script so the binary is on PATH."
    ),
)


NETMHCIIPAN_REQUIREMENT = ToolRequirement(
    name="NetMHCIIpan 4.3",
    env_var="CANCERSTUDIO_NETMHCIIPAN_BIN",
    default_binary="netMHCIIpan",
    install_hint=(
        "NetMHCIIpan 4.3 requires a free academic license from DTU. Extract under "
        "${CANCERSTUDIO_DATA_ROOT}/netmhc/netMHCIIpan-4.3/ (mounted read-only into the container)."
    ),
)


NEOANTIGEN_TOOLS: tuple[ToolRequirement, ...] = (
    PVACSEQ_REQUIREMENT,
    NETMHCPAN_REQUIREMENT,
    NETMHCIIPAN_REQUIREMENT,
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


# --------------------------------------------------------------------------- #
# GPU detection (drives variant calling Parabricks vs. CPU GATK dispatch)
# --------------------------------------------------------------------------- #


AccelerationMode = Literal["gpu_parabricks", "cpu_gatk"]


@lru_cache(maxsize=1)
def detect_gpu_available() -> bool:
    """Return True iff `nvidia-smi` succeeds and reports at least one GPU.

    Honors ``CANCERSTUDIO_VC_FORCE_CPU=1`` as a hard override for users or
    CI that want to exercise the CPU path from inside a GPU-capable image.
    Cached — GPU presence doesn't change within a process lifetime.
    """
    if os.getenv("CANCERSTUDIO_VC_FORCE_CPU") == "1":
        return False
    if shutil.which("nvidia-smi") is None:
        return False
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
            capture_output=True,
            text=True,
            timeout=5.0,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    if result.returncode != 0:
        return False
    return any(line.strip() for line in result.stdout.splitlines())


def current_acceleration_mode() -> AccelerationMode:
    """Resolve the acceleration mode for variant calling."""
    return "gpu_parabricks" if detect_gpu_available() else "cpu_gatk"


# Strobealign peaks at ~31 GB building the hg38 strobemer index (544M syncmer
# seeds) and ~25–33 GB during alignment. A 35 GB threshold gives a ~2 GB safety
# buffer over the indexing peak and ~2 GB over the alignment peak — enough that
# the rest of the desktop stack (Electron, renderer, samtools sort stream,
# Mutect2 later) doesn't get pushed into swap.
STROBEALIGN_INDEX_MEMORY_BYTES = 35 * 1024 * 1024 * 1024


def read_available_memory_bytes() -> int | None:
    """Return ``/proc/meminfo``'s ``MemAvailable`` in bytes, or ``None``.

    Returns ``None`` on non-Linux systems, or if the file is unreadable or
    the line is missing — the caller should treat that as "can't check,
    let the operation proceed" rather than blocking.
    """
    return _read_meminfo_field_bytes("MemAvailable")


def read_total_memory_bytes() -> int | None:
    """Return ``/proc/meminfo``'s ``MemTotal`` in bytes, or ``None``.

    Same semantics as :func:`read_available_memory_bytes` — non-Linux or
    unreadable ``/proc/meminfo`` returns ``None``.
    """
    return _read_meminfo_field_bytes("MemTotal")


def _read_meminfo_field_bytes(label: str) -> int | None:
    try:
        with open("/proc/meminfo", "r", encoding="utf-8") as handle:
            for line in handle:
                if line.startswith(f"{label}:"):
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


def verify_memory_for_strobealign_index() -> None:
    """Refuse to start ``strobealign --create-index`` when free RAM is below the threshold.

    Reads ``/proc/meminfo`` and raises :class:`InsufficientMemoryError` with a
    structured payload the API layer can surface as a 503. If ``/proc/meminfo``
    is unreadable (non-Linux, restricted container) we pass through and let
    the subprocess fail on its own — that's still better than silently freezing.
    """
    available = read_available_memory_bytes()
    if available is None:
        return
    if available < STROBEALIGN_INDEX_MEMORY_BYTES:
        raise InsufficientMemoryError(
            required_bytes=STROBEALIGN_INDEX_MEMORY_BYTES,
            available_bytes=available,
            purpose="Reference indexing (strobealign --create-index)",
        )
