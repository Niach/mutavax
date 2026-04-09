from fastapi import APIRouter, File, HTTPException, UploadFile, status

from app.models.schemas import (
    ActiveStageUpdateRequest,
    WorkspaceCreateRequest,
    WorkspaceResponse,
)
from app.services.workspace_store import (
    create_workspace,
    list_workspaces,
    load_workspace,
    update_workspace_active_stage,
    upload_workspace_files,
)

router = APIRouter()


@router.get("/", response_model=list[WorkspaceResponse])
async def get_workspaces():
    return list_workspaces()


@router.post(
    "/", response_model=WorkspaceResponse, status_code=status.HTTP_201_CREATED
)
async def create_workspace_route(request: WorkspaceCreateRequest):
    return create_workspace(request)


@router.get("/{workspace_id}", response_model=WorkspaceResponse)
async def get_workspace(workspace_id: str):
    try:
        return load_workspace(workspace_id)
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.post("/{workspace_id}/files", response_model=WorkspaceResponse)
async def upload_files(workspace_id: str, files: list[UploadFile] = File(...)):
    try:
        return upload_workspace_files(workspace_id, files)
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.patch("/{workspace_id}/active-stage", response_model=WorkspaceResponse)
async def update_active_stage(
    workspace_id: str, request: ActiveStageUpdateRequest
):
    try:
        return update_workspace_active_stage(workspace_id, request)
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
