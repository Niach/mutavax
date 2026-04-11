#!/usr/bin/env python3
from __future__ import annotations

import argparse
import gzip
import shutil
from pathlib import Path
from typing import Final
from urllib.request import Request, urlopen


DATASET_NAME: Final = "seqc2-hcc1395-wes-ll"
DEFAULT_OUTPUT_ROOT: Final = Path("data") / "sample-data" / DATASET_NAME
DEFAULT_READS_PER_FILE: Final = 50_000
DEFAULT_TIMEOUT_SECONDS: Final = 120
CHUNK_SIZE_BYTES: Final = 1024 * 1024

FILES: Final = (
    {
        "name": "tumor_R1.fastq.gz",
        "source_run": "SRR7890850",
        "library_name": "WES_LL_T_1",
        "sample_type": "tumor",
        "url": "https://ftp.sra.ebi.ac.uk/vol1/fastq/SRR789/000/SRR7890850/SRR7890850_1.fastq.gz",
    },
    {
        "name": "tumor_R2.fastq.gz",
        "source_run": "SRR7890850",
        "library_name": "WES_LL_T_1",
        "sample_type": "tumor",
        "url": "https://ftp.sra.ebi.ac.uk/vol1/fastq/SRR789/000/SRR7890850/SRR7890850_2.fastq.gz",
    },
    {
        "name": "normal_R1.fastq.gz",
        "source_run": "SRR7890851",
        "library_name": "WES_LL_N_1",
        "sample_type": "normal",
        "url": "https://ftp.sra.ebi.ac.uk/vol1/fastq/SRR789/001/SRR7890851/SRR7890851_1.fastq.gz",
    },
    {
        "name": "normal_R2.fastq.gz",
        "source_run": "SRR7890851",
        "library_name": "WES_LL_N_1",
        "sample_type": "normal",
        "url": "https://ftp.sra.ebi.ac.uk/vol1/fastq/SRR789/001/SRR7890851/SRR7890851_2.fastq.gz",
    },
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Download the SEQC2 HCC1395/HCC1395BL matched human exome pair "
            "with cancerstudio-friendly FASTQ names."
        )
    )
    parser.add_argument(
        "--mode",
        choices=("smoke", "full"),
        default="smoke",
        help=(
            "smoke streams a small subset from each FASTQ; "
            "full downloads the complete renamed files"
        ),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="Directory for the resulting FASTQ files. Defaults to data/sample-data/<dataset>/<mode>.",
    )
    parser.add_argument(
        "--reads",
        type=int,
        default=DEFAULT_READS_PER_FILE,
        help=(
            "Reads per FASTQ file in smoke mode. "
            f"Defaults to {DEFAULT_READS_PER_FILE}."
        ),
    )
    parser.add_argument(
        "--lines-per-file",
        type=int,
        help="Override the smoke subset size directly. Must be a positive multiple of 4.",
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
    return DEFAULT_OUTPUT_ROOT / args.mode


def resolve_line_limit(args: argparse.Namespace) -> int:
    if args.lines_per_file is not None:
        line_limit = args.lines_per_file
    else:
        line_limit = args.reads * 4

    if line_limit <= 0 or line_limit % 4 != 0:
        raise ValueError("Smoke subset size must be a positive multiple of 4 lines.")

    return line_limit


def metadata_text(mode: str, line_limit: int | None) -> str:
    lines = [
        "Dataset: SEQC2 HCC1395/HCC1395BL matched human exome pair",
        "Study: SRP162370 / PRJNA489865",
        "Tumor sample: HCC1395",
        "Normal sample: HCC1395BL",
        "Tumor run: SRR7890850 (WES_LL_T_1)",
        "Normal run: SRR7890851 (WES_LL_N_1)",
        "Source paper: https://pmc.ncbi.nlm.nih.gov/articles/PMC8578599/",
        "Naming note: cancerstudio requires R1/R2 in FASTQ filenames, so the ENA _1/_2 files are renamed here.",
        f"Mode: {mode}",
    ]
    if line_limit is not None:
        lines.append(f"Reads per FASTQ: {line_limit // 4}")
        lines.append(f"Lines per FASTQ: {line_limit}")

    lines.append("")
    lines.append("Files:")
    for entry in FILES:
        lines.append(
            f"- {entry['name']} <- {entry['source_run']} / {entry['library_name']} / {entry['url']}"
        )

    return "\n".join(lines) + "\n"


def open_remote(url: str, timeout: int):
    request = Request(url, headers={"User-Agent": "cancerstudio-sample-data/1.0"})
    return urlopen(request, timeout=timeout)


def write_metadata_file(output_dir: Path, mode: str, line_limit: int | None) -> None:
    (output_dir / "dataset-metadata.txt").write_text(
        metadata_text(mode, line_limit),
        encoding="utf-8",
    )


def download_full_file(url: str, destination: Path, timeout: int) -> None:
    with open_remote(url, timeout) as response, destination.open("wb") as handle:
        shutil.copyfileobj(response, handle, length=CHUNK_SIZE_BYTES)


def download_smoke_file(url: str, destination: Path, line_limit: int, timeout: int) -> None:
    written_lines = 0
    with open_remote(url, timeout) as response:
        with gzip.GzipFile(fileobj=response) as source_handle, gzip.open(
            destination,
            "wb",
        ) as destination_handle:
            for line in source_handle:
                destination_handle.write(line)
                written_lines += 1
                if written_lines >= line_limit:
                    break

    if written_lines < line_limit:
        raise RuntimeError(
            f"{url} ended after {written_lines} lines; expected at least {line_limit}."
        )


def download_file(
    *,
    mode: str,
    url: str,
    destination: Path,
    line_limit: int | None,
    timeout: int,
) -> None:
    temporary_path = destination.with_suffix(destination.suffix + ".part")
    if temporary_path.exists():
        temporary_path.unlink()

    try:
        if mode == "full":
            download_full_file(url, temporary_path, timeout)
        else:
            if line_limit is None:
                raise RuntimeError("Smoke mode requires a line limit.")
            download_smoke_file(url, temporary_path, line_limit, timeout)
        temporary_path.replace(destination)
    except Exception:
        if temporary_path.exists():
            temporary_path.unlink()
        raise


def main() -> int:
    args = parse_args()
    line_limit = None if args.mode == "full" else resolve_line_limit(args)
    output_dir = resolve_output_dir(args)

    print(f"Preparing {args.mode} dataset in {output_dir}")
    print("Source study: SRP162370 (SEQC2 HCC1395 tumor / HCC1395BL normal)")
    if line_limit is not None:
        print(f"Subset size: {line_limit // 4} reads per FASTQ ({line_limit} lines)")

    if args.dry_run:
        for entry in FILES:
            print(f"[dry-run] {entry['name']} <= {entry['url']}")
        print("[dry-run] dataset-metadata.txt will be written")
        return 0

    output_dir.mkdir(parents=True, exist_ok=True)
    write_metadata_file(output_dir, args.mode, line_limit)

    for entry in FILES:
        destination = output_dir / entry["name"]
        if destination.exists() and not args.force:
            print(f"Skipping existing file: {destination}")
            continue

        print(f"Fetching {entry['name']} from {entry['source_run']}")
        download_file(
            mode=args.mode,
            url=entry["url"],
            destination=destination,
            line_limit=line_limit,
            timeout=args.timeout,
        )
        print(f"Wrote {destination}")

    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
