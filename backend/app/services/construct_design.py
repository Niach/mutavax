"""Stage 7 — mRNA construct design service.

Stage 7 wraps the picked epitopes from stage 6 with canonical vaccine
flanks (tPA signal peptide, AAY/GPGPG linkers, MITD trafficking tail,
5' UTR/Kozak, 3' UTR, poly(A)) and computes codon-optimization metrics
(LinearDesign-style lambda sweep across CAI vs. MFE). Like stage 6, this
stage is fixture-backed: no external tool binary is invoked. The user's
design choices (lambda value, signal/MITD toggles, confirmation) persist
on ``WorkspaceRecord.construct_config`` as a JSON blob.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Optional

from app.db import session_scope
from app.models.schemas import (
    ConstructDesignOptions,
    ConstructDesignStatus,
    ConstructDesignUpdate,
    ConstructFlanks,
    ConstructManufacturingCheck,
    ConstructMetrics,
    ConstructPreview,
    ConstructPreviewCodon,
    ConstructSegment,
    ConstructStageSummaryResponse,
    EpitopeCandidateResponse,
)
from app.services.epitope_selection import load_epitope_stage_summary
from app.services.workspace_store import (
    get_workspace_record,
    load_workspace_construct_config,
    store_workspace_construct_config,
    utc_now,
)


FIXTURE_PATH = Path(__file__).resolve().parents[1] / "data" / "construct_fixture.json"

_PEPTIDE_CLASS_I_COLOR = "#0f766e"
_PEPTIDE_CLASS_II_COLOR = "#7c3aed"
_SIGNAL_COLOR = "#64748b"
_LINKER_COLOR = "#cbd5e1"
_MITD_COLOR = "#0ea5e9"


@lru_cache(maxsize=1)
def _fixture() -> dict:
    with FIXTURE_PATH.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _flanks_model() -> ConstructFlanks:
    raw = _fixture()["flanks"]
    return ConstructFlanks(
        kozak=raw["kozak"],
        utr5=raw["utr5"],
        utr3=raw["utr3"],
        poly_a=raw["poly_a_len"],
        signal_aa=raw["signal"]["aa"],
        mitd_aa=raw["mitd"]["aa"],
        signal_why=raw["signal"]["why"],
        mitd_why=raw["mitd"]["why"],
    )


def _linkers() -> dict[str, str]:
    return dict(_fixture()["linkers"])


def _manufacturing_checks() -> list[ConstructManufacturingCheck]:
    return [
        ConstructManufacturingCheck(**entry)
        for entry in _fixture()["manufacturing_checks"]
    ]


def reverse_translate(aa: str, table: str = "opt") -> str:
    codons = _fixture()["codon_opt"] if table == "opt" else _fixture()["codon_unopt"]
    return "".join(codons.get(c, "NNN") for c in aa)


def build_orf(
    peptides: list[EpitopeCandidateResponse],
    *,
    signal: bool,
    mitd: bool,
) -> tuple[list[ConstructSegment], str]:
    flanks = _fixture()["flanks"]
    linkers = _linkers()

    sorted_peptides = sorted(peptides, key=lambda p: 0 if p.mhc_class == "I" else 1)

    segments: list[ConstructSegment] = []
    if signal:
        segments.append(
            ConstructSegment(
                kind="signal",
                label=flanks["signal"]["short_name"],
                aa=flanks["signal"]["aa"],
                color=_SIGNAL_COLOR,
            )
        )
        segments.append(
            ConstructSegment(
                kind="linker",
                label="hinge",
                aa=linkers["hinge"],
                color=_LINKER_COLOR,
            )
        )

    for i, peptide in enumerate(sorted_peptides):
        segments.append(
            ConstructSegment(
                kind="peptide",
                label=peptide.gene,
                sub=peptide.mutation,
                aa=peptide.seq,
                mhc_class=peptide.mhc_class,
                peptide_id=peptide.id,
                color=_PEPTIDE_CLASS_II_COLOR
                if peptide.mhc_class == "II"
                else _PEPTIDE_CLASS_I_COLOR,
            )
        )
        if i < len(sorted_peptides) - 1:
            next_peptide = sorted_peptides[i + 1]
            use_class_ii_linker = (
                peptide.mhc_class == "II" or next_peptide.mhc_class == "II"
            )
            link = linkers["classII"] if use_class_ii_linker else linkers["classI"]
            segments.append(
                ConstructSegment(
                    kind="linker",
                    label=link,
                    aa=link,
                    color=_LINKER_COLOR,
                )
            )

    if mitd:
        segments.append(
            ConstructSegment(
                kind="linker",
                label="hinge",
                aa=linkers["hinge"],
                color=_LINKER_COLOR,
            )
        )
        segments.append(
            ConstructSegment(
                kind="mitd",
                label=flanks["mitd"]["short_name"],
                aa=flanks["mitd"]["aa"],
                color=_MITD_COLOR,
            )
        )

    aa_seq = "".join(s.aa for s in segments)
    return segments, aa_seq


def compute_metrics(aa_seq: str, *, lambda_value: float) -> ConstructMetrics:
    nt_len = len(aa_seq) * 3
    cai = round(0.60 + (0.98 - 0.60) * lambda_value, 2)
    mfe = round(-900 + (-620 - -900) * lambda_value)
    gc = round(0.52 + (0.62 - 0.52) * lambda_value, 3)
    flanks = _fixture()["flanks"]
    full_nt = (
        len(flanks["utr5"])
        + nt_len
        + 3  # stop codon
        + len(flanks["utr3"])
        + flanks["poly_a_len"]
    )
    return ConstructMetrics(
        aa_len=len(aa_seq),
        nt_len=nt_len,
        cai=cai,
        mfe=mfe,
        gc=gc,
        full_mrna_nt=full_nt,
        mfe_per_nt=round(mfe / nt_len, 3) if nt_len else 0.0,
    )


def _build_preview() -> ConstructPreview:
    raw = _fixture()["preview_peptide"]
    aa = raw["aa"]
    unopt_nt = raw["unopt_nt"]
    opt_nt = raw["opt_nt"]
    codons: list[ConstructPreviewCodon] = []
    for i, residue in enumerate(aa):
        u = unopt_nt[i * 3 : i * 3 + 3]
        o = opt_nt[i * 3 : i * 3 + 3]
        codons.append(
            ConstructPreviewCodon(aa=residue, unopt=u, opt=o, swapped=u != o)
        )
    return ConstructPreview(gene=raw["gene"], mut=raw["mut"], codons=codons)


def _default_options() -> ConstructDesignOptions:
    return ConstructDesignOptions(
        lambda_value=0.65, signal=True, mitd=True, confirmed=False
    )


def _load_options(config: dict) -> ConstructDesignOptions:
    raw = config.get("options") if isinstance(config, dict) else None
    if not isinstance(raw, dict):
        return _default_options()
    lambda_value = raw.get("lambda", raw.get("lambda_value"))
    try:
        lambda_value = float(lambda_value) if lambda_value is not None else 0.65
    except (TypeError, ValueError):
        lambda_value = 0.65
    lambda_value = max(0.0, min(1.0, lambda_value))
    return ConstructDesignOptions(
        lambda_value=lambda_value,
        signal=bool(raw.get("signal", True)),
        mitd=bool(raw.get("mitd", True)),
        confirmed=bool(raw.get("confirmed", False)),
    )


def _blocked_summary(workspace_id: str, reason: str) -> ConstructStageSummaryResponse:
    options = _default_options()
    flanks = _flanks_model()
    return ConstructStageSummaryResponse(
        workspace_id=workspace_id,
        status=ConstructDesignStatus.BLOCKED,
        blocking_reason=reason,
        options=options,
        flanks=flanks,
        linkers=_linkers(),
        segments=[],
        aa_seq="",
        metrics=ConstructMetrics(
            aa_len=0,
            nt_len=0,
            cai=0.60,
            mfe=0,
            gc=0.52,
            full_mrna_nt=0,
            mfe_per_nt=0.0,
        ),
        preview=_build_preview(),
        manufacturing_checks=_manufacturing_checks(),
        peptide_count=0,
        ready_for_output=False,
    )


def _picked_peptides(
    selection: list[str], candidates: list[EpitopeCandidateResponse]
) -> list[EpitopeCandidateResponse]:
    by_id = {c.id: c for c in candidates}
    return [by_id[p] for p in selection if p in by_id]


def load_construct_stage_summary(workspace_id: str) -> ConstructStageSummaryResponse:
    epitope_summary = load_epitope_stage_summary(workspace_id)
    if not epitope_summary.ready_for_construct_design:
        reason = (
            epitope_summary.blocking_reason
            or "Lock the epitope shortlist before designing the construct."
        )
        return _blocked_summary(workspace_id, reason)

    picked = _picked_peptides(epitope_summary.selection, epitope_summary.candidates)
    if not picked:
        return _blocked_summary(
            workspace_id,
            "Pick at least one peptide in stage 6 before building the construct.",
        )

    with session_scope() as session:
        workspace = get_workspace_record(session, workspace_id)
        config = load_workspace_construct_config(workspace)

    options = _load_options(config)

    segments, aa_seq = build_orf(picked, signal=options.signal, mitd=options.mitd)
    metrics = compute_metrics(aa_seq, lambda_value=options.lambda_value)

    status = (
        ConstructDesignStatus.CONFIRMED
        if options.confirmed
        else ConstructDesignStatus.SCAFFOLDED
    )

    return ConstructStageSummaryResponse(
        workspace_id=workspace_id,
        status=status,
        blocking_reason=None,
        options=options,
        flanks=_flanks_model(),
        linkers=_linkers(),
        segments=segments,
        aa_seq=aa_seq,
        metrics=metrics,
        preview=_build_preview(),
        manufacturing_checks=_manufacturing_checks(),
        peptide_count=len(picked),
        ready_for_output=options.confirmed,
    )


def update_construct_options(
    workspace_id: str, payload: ConstructDesignUpdate
) -> ConstructStageSummaryResponse:
    epitope_summary = load_epitope_stage_summary(workspace_id)
    if not epitope_summary.ready_for_construct_design:
        reason = (
            epitope_summary.blocking_reason
            or "Lock the epitope shortlist before designing the construct."
        )
        return _blocked_summary(workspace_id, reason)

    with session_scope() as session:
        workspace = get_workspace_record(session, workspace_id)
        existing = load_workspace_construct_config(workspace)
        if not isinstance(existing, dict):
            existing = {}
        now_iso = utc_now().strftime("%Y-%m-%d %H:%M UTC")
        existing["options"] = {
            "lambda": max(0.0, min(1.0, float(payload.lambda_value))),
            "signal": bool(payload.signal),
            "mitd": bool(payload.mitd),
            "confirmed": bool(payload.confirmed),
        }
        if payload.confirmed:
            existing.setdefault("confirmed_at", now_iso)
        else:
            existing.pop("confirmed_at", None)
        store_workspace_construct_config(workspace, existing)
        workspace.updated_at = utc_now()
        session.add(workspace)

    return load_construct_stage_summary(workspace_id)


def get_confirmed_construct(workspace_id: str) -> Optional[ConstructStageSummaryResponse]:
    summary = load_construct_stage_summary(workspace_id)
    if summary.status != ConstructDesignStatus.CONFIRMED:
        return None
    return summary
