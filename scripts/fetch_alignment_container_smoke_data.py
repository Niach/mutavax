#!/usr/bin/env python3
from __future__ import annotations

import argparse
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Final
from urllib.request import Request, urlopen


DATASET_NAME: Final = "htslib-xx-pair"
DEFAULT_OUTPUT_ROOT: Final = Path("data") / "sample-data" / DATASET_NAME
DEFAULT_TIMEOUT_SECONDS: Final = 60
SAM_URL: Final = (
    "https://raw.githubusercontent.com/samtools/htslib/develop/test/xx%23pair.sam"
)
REFERENCE_URL: Final = (
    "https://raw.githubusercontent.com/samtools/htslib/develop/test/xx.fa"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Download a tiny public paired sample and materialize BAM/CRAM smoke fixtures."
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="Directory for the resulting tumor.bam, normal.cram, and xx.fa files.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=DEFAULT_TIMEOUT_SECONDS,
        help=f"Per-file download timeout in seconds. Defaults to {DEFAULT_TIMEOUT_SECONDS}.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing files in the output directory.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the planned work without downloading anything.",
    )
    return parser.parse_args()


def resolve_output_dir(args: argparse.Namespace) -> Path:
    if args.output_dir is not None:
        return args.output_dir
    return DEFAULT_OUTPUT_ROOT / "smoke"


def open_remote(url: str, timeout: int):
    request = Request(url, headers={"User-Agent": "cancerstudio-sample-data/1.0"})
    return urlopen(request, timeout=timeout)


def download_file(url: str, destination: Path, timeout: int) -> None:
    temporary_path = destination.with_suffix(destination.suffix + ".part")
    if temporary_path.exists():
        temporary_path.unlink()

    try:
        with open_remote(url, timeout) as response, temporary_path.open("wb") as handle:
            shutil.copyfileobj(response, handle)
        temporary_path.replace(destination)
    except Exception:
        if temporary_path.exists():
            temporary_path.unlink()
        raise


def docker_compose_command() -> list[str] | None:
    if shutil.which("docker"):
        return ["docker", "compose"]
    if shutil.which("docker-compose"):
        return ["docker-compose"]
    return None


def resolve_samtools_command(repo_root: Path) -> tuple[list[str], bool]:
    if shutil.which("samtools"):
        return ["samtools"], False

    compose = docker_compose_command()
    if compose is None:
        raise RuntimeError(
            "samtools was not found locally and docker compose is unavailable."
        )

    return (
        [
            *compose,
            "run",
            "--rm",
            "--no-deps",
            "-T",
            "-v",
            f"{repo_root}:/workspace",
            "-w",
            "/workspace",
            "backend",
            "samtools",
        ],
        True,
    )


def run_samtools(command: list[str], args: list[str]) -> None:
    subprocess.run([*command, *args], check=True)


def containerize_path(path: Path, repo_root: Path) -> str:
    return str(Path("/workspace") / path.resolve().relative_to(repo_root.resolve()))


def metadata_text(output_dir: Path) -> str:
    return "\n".join(
        [
            "Dataset: HTSlib tiny paired alignment sample",
            f"Source SAM: {SAM_URL}",
            f"Reference FASTA: {REFERENCE_URL}",
            "Outputs:",
            f"- {output_dir / 'tumor.bam'}",
            f"- {output_dir / 'normal.cram'}",
            f"- {output_dir / 'xx.fa'}",
            "Note: tumor.bam and normal.cram are both derived from the same public paired SAM fixture.",
            "",
        ]
    )


def main() -> int:
    args = parse_args()
    output_dir = resolve_output_dir(args).resolve()
    repo_root = Path(__file__).resolve().parents[1]

    print(f"Preparing alignment-container smoke data in {output_dir}")
    print(f"SAM source: {SAM_URL}")
    print(f"Reference source: {REFERENCE_URL}")

    if args.dry_run:
        print(f"[dry-run] xx.fa <= {REFERENCE_URL}")
        print(f"[dry-run] source.sam <= {SAM_URL}")
        print(
            f"[dry-run] tumor.bam and normal.cram will be materialized in {output_dir}"
        )
        return 0

    output_dir.mkdir(parents=True, exist_ok=True)
    reference_path = output_dir / "xx.fa"
    bam_path = output_dir / "tumor.bam"
    cram_path = output_dir / "normal.cram"

    if args.force or not reference_path.exists():
        print("Fetching xx.fa")
        download_file(REFERENCE_URL, reference_path, args.timeout)
    else:
        print(f"Skipping existing file: {reference_path}")

    samtools_command, uses_container_paths = resolve_samtools_command(repo_root)

    with tempfile.TemporaryDirectory(
        prefix="cancerstudio-alignment-smoke-",
        dir=repo_root,
    ) as temp_dir_name:
        temp_dir = Path(temp_dir_name)
        sam_path = temp_dir / "xx#pair.sam"
        print("Fetching xx#pair.sam")
        download_file(SAM_URL, sam_path, args.timeout)

        bam_output = (
            containerize_path(bam_path, repo_root)
            if uses_container_paths
            else str(bam_path)
        )
        cram_output = (
            containerize_path(cram_path, repo_root)
            if uses_container_paths
            else str(cram_path)
        )
        reference_arg = (
            containerize_path(reference_path, repo_root)
            if uses_container_paths
            else str(reference_path)
        )
        sam_input = (
            containerize_path(sam_path, repo_root)
            if uses_container_paths
            else str(sam_path)
        )

        if args.force or not bam_path.exists():
            print("Materializing tumor.bam")
            run_samtools(
                samtools_command,
                ["view", "-b", "-o", bam_output, sam_input],
            )
        else:
            print(f"Skipping existing file: {bam_path}")

        if args.force or not cram_path.exists():
            print("Materializing normal.cram")
            run_samtools(
                samtools_command,
                [
                    "view",
                    "-C",
                    "-T",
                    reference_arg,
                    "-o",
                    cram_output,
                    sam_input,
                ],
            )
        else:
            print(f"Skipping existing file: {cram_path}")

    (output_dir / "dataset-metadata.txt").write_text(
        metadata_text(output_dir),
        encoding="utf-8",
    )
    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
