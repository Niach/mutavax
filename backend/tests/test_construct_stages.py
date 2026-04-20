"""Smoke tests for stages 7 (construct design) and 8 (construct output).

These tests bypass stages 1–6 by stubbing the epitope stage summary loader
directly, since the construct services only need `ready_for_construct_design`
and the selected peptide candidates.
"""
from __future__ import annotations

import uuid

import pytest

from app.db import init_db, session_scope
from app.models.records import (
    IngestionBatchRecord,
    PipelineArtifactRecord,
    PipelineRunRecord,
    WorkspaceFileRecord,
    WorkspaceRecord,
)
from app.models.schemas import (
    ConstructDesignStatus,
    ConstructDesignUpdate,
    ConstructOutputAction,
    ConstructOutputStatus,
    EpitopeStageStatus,
    EpitopeStageSummaryResponse,
    WorkspaceCreateRequest,
    WorkspaceSpecies,
)
from app.services import construct_design, construct_output, epitope_selection
from app.services.construct_design import (
    load_construct_stage_summary,
    update_construct_options,
)
from app.services.construct_output import (
    load_construct_output_summary,
    update_construct_output,
)
from app.services.workspace_store import create_workspace


@pytest.fixture(autouse=True)
def _clean_database():
    init_db()
    with session_scope() as session:
        for model in (
            PipelineArtifactRecord,
            PipelineRunRecord,
            WorkspaceFileRecord,
            IngestionBatchRecord,
            WorkspaceRecord,
        ):
            session.query(model).delete()
    yield
    with session_scope() as session:
        for model in (
            PipelineArtifactRecord,
            PipelineRunRecord,
            WorkspaceFileRecord,
            IngestionBatchRecord,
            WorkspaceRecord,
        ):
            session.query(model).delete()


def _stub_epitope(monkeypatch, *, ready: bool) -> None:
    def fake(workspace_id: str) -> EpitopeStageSummaryResponse:
        if not ready:
            return EpitopeStageSummaryResponse(
                workspace_id=workspace_id,
                status=EpitopeStageStatus.BLOCKED,
                blocking_reason="stubbed blocked",
                candidates=[],
                safety={},
                alleles=[],
                default_picks=[],
                selection=[],
                ready_for_construct_design=False,
            )
        candidates = epitope_selection._build_candidates()
        default_picks = epitope_selection._default_picks()
        return EpitopeStageSummaryResponse(
            workspace_id=workspace_id,
            status=EpitopeStageStatus.COMPLETED,
            blocking_reason=None,
            candidates=candidates,
            safety=epitope_selection._build_safety(),
            alleles=epitope_selection._build_alleles(),
            default_picks=default_picks,
            selection=default_picks,
            ready_for_construct_design=True,
        )

    monkeypatch.setattr(construct_design, "load_epitope_stage_summary", fake)


def _create_workspace(name: str = "Stage7 Dog") -> str:
    return create_workspace(
        WorkspaceCreateRequest(display_name=name, species=WorkspaceSpecies.DOG)
    ).id


def test_stage7_is_blocked_before_epitope_ready(monkeypatch):
    _stub_epitope(monkeypatch, ready=False)
    workspace_id = _create_workspace()
    summary = load_construct_stage_summary(workspace_id)
    assert summary.status == ConstructDesignStatus.BLOCKED
    assert summary.blocking_reason is not None


def test_stage7_scaffolded_when_epitope_ready(monkeypatch):
    _stub_epitope(monkeypatch, ready=True)
    workspace_id = _create_workspace()
    summary = load_construct_stage_summary(workspace_id)
    assert summary.status == ConstructDesignStatus.SCAFFOLDED
    assert summary.peptide_count == 7
    # ORF should include at least signal + 7 peptides + MITD + linkers
    assert len(summary.segments) >= 10
    assert summary.metrics.full_mrna_nt > 0
    assert summary.ready_for_output is False


def test_stage7_options_persist_and_confirm(monkeypatch):
    _stub_epitope(monkeypatch, ready=True)
    workspace_id = _create_workspace()

    summary = update_construct_options(
        workspace_id,
        ConstructDesignUpdate.model_validate(
            {"lambda": 0.85, "signal": False, "mitd": True, "confirmed": False}
        ),
    )
    assert summary.options.lambda_value == pytest.approx(0.85)
    assert summary.options.signal is False

    # Reload — options survive
    summary2 = load_construct_stage_summary(workspace_id)
    assert summary2.options.lambda_value == pytest.approx(0.85)
    assert summary2.options.signal is False
    # Signal off → no signal segment in the ORF
    assert not any(s.kind == "signal" for s in summary2.segments)

    # Confirm flips status + unlocks stage 8
    confirmed = update_construct_options(
        workspace_id,
        ConstructDesignUpdate.model_validate(
            {"lambda": 0.85, "signal": False, "mitd": True, "confirmed": True}
        ),
    )
    assert confirmed.status == ConstructDesignStatus.CONFIRMED
    assert confirmed.ready_for_output is True


def test_stage8_blocked_until_stage7_confirmed(monkeypatch):
    _stub_epitope(monkeypatch, ready=True)
    workspace_id = _create_workspace()

    summary = load_construct_output_summary(workspace_id)
    assert summary.status == ConstructOutputStatus.BLOCKED


def test_stage8_ready_and_release_flow(monkeypatch):
    _stub_epitope(monkeypatch, ready=True)
    workspace_id = _create_workspace("Release Dog")

    update_construct_options(
        workspace_id,
        ConstructDesignUpdate.model_validate(
            {"lambda": 0.65, "signal": True, "mitd": True, "confirmed": True}
        ),
    )

    ready = load_construct_output_summary(workspace_id)
    assert ready.status == ConstructOutputStatus.READY
    assert ready.total_nt > 0
    assert len(ready.full_nt) == ready.total_nt
    assert ready.full_nt.startswith("GGG")  # 5' UTR
    assert ready.full_nt.endswith("A" * 120)  # poly(A) tail
    assert ready.checksum.startswith("sha256:")
    assert len(ready.cmo_options) == 3

    selected = update_construct_output(
        workspace_id, ConstructOutputAction(action="select_cmo", cmo_id="trilink")
    )
    assert selected.selected_cmo == "trilink"
    assert selected.status == ConstructOutputStatus.READY
    assert selected.order is None

    released = update_construct_output(
        workspace_id, ConstructOutputAction(action="release", cmo_id="trilink")
    )
    assert released.status == ConstructOutputStatus.RELEASED
    assert released.order is not None
    assert released.order.cmo_id == "trilink"
    assert released.order.po_number.startswith("CS-2026-")
    assert released.released_at


def test_stage8_release_requires_cmo(monkeypatch):
    _stub_epitope(monkeypatch, ready=True)
    workspace_id = _create_workspace("No-CMO Dog")

    update_construct_options(
        workspace_id,
        ConstructDesignUpdate.model_validate(
            {"lambda": 0.5, "signal": True, "mitd": True, "confirmed": True}
        ),
    )

    with pytest.raises(ValueError):
        update_construct_output(workspace_id, ConstructOutputAction(action="release"))


def test_stage8_unknown_cmo_rejected(monkeypatch):
    _stub_epitope(monkeypatch, ready=True)
    workspace_id = _create_workspace("Bad-CMO Dog")

    update_construct_options(
        workspace_id,
        ConstructDesignUpdate.model_validate(
            {"lambda": 0.5, "signal": True, "mitd": True, "confirmed": True}
        ),
    )

    with pytest.raises(ValueError):
        update_construct_output(
            workspace_id, ConstructOutputAction(action="select_cmo", cmo_id="nope")
        )
