"""Seed a demo workspace with completed pipeline-run stubs for screenshots.

Inserts a workspace plus the minimum DB state (annotation + neoantigen
pipeline runs marked completed) so stages 6–8 render the live UI without
re-running the real 12 h bioinformatics pipeline. Run inside the backend
container:

    docker exec cancerstudio-backend python scripts/seed_demo_workspace.py

The resulting workspace ID is written to stdout so `take-screenshots.mjs`
can consume it.
"""
from __future__ import annotations

import sys
import uuid
from datetime import datetime, timezone

from app.db import init_db, session_scope
from app.models.records import PipelineRunRecord, WorkspaceRecord
from app.models.schemas import (
    PipelineStageId,
    WorkspaceCreateRequest,
    WorkspaceSpecies,
)
from app.services.construct_design import update_construct_options
from app.services.construct_output import update_construct_output
from app.services.epitope_selection import update_epitope_selection
from app.services.workspace_store import create_workspace
from app.models.schemas import (
    ConstructDesignUpdate,
    ConstructOutputAction,
    EpitopeSelectionUpdate,
)


DEMO_NAME = "Rosie — mast cell tumor (demo)"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def insert_completed_run(session, workspace_id: str, stage_id: str) -> None:
    now = utcnow()
    session.add(
        PipelineRunRecord(
            id=str(uuid.uuid4()),
            workspace_id=workspace_id,
            stage_id=stage_id,
            status="completed",
            progress=100,
            qc_verdict="pass",
            runtime_phase=None,
            command_log=None,
            result_payload=None,
            blocking_reason=None,
            error=None,
            created_at=now,
            updated_at=now,
            started_at=now,
            completed_at=now,
        )
    )


def find_or_create_workspace() -> str:
    init_db()
    with session_scope() as session:
        existing = (
            session.query(WorkspaceRecord).filter_by(display_name=DEMO_NAME).first()
        )
        if existing:
            return existing.id

    workspace = create_workspace(
        WorkspaceCreateRequest(display_name=DEMO_NAME, species=WorkspaceSpecies.DOG)
    )
    return workspace.id


def main() -> None:
    workspace_id = find_or_create_workspace()

    with session_scope() as session:
        already_seeded = (
            session.query(PipelineRunRecord)
            .filter_by(workspace_id=workspace_id, stage_id=PipelineStageId.NEOANTIGEN_PREDICTION.value)
            .first()
        )
        if not already_seeded:
            insert_completed_run(
                session, workspace_id, PipelineStageId.ANNOTATION.value
            )
            insert_completed_run(
                session, workspace_id, PipelineStageId.NEOANTIGEN_PREDICTION.value
            )
            workspace = session.get(WorkspaceRecord, workspace_id)
            workspace.active_stage = PipelineStageId.CONSTRUCT_DESIGN.value
            workspace.updated_at = utcnow()

    update_epitope_selection(
        workspace_id,
        EpitopeSelectionUpdate(
            peptide_ids=["ep01", "ep05", "ep07", "ep15", "ep17", "ep32", "ep33"]
        ),
    )

    update_construct_options(
        workspace_id,
        ConstructDesignUpdate.model_validate(
            {"lambda": 0.65, "signal": True, "mitd": True, "confirmed": True}
        ),
    )

    update_construct_output(
        workspace_id,
        ConstructOutputAction(action="select_cmo", cmo_id="trilink"),
    )

    print(workspace_id)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # pragma: no cover
        print(f"seed failed: {exc}", file=sys.stderr)
        raise
