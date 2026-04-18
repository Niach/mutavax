"""Ensembl protein-domain lookups for the annotation mutation map.

Replaces the frontend's 12-gene hand-curated preset library with real
coordinates from Ensembl REST. One HTTP call per focused gene, cached
to disk so repeat reads are offline.

The contract: ``fetch_domains_for_ensp`` MUST NOT raise on a network
error, HTTP non-200, or a malformed response. Annotation has to land
gracefully even when the container is offline; a missing domain band
is always preferable to a failed run.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Iterable, Optional

import httpx

from app.models.schemas import ProteinDomain
from app.runtime import get_vep_cache_root

logger = logging.getLogger(__name__)

ENSEMBL_REST_BASE = "https://rest.ensembl.org"
# Filter to curated / well-named sources. Ensembl's protein_feature
# endpoint also returns Superfamily, Gene3D, Prints, Prosite_profiles
# etc.; those are noisier duplicates of Pfam + SMART.
KEEP_SOURCES = frozenset({"Pfam", "Smart"})

# Substrings (matched case-insensitively) that flag a domain as the
# "business end" — rendered in the theme accent. Everything else stays
# neutral grey.
CATALYTIC_KEYWORDS = (
    "kinase",
    "phosphatase",
    "set ",
    "set_",
    "sethd",
    "dna-binding",
    "dna binding",
    "brct",
    "wd40",
    "wd repeat",
    "brc",
    "heat",
    "ank",
    "ankyrin",
    "bromo",
    "chromo",
    "helicase",
    "tyrosine",
    "catalytic",
    "atpase",
)

_ENSP_RE = re.compile(r"(ENS[A-Z]*P\d+)(?:\.\d+)?")


def strip_version(ensp: str) -> str:
    """Normalise ENSP00000493543.1 → ENSP00000493543 for stable cache keys."""
    return ensp.split(".", 1)[0]


def parse_ensp_from_hgvsp(hgvsp: Optional[str]) -> Optional[str]:
    """Extract the ENSP id from ``"ENSP00000493543.1:p.Val600Glu"``.

    Returns the versionless ENSP so it matches the cache key. Works for
    canine (``ENSCAFP*``), feline (``ENSFCAP*``) and human IDs.
    """
    if not hgvsp:
        return None
    match = _ENSP_RE.search(hgvsp)
    if not match:
        return None
    return match.group(1)


def _cache_dir() -> Path:
    root = get_vep_cache_root() / "protein-features"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _cache_path(ensp: str) -> Path:
    return _cache_dir() / f"{strip_version(ensp)}.json"


def _classify_kind(label: str) -> str:
    low = label.lower()
    return "catalytic" if any(kw in low for kw in CATALYTIC_KEYWORDS) else "neutral"


def _pick_label(feature: dict) -> str:
    # Ensembl's response has: description (human readable), interpro_description
    # (usually richer), id (accession like PF07714). Prefer description, fall
    # back to interpro_description, last resort is the raw accession.
    for key in ("description", "interpro_description", "id"):
        value = feature.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return "domain"


def _dedupe_overlapping(domains: list[ProteinDomain]) -> list[ProteinDomain]:
    """Keep the longest band within any set of strictly-overlapping spans.

    Ensembl often returns several sources describing the same region
    (Pfam + SMART covering the same kinase domain with slightly shifted
    coordinates). For the lollipop we want one labelled band per region.
    """
    if not domains:
        return []
    ordered = sorted(domains, key=lambda d: (d.start, -(d.end - d.start)))
    kept: list[ProteinDomain] = []
    for candidate in ordered:
        replaced = False
        for idx, existing in enumerate(kept):
            # Overlap by more than 50% of the shorter band → treat as same
            # region and keep whichever is longer / has a richer label.
            overlap = max(
                0, min(candidate.end, existing.end) - max(candidate.start, existing.start)
            )
            shorter = min(candidate.end - candidate.start, existing.end - existing.start)
            if shorter > 0 and overlap / shorter >= 0.5:
                existing_len = existing.end - existing.start
                candidate_len = candidate.end - candidate.start
                if candidate_len > existing_len or (
                    candidate_len == existing_len and len(candidate.label) > len(existing.label)
                ):
                    kept[idx] = candidate
                replaced = True
                break
        if not replaced:
            kept.append(candidate)
    kept.sort(key=lambda d: d.start)
    return kept


def _parse_features(payload: Iterable[dict]) -> list[ProteinDomain]:
    domains: list[ProteinDomain] = []
    for feature in payload:
        source = feature.get("type") or feature.get("source") or ""
        if source not in KEEP_SOURCES:
            continue
        try:
            start = int(feature["start"])
            end = int(feature["end"])
        except (KeyError, TypeError, ValueError):
            continue
        if end <= start:
            continue
        label = _pick_label(feature)
        domains.append(
            ProteinDomain(
                start=start,
                end=end,
                label=label,
                kind=_classify_kind(label),  # type: ignore[arg-type]
            )
        )
    return _dedupe_overlapping(domains)


def _read_cache(ensp: str) -> Optional[list[ProteinDomain]]:
    path = _cache_path(ensp)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, list):
        return None
    try:
        return [ProteinDomain.model_validate(entry) for entry in payload]
    except Exception:  # noqa: BLE001 — malformed cache entry → refetch
        return None


def _write_cache(ensp: str, domains: list[ProteinDomain]) -> None:
    path = _cache_path(ensp)
    try:
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(
            json.dumps([d.model_dump(mode="json") for d in domains], indent=2)
        )
        tmp.replace(path)
    except OSError as error:
        logger.warning("Failed to write protein-features cache for %s: %s", ensp, error)


def fetch_domains_for_ensp(
    ensp: str,
    *,
    timeout_seconds: float = 5.0,
) -> list[ProteinDomain]:
    """Return curated protein-domain bands for an Ensembl ENSP id.

    Looks up the disk cache first. On a miss, hits
    ``{ENSEMBL_REST_BASE}/overlap/translation/{ENSP}?feature=protein_feature``,
    filters to Pfam + SMART, dedupes overlapping bands, writes the
    result to disk, and returns it. Any failure path returns an empty
    list — annotation MUST NOT crash on a domain lookup.
    """
    normalized = strip_version(ensp)

    cached = _read_cache(normalized)
    if cached is not None:
        return cached

    url = f"{ENSEMBL_REST_BASE}/overlap/translation/{normalized}"
    params = {"feature": "protein_feature"}
    headers = {"Accept": "application/json"}
    try:
        with httpx.Client(timeout=timeout_seconds) as client:
            response = client.get(url, params=params, headers=headers)
        if response.status_code != 200:
            logger.warning(
                "Ensembl protein_feature lookup for %s returned %s", normalized, response.status_code
            )
            return []
        payload = response.json()
    except (httpx.HTTPError, ValueError) as error:
        logger.warning("Ensembl protein_feature fetch for %s failed: %s", normalized, error)
        return []

    if not isinstance(payload, list):
        return []

    domains = _parse_features(payload)
    _write_cache(normalized, domains)
    return domains
