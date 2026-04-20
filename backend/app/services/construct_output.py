"""Stage 8 — Construct output service.

Stage 8 assembles the confirmed stage-7 construct into the final mRNA
deliverable: 5' UTR + signal + linker/peptide/MITD codon runs + stop +
3' UTR + poly(A). It also curates the three audience artifacts (CMO
order, vet dosing, audit trail) and records the "release" action that
locks the sequence.
"""
from __future__ import annotations

import hashlib
import json
import random
from functools import lru_cache
from pathlib import Path
from typing import Optional

from app.db import session_scope
from app.models.schemas import (
    AuditEntry,
    CmoOption,
    ConstructDesignStatus,
    ConstructOutputAction,
    ConstructOutputOrder,
    ConstructOutputRun,
    ConstructOutputStageSummaryResponse,
    ConstructOutputStatus,
    DosingProtocol,
    DosingScheduleItem,
)
from app.services.construct_design import (
    load_construct_stage_summary,
    reverse_translate,
)
from app.services.workspace_store import (
    get_workspace_record,
    load_workspace_construct_output_config,
    store_workspace_construct_output_config,
    utc_now,
)


FIXTURE_PATH = (
    Path(__file__).resolve().parents[1] / "data" / "construct_output_fixture.json"
)


@lru_cache(maxsize=1)
def _fixture() -> dict:
    with FIXTURE_PATH.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _cmo_options() -> list[CmoOption]:
    return [CmoOption(**entry) for entry in _fixture()["cmo_options"]]


def _dosing_protocol() -> DosingProtocol:
    raw = _fixture()["dosing_protocol"]
    return DosingProtocol(
        formulation=raw["formulation"],
        route=raw["route"],
        dose=raw["dose"],
        schedule=[DosingScheduleItem(**item) for item in raw["schedule"]],
        watch_for=list(raw["watch_for"]),
    )


def _segment_run_kind(segment_kind: str, mhc_class: Optional[str]) -> str:
    if segment_kind == "signal":
        return "signal"
    if segment_kind == "mitd":
        return "mitd"
    if segment_kind == "peptide":
        return "classII" if mhc_class == "II" else "classI"
    return "linker"


def _build_runs(construct_summary) -> list[ConstructOutputRun]:
    flanks = construct_summary.flanks
    runs: list[ConstructOutputRun] = [
        ConstructOutputRun(kind="utr5", label="5' UTR", nt=flanks.utr5),
    ]
    for segment in construct_summary.segments:
        nt = reverse_translate(segment.aa, table="opt")
        if segment.kind == "peptide":
            label = (
                f"{segment.label} · {segment.sub}"
                if segment.sub
                else segment.label
            )
        elif segment.kind == "signal":
            label = "SP"
        elif segment.kind == "mitd":
            label = "MITD"
        else:
            label = "linker"
        runs.append(
            ConstructOutputRun(
                kind=_segment_run_kind(segment.kind, segment.mhc_class),
                label=label,
                nt=nt,
            )
        )
    runs.append(ConstructOutputRun(kind="stop", label="stop", nt="TAA"))
    runs.append(ConstructOutputRun(kind="utr3", label="3' UTR", nt=flanks.utr3))
    runs.append(
        ConstructOutputRun(
            kind="polyA",
            label=f"poly(A){flanks.poly_a}",
            nt="A" * flanks.poly_a,
        )
    )
    return runs


def _construct_id(workspace_id: str, display_name: str) -> str:
    slug = "".join(c if c.isalnum() else "-" for c in display_name.strip())
    slug = "-".join(part for part in slug.split("-") if part)
    if not slug:
        slug = workspace_id[:8]
    return f"{slug}-MCT-001"


def _species_label(species: str) -> str:
    labels = _fixture()["species_labels"]
    return labels.get(species, species)


def _compute_checksum(full_nt: str) -> str:
    digest = hashlib.sha256(full_nt.encode("ascii")).hexdigest()
    return f"sha256:{digest[:16]}"


def _build_audit_trail(
    construct_summary, output_config: dict
) -> list[AuditEntry]:
    template = _fixture()["audit_trail_template"]
    operator = "operator@cancerstudio.dev"
    trail: list[AuditEntry] = []
    for entry in template:
        when = output_config.get("event_timestamps", {}).get(
            f"{entry['stage']}-{entry['what']}",
            utc_now().strftime("%m-%d %H:%M"),
        )
        trail.append(
            AuditEntry(
                stage=entry["stage"],
                when=when,
                who=operator if entry["kind"] == "human" else "pipeline",
                what=entry["what"],
                kind=entry["kind"],
            )
        )
    if output_config.get("released"):
        trail.append(
            AuditEntry(
                stage="08",
                when=output_config.get("released_at", ""),
                who=operator,
                what=f"Released construct to {output_config.get('selected_cmo', 'manufacturer')}",
                kind="human",
            )
        )
    return trail


