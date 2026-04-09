import json
from datetime import datetime
from pathlib import Path

from sqlalchemy import select

from app.db import session_scope
from app.models.records import WorkspaceRecord
from app.models.schemas import PipelineStageId, WorkspaceSpecies
from app.services.workspace_store import utc_now


def import_legacy_workspace_manifests(root: Path) -> int:
    if not root.exists():
        return 0

    imported = 0
    for manifest in sorted(root.glob("*/workspace.json")):
        payload = json.loads(manifest.read_text())
        workspace_id = payload.get("id")
        if not workspace_id:
            continue

        with session_scope() as session:
            existing = session.scalar(
                select(WorkspaceRecord).where(WorkspaceRecord.id == workspace_id)
            )
            if existing:
                continue

            created_at = payload.get("created_at")
            updated_at = payload.get("updated_at") or created_at
            timestamp = utc_now()
            session.add(
                WorkspaceRecord(
                    id=workspace_id,
                    display_name=payload.get("display_name") or "Imported workspace",
                    species=payload.get("species") or WorkspaceSpecies.DOG.value,
                    active_stage=payload.get("active_stage") or PipelineStageId.INGESTION.value,
                    created_at=timestamp if created_at is None else datetime.fromisoformat(created_at),
                    updated_at=timestamp if updated_at is None else datetime.fromisoformat(updated_at),
                )
            )
            imported += 1

    return imported
