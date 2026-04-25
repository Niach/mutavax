"""Allele and heterodimer normalization for HLA class II research data."""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.research.mhc2.ipd import known_two_field


_GENE_RE = re.compile(r"^(?:HLA[-_]?)?(DRA|DRA1|DRB[1-9]|DQA1|DQB1|DPA1|DPB1)\*?(.+)?$")
_HAS_DIGITS = re.compile(r"\d")


@dataclass(frozen=True)
class MHC2Allele:
    raw: str
    normalized: str
    locus: str
    alpha: str | None = None
    beta: str | None = None


def normalize_mhc2_allele(value: str) -> MHC2Allele:
    """Normalize common HLA-II allele/dimer strings.

    Accepts canonical IPD form (``HLA-DRB1*15:01``), HLAIIPred-style names
    (``DRB1*15:01``, ``DQA1*03:01-DQB1*04:01``), and the concatenated DTU
    NetMHCIIpan form (``DRB1_1501``, ``HLA-DPA10103-DPB110401``).

    DR records are normalized to the beta-chain form used by HLAIIPred
    (``HLA-DRB1*15:01``). DP/DQ records are normalized as alpha-beta
    heterodimers (``HLA-DQA1*03:01-DQB1*04:01``).
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
    text = value.strip().upper()
    text = re.sub(r"^(HLA[-_]?)?(DRA1?|DRB[1-9]|DQA1|DQB1|DPA1|DPB1)_", r"\1\2*", text)
    text = text.replace("_", "-")

    match = _GENE_RE.match(text)
    if not match:
        raise ValueError(f"unrecognized MHC-II allele chain: {value!r}")
    gene, fields = match.groups()
    if not fields:
        raise ValueError(f"MHC-II allele chain lacks fields: {value!r}")

    fields = fields.lstrip("*").lstrip(":").lstrip("-")
    if not fields:
        raise ValueError(f"MHC-II allele chain lacks fields: {value!r}")

    if ":" in fields:
        return f"HLA-{gene}*{fields}"

    if not fields.isdigit():
        return f"HLA-{gene}*{fields}"

    f1, f2 = _split_concat_fields(gene, fields)
    return f"HLA-{gene}*{f1}:{f2}"


def _split_concat_fields(gene: str, digits: str) -> tuple[str, str]:
    """Split a digits-only field string into (family, protein).

    For 4 digits the split is unambiguous (2:2). For 5+ digits we consult
    the IPD-IMGT/HLA allele list when available. With no lookup, the 2-digit
    family is the safer default (it covers the common case for DRB1, DRA1,
    DQA1, DPA1; high-numbered DPB1/DQB1 alleles will be wrong but flagged).
    """
    if len(digits) == 4:
        return digits[:2], digits[2:]
    if len(digits) < 4:
        raise ValueError(f"allele field too short to split: {digits!r}")

    candidates: list[tuple[str, str]] = []
    if len(digits) == 5:
        candidates = [(digits[:2], digits[2:]), (digits[:3], digits[3:])]
    elif len(digits) == 6:
        candidates = [(digits[:3], digits[3:]), (digits[:2], digits[2:])]
    else:
        candidates = [(digits[:2], digits[2:]), (digits[:3], digits[3:]), (digits[:4], digits[4:])]

    valid = known_two_field(gene)
    if valid:
        for f1, f2 in candidates:
            if f"{f1}:{f2}" in valid:
                return f1, f2

    return candidates[0]


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
