from fastapi import APIRouter, HTTPException, status
from fastapi.responses import FileResponse

from app.models.schemas import (
    ActiveStageUpdateRequest,
    AlignmentStageSummaryResponse,
    IngestionLanePreviewResponse,
    LocalFileRegistrationRequest,
    SampleLane,
    VariantCallingStageSummaryResponse,
    WorkspaceAnalysisProfileUpdateRequest,
    WorkspaceCreateRequest,
    WorkspaceResponse,
)
from app.services.alignment import (
    AlignmentArtifactNotFoundError,
    cancel_alignment_run,
    create_alignment_run,
    load_alignment_artifact_download,
    load_alignment_stage_summary,
    pause_alignment_run,
    rerun_alignment,
    resume_alignment_run,
)
from app.services.variant_calling import (
    VariantCallingArtifactNotFoundError,
    create_variant_calling_run,
    load_variant_calling_artifact_download,
    load_variant_calling_stage_summary,
    rerun_variant_calling,
)
from app.services.tool_preflight import (
    ALIGNMENT_TOOLS,
    InsufficientMemoryError,
    MissingToolError,
    ingestion_tools_for_paths,
    verify_tools,
)
from app.services.workspace_store import (
    create_workspace,
    LanePreviewUnavailableError,
    list_workspaces,
    load_ingestion_lane_preview,
    load_workspace,
    register_local_lane_files,
    reset_workspace_ingestion,
    update_workspace_analysis_profile,
    update_workspace_active_stage,
)

router = APIRouter()


def unexpected_workspace_error(action: str, error: Exception) -> HTTPException:
    return HTTPException(status_code=500, detail=f"{action} failed: {error}")


def missing_tools_error(error: MissingToolError) -> HTTPException:
    return HTTPException(status_code=503, detail=error.to_payload())


def insufficient_memory_error(error: InsufficientMemoryError) -> HTTPException:
    return HTTPException(status_code=503, detail=error.to_payload())


@router.get("/", response_model=list[WorkspaceResponse])
async def get_workspaces():
    return list_workspaces()


@router.post(
    "/", response_model=WorkspaceResponse, status_code=status.HTTP_201_CREATED
)
async def create_workspace_route(request: WorkspaceCreateRequest):
    try:
        return create_workspace(request)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except Exception as error:
        raise unexpected_workspace_error("Workspace creation", error) from error


@router.get("/{workspace_id}", response_model=WorkspaceResponse)
async def get_workspace(workspace_id: str):
    try:
        return load_workspace(workspace_id)
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except Exception as error:
        raise unexpected_workspace_error("Workspace load", error) from error


@router.patch("/{workspace_id}/analysis-profile", response_model=WorkspaceResponse)
async def update_analysis_profile(
    workspace_id: str,
    request: WorkspaceAnalysisProfileUpdateRequest,
):
    try:
        return update_workspace_analysis_profile(workspace_id, request)
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except Exception as error:
        raise unexpected_workspace_error("Analysis profile update", error) from error


@router.get(
    "/{workspace_id}/alignment",
    response_model=AlignmentStageSummaryResponse,
)
async def get_alignment_stage_summary(workspace_id: str):
    try:
        return load_alignment_stage_summary(workspace_id)
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except Exception as error:
        raise unexpected_workspace_error("Alignment summary load", error) from error


@router.post(
    "/{workspace_id}/alignment/run",
    response_model=AlignmentStageSummaryResponse,
)
async def run_alignment_stage(workspace_id: str):
    try:
        verify_tools(ALIGNMENT_TOOLS)
        return create_alignment_run(workspace_id)
    except MissingToolError as error:
        raise missing_tools_error(error) from error
    except InsufficientMemoryError as error:
        raise insufficient_memory_error(error) from error
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except Exception as error:
        raise unexpected_workspace_error("Alignment run", error) from error


@router.post(
    "/{workspace_id}/alignment/rerun",
    response_model=AlignmentStageSummaryResponse,
)
async def rerun_alignment_stage(workspace_id: str):
    try:
        verify_tools(ALIGNMENT_TOOLS)
        return rerun_alignment(workspace_id)
    except MissingToolError as error:
        raise missing_tools_error(error) from error
    except InsufficientMemoryError as error:
        raise insufficient_memory_error(error) from error
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except Exception as error:
        raise unexpected_workspace_error("Alignment rerun", error) from error


