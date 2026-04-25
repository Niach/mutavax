"""Allele and heterodimer normalization for HLA class II research data."""

from __future__ import annotations

import re
from dataclasses import dataclass


_GENE_RE = re.compile(r"^(?:HLA[-_]?)?(DRA|DRA1|DRB[1-9]|DQA1|DQB1|DPA1|DPB1)\*?(.+)?$")


@dataclass(frozen=True)
class MHC2Allele:
    raw: str
    normalized: str
    locus: str
    alpha: str | None = None
    beta: str | None = None


def normalize_mhc2_allele(value: str) -> MHC2Allele:
    """Normalize common HLA-II allele/dimer strings.

    DR records are normalized to the beta-chain form used by HLAIIPred
    (for example ``HLA-DRB1*15:01``). DP/DQ records are normalized as
    alpha-beta heterodimers (for example
    ``HLA-DQA1*03:01-DQB1*04:01``).
    """
    raw = value.strip()
    if not raw or raw in {"0", "NA", "N/A", "None", "nan"}:
        raise ValueError("empty MHC-II allele")

    parts = _split_dimer(raw)
    normalized_parts = [_normalize_chain(part) for part in parts]
    alpha = next((p for p in normalized_parts if _chain_role(p) == "alpha"), None)
    beta = next((p for p in normalized_parts if _chain_role(p) == "beta"), None)

    locus = _infer_locus(normalized_parts)
    if locus == "DR":
        if beta is None:
            raise ValueError(f"DR allele lacks a beta chain: {value!r}")
        return MHC2Allele(raw=raw, normalized=beta, locus=locus, alpha=alpha, beta=beta)

    if alpha is None or beta is None:
        raise ValueError(f"{locus} allele must include alpha and beta chains: {value!r}")
    normalized = f"{alpha}-{_strip_hla_prefix(beta)}"
    return MHC2Allele(
        raw=raw,
        normalized=normalized,
        locus=locus,
        alpha=alpha,
        beta=beta,
    )


def normalize_many(values: list[str] | tuple[str, ...]) -> tuple[str, ...]:
    normalized: list[str] = []
    seen: set[str] = set()
    for value in values:
        allele = normalize_mhc2_allele(value).normalized
        if allele not in seen:
            seen.add(allele)
            normalized.append(allele)
    return tuple(normalized)


def _split_dimer(value: str) -> list[str]:
    text = value.strip().replace("__", "-").replace("/", "-")
    text = re.sub(r"\s+", "", text)
    parts = [part for part in text.split("-") if part]
    if len(parts) == 1:
        return parts
    if len(parts) == 2 and parts[0].upper() == "HLA":
        return [f"HLA-{parts[1]}"]
    if len(parts) == 3 and parts[0].upper() == "HLA":
        return [f"HLA-{parts[1]}", parts[2]]
    return parts


def _normalize_chain(value: str) -> str:
    text = value.strip().upper().replace("_", "-")
    match = _GENE_RE.match(text)
    if not match:
        raise ValueError(f"unrecognized MHC-II allele chain: {value!r}")
    gene, fields = match.groups()
    if not fields:
        raise ValueError(f"MHC-II allele chain lacks fields: {value!r}")
    fields = fields.replace("*", "").replace("-", ":")
    return f"HLA-{gene}*{fields}"


def _strip_hla_prefix(value: str) -> str:
    return value.removeprefix("HLA-")


def _chain_role(value: str) -> str:
    chain = value.removeprefix("HLA-").split("*", 1)[0]
    if chain in {"DRA", "DRA1", "DQA1", "DPA1"}:
        return "alpha"
    return "beta"


def _infer_locus(parts: list[str]) -> str:
    joined = " ".join(parts)
    if "DR" in joined:
        return "DR"
    if "DQ" in joined:
        return "DQ"
    if "DP" in joined:
        return "DP"
    raise ValueError(f"could not infer MHC-II locus from {parts!r}")