def _po_number(workspace_id: str) -> str:
    seed = int(hashlib.sha256(workspace_id.encode()).hexdigest()[:6], 16)
    rnd = random.Random(seed)
    return f"CS-2026-{rnd.randint(1000, 9999):04d}-001"


def _blocked_summary(
    workspace_id: str, reason: str
) -> ConstructOutputStageSummaryResponse:
    return ConstructOutputStageSummaryResponse(
        workspace_id=workspace_id,
        status=ConstructOutputStatus.BLOCKED,
        blocking_reason=reason,
        construct_id="",
        species="",
        version=_fixture()["version"],
        checksum="",
        released_at=None,
        released_by=None,
        runs=[],
        full_nt="",
        total_nt=0,
        cmo_options=_cmo_options(),
        selected_cmo=None,
        order=None,
        dosing=_dosing_protocol(),
        audit_trail=[],
    )


def load_construct_output_summary(
    workspace_id: str,
) -> ConstructOutputStageSummaryResponse:
    construct_summary = load_construct_stage_summary(workspace_id)
    if construct_summary.status != ConstructDesignStatus.CONFIRMED:
        reason = (
            construct_summary.blocking_reason
            or "Confirm the construct design before generating the output."
        )
        return _blocked_summary(workspace_id, reason)

    runs = _build_runs(construct_summary)
    full_nt = "".join(r.nt for r in runs)
    checksum = _compute_checksum(full_nt)

    with session_scope() as session:
        workspace = get_workspace_record(session, workspace_id)
        display_name = workspace.display_name
        species = workspace.species
        output_config = load_workspace_construct_output_config(workspace)

    released = bool(output_config.get("released"))
    selected_cmo = output_config.get("selected_cmo")
    status = (
        ConstructOutputStatus.RELEASED if released else ConstructOutputStatus.READY
    )

    order: Optional[ConstructOutputOrder] = None
    if released and selected_cmo:
        order = ConstructOutputOrder(
            cmo_id=selected_cmo,
            po_number=output_config.get("po_number") or _po_number(workspace_id),
            ordered_at=output_config.get("released_at", ""),
        )

    return ConstructOutputStageSummaryResponse(
        workspace_id=workspace_id,
        status=status,
        blocking_reason=None,
        construct_id=_construct_id(workspace_id, display_name),
        species=_species_label(species),
        version=_fixture()["version"],
        checksum=checksum,
        released_at=output_config.get("released_at") if released else None,
        released_by=output_config.get("released_by") if released else None,
        runs=runs,
        full_nt=full_nt,
        total_nt=len(full_nt),
        cmo_options=_cmo_options(),
        selected_cmo=selected_cmo,
        order=order,
        dosing=_dosing_protocol(),
        audit_trail=_build_audit_trail(construct_summary, output_config),
    )


def update_construct_output(
    workspace_id: str, payload: ConstructOutputAction
) -> ConstructOutputStageSummaryResponse:
    summary = load_construct_output_summary(workspace_id)
    if summary.status == ConstructOutputStatus.BLOCKED:
        return summary

    valid_cmo_ids = {o.id for o in _cmo_options()}

    with session_scope() as session:
        workspace = get_workspace_record(session, workspace_id)
        existing = load_workspace_construct_output_config(workspace)
        if not isinstance(existing, dict):
            existing = {}

        if payload.action == "select_cmo":
            if payload.cmo_id not in valid_cmo_ids:
                raise ValueError(f"Unknown CMO: {payload.cmo_id}")
            existing["selected_cmo"] = payload.cmo_id

        elif payload.action == "release":
            cmo_id = payload.cmo_id or existing.get("selected_cmo")
            if cmo_id not in valid_cmo_ids:
                raise ValueError(
                    "Select a manufacturer before releasing the construct."
                )
            existing["selected_cmo"] = cmo_id
            existing["released"] = True
            existing["released_at"] = utc_now().strftime("%Y-%m-%d %H:%M UTC")
            existing["released_by"] = "operator@cancerstudio.dev"
            existing["po_number"] = _po_number(workspace_id)

        else:  # pragma: no cover - pydantic restricts the literal
            raise ValueError(f"Unknown action: {payload.action}")

        store_workspace_construct_output_config(workspace, existing)
        workspace.updated_at = utc_now()
        session.add(workspace)

    return load_construct_output_summary(workspace_id)
