#!/usr/bin/env python3
from __future__ import annotations

import argparse
import gzip
import hashlib
import shutil
from pathlib import Path
from typing import Final
from urllib.request import Request, urlopen


DATASET_NAME: Final = "colo829-wgs"
DEFAULT_OUTPUT_ROOT: Final = Path("data") / "sample-data" / DATASET_NAME
DEFAULT_READS_PER_FILE: Final = 50_000
DEFAULT_TIMEOUT_SECONDS: Final = 1800
CHUNK_SIZE_BYTES: Final = 1024 * 1024

FILES: Final = (
    {
        "name": "tumor_R1.fastq.gz",
        "source_run": "ERR2752450",
        "library_name": "COLO829T_WGS",
        "sample_type": "tumor",
        "url": "https://ftp.sra.ebi.ac.uk/vol1/fastq/ERR275/000/ERR2752450/ERR2752450_1.fastq.gz",
        "md5": "306a35f4440940f26f60f322d47d826a",
    },
    {
        "name": "tumor_R2.fastq.gz",
        "source_run": "ERR2752450",
        "library_name": "COLO829T_WGS",
        "sample_type": "tumor",
        "url": "https://ftp.sra.ebi.ac.uk/vol1/fastq/ERR275/000/ERR2752450/ERR2752450_2.fastq.gz",
        "md5": "fcf0f47b218c44b91861a1c311a4cf5f",
    },
    {
        "name": "normal_R1.fastq.gz",
        "source_run": "ERR2752449",
        "library_name": "COLO829BL_WGS",
        "sample_type": "normal",
        "url": "https://ftp.sra.ebi.ac.uk/vol1/fastq/ERR275/009/ERR2752449/ERR2752449_1.fastq.gz",
        "md5": "9acf7704dc1fff0a68c18b1de9f492c4",
    },
    {
        "name": "normal_R2.fastq.gz",
        "source_run": "ERR2752449",
        "library_name": "COLO829BL_WGS",
        "sample_type": "normal",
        "url": "https://ftp.sra.ebi.ac.uk/vol1/fastq/ERR275/009/ERR2752449/ERR2752449_2.fastq.gz",
        "md5": "4bb3d714a195ad36cc91e371c40cc153",
    },
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Download the COLO829/COLO829BL matched human melanoma whole-genome "
            "pair (PRJEB27698, Illumina HiSeq X Ten) with cancerstudio-friendly "
            "FASTQ names."
        )
    )
    parser.add_argument(
        "--mode",
        choices=("smoke", "full"),
        default="smoke",
        help=(
            "smoke streams a small subset from each FASTQ; "
            "full downloads the complete renamed files (~174 GB total)"
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
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Verify existing files against the published ENA md5s without downloading.",
    )
    return parser.parse_args()


def compute_md5(path: Path) -> str:
    digest = hashlib.md5()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(CHUNK_SIZE_BYTES), b""):
            digest.update(block)
    return digest.hexdigest()


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
        "Dataset: COLO829/COLO829BL matched human melanoma whole-genome pair",
        "Study: PRJEB27698",
        "Source paper: Valle-Inclan et al., Cell Genomics 2022 — https://doi.org/10.1016/j.xgen.2022.100139",
        "Tumor sample: COLO829 (metastatic cutaneous melanoma cell line)",
        "Normal sample: COLO829BL (matched B-lymphoblastoid cell line)",
        "Tumor run: ERR2752450 (COLO829T_WGS, ~1.00 B read pairs, Illumina HiSeq X Ten, ~100x coverage)",
        "Normal run: ERR2752449 (COLO829BL_WGS, ~378 M read pairs, Illumina HiSeq X Ten, ~38x coverage)",
        "Coverage note: tumor is ~2.6x deeper than normal. Acceptable for Mutect2; surface in downstream QC.",
        "Full-mode footprint: ~174 GB compressed (tumor ~125 GB + normal ~49 GB).",
        "Truth set: Hartwig COLO829 somatic SNV/indel/SV truth set — https://zenodo.org/records/4716169",
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
    expected_md5: str | None,
) -> None:
    temporary_path = destination.with_suffix(destination.suffix + ".part")
    if temporary_path.exists():
        temporary_path.unlink()

    try:
        if mode == "full":
            download_full_file(url, temporary_path, timeout)
            if expected_md5 is not None:
                actual = compute_md5(temporary_path)
                if actual != expected_md5:
                    raise RuntimeError(
                        f"md5 mismatch after downloading {url}: expected {expected_md5}, got {actual}"
                    )
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
    print("Source study: PRJEB27698 (COLO829 tumor / COLO829BL normal, Illumina HiSeq X Ten WGS)")
    if args.mode == "full":
        print("Full-mode footprint: ~174 GB compressed (tumor ~125 GB + normal ~49 GB).")
    if line_limit is not None:
        print(f"Subset size: {line_limit // 4} reads per FASTQ ({line_limit} lines)")

    if args.verify:
        if args.mode != "full":
            raise SystemExit("--verify is only meaningful with --mode full (smoke files are subset copies, not ENA-hash-comparable).")
        mismatched: list[str] = []
        for entry in FILES:
            destination = output_dir / entry["name"]
            if not destination.exists():
                print(f"MISSING  {entry['name']}")
                mismatched.append(entry["name"])
                continue
            actual = compute_md5(destination)
            expected = entry["md5"]
            if actual == expected:
                print(f"OK       {entry['name']}  {actual}")
            else:
                print(f"MISMATCH {entry['name']}  expected {expected}  got {actual}")
                mismatched.append(entry["name"])
        if mismatched:
            raise SystemExit(f"md5 verification failed for: {', '.join(mismatched)}")
        print("All files match published ENA md5s.")
        return 0

    if args.dry_run:
        for entry in FILES:
            print(f"[dry-run] {entry['name']} <= {entry['url']}")
        print("[dry-run] dataset-metadata.txt will be written")
        return 0

    output_dir.mkdir(parents=True, exist_ok=True)
    write_metadata_file(output_dir, args.mode, line_limit)

    for entry in FILES:
        destination = output_dir / entry["name"]
        expected_md5 = entry["md5"] if args.mode == "full" else None
        if destination.exists() and not args.force:
            if expected_md5 is not None:
                actual = compute_md5(destination)
                if actual != expected_md5:
                    print(
                        f"md5 mismatch on existing {destination.name} "
                        f"(expected {expected_md5}, got {actual}); re-downloading."
                    )
                    destination.unlink()
                else:
                    print(f"Skipping existing file (md5 OK): {destination}")
                    continue
            else:
                print(f"Skipping existing file: {destination}")
                continue

        print(f"Fetching {entry['name']} from {entry['source_run']}")
        download_file(
            mode=args.mode,
            url=entry["url"],
            destination=destination,
            line_limit=line_limit,
            timeout=args.timeout,
            expected_md5=expected_md5,
        )
        print(f"Wrote {destination}")

    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
