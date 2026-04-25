"""Small, explicit data downloader for MHC-II research assets."""

from __future__ import annotations

import hashlib
import json
import urllib.request
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from app.research.mhc2.constants import DATA_SOURCES, DataSource


HLAIIPRED_FILES = {
    "train_positive.csv": "https://zenodo.org/api/records/15299217/files/train_positive.csv/content",
    "valid_positive.csv": "https://zenodo.org/api/records/15299217/files/valid_positive.csv/content",
    "test_positive.csv": "https://zenodo.org/api/records/15299217/files/test_positive.csv/content",
}

NETMHCIIPAN_FILES = {
    "NetMHCIIpan_train.tar.gz": "https://services.healthtech.dtu.dk/suppl/immunology/NetMHCIIpan-4.3/NetMHCIIpan_train.tar.gz",
    "NetMHCIIpan_eval.fa": "https://services.healthtech.dtu.dk/suppl/immunology/NetMHCIIpan-4.3/NetMHCIIpan_eval.fa",
}

IPD_IMGT_HLA_FILES = {
    "Allelelist.txt": "https://raw.githubusercontent.com/ANHIG/IMGTHLA/Latest/Allelelist.txt",
}


def fetch_source(key: str, destination: Path, dry_run: bool = False) -> dict:
    if key not in DATA_SOURCES:
        raise KeyError(f"unknown MHC-II data source: {key}")
    source = DATA_SOURCES[key]
    urls = _urls_for(source)
    destination.mkdir(parents=True, exist_ok=True)
    manifest = {
        "source": asdict(source),
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "dry_run": dry_run,
        "files": [],
    }
    for filename, url in urls.items():
        target = destination / filename
        entry = {"filename": filename, "url": url, "path": str(target)}
        if dry_run:
            manifest["files"].append(entry)
            continue
        sha256 = _download(url, target)
        entry["sha256"] = sha256
        entry["size_bytes"] = target.stat().st_size
        manifest["files"].append(entry)
    manifest_path = destination / f"{key}.manifest.json"
    if not dry_run:
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return manifest


def available_sources() -> list[DataSource]:
    return list(DATA_SOURCES.values())


def _urls_for(source: DataSource) -> dict[str, str]:
    if source.key == "hlaiipred_zenodo":
        return HLAIIPRED_FILES
    if source.key == "netmhciipan_43":
        return NETMHCIIPAN_FILES
    if source.key == "ipd_imgt_hla":
        return IPD_IMGT_HLA_FILES
    raise ValueError(
        f"{source.key} has no direct downloader yet; use the source URL and place files manually."
    )


def _download(url: str, target: Path) -> str:
    hasher = hashlib.sha256()
    request = urllib.request.Request(url, headers={"User-Agent": "cancerstudio-mhc2/0.1"})
    with urllib.request.urlopen(request, timeout=600) as response:
        with target.open("wb") as handle:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                hasher.update(chunk)
                handle.write(chunk)
    return hasher.hexdigest()

