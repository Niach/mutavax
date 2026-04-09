import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException

from app.models.schemas import (
    JobResponse,
    JobStatus,
    JobSubmitRequest,
    PipelineStageId,
)
from app.services.workspace_store import load_workspace

router = APIRouter()

# In-memory job store (replace with database later)
jobs: dict[str, JobResponse] = {}


@router.post("/submit", response_model=JobResponse)
async def submit_job(request: JobSubmitRequest):
    if request.workspace_id is not None:
        try:
            load_workspace(request.workspace_id)
        except FileNotFoundError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

    timestamp = datetime.now(timezone.utc).isoformat()
    job_id = str(uuid.uuid4())
    job = JobResponse(
        id=job_id,
        workspace_id=request.workspace_id,
        stage_id=request.stage_id,
        status=JobStatus.PENDING,
        progress=0.0,
        created_at=timestamp,
        updated_at=timestamp,
    )
    jobs[job_id] = job

    # TODO: dispatch to Celery task queue based on stage_id
    # For now, just return the pending job
    return job


@router.get("/jobs/{job_id}", response_model=JobResponse)
async def get_job(job_id: str):
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    return jobs[job_id]


@router.get("/jobs")
async def list_jobs(
    stage_id=None, workspace_id=None
):
    if stage_id:
        return [
            job
            for job in jobs.values()
            if job.stage_id == stage_id
            and (workspace_id is None or job.workspace_id == workspace_id)
        ]
    if workspace_id:
        return [job for job in jobs.values() if job.workspace_id == workspace_id]
    return list(jobs.values())


@router.get("/results/{stage_id}/{workspace_id}")
async def get_stage_results(stage_id: PipelineStageId, workspace_id: str):
    # TODO: retrieve actual results from storage
    return {
        "stage_id": stage_id,
        "workspace_id": workspace_id,
        "results": None,
        "message": "Results storage not yet implemented",
    }


@router.get("/stages")
async def list_stages():
    return [
        {"id": s.value, "name": s.name.replace("_", " ").title()}
        for s in PipelineStageId
    ]
