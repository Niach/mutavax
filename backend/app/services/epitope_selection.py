"""Epitope selection stage service (pVACview curation).

Stage 6 is a curation surface on top of the stage-5 neoantigen output: the
user picks ~7 of the top peptides for the mRNA cassette. No subprocess
runs here — the "stage" is a persisted shortlist plus the deck of
candidates to choose from.

When stage 5 has completed for a workspace, the candidate deck is built
from pVACseq's ``top`` candidates (via ``load_neoantigen_stage_summary``).
For demo workspaces seeded without a real stage-5 run, or when the latest
run has no parseable metrics yet, the service falls back to the fixture
deck in ``backend/app/data/epitope_fixture.json``. The stage is gated on
``readyForEpitopeSelection`` from the neoantigen summary.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Iterable, Optional

from app.db import session_scope
from app.models.schemas import (
    EpitopeAlleleResponse,
    EpitopeCandidateResponse,
    EpitopeSafetyFlagResponse,
    EpitopeSelectionUpdate,
    EpitopeStageStatus,
    EpitopeStageSummaryResponse,
    NeoantigenStageSummaryResponse,
    TopCandidate,
)
from app.services.neoantigen import load_neoantigen_stage_summary
from app.services.self_identity import run_self_identity_check
from app.services.workspace_store import (
    default_reference_preset_for_species,
    get_workspace_record,
    load_workspace_epitope_config,
    store_workspace_epitope_config,
    utc_now,
)


FIXTURE_PATH = Path(__file__).resolve().parents[1] / "data" / "epitope_fixture.json"

MAX_SELECTION = 8

# Palette for allele chips, cycled in deck order.
_ALLELE_COLORS = (
    "#0f766e", "#0ea5e9", "#6366f1", "#8b5cf6",
    "#d97706", "#dc2626", "#059669", "#7c3aed",
)


@lru_cache(maxsize=1)
def _fixture() -> dict:
    with FIXTURE_PATH.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _build_alleles() -> list[EpitopeAlleleResponse]:
    return [
        EpitopeAlleleResponse.model_validate(entry)
        for entry in _fixture()["alleles"]
    ]


def _build_candidates() -> list[EpitopeCandidateResponse]:
    return [
        EpitopeCandidateResponse.model_validate(entry)
        for entry in _fixture()["candidates"]
    ]


def _build_safety() -> dict[str, EpitopeSafetyFlagResponse]:
    return {
        peptide_id: EpitopeSafetyFlagResponse.model_validate(entry)
        for peptide_id, entry in _fixture()["safety"].items()
    }


def _default_picks() -> list[str]:
    return list(_fixture()["default_picks"])


def _tier_for(ic50: float) -> str:
    return "strong" if ic50 < 100 else "moderate"


def _deck_from_top(top: list[TopCandidate]) -> tuple[
    list[EpitopeCandidateResponse], list[EpitopeAlleleResponse], list[str]
]:
    """Map pVACseq top candidates into stage-6 deck + allele chips + default
    picks. Default picks prioritize distinct genes and at least one class-II
    for T-cell help, matching the six plain-English goals in the UI."""
    candidates: list[EpitopeCandidateResponse] = []
    allele_seen: dict[str, str] = {}
    for idx, c in enumerate(top, start=1):
        pid = f"rd{idx:03d}"
        if c.allele not in allele_seen:
            allele_seen[c.allele] = _ALLELE_COLORS[
                len(allele_seen) % len(_ALLELE_COLORS)
            ]
        candidates.append(
            EpitopeCandidateResponse(
                id=pid,
                seq=c.seq,
                gene=c.gene,
                mutation=c.mut,
                length=c.length,
                **{"class": c.mhc_class},
                allele_id=c.allele,
                ic50_nm=float(c.ic50),
                agretopicity=float(c.agretopicity) if c.agretopicity is not None else 0.0,
                vaf=float(c.vaf) if c.vaf is not None else 0.0,
                tpm=float(c.tpm) if c.tpm is not None else 0.0,
                cancer_gene=bool(c.cancer_gene),
                driver_context=None,
                tier=_tier_for(c.ic50),
                flags=[],
            )
        )

    alleles = [
        EpitopeAlleleResponse.model_validate(
            {
                "id": allele_id,
                "class": _allele_class(allele_id),
                "color": color,
            }
        )
        for allele_id, color in allele_seen.items()
    ]

    default_picks = _pick_defaults(candidates)
    return candidates, alleles, default_picks


def _allele_class(allele_id: str) -> str:
    """Quick class-I/II split: HLA-DR/DQ/DP and DLA-DRB/DQB/DLAII → II; else I."""
    upper = allele_id.upper()
    if any(marker in upper for marker in ("DRB", "DQB", "DPB", "-DR", "-DQ", "-DP")):
        return "II"
    return "I"


def _pick_defaults(candidates: list[EpitopeCandidateResponse]) -> list[str]:
    """Pick up to 7 defaults: strongest class-I candidates across distinct genes,
    plus 1–2 class-II picks for T-cell help. Skip passenger (non-cancer) genes
    when possible, but fall back to them if the cancer-gene pool is too shallow
    to hit the six-peptide goals floor (common on real canine data, and on
    human pools where the pVACseq-filtered candidate set happens to cluster on
    a handful of drivers only)."""
    sorted_c = sorted(candidates, key=lambda p: (p.ic50_nm, -p.vaf))

    picks: list[str] = []
    genes: set[str] = set()

    # Phase 1 — strongest cancer-gene class-I, one per gene.
    for p in sorted_c:
        if p.mhc_class != "I" or not p.cancer_gene:
            continue
        if p.gene in genes:
            continue
        picks.append(p.id)
        genes.add(p.gene)
        if len(picks) >= 5:
            break

    # Phase 2 — class-II for T-cell help, distinct gene, cancer-gene preferred.
    for p in sorted_c:
        if p.mhc_class != "II" or not p.cancer_gene:
            continue
        if p.gene in genes:
            continue
        picks.append(p.id)
        genes.add(p.gene)
        if sum(1 for pid in picks if _class_of(pid, candidates) == "II") >= 2:
            break
        if len(picks) >= 7:
            break

    # Phase 2b — class-II floor. If the pool offers class-II candidates but
    # none cleared phase 2 (usually because every class-II binder overlaps a
    # gene already picked by phase 1), relax the distinct-gene rule and take
    # the best class-II cancer-gene peptide. Same-gene class-I + class-II
    # pairs give complementary CD4+ help for the CD8+ response on the same
    # driver — a feature, not a compromise. Passenger class-II is accepted
    # only if no cancer-gene class-II exists, mirroring phase-3 rescue.
    has_class_ii_pick = any(_class_of(pid, candidates) == "II" for pid in picks)
    pool_class_ii = [p for p in sorted_c if p.mhc_class == "II"]
    if not has_class_ii_pick and pool_class_ii and len(picks) < MAX_SELECTION:
        preferred = [p for p in pool_class_ii if p.cancer_gene and p.id not in picks]
        pool = preferred or [p for p in pool_class_ii if p.id not in picks]
        if pool:
            picks.append(pool[0].id)

    # Phase 3 — if the cancer-gene pool didn't reach the 6-pick goals floor,
    # top up with the next-best distinct-gene candidates, passengers included.
    # Keeps gene diversity rising and unblocks epitope completion when the
    # upstream pVACseq filter surfaces only a few drivers (as on COLO829).
    if len(picks) < 6:
        for p in sorted_c:
            if p.id in picks or p.gene in genes:
                continue
            picks.append(p.id)
            genes.add(p.gene)
            if len(picks) >= 7:
                break

    return picks[:MAX_SELECTION]


def _class_of(pid: str, candidates: list[EpitopeCandidateResponse]) -> Optional[str]:
    for c in candidates:
        if c.id == pid:
            return c.mhc_class
    return None


def _goals_pass(selection: list[str], candidates: list[EpitopeCandidateResponse],
                safety: dict[str, EpitopeSafetyFlagResponse]) -> bool:
    # Goals are data-adaptive: requirements that are unreachable given what
    # pVACseq surfaced for this workspace (e.g. canine class-II binders,
    # or ≥3 usable DLA alleles) fall back to "whatever the pool offers"
    # rather than hard-blocking the stage.
    if not selection:
        return False
    by_id = {c.id: c for c in candidates}
    picks = [by_id[p] for p in selection if p in by_id]
    if len(picks) < 6 or len(picks) > 8:
        return False
    if len({p.gene for p in picks}) < 5:
        return False

    pool_alleles = {c.allele_id for c in candidates}
    required_alleles = min(3, max(1, len(pool_alleles)))
    if len({p.allele_id for p in picks}) < required_alleles:
        return False

    pool_has_class_ii = any(c.mhc_class == "II" for c in candidates)
    if pool_has_class_ii and sum(1 for p in picks if p.mhc_class == "II") < 1:
        return False

    # Require at least one driver peptide when any exist in the pool. The full
    # "all picks must be cancer genes" rule is unreachable on real canine data
    # where pVACseq usually surfaces at most 1-2 driver binders — requiring all
    # six+ slots to be drivers would block completion even when the shortlist
    # *does* include every driver available.
    cancer_gene_pool = sum(1 for c in candidates if c.cancer_gene)
    if cancer_gene_pool > 0 and not any(p.cancer_gene for p in picks):
        return False

    if any(safety.get(p.id) and safety[p.id].risk == "critical" for p in picks):
        return False
    return True


def _filtered_selection(
    raw: Iterable[str], candidates: list[EpitopeCandidateResponse]
) -> list[str]:
    valid = {c.id for c in candidates}
    seen: set[str] = set()
    out: list[str] = []
    for peptide_id in raw:
        if peptide_id in valid and peptide_id not in seen:
            seen.add(peptide_id)
            out.append(peptide_id)
            if len(out) >= MAX_SELECTION:
                break
    return out


def _blocked_summary(workspace_id: str, reason: str) -> EpitopeStageSummaryResponse:
    return EpitopeStageSummaryResponse(
        workspace_id=workspace_id,
        status=EpitopeStageStatus.BLOCKED,
        blocking_reason=reason,
        candidates=[],
        safety={},
        alleles=[],
        default_picks=[],
        selection=[],
        ready_for_construct_design=False,
    )


def _real_deck_from_summary(
    summary: NeoantigenStageSummaryResponse,
) -> Optional[tuple[
    list[EpitopeCandidateResponse], list[EpitopeAlleleResponse], list[str]
]]:
    """Return (candidates, alleles, default_picks) built from stage-5 output,
    or ``None`` when no parseable top-candidate data is available (e.g. a demo
    workspace seeded without a real stage-5 run)."""
    if summary.latest_run is None or summary.latest_run.metrics is None:
        return None
    top = summary.latest_run.metrics.top
    if not top:
        return None
    return _deck_from_top(list(top))


def load_epitope_stage_summary(workspace_id: str) -> EpitopeStageSummaryResponse:
    neoantigen_summary = load_neoantigen_stage_summary(workspace_id)
    if not neoantigen_summary.ready_for_epitope_selection:
        reason = (
            neoantigen_summary.blocking_reason
            or "Finish neoantigen prediction before curating the cassette."
        )
        return _blocked_summary(workspace_id, reason)

    with session_scope() as session:
        workspace = get_workspace_record(session, workspace_id)
        config = load_workspace_epitope_config(workspace)
        workspace_species = workspace.species

    real = _real_deck_from_summary(neoantigen_summary)
    if real is not None:
        candidates, alleles, default_picks = real
        # BLAST the real candidates against the species' Swiss-Prot proteome.
        # No-op (sparse empty dict) when DIAMOND or the proteome are missing;
        # the caller logs why. Fixture workspaces keep their fixture flags
        # since the fixture peptides aren't real-world sequences — BLASTing
        # them would produce misleading zero-hit results.
        safety = run_self_identity_check(
            [(c.id, c.seq) for c in candidates],
            default_reference_preset_for_species(workspace_species),
        )
    else:
        candidates = _build_candidates()
        safety = _build_safety()
        alleles = _build_alleles()
        default_picks = _default_picks()

    stored_selection = config.get("selection") if isinstance(config, dict) else None
    selection = _filtered_selection(stored_selection or [], candidates)
    if not selection:
        selection = _filtered_selection(default_picks, candidates)

    status = (
        EpitopeStageStatus.COMPLETED
        if _goals_pass(selection, candidates, safety)
        else EpitopeStageStatus.SCAFFOLDED
    )
    return EpitopeStageSummaryResponse(
        workspace_id=workspace_id,
        status=status,
        blocking_reason=None,
        candidates=candidates,
        safety=safety,
        alleles=alleles,
        default_picks=default_picks,
        selection=selection,
        ready_for_construct_design=status == EpitopeStageStatus.COMPLETED,
    )


def update_epitope_selection(
    workspace_id: str, payload: EpitopeSelectionUpdate
) -> EpitopeStageSummaryResponse:
    # Use whatever deck is currently active (real data from stage 5 output if
    # available, else fixture) so selections are validated against the deck
    # the user actually saw.
    summary = load_neoantigen_stage_summary(workspace_id)
    real = (
        _real_deck_from_summary(summary)
        if summary.ready_for_epitope_selection
        else None
    )
    candidates = real[0] if real is not None else _build_candidates()
    selection = _filtered_selection(payload.peptide_ids, candidates)

    with session_scope() as session:
        workspace = get_workspace_record(session, workspace_id)
        existing = load_workspace_epitope_config(workspace)
        if not isinstance(existing, dict):
            existing = {}
        existing["selection"] = selection
        store_workspace_epitope_config(workspace, existing)
        workspace.updated_at = utc_now()
        session.add(workspace)

    return load_epitope_stage_summary(workspace_id)