@router.post(
    "/{workspace_id}/alignment/runs/{run_id}/cancel",
    response_model=AlignmentStageSummaryResponse,
)
async def cancel_alignment_run_route(workspace_id: str, run_id: str):
    try:
        return cancel_alignment_run(workspace_id, run_id)
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except Exception as error:
        raise unexpected_workspace_error("Alignment cancel", error) from error


@router.post(
    "/{workspace_id}/alignment/runs/{run_id}/pause",
    response_model=AlignmentStageSummaryResponse,
)
async def pause_alignment_run_route(workspace_id: str, run_id: str):
    try:
        return pause_alignment_run(workspace_id, run_id)
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except Exception as error:
        raise unexpected_workspace_error("Alignment pause", error) from error


@router.post(
    "/{workspace_id}/alignment/runs/{run_id}/resume",
    response_model=AlignmentStageSummaryResponse,
)
async def resume_alignment_run_route(workspace_id: str, run_id: str):
    try:
        return resume_alignment_run(workspace_id, run_id)
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except Exception as error:
        raise unexpected_workspace_error("Alignment resume", error) from error


@router.get("/{workspace_id}/alignment/artifacts/{artifact_id}/download")
async def download_alignment_artifact(
    workspace_id: str,
    artifact_id: str,
):
    try:
        artifact = load_alignment_artifact_download(workspace_id, artifact_id)
        return FileResponse(
            path=artifact.local_path,
            media_type=artifact.content_type or "application/octet-stream",
            filename=artifact.filename,
        )
    except AlignmentArtifactNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.get(
    "/{workspace_id}/variant-calling",
    response_model=VariantCallingStageSummaryResponse,
)
async def get_variant_calling_stage_summary(workspace_id: str):
    try:
        return load_variant_calling_stage_summary(workspace_id)
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except Exception as error:
        raise unexpected_workspace_error("Variant calling summary load", error) from error


@router.post(
    "/{workspace_id}/variant-calling/run",
    response_model=VariantCallingStageSummaryResponse,
)
async def run_variant_calling_stage(workspace_id: str):
    try:
        return create_variant_calling_run(workspace_id)
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except Exception as error:
        raise unexpected_workspace_error("Variant calling run", error) from error


@router.post(
    "/{workspace_id}/variant-calling/rerun",
    response_model=VariantCallingStageSummaryResponse,
)
async def rerun_variant_calling_stage(workspace_id: str):
    try:
        return rerun_variant_calling(workspace_id)
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except Exception as error:
        raise unexpected_workspace_error("Variant calling rerun", error) from error


@router.get("/{workspace_id}/variant-calling/artifacts/{artifact_id}/download")
async def download_variant_calling_artifact(
    workspace_id: str,
    artifact_id: str,
):
    try:
        artifact = load_variant_calling_artifact_download(workspace_id, artifact_id)
        return FileResponse(
            path=artifact.local_path,
            media_type=artifact.content_type or "application/octet-stream",
            filename=artifact.filename,
        )
    except VariantCallingArtifactNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except Exception as error:
        raise unexpected_workspace_error("Alignment artifact download", error) from error


@router.get(
    "/{workspace_id}/ingestion/preview/{sample_lane}",
    response_model=IngestionLanePreviewResponse,
)
async def get_ingestion_lane_preview(
    workspace_id: str,
    sample_lane: SampleLane,
):
    try:
        return load_ingestion_lane_preview(workspace_id, sample_lane)
    except LanePreviewUnavailableError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except Exception as error:
        raise unexpected_workspace_error("Sequence preview load", error) from error


@router.post(
    "/{workspace_id}/ingestion/local-files",
    response_model=WorkspaceResponse,
)
async def register_local_files_route(
    workspace_id: str,
    request: LocalFileRegistrationRequest,
):
    try:
        verify_tools(ingestion_tools_for_paths(request.paths))
        return register_local_lane_files(workspace_id, request)
    except MissingToolError as error:
        raise missing_tools_error(error) from error
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except Exception as error:
        raise unexpected_workspace_error("Local file registration", error) from error


@router.delete(
    "/{workspace_id}/ingestion",
    response_model=WorkspaceResponse,
)
async def reset_workspace_ingestion_route(workspace_id: str):
    try:
        return reset_workspace_ingestion(workspace_id)
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except Exception as error:
        raise unexpected_workspace_error("Workspace ingestion reset", error) from error


@router.patch("/{workspace_id}/active-stage", response_model=WorkspaceResponse)
async def update_active_stage(
    workspace_id: str, request: ActiveStageUpdateRequest
):
    try:
        return update_workspace_active_stage(workspace_id, request)
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except Exception as error:
        raise unexpected_workspace_error("Active stage update", error) from error
