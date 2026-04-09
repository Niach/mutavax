from app.services.workspace_store import run_batch_normalization
from app.tasks.celery_app import celery_app


@celery_app.task(bind=True, name="ingestion.normalize_batch")
def normalize_ingestion_batch(self, batch_id: str):
    self.update_state(state="STARTED", meta={"batch_id": batch_id})
    workspace = run_batch_normalization(batch_id)
    return {
        "batch_id": batch_id,
        "workspace_id": workspace.id,
        "ingestion_status": workspace.ingestion.status,
    }
